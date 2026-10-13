"""`mutation.zero_baseline`: an ADD/SUBTRACT swap on an unsigned field that
every test case starts at zero stores the same magnitude either way, so
it survives whatever the assertions say. Such survivors get a hint that
names the field and says to seed it, rather than reading as a missing
assertion."""

from __future__ import annotations

import pytest
from cobolparser import parse_cobol

import mockymock.mutation.runner as runner
from mockymock.dsl.parser import parse_cut
from mockymock.mutation.operators import Mutant, generate_mutants
from mockymock.mutation.report import (
    MutantResult,
    MutationOutcome,
    format_console,
    to_json_dict,
)
from mockymock.mutation.runner import SuiteRun
from mockymock.mutation.zero_baseline import zero_baseline_hint
from mockymock.runtime import docker_toolchain

PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CNTPROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-PURGED        PIC 9(5) COMP-3 VALUE ZERO.
       01  WS-KEPT          PIC 9(5) COMP-3.
       01  WS-SEEDED        PIC 9(5) COMP-3 VALUE 0.
       01  WS-SIGNED        PIC S9(5) COMP-3 VALUE 0.
       01  WS-STARTS-AT-5   PIC 9(5) COMP-3 VALUE 5.
       01  WS-TOTAL         PIC 9(5) VALUE 0.
       01  WS-EDITED        PIC ZZZZ9.
       01  WS-TEXT          PIC X(5).
       PROCEDURE DIVISION.
       MAIN-PARA.
           ADD 1 TO WS-PURGED
           SUBTRACT 1 FROM WS-KEPT
           ADD 1 TO WS-SEEDED
           ADD 1 TO WS-SIGNED
           ADD 1 TO WS-STARTS-AT-5
           ADD WS-PURGED TO WS-KEPT GIVING WS-TOTAL
           ADD 1 TO WS-PURGED WS-SIGNED
           GOBACK.
"""

CUT = """\
TESTSUITE "CNTPROG"

TESTCASE "counts"
    MOVE 3 TO WS-SEEDED
    PERFORM MAIN-PARA
    EXPECT WS-PURGED TO BE 1
"""


@pytest.fixture(scope="module")
def ast():
    result = parse_cobol(PROGRAM, filename="CNTPROG.cbl")
    assert result.success, result.errors
    return result.ast


@pytest.fixture(scope="module")
def suite():
    return parse_cut(CUT)


def _swap_on(text: str) -> Mutant:
    lines = PROGRAM.splitlines()
    for mutant in generate_mutants(lines):
        if mutant.operator == "arith-verb-swap" and text in mutant.original:
            return mutant
    raise AssertionError(f"no arith-verb-swap mutant on a line containing {text!r}")


def test_add_on_unsigned_zero_start_counter_gets_a_hint(ast, suite):
    hint = zero_baseline_hint(_swap_on("ADD 1 TO WS-PURGED"), ast, suite)
    assert "WS-PURGED" in hint
    assert "untestable" in hint
    assert "MOVE 5 TO WS-PURGED" in hint


def test_subtract_on_field_with_no_value_clause_counts_as_zero_start(ast, suite):
    # reset.py resets a numeric item without VALUE to ZERO between cases.
    hint = zero_baseline_hint(_swap_on("SUBTRACT 1 FROM WS-KEPT"), ast, suite)
    assert "WS-KEPT" in hint


@pytest.mark.parametrize(
    "line",
    [
        "ADD 1 TO WS-SEEDED",  # a test case MOVEs a value into it
        "ADD 1 TO WS-SIGNED",  # signed: 0 - 1 stores -1, distinguishable
        "ADD 1 TO WS-STARTS-AT-5",  # VALUE 5: 6 vs 4
        "GIVING WS-TOTAL",  # GIVING form: receiving field is not the addend
        "ADD 1 TO WS-PURGED WS-SIGNED",  # one target is signed
    ],
)
def test_no_hint_when_the_field_can_tell_add_from_subtract(ast, suite, line):
    assert zero_baseline_hint(_swap_on(line), ast, suite) == ""


def test_seeding_through_a_mock_body_or_rows_suppresses_the_hint(ast):
    seeded = parse_cut("""\
TESTSUITE "CNTPROG"

TESTCASE "counts"
    MOCK PARAGRAPH OTHER-PARA
        MOVE 7 TO WS-PURGED
    END-MOCK
    PERFORM MAIN-PARA
""")
    assert zero_baseline_hint(_swap_on("ADD 1 TO WS-PURGED"), ast, seeded) == ""


@pytest.mark.parametrize("hook", ["BEFORE-ALL", "BEFORE-EACH"])
def test_seeding_through_a_before_hook_move_suppresses_the_hint(ast, hook):
    seeded = parse_cut(f"""\
TESTSUITE "CNTPROG"

{hook}
    MOVE 7 TO WS-PURGED
END-BEFORE

TESTCASE "counts"
    PERFORM MAIN-PARA
