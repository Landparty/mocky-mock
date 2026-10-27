"""Unit tests for Approach B's safe-chain terminator detection
(docs/2026-07-08-goback-stop-run-support-design.md). Mirrors
tests/unit/test_linkage.py's structure: the analysis functions and the
refusal wrapper are tested together since they're always used together.
"""

from cobolparser import parse_cobol
from cobolparser.preprocess import normalize_fixed_format

from mockymock.analysis.mock_surface import analyze
from mockymock.analysis.refusal import (
    _falls_through,
    _go_to_fallthrough_targets,
    check_terminator_layout,
    find_terminator_plans,
)
from mockymock.dsl.model import MockTestCase, MockTestSuite
from mockymock.splicer.source_map import annotate_nested_sites, collect_scope_map

SHARED_LINE_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TERMSHARE.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-RESULT           PIC 9(4) VALUE 0.

       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           MOVE 1 TO WS-RESULT STOP RUN.
"""

CHAIN_SHARED_LINE_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CHAINSHARE.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A                PIC 9.

       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           MOVE 1 TO WS-A PERFORM 1000-WRAPPER.

       1000-WRAPPER.
           STOP RUN.
"""

SAFE_CHAIN_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SAFECHAIN.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-RESULT           PIC 9(4) VALUE 0.

       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           PERFORM 1000-DO-WORK
           STOP RUN.

       1000-DO-WORK.
           CALL "CALCPGM" USING WS-RESULT.
"""

GO_TO_UNSAFE_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. GOTOUNSAFE.

       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           PERFORM 1000-DO-WORK
           STOP RUN.

       1000-DO-WORK.
           DISPLAY "WORK".

       1000-DO-WORK-ALIAS.
           GO TO 1000-DO-WORK.
"""

GO_TO_OWN_PARAGRAPH_UNSAFE_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. GOTOOWNPARA.

       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           PERFORM 1000-DO-WORK.

       1000-DO-WORK.
           STOP RUN.

       1000-DO-WORK-ALIAS.
           GO TO 1000-DO-WORK.
"""

SECTION_UNSAFE_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SECTUNSAFE.

       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           PERFORM 1000-SECTION
           STOP RUN.

       1000-SECTION SECTION.
       1000-DO-WORK.
           DISPLAY "WORK".
"""

SECTION_OWN_PARAGRAPH_UNSAFE_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SECTOWNPARA.

       PROCEDURE DIVISION.
       0000-MAIN-SECTION SECTION.
       0000-MAIN-PROCESS.
           STOP RUN.
"""

CHAIN_SECTION_STILL_UNSAFE_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CHAINSECTUNSAFE.

       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           PERFORM 1000-SECTION
           STOP RUN.

       9000-ALSO-CALLS-DIRECTLY.
           PERFORM 1000-DO-WORK.

       1000-SECTION SECTION.
       1000-DO-WORK.
           DISPLAY "WORK".
"""

SECTION_FIRST_PARAGRAPH_SAFE_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SECTFIRSTSAFE.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-RESULT           PIC 9(4) VALUE 0.

       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           PERFORM 1000-TERM-SECTION
           DISPLAY "AFTER-SECTION".

       1000-TERM-SECTION SECTION.
       1000-TERM-FIRST.
           MOVE 1 TO WS-RESULT
           STOP RUN.
       1000-TERM-SECOND.
           MOVE 999 TO WS-RESULT.
"""

SECTION_LATER_PARAGRAPH_UNSAFE_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SECTLATERUNSAFE.

       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           PERFORM 1000-TERM-SECTION.

       1000-TERM-SECTION SECTION.
       1000-TERM-FIRST.
           DISPLAY "FIRST".
       1000-TERM-SECOND.
           STOP RUN.
"""

LOOP_SAFE_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. LOOPSAFE.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-DONE             PIC X VALUE "N".

       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           PERFORM 1000-LOOP-BODY UNTIL WS-DONE = "Y"
           STOP RUN.

       1000-LOOP-BODY.
           MOVE "Y" TO WS-DONE.
"""

LOOP_TERMINATOR_UNSAFE_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. LOOPUNSAFE.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-DONE             PIC X VALUE "N".

       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           PERFORM 1000-LOOP-BODY UNTIL WS-DONE = "Y".

       1000-LOOP-BODY.
           STOP RUN.
"""


def _analyze(source, name="X.cbl"):
    """Returns (program, surface, scope_map, lines) -- find_terminator_plans
    needs all four: program/surface for the reachability walk,
    scope_map/lines to validate each intermediate PERFORM's line ownership
    via statement_top_level_problem."""
    result = parse_cobol(source, filename=name)
    assert result.success, result.errors
    lines = normalize_fixed_format(source.splitlines()).splitlines()
    surface = analyze(result.ast)
    scope_map = collect_scope_map(result.ast, lines)
    annotate_nested_sites(surface, scope_map, lines)
    return result.ast, surface, scope_map, lines


def _suite(perform_target="0000-MAIN-PROCESS"):
    case = MockTestCase(name="c", perform_target=perform_target)
    return MockTestSuite(name="S", test_cases=[case])


def _paragraph(source, name):
    program, _, _, _ = _analyze(source)
    procedure = program.get_division("PROCEDURE")
    for p in procedure.paragraphs:
        if p.paragraph_name == name:
            return p
    for section in getattr(procedure, "_sections", {}).values():
        for p in section.paragraphs:
            if p.paragraph_name == name:
                return p
    raise AssertionError(f"paragraph {name!r} not found")


