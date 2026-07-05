"""Execution result type and exit-code conventions for running compiled
COBOL test binaries.

The local-subprocess implementation that used to live here was removed when
the toolchain went Docker-only (see
docs/2026-07-04-docker-toolchain-design.md); execution now happens in
runtime/docker_toolchain.py via `docker exec ... timeout N <binary>`.
"""

from __future__ import annotations

from dataclasses import dataclass

# Conventional exit codes so ExecutionResult.exit_code stays a plain int and
# every consumer (report/results.py's parse_stdout, main.py's _cmd_run)
# keeps working unmodified. 124 matches both the `timeout` shell command and
# the container-side `timeout` wrapper the Docker toolchain uses.
TIMEOUT_EXIT_CODE = 124
NOT_FOUND_EXIT_CODE = 127


@dataclass
class ExecutionResult:
    exit_code: int
    stdout: str
    stderr: str


def _coerce_output(value: str | bytes | None) -> str:
    """subprocess.TimeoutExpired's .stdout/.stderr can be None or bytes.
    Normalize to str so ExecutionResult's fields stay str as documented and
    report/results.py's parse_stdout never receives None."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value