""")
    assert zero_baseline_hint(_swap_on("ADD 1 TO WS-PURGED"), ast, seeded) == ""


def test_other_operators_never_get_a_hint(ast, suite):
    mutant = Mutant(
        line=15,
        operator="stmt-delete",
        original="           ADD 1 TO WS-PURGED",
        mutated="           CONTINUE",
        description="delete statement",
    )
    assert zero_baseline_hint(mutant, ast, suite) == ""


def test_console_and_json_carry_the_hint():
    mutant = _swap_on("ADD 1 TO WS-PURGED")
    outcome = MutationOutcome(
        program="CNTPROG.cbl",
        cut="CNTPROG.cut",
        results=[MutantResult(mutant=mutant, status="survived", hint="seed it")],
    )
    text = format_console(outcome)
    assert "    ! seed it" in text
    assert "1 of those survivors cannot be killed from the test data" in text
    # Still scored as a survivor: seeding the field is how it gets killed.
    assert outcome.score == 0.0
    assert to_json_dict(outcome)["mutants"][0]["hint"] == "seed it"


def test_run_mutation_attaches_hints_to_built_survivors_only(monkeypatch, tmp_path):
    program = tmp_path / "CNTPROG.cbl"
    program.write_text(PROGRAM)
    cut = tmp_path / "CNTPROG.cut"
    cut.write_text(CUT)
    monkeypatch.setattr(docker_toolchain, "ensure_toolchain", lambda: None)
    built = _swap_on("ADD 1 TO WS-PURGED")
    gated = _swap_on("SUBTRACT 1 FROM WS-KEPT")
    monkeypatch.setattr(runner, "generate_mutants", lambda lines: [built, gated])

    def fake_run_suite_once(source_text, source_name, cut_path, cb, timeout, **kw):
        if source_text == PROGRAM:
            return SuiteRun("passed", "", coverage={gated.line: False})
        return SuiteRun("passed", "")  # the mutant survived

    monkeypatch.setattr(runner, "_run_suite_once", fake_run_suite_once)
    problems, outcome, _ = runner.run_mutation(program, cut, None)
    assert problems == []
    assert outcome is not None
    by_line = {r.mutant.line: r for r in outcome.results}
    assert "WS-PURGED" in by_line[built.line].hint
    assert by_line[gated.line].ran is False
    assert by_line[gated.line].hint == ""


UNASSERTED_PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CNTPROG2.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-READ-COUNT    PIC 9(5) COMP-3 VALUE ZERO.
       01  WS-FLOWS         PIC 9(5) COMP-3 VALUE ZERO.
       01  WS-OUT           PIC 9(5) VALUE ZERO.
       01  WS-TOTALS.
           05  WS-IN-GROUP  PIC 9(5) COMP-3 VALUE ZERO.
       PROCEDURE DIVISION.
       MAIN-PARA.
           ADD 1 TO WS-READ-COUNT
           ADD 1 TO WS-READ-COUNT
           ADD 1 TO WS-FLOWS
           ADD 1 TO WS-IN-GROUP
           MOVE WS-FLOWS TO WS-OUT
           DISPLAY "RECORDS READ: " WS-READ-COUNT
           GOBACK.
"""

UNASSERTED_CUT = """\
TESTSUITE "CNTPROG2"

TESTCASE "runs"
    PERFORM MAIN-PARA
    EXPECT WS-OUT TO BE 1
    EXPECT WS-TOTALS TO BE "00001"
"""


def _swap_in(program: str, text: str) -> Mutant:
    for mutant in generate_mutants(program.splitlines()):
        if mutant.operator == "arith-verb-swap" and text in mutant.original:
            return mutant
    raise AssertionError(f"no arith-verb-swap mutant on a line containing {text!r}")


@pytest.fixture(scope="module")
def unasserted_ast():
    result = parse_cobol(UNASSERTED_PROGRAM, filename="CNTPROG2.cbl")
    assert result.success, result.errors
    return result.ast


def test_no_hint_when_nothing_observes_the_field(unasserted_ast):
    """WS-READ-COUNT is only ever incremented and DISPLAYed: no EXPECT
    names it and nothing the suite can see reads it. Seeding it would not
    kill the swap either -- the survivor is a missing assertion, and a
    hint calling it untestable (filed as `untestable-mutant` instead of
    `missing-assertion` by `mockymock report`) sends the author to the
    wrong fix."""
    mutant = _swap_in(UNASSERTED_PROGRAM, "ADD 1 TO WS-READ-COUNT")
    assert zero_baseline_hint(mutant, unasserted_ast, parse_cut(UNASSERTED_CUT)) == ""


@pytest.mark.parametrize(
    "line",
    [
        "ADD 1 TO WS-FLOWS",  # MOVEd into WS-OUT, which a case asserts
        "ADD 1 TO WS-IN-GROUP",  # its group WS-TOTALS is asserted
    ],
)
def test_hint_kept_when_the_field_is_observed(unasserted_ast, line):
    mutant = _swap_in(UNASSERTED_PROGRAM, line)
    hint = zero_baseline_hint(mutant, unasserted_ast, parse_cut(UNASSERTED_CUT))
    assert "untestable" in hint
