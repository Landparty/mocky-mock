---
type: Module
title: Docker Runtime
description: mockymock-cobc container lifecycle, docker exec-based compile/run, the Docker sandbox model, and the opt-in native backend that runs a bundled GnuCOBOL tree instead.
tags: [runtime, docker, gnucobol, native]
timestamp: 2026-10-25T00:00:00Z
---

# Overview

mockymock compiles and executes in Docker by default (decision
2026-07-04, `docs/2026-07-04-docker-toolchain-design.md`): `cobc` and every
compiled test binary live and execute inside a single long-lived container,
`mockymock-cobc`. If the daemon is unreachable, the CLI fails loudly and
exits 1.

The one exception is the **native backend** (2026-10-25, see
**Native toolchain** below): when `MOCKYMOCK_GNUCOBOL_HOME` names a
self-contained GnuCOBOL tree (the VS Code extension bundles one), the same
compile/run/coverage/debug steps run on the host from that tree. Commands
never import a backend directly: they call `runtime/toolchain.py`'s
`active()` and use the module it returns.

```
mockymock setup / mockymock run
   │
   ├─ ensure_toolchain()                 docker_toolchain.py
   │     docker daemon unreachable ───▶ DockerNotAvailableError (exit 1)
   │     image "mockymock-gnucobol:<hash>" missing ───▶ docker build -t ... runtime/docker/
   │     container "mockymock-cobc" missing ───▶ docker run -d --name mockymock-cobc
   │                                              -v ~/.mockymock/work:/work ... sleep infinity
   │     container built from a stale image tag ───▶ docker rm -f + recreate
   │     container stopped ───▶ docker start mockymock-cobc
   │
   ├─ sandbox_dir_maybe_kept(root=WORK_ROOT, keep=...)   ~/.mockymock/work/mockymock-XXXX/
   │     instrumented .cbl written with newline="\n" (cobc runs Linux-side)
   │
   ├─ compile_source()   docker exec mockymock-cobc cobc -free -std=mvs -fno-arithmetic-osvs -x /work/<sb>/PROG.cbl -o /work/<sb>/PROG
   │
   └─ run_binary()       docker exec -w /work/<sb> mockymock-cobc timeout -k 5 30 /work/<sb>/PROG
                            stdout parsed by report/results.py, unchanged
```

# Why everything moved into the container

Before 2026-07-04 mockymock shelled out to a host-installed `cobc` and ran the
compiled binary directly on the host. Two chronic Windows failures forced the
move (`docs/2026-07-04-docker-toolchain-design.md` §1):

1. **`COB_CONFIG_DIR` propagation** — Chocolatey-installed GnuCOBOL needs a
   user-scope env var; any shell that doesn't inherit it fails every compile
   with `configuration error: default.conf: No such file or directory`.
2. **Smart App Control / WDAC flake** — Windows intermittently refused to
   execute freshly compiled unsigned binaries (`WinError 4551`), failing
   roughly 1 in 3 full integration runs.

Both disappear once compilation *and* execution happen inside a Linux
container: the image bakes in a correctly configured `cobc`, and the binary
never touches the host's application-control policy. `runtime/gnucobol_bootstrap.py`
(choco/brew/apt install logic) was deleted outright, not kept as a fallback.

A **persistent container + `docker exec`** was chosen over a fresh `docker run`
per compile/run: `docker exec` costs ~100-300 ms per call, whereas a per-call
`docker run` costs ~1 s under Docker Desktop — a 19-test integration sweep
would otherwise spin up ~40 containers.

# Container lifecycle

`ensure_toolchain(force_rebuild: bool = False)` in
`mockymock/runtime/docker_toolchain.py` is idempotent and is called at the
start of **both** `mockymock setup` and every `mockymock run` (so a
container that died between runs is restarted automatically; `setup` is
therefore optional). `force_rebuild=True` is passed only by `mockymock
setup --rebuild` — see **Forced rebuild** below. Nothing else in the CLI
mutates the toolchain: `dashboard` and `doctor` go through
`runtime/status.py`'s read-only `probe()` instead (see
[dashboard](dashboard.md)).

