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
