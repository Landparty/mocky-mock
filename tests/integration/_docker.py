"""Shared skip-guard: integration tests need a working GnuCOBOL toolchain --
a reachable Docker daemon, or the native backend (`MOCKYMOCK_GNUCOBOL_HOME`
set, see mockymock/runtime/toolchain.py)."""

from __future__ import annotations

import functools
import shutil
import subprocess

import pytest


@functools.lru_cache(maxsize=1)
def docker_available() -> bool:
    from mockymock.runtime.toolchain import selected

    if selected() == "native":
        return True
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
    not docker_available(), reason="no toolchain: Docker daemon not reachable"
)


def pinned_coverage_toolchain() -> bool:
    """Whether exact `--coverage` line counts can be asserted. They are
    pinned against the Docker image's gcc: gcov's idea of which lines are
    executable moves with the C compiler's version (gcc 13 counts 110
    own lines of ACCTPRG.cbl where the image's gcc 14 counts 97), and the
    native toolchain compiles with whatever gcc the host has."""
    from mockymock.runtime.toolchain import selected

    return selected() == "docker"
