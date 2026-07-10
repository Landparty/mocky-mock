"""Unit tests for Approach B's safe-chain terminator detection
(docs/2026-07-08-goback-stop-run-support-design.md). Mirrors
tests/unit/test_linkage.py's structure: the analysis functions and the
refusal wrapper are tested together since they're always used together.
"""

from cobolparser import parse_cobol
from cobolparser.preprocess import normalize_fixed_format

from mockymock.analysis.mock_surface import analyze
from mockymock.analysis.refusal import (
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


def test_terminator_in_a_later_section_paragraph_still_refuses():
    """Even though 1000-TERM-SECTION is a safe entry (its first paragraph
    is never GO TO'd or directly PERFORMed elsewhere), the terminator
    here sits in 1000-TERM-SECOND -- reached only by fall-through after
    1000-TERM-FIRST, never PERFORMed by name anywhere this codebase's BFS
    would follow. Shape 2 from
    docs/2026-07-10-section-scoped-terminator-support-design.md,
    deliberately still out of scope: pins the boundary as documented
    intent, not an accident of the safe_section_first_names check."""
    program, surface, scope_map, lines = _analyze(SECTION_LATER_PARAGRAPH_UNSAFE_SOURCE)
    plans, reasons = find_terminator_plans(surface, program, _suite(), scope_map, lines)
    assert plans == []
    assert len(reasons) == 1
    assert reasons[0].code == "UNSUPPORTED_TERMINATOR_LAYOUT"
    assert "SECTION" in reasons[0].message


def test_section_own_paragraph_terminator_refuses():
    """The terminator's OWN paragraph (0000-MAIN-PROCESS) is a SECTION
    member, reached directly as the case's perform_target -- distinct from
    test_section_scoped_terminator_refuses, which tests the chain-level
    check instead."""
    program, surface, scope_map, lines = _analyze(SECTION_OWN_PARAGRAPH_UNSAFE_SOURCE)
    plans, reasons = find_terminator_plans(surface, program, _suite(), scope_map, lines)
    assert plans == []
    assert len(reasons) == 1
    assert reasons[0].code == "UNSUPPORTED_TERMINATOR_LAYOUT"
    assert "SECTION" in reasons[0].message


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
