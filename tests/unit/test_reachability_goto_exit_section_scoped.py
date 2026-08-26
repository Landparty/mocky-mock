"""Unit tests for the SECTION-scoped GO TO fall-through closure (2026-08-26).

The "GO TO <own-exit-label>" idiom `find_goto_exit_plans`/
`neutralized_goto_targets` handle (see test_reachability_goto_exit.py) only
neutralizes the shape where the exit-only paragraph immediately follows the
ONE enclosing paragraph doing the GO TO. The equally idiomatic mainframe
shape -- several validation paragraphs in the SAME section each doing
`GO TO <shared-section-exit-label>` as an early bailout, e.g.

    2200-VALIDATE-HYPOTHEQUE SECTION.
    2211-VALIDER-HYP-TERME.
        IF invalid GO TO 2200-EXIT END-IF ...
    2212-VALIDER-HYP-TAUX.
        IF invalid GO TO 2200-EXIT END-IF ...
    2200-EXIT.
        EXIT.

    3000-DOWNSTREAM SECTION.
    ...

-- can only have its adjacency check satisfied for the ONE caller
physically right before 2200-EXIT (2212 here); every other caller (2211)
fails it, so find_goto_exit_plans' all-or-nothing rule declines the whole
target and neither GO TO is spliced. Before this fix, `_reachable_paragraphs`
then treated 2200-EXIT's un-neutralized bare-EXIT body as falling through
past the section boundary into 3000-DOWNSTREAM and everything after it --
demanding mocks for boundaries the compiled program can never reach when
entered via `PERFORM 2200-VALIDATE-HYPOTHEQUE` (GnuCOBOL's own implicit
PERFORM-range return fires exactly at the section's own end, regardless of
whether that point is reached by fall-through or by an internal GO TO).
`_fallthrough_safe_sections`/`_walk_fallthrough_from` now recognize this,
but only when the section is provably entered exclusively via `PERFORM
<section-name>` -- never touching what find_goto_exit_plans itself splices.
"""

from cobolparser import parse_cobol
from cobolparser.preprocess import normalize_fixed_format

from mockymock.analysis.mock_surface import analyze
from mockymock.analysis.refusal import (
    _reachable_paragraphs,
    check_test_case,
    find_goto_exit_plans,
    union_executed_paragraphs,
)
from mockymock.dsl.model import MockTestCase
from mockymock.dsl.parser import parse_cut
from mockymock.splicer.source_map import annotate_nested_sites, collect_scope_map

# Two validation paragraphs sharing one section-scoped exit label; only the
# second (2212) is physically adjacent to 2200-EXIT, so find_goto_exit_plans
# must decline the whole target (see test_declines_when_not_every_caller_
# is_adjacent below) -- this is deliberately NOT the shape
# test_reachability_goto_exit.py already covers.
SHARED_SECTION_EXIT_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. VALSECT.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-COND             PIC X VALUE "N".

       PROCEDURE DIVISION.
       2200-VALIDATE-HYPOTHEQUE SECTION.
       2211-VALIDER-HYP-TERME.
           IF WS-COND = "Y"
               GO TO 2200-EXIT
           END-IF
           DISPLAY "TERME OK".

       2212-VALIDER-HYP-TAUX.
           IF WS-COND = "Y"
               GO TO 2200-EXIT
           END-IF
           DISPLAY "TAUX OK".

       2200-EXIT.
           EXIT.

       3000-DOWNSTREAM SECTION.
       3001-DOWNSTREAM-PARA.
           CALL "DOWNSTRM" USING WS-COND.

       9999-ABEND-PROGRAM.
           STOP RUN.