| Step | Check | Action if missing/stopped/stale |
|------|-------|---------------------------------|
| 1. Daemon | `docker info` (30s timeout) | non-zero exit -> `DockerNotAvailableError` with `_DAEMON_HINT` |
| 2. Image | `docker image inspect <IMAGE>` | build via `docker build -t <IMAGE> <package>/runtime/docker/` |
| 3. Container | one `docker inspect -f "{{.State.Running}} {{.Config.Image}}" mockymock-cobc` yields both running state and creating image | absent -> `_create_container()` (`docker run -d --name mockymock-cobc <hardening flags> -v <WORK_ROOT>:/work <IMAGE> sleep infinity`); **created from a different image tag** -> `docker rm -f` then `_create_container()` (a stale container would otherwise defeat the content-hash tag forever); present-but-stopped -> `docker start mockymock-cobc` |

`<hardening flags>` is `_HARDENING_FLAGS` — see the **Threat model** section
below. `_image_tag()` hashes the Dockerfile content *and* `_HARDENING_FLAGS`
together (fixed 2026-08-10, audit finding F2 — previously only the Dockerfile
fed `IMAGE`, so an edit to the flags alone left a running container's
hardening silently stale): editing either one changes `IMAGE`, so step 3 sees
the old container's image `!= IMAGE` and rm+recreates it with the current
flags. No manual "bump the Dockerfile" step is needed for a flags-only change.

## Forced rebuild (`setup --rebuild`)

`force_rebuild=True` makes step 2 run `docker build` unconditionally, and
then — since 2026-09-15 — also `docker rm -f <CONTAINER>` before step 3.
The removal is not belt-and-braces: `docker build -t IMAGE` re-tags the
**same content-hash tag** onto the newly built image ID, so step 3's
stale-image check (which compares tag strings, not image IDs) sees no
difference and keeps the container created from the *old* image. Without
the removal, `--rebuild` rebuilt the image and every subsequent compile
still ran in exactly the toolchain the user asked to replace. An `rm -f`
that fails for any reason other than *"no such container"* raises
`DockerNotAvailableError` naming both the image and the container, rather
than silently continuing into the same stale state.

Note the asymmetry with the ordinary stale path below: there the tag
really did change, so comparing tags is sufficient; only a forced rebuild
can produce a new image under an unchanged tag.

`_create_container()` also absorbs the concurrent-first-run race: if
`docker run --name` fails with *"name already in use"* (another invocation
won the race between our inspect and run), it re-inspects and adopts the
winner's container — starting it if it exists but is stopped — instead of
raising. Any other `docker run` failure still raises
`DockerNotAvailableError`.

