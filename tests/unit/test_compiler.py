"""Unit tests for the cobc wrapper -- no GnuCOBOL required."""

from pathlib import Path
from unittest.mock import patch

from mockymock.runtime.compiler import compile_source


def test_compile_source_returns_clean_result_when_cobc_cannot_be_launched():
    """cobc missing from PATH or blocked by an OS execution policy (e.g.
    Windows Smart App Control, WinError 4551) raises OSError from subprocess.
    compile_source must return a clean failure result, not leak a traceback."""
    with patch(
        "subprocess.run",
        side_effect=OSError(
            4551, "An Application Control policy has blocked this file"
        ),
    ):
        result = compile_source(Path("prog.cbl"))

    assert result.success is False
    assert result.binary_path is None
    assert "could not run cobc" in result.stderr