"""


def _analyze(source, name="X.cbl"):
    result = parse_cobol(source, filename=name)
    assert result.success, result.errors
    lines = normalize_fixed_format(source.splitlines()).splitlines()
    surface = analyze(result.ast)
    scope_map = collect_scope_map(result.ast, lines)
    annotate_nested_sites(surface, scope_map, lines)
    return result.ast, surface, scope_map, lines


def _case(perform_target, mocks=None):
    return MockTestCase(name="c", perform_target=perform_target, mocks=mocks or [])


def test_declines_when_not_every_caller_is_adjacent():
    """Confirms this fixture actually exercises the declined shape (not a
    duplicate of the single-adjacent-caller idiom test_reachability_goto_
    exit.py already covers): find_goto_exit_plans must leave both GO TOs
    un-neutralized, with a note explaining why."""
    program, _, scope_map, lines = _analyze(SHARED_SECTION_EXIT_SOURCE)
    plans, notes = find_goto_exit_plans(program, scope_map, lines)
    assert plans == []
    assert any("2200-EXIT" in note for note in notes)


def test_perform_section_name_stops_the_walk_at_the_section_end():
    """The safe, intended entry point: PERFORM <section-name>. Reaching
    2200-EXIT (via GO TO from either validation paragraph) and falling off
    its end must NOT cascade into 3000-DOWNSTREAM/9999-ABEND-PROGRAM --
    GnuCOBOL's own PERFORM-range return fires at the section boundary."""
    program, _, _, _ = _analyze(SHARED_SECTION_EXIT_SOURCE)
    reachable, reasons = _reachable_paragraphs(program, "2200-VALIDATE-HYPOTHEQUE")
    assert reasons == []
    assert "2211-VALIDER-HYP-TERME" in reachable
    assert "2212-VALIDER-HYP-TAUX" in reachable
    assert "2200-EXIT" in reachable
    assert "3001-DOWNSTREAM-PARA" not in reachable
    assert "9999-ABEND-PROGRAM" not in reachable


def test_direct_mid_section_perform_keeps_the_cascade():
    """Negative control (the "shape 3" bypass): a .cut case naming
    2211-VALIDER-HYP-TERME directly, not the section, does NOT actually
    enter via PERFORM <section-name> -- GnuCOBOL's real return marker for
    that specific PERFORM is that one paragraph's own boundary, not the
    section's end, so the relaxation must not apply and the old
    conservative cascade must still fire."""
    program, _, _, _ = _analyze(SHARED_SECTION_EXIT_SOURCE)
    reachable, reasons = _reachable_paragraphs(program, "2211-VALIDER-HYP-TERME")
    assert reasons == []
    assert "3001-DOWNSTREAM-PARA" in reachable
    assert "9999-ABEND-PROGRAM" in reachable


def test_check_test_case_without_the_cascade_needs_no_downstream_mocks():
    program, surface, _, _ = _analyze(SHARED_SECTION_EXIT_SOURCE)
    reasons = check_test_case(surface, program, _case("2200-VALIDATE-HYPOTHEQUE"))
    assert reasons == []


def test_check_test_case_direct_mid_section_perform_still_refuses():
    program, surface, _, _ = _analyze(SHARED_SECTION_EXIT_SOURCE)
    codes = {
        r.code
        for r in check_test_case(surface, program, _case("2211-VALIDER-HYP-TERME"))
    }
    assert "UNMOCKED_CALL" in codes


# --- union_executed_paragraphs -----------------------------------------------

SECTION_ENTRY_CUT = """\
TESTSUITE "section entry"

TESTCASE "via section name"
    PERFORM 2200-VALIDATE-HYPOTHEQUE
"""

MID_SECTION_ENTRY_CUT = """\
TESTSUITE "mid-section entry"

TESTCASE "direct paragraph"
    PERFORM 2211-VALIDER-HYP-TERME
"""


def test_union_executed_paragraphs_excludes_downstream_via_section_entry():
    program, _, _, _ = _analyze(SHARED_SECTION_EXIT_SOURCE)
    union = union_executed_paragraphs(program, parse_cut(SECTION_ENTRY_CUT))
    assert union is not None
    assert "3001-DOWNSTREAM-PARA" not in union


def test_union_executed_paragraphs_keeps_downstream_via_mid_section_entry():
    """Same shape-3 guard as _reachable_paragraphs, applied suite-wide via
    case_seeds: a case naming the member paragraph directly must not waive
    a warning confined to 3001-DOWNSTREAM-PARA."""
    program, _, _, _ = _analyze(SHARED_SECTION_EXIT_SOURCE)
    union = union_executed_paragraphs(program, parse_cut(MID_SECTION_ENTRY_CUT))
    assert union is not None
    assert "3001-DOWNSTREAM-PARA" in union
