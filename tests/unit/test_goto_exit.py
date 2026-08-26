"""Unit tests for the GO-TO-to-EXIT-PARAGRAPH simplification (see
docs/2026-08-17-goto-exit-paragraph-simplification-design.md).
STATUS: this feature is implemented but not yet verified against real
GnuCOBOL -- these are structural/unit tests only, mirroring
tests/unit/test_terminators.py's style (the analysis functions and the
splice output are tested together since they're always used together).
"""

from cobolparser import parse_cobol
from cobolparser.preprocess import normalize_fixed_format

from mockymock.analysis.mock_surface import analyze
from mockymock.analysis.refusal import (
    GotoExitPlan,
    _is_exit_only_paragraph,
    find_goto_exit_plans,
    find_terminator_plans,
)
from mockymock.dsl.model import MockTestCase, MockTestSuite
from mockymock.splicer.naming import TallyRegistry
from mockymock.splicer.orchestrator import splice_program
from mockymock.splicer.source_map import (
    annotate_nested_sites,
    collect_boundaries,
    collect_scope_map,
)

# --- shared fixtures -------------------------------------------------------

SAFE_GOTO_EXIT_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. GOTOEXIT.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-COND             PIC X VALUE "N".

       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           PERFORM 1000-DO-WORK
           IF WS-COND = "Y"
               GO TO 0000-MAIN-EXIT
           END-IF
           PERFORM 2000-TERMINATE.

       0000-MAIN-EXIT.
           EXIT.

       1000-DO-WORK.
           DISPLAY "WORK".

       2000-TERMINATE.
           STOP RUN.
"""

COMPUTED_GOTO_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. COMPUTEDGOTO.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-N                PIC 9 VALUE 9.

       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           GO TO 0000-MAIN-EXIT 1000-DO-WORK DEPENDING ON WS-N.

       0000-MAIN-EXIT.
           EXIT.

       1000-DO-WORK.
           DISPLAY "WORK".
"""

UNSAFE_ENCLOSING_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. UNSAFEENCLOSE.

       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           PERFORM 1000-ALIAS.

       0000-MAIN-EXIT.
           EXIT.

       1000-ALIAS.
           GO TO 0000-MAIN-EXIT.

       1000-DO-WORK.
           GO TO 1000-ALIAS.
"""

SHARED_LINE_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. GOTOSHARED.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A                PIC 9.

       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           MOVE 1 TO WS-A GO TO 0000-MAIN-EXIT.

       0000-MAIN-EXIT.
           EXIT.
"""

MIXED_SAFETY_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. GOTOMIXED.

       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           PERFORM 1000-SAFE-SITE
           PERFORM 1000-UNSAFE-SITE.

       0000-MAIN-EXIT.
           EXIT.

       1000-SAFE-SITE.
           GO TO 0000-MAIN-EXIT.

       1000-UNSAFE-SITE.
           GO TO 0000-MAIN-EXIT.

       1000-ALIAS.
           GO TO 1000-UNSAFE-SITE.
"""

SECTION_ENTRY_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. GOTOSECTION.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-COND             PIC X VALUE "N".

       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           PERFORM 1000-WORK-SECTION.

       1000-WORK-SECTION SECTION.
       1000-ENTRY.
           IF WS-COND = "Y"
               GO TO 1000-EXIT
           END-IF
           DISPLAY "WORK".
       1000-EXIT.
           EXIT.
"""


def _analyze(source, name="X.cbl"):
    result = parse_cobol(source, filename=name)
    assert result.success, result.errors
    lines = normalize_fixed_format(source.splitlines()).splitlines()
    surface = analyze(result.ast)
    scope_map = collect_scope_map(result.ast, lines)
    annotate_nested_sites(surface, scope_map, lines)
    return result.ast, surface, scope_map, lines


def _paragraph(program, name):
    procedure = program.get_division("PROCEDURE")
    for p in procedure.paragraphs:
        if p.paragraph_name == name:
            return p
    for section in getattr(procedure, "_sections", {}).values():
        for p in section.paragraphs:
            if p.paragraph_name == name:
                return p
    raise AssertionError(f"paragraph {name!r} not found")


