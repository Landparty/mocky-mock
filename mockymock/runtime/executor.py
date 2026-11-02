"""Execution result type and exit-code conventions for running compiled
COBOL test binaries.

The local-subprocess implementation that used to live here was removed when
the toolchain went Docker-only (see
docs/2026-07-04-docker-toolchain-design.md); execution now happens in
runtime/docker_toolchain.py via `docker exec ... timeout N <binary>`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# Conventional exit codes so ExecutionResult.exit_code stays a plain int and
# every consumer (report/results.py's parse_stdout, main.py's _cmd_run)
# keeps working unmodified. 124 matches both the `timeout` shell command and
# the container-side `timeout` wrapper the Docker toolchain uses.
TIMEOUT_EXIT_CODE = 124
NOT_FOUND_EXIT_CODE = 127

#: The clock every test binary runs on: GnuCOBOL answers FUNCTION
#: CURRENT-DATE, ACCEPT ... FROM DATE / DAY / TIME / DAY-OF-WEEK with it
#: (`COB_CURRENT_DATE`). With the wall clock, a program that DISPLAYs or
#: writes the date gave a different result on every run, so a recorded
#: expectation or behaviour baseline failed the next run although nothing
#: changed. MOCKYMOCK_CURRENT_DATE picks another instant ("real" keeps the
#: wall clock); a COB_CURRENT_DATE already in the environment is kept.
DEFAULT_CURRENT_DATE = "2026/01/15 10:30:00.00"
CURRENT_DATE_ENV = "MOCKYMOCK_CURRENT_DATE"


def fixed_clock_env() -> dict[str, str]:
    """`{"COB_CURRENT_DATE": ...}` for a test binary's environment, or `{}`
    when the user keeps the wall clock or set COB_CURRENT_DATE already."""
    if os.environ.get("COB_CURRENT_DATE"):
        return {}
    value = os.environ.get(CURRENT_DATE_ENV, "").strip() or DEFAULT_CURRENT_DATE
    if value.lower() == "real":
        return {}
    return {"COB_CURRENT_DATE": value}


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
