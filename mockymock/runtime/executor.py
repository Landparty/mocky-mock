"""Runs a compiled COBOL test binary and captures its output."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

# Conventional exit codes so ExecutionResult.exit_code stays a plain int and
# every existing consumer (report/results.py's parse_stdout, main.py's
# _cmd_run) keeps working unmodified: parse_stdout only ever inspects
# .stdout, and a non-zero exit_code with empty/explanatory .stdout naturally
# yields all_passed=False downstream (tests_run stays 0, since no
# __MOCKYMOCK__ SUMMARY line is present in the captured output).
TIMEOUT_EXIT_CODE = 124  # matches the `timeout` shell command's convention
NOT_FOUND_EXIT_CODE = 127  # matches shell's "command not found" convention


@dataclass
class ExecutionResult:
    exit_code: int
    stdout: str
    stderr: str


def run_binary(binary_path: Path, timeout_seconds: int = 30) -> ExecutionResult:
    """Run a compiled binary in its own directory, capturing stdout/stderr.

    For a mocking tool specifically, an infinite loop in the instrumented
    program is a realistic failure mode: mocking out a CALL that happened to
    supply a loop's terminating condition can easily produce one. Rather
    than letting subprocess.TimeoutExpired propagate as an uncaught
    exception, this returns a clean ExecutionResult with a conventional
    non-zero exit code and an explanatory stderr message. FileNotFoundError
    (the binary path somehow doesn't exist/isn't executable) is handled the
    same way for robustness.
    """
    try:
        result = subprocess.run(
            [str(binary_path)],
            capture_output=True,
            text=True,
            cwd=binary_path.parent,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return ExecutionResult(
            exit_code=TIMEOUT_EXIT_CODE,
            stdout=_coerce_output(exc.stdout),
            stderr=(
                _coerce_output(exc.stderr)
                + f"mockymock: binary timed out after {timeout_seconds}s "
                f"(a mocked CALL may have removed a loop's terminating "
                f"condition, producing an infinite loop)\n"
            ),
        )
    except FileNotFoundError as exc:
        return ExecutionResult(
            exit_code=NOT_FOUND_EXIT_CODE,
            stdout="",
            stderr=f"mockymock: could not execute {binary_path}: {exc}\n",
        )
    except OSError as exc:
        # Seen in practice as WinError 4551 ("An Application Control policy
        # has blocked this file"): Windows Smart App Control / WDAC can
        # refuse to launch a freshly compiled unsigned binary, sometimes
        # intermittently while its cloud reputation check is pending. Return
        # a clean, explanatory failure instead of a traceback; the fix is an
        # OS-policy exclusion for the sandbox directory, not a retry.
        return ExecutionResult(
            exit_code=NOT_FOUND_EXIT_CODE,
            stdout="",
            stderr=(
                f"mockymock: the operating system refused to execute "
                f"{binary_path}: {exc}\n"
                f"(on Windows this is often Smart App Control / an "
                f"Application Control policy blocking a freshly compiled "
                f"unsigned binary -- add an exclusion for the sandbox "
                f"directory or adjust the policy)\n"
            ),
        )
    return ExecutionResult(
        exit_code=result.returncode, stdout=result.stdout, stderr=result.stderr
    )


def _coerce_output(value: str | bytes | None) -> str:
    """subprocess.TimeoutExpired's .stdout/.stderr can be None (nothing was
    captured before the process was killed) or bytes (when `text=True` isn't
    honored for partially-captured output on some platforms). Normalize to
    str so ExecutionResult's fields stay str as documented, and so
    report/results.py's parse_stdout (which calls .splitlines()
    unconditionally) never receives None."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value
