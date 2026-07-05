"""Wraps `cobc` to compile a free-form COBOL source file."""

from __future__ import annotations

import platform
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CompileResult:
    success: bool
    binary_path: Path | None
    stdout: str
    stderr: str


def compile_source(source_path: Path, cobc_path: str = "cobc") -> CompileResult:
    """Compile a free-form COBOL source file into an executable.

    Output binary is written next to source_path, same stem, with the
    platform's executable suffix (.exe on Windows, none elsewhere).
    """
    suffix = ".exe" if platform.system() == "Windows" else ""
    binary_path = source_path.with_suffix(suffix)
    try:
        result = subprocess.run(
            [cobc_path, "-free", "-x", str(source_path), "-o", str(binary_path)],
            capture_output=True,
            text=True,
            cwd=source_path.parent,
            check=False,
        )
    except OSError as exc:
        # cobc missing (FileNotFoundError) or blocked by an OS execution
        # policy (e.g. WinError 4551, Windows Smart App Control). Surface a
        # clean failure; callers already print CompileResult.stderr.
        return CompileResult(
            success=False,
            binary_path=None,
            stdout="",
            stderr=f"mockymock: could not run {cobc_path}: {exc}\n",
        )
    success = result.returncode == 0 and binary_path.exists()
    return CompileResult(
        success=success,
        binary_path=binary_path if success else None,
        stdout=result.stdout,
        stderr=result.stderr,
    )
