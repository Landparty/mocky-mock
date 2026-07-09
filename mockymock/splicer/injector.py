"""Builds the EVALUATE UT-CURRENT-CASE dispatch block spliced over one
mocked boundary site -- necessary because all TESTCASEs in a suite share
one compiled binary and therefore one physical copy of each mocked
statement (see Global Constraints: one binary per TESTSUITE).

Dispatch is built per SITE, not per mock key: different test cases may
match the same statement through different keys (case 1 mocks
`OPEN IN-FILE`, case 2 mocks `OPEN OUT-FILE`, both matching the one
`OPEN INPUT IN-FILE OUTPUT OUT-FILE` statement), so the tally increment
lives inside each case's WHEN branch, crediting that case's own directive.

Also builds the trap stub spliced over *unmocked* EXEC SQL/CICS/DLI sites:
those must be commented out program-wide regardless of reachability (cobc
cannot compile raw EXEC blocks), and if control somehow reaches one the
trap records a failure instead of silently doing nothing.
"""

from __future__ import annotations

from mockymock.analysis.mock_surface import BoundarySite
from mockymock.analysis.refusal import directive_matches_site
from mockymock.dsl.model import MockTestSuite
from mockymock.splicer.naming import TallyRegistry


def build_site_dispatch(
    site: BoundarySite,
    suite: MockTestSuite,
    registry: TallyRegistry,
) -> list[str]:
    """EVALUATE block replacing one mocked boundary statement."""
    lines = ["           EVALUATE UT-CURRENT-CASE"]

    for index, case in enumerate(suite.test_cases, start=1):
        matches = [d for d in case.mocks if directive_matches_site(d, site)]
        if len(matches) > 1:
            raise ValueError(
                f"site at line {site.line} matched by multiple directives of "
                f"test case {index} -- refusal gate should have caught this "
                f"(AMBIGUOUS_MOCK)"
            )
        if not matches:
            continue
        directive = matches[0]
        lines.append(f'               WHEN "{index:03d}"')
        lines.append(
            f"                   ADD 1 TO "
            f"{registry.name(directive.category, directive.key)}"
        )
        lines.extend(f"                   {body}" for body in directive.body_lines)

    lines.append("               WHEN OTHER")
    lines.append(
        f'                   DISPLAY "__MOCKYMOCK__ ERROR: {site.label} '
        f'boundary (line {site.line}) reached "'
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


def build_terminator_neutralization() -> list[str]:
    """Replacement for a STOP RUN/GOBACK statement found safe to
    neutralize (see docs/2026-07-08-goback-stop-run-support-design.md):
    set the early-exit flag and return via EXIT PARAGRAPH -- never GO TO,
    since EXIT PARAGRAPH is the only mechanism verified to correctly
    resume the real PERFORM caller. Identical regardless of which test
    case is running -- unlike build_site_dispatch, no per-case EVALUATE
    UT-CURRENT-CASE dispatch is needed here."""
    return [
        '           MOVE "Y" TO UT-EARLY-EXIT',
        "           EXIT PARAGRAPH",
    ]


def build_chain_check() -> list[str]:
    """Inserted immediately after an intermediate PERFORM statement lying
    on a safe chain toward a neutralized terminator: if the flag is set,
    stop this paragraph too instead of running whatever sibling code
    follows -- propagating the early exit one more level toward the test
    driver. Identical every time it's used; no parameters needed."""
    return [
        '           IF UT-EARLY-EXIT = "Y"',
        "               EXIT PARAGRAPH",
        "           END-IF",
    ]
