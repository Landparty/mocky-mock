"""Issue #349: mutants provably equivalent to the original program are
recognized before they are built, reported as `equivalent`, and left out
of the score."""

from __future__ import annotations

import pytest

from mockymock.mutation.equivalence import equivalence_reason
from mockymock.mutation.operators import generate_mutants
from mockymock.mutation.report import MutantResult, MutationOutcome, to_json_dict

PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. EQUIV.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-FLAG PIC X.
           88  WS-FLAG-YES VALUE "Y".
           88  WS-FLAG-NO  VALUE "N".
       01  WS-OTHER PIC X.
       01  WS-COUNT PIC 9(3) COMP-3.
       01  WS-SIGNED PIC S9(3).
       01  WS-GROUP.
           05  WS-PART PIC X(2).
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE "N" TO WS-FLAG
           SET WS-FLAG-YES TO TRUE
           MOVE 0 TO WS-COUNT
           ADD 1 TO WS-COUNT
           MOVE 0 TO WS-SIGNED
           ADD 1 TO WS-SIGNED
           MOVE "N" TO WS-OTHER
           MOVE WS-OTHER TO WS-FLAG
           MOVE "AB" TO WS-PART
           MOVE SPACES TO WS-GROUP
           ADD 1 TO WS-COUNT
           IF WS-FLAG-YES
               MOVE 0 TO WS-COUNT.
           ADD 1 TO WS-COUNT.
           STOP RUN.
"""


@pytest.fixture(scope="module")
def parsed():
    from cobolparser import parse_cobol

    lines = PROGRAM.splitlines()
    return lines, parse_cobol(PROGRAM, filename="EQUIV.cbl").ast


def _reason(parsed, line: int, operator: str) -> str:
    lines, ast = parsed
    (mutant,) = [
        m
        for m in generate_mutants(lines)
        if m.line == line
        and m.operator == operator
        and (operator != "arith-verb-swap" or "SUBTRACT" in m.description.upper())
    ]
    return equivalence_reason(mutant, lines, ast)


def test_a_move_overwritten_by_setting_its_88_is_equivalent(parsed):
    """`MOVE "N" TO WS-FLAG` then `SET WS-FLAG-YES TO TRUE`."""
    reason = _reason(parsed, 15, "stmt-delete")
    assert reason.startswith("equivalent: line 16")


def test_zero_then_add_on_an_unsigned_field_is_equivalent(parsed):
    assert "unsigned" in _reason(parsed, 18, "arith-verb-swap")


def test_zero_then_add_on_a_signed_field_is_not(parsed):
    assert _reason(parsed, 20, "arith-verb-swap") == ""


def test_a_move_whose_value_the_next_statement_reads_is_not(parsed):
    """`MOVE "N" TO WS-OTHER` then `MOVE WS-OTHER TO WS-FLAG`."""
    assert _reason(parsed, 21, "stmt-delete") == ""


def test_a_group_move_covers_its_subordinate(parsed):
    """`MOVE "AB" TO WS-PART` then `MOVE SPACES TO WS-GROUP`."""
    assert _reason(parsed, 23, "stmt-delete").startswith("equivalent")


def test_an_add_without_zeroing_right_before_is_not(parsed):
    assert _reason(parsed, 25, "arith-verb-swap") == ""


def test_zeroing_inside_an_if_its_period_closes_is_not(parsed):
    """`IF ... MOVE 0 TO WS-COUNT.` then `ADD 1 TO WS-COUNT.`: the zeroing
    only runs on one path."""
    assert _reason(parsed, 28, "arith-verb-swap") == ""


def test_equivalent_mutants_are_reported_but_not_scored():
    from mockymock.mutation.operators import Mutant

    def mutant(line):
        return Mutant(line, "stmt-delete", "x", "y", "delete MOVE statement")

    outcome = MutationOutcome(program="P", cut="C")
    outcome.results = [
        MutantResult(mutant(1), "killed"),
        MutantResult(mutant(2), "equivalent", detail="equivalent: why", ran=False),
    ]
    assert outcome.score == 1.0
    assert outcome.not_compiled == 0
    data = to_json_dict(outcome)
    assert data["totals"]["equivalent"] == 1
    assert data["mutants"][1]["status"] == "equivalent"
