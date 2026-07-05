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
