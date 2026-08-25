"""Unit tests for the GO-TO-exit reachability narrowing (2026-08-25):
`check_test_case`/`_reachable_paragraphs` consume `neutralized_goto_targets`
so the mock gates agree with the program the splicer actually compiles.

Before this wiring, the idiomatic mainframe early-return shape

    2212-VALIDATE. ... GO TO 2212-EXIT ...
    2212-EXIT. EXIT.
    2213-NEXT. <real work, boundaries>
    ...

made the reachability BFS treat 2212-EXIT as a live GO TO target whose
bare-EXIT body falls through into 2213-NEXT and cascades to the end of the
program -- demanding mocks for every boundary on the way, even though the
splicer (run/export/debug/mutate) replaces that exact GO TO with EXIT
PARAGRAPH and the compiled test can never execute any of it. Mirrors
tests/unit/test_goto_exit.py's harness. STATUS note: the underlying splice
is implemented but not yet verified against real GnuCOBOL; these are
structural/unit tests of the static gates only.
"""

from cobolparser import parse_cobol
from cobolparser.preprocess import normalize_fixed_format

from mockymock.analysis.mock_surface import analyze
from mockymock.analysis.refusal import (
    _reachable_paragraphs,
    check_test_case,
    neutralized_goto_targets,
)
from mockymock.dsl.model import MockTestCase
from mockymock.splicer.source_map import annotate_nested_sites, collect_scope_map

# The screenshot shape, miniaturized: a validation paragraph early-returns
# via GO TO to its own adjacent exit label; real boundary-carrying
# paragraphs follow in source order all the way to the terminator.
EARLY_RETURN_CASCADE_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CASCADE.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-COND             PIC X VALUE "N".

       PROCEDURE DIVISION.
       2212-VALIDATE.
           IF WS-COND = "Y"
               GO TO 2212-EXIT
           END-IF
           DISPLAY "VALIDATED".

       2212-EXIT.
           EXIT.

       2213-DOWNSTREAM.
           CALL "DOWNSTRM" USING WS-COND.

       9999-ABEND-PROGRAM.
           STOP RUN.
"""

# Negative control: identical, except a computed GO TO elsewhere also names
# 2212-EXIT -- find_goto_exit_plans must decline the whole target, so the
# cascade legitimately stays reachable (the compiled program keeps a real
# GO TO edge into 2212-EXIT).
COMPUTED_ALIAS_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CASCADEALIAS.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-COND             PIC X VALUE "N".
       01  WS-N                PIC 9 VALUE 9.

       PROCEDURE DIVISION.
       2212-VALIDATE.
           IF WS-COND = "Y"
               GO TO 2212-EXIT
           END-IF
           DISPLAY "VALIDATED".

       2212-EXIT.
           EXIT.

       2213-DOWNSTREAM.
           CALL "DOWNSTRM" USING WS-COND.

       9999-ABEND-PROGRAM.
           STOP RUN.

       9998-DISPATCH.
           GO TO 2212-EXIT 2213-DOWNSTREAM DEPENDING ON WS-N.
"""


def _analyze(source, name="X.cbl"):
    result = parse_cobol(source, filename=name)
    assert result.success, result.errors
    lines = normalize_fixed_format(source.splitlines()).splitlines()
    surface = analyze(result.ast)
    scope_map = collect_scope_map(result.ast, lines)
    annotate_nested_sites(surface, scope_map, lines)
    return result.ast, surface, scope_map, lines


def _case(perform_target="2212-VALIDATE", mocks=None):
    return MockTestCase(name="c", perform_target=perform_target, mocks=mocks or [])


# --- neutralized_goto_targets ------------------------------------------------


def test_neutralized_goto_targets_names_the_fully_covered_exit_label():
    program, _, scope_map, lines = _analyze(EARLY_RETURN_CASCADE_SOURCE)
    assert neutralized_goto_targets(program, scope_map, lines) == frozenset(
        {"2212-EXIT"}
    )


def test_neutralized_goto_targets_empty_when_a_computed_goto_aliases_the_label():
    program, _, scope_map, lines = _analyze(COMPUTED_ALIAS_SOURCE)
    assert neutralized_goto_targets(program, scope_map, lines) == frozenset()


