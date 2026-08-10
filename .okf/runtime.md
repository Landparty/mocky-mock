---
type: Module
title: Docker Runtime
description: mockymock-cobc container lifecycle, docker exec-based compile/run, and the Docker-only sandbox model that replaced the local cobc toolchain.
tags: [runtime, docker, gnucobol]
timestamp: 2026-08-10T00:00:00Z
---

# Overview

mockymock is **Docker-only** for compilation and execution (decision
2026-07-04, `docs/2026-07-04-docker-toolchain-design.md`). Nothing COBOL-related
runs on the host: `cobc` and every compiled test binary live and execute
exclusively inside a single long-lived container, `mockymock-cobc`. There is no
`--toolchain` flag and no local-`cobc` fallback — if the daemon is unreachable,
the CLI fails loudly and exits 1.

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
   ├─ compile_source()   docker exec mockymock-cobc cobc -free -x /work/<sb>/PROG.cbl -o /work/<sb>/PROG
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

`ensure_toolchain()` in `mockymock/runtime/docker_toolchain.py` is idempotent
and is called at the start of **both** `mockymock setup` and every
`mockymock run` (so a container that died between runs is restarted
automatically; `setup` is therefore optional).

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
- Runs `docker exec mockymock-cobc timeout -k 5 585 cobc -free -x <container_source> -o <container_binary>`
  (fixed 2026-08-10, audit finding F1 — previously unwrapped: a `cobc`
  invocation that hung inside the shared container had no container-side
  bound at all and outlived even the host's own 600s `subprocess.run`
  timeout, leaking an orphaned process into a container every other run
  also uses). The container-side ceiling (585s) stays under the host-side
  `subprocess.run(timeout=600)` guard, same `-k 5` SIGKILL-escalation
  pattern as `run_binary` below.
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

# What compiler.py / executor.py still hold

Both modules were reduced to shared types only — the local-subprocess
implementations that used to live there were deleted wholesale, not adapted:

| Module | Contents kept |
|--------|---------------|
| `runtime/compiler.py` | `CompileResult` dataclass: `success: bool`, `binary_path: Path \| None`, `stdout: str`, `stderr: str` |
| `runtime/executor.py` | `ExecutionResult` dataclass, `TIMEOUT_EXIT_CODE = 124`, `NOT_FOUND_EXIT_CODE = 127`, `_coerce_output()` |

These shapes are a stable contract consumed by `cli/main.py` and
`report/results.py` — the Docker rewrite deliberately left them unchanged so
nothing downstream of compile/run needed to change.

# CLI mapping

| Command | Behavior |
|---------|----------|
| `mockymock setup` | Calls `ensure_toolchain()` then `cobc_version()` (first line of in-container `cobc --version`). Prints `container mockymock-cobc ready (<version>)` and exits 0, or prints the `DockerNotAvailableError` message and exits 1. Optional — `run` brings the container up on its own. |
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
afterwards when `--keep-sandbox` was not also given. That removal now
lives in a `try/finally` wrapping the whole compile/run/coverage body
(fixed 2026-08-10, audit finding F10) — it used to be a bare statement
after the `with` block, so a compile failure's early `return 1`, or any
exception from `compile_source`/`run_binary`/`run_gcov`, skipped it and
leaked the sandbox permanently. `finally` now runs on every exit path.
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