def test_find_terminator_plans_accepts_a_safe_plain_perform_chain():
    program, surface, scope_map, lines = _analyze(SAFE_CHAIN_SOURCE)
    plans, reasons = find_terminator_plans(surface, program, _suite(), scope_map, lines)
    assert reasons == []
    assert len(plans) == 1
    assert plans[0].site.label == "STOP RUN"
    assert plans[0].site.paragraph_name == "0000-MAIN-PROCESS"
    # PERFORM 1000-DO-WORK isn't on the path to the terminator (it's
    # directly in the target paragraph) but chain_performs is the whole
    # case's over-inclusive reachable set, not a precise per-terminator
    # path -- see find_terminator_plans' docstring.
    assert {p.target_paragraph for p in plans[0].chain_performs} == {"1000-DO-WORK"}


def test_find_terminator_plans_empty_when_unreachable():
    program, surface, scope_map, lines = _analyze(SAFE_CHAIN_SOURCE)
    suite = _suite(perform_target="1000-DO-WORK")
    plans, reasons = find_terminator_plans(surface, program, suite, scope_map, lines)
    assert plans == []
    assert reasons == []


def test_find_terminator_plans_includes_intermediate_perform_in_chain():
    source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TWOLEVEL.

       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           PERFORM 1000-WRAPPER.

       1000-WRAPPER.
           PERFORM 2000-INNER.

       2000-INNER.
           STOP RUN.
"""
    program, surface, scope_map, lines = _analyze(source)
    plans, reasons = find_terminator_plans(surface, program, _suite(), scope_map, lines)
    assert reasons == []
    assert len(plans) == 1
    # both PERFORM 1000-WRAPPER and PERFORM 2000-INNER are on the chain
    assert {p.target_paragraph for p in plans[0].chain_performs} == {
        "1000-WRAPPER",
        "2000-INNER",
    }


def test_looping_perform_is_excluded_from_the_safe_chain():
    """A PERFORM ... UNTIL used as an intermediate chain link is NOT a
    "plain, unconditional" PERFORM: EXIT PARAGRAPH from inside its target
    only ends the current iteration, not the loop, so its target must not
    be treated as safely reachable. Here the terminator sits directly in
    the perform_target paragraph (always in safe_names), so it's still
    accepted -- but the loop's own PERFORM must NOT appear in
    chain_performs, since instrumenting it would insert a chain-check that
    fires on every iteration rather than once after the whole loop."""
    program, surface, scope_map, lines = _analyze(LOOP_SAFE_SOURCE)
    plans, reasons = find_terminator_plans(surface, program, _suite(), scope_map, lines)
    assert reasons == []
    assert len(plans) == 1
    assert plans[0].chain_performs == []


def test_terminator_reached_only_through_a_loop_body_refuses():
    """The terminator (STOP RUN) lives inside 1000-LOOP-BODY, which is
    reachable ONLY as the target of a PERFORM ... UNTIL -- not a plain,
    unconditional PERFORM. Confirmed empirically (a synthetic spliced
    program with this shape kept iterating past a real STOP RUN instead
    of stopping) that treating this as safe is a genuine correctness bug;
    this must refuse instead."""
    program, surface, scope_map, lines = _analyze(LOOP_TERMINATOR_UNSAFE_SOURCE)
    plans, reasons = find_terminator_plans(surface, program, _suite(), scope_map, lines)
    assert plans == []
    assert len(reasons) == 1
    assert reasons[0].code == "UNSUPPORTED_TERMINATOR_LAYOUT"
    assert "not via a chain of plain, unconditional" in reasons[0].message


LOOP_TERMINATOR_UNSAFE_VARYING_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. LOOPUNSAFEVARY.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-I                PIC 9(2) VALUE 0.

       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           PERFORM 1000-LOOP-BODY
               VARYING WS-I FROM 1 BY 1 UNTIL WS-I > 5.

       1000-LOOP-BODY.
           STOP RUN.
"""


def test_terminator_reached_only_through_a_varying_loop_body_refuses():
    """Same hazard as test_terminator_reached_only_through_a_loop_body_refuses
    above, but for the out-of-line PERFORM ... VARYING form specifically --
    a distinct cobolparser codepath from UNTIL/TIMES. This shape's VARYING
    clause used to be silently dropped, mistagging perform_type "SIMPLE"
    (indistinguishable from a safe plain PERFORM to
    _plain_perform_edges_from); what protected it then was an unrelated
    PARSE_WARNING refusal for the dropped clause -- see
    tests/unit/test_refusal.py's OUT_OF_LINE_PERFORM_VARYING_SOURCE comment.
    cobolparser now parses this correctly (perform_type == "VARYING", no
    warnings -- test_refusal.py::test_out_of_line_perform_varying_parses_correctly),
    so this pins that the *intended* mechanism -- the perform_type guard in
    _plain_perform_edges_from -- independently still excludes it, rather
    than relying on the parser bug's accidental safety net."""
    program, surface, scope_map, lines = _analyze(LOOP_TERMINATOR_UNSAFE_VARYING_SOURCE)
    plans, reasons = find_terminator_plans(surface, program, _suite(), scope_map, lines)
    assert plans == []
    assert len(reasons) == 1
    assert reasons[0].code == "UNSUPPORTED_TERMINATOR_LAYOUT"
    assert "not via a chain of plain, unconditional" in reasons[0].message


def test_falls_through_true_for_empty_paragraph():
    source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. EMPTYPARA.

       PROCEDURE DIVISION.
       P1.
       P2.
           STOP RUN.
"""
    assert _falls_through(_paragraph(source, "P1")) is True


def test_falls_through_false_for_goback():
    source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. GOBACKEND.

       PROCEDURE DIVISION.
       P1.
           DISPLAY "X"
           GOBACK.
"""
    assert _falls_through(_paragraph(source, "P1")) is False


def test_falls_through_false_for_stop_run():
    source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. STOPRUNEND.

       PROCEDURE DIVISION.
       P1.
           DISPLAY "X"
           STOP RUN.
"""
    assert _falls_through(_paragraph(source, "P1")) is False


def test_falls_through_true_for_stop_literal():
    """STOP "MSG" only pauses for operator input and resumes -- it does
    not terminate control flow, unlike STOP RUN."""
    source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. STOPLITEND.

       PROCEDURE DIVISION.
       P1.
           DISPLAY "X"
           STOP "MSG".
       P2.
           DISPLAY "Y".
"""
    assert _falls_through(_paragraph(source, "P1")) is True


