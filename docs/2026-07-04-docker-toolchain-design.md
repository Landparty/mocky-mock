# mockymock — Docker GnuCOBOL Toolchain Design

**Status:** Approved 2026-07-04 (supersedes the local-`cobc` toolchain described
in §7–8 of `2026-06-30-mockymock-mvp-design.md`).
**Date:** 2026-07-04

## 1. Problem

The MVP toolchain shells out to a locally installed `cobc` and executes the
compiled binary directly on the host. On Windows this has two chronic
failure modes, both observed in practice:

1. **`COB_CONFIG_DIR` propagation** — GnuCOBOL installed via Chocolatey needs
   a user-scope `COB_CONFIG_DIR` env var; any shell started before the
   install (or that doesn't inherit user scope) fails every compile with
   `configuration error: default.conf: No such file or directory`.
2. **Smart App Control / WDAC flake** — Windows intermittently refuses to
   execute freshly compiled unsigned binaries (`WinError 4551`), failing
   roughly 1 in 3 full integration runs on one random test.

Both disappear if compilation *and* execution happen inside a Linux
container: the image bakes in a correctly configured `cobc`, and the binary
never touches the host OS's application-control policy.

## 2. Decisions

Made with the user on 2026-07-04:

- **Docker-only, fail loudly.** The local-`cobc` toolchain is removed, not
  kept as a fallback. If the Docker daemon is unreachable, `mockymock run`
  exits 1 with a clear message telling the user to start Docker. There is no
  `--toolchain` flag.
- **Persistent container + `docker exec`.** One long-lived container is
  spun up once and every compile/run talks to it via `docker exec`
  (~100–300 ms per call), rather than a fresh `docker run` per call
  (~1 s each under Docker Desktop; a 19-test integration sweep would spin
  ~40 containers).

## 3. Architecture

```
mockymock run
   │
   ├─ ensure_toolchain()          docker_toolchain.py
   │     daemon unreachable ──▶ DockerNotAvailableError (exit 1, loud)
   │     image missing      ──▶ docker build -t mockymock-gnucobol docker/
   │     container missing/stopped ──▶ docker run -d --name mockymock-cobc
   │                                     -v <work_root>:/work … sleep infinity
   │
   ├─ sandbox_dir(root=work_root)      ~/.mockymock/work/mockymock-XXXX/
   │     instrumented source written with newline="\n" (cobc is Linux-side)
   │
   ├─ compile:  docker exec mockymock-cobc
   │              cobc -free -x /work/<sb>/PROG.cbl -o /work/<sb>/PROG
   │
   └─ execute:  docker exec mockymock-cobc timeout 30 /work/<sb>/PROG
                  └─ stdout parsed by report/results.py, unchanged
```

- **Image**: `docker/Dockerfile` — `FROM debian:trixie-slim`,
  `apt-get install -y --no-install-recommends gnucobol` (GnuCOBOL 3.2,
  same major version as the previous local toolchain). Tag:
  `mockymock-gnucobol`.
- **Container**: name `mockymock-cobc`, started detached with
  `sleep infinity`, bind mount `<work_root> → /work`.
- **Work root**: fixed host directory `~/.mockymock/work`. Sandboxes must
  live under it — it is the only path the container can see. The mount is
  established once at container creation; per-run temp dirs elsewhere on
  the host would be invisible to `docker exec`.
- **Path mapping**: pure function `to_container_path(host_path, work_root)
  -> str` mapping `work_root/X/Y → /work/X/Y` (POSIX separators).
  Unit-testable without Docker. Paths outside `work_root` are a programming
  error and raise `ValueError`.

## 4. Module Changes

| Module | Change |
|--------|--------|
| `runtime/docker_toolchain.py` | **New.** `DockerNotAvailableError`, `ensure_toolchain()`, `compile_source()`, `run_binary()`, `to_container_path()`, work-root constant. |
| `runtime/compiler.py` | Local subprocess implementation removed. `CompileResult` dataclass stays (same shape, consumed by CLI). |
| `runtime/executor.py` | Local implementation removed. `ExecutionResult` dataclass and the `TIMEOUT_EXIT_CODE = 124` / `NOT_FOUND_EXIT_CODE = 127` conventions stay; container-side `timeout 30` exits 124, matching the existing convention with no report-layer change. |
| `runtime/gnucobol_bootstrap.py` | **Deleted** (choco/brew/apt logic obsolete). |
| `runtime/sandbox.py` | `sandbox_dir()` gains optional `root: Path \| None`; when given, the temp dir is created under it. |
| `cli/main.py` | `_cmd_setup` repurposed: ensure daemon, build image, start container, print in-container `cobc --version`. `_cmd_run`: call `ensure_toolchain()` (so setup is optional), create sandbox under work root, use docker compile/run, write instrumented source with `newline="\n"`. |
| `docker/Dockerfile` | **New.** |

Compiled binaries are Linux ELF files with no `.exe` suffix; the
`platform.system()`-based suffix logic disappears with the local compiler.

## 5. Error Handling

- **Daemon unreachable** (`docker` missing from PATH, or `docker info`
  non-zero): `DockerNotAvailableError` with an actionable message
  ("Docker is required — start Docker Desktop, or install Docker, then
  re-run"). CLI prints it and exits 1.
- **Image build failure**: surfaced with docker's stderr, exit 1.
- **Compile failure inside container**: unchanged contract —
  `CompileResult(success=False, stderr=cobc stderr)`.
- **Runtime timeout**: `timeout 30` inside the container returns exit 124;
  `ExecutionResult` carries it; downstream `all_passed=False` as today.
  The host-side `subprocess.run` also gets a slightly larger timeout as a
  belt-and-suspenders guard against a hung `docker exec` itself.
- **Container died between calls**: `ensure_toolchain()` restarts it; it is
  invoked at the start of every `run`, not just `setup`.

## 6. Testing

- **Unit (no Docker required)** — mocked-subprocess style, mirroring the
  deleted bootstrap/compiler/executor tests:
  - `ensure_toolchain()`: daemon missing → raises; image absent → build
    invoked; container stopped → started; happy path → no-op.
  - `to_container_path()`: mapping, POSIX separators, outside-root rejection.
  - compile/run: correct `docker exec` argv, exit-124 mapping, stderr
    passthrough.
- **Integration** — skip-guard changes from `requires_gnucobol` to
  `requires_docker` (skips only when the daemon is unreachable). All
  existing e2e tests run through the container unchanged in their
  assertions.
- **CI** — the "install GnuCOBOL on the runner" step is removed; the
  ubuntu runner's preinstalled Docker builds the image (first run ~1 min,
  cacheable).

## 7. Trade-offs Accepted

- First run on a fresh machine pays an image build (~1 min).
- Docker Desktop must be running; there is deliberately no fallback.
- Binaries are Linux ELF, not Windows executables — irrelevant, they are
  transient test artifacts that only ever execute inside the container.
