"""Unit tests for mutation site discovery -- pure text level, no Docker."""

from mockymock.mutation.operators import generate_mutants


def _procedure(*statements: str) -> list[str]:
    return [
        "       IDENTIFICATION DIVISION.",
        "       PROGRAM-ID. SAMPLE.",
        "       PROCEDURE DIVISION.",
        "       MAIN-PARA.",
        *statements,
    ]


def _ops(mutants):
    return sorted({m.operator for m in mutants})


def test_no_mutants_before_procedure_division():
    lines = [
        "       IDENTIFICATION DIVISION.",
        "       PROGRAM-ID. SAMPLE.",
        "       DATA DIVISION.",
        "       WORKING-STORAGE SECTION.",
        "       01 WS-A PIC 9(4) VALUE 3.",
    ]
    assert generate_mutants(lines) == []


def test_rel_swap_in_condition_line():
    mutants = generate_mutants(_procedure("           PERFORM CALC UNTIL WS-I > 4"))
    swaps = [m for m in mutants if m.operator == "rel-swap"]
    assert len(swaps) == 1
    assert swaps[0].mutated == "           PERFORM CALC UNTIL WS-I >= 4"
    assert swaps[0].line == 5


def test_compound_symbol_not_double_mutated():
    mutants = generate_mutants(_procedure("           IF WS-I >= 4"))
    swaps = [m for m in mutants if m.operator == "rel-swap"]
    # `>=` -> `>` only; the bare-`>` swap must not also fire on the same
    # characters and produce `>>=`.
    assert [m.mutated for m in swaps] == ["           IF WS-I > 4"]


def test_rel_symbol_outside_condition_context_is_ignored():
    # No IF/UNTIL/WHEN on the line: nothing to swap even though `>` occurs.
    mutants = generate_mutants(_procedure('           DISPLAY "A > B"'))
    assert [m for m in mutants if m.operator == "rel-swap"] == []


def test_literal_and_inline_comment_are_not_sites():
    mutants = generate_mutants(
        _procedure('           IF WS-MSG = "X > Y" *> checks > marker')
    )
    assert [m for m in mutants if m.operator == "rel-swap"] == []


def test_arith_verb_swap_rewrites_preposition():
    mutants = generate_mutants(_procedure("           ADD 2 TO WS-TOTAL"))
    swaps = [m for m in mutants if m.operator == "arith-verb-swap"]
    assert [m.mutated for m in swaps] == ["           SUBTRACT 2 FROM WS-TOTAL"]


def test_move_integer_literal_is_incremented():
    mutants = generate_mutants(_procedure("           MOVE 0 TO WS-TOTAL."))
    moves = [m for m in mutants if m.operator == "move-literal"]
    assert [m.mutated for m in moves] == ["           MOVE 1 TO WS-TOTAL."]


def test_boundary_literal_incremented_in_condition():
    mutants = generate_mutants(_procedure("           PERFORM CALC UNTIL WS-I > 4"))
    boundaries = [m for m in mutants if m.operator == "boundary-literal"]
    assert [m.mutated for m in boundaries] == ["           PERFORM CALC UNTIL WS-I > 5"]


def test_statement_deletion_preserves_indent_and_period():
    mutants = generate_mutants(_procedure("           MOVE 0 TO WS-TOTAL."))
    deletions = [m for m in mutants if m.operator == "stmt-delete"]
    assert [m.mutated for m in deletions] == ["           CONTINUE."]


def test_statement_without_period_deletes_without_period():
    mutants = generate_mutants(_procedure("               ADD 2 TO WS-TOTAL"))
    deletions = [m for m in mutants if m.operator == "stmt-delete"]
    assert [m.mutated for m in deletions] == ["               CONTINUE"]


def test_boundary_verbs_exclude_the_whole_line():
    mutants = generate_mutants(
        _procedure(
            '           CALL "SUBPGM" USING WS-TOTAL',
            "           READ INV-FILE",
            "           STOP RUN.",
            "           GOBACK.",
        )
    )
    assert mutants == []


def test_scope_carrying_lines_are_never_deleted():
    mutants = generate_mutants(_procedure("           MOVE 1 TO WS-A IF WS-B > 2"))
    assert [m for m in mutants if m.operator == "stmt-delete"] == []


def test_comment_lines_are_ignored():
    mutants = generate_mutants(
        _procedure(
            "      * MOVE 0 TO WS-TOTAL.",
            "           *> MOVE 0 TO WS-TOTAL.",
        )
    )
    assert mutants == []


def test_fixture_yields_expected_mutant_set():
    """Pin the exact mutant population of the integration fixture so the
    Docker-gated kill-loop test's expectations stay explainable."""
    from pathlib import Path

    fixture = (
        Path(__file__).parent.parent
        / "integration"
        / "fixtures"
        / "mutation_target.cbl"
    )
    mutants = generate_mutants(fixture.read_text(encoding="utf-8").splitlines())
    assert [(m.line, m.operator) for m in mutants] == [
        (9, "move-literal"),
        (9, "stmt-delete"),
        (10, "rel-swap"),
        (10, "boundary-literal"),
        (11, "arith-verb-swap"),
        (11, "stmt-delete"),
    ]
