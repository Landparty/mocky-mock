"""Merges every test case's MOCK CALL body for one call name into a single
EVALUATE UT-CURRENT-CASE dispatch block -- necessary because all TESTCASEs
in a suite share one compiled binary and therefore one physical copy of
each CALL statement (see Global Constraints: one binary per TESTSUITE).
"""

from __future__ import annotations

import re

from mockymock.dsl.model import MockTestSuite

_NON_COBOL_NAME_CHAR_RE = re.compile(r"[^A-Z0-9-]")


def tally_field_name(call_name: str) -> str:
    sanitized = _NON_COBOL_NAME_CHAR_RE.sub("-", call_name.upper())
    return f"UT-{sanitized}-TALLY"


def build_call_dispatch(call_name: str, suite: MockTestSuite) -> list[str]:
    """Tally increment + EVALUATE block for the CALL "call_name" splice site."""
    tally = tally_field_name(call_name)
    lines = [f"           ADD 1 TO {tally}", "           EVALUATE UT-CURRENT-CASE"]

    for index, case in enumerate(suite.test_cases, start=1):
        case_id = f"{index:03d}"
        for mock in case.mocks:
            if mock.program_name != call_name:
                continue
            lines.append(f'               WHEN "{case_id}"')
            lines.extend(f"                   {body}" for body in mock.body_lines)

    lines.append("               WHEN OTHER")
    lines.append(
        f'                   DISPLAY "__MOCKYMOCK__ ERROR: {call_name} called "'
    )
    lines.append('                       "from unmocked test case " UT-CURRENT-CASE')
    lines.append("           END-EVALUATE")
    return lines
