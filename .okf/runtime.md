---
type: Module
title: Docker Runtime
description: mockymock-cobc container lifecycle, docker exec-based compile/run, and the Docker-only sandbox model that replaced the local cobc toolchain.
tags: [runtime, docker, gnucobol]
timestamp: 2026-07-07T00:00:00Z
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
   │     image "mockymock-gnucobol:<hash>" missing ───▶ docker build -t ... docker/
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
| 2. Image | `docker image inspect <IMAGE>` | build via `docker build -t <IMAGE> <repo>/docker/` |
| 3. Container | one `docker inspect -f "{{.State.Running}} {{.Config.Image}}" mockymock-cobc` yields both running state and creating image | absent -> `_create_container()` (`docker run -d --name mockymock-cobc -v <WORK_ROOT>:/work <IMAGE> sleep infinity`); **created from a different image tag** -> `docker rm -f` then `_create_container()` (a stale container would otherwise defeat the content-hash tag forever); present-but-stopped -> `docker start mockymock-cobc` |

`_create_container()` also absorbs the concurrent-first-run race: if
`docker run --name` fails with *"name already in use"* (another invocation
won the race between our inspect and run), it re-inspects and adopts the
winner's container — starting it if it exists but is stopped — instead of
raising. Any other `docker run` failure still raises
`DockerNotAvailableError`.

Constants (asserted by unit tests, must not drift in shape):

| Name | Value |
|------|-------|
| `IMAGE` | `mockymock-gnucobol:<8-char sha256 of docker/Dockerfile>` — computed by `_image_tag()` at import, so editing the Dockerfile changes the tag, the image-inspect misses, a rebuild happens, **and** step 3 recreates the container from the new image |
| `CONTAINER` | `mockymock-cobc` |
| `WORK_ROOT` | `Path.home() / ".mockymock" / "work"` |

The `docker build` context is resolved as `Path(__file__).resolve().parents[2] / "docker"`
(repo-root `docker/`) so the build context is found under editable installs —
the only supported install mode.

`_docker(*args, timeout=600)` is the sole subprocess wrapper: any `OSError` or
`subprocess.TimeoutExpired` from the docker CLI itself (not the workload inside
it) becomes `DockerNotAvailableError` with the actionable `_DAEMON_HINT`
message ("Start Docker Desktop ... and re-run").

# Image

`docker/Dockerfile`: `FROM debian:trixie-slim`, `apt-get install -y
--no-install-recommends gnucobol` (GnuCOBOL 3.2, same major version as the
former local toolchain), `WORKDIR /work`. No entrypoint — the container is
started with `sleep infinity` and driven entirely via `docker exec`.

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
- Runs `docker exec mockymock-cobc cobc -free -x <container_source> -o <container_binary>`.
- Success requires **both** `returncode == 0` **and** `binary_path.exists()`
  on the host side — a zero exit with no binary materializing (e.g. a stale
  mount) is treated as failure, not a phantom success.
- `OSError` (docker CLI vanished mid-call) and `subprocess.TimeoutExpired`
  (600s) are both caught and turned into a failed `CompileResult` with an
  explanatory `stderr`, never an unhandled exception.

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
printed on compile failure still exists, but the CLI removes it afterwards
when the run got past compilation. So sandboxes are *not* always removed
on exit. Their only Docker-specific feature:
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