The stale-image path (step 3's `docker rm -f` + recreate) has the mirror
-image race: two invocations can both see the same stale tag and both try
to remove it. The winner's `rm -f` succeeds; the loser's then fails
against an already-gone container with stderr containing *"No such
container"* — not a real failure, just evidence the winner got there
first. Fixed 2026-08-10 (audit finding F9) to fall through to
`_create_container()` in that case instead of raising
`DockerNotAvailableError`, same treatment as the "already in use" race
above, just on the removal side of the sequence rather than the creation
side.

Constants (asserted by unit tests, must not drift in shape):

| Name | Value |
|------|-------|
| `IMAGE` | `mockymock-gnucobol:<8-char sha256 of docker/Dockerfile content + _HARDENING_FLAGS>` — computed by `_image_tag()` at import, so editing *either* the Dockerfile *or* the hardening flags changes the tag, the image-inspect misses, a rebuild happens, **and** step 3 recreates the container from the new image |
| `CONTAINER` | `mockymock-cobc` |
| `WORK_ROOT` | `Path.home() / ".mockymock" / "work"` |

The `docker build` context is resolved as `Path(__file__).resolve().parent /
"docker"` (`mockymock/runtime/docker/`, bundled *inside* the package, not
repo-root `docker/`) so the build context ships in the wheel and is found
under any install mode — editable sibling checkout or a real `uv tool
install` with no repo checkout present at all. Prior to 2026-07-09 the
Dockerfile lived at repo-root `docker/` and was resolved via
`parents[2]`, which broke `uv tool install` (FileNotFoundError on
`mockymock setup`) because setuptools never packaged anything outside
`mockymock/`.

`_docker(*args, timeout=600)` is the sole subprocess wrapper: any `OSError` or
`subprocess.TimeoutExpired` from the docker CLI itself (not the workload inside
it) becomes `DockerNotAvailableError` with the actionable `_DAEMON_HINT`
message ("Start Docker Desktop ... and re-run").

# Image

`mockymock/runtime/docker/Dockerfile`: `FROM debian:trixie-slim`, `apt-get install -y
--no-install-recommends gnucobol` (GnuCOBOL 3.2, same major version as the
former local toolchain), `WORKDIR /work`. No entrypoint — the container is
started with `sleep infinity` and driven entirely via `docker exec`.

# Threat model

mockymock compiles and **runs untrusted COBOL**. A hostile `.cbl` — or a
`MOCK` body, which the splicer injects into the program *verbatim* — can reach
`CALL "SYSTEM"` (GnuCOBOL supports it) and execute arbitrary shell inside the
container. Docker gives no host escape here, but an unhardened container still
lets that shell exfiltrate data over the network, fork-bomb, exhaust host
memory, or tamper with other concurrent runs' sandboxes under the shared
`/work` mount.

`_create_container()` therefore launches with `_HARDENING_FLAGS`
(`mockymock/runtime/docker_toolchain.py`):

| Flag | Purpose |
|------|---------|
| `--network none` | no outbound network — blocks exfiltration and callbacks |
| `--pids-limit <PIDS_LIMIT>` (512) | fork-bomb ceiling |
| `--memory <MEMORY_LIMIT>` / `--memory-swap <MEMORY_LIMIT>` (1g / 1g) | memory ceiling; swap pinned to the same value so the limit actually bites |
| `--cap-drop ALL` + `--cap-add DAC_OVERRIDE` | drop every Linux capability except the one root needs to read/write the bind mount (see below) |
| `--security-opt no-new-privileges` | setuid binaries cannot escalate |

`DAC_OVERRIDE` is added back deliberately: sandboxes are created host-side by
`tempfile.mkdtemp` (mode `0700`, owned by the host uid) and bind-mounted in, so
container-root reads the `.cbl` and writes the compiled binary through the mount
purely via `CAP_DAC_OVERRIDE` (root's bypass of file-permission bits).
`--cap-drop ALL` alone strips it and `cobc` fails with `Permission denied` on
the host-owned source. `DAC_OVERRIDE` only bypasses DAC checks on the
already-isolated `/work` mount; the caps that matter for container escape
(`SYS_ADMIN`, `NET_RAW`, `SETUID`/`SETGID`, `MKNOD`, …) stay dropped.

Image **build** still has network (it's a separate `docker build`, not the
container run); only the long-lived container is network-isolated, which is
fine because `cobc` and the compiled binaries never need the network.

**Why still root, not a non-root `USER`.** The bind-mounted work root is owned
by the host user, whose uid is not portable across machines and is absent on
the Windows Docker Desktop host mockymock explicitly targets. A fixed non-root
uid in the image would fail to write the compiled binary into `/work` on hosts
where the uids don't line up. Root is instead *neutralized* by the flags above
(no capabilities, no privilege escalation, no network, bounded pids/memory).

**Residual risk.** Within a single run the workload can still consume up to the
pids/memory ceilings and read/write any sandbox under `/work` (all runs share
one mount). Per-run mount isolation and a non-root uid strategy that survives
the Windows bind mount are the remaining hardening steps, not yet done.

Tuning: `PIDS_LIMIT` and `MEMORY_LIMIT` are module-level constants. Changing
either, or any of `_HARDENING_FLAGS`, changes `IMAGE` automatically
(`_image_tag()` hashes the flags alongside the Dockerfile content — see
above) and step 3 rm+recreates the container on the next `ensure_toolchain()`
call; no manual Dockerfile edit is needed to force that.

# Host <-> container filesystem boundary

The bind mount `WORK_ROOT (~/.mockymock/work) -> /work` is established **once**,
at container creation. This is the only path the container can see — it is not
re-mounted per run. Consequences:

- Every sandbox must be created under `WORK_ROOT` via
  `sandbox_dir(root=docker_toolchain.WORK_ROOT)` (see `runtime/sandbox.py`
  and [splicer](splicer.md) for how the instrumented `.cbl` is produced before
  being written into the sandbox). A temp dir created elsewhere on the host
  (e.g. plain `tempfile.mkdtemp()` with no root) would be invisible to
  `docker exec` and every compile/run would fail.
- `to_container_path(host_path, work_root=WORK_ROOT) -> str` is the one pure,
  Docker-free function that maps a host path to its container path
  (`work_root/X/Y` -> `/work/X/Y`, POSIX separators via `Path.as_posix()`
  regardless of host OS). Paths outside `work_root` raise `ValueError` — this
  is treated as a programming error, not a runtime condition to recover from.
- Instrumented COBOL source must be written with `newline="\n"` — `cobc` runs
  Linux-side inside the container and CRLF line endings from a Windows host
  are not translated across the bind mount.
- Compiled binaries are **Linux ELF** with no suffix (`source_path.with_suffix("")`).
  They are transient test artifacts that only ever execute inside the
  container; the old `platform.system()`-based `.exe` suffix logic is gone
  entirely.

# Compile and run

`compile_source(source_path: Path) -> CompileResult`:
- Maps source and binary paths to container paths via `to_container_path`.
- Runs `docker exec mockymock-cobc timeout -k 5 585 cobc -free -std=mvs -fno-arithmetic-osvs -x <container_source> -o <container_binary>`
  (fixed 2026-08-10, audit finding F1 — previously unwrapped: a `cobc`
  invocation that hung inside the shared container had no container-side
  bound at all and outlived even the host's own 600s `subprocess.run`
  timeout, leaking an orphaned process into a container every other run
  also uses). The container-side ceiling (585s) stays under the host-side
  `subprocess.run(timeout=600)` guard, same `-k 5` SIGKILL-escalation
  pattern as `run_binary` below.
- `-std=mvs` is required because GnuCOBOL's default dialect doesn't
  implement the IBM compiler-directing statements (`EJECT`,
  `SKIP1`/`SKIP2`/`SKIP3`) that real z/OS mainframe sources use between
  paragraphs/sections — those otherwise fail to compile even though
  cobol-parser itself already treats them as no-ops.
- `-fno-arithmetic-osvs` undoes one setting `-std=mvs` brings with it.
  GnuCOBOL 3.2's OS/VS intermediate-result emulation is wrong:
  `COMPUTE X = P * (1 - D)` (and `P * (1 + D)`, `(1 - D) * P`,
  `P * (ONE - D)`) gives 0 whenever `D` is zero. Found 2026-10-25 from
  PREMCALC's 18 false failures; a differential run of 2,283 random `+ - *`
  COMPUTEs had 393 wrong with the setting on and none with it off, and
  divisions came out the same either way. Enterprise COBOL does not use
  the OS/VS rules, so nothing is lost. Pinned by
  `tests/integration/test_osvs_arithmetic.py`.
- Success requires **both** `returncode == 0` **and** `binary_path.exists()`
  on the host side — a zero exit with no binary materializing (e.g. a stale
  mount) is treated as failure, not a phantom success.
- `OSError` (docker CLI vanished mid-call) and `subprocess.TimeoutExpired`
  (600s) are both caught and turned into a failed `CompileResult` with an
  explanatory `stderr`, never an unhandled exception.

`run_gcov(source_path: Path) -> GcovResult` is wrapped the same way (`timeout
-k 5 50`, fixed alongside F1 for the identical orphaned-process risk).

`run_binary(binary_path: Path, timeout_seconds: int = 30) -> ExecutionResult`:
- Runs `docker exec -w <container_dir> mockymock-cobc timeout -k 5 <timeout_seconds> <container_binary>`
  — working directory is set to the binary's own sandbox dir inside the
  container. `-k 5` escalates to SIGKILL five seconds after the SIGTERM,
  so a binary that ignores SIGTERM cannot keep burning CPU as an orphan
  inside the persistent container.
- Drops libxml2's own `Warning: program compiled against libxml N using
  older M` line from the binary's stderr (`_LIBXML_VERSION_WARNING_RE`):
  the Debian image's GnuCOBOL build prints it on every run and it is
  harmless (2026-10-24). `compile_source` drops it from cobc's stderr
  too (2026-10-25).
- **Output is captured as bytes**, then decoded UTF-8 with
  `errors="replace"` and no newline translation (2026-09-30, bug hunt round
  11). `text=True` decoded strictly, so one DISPLAY of a non-UTF-8 byte
  (HIGH-VALUES, a COMP field) raised `UnicodeDecodeError` out of the whole
  run, and its universal newlines turned a lone CR inside a DISPLAYed value
  into LF, splitting a `__MOCKYMOCK__` marker before `parse_stdout`'s
  LF-only split saw it.
- **Two layered timeouts**: coreutils `timeout` enforces the limit
  container-side and exits `124` on expiry (`TIMEOUT_EXIT_CODE`, defined in
  `runtime/executor.py` and shared with the report layer's `parse_stdout`);
  the host-side `subprocess.run(..., timeout=timeout_seconds + 15)` is a wider
  belt-and-suspenders guard against `docker exec` itself (not the workload)
  hanging — e.g. a wedged Docker daemon.
- On container-side timeout, `stderr` is annotated with a domain-specific
  hint: *"a mocked CALL may have removed a loop's terminating condition,
  producing an infinite loop"* — this is the most common real-world cause in
  this codebase (a mock body that never sets the EOF flag a `PERFORM UNTIL`
  depends on). The CLI's `run` prints `executed.stderr` (so this hint
  actually reaches users) and frames exit 124 as a timeout rather than a
  generic crash — see [cli](cli.md).
- On host-side hang (`subprocess.TimeoutExpired`), exit code is coerced to the
  same `TIMEOUT_EXIT_CODE = 124` so downstream consumers never need to
  distinguish "container said timeout" from "docker exec itself hung".
- On docker CLI `OSError`, exit code is `NOT_FOUND_EXIT_CODE = 127`.
- `_coerce_output` in `executor.py` normalizes `subprocess.TimeoutExpired`'s
  `.stdout`/`.stderr` (which can be `None` or `bytes`) to `str`, so
  `ExecutionResult` fields stay `str` as documented and `report/results.py`'s
  `parse_stdout` never receives `None`.

`compile_source(..., extra_sources=())` (2026-11-01, USE REAL CALL):
further sources in the same sandbox, compiled into the same executable
(`cobc -x main.cbl real_X.cbl ...`) by both backends; `run` passes the
instrumented real programs only when a suite has some, so a monkeypatched
`compile_source` without the parameter keeps working.

# What compiler.py / executor.py still hold

Both modules were reduced to shared types only — the local-subprocess
implementations that used to live there were deleted wholesale, not adapted:

| Module | Contents kept |
|--------|---------------|
| `runtime/compiler.py` | `CompileResult` dataclass: `success: bool`, `binary_path: Path \| None`, `stdout: str`, `stderr: str` |
| `runtime/executor.py` | `ExecutionResult` dataclass, `TIMEOUT_EXIT_CODE = 124`, `NOT_FOUND_EXIT_CODE = 127`, `_coerce_output()` |
| `runtime/status.py` | The read-only counterpart: `probe() -> ToolchainStatus` (four `Check` records — `daemon`, `image`, `container`, `cobc`) mirroring the lifecycle table above using pure reads only. Documented in [dashboard](dashboard.md), not here, because both its consumers (`dashboard`, `doctor`) live there. |

These shapes are a stable contract consumed by `cli/main.py` and
`report/results.py` — the Docker rewrite deliberately left them unchanged so
nothing downstream of compile/run needed to change.

# CLI mapping

| Command | Behavior |
|---------|----------|
| `mockymock setup [--rebuild]` | Calls `ensure_toolchain(force_rebuild=args.rebuild)` then `cobc_version()` (first line of in-container `cobc --version`). Prints `container mockymock-cobc ready (<version>)` and exits 0, or prints the `DockerNotAvailableError` message and exits 1. Optional — `run` brings the container up on its own. `--rebuild` forces a fresh image build *and* container recreation (see **Forced rebuild** above). |
| `mockymock doctor` / `mockymock dashboard` | Never call `ensure_toolchain()` at all — they report what it *would* find, via `runtime/status.py`'s `probe()`. See [dashboard](dashboard.md). |
| `mockymock debug` | Adds `start_gdb_session(binary_path)`: a long-lived `docker exec -i ... gdb` process the DAP adapter drives over stdin/stdout. Same container, same `/work` mount; see [cli](cli.md)'s `debug` section. |
| `mockymock run <program.cbl> --cut <file.cut>` | Validates that the program and .cut paths exist (cheap, clean per-file error), then calls `ensure_toolchain()` before any parsing or sandbox creation — a down daemon fails fast with just the actionable message, no wasted parse work, and a typo'd path never pays for an image build. Then creates a sandbox under `WORK_ROOT`, writes the instrumented source with `newline="\n"`, and calls `docker_toolchain.compile_source()` / `docker_toolchain.run_binary()`. The binary's stderr and exit code are surfaced: nonzero exit fails the run even if all case markers passed. |

`cobc_version()` itself runs `docker exec mockymock-cobc cobc --version` and
raises `DockerNotAvailableError` if that exec fails (e.g. container up but
`cobc` broken inside the image).

# Sandbox model

`runtime/sandbox.py` has two context managers. `sandbox_dir(root=None)`
yields a temp directory removed on exit (`shutil.rmtree(...,
ignore_errors=True)`). `sandbox_dir_maybe_kept(root, keep)` is what the
CLI's `run` actually uses: with `keep=True` the directory is **left on
disk** — `--keep-sandbox` keeps it unconditionally (and prints its path);
`--verbose` keeps it through the context so the instrumented-source path
printed on compile failure still exists, but `_cmd_run` removes it
afterwards when `--keep-sandbox` was not also given. A compile failure's
own `return 1` deliberately skips that removal (the path it just printed
must still resolve — that survival is itself covered by
`tests/integration/test_cli.py`). What used to leak permanently was the
*next* phase: `run_binary`/`run_gcov` raising, which prints no path
pointing at the sandbox at all. That phase's removal now lives in its own
`try/finally` (fixed 2026-08-10, audit finding F10) instead of a bare
statement after the `with` block, which only ran on that phase's normal
completion.
So sandboxes are *not* always removed on exit. Their only Docker-specific
feature:
when `root` is given, the temp dir is created *under* that directory (creating
`root` first if missing) via `tempfile.mkdtemp(prefix="mockymock-", dir=root)`.
The Docker toolchain always calls it as `sandbox_dir(root=docker_toolchain.WORK_ROOT)`
— this is what makes the sandbox visible to `docker exec` at all; a sandbox
created with no `root` (system temp) would compile/run against a path the
container has never heard of and `to_container_path` would reject it.

# Gotchas

**Silent phantom-success trap:** `compile_source` treats
`returncode == 0 and binary_path.exists()` as the success condition, not
returncode alone. This exists specifically to guard against a stale or
half-mounted `/work` making `cobc` appear to succeed on the container side
while the host never sees the binary.

**CRLF corrupts compiles silently on Windows:** any code path that writes the
instrumented `.cbl` without `newline="\n"` will produce a source file with CRLF
line endings; GnuCOBOL inside the Linux container does not normalize these,
and `cobc -free` can misparse or fail in ways that look like ordinary syntax
errors rather than an encoding bug. Both the CLI's `_cmd_run` and the
integration fixtures write source with explicit `newline="\n"` for this reason.

**Two timeouts, same exit code:** a genuine in-container infinite loop and a
wedged `docker exec` call both surface as `exit_code == 124` to callers. The
`stderr` text is the only way to distinguish "your mocked CALL created an
infinite loop" from "the docker daemon may be wedged" — don't rely on exit
code alone when debugging a timeout report.

# See Also

- [splicer](splicer.md) — produces the instrumented `.cbl` source that gets
  written into the Docker sandbox and compiled.
- [cli](cli.md) — `setup`/`run` command wiring that drives `ensure_toolchain`,
  `compile_source`, and `run_binary`.
- [coverage](coverage.md) — `compile_source(..., coverage=True)` and `run_gcov`
  build on this module's existing Docker toolchain.
- [dashboard](dashboard.md) — `runtime/status.py`'s read-only `probe()`, the
  one place that inspects this toolchain without mutating it.


# Native toolchain

`mockymock/runtime/native_toolchain.py` has the same module-level interface
as `docker_toolchain.py` (`ensure_toolchain`, `compile_source`, `run_binary`,
`run_gcov`, `start_gdb_session`, `cobc_version`, `toolchain_failure`,
`container_identity`, `docker_failure_line`, `WORK_ROOT`, `CONTAINER`,
`ToolchainNotAvailableError`). `runtime/toolchain.py` picks one:

| `MOCKYMOCK_TOOLCHAIN` | Backend |
|-----------------------|---------|
| unset / `auto` | native when `MOCKYMOCK_GNUCOBOL_HOME` is set, else Docker |
| `docker` | Docker, even with a GnuCOBOL home set |
| `native` | native (fails loudly if the home is unset or has no `bin/cobc`) |

Any other value raises `ToolchainNotAvailableError`. Both backends raise
that one class (`DockerNotAvailableError` is the same object), so every
`except` keeps working.

**Relocation.** cobc and libcob bake absolute install paths in at build time.
`_env(home)` overrides every one from the tree's location: `COB_CONFIG_DIR`,
`COB_COPY_DIR`, `COB_CFLAGS` (`-I<home>/include`, which carries `gmp.h`),
`COB_LDFLAGS`, `COB_LIBS`, `COB_LIBRARY_PATH`, plus `PATH` and the loader
path (`LD_LIBRARY_PATH` / `DYLD_LIBRARY_PATH`; on Windows `PATH` covers
DLLs). A variable the user already exported wins (`setdefault`).

**C compiler.** cobc translates to C and calls the system compiler. A Linux
or macOS tree does not carry one: `ensure_toolchain` reads `COB_CC` (env,
else `cobc --info`, cached per process) and fails with what to install when
it is not on `PATH`. A Windows tree is expected to be a MinGW build with gcc
in `bin/`. gcov (`MOCKYMOCK_GCOV`, default `gcov`) and gdb are resolved to a
full path on the child environment's `PATH` (`_resolve`) before they are
spawned: Windows' CreateProcess looks a bare name up on the *parent's* `PATH`
and ignores `env=`, so the tree's own `gcov.exe` / `gdb.exe` were not found
(`[WinError 2]`). cobc is always spawned by full path.

**Windows tree.** Verified 2026-10-25 with the build the Chocolatey
`gnucobol` package (3.2.0.20240515) downloads: Arnold Trembley's 32-bit MinGW
GC32-BDB (gcc 9.2, gcov, gdb, BDB, GMP, cJSON; no libxml2). It keeps
`config/`, `copy/`, `extras/` at the root (no `share/`); `_tree_dir` finds
both layouts. Smart App Control did not block compiled binaries there.

**Behaviour kept from the container.** Same cobc flags (`-free -std=mvs`,
`--coverage`, `-ftraceall`, `-g`); the compiler runs from the sandbox
directory (gcov bakes the `.gcno` path in from the compiler's CWD) with
`TMPDIR` pointed at the sandbox; timeouts exit 124 and kill the binary's
whole **process group** (`start_new_session`, `killpg`; `taskkill /T` on
Windows) the way `timeout -k` does in the container; a signal death is
reported as `128 + signal` (so the SIGKILL check in `mutate` still reads 137).
`container_identity()` is always None (no restarts to detect).

**Not kept.** The container's hardening (`_HARDENING_FLAGS`: no network,
pids/memory limits, dropped capabilities) has no equivalent: tests run as the
user on the host. Windows Smart App Control / WDAC, one of the two reasons for
going Docker-only, can still refuse freshly compiled binaries there.

**Coverage numbers move with the host gcc.** gcov's executable-line count
depends on the C compiler version: ACCTPRG's own lines are 97 under the
image's gcc 14 and 110 under gcc 13. The integration tests that pin exact
figures assert them only when the Docker backend is selected
(`tests/integration/_docker.py`'s `pinned_coverage_toolchain()`).

`runtime/status.py`'s `probe()` reports three checks for this backend
(`home`, `cc`, `cobc`; `container` is `"native"`, `image` the home path), so
the dashboard, `doctor` and `init`'s run gate work unchanged.

# Fixed test clock

Every test binary runs with `COB_CURRENT_DATE` set
(`runtime/executor.py` `fixed_clock_env()`, used by both toolchains'
`run_binary`): GnuCOBOL answers `FUNCTION CURRENT-DATE` and `ACCEPT ... FROM
DATE / DAY / TIME / DAY-OF-WEEK` with it. Default `2026/01/15 10:30:00.00`
(`DEFAULT_CURRENT_DATE`); `MOCKYMOCK_CURRENT_DATE` picks another instant,
`real` keeps the wall clock, and a `COB_CURRENT_DATE` already exported wins.
Without it a program that DISPLAYs or writes the date failed every recorded
expectation and every oracle compare.

# Children killed on termination

The native toolchain runs cobc and the test binary in their own sessions
(so a timeout kills the whole tree), which also means a signal to mockymock
never reaches them. `native_toolchain._ACTIVE` tracks the running children;
the real command line (`main(argv=None)`) installs
`install_termination_handler()`, so SIGTERM / SIGHUP kills their trees and
exits 128+signal. The oracle runner (`runner/jobs.py` `_stop`) stops a
timed-out suite with SIGTERM to its process group, waits
`TERMINATE_GRACE_SECONDS`, then SIGKILL. Before this, a timed-out HUGE01
suite left cobc and gcc running for 20 minutes with 9 GB of memory.
