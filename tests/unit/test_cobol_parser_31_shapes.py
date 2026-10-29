"""The bundle and AST shapes cobol-parser 3.1 changed, checked directly so
they hold whichever cobol-parser is installed: per-(category, key)
`call_count`s (cobol-parser #363) and quoted literal CALL arguments."""

from __future__ import annotations

from cobolparser import parse_cobol

from mockymock.analysis.mock_surface import analyze
from mockymock.dsl.fixture_bundle import (
    BoundaryFixture,
    Expectation,
    FixtureBundle,
    Scenario,
)
from mockymock.dsl.generator import _with_site_call_counts
from mockymock.splicer.injector import _call_using_literals, reported_literal

PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SHAPES.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-FILE ASSIGN TO "IN".
       DATA DIVISION.
       FILE SECTION.
       FD  IN-FILE.
       01  IN-REC PIC X(5).
       WORKING-STORAGE SECTION.
       01  WS-N PIC 9.
       PROCEDURE DIVISION.
       MAIN-PARA.
           CALL "SUB" USING WS-N
           READ IN-FILE
               AT END MOVE 1 TO WS-N
           END-READ
           GOBACK.
"""


def _surface():
    return analyze(parse_cobol(PROGRAM, filename="shapes.cbl").ast)


def _fixture(category: str, key: str, line: int, rows: int) -> BoundaryFixture:
    return BoundaryFixture(
        category=category,
        key=key,
        paragraph="MAIN-PARA",
        line=line,
        direction="IN",
        sequence=[{"IN-REC": "AAAAA"}] * rows,
    )


def _counts(scenario: Scenario) -> dict[str, int]:
    return {e.ref: e.value for e in scenario.expectations if e.kind == "call_count"}


def _bundle(*scenarios: Scenario) -> FixtureBundle:
    return FixtureBundle(
        bundle_version=1, program_name="SHAPES", seed=1, scenarios=list(scenarios)
    )


def test_an_uncounted_key_gets_its_per_site_counts_back() -> None:
    scenario = Scenario(
        name="happy path",
        fixtures=[_fixture("CALL", "SUB", 15, 1), _fixture("READ", "IN-FILE", 16, 3)],
    )
    (out,) = _with_site_call_counts(_bundle(scenario), _surface()).scenarios
    # A CALL counts once; a READ with AT END counts its rows plus the read
    # that hits end of file.
    assert _counts(out) == {"CALL:SUB": 1, "READ:IN-FILE": 4}


def test_a_count_the_bundle_wrote_is_kept() -> None:
    scenario = Scenario(
        name="happy path",
        fixtures=[_fixture("CALL", "SUB", 15, 1)],
        expectations=[Expectation(kind="call_count", ref="CALL:SUB", value=3)],
    )
    (out,) = _with_site_call_counts(_bundle(scenario), _surface()).scenarios
    assert out.expectations == scenario.expectations


def test_an_error_status_scenario_is_left_uncounted() -> None:
    scenario = Scenario(
        name="error status: CALL SUB ON EXCEPTION",
        fixtures=[_fixture("CALL", "SUB", 15, 1)],
    )
    (out,) = _with_site_call_counts(_bundle(scenario), _surface()).scenarios
    assert _counts(out) == {}


def test_a_quoted_name_is_a_reported_literal() -> None:
    assert reported_literal('"D\'E"') == '"D\'E"'
    assert reported_literal('X"C1"') == 'X"C1"'
    assert reported_literal("WS-N") is None
    assert reported_literal("42") is None


def test_the_text_scan_accepts_either_release_spelling() -> None:
    text = "CALL \"SUB\" USING BY CONTENT 'D''E' WS-N"
    expected = ["'D''E'", None]
    assert _call_using_literals(text, ["D'E", "WS-N"]) == expected  # before 3.1
    assert _call_using_literals(text, ['"D\'E"', "WS-N"]) == expected  # 3.1
