"""Merges every test case's mock body for one (category, key) into a single
EVALUATE UT-CURRENT-CASE dispatch block -- necessary because all TESTCASEs
in a suite share one compiled binary and therefore one physical copy of
each mocked statement (see Global Constraints: one binary per TESTSUITE).

Also builds the trap stub spliced over *unmocked* EXEC SQL/CICS/DLI sites:
those must be commented out program-wide regardless of reachability (cobc
cannot compile raw EXEC blocks), and if control somehow reaches one the
trap records a failure instead of silently doing nothing.
"""

from __future__ import annotations

from mockymock.dsl.model import MockCategory, MockTestSuite
from mockymock.splicer.naming import TallyRegistry


def build_dispatch(
    category: MockCategory,
    key: str,
    suite: MockTestSuite,
    registry: TallyRegistry,
) -> list[str]:
    """Tally increment + EVALUATE block for one mocked boundary site."""
    tally = registry.name(category, key)
    lines = [f"           ADD 1 TO {tally}", "           EVALUATE UT-CURRENT-CASE"]

    for index, case in enumerate(suite.test_cases, start=1):
        case_id = f"{index:03d}"
        for mock in case.mocks:
            if mock.category is not category or mock.key != key:
                continue
            lines.append(f'               WHEN "{case_id}"')
            body = [f"                   {line}" for line in mock.body_lines]
            # An empty WHEN branch is invalid COBOL; CONTINUE is the no-op.
            lines.extend(body or ["                   CONTINUE"])

    describe = (
        key
        if category is MockCategory.CALL
        else f"{category.value} {key}".replace('"', "")
    )
    lines.append("               WHEN OTHER")
    lines.append(
        f'                   DISPLAY "__MOCKYMOCK__ ERROR: {describe} reached "'
    )
    lines.append('                       "from unmocked test case " UT-CURRENT-CASE')
    lines.append("                   ADD 1 TO UT-FAIL-COUNT")
    lines.append("           END-EVALUATE")
    return lines


def build_exec_trap(kind: str, line: int) -> list[str]:
    """Replacement for an EXEC site no test case mocks. It still has to be
    commented out for the program to compile at all; this trap makes an
    unexpected execution a loud failure instead of a silent no-op."""
    return [
        f'           DISPLAY "__MOCKYMOCK__ ERROR: unmocked EXEC {kind} '
        f'reached (line {line})"',
        "           ADD 1 TO UT-FAIL-COUNT",
    ]
