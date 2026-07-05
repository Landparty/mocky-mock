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