def test_falls_through_false_for_plain_go_to():
    source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PLAINGOTOEND.

       PROCEDURE DIVISION.
       P1.
           GO TO P2.
       P2.
           STOP RUN.
"""
    assert _falls_through(_paragraph(source, "P1")) is False


def test_falls_through_true_for_computed_go_to():
    """GO TO ... DEPENDING ON falls through to the next statement when the
    subscript is out of range -- it is NOT a guaranteed unconditional
    transfer, unlike a plain single-target GO TO."""
    source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. COMPUTEDGOTOEND.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-N                PIC 9 VALUE 9.

       PROCEDURE DIVISION.
       P1.
           GO TO P2 P3 DEPENDING ON WS-N.
       P2.
           STOP RUN.
       P3.
           STOP RUN.
"""
    assert _falls_through(_paragraph(source, "P1")) is True


def test_falls_through_false_for_exit_paragraph():
    source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. EXITPARAEND.

       PROCEDURE DIVISION.
       P1.
           DISPLAY "X"
           EXIT PARAGRAPH.
       P2.
           STOP RUN.
"""
    assert _falls_through(_paragraph(source, "P1")) is False


def test_falls_through_true_for_trailing_if():
    """Conservative: no attempt to prove every branch of a trailing IF
    terminates."""
    source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TRAILINGIF.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-FLAG             PIC X VALUE "N".

       PROCEDURE DIVISION.
       P1.
           IF WS-FLAG = "Y"
               STOP RUN
           END-IF.
       P2.
           DISPLAY "Y".
"""
    assert _falls_through(_paragraph(source, "P1")) is True


def test_go_to_fallthrough_targets_finds_paragraph_after_falling_through():
    source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. FALLTHRU.

       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           PERFORM 1000-DO-WORK.

       1000-DO-WORK-ALIAS.
           GO TO 1000-DO-WORK.

       1000-DO-WORK.
           DISPLAY "WORK".

       1000-AFTER.
           STOP RUN.
"""
    program, _, _, _ = _analyze(source)
    go_to_targets = {"1000-DO-WORK"}
    hazard = _go_to_fallthrough_targets(program, go_to_targets)
    assert hazard == {"1000-AFTER": "1000-DO-WORK"}


def test_go_to_fallthrough_targets_stops_at_a_terminating_paragraph():
    """1000-DO-WORK's own STOP RUN means it never falls through --
    1000-AFTER must not be hazarded."""
    source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. NOFALLTHRU.

       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           PERFORM 1000-DO-WORK.

       1000-DO-WORK-ALIAS.
           GO TO 1000-DO-WORK.

       1000-DO-WORK.
           DISPLAY "WORK"
           STOP RUN.

       1000-AFTER.
           STOP RUN.
"""
    program, _, _, _ = _analyze(source)
    go_to_targets = {"1000-DO-WORK"}
    hazard = _go_to_fallthrough_targets(program, go_to_targets)
    assert hazard == {}


def test_go_to_fallthrough_targets_propagates_through_computed_go_to():
    source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. COMPUTEDCHAIN.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-N                PIC 9 VALUE 9.

       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           PERFORM 1000-DO-WORK.

       1000-DO-WORK-ALIAS.
           GO TO 1000-DO-WORK.

       1000-DO-WORK.
           GO TO 1000-A 1000-B DEPENDING ON WS-N.

       1000-A.
           DISPLAY "A".

       1000-B.
           STOP RUN.
"""
    program, _, _, _ = _analyze(source)
    go_to_targets = {"1000-DO-WORK"}
    hazard = _go_to_fallthrough_targets(program, go_to_targets)
    # 1000-DO-WORK's own computed GO TO does not stop fall-through, so
    # BOTH 1000-A (falls through) and 1000-B (terminates, chain stops
    # there) are hazarded.
    assert hazard == {"1000-A": "1000-DO-WORK", "1000-B": "1000-DO-WORK"}


def test_go_to_fallthrough_targets_seeds_from_section_first_paragraph():
    source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SECTIONFALLTHRU.

       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           PERFORM 1000-SECTION.

       1000-SECTION-ALIAS.
           GO TO 1000-SECTION.

       1000-SECTION SECTION.
       1000-FIRST.
           DISPLAY "FIRST".
       1000-SECOND.
           DISPLAY "SECOND".

       1000-AFTER.
           STOP RUN.
"""
    program, _, _, _ = _analyze(source)
    go_to_targets = {"1000-SECTION"}
    hazard = _go_to_fallthrough_targets(program, go_to_targets)
    assert hazard == {
        "1000-SECOND": "1000-SECTION",
        "1000-AFTER": "1000-SECTION",
    }


def test_go_to_reachable_terminator_refuses():
    """The terminator's OWN paragraph (1000-DO-WORK) is a GO TO target,
    reached from perform_target via a plain, otherwise-safe PERFORM."""
    program, surface, scope_map, lines = _analyze(GO_TO_OWN_PARAGRAPH_UNSAFE_SOURCE)
    plans, reasons = find_terminator_plans(surface, program, _suite(), scope_map, lines)
    assert plans == []
    assert len(reasons) == 1
    assert reasons[0].code == "UNSUPPORTED_TERMINATOR_LAYOUT"
    assert "GO TO" in reasons[0].message


def test_go_to_target_refuses_even_when_a_different_case_uses_it_safely():
    """1000-DO-WORK is safely PERFORM-reachable from case "safe", but it is
    ALSO a GO TO target somewhere in the program (via 1000-DO-WORK-ALIAS) --
    per the design doc this refuses unconditionally, not just for the case
    that actually takes the GO TO path."""
    program, surface, scope_map, lines = _analyze(GO_TO_UNSAFE_SOURCE)
    suite = MockTestSuite(
        name="S",
        test_cases=[MockTestCase(name="safe", perform_target="0000-MAIN-PROCESS")],
    )
    plans, reasons = find_terminator_plans(surface, program, suite, scope_map, lines)
    assert plans == []
    assert len(reasons) == 1
    assert reasons[0].code == "UNSUPPORTED_TERMINATOR_LAYOUT"