def _suite(perform_target="0000-MAIN-PROCESS"):
    case = MockTestCase(name="c", perform_target=perform_target)
    return MockTestSuite(name="S", test_cases=[case])


# --- _is_exit_only_paragraph -----------------------------------------------


def test_is_exit_only_paragraph_true_for_bare_exit():
    program, _, _, _ = _analyze(SAFE_GOTO_EXIT_SOURCE)
    assert _is_exit_only_paragraph(_paragraph(program, "0000-MAIN-EXIT")) is True


def test_is_exit_only_paragraph_false_for_exit_paragraph():
    source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. NOTEXITONLY.

       PROCEDURE DIVISION.
       P1.
           EXIT PARAGRAPH.
"""
    program, _, _, _ = _analyze(source)
    assert _is_exit_only_paragraph(_paragraph(program, "P1")) is False


def test_is_exit_only_paragraph_false_with_extra_statement():
    source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. NOTEXITONLY2.

       PROCEDURE DIVISION.
       P1.
           DISPLAY "X"
           EXIT.
"""
    program, _, _, _ = _analyze(source)
    assert _is_exit_only_paragraph(_paragraph(program, "P1")) is False


def test_is_exit_only_paragraph_false_for_empty_body():
    source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. EMPTYBODY.

       PROCEDURE DIVISION.
       P1.
       P2.
           STOP RUN.
"""
    program, _, _, _ = _analyze(source)
    assert _is_exit_only_paragraph(_paragraph(program, "P1")) is False


# --- find_goto_exit_plans ----------------------------------------------------


def test_find_goto_exit_plans_accepts_the_textbook_idiom():
    program, _, scope_map, lines = _analyze(SAFE_GOTO_EXIT_SOURCE)
    plans, notes = find_goto_exit_plans(program, scope_map, lines)
    assert notes == []
    assert len(plans) == 1
    plan = plans[0]
    assert isinstance(plan, GotoExitPlan)
    assert plan.paragraph_name == "0000-MAIN-PROCESS"
    assert plan.exit_kind == "PARAGRAPH"


def test_find_goto_exit_plans_ignores_computed_goto():
    program, _, scope_map, lines = _analyze(COMPUTED_GOTO_SOURCE)
    plans, notes = find_goto_exit_plans(program, scope_map, lines)
    assert plans == []
    assert notes == []


def test_find_goto_exit_plans_declines_when_enclosing_paragraph_is_a_goto_target():
    program, _, scope_map, lines = _analyze(UNSAFE_ENCLOSING_SOURCE)
    plans, notes = find_goto_exit_plans(program, scope_map, lines)
    assert plans == []
    assert len(notes) == 1
    assert "0000-MAIN-EXIT" in notes[0]
    assert "1000-ALIAS" in notes[0]


def test_find_goto_exit_plans_declines_when_goto_shares_its_line():
    program, _, scope_map, lines = _analyze(SHARED_LINE_SOURCE)
    plans, notes = find_goto_exit_plans(program, scope_map, lines)
    assert plans == []
    assert len(notes) == 1
    assert "does not start its own line" in notes[0]


def test_find_goto_exit_plans_is_all_or_nothing_per_target():
    """One unsafe site sharing a target with a safe one leaves BOTH
    untouched -- _go_to_targets is a whole-program property, so partially
    neutralizing a target paragraph would leave it exactly as hazardous
    as before."""
    program, _, scope_map, lines = _analyze(MIXED_SAFETY_SOURCE)
    plans, notes = find_goto_exit_plans(program, scope_map, lines)
    assert plans == []
    assert len(notes) == 1
    assert "2 site(s)" in notes[0]


def test_find_goto_exit_plans_resolves_a_transitive_fallthrough_chain():
    """Regression pin for a real bug: three back-to-back validation-style
    paragraphs, each GO TO-ing its own following bare-EXIT paragraph.
    2000-VALIDATE-B is only reachable, on paper, by falling through past
    1000-EXIT (a GO TO target) -- but 1000-EXIT's own GO TO is itself
    safe to neutralize, which drops 1000-EXIT out of _go_to_targets and
    un-marks 2000-VALIDATE-B as a fallthrough hazard. A single static
    pass over the raw, whole-program hazard sets sees 2000-VALIDATE-B
    (and, transitively, 3000-VALIDATE-C) as hazardous from the very start
    and declines the whole chain; find_goto_exit_plans must instead
    re-evaluate every remaining candidate as each earlier one confirms,
    resolving the chain to a fixpoint in one call."""
    source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. GOTOCHAIN.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-COND             PIC X VALUE "N".

       PROCEDURE DIVISION.
       1000-VALIDATE-A.
           IF WS-COND = "Y"
               GO TO 1000-EXIT
           END-IF
           DISPLAY "A".

       1000-EXIT.
           EXIT.

       2000-VALIDATE-B.
           IF WS-COND = "Y"
               GO TO 2000-EXIT
           END-IF
           DISPLAY "B".

       2000-EXIT.
           EXIT.

       3000-VALIDATE-C.
           IF WS-COND = "Y"
               GO TO 3000-EXIT
           END-IF
           DISPLAY "C".

       3000-EXIT.
           EXIT.

       4000-TERMINATE.
           STOP RUN.
"""
    program, _, scope_map, lines = _analyze(source)
    plans, notes = find_goto_exit_plans(program, scope_map, lines)
    assert notes == []
    assert {plan.paragraph_name for plan in plans} == {
        "1000-VALIDATE-A",
        "2000-VALIDATE-B",
        "3000-VALIDATE-C",
    }


