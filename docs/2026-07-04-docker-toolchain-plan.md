# Docker GnuCOBOL Toolchain Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace mockymock's local-`cobc` toolchain with a persistent Docker container (`mockymock-cobc`) that compiles and runs instrumented COBOL via `docker exec`; Docker-only, fail loudly when the daemon is unreachable.

**Architecture:** A new `mockymock/runtime/docker_toolchain.py` owns the container lifecycle (`ensure_toolchain()`), host↔container path mapping, and docker-backed `compile_source()`/`run_binary()` that return the existing `CompileResult`/`ExecutionResult` dataclasses. Sandboxes move under a fixed bind-mounted work root (`~/.mockymock/work`). The local subprocess implementations, `gnucobol_bootstrap.py`, and their tests are deleted.

**Tech Stack:** Python 3.11+ stdlib only (subprocess, pathlib), Docker CLI, `debian:trixie-slim` + apt `gnucobol` (3.2), pytest with `unittest.mock`.

**Spec:** `docs/2026-07-04-docker-toolchain-design.md` (approved 2026-07-04).

## Global Constraints

- Zero runtime Python dependencies (stdlib only), matching the existing package.
- Image tag is exactly `mockymock-gnucobol`; container name is exactly `mockymock-cobc`; container mount point is exactly `/work`.
- Work root is exactly `Path.home() / ".mockymock" / "work"`.
- `CompileResult` stays in `mockymock/runtime/compiler.py`; `ExecutionResult`, `TIMEOUT_EXIT_CODE = 124`, `NOT_FOUND_EXIT_CODE = 127`, and `_coerce_output` stay in `mockymock/runtime/executor.py`. Their shapes must not change — `cli/main.py` and `report/` consume them.
- Unit tests must pass without Docker installed; only `tests/integration/` may touch the real daemon, guarded by `requires_docker`.
- All docker CLI paths passed as `-v` or exec arguments use POSIX separators (`Path.as_posix()`), never backslashes.
- Instrumented source written for the container must use LF line endings (`newline="\n"`).
- Run tests with the project venv: `.venv/Scripts/python.exe -m pytest ...` from the repo root (Windows host).

---

### Task 1: Dockerfile, module skeleton, and path mapping

**Files:**
- Create: `docker/Dockerfile`
- Create: `mockymock/runtime/docker_toolchain.py`
- Test: `tests/unit/test_docker_toolchain.py`

**Interfaces:**
- Produces: `WORK_ROOT: Path`, `IMAGE = "mockymock-gnucobol"`, `CONTAINER = "mockymock-cobc"`, `class DockerNotAvailableError(RuntimeError)`, `to_container_path(host_path: Path, work_root: Path = WORK_ROOT) -> str`. Every later task imports these from `mockymock.runtime.docker_toolchain`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_docker_toolchain.py
"""Tests for the Docker-backed GnuCOBOL toolchain.

All tests here mock subprocess -- they must pass on a machine without
Docker installed. Real-daemon coverage lives in tests/integration/.
"""

from pathlib import Path

import pytest

from mockymock.runtime.docker_toolchain import (
    CONTAINER,
    IMAGE,
    WORK_ROOT,
    DockerNotAvailableError,
    to_container_path,
)


def test_constants_have_the_agreed_names():
    assert IMAGE == "mockymock-gnucobol"
    assert CONTAINER == "mockymock-cobc"
    assert WORK_ROOT == Path.home() / ".mockymock" / "work"
    assert issubclass(DockerNotAvailableError, RuntimeError)


def test_to_container_path_maps_work_root_child_to_slash_work(tmp_path: Path):
    host = tmp_path / "mockymock-abc" / "PROG.cbl"
    assert to_container_path(host, work_root=tmp_path) == "/work/mockymock-abc/PROG.cbl"


def test_to_container_path_uses_posix_separators_on_windows_paths(tmp_path: Path):
    host = tmp_path / "a" / "b" / "PROG"
    assert to_container_path(host, work_root=tmp_path) == "/work/a/b/PROG"


def test_to_container_path_rejects_paths_outside_work_root(tmp_path: Path):
    outside = tmp_path.parent / "elsewhere" / "PROG.cbl"
    with pytest.raises(ValueError, match="not under the Docker work root"):
        to_container_path(outside, work_root=tmp_path / "work")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_docker_toolchain.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mockymock.runtime.docker_toolchain'`

- [ ] **Step 3: Write `docker/Dockerfile` and the module skeleton**

```dockerfile
# docker/Dockerfile
# GnuCOBOL 3.2 toolchain image for mockymock. Built once by
# `mockymock setup` (or implicitly by `mockymock run`) and kept running as
# the long-lived `mockymock-cobc` container with ~/.mockymock/work mounted
# at /work.
FROM debian:trixie-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends gnucobol \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /work
```