# --- _reachable_paragraphs ---------------------------------------------------


def test_unnarrowed_walk_still_cascades_past_the_exit_label():
    """Pin the pre-existing conservative behavior: with no narrowing, the
    bare-EXIT landing pad falls through into everything downstream."""
    program, _, _, _ = _analyze(EARLY_RETURN_CASCADE_SOURCE)
    reachable, reasons = _reachable_paragraphs(program, "2212-VALIDATE")
    assert reasons == []
    assert "2213-DOWNSTREAM" in reachable
    assert "9999-ABEND-PROGRAM" in reachable


def test_narrowed_walk_stops_at_the_neutralized_exit_label():
    program, _, scope_map, lines = _analyze(EARLY_RETURN_CASCADE_SOURCE)
    neutralized = neutralized_goto_targets(program, scope_map, lines)
    reachable, reasons = _reachable_paragraphs(
        program, "2212-VALIDATE", neutralized_goto=neutralized
    )
    assert reasons == []
    assert "2212-VALIDATE" in reachable
    # The spliced GO TO is not an edge, and the exit label no longer seeds
    # the fall-through closure -- nothing downstream is reachable.
    assert "2213-DOWNSTREAM" not in reachable
    assert "9999-ABEND-PROGRAM" not in reachable


def test_narrowed_walk_keeps_a_thru_declared_exit_label_reachable():
    """PERFORM 2212-VALIDATE THRU 2212-EXIT still covers the label via the
    THRU slice -- narrowing removes the GO TO edge and the fall-through
    cascade, never the driver's own declared range."""
    program, _, scope_map, lines = _analyze(EARLY_RETURN_CASCADE_SOURCE)
    neutralized = neutralized_goto_targets(program, scope_map, lines)
    reachable, reasons = _reachable_paragraphs(
        program, "2212-VALIDATE", "2212-EXIT", neutralized_goto=neutralized
    )
    assert reasons == []
    assert "2212-EXIT" in reachable
    assert "2213-DOWNSTREAM" not in reachable


def test_narrowed_walk_still_cascades_when_the_label_is_not_neutralizable():
    program, _, scope_map, lines = _analyze(COMPUTED_ALIAS_SOURCE)
    neutralized = neutralized_goto_targets(program, scope_map, lines)
    reachable, reasons = _reachable_paragraphs(
        program, "2212-VALIDATE", neutralized_goto=neutralized
    )
    assert reasons == []
    assert "2213-DOWNSTREAM" in reachable
    assert "9999-ABEND-PROGRAM" in reachable


# --- check_test_case ---------------------------------------------------------


def test_check_test_case_without_narrowing_demands_the_cascades_mocks():
    """Pin the old behavior at the gate level: the downstream CALL refuses
    UNMOCKED_CALL even though the compiled test never reaches it."""
    program, surface, _, _ = _analyze(EARLY_RETURN_CASCADE_SOURCE)
    codes = {r.code for r in check_test_case(surface, program, _case())}
    assert "UNMOCKED_CALL" in codes


def test_check_test_case_with_narrowing_needs_no_cascade_mocks():
    program, surface, scope_map, lines = _analyze(EARLY_RETURN_CASCADE_SOURCE)
    neutralized = neutralized_goto_targets(program, scope_map, lines)
    reasons = check_test_case(surface, program, _case(), neutralized_goto=neutralized)
    assert reasons == []


def test_check_test_case_with_narrowing_still_refuses_the_aliased_shape():
    """Negative control: when find_goto_exit_plans declines the target,
    the gate keeps demanding the cascade's mocks -- the narrowing is
    gated on the splice actually happening, not vacuously permissive."""
    program, surface, scope_map, lines = _analyze(COMPUTED_ALIAS_SOURCE)
    neutralized = neutralized_goto_targets(program, scope_map, lines)
    codes = {
        r.code
        for r in check_test_case(
            surface, program, _case(), neutralized_goto=neutralized
        )
    }
    assert "UNMOCKED_CALL" in codes