GO_TO_FALLTHROUGH_UNSAFE_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. GOTOFALLUNSAFE.

       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           PERFORM 1000-DO-WORK.

       1000-DO-WORK-ALIAS.
           GO TO 1000-DO-WORK.

       1000-DO-WORK.
           DISPLAY "WORK".

       1000-AFTER.
           STOP RUN.
"""

GO_TO_FALLTHROUGH_TERMINATES_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. GOTONOFALL.

       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           PERFORM 1000-DO-WORK.

       1000-DO-WORK-ALIAS.
           GO TO 1000-DO-WORK.

       1000-DO-WORK.
           DISPLAY "WORK"
           STOP RUN.

       1000-AFTER.
           STOP RUN.
"""

GO_TO_FALLTHROUGH_CHAIN_UNSAFE_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. GOTOFALLCHAIN.

       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           PERFORM 1000-WRAPPER.

       1000-WRAPPER.
           PERFORM 1000-MIDDLE
           STOP RUN.

       1000-GOTO-SOURCE.
           GO TO 1000-EARLY.

       1000-EARLY.
           DISPLAY "EARLY".

       1000-MIDDLE.
           DISPLAY "MIDDLE".
"""


def test_go_to_fallthrough_terminator_refuses():
    """1000-AFTER's STOP RUN is never itself a GO TO target -- it's only
    reachable because 1000-DO-WORK (a GO TO target) falls through into
    it. Case "main" reaches the program the ordinary way; case "after"
    targets 1000-AFTER directly, mirroring the real danger this guards
    against: a *different* test case's own, otherwise-legitimate
    perform_target sharing a physical terminator that another part of the
    program can reach only through this unmodeled GO-TO-fallthrough path.
    Without this guard, case "after" would see 1000-AFTER as trivially
    safe (it's directly its own perform_target) and neutralize it."""
    program, surface, scope_map, lines = _analyze(GO_TO_FALLTHROUGH_UNSAFE_SOURCE)
    suite = MockTestSuite(
        name="S",
        test_cases=[
            MockTestCase(name="main", perform_target="0000-MAIN-PROCESS"),
            MockTestCase(name="after", perform_target="1000-AFTER"),
        ],
    )
    plans, reasons = find_terminator_plans(surface, program, suite, scope_map, lines)
    assert plans == []
    assert len(reasons) == 1
    assert reasons[0].code == "UNSUPPORTED_TERMINATOR_LAYOUT"
    assert "1000-DO-WORK" in reasons[0].message
    assert "falling through" in reasons[0].message


def test_go_to_fallthrough_does_not_refuse_when_target_terminates():
    """Negative control: 1000-DO-WORK's own STOP RUN means it never falls
    through, so 1000-AFTER's separate terminator is unaffected by the new
    fallthrough check and is still accepted as safe -- no false-positive
    refusal from over-eager hazard propagation. 1000-DO-WORK's own
    terminator still refuses, but via the pre-existing direct-GO-TO-target
    check, not the new fallthrough one."""
    program, surface, scope_map, lines = _analyze(GO_TO_FALLTHROUGH_TERMINATES_SOURCE)
    suite = MockTestSuite(
        name="S",
        test_cases=[
            MockTestCase(name="main", perform_target="0000-MAIN-PROCESS"),
            MockTestCase(name="after", perform_target="1000-AFTER"),
        ],
    )
    plans, reasons = find_terminator_plans(surface, program, suite, scope_map, lines)
    assert len(plans) == 1
    assert plans[0].site.paragraph_name == "1000-AFTER"
    assert len(reasons) == 1
    assert "GO TO" in reasons[0].message
    assert "falling through" not in reasons[0].message


def test_go_to_fallthrough_chain_paragraph_refuses():
    """The terminator itself (STOP RUN in 1000-WRAPPER) has no problem on
    its own -- the hazard is that 1000-MIDDLE, a legitimate chain_performs
    member (PERFORMed by 1000-WRAPPER), is ALSO reached by falling through
    past 1000-EARLY (a GO TO target). Mirrors
    test_go_to_target_refuses_even_when_a_different_case_uses_it_safely's
    chain-level shape but for the fallthrough hazard instead of a direct
    GO TO target."""
    program, surface, scope_map, lines = _analyze(GO_TO_FALLTHROUGH_CHAIN_UNSAFE_SOURCE)
    plans, reasons = find_terminator_plans(surface, program, _suite(), scope_map, lines)
    assert plans == []
    assert len(reasons) == 1
    assert reasons[0].code == "UNSUPPORTED_TERMINATOR_LAYOUT"
    assert "1000-MIDDLE" in reasons[0].message
    assert "falling through" in reasons[0].message


def test_section_touched_only_via_safe_entry_no_longer_refuses():
    """SECTION_UNSAFE_SOURCE's terminator sits directly in
    0000-MAIN-PROCESS, a top-level paragraph -- the chain merely PERFORMs
    1000-SECTION on the way, and 1000-SECTION's only paragraph
    (1000-DO-WORK) is never GO TO'd or directly PERFORMed anywhere else,
    so it's a safe section entry
    (docs/2026-07-10-section-scoped-terminator-support-design.md). This
    used to refuse under the old blanket "any SECTION anywhere in the
    chain is unsafe" check; now it's correctly recognized as safe. The
    terminator's own paragraph is still top-level, so exit_kind stays
    PARAGRAPH -- this test is about the chain-level check, not the
    terminator's own paragraph classification (see
    test_terminator_in_safe_section_first_paragraph_is_accepted for
    that)."""
    program, surface, scope_map, lines = _analyze(SECTION_UNSAFE_SOURCE)
    plans, reasons = find_terminator_plans(surface, program, _suite(), scope_map, lines)
    assert reasons == []
    assert len(plans) == 1
    assert plans[0].exit_kind == "PARAGRAPH"


def test_chain_touching_a_genuinely_unsafe_section_still_refuses():
    """Unlike SECTION_UNSAFE_SOURCE, 1000-DO-WORK here is ALSO directly
    PERFORMed by 9000-ALSO-CALLS-DIRECTLY -- a second entry path -- so
    1000-SECTION is NOT a safe entry, and the terminator (still in the
    top-level 0000-MAIN-PROCESS) must still refuse via
    chain_section_names."""
    program, surface, scope_map, lines = _analyze(CHAIN_SECTION_STILL_UNSAFE_SOURCE)
    plans, reasons = find_terminator_plans(surface, program, _suite(), scope_map, lines)
    assert plans == []
    assert len(reasons) == 1
    assert reasons[0].code == "UNSUPPORTED_TERMINATOR_LAYOUT"
    assert "SECTION" in reasons[0].message


def test_terminator_in_safe_section_first_paragraph_is_accepted():
    """The core shape-1 feature: STOP RUN sits in 1000-TERM-FIRST, the
    first paragraph of 1000-TERM-SECTION, entered only via PERFORM
    1000-TERM-SECTION. Whether 1000-TERM-SECOND actually fails to run at
    real GnuCOBOL runtime is the integration test's job
    (tests/integration/test_terminator_support.py) -- here we confirm the
    plan itself: SECTION exit kind, and the section-name PERFORM captured
    as a chain_performs edge (0000-MAIN-PROCESS has a DISPLAY after it,
    so it needs the standard post-PERFORM flag check)."""
    program, surface, scope_map, lines = _analyze(SECTION_FIRST_PARAGRAPH_SAFE_SOURCE)
    plans, reasons = find_terminator_plans(surface, program, _suite(), scope_map, lines)
    assert reasons == []
    assert len(plans) == 1
    assert plans[0].site.paragraph_name == "1000-TERM-FIRST"
    assert plans[0].exit_kind == "SECTION"
    assert {p.target_paragraph for p in plans[0].chain_performs} == {
        "1000-TERM-SECTION"
    }


def test_terminator_in_safe_section_reached_directly_by_test_target():
    """When the test's own PERFORM_TARGET names the section directly,
    there's no intermediate chain at all -- mirrors how a top-level
    terminator directly in perform_target needs no chain_performs
    (test_find_terminator_plans_accepts_a_safe_plain_perform_chain)."""
    program, surface, scope_map, lines = _analyze(SECTION_FIRST_PARAGRAPH_SAFE_SOURCE)
    suite = _suite(perform_target="1000-TERM-SECTION")
    plans, reasons = find_terminator_plans(surface, program, suite, scope_map, lines)
    assert reasons == []
    assert len(plans) == 1
    assert plans[0].exit_kind == "SECTION"
    assert plans[0].chain_performs == []


def test_terminator_in_a_later_section_paragraph_reached_by_fall_through():
    """Shape 2 of docs/2026-07-10-section-scoped-terminator-support-design.md,
    supported since 2026-10-27: 1000-TERM-SECOND runs inside the `PERFORM
    1000-TERM-SECTION` range by falling through from 1000-TERM-FIRST, so it
    leaves with EXIT SECTION (verified against GnuCOBOL 3.2, see
    docs/2026-10-27-section-member-terminators-design.md)."""
    program, surface, scope_map, lines = _analyze(SECTION_LATER_PARAGRAPH_UNSAFE_SOURCE)
    plans, reasons = find_terminator_plans(surface, program, _suite(), scope_map, lines)
    assert reasons == []
    assert len(plans) == 1
    assert plans[0].site.paragraph_name == "1000-TERM-SECOND"
    assert plans[0].exit_kind == "SECTION"


def test_later_section_paragraph_after_a_diverting_one_is_not_in_section_mode():
    """A member after one that provably diverts (its last statement is a
    GOBACK) is never reached by fall-through, so PERFORMing it by name is
    its only entry and EXIT PARAGRAPH returns from it."""
    source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SECTMODES.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-RC PIC 9 VALUE 0.
       PROCEDURE DIVISION.
       A000-MAIN SECTION.
       A000-START.
           PERFORM A100-CHECK
           GOBACK.
       A100-CHECK.
           IF WS-RC NOT = 0
               STOP RUN
           END-IF
           DISPLAY "CHECKED".
"""
    program, surface, scope_map, lines = _analyze(source)
    plans, reasons = find_terminator_plans(
        surface, program, _suite("A000-START"), scope_map, lines
    )
    assert reasons == []
    kinds = {p.site.paragraph_name: p.exit_kind for p in plans}
    assert kinds == {"A000-START": "PARAGRAPH", "A100-CHECK": "PARAGRAPH"}
    # The PERFORM in A000-START is a chain edge of a by-name entry: its
    # check exits the paragraph, not the section.
    for plan in plans:
        assert set(plan.chain_exit_kinds.values()) <= {"PARAGRAPH"}

    # Entered as the whole section instead, A000-START runs in section mode.
    plans, reasons = find_terminator_plans(
        surface, program, _suite("A000-MAIN"), scope_map, lines
    )
    assert reasons == []
    kinds = {p.site.paragraph_name: p.exit_kind for p in plans}
    assert kinds == {"A000-START": "SECTION", "A100-CHECK": "PARAGRAPH"}
    perform = plans[0].chain_performs[0]
    assert plans[0].chain_exit_kinds[id(perform)] == "SECTION"


def test_section_member_entered_both_ways_still_refuses():
    """A000-START is PERFORMed by name by one case and runs as the section's
    range for another: no single EXIT verb returns from it."""
    from mockymock.dsl.model import MockTestCase, MockTestSuite

    program, surface, scope_map, lines = _analyze(SECTION_OWN_PARAGRAPH_UNSAFE_SOURCE)
    suite = MockTestSuite(
        name="S",
        test_cases=[
            MockTestCase(name="a", perform_target="0000-MAIN-PROCESS"),
            MockTestCase(name="b", perform_target="0000-MAIN-SECTION"),
        ],
    )
    plans, reasons = find_terminator_plans(surface, program, suite, scope_map, lines)
    assert plans == []
    assert len(reasons) == 1
    assert "entered more than one way" in reasons[0].message


def test_section_member_inside_a_thru_range_still_refuses():
    source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SECTTHRU.
       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           PERFORM 1000-A THRU 1000-B
           PERFORM 1000-B.
       1000-S SECTION.
       1000-A.
           DISPLAY "A".
       1000-B.
           STOP RUN.
"""
    program, surface, scope_map, lines = _analyze(source)
    plans, reasons = find_terminator_plans(surface, program, _suite(), scope_map, lines)
    assert plans == []
    assert any(r.code == "UNSUPPORTED_TERMINATOR_LAYOUT" for r in reasons)


def test_section_own_paragraph_reached_by_name_is_accepted():
    """Shape 3, supported since 2026-10-27: the terminator's own paragraph
    is a SECTION member PERFORMed by its own name (here the case's own
    target) and never entered as its section's range, so its range is the
    paragraph alone and EXIT PARAGRAPH returns from it."""
    program, surface, scope_map, lines = _analyze(SECTION_OWN_PARAGRAPH_UNSAFE_SOURCE)
    plans, reasons = find_terminator_plans(surface, program, _suite(), scope_map, lines)
    assert reasons == []
    assert len(plans) == 1
    assert plans[0].exit_kind == "PARAGRAPH"


def test_terminator_sharing_its_line_refuses():
    """Complements Task 2's direct source_map.py test: here the same
    shared-line shape is checked through the full find_terminator_plans
    path, proving the span-validation wiring actually runs."""
    program, surface, scope_map, lines = _analyze(SHARED_LINE_SOURCE)
    plans, reasons = find_terminator_plans(surface, program, _suite(), scope_map, lines)
    assert plans == []
    assert len(reasons) == 1
    assert reasons[0].code == "UNSUPPORTED_TERMINATOR_LAYOUT"
    assert "does not start its own line" in reasons[0].message


def test_intermediate_perform_sharing_its_line_refuses():
    """The terminator itself (STOP RUN in 1000-WRAPPER) is perfectly safe
    on its own -- the problem is the intermediate PERFORM 1000-WRAPPER in
    0000-MAIN-PROCESS sharing its line with a MOVE. Proves
    statement_top_level_problem is actually being called against
    chain_performs, not just built and left unused."""
    program, surface, scope_map, lines = _analyze(CHAIN_SHARED_LINE_SOURCE)
    plans, reasons = find_terminator_plans(surface, program, _suite(), scope_map, lines)
    assert plans == []
    assert len(reasons) == 1
    assert reasons[0].code == "UNSUPPORTED_TERMINATOR_LAYOUT"
    assert "does not start its own line" in reasons[0].message


def test_check_terminator_layout_is_reasons_only():
    program, surface, scope_map, lines = _analyze(SAFE_CHAIN_SOURCE)
    assert check_terminator_layout(surface, program, _suite(), scope_map, lines) == []

    program, surface, scope_map, lines = _analyze(CHAIN_SECTION_STILL_UNSAFE_SOURCE)
    reasons = check_terminator_layout(surface, program, _suite(), scope_map, lines)
    assert len(reasons) == 1
    assert reasons[0].code == "UNSUPPORTED_TERMINATOR_LAYOUT"


# Issue #212: EXIT PROGRAM in a called subprogram returns to the caller, but
# the driver makes the program under test the main program, where EXIT
# PROGRAM is a no-op -- it has to be neutralized like GOBACK.
EXIT_PROGRAM_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. EXITPGM.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-X                PIC 999 VALUE 0.
       01  WS-CODE             PIC X.

       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           PERFORM 1000-VALIDATE
           ADD 100 TO WS-X
           GOBACK.

       1000-VALIDATE.
           ADD 1 TO WS-X
           IF WS-CODE = "E"
               EXIT PROGRAM
           END-IF
           ADD 10 TO WS-X.
"""


def test_exit_program_is_a_terminator_site():
    _, surface, _, _ = _analyze(EXIT_PROGRAM_SOURCE)
    labels = [s.label for s in surface.boundary_sites if s.category is None]
    assert "EXIT PROGRAM" in labels


def test_exit_program_is_planned_and_spliced_like_goback():
    from mockymock.splicer.naming import TallyRegistry
    from mockymock.splicer.orchestrator import splice_program
    from mockymock.splicer.source_map import collect_boundaries

    program, surface, scope_map, lines = _analyze(EXIT_PROGRAM_SOURCE)
    suite = _suite()
    plans, reasons = find_terminator_plans(surface, program, suite, scope_map, lines)
    assert reasons == []
    exit_plans = [p for p in plans if p.site.label == "EXIT PROGRAM"]
    assert len(exit_plans) == 1
    assert {p.target_paragraph for p in exit_plans[0].chain_performs} == {
        "1000-VALIDATE"
    }
    spliced = "\n".join(
        splice_program(
            lines,
            collect_boundaries(program),
            surface,
            suite,
            TallyRegistry(suite),
            plans,
        )
    )
    assert "*>         EXIT PROGRAM" in spliced
    assert 'IF UT-EARLY-EXIT = "Y"' in spliced


# Issue #211: the .cut's own PERFORM X THRU Y. Neutralizing a terminator
# ends X with EXIT PARAGRAPH, and the driver's THRU range then falls
# through into the rest of the range -- code the real program never runs.
THRU_TAIL_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. THRUTAIL.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-X                PIC 999 VALUE 0.
       01  WS-ERR              PIC X VALUE "N".

       PROCEDURE DIVISION.
       1000-A.
           ADD 1 TO WS-X
           IF WS-ERR = "Y"
               GOBACK
           END-IF.

       1000-B.
           ADD 10 TO WS-X.

       1000-EXIT.
           EXIT.
"""


def _thru_suite(target, thru):
    case = MockTestCase(name="c", perform_target=target, perform_thru=thru)
    return MockTestSuite(name="S", test_cases=[case])


def test_terminator_under_a_cut_thru_range_with_real_tail_refuses():
    program, surface, scope_map, lines = _analyze(THRU_TAIL_SOURCE)
    suite = _thru_suite("1000-A", "1000-EXIT")
    plans, reasons = find_terminator_plans(surface, program, suite, scope_map, lines)
    assert plans == []
    assert [r.code for r in reasons] == ["UNSUPPORTED_TERMINATOR_LAYOUT"]
    assert "fall through into '1000-B'" in reasons[0].message


def test_terminator_under_a_cut_thru_range_with_exit_only_tail_is_planned():
    source = THRU_TAIL_SOURCE.replace(
        """       1000-B.
           ADD 10 TO WS-X.

""",
        "",
    )
    program, surface, scope_map, lines = _analyze(source)
    suite = _thru_suite("1000-A", "1000-EXIT")
    plans, reasons = find_terminator_plans(surface, program, suite, scope_map, lines)
    assert reasons == []
    assert [p.site.label for p in plans] == ["GOBACK"]


def test_terminator_under_a_hook_thru_range_with_real_tail_refuses():
    from mockymock.dsl.model import HookStep

    program, surface, scope_map, lines = _analyze(THRU_TAIL_SOURCE)
    suite = _thru_suite("1000-EXIT", None)
    suite.before_each_steps = [
        HookStep(kind="PERFORM", target="1000-A", thru="1000-EXIT")
    ]
    plans, reasons = find_terminator_plans(surface, program, suite, scope_map, lines)
    assert plans == []
    assert [r.code for r in reasons] == ["UNSUPPORTED_TERMINATOR_LAYOUT"]


# Issue #219: STOP RUN RETURNING n / GOBACK RETURNING n set RETURN-CODE,
# and the neutralization used to drop the phrase with the statement.
RETURNING_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. RETCODE.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-CODE             PIC X.
       01  WS-RC               PIC 9 VALUE 4.

       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           PERFORM 1000-CHECK
           GOBACK RETURNING WS-RC.

       1000-CHECK.
           IF WS-CODE = "E"
               STOP RUN RETURNING 8
           END-IF.
"""


def test_terminator_plan_carries_its_returning_operand():
    from mockymock.splicer.naming import TallyRegistry
    from mockymock.splicer.orchestrator import splice_program
    from mockymock.splicer.source_map import collect_boundaries

    program, surface, scope_map, lines = _analyze(RETURNING_SOURCE)
    suite = _suite()
    plans, reasons = find_terminator_plans(surface, program, suite, scope_map, lines)
    assert reasons == []
    assert sorted((p.site.label, p.return_code) for p in plans) == [
        ("GOBACK", "WS-RC"),
        ("STOP RUN", "8"),
    ]
    spliced = "\n".join(
        splice_program(
            lines,
            collect_boundaries(program),
            surface,
            suite,
            TallyRegistry(suite),
            plans,
        )
    )
    assert "MOVE 8 TO RETURN-CODE" in spliced
    assert "MOVE WS-RC TO RETURN-CODE" in spliced


def test_terminator_with_an_uncopyable_returning_operand_refuses():
    from mockymock.analysis.refusal._plans import _terminator_return_code

    class _Stop:
        returning = "WS-RC OF WS-GROUP"

    operand, problem = _terminator_return_code(_Stop())
    assert operand is None
    assert "RETURNING operand" in problem

    class _Goback:
        returning_value = "-8"

    assert _terminator_return_code(_Goback()) == ("-8", None)


# Issue #215: EXEC CICS RETURN/XCTL/ABEND never give control back, so a
# planned one runs its mock body and then ends the run under test.
CICS_TERMINATOR_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CICSTERM.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-RESP             PIC S9(8) COMP.
       01  WS-STEP             PIC X(10).

       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           PERFORM 1000-FIRST-TIME
           MOVE "PROCESSED" TO WS-STEP
           EXEC CICS RETURN END-EXEC.

       1000-FIRST-TIME.
           EXEC CICS XCTL PROGRAM('NEXT') RESP(WS-RESP)
           END-EXEC
           MOVE "XCTL-FAIL" TO WS-STEP.
"""


def _cics_suite():
    from mockymock.dsl.model import MockCategory, MockDirective

    case = MockTestCase(
        name="c",
        perform_target="0000-MAIN-PROCESS",
        mocks=[
            MockDirective(MockCategory.CICS, "RETURN"),
            MockDirective(MockCategory.CICS, "XCTL"),
        ],
    )
    return MockTestSuite(name="S", test_cases=[case])


def test_cics_return_and_xctl_are_planned_as_terminators():
    program, surface, scope_map, lines = _analyze(CICS_TERMINATOR_SOURCE)
    plans, reasons = find_terminator_plans(
        surface, program, _cics_suite(), scope_map, lines
    )
    assert reasons == []
    by_command = {p.site.statement.cics_command: p for p in plans}
    assert set(by_command) == {"RETURN", "XCTL"}
    assert by_command["RETURN"].resp_field is None
    assert by_command["XCTL"].resp_field == "WS-RESP"


def test_cics_terminator_splice_wraps_the_mock_dispatch_with_the_early_exit():
    from mockymock.splicer.naming import TallyRegistry
    from mockymock.splicer.orchestrator import splice_program
    from mockymock.splicer.source_map import collect_boundaries

    program, surface, scope_map, lines = _analyze(CICS_TERMINATOR_SOURCE)
    suite = _cics_suite()
    plans, _ = find_terminator_plans(surface, program, suite, scope_map, lines)
    spliced = [
        line.strip()
        for line in splice_program(
            lines,
            collect_boundaries(program),
            surface,
            suite,
            TallyRegistry(suite),
            plans,
        )
    ]
    # XCTL with RESP: preset NORMAL, exit only while the field is still 0.
    preset = spliced.index("MOVE 0 TO WS-RESP")
    guard = spliced.index("IF WS-RESP = 0")
    assert preset < spliced.index("ADD 1 TO UT-CICS-XCTL-TALLY") < guard
    assert spliced[guard + 1 : guard + 4] == [
        'MOVE "Y" TO UT-EARLY-EXIT',
        "EXIT PARAGRAPH",
        "END-IF",
    ]
    # RETURN without RESP: unconditional, after its own dispatch, keeping
    # the sentence-ending period.
    return_tally = spliced.index("ADD 1 TO UT-CICS-RETURN-TALLY")
    tail = spliced[return_tally:]
    assert tail[tail.index("END-EVALUATE") + 1 : tail.index("END-EVALUATE") + 3] == [
        'MOVE "Y" TO UT-EARLY-EXIT',
        "EXIT PARAGRAPH.",
    ]
    # The chain check after PERFORM 1000-FIRST-TIME propagates the exit.
    assert 'IF UT-EARLY-EXIT = "Y"' in spliced


def test_cics_terminator_off_a_plain_perform_chain_refuses():
    source = CICS_TERMINATOR_SOURCE.replace(
        "PERFORM 1000-FIRST-TIME\n", "PERFORM 1000-FIRST-TIME 2 TIMES\n"
    )
    program, surface, scope_map, lines = _analyze(source)
    plans, reasons = find_terminator_plans(
        surface, program, _cics_suite(), scope_map, lines
    )
    assert [p.site.statement.cics_command for p in plans] == ["RETURN"]
    assert len(reasons) == 1
    assert reasons[0].code == "UNSUPPORTED_TERMINATOR_LAYOUT"
    assert reasons[0].message.startswith("EXEC CICS XCTL at line")


def test_falls_through_false_for_trailing_cics_return():
    paragraph = _paragraph(CICS_TERMINATOR_SOURCE, "0000-MAIN-PROCESS")
    assert _falls_through(paragraph) is False


def test_cics_resp_option_that_is_not_a_data_name_refuses():
    from mockymock.analysis.refusal._plans import _cics_resp_field

    class _Xctl:
        cics_text = "PROGRAM ( X ) RESP ( WS-R ( 1 ) )"

    assert _cics_resp_field(_Xctl())[0] is None
    assert "RESP option" in _cics_resp_field(_Xctl())[1]

    class _Resp2Only:
        cics_text = "PROGRAM ( X ) RESP2 ( WS-R2 )"

    assert _cics_resp_field(_Resp2Only()) == (None, None)


SECTION_GO_TO_EXIT_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SECEXIT.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-RC  PIC 9(4) VALUE 0.
       01 WS-AMT PIC S9(4) VALUE 0.
       01 WS-I   PIC 9(4) VALUE 0.
       01 WS-SUM PIC 9(4) VALUE 0.
       PROCEDURE DIVISION.
       A000-MAIN SECTION.
       A010-START.
           PERFORM B000-VALIDATE
           IF WS-RC = 0
               PERFORM C000-SUM
           END-IF
           GOBACK.
       B000-VALIDATE SECTION.
       B010.
           IF WS-AMT < 0
               MOVE 8 TO WS-RC
               GO TO B099-EXIT
           END-IF
           MOVE 0 TO WS-RC.
       B099-EXIT.
           EXIT.
       C000-SUM SECTION.
       C010.
           PERFORM VARYING WS-I FROM 1 BY 1 UNTIL WS-I > 3
               ADD WS-I TO WS-SUM
               CALL "TRACE" USING WS-I
           END-PERFORM.
"""


def test_terminator_after_a_section_scoped_go_to_exit_is_planned():
    """Issue #259: B099-EXIT ends a section entered only by PERFORM
    B000-VALIDATE, so its implicit PERFORM return fires there and C010 is
    never reached by falling through. The terminator planner treated C010
    as a GO TO fall-through hazard while the reachability gate did not."""
    program, surface, scope_map, lines = _analyze(SECTION_GO_TO_EXIT_SOURCE)
    plans, reasons = find_terminator_plans(
        surface, program, _suite("A000-MAIN"), scope_map, lines
    )
    assert reasons == []
    assert [plan.site.label for plan in plans] == ["GOBACK"]


def test_go_to_fallthrough_section_stop_is_dropped_for_a_member_entry():
    """Naming a member paragraph directly bypasses PERFORM <section-name>,
    so that section's end is no stop and the walk carries on."""
    from mockymock.analysis.refusal._reachability import (
        _fallthrough_safe_sections,
        _paragraph_safe_section_map,
    )

    program, _, _, _ = _analyze(SECTION_GO_TO_EXIT_SOURCE)
    members = {
        "A000-MAIN": ["A010-START"],
        "B000-VALIDATE": ["B010", "B099-EXIT"],
        "C000-SUM": ["C010"],
    }
    safe = _fallthrough_safe_sections(program)
    assert _go_to_fallthrough_targets(program, {"B099-EXIT"}) == {"C010": "B099-EXIT"}
    stopped = _paragraph_safe_section_map(members, safe, {"A000-MAIN"})
    assert _go_to_fallthrough_targets(program, {"B099-EXIT"}, stopped) == {}
    bypassed = _paragraph_safe_section_map(members, safe, {"B010"})
    assert _go_to_fallthrough_targets(program, {"B099-EXIT"}, bypassed) == {
        "C010": "B099-EXIT"
    }