def test_find_goto_exit_plans_declines_section_scoped_enclosing_paragraph():
    """SECTION support is deliberately NOT implemented (see the module
    docstring): both a cleanup paragraph after the exit-only paragraph
    inside the same section, and find_terminator_plans' own unverified
    "shape 3" (a .cut perform_target naming the section's first paragraph
    directly) need suite-case context this whole-program function does
    not have. A SECTION-scoped enclosing paragraph is declined, not
    silently mishandled."""
    program, _, scope_map, lines = _analyze(SECTION_ENTRY_SOURCE)
    plans, notes = find_goto_exit_plans(program, scope_map, lines)
    assert plans == []
    assert len(notes) == 1
    assert "SECTION" in notes[0]


def test_find_goto_exit_plans_declines_when_thru_range_would_cover_a_real_paragraph():
    """Regression pin for a real bug found by code review: without an
    adjacency check, splicing GO TO -> EXIT PARAGRAPH silently changes
    the early-exit path's behavior whenever a PERFORM ... THRU range
    (declared by a .cut test, or written in-program) covers a REAL
    paragraph between the GO TO's enclosing paragraph and the exit-only
    target -- the original GO TO skips it, but EXIT PARAGRAPH only ends
    the enclosing paragraph, so the THRU range's own fall-through then
    runs it on the early-exit path where it never did before."""
    source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. THRUMID.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-COND             PIC X VALUE "N".
       01  WS-Y                PIC 9 VALUE 0.

       PROCEDURE DIVISION.
       1000-STEP.
           IF WS-COND = "Y"
               GO TO 9000-EXIT
           END-IF
           DISPLAY "NORMAL".

       2000-MORE.
           MOVE 2 TO WS-Y.

       9000-EXIT.
           EXIT.
