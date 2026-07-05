"""Docker-backed GnuCOBOL toolchain.

mockymock is Docker-only by design (decision 2026-07-04): compilation and
execution both happen inside a persistent `mockymock-cobc` container so
that a correctly configured cobc is guaranteed (no COB_CONFIG_DIR issues)
and compiled binaries never execute on the host (no Windows Smart App
Control / WDAC interference). If the daemon is unreachable we fail loudly;
there is no local-cobc fallback.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from mockymock.runtime.compiler import CompileResult
from mockymock.runtime.executor import (
    NOT_FOUND_EXIT_CODE,
    TIMEOUT_EXIT_CODE,
    ExecutionResult,
    _coerce_output,
)

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


def cobc_version() -> str:
    """First line of `cobc --version` from inside the container."""
    result = _docker("exec", CONTAINER, "cobc", "--version", timeout=30)
    if result.returncode != 0:
        raise DockerNotAvailableError(
            f"could not query cobc inside {CONTAINER}:\n{result.stderr.strip()}"
        )
    return result.stdout.splitlines()[0] if result.stdout else "unknown"


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
