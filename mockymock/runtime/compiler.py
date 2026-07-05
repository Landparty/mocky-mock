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