"""
    program, _, scope_map, lines = _analyze(source)
    plans, notes = find_goto_exit_plans(program, scope_map, lines)
    assert plans == []
    assert len(notes) == 1
    assert "not the paragraph immediately following" in notes[0]


def test_find_goto_exit_plans_declines_when_a_computed_goto_also_names_the_target():
    """Regression pin for a real bug found by code review: a computed or
    multi-target GO TO naming the exit-only paragraph is invisible to
    _go_statement_target (returns None), so it was never counted as a
    site against that target -- but it is still a real GO TO edge into
    it. Left unguarded, find_terminator_plans' narrowing of
    _go_to_targets by a "fully neutralized" target would be unsound: the
    computed GO TO stays live in the compiled source, entering the
    (formerly) exit-only paragraph via GO TO exactly as before."""
    source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. COMPUTEDBLIND.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-COND             PIC X VALUE "N".
       01  WS-N                PIC 9 VALUE 9.

       PROCEDURE DIVISION.
       1000-PROC.
           IF WS-COND = "Y"
               GO TO 9000-EXIT
           END-IF
           DISPLAY "WORK".

       9000-EXIT.
           EXIT.

       2000-OTHER.
           GO TO 9000-EXIT 9000-EXIT DEPENDING ON WS-N.
"""
    program, _, scope_map, lines = _analyze(source)
    plans, notes = find_goto_exit_plans(program, scope_map, lines)
    assert plans == []
    assert len(notes) == 1
    assert "computed or multi-target GO TO" in notes[0]


# --- wiring into find_terminator_plans --------------------------------------


def test_terminator_behind_exit_only_fallthrough_is_no_longer_refused():
    """Before this feature: 0000-MAIN-EXIT (a GO TO target) falls through
    (bare EXIT) into 2000-TERMINATE, so 2000-TERMINATE lands in
    go_to_fallthrough and STOP RUN there refuses UNSUPPORTED_TERMINATOR_
    LAYOUT even though it's genuinely PERFORMed by 0000-MAIN-PROCESS too.
    After: the GO TO is neutralized, 0000-MAIN-EXIT drops out of
    go_to_targets, so the fallthrough hazard evaporates and the plain
    PERFORM chain qualifies normally."""
    program, surface, scope_map, lines = _analyze(SAFE_GOTO_EXIT_SOURCE)
    plans, reasons = find_terminator_plans(surface, program, _suite(), scope_map, lines)
    assert reasons == []
    assert len(plans) == 1
    assert plans[0].site.label == "STOP RUN"
    assert plans[0].site.paragraph_name == "2000-TERMINATE"


def test_neutralized_chain_needs_no_perform_thru_declaration():
    """THRU elision (design doc's "THRU elision" section): once every GO
    TO into 0000-MAIN-EXIT is neutralized, a .cut test targeting
    0000-MAIN-PROCESS with NO perform_thru declared still gets a clean
    TerminatorPlan -- exactly the claim that PERFORM ... THRU 0000-MAIN-
    EXIT is no longer required for this shape. (Every test in this file
    already uses perform_thru=None via _suite()'s default; this test
    exists to pin that claim explicitly rather than leave it implicit.)"""
    program, surface, scope_map, lines = _analyze(SAFE_GOTO_EXIT_SOURCE)
    suite = _suite(perform_target="0000-MAIN-PROCESS")
    assert suite.test_cases[0].perform_thru is None
    plans, reasons = find_terminator_plans(surface, program, suite, scope_map, lines)
    assert reasons == []
    assert len(plans) == 1


def test_terminator_behind_a_real_fallthrough_paragraph_still_refuses():
    """Negative control: same shape, but the paragraph the GO TO targets
    does real work (not exit-only) -- proves the wiring above is actually
    gated on find_goto_exit_plans, not vacuously permissive."""
    source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. GOTOREALWORK.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-COND             PIC X VALUE "N".

       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           PERFORM 1000-DO-WORK
           IF WS-COND = "Y"
               GO TO 0000-MAIN-EXIT
           END-IF
           PERFORM 2000-TERMINATE.

       0000-MAIN-EXIT.
           DISPLAY "NOT JUST EXIT".

       1000-DO-WORK.
           DISPLAY "WORK".

       2000-TERMINATE.
           STOP RUN.
