"""2026-08-12 bug review: the reachability BFS must close over the GO TO
fall-through hazard.

A GO TO target whose body does not provably divert control continues -- by
ordinary sequential execution, not a flow edge -- into the next paragraph
in source order. Before the fix, `_reachable_paragraphs` stopped at the GO
TO target, so a boundary (CALL/file-op/ACCEPT) in the fallen-into paragraph
passed every gate unmocked, survived splicing verbatim, and executed for
real at runtime. `union_executed_paragraphs` and the terminator layer
already modeled this exact hazard; the per-case mock gate was the one
consumer that didn't.
"""

from cobolparser import parse_cobol

from mockymock.analysis.mock_surface import analyze
from mockymock.analysis.refusal import _reachable_paragraphs, check_test_case
from mockymock.dsl.model import MockCategory, MockDirective, MockTestCase

FALLTHROUGH_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. FALLTHRU.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-FLAG      PIC 9 VALUE 1.
       01  WS-RESULT    PIC X(10).
       PROCEDURE DIVISION.
       MAIN-PARA.
           IF WS-FLAG = 1
               GO TO OTHER-PARA
           END-IF.
           DISPLAY 'NO JUMP'.
           GOBACK.
       OTHER-PARA.
           DISPLAY 'JUMPED'.
       FALLEN-PARA.
           CALL 'SUBPROG' USING WS-RESULT.
           GOBACK.
"""

CHAINED_FALLTHROUGH_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. FALLCHAIN.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-RESULT    PIC X(10).
       PROCEDURE DIVISION.
       MAIN-PARA.
           GO TO HOP-PARA.
       HOP-PARA.
           DISPLAY 'HOP'.
       STEP-PARA.
           DISPLAY 'STEP'.
       DEEP-PARA.
           CALL 'DEEPSUB' USING WS-RESULT.
           GOBACK.
"""

STOPPED_FALLTHROUGH_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. NOFALL.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-RESULT    PIC X(10).
       PROCEDURE DIVISION.
       MAIN-PARA.
           GO TO END-PARA.
       END-PARA.
           DISPLAY 'DONE'.
           GOBACK.
       NEVER-PARA.
           CALL 'NEVERSUB' USING WS-RESULT.
           GOBACK.
"""


def _program(source):
    result = parse_cobol(source)
    assert result.errors == [], result.errors
    return result.ast


class TestReachableSetClosesOverFallThrough:
    def test_fallen_into_paragraph_is_reachable(self):
        program = _program(FALLTHROUGH_SOURCE)
        reachable, reasons = _reachable_paragraphs(program, "MAIN-PARA")
        assert reasons == []
        assert "FALLEN-PARA" in reachable

    def test_fall_through_chain_propagates(self):
        # HOP-PARA falls into STEP-PARA falls into DEEP-PARA: the closure
        # must reach the end of the chain, not just one hop.
        program = _program(CHAINED_FALLTHROUGH_SOURCE)
        reachable, reasons = _reachable_paragraphs(program, "MAIN-PARA")
        assert reasons == []
        assert {"HOP-PARA", "STEP-PARA", "DEEP-PARA"} <= reachable

    def test_goback_stops_the_walk(self):
        # END-PARA ends in GOBACK (provably diverts), so NEVER-PARA is NOT
        # reachable -- the closure must not over-reach past a terminator.
        program = _program(STOPPED_FALLTHROUGH_SOURCE)
        reachable, reasons = _reachable_paragraphs(program, "MAIN-PARA")
        assert reasons == []
        assert "NEVER-PARA" not in reachable


class TestGateRefusesUnmockedFallenBoundary:
    def test_unmocked_call_in_fallen_paragraph_refuses(self):
        program = _program(FALLTHROUGH_SOURCE)
        surface = analyze(program)
        case = MockTestCase(name="c1", perform_target="MAIN-PARA")
        codes = {r.code for r in check_test_case(surface, program, case)}
        assert "UNMOCKED_CALL" in codes

    def test_mocking_the_fallen_call_satisfies_the_gate(self):
        program = _program(FALLTHROUGH_SOURCE)
        surface = analyze(program)
        case = MockTestCase(
            name="c1",
            perform_target="MAIN-PARA",
            mocks=[
                MockDirective(
                    category=MockCategory.CALL,
                    key="SUBPROG",
                    body_lines=['MOVE "OK" TO WS-RESULT'],
                )
            ],
        )
        codes = {r.code for r in check_test_case(surface, program, case)}
        assert "UNMOCKED_CALL" not in codes
        # The directive matched a genuinely reachable site, so it must not
        # be flagged as unmatched either.
        assert "UNMATCHED_MOCK" not in codes

    def test_paragraph_past_a_terminator_needs_no_mock(self):
        # NEVER-PARA's CALL is unreachable (the fall-through chain stops at
        # END-PARA's GOBACK), so an unmocked run is still clean.
        program = _program(STOPPED_FALLTHROUGH_SOURCE)
        surface = analyze(program)
        case = MockTestCase(name="c1", perform_target="MAIN-PARA")
        codes = {r.code for r in check_test_case(surface, program, case)}
        assert "UNMOCKED_CALL" not in codes