```python
# mockymock/runtime/docker_toolchain.py
"""Docker-backed GnuCOBOL toolchain.

mockymock is Docker-only by design (decision 2026-07-04): compilation and
execution both happen inside a persistent `mockymock-cobc` container so
that a correctly configured cobc is guaranteed (no COB_CONFIG_DIR issues)
and compiled binaries never execute on the host (no Windows Smart App
Control / WDAC interference). If the daemon is unreachable we fail loudly;
there is no local-cobc fallback.
"""

from __future__ import annotations

from pathlib import Path

IMAGE = "mockymock-gnucobol"
CONTAINER = "mockymock-cobc"
WORK_ROOT = Path.home() / ".mockymock" / "work"

# Repo-root docker/ directory, resolved relative to this file so the build
# context is found under editable installs (the only supported install mode).
_DOCKER_CONTEXT = Path(__file__).resolve().parents[2] / "docker"


class DockerNotAvailableError(RuntimeError):
    """Raised when the Docker daemon (or CLI) cannot be reached or the
    toolchain image/container cannot be brought up."""


def to_container_path(host_path: Path, work_root: Path = WORK_ROOT) -> str:
    """Map a host path under `work_root` to its /work path inside the
    container. The bind mount is `work_root -> /work`, established once at
    container creation, so only paths under the work root are visible to
    `docker exec`."""
    try:
        rel = host_path.resolve().relative_to(work_root.resolve())
    except ValueError:
        raise ValueError(
            f"{host_path} is not under the Docker work root {work_root}; "
            f"only files inside the work root are visible to the container"
        ) from None
    return "/work/" + rel.as_posix()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_docker_toolchain.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add docker/Dockerfile mockymock/runtime/docker_toolchain.py tests/unit/test_docker_toolchain.py
git commit -m "feat: Docker toolchain skeleton — image, constants, path mapping"
```

---

### Task 2: `ensure_toolchain()` container lifecycle

**Files:**
- Modify: `mockymock/runtime/docker_toolchain.py`
- Test: `tests/unit/test_docker_toolchain.py` (append)

**Interfaces:**
- Consumes: Task 1's constants and `DockerNotAvailableError`.
- Produces: `ensure_toolchain() -> None` (raises `DockerNotAvailableError`), `_docker(*args, timeout=...) -> subprocess.CompletedProcess` internal helper. Task 6 calls `ensure_toolchain()` from the CLI.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_docker_toolchain.py`:

```python
import subprocess
from unittest import mock

from mockymock.runtime.docker_toolchain import ensure_toolchain