"""
    program, surface, scope_map, lines = _analyze(source)
    plans, reasons = find_terminator_plans(surface, program, _suite(), scope_map, lines)
    assert plans == []
    assert len(reasons) == 1
    assert reasons[0].code == "UNSUPPORTED_TERMINATOR_LAYOUT"


# --- splice mechanics --------------------------------------------------------


def _splice_goto_exit(source, suite):
    result = parse_cobol(source, filename="gotoexit.cbl")
    assert result.success, result.errors
    surface = analyze(result.ast)
    lines = normalize_fixed_format(source.splitlines()).splitlines()
    scope_map = collect_scope_map(result.ast, lines)
    annotate_nested_sites(surface, scope_map, lines)
    boundaries = collect_boundaries(result.ast)
    terminator_plans, treasons = find_terminator_plans(
        surface, result.ast, suite, scope_map, lines
    )
    assert treasons == []
    goto_exit_plans, gnotes = find_goto_exit_plans(result.ast, scope_map, lines)
    assert gnotes == []
    return splice_program(
        lines,
        boundaries,
        surface,
        suite,
        TallyRegistry(suite),
        terminator_plans,
        goto_exit_plans=goto_exit_plans,
    )


def test_goto_is_commented_out_and_replaced_with_exit_paragraph():
    lines = _splice_goto_exit(SAFE_GOTO_EXIT_SOURCE, _suite())
    joined = "\n".join(lines)
    assert "GO TO 0000-MAIN-EXIT" in joined  # commented-out original text
    commented = [
        line for line in lines if "*>" in line and "GO TO 0000-MAIN-EXIT" in line
    ]
    assert len(commented) == 1
    assert "           EXIT PARAGRAPH" in lines


def test_nested_goto_replacement_does_not_swallow_the_enclosing_end_if():
    """Regression pin for a real bug found while building this feature:
    the GO TO in SAFE_GOTO_EXIT_SOURCE is nested inside an IF, so its
    replacement span must stop before END-IF (nested_statement_span), not
    extend past it the way plain statement_span would (it has no location
    data for block words). A wrong span here would comment out END-IF
    too, turning EXIT PARAGRAPH into an unconditional statement instead
    of one gated by the IF -- silently changing the paragraph's normal
    (early-exit-not-taken) behavior. Anchored specifically on the `IF
    WS-COND` line -- the paragraph also gets terminator chain-check `IF
    UT-EARLY-EXIT = "Y" ... END-IF` blocks inserted around it, which are
    unrelated and must not be confused with this IF/END-IF pair."""
    lines = _splice_goto_exit(SAFE_GOTO_EXIT_SOURCE, _suite())
    if_idx = next(i for i, line in enumerate(lines) if "IF WS-COND" in line)
    # The next line after the IF must be the commented-out original GO TO.
    assert lines[if_idx + 1].strip().startswith("*>")
    assert "GO TO 0000-MAIN-EXIT" in lines[if_idx + 1]
    # Then EXIT PARAGRAPH, gated inside the IF.
    assert lines[if_idx + 2].strip() == "EXIT PARAGRAPH"
    # Then this exact IF's own END-IF -- immediately next, un-commented.
    assert lines[if_idx + 3].strip() == "END-IF"
    # The paragraph's normal-path statement (PERFORM 2000-TERMINATE, in
    # SAFE_GOTO_EXIT_SOURCE) survives right after, unaltered and
    # un-commented -- proving END-IF was not swallowed.
    assert "PERFORM 2000-TERMINATE" in lines[if_idx + 4]
    assert not lines[if_idx + 4].strip().startswith("*>")


def test_goto_exit_splice_coexists_with_terminator_neutralization():
    lines = _splice_goto_exit(SAFE_GOTO_EXIT_SOURCE, _suite())
    joined = "\n".join(lines)
    assert "      *>     STOP RUN." in joined
    assert 'MOVE "Y" TO UT-EARLY-EXIT' in joined


def test_no_goto_exit_plans_argument_leaves_existing_behavior_unchanged():
    result = parse_cobol(SAFE_GOTO_EXIT_SOURCE, filename="gotoexit.cbl")
    assert result.success, result.errors
    surface = analyze(result.ast)
    lines = normalize_fixed_format(SAFE_GOTO_EXIT_SOURCE.splitlines()).splitlines()
    boundaries = collect_boundaries(result.ast)
    suite = _suite()
    spliced = splice_program(lines, boundaries, surface, suite, TallyRegistry(suite))
    assert "\n".join(spliced) == "\n".join(lines)
