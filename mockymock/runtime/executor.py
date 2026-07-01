"""Runs a compiled COBOL test binary and captures its output."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ExecutionResult:
    exit_code: int
    stdout: str
    stderr: str


def run_binary(binary_path: Path, timeout_seconds: int = 30) -> ExecutionResult:
    """Run a compiled binary in its own directory, capturing stdout/stderr."""
    result = subprocess.run(
        [str(binary_path)],
        capture_output=True,
        text=True,
        cwd=binary_path.parent,
        timeout=timeout_seconds,
        check=False,
    )
    return ExecutionResult(
        exit_code=result.returncode, stdout=result.stdout, stderr=result.stderr
    )