def _completed(argv, returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(argv, returncode, stdout, stderr)


def test_ensure_toolchain_raises_when_docker_cli_is_missing():
    with mock.patch(
        "mockymock.runtime.docker_toolchain.subprocess.run",
        side_effect=FileNotFoundError("docker"),
    ):
        with pytest.raises(DockerNotAvailableError, match="Docker is required"):
            ensure_toolchain()


def test_ensure_toolchain_raises_when_daemon_is_unreachable():
    with mock.patch(
        "mockymock.runtime.docker_toolchain.subprocess.run",
        return_value=_completed(["docker", "info"], returncode=1,
                                stderr="Cannot connect to the Docker daemon"),
    ):
        with pytest.raises(DockerNotAvailableError, match="Docker is required"):
            ensure_toolchain()


def test_ensure_toolchain_builds_image_when_missing():
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        if argv[:3] == ["docker", "image", "inspect"]:
            return _completed(argv, returncode=1)  # image missing
        if argv[:2] == ["docker", "inspect"]:
            return _completed(argv, stdout="true\n")  # container running
        return _completed(argv)  # info, build succeed

    with mock.patch(
        "mockymock.runtime.docker_toolchain.subprocess.run", side_effect=fake_run
    ):
        ensure_toolchain()

    build_calls = [c for c in calls if c[:2] == ["docker", "build"]]
    assert len(build_calls) == 1
    assert "-t" in build_calls[0] and IMAGE in build_calls[0]


def test_ensure_toolchain_raises_when_image_build_fails():
    def fake_run(argv, **kwargs):
        if argv[:3] == ["docker", "image", "inspect"]:
            return _completed(argv, returncode=1)
        if argv[:2] == ["docker", "build"]:
            return _completed(argv, returncode=1, stderr="build boom")
        return _completed(argv)

    with mock.patch(
        "mockymock.runtime.docker_toolchain.subprocess.run", side_effect=fake_run
    ):
        with pytest.raises(DockerNotAvailableError, match="build boom"):
            ensure_toolchain()


def test_ensure_toolchain_creates_container_when_absent(tmp_path):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        if argv[:2] == ["docker", "inspect"]:
            return _completed(argv, returncode=1)  # no such container
        return _completed(argv, stdout="")

    with mock.patch(
        "mockymock.runtime.docker_toolchain.subprocess.run", side_effect=fake_run
    ), mock.patch(
        "mockymock.runtime.docker_toolchain.WORK_ROOT", tmp_path / "work"
    ):
        ensure_toolchain()

    run_calls = [c for c in calls if c[:2] == ["docker", "run"]]
    assert len(run_calls) == 1
    joined = " ".join(run_calls[0])
    assert "--name mockymock-cobc" in joined
    assert f"{(tmp_path / 'work').as_posix()}:/work" in joined
    assert joined.endswith("sleep infinity")
    assert (tmp_path / "work").is_dir()  # created before mounting


def test_ensure_toolchain_starts_container_when_stopped():
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        if argv[:2] == ["docker", "inspect"]:
            return _completed(argv, stdout="false\n")  # exists but stopped
        return _completed(argv)

    with mock.patch(
        "mockymock.runtime.docker_toolchain.subprocess.run", side_effect=fake_run
    ):
        ensure_toolchain()

    assert ["docker", "start", CONTAINER] in calls


def test_ensure_toolchain_is_a_noop_when_everything_is_up():
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        if argv[:2] == ["docker", "inspect"]:
            return _completed(argv, stdout="true\n")
        return _completed(argv)

    with mock.patch(
        "mockymock.runtime.docker_toolchain.subprocess.run", side_effect=fake_run
    ):
        ensure_toolchain()

    assert not any(
        c[:2] in (["docker", "build"], ["docker", "run"], ["docker", "start"])
        for c in calls
    )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_docker_toolchain.py -v`
Expected: FAIL — `ImportError: cannot import name 'ensure_toolchain'`

- [ ] **Step 3: Implement `ensure_toolchain()`**

Append to `mockymock/runtime/docker_toolchain.py` (add `import subprocess` at the top):

```python
_DAEMON_HINT = (
    "Docker is required: mockymock compiles and runs COBOL inside a "
    "GnuCOBOL container. Start Docker Desktop (or the docker service) "
    "and re-run."
)


def _docker(*args: str, timeout: int = 600) -> subprocess.CompletedProcess:
    """Run a docker CLI command, translating a missing/broken CLI into
    DockerNotAvailableError."""
    try:
        return subprocess.run(
            ["docker", *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise DockerNotAvailableError(f"{_DAEMON_HINT} ({exc})") from exc


def ensure_toolchain() -> None:
    """Bring the toolchain up: daemon reachable, image built, container
    running. Idempotent; called by both `mockymock setup` and every
    `mockymock run` (so the container is restarted if it died)."""
    info = _docker("info", timeout=30)
    if info.returncode != 0:
        raise DockerNotAvailableError(f"{_DAEMON_HINT}\n{info.stderr.strip()}")

    image = _docker("image", "inspect", IMAGE, timeout=30)
    if image.returncode != 0:
        build = _docker("build", "-t", IMAGE, str(_DOCKER_CONTEXT))
        if build.returncode != 0:
            raise DockerNotAvailableError(
                f"failed to build image {IMAGE}:\n{build.stderr.strip()}"
            )

    state = _docker(
        "inspect", "-f", "{{.State.Running}}", CONTAINER, timeout=30
    )
    if state.returncode != 0:
        WORK_ROOT.mkdir(parents=True, exist_ok=True)
        run = _docker(
            "run", "-d",
            "--name", CONTAINER,
            "-v", f"{WORK_ROOT.as_posix()}:/work",
            IMAGE,
            "sleep", "infinity",
        )
        if run.returncode != 0:
            raise DockerNotAvailableError(
                f"failed to start container {CONTAINER}:\n{run.stderr.strip()}"
            )
    elif state.stdout.strip() != "true":
        start = _docker("start", CONTAINER, timeout=60)
        if start.returncode != 0:
            raise DockerNotAvailableError(
                f"failed to start container {CONTAINER}:\n{start.stderr.strip()}"
            )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_docker_toolchain.py -v`
Expected: PASS (11 passed)

- [ ] **Step 5: Commit**

```bash
git add mockymock/runtime/docker_toolchain.py tests/unit/test_docker_toolchain.py
git commit -m "feat: ensure_toolchain() brings up the GnuCOBOL container idempotently"
```

---

### Task 3: Docker-backed `compile_source()`

**Files:**
- Modify: `mockymock/runtime/docker_toolchain.py`
- Test: `tests/unit/test_docker_toolchain.py` (append)

**Interfaces:**
- Consumes: `CompileResult` from `mockymock.runtime.compiler` (dataclass: `success: bool, binary_path: Path | None, stdout: str, stderr: str`), Task 1's `to_container_path`/`CONTAINER`.
- Produces: `compile_source(source_path: Path) -> CompileResult` in `docker_toolchain` — same contract the CLI already codes against, but the binary has **no suffix** (Linux ELF) and the source must live under `WORK_ROOT`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_docker_toolchain.py`:

```python
from mockymock.runtime.compiler import CompileResult
from mockymock.runtime.docker_toolchain import compile_source


def _work(tmp_path):
    """A fake work root with a sandbox and source file inside it."""
    work = tmp_path / "work"
    sandbox = work / "mockymock-x"
    sandbox.mkdir(parents=True)
    source = sandbox / "PROG.cbl"
    source.write_text("dummy\n")
    return work, source


def test_compile_source_execs_cobc_with_container_paths(tmp_path):
    work, source = _work(tmp_path)
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        (source.parent / "PROG").write_text("")  # cobc writes via the mount
        return _completed(argv)

    with mock.patch(
        "mockymock.runtime.docker_toolchain.subprocess.run", side_effect=fake_run
    ), mock.patch("mockymock.runtime.docker_toolchain.WORK_ROOT", work):
        result = compile_source(source)

    assert calls == [[
        "docker", "exec", CONTAINER,
        "cobc", "-free", "-x",
        "/work/mockymock-x/PROG.cbl", "-o", "/work/mockymock-x/PROG",
    ]]
    assert result.success
    assert result.binary_path == source.parent / "PROG"


def test_compile_source_failure_carries_cobc_stderr(tmp_path):
    work, source = _work(tmp_path)
    with mock.patch(
        "mockymock.runtime.docker_toolchain.subprocess.run",
        return_value=_completed([], returncode=1, stderr="PROG.cbl:7: syntax error"),
    ), mock.patch("mockymock.runtime.docker_toolchain.WORK_ROOT", work):
        result = compile_source(source)
    assert result == CompileResult(
        success=False, binary_path=None, stdout="", stderr="PROG.cbl:7: syntax error"
    )


def test_compile_source_fails_cleanly_when_binary_never_appears(tmp_path):
    """docker exec exiting 0 without the binary on the host side (e.g. a
    stale mount) must be a failure, not a phantom success."""
    work, source = _work(tmp_path)
    with mock.patch(
        "mockymock.runtime.docker_toolchain.subprocess.run",
        return_value=_completed([], returncode=0),
    ), mock.patch("mockymock.runtime.docker_toolchain.WORK_ROOT", work):
        result = compile_source(source)
    assert not result.success
    assert result.binary_path is None


def test_compile_source_wraps_docker_oserror_cleanly(tmp_path):
    work, source = _work(tmp_path)
    with mock.patch(
        "mockymock.runtime.docker_toolchain.subprocess.run",
        side_effect=OSError("docker went away"),
    ), mock.patch("mockymock.runtime.docker_toolchain.WORK_ROOT", work):
        result = compile_source(source)
    assert not result.success
    assert "docker went away" in result.stderr
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_docker_toolchain.py -v`
Expected: FAIL — `ImportError: cannot import name 'compile_source' from 'mockymock.runtime.docker_toolchain'`

- [ ] **Step 3: Implement `compile_source()`**

Append to `mockymock/runtime/docker_toolchain.py` (add `from mockymock.runtime.compiler import CompileResult` at the top):

```python
def compile_source(source_path: Path) -> CompileResult:
    """Compile a free-form COBOL source file (which must live under
    WORK_ROOT) inside the container. The binary is written next to the
    source with no suffix -- it is a Linux ELF that only ever executes
    inside the container."""
    container_source = to_container_path(source_path, WORK_ROOT)
    binary_path = source_path.with_suffix("")
    container_binary = to_container_path(binary_path, WORK_ROOT)
    try:
        result = subprocess.run(
            [
                "docker", "exec", CONTAINER,
                "cobc", "-free", "-x", container_source, "-o", container_binary,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        return CompileResult(
            success=False,
            binary_path=None,
            stdout="",
            stderr=f"mockymock: could not run docker exec: {exc}\n",
        )
    success = result.returncode == 0 and binary_path.exists()
    return CompileResult(
        success=success,
        binary_path=binary_path if success else None,
        stdout=result.stdout,
        stderr=result.stderr,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_docker_toolchain.py -v`
Expected: PASS (15 passed)

- [ ] **Step 5: Commit**

```bash
git add mockymock/runtime/docker_toolchain.py tests/unit/test_docker_toolchain.py
git commit -m "feat: docker exec-based compile_source"
```

---

### Task 4: Docker-backed `run_binary()`

**Files:**
- Modify: `mockymock/runtime/docker_toolchain.py`
- Test: `tests/unit/test_docker_toolchain.py` (append)

**Interfaces:**
- Consumes: `ExecutionResult`, `TIMEOUT_EXIT_CODE`, `NOT_FOUND_EXIT_CODE`, `_coerce_output` from `mockymock.runtime.executor`.
- Produces: `run_binary(binary_path: Path, timeout_seconds: int = 30) -> ExecutionResult` in `docker_toolchain`. Container-side `timeout` yields exit 124 (= `TIMEOUT_EXIT_CODE`); a host-side hang or docker OSError maps to the same conventions the executor documented.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_docker_toolchain.py`:

```python
from mockymock.runtime.docker_toolchain import run_binary
from mockymock.runtime.executor import NOT_FOUND_EXIT_CODE, TIMEOUT_EXIT_CODE


def test_run_binary_execs_via_container_timeout(tmp_path):
    work, source = _work(tmp_path)
    binary = source.parent / "PROG"
    binary.write_text("")
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs.get("timeout")))
        return _completed(argv, stdout="__MOCKYMOCK__ SUMMARY: RUN=1 FAILURES=0\n")

    with mock.patch(
        "mockymock.runtime.docker_toolchain.subprocess.run", side_effect=fake_run
    ), mock.patch("mockymock.runtime.docker_toolchain.WORK_ROOT", work):
        result = run_binary(binary, timeout_seconds=30)

    argv, host_timeout = calls[0]
    assert argv == [
        "docker", "exec", "-w", "/work/mockymock-x", CONTAINER,
        "timeout", "30", "/work/mockymock-x/PROG",
    ]
    assert host_timeout > 30  # belt-and-suspenders guard above container timeout
    assert result.exit_code == 0
    assert "SUMMARY" in result.stdout


def test_run_binary_container_timeout_gets_explanatory_stderr(tmp_path):
    work, source = _work(tmp_path)
    binary = source.parent / "PROG"
    with mock.patch(
        "mockymock.runtime.docker_toolchain.subprocess.run",
        return_value=_completed([], returncode=TIMEOUT_EXIT_CODE),
    ), mock.patch("mockymock.runtime.docker_toolchain.WORK_ROOT", work):
        result = run_binary(binary)
    assert result.exit_code == TIMEOUT_EXIT_CODE
    assert "timed out" in result.stderr


def test_run_binary_host_side_hang_maps_to_timeout_exit_code(tmp_path):
    work, source = _work(tmp_path)
    binary = source.parent / "PROG"
    with mock.patch(
        "mockymock.runtime.docker_toolchain.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd=["docker"], timeout=40, output=None),
    ), mock.patch("mockymock.runtime.docker_toolchain.WORK_ROOT", work):
        result = run_binary(binary)
    assert result.exit_code == TIMEOUT_EXIT_CODE
    assert result.stdout == ""  # None coerced, never propagated


def test_run_binary_docker_oserror_maps_to_not_found(tmp_path):
    work, source = _work(tmp_path)
    binary = source.parent / "PROG"
    with mock.patch(
        "mockymock.runtime.docker_toolchain.subprocess.run",
        side_effect=OSError("docker went away"),
    ), mock.patch("mockymock.runtime.docker_toolchain.WORK_ROOT", work):
        result = run_binary(binary)
    assert result.exit_code == NOT_FOUND_EXIT_CODE
    assert "docker went away" in result.stderr
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_docker_toolchain.py -v`
Expected: FAIL — `ImportError: cannot import name 'run_binary' from 'mockymock.runtime.docker_toolchain'`

- [ ] **Step 3: Implement `run_binary()`**

Append to `mockymock/runtime/docker_toolchain.py` (add the executor imports at the top):

```python
from mockymock.runtime.executor import (
    NOT_FOUND_EXIT_CODE,
    TIMEOUT_EXIT_CODE,
    ExecutionResult,
    _coerce_output,
)


def run_binary(binary_path: Path, timeout_seconds: int = 30) -> ExecutionResult:
    """Run a compiled binary inside the container, from its own sandbox
    directory. coreutils `timeout` enforces the limit container-side and
    exits 124 on expiry, matching TIMEOUT_EXIT_CODE; the host-side
    subprocess timeout is a wider guard against `docker exec` itself
    hanging."""
    container_binary = to_container_path(binary_path, WORK_ROOT)
    container_dir = container_binary.rsplit("/", 1)[0]
    try:
        result = subprocess.run(
            [
                "docker", "exec", "-w", container_dir, CONTAINER,
                "timeout", str(timeout_seconds), container_binary,
            ],
            capture_output=True,
            text=True,
            timeout=timeout_seconds + 15,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return ExecutionResult(
            exit_code=TIMEOUT_EXIT_CODE,
            stdout=_coerce_output(exc.stdout),
            stderr=(
                _coerce_output(exc.stderr)
                + f"mockymock: docker exec did not return within "
                f"{timeout_seconds + 15}s (container-side timeout is "
                f"{timeout_seconds}s; the docker daemon may be wedged)\n"
            ),
        )
    except OSError as exc:
        return ExecutionResult(
            exit_code=NOT_FOUND_EXIT_CODE,
            stdout="",
            stderr=f"mockymock: could not run docker exec: {exc}\n",
        )
    stderr = result.stderr
    if result.returncode == TIMEOUT_EXIT_CODE:
        stderr += (
            f"mockymock: binary timed out after {timeout_seconds}s "
            f"(a mocked CALL may have removed a loop's terminating "
            f"condition, producing an infinite loop)\n"
        )
    return ExecutionResult(
        exit_code=result.returncode, stdout=result.stdout, stderr=stderr
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_docker_toolchain.py -v`
Expected: PASS (19 passed)

- [ ] **Step 5: Commit**

```bash
git add mockymock/runtime/docker_toolchain.py tests/unit/test_docker_toolchain.py
git commit -m "feat: docker exec-based run_binary with container-side timeout"
```

---

### Task 5: `sandbox_dir()` root parameter

**Files:**
- Modify: `mockymock/runtime/sandbox.py`
- Test: `tests/unit/test_sandbox.py` (create)

**Interfaces:**
- Consumes: nothing new.
- Produces: `sandbox_dir(root: Path | None = None)` — when `root` is given, the temp dir is created under it (creating `root` if needed). Task 6 calls `sandbox_dir(root=WORK_ROOT)`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_sandbox.py
from pathlib import Path

from mockymock.runtime.sandbox import sandbox_dir


def test_sandbox_dir_defaults_to_system_temp():
    with sandbox_dir() as tmp:
        assert tmp.is_dir()
        assert tmp.name.startswith("mockymock-")
    assert not tmp.exists()


def test_sandbox_dir_under_given_root_creates_root_and_cleans_up(tmp_path: Path):
    root = tmp_path / "deep" / "work"  # does not exist yet
    with sandbox_dir(root=root) as tmp:
        assert tmp.parent == root
        assert tmp.is_dir()
    assert not tmp.exists()
    assert root.is_dir()  # root itself survives
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_sandbox.py -v`
Expected: FAIL — `TypeError: sandbox_dir() got an unexpected keyword argument 'root'`

- [ ] **Step 3: Implement**

Replace the body of `mockymock/runtime/sandbox.py`:

```python
"""Temporary sandbox directories for compiling and running COBOL programs."""

from __future__ import annotations

import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


@contextmanager
def sandbox_dir(root: Path | None = None) -> Iterator[Path]:
    """Yield a fresh temp directory, removed on exit.

    With `root`, the sandbox is created under that directory (created if
    missing). The Docker toolchain requires this: only paths under its
    bind-mounted work root are visible inside the container."""
    if root is not None:
        root.mkdir(parents=True, exist_ok=True)
    path = Path(tempfile.mkdtemp(prefix="mockymock-", dir=root))
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_sandbox.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add mockymock/runtime/sandbox.py tests/unit/test_sandbox.py
git commit -m "feat: sandbox_dir accepts a root so sandboxes can live under the Docker mount"
```

---

### Task 6: CLI rewire — `setup` and `run` go through Docker

**Files:**
- Modify: `mockymock/cli/main.py` (`_cmd_setup` whole body; `_cmd_run` imports, toolchain check, sandbox block; `build_parser` setup help text)
- Modify: `mockymock/runtime/docker_toolchain.py` (add `cobc_version()`)
- Test: `tests/unit/test_cli_docker.py` (create)

**Interfaces:**
- Consumes: `ensure_toolchain`, `compile_source`, `run_binary`, `cobc_version`, `WORK_ROOT`, `DockerNotAvailableError` from `docker_toolchain`; `sandbox_dir(root=...)` from Task 5.
- Produces: `cobc_version() -> str` (first line of in-container `cobc --version`). CLI behavior later tasks' integration tests rely on: `run`/`setup` exit 1 with a `mockymock ...: Docker is required` message when the daemon is down.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_cli_docker.py
"""CLI behavior around the Docker toolchain, with the toolchain mocked --
these tests must pass without Docker installed."""

from unittest import mock

from mockymock.cli.main import main
from mockymock.runtime.docker_toolchain import DockerNotAvailableError


def test_setup_reports_container_and_cobc_version(capsys):
    with mock.patch(
        "mockymock.runtime.docker_toolchain.ensure_toolchain"
    ) as ensure, mock.patch(
        "mockymock.runtime.docker_toolchain.cobc_version",
        return_value="cobc (GnuCOBOL) 3.2.0",
    ):
        exit_code = main(["setup"])
    assert exit_code == 0
    ensure.assert_called_once()
    out = capsys.readouterr().out
    assert "mockymock-cobc" in out
    assert "cobc (GnuCOBOL) 3.2.0" in out


def test_setup_fails_loudly_when_docker_unavailable(capsys):
    with mock.patch(
        "mockymock.runtime.docker_toolchain.ensure_toolchain",
        side_effect=DockerNotAvailableError("Docker is required: start Docker Desktop"),
    ):
        exit_code = main(["setup"])
    assert exit_code == 1
    assert "Docker is required" in capsys.readouterr().out


def test_run_fails_loudly_before_parsing_when_docker_unavailable(tmp_path, capsys):
    """ensure_toolchain runs first: no parse work, no sandbox, just the
    actionable message. The program/cut paths deliberately don't exist."""
    with mock.patch(
        "mockymock.runtime.docker_toolchain.ensure_toolchain",
        side_effect=DockerNotAvailableError("Docker is required: start Docker Desktop"),
    ):
        exit_code = main(
            ["run", str(tmp_path / "NOPE.cbl"), "--cut", str(tmp_path / "NOPE.cut")]
        )
    assert exit_code == 1
    assert "Docker is required" in capsys.readouterr().out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_cli_docker.py -v`
Expected: FAIL — setup still prints `found cobc at ...` (old bootstrap path) / run raises `FileNotFoundError` reading NOPE.cbl instead of exiting 1.

- [ ] **Step 3: Add `cobc_version()` to `docker_toolchain.py`**

```python
def cobc_version() -> str:
    """First line of `cobc --version` from inside the container."""
    result = _docker("exec", CONTAINER, "cobc", "--version", timeout=30)
    if result.returncode != 0:
        raise DockerNotAvailableError(
            f"could not query cobc inside {CONTAINER}:\n{result.stderr.strip()}"
        )
    return result.stdout.splitlines()[0] if result.stdout else "unknown"
```

- [ ] **Step 4: Rewire `cli/main.py`**

Replace `_cmd_setup` entirely:

```python
def _cmd_setup(args: argparse.Namespace) -> int:
    from mockymock.runtime import docker_toolchain

    try:
        docker_toolchain.ensure_toolchain()
        version = docker_toolchain.cobc_version()
    except docker_toolchain.DockerNotAvailableError as exc:
        print(f"mockymock setup: {exc}")
        return 1
    print(
        f"mockymock setup: container {docker_toolchain.CONTAINER} ready "
        f"({version})"
    )
    return 0
```

In `_cmd_run`, replace the two runtime imports

```python
    from mockymock.runtime.compiler import compile_source
    from mockymock.runtime.executor import run_binary
```

with

```python
    from mockymock.runtime import docker_toolchain
```

and insert the fail-fast toolchain check as the FIRST statements of the
function body (before `source_path = Path(args.program)`):

```python
    try:
        docker_toolchain.ensure_toolchain()
    except docker_toolchain.DockerNotAvailableError as exc:
        print(f"mockymock run: {exc}")
        return 1
```

then replace the sandbox block

```python
    with sandbox_dir() as tmp:
        instrumented_path = tmp / source_path.with_suffix(".cbl").name
        instrumented_path.write_text("\n".join(instrumented) + "\n")

        compiled = compile_source(instrumented_path)
```

with

```python
    with sandbox_dir(root=docker_toolchain.WORK_ROOT) as tmp:
        instrumented_path = tmp / source_path.with_suffix(".cbl").name
        instrumented_path.write_text(
            "\n".join(instrumented) + "\n", newline="\n"
        )

        compiled = docker_toolchain.compile_source(instrumented_path)
```

and `executed = run_binary(compiled.binary_path)` with
`executed = docker_toolchain.run_binary(compiled.binary_path)`.

Finally update the setup subparser help string in `build_parser` to
`"Build the GnuCOBOL image and start the mockymock-cobc container"`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_cli_docker.py tests/unit/test_docker_toolchain.py -v`
Expected: PASS (22 passed)

- [ ] **Step 6: Commit**

```bash
git add mockymock/cli/main.py mockymock/runtime/docker_toolchain.py tests/unit/test_cli_docker.py
git commit -m "feat: CLI setup/run drive the Docker toolchain, fail loudly without Docker"
```

---

### Task 7: Remove the local toolchain; integration tests go through Docker

**Files:**
- Delete: `mockymock/runtime/gnucobol_bootstrap.py`, `tests/unit/test_gnucobol_bootstrap.py`, `tests/unit/test_compiler.py`, `tests/unit/test_executor.py`
- Modify: `mockymock/runtime/compiler.py` (dataclass only), `mockymock/runtime/executor.py` (dataclass + constants + `_coerce_output` only)
- Create: `tests/integration/_docker.py`
- Modify: `tests/integration/test_walking_skeleton.py`, `tests/integration/test_cli.py`, `tests/integration/test_ordrproc_example.py`, `tests/integration/test_copybook_expansion.py`

**Interfaces:**
- Consumes: everything produced by Tasks 1–6.
- Produces: `tests/integration/_docker.py::docker_available() -> bool` and the `requires_docker` marker pattern all integration files use.

- [ ] **Step 1: Reduce `compiler.py` and `executor.py` to their shared types**

`mockymock/runtime/compiler.py` becomes exactly:

```python
"""Compile result type shared by the Docker toolchain and its consumers.

The local-cobc implementation that used to live here was removed when the
toolchain went Docker-only (see docs/2026-07-04-docker-toolchain-design.md);
compilation now happens in runtime/docker_toolchain.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class CompileResult:
    success: bool
    binary_path: Path | None
    stdout: str
    stderr: str
```

`mockymock/runtime/executor.py` becomes exactly:

```python
"""Execution result type and exit-code conventions for running compiled
COBOL test binaries.

The local-subprocess implementation that used to live here was removed when
the toolchain went Docker-only (see
docs/2026-07-04-docker-toolchain-design.md); execution now happens in
runtime/docker_toolchain.py via `docker exec ... timeout N <binary>`.
"""

from __future__ import annotations

from dataclasses import dataclass

# Conventional exit codes so ExecutionResult.exit_code stays a plain int and
# every consumer (report/results.py's parse_stdout, main.py's _cmd_run)
# keeps working unmodified. 124 matches both the `timeout` shell command and
# the container-side `timeout` wrapper the Docker toolchain uses.
TIMEOUT_EXIT_CODE = 124
NOT_FOUND_EXIT_CODE = 127


@dataclass
class ExecutionResult:
    exit_code: int
    stdout: str
    stderr: str


def _coerce_output(value: str | bytes | None) -> str:
    """subprocess.TimeoutExpired's .stdout/.stderr can be None or bytes.
    Normalize to str so ExecutionResult's fields stay str as documented and
    report/results.py's parse_stdout never receives None."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value
```

Delete `mockymock/runtime/gnucobol_bootstrap.py`,
`tests/unit/test_gnucobol_bootstrap.py`, `tests/unit/test_compiler.py`,
`tests/unit/test_executor.py`:

```bash
git rm mockymock/runtime/gnucobol_bootstrap.py tests/unit/test_gnucobol_bootstrap.py tests/unit/test_compiler.py tests/unit/test_executor.py
```

- [ ] **Step 2: Create the shared integration guard**

```python
# tests/integration/_docker.py
"""Shared skip-guard: integration tests need a reachable Docker daemon."""

from __future__ import annotations

import functools
import shutil
import subprocess

import pytest


@functools.lru_cache(maxsize=1)
def docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        return (
            subprocess.run(
                ["docker", "info"], capture_output=True, timeout=30, check=False
            ).returncode
            == 0
        )
    except (OSError, subprocess.TimeoutExpired):
        return False


requires_docker = pytest.mark.skipif(
    not docker_available(), reason="Docker daemon not reachable"
)
```

- [ ] **Step 3: Swap the guard and toolchain in the four integration files**

In `tests/integration/test_cli.py`, `test_ordrproc_example.py`,
`test_copybook_expansion.py`: delete the `import shutil` line and the local

```python
requires_gnucobol = pytest.mark.skipif(
    shutil.which("cobc") is None, reason="GnuCOBOL (cobc) not installed"
)
```

block, add `from tests.integration._docker import requires_docker`, and
rename every `@requires_gnucobol` decorator to `@requires_docker`.

`tests/integration/test_walking_skeleton.py` additionally switches to the
Docker toolchain (its sandbox must live under the mounted work root, and
the source must be written with LF endings):

```python
from pathlib import Path

from mockymock.runtime.docker_toolchain import (
    WORK_ROOT,
    compile_source,
    ensure_toolchain,
    run_binary,
)
from mockymock.runtime.sandbox import sandbox_dir
from tests.integration._docker import requires_docker

FIXTURE = Path(__file__).parent / "fixtures" / "walking_skeleton.cbl"


@requires_docker
def test_walking_skeleton_compiles_and_runs():
    ensure_toolchain()
    with sandbox_dir(root=WORK_ROOT) as tmp:
        source_copy = tmp / "walking_skeleton.cbl"
        source_copy.write_text(FIXTURE.read_text(), newline="\n")

        compiled = compile_source(source_copy)
        assert compiled.success, compiled.stderr

        executed = run_binary(compiled.binary_path)

    assert executed.exit_code == 0
    assert "__MOCKYMOCK__ TESTSUITE: walking skeleton" in executed.stdout
    assert "__MOCKYMOCK__ CASE 001 START:" in executed.stdout
    assert "__MOCKYMOCK__ CASE 001 END" in executed.stdout
    assert "__MOCKYMOCK__ SUMMARY: RUN=1 FAILURES=0" in executed.stdout
```

- [ ] **Step 4: Run the unit suite (no Docker needed)**

Run: `.venv/Scripts/python.exe -m pytest tests/unit -v`
Expected: PASS — the three deleted test files are gone; `test_docker_toolchain.py`, `test_cli_docker.py`, `test_sandbox.py` cover their ground.

- [ ] **Step 5: Run the integration suite against real Docker**

Docker Desktop must be running. First run builds the image (~1 min).

Run: `.venv/Scripts/python.exe -m pytest tests/integration -v`
Expected: PASS (19 passed) — first run is slower due to the image build; no `COB_CONFIG_DIR` export needed, and the Smart App Control flake cannot occur (binaries execute in the container).

- [ ] **Step 6: Run the whole suite**

Run: `.venv/Scripts/python.exe -m pytest tests/ -v`
Expected: PASS (unit + integration green, 1 xfail in mock_surface as before).

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat!: remove local cobc toolchain; all compile/run goes through Docker"
```

---

### Task 8: CI and docs

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `README.md` (Setup section)

**Interfaces:**
- Consumes: the Docker-only behavior from Task 7.
- Produces: nothing downstream; this closes out the spec.

- [ ] **Step 1: Update CI**

In `.github/workflows/ci.yml`, replace the step

```yaml
      - name: Install GnuCOBOL
        run: sudo apt-get update && sudo apt-get install -y gnucobol
```

with

```yaml
      # No GnuCOBOL install: the toolchain is Docker-only (see
      # docs/2026-07-04-docker-toolchain-design.md). ubuntu-latest runners
      # ship with Docker; the integration tests build the mockymock-gnucobol
      # image on first use (~1 min per job).
```

- [ ] **Step 2: Update README Setup section**

Replace the Setup block (`mockymock setup           # installs GnuCOBOL if not already on PATH` line and surroundings) so it reads:

```markdown
## Setup

Requires a running Docker daemon (Docker Desktop on Windows/macOS). COBOL
is compiled and executed inside a GnuCOBOL container — nothing runs on the
host, and no local GnuCOBOL install is needed.

```bash
python -m venv .venv
.venv/Scripts/activate   # or source .venv/bin/activate on macOS/Linux
pip install -r requirements-dev.txt
mockymock setup           # builds the GnuCOBOL image, starts mockymock-cobc
python -m pytest tests/unit -v
```

`tests/integration/` additionally requires the Docker daemon to be
reachable and is skipped automatically if it isn't. `mockymock run` brings
the container up on its own, so `mockymock setup` is optional.
```

- [ ] **Step 3: Sanity-check the workflow file parses**

Run: `.venv/Scripts/python.exe -c "import yaml,sys; yaml.safe_load(open('.github/workflows/ci.yml')); print('ok')"`
Expected: `ok` (if PyYAML isn't in the venv, visually verify indentation instead — the change only removes one step and adds a comment).

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/ci.yml README.md
git commit -m "docs+ci: Docker-only toolchain — drop runner GnuCOBOL install, update setup docs"
```
