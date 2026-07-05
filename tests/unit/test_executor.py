"""Tests for runtime.executor.run_binary's failure-mode handling.

A mocking tool specifically has a realistic failure mode here: mocking out a
CALL that happened to supply a loop's terminating condition can easily
produce an infinite loop in the compiled program, which then hits
run_binary's subprocess timeout. Before this fix, subprocess.TimeoutExpired
propagated as an uncaught exception instead of failing cleanly.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

from mockymock.runtime.executor import ExecutionResult, run_binary


def test_run_binary_returns_clean_result_on_timeout():
    """subprocess.run raising TimeoutExpired must not propagate -- run_binary
    should return an ExecutionResult with a conventional non-zero exit code
    and a clear stderr message instead."""
    binary_path = Path("/fake/bin/PROG")
    with patch(
        "subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd=[str(binary_path)], timeout=30),
    ):
        result = run_binary(binary_path)

    assert isinstance(result, ExecutionResult)
    assert result.exit_code != 0
    # Conventional shell "timeout" command exit code.
    assert result.exit_code == 124
    assert "timed out" in result.stderr.lower() or "timeout" in result.stderr.lower()
    assert isinstance(result.stdout, str)
    assert isinstance(result.stderr, str)


def test_run_binary_returns_clean_result_on_timeout_with_none_stdout():
    """TimeoutExpired's .stdout/.stderr attributes can be None (subprocess
    only partially captures output before killing the process) -- run_binary
    must coerce these to strings rather than propagating a None into
    ExecutionResult (report/results.py's parse_stdout calls .splitlines() on
    it unconditionally)."""
    binary_path = Path("/fake/bin/PROG")
    timeout_error = subprocess.TimeoutExpired(cmd=[str(binary_path)], timeout=30)
    timeout_error.stdout = None
    timeout_error.stderr = None
    with patch("subprocess.run", side_effect=timeout_error):
        result = run_binary(binary_path)

    assert result.stdout == ""
    assert "timeout" in result.stderr.lower() or "timed out" in result.stderr.lower()


def test_run_binary_returns_clean_result_on_file_not_found():
    """A binary path that doesn't actually exist (e.g. a compile step that
    silently failed to produce a binary) must not propagate
    FileNotFoundError -- run_binary should return a clean failure result."""
    binary_path = Path("/fake/bin/DOES-NOT-EXIST")
    with patch("subprocess.run", side_effect=FileNotFoundError("no such file")):
        result = run_binary(binary_path)

    assert isinstance(result, ExecutionResult)
    assert result.exit_code != 0
    assert result.exit_code == 127
    assert result.stdout == ""
    assert result.stderr != ""


def test_run_binary_still_returns_normal_result_on_success():
    """Regression guard: the happy path must be untouched by the new
    exception handling."""
    binary_path = Path("/fake/bin/PROG")

    class _FakeCompletedProcess:
        returncode = 0
        stdout = "hello\n"
        stderr = ""

    with patch("subprocess.run", return_value=_FakeCompletedProcess()):
        result = run_binary(binary_path)

    assert result.exit_code == 0
    assert result.stdout == "hello\n"
    assert result.stderr == ""


def test_run_binary_returns_clean_result_when_os_blocks_execution():
    """Windows App Control / Smart App Control can refuse to launch a freshly
    compiled unsigned binary (WinError 4551), surfacing as OSError from
    subprocess. run_binary must return a clean failure result, not leak a
    traceback."""
    with patch(
        "subprocess.run",
        side_effect=OSError(4551, "An Application Control policy has blocked this file"),
    ):
        result = run_binary(Path("blocked.exe"))

    assert result.exit_code != 0
    assert result.stdout == ""
    assert "blocked.exe" in result.stderr
    assert "Application Control" in result.stderr
