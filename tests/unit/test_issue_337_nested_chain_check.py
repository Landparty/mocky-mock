"""Issue #337: a chain PERFORM nested in an IF branch, an EVALUATE WHEN or
an inline PERFORM body gets its early-exit check right after the PERFORM,
inside that branch -- not after the enclosing END-IF/END-EVALUATE/
END-PERFORM, where the rest of the branch (or the next loop iteration)
would still run after the program should have ended."""

from cobolparser import parse_cobol
from cobolparser.preprocess import normalize_fixed_format

from mockymock.analysis.mock_surface import analyze
from mockymock.analysis.refusal import find_terminator_plans
from mockymock.dsl.model import MockTestCase, MockTestSuite
from mockymock.splicer.naming import TallyRegistry
from mockymock.splicer.orchestrator import splice_program
from mockymock.splicer.source_map import (
    annotate_nested_sites,
    collect_boundaries,
    collect_scope_map,
)

SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. NESTCHK.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-CNT  PIC 9(3) VALUE 2.
       01 WS-POST PIC 9(3) VALUE 0.
       01 WS-FLAG PIC X VALUE "Y".
       PROCEDURE DIVISION.
       IF-PARA.
           IF WS-FLAG = "Y"
               PERFORM STEP-PARA
               ADD 1 TO WS-POST
           END-IF
           GOBACK.
       EV-PARA.
           EVALUATE WS-FLAG
               WHEN "Y"
                   PERFORM STEP-PARA
                   MOVE 1 TO WS-POST
               WHEN OTHER
                   CONTINUE
           END-EVALUATE
           GOBACK.
       LOOP-PARA.
           PERFORM UNTIL WS-CNT >= 5
               PERFORM STEP-PARA
           END-PERFORM
           GOBACK.
       GLUED-PARA.
           IF WS-FLAG = "Y"
               PERFORM STEP-PARA ADD 1 TO WS-POST
           END-IF
           GOBACK.
       STEP-PARA.
           ADD 1 TO WS-CNT
           IF WS-CNT = 3
               DISPLAY "FATAL"
               GOBACK
           END-IF.
"""


def _plan(target):
    result = parse_cobol(SOURCE, filename="nestchk.cbl")
    assert result.success, result.errors
    surface = analyze(result.ast)
    lines = normalize_fixed_format(SOURCE.splitlines()).splitlines()
    scope_map = collect_scope_map(result.ast, lines)
    annotate_nested_sites(surface, scope_map, lines)
    suite = MockTestSuite(
        name="T", test_cases=[MockTestCase(name="c", perform_target=target)]
    )
    plans, reasons = find_terminator_plans(surface, result.ast, suite, scope_map, lines)
    return result, surface, lines, suite, plans, reasons


def _splice(target):
    result, surface, lines, suite, plans, reasons = _plan(target)
    assert reasons == []
    return splice_program(
        lines,
        collect_boundaries(result.ast),
        surface,
        suite,
        TallyRegistry(suite),
        plans,
    )


def _line_after_perform(spliced, paragraph):
    header = next(i for i, line in enumerate(spliced) if f"{paragraph}." in line)
    index = next(
        i
        for i, line in enumerate(spliced)
        if i > header and "PERFORM STEP-PARA" in line
    )
    return spliced[index + 1].strip()


def test_check_lands_inside_the_if_branch():
    spliced = _splice("IF-PARA")
    assert _line_after_perform(spliced, "IF-PARA") == 'IF UT-EARLY-EXIT = "Y"'
    check = next(i for i, line in enumerate(spliced) if "UT-EARLY-EXIT =" in line)
    post = next(i for i, line in enumerate(spliced) if "ADD 1 TO WS-POST" in line)
    assert check < post


def test_check_lands_inside_the_evaluate_when():
    spliced = _splice("EV-PARA")
    assert _line_after_perform(spliced, "EV-PARA") == 'IF UT-EARLY-EXIT = "Y"'


def test_check_lands_inside_the_inline_perform_body():
    spliced = _splice("LOOP-PARA")
    assert _line_after_perform(spliced, "LOOP-PARA") == 'IF UT-EARLY-EXIT = "Y"'
    header = next(i for i, line in enumerate(spliced) if "LOOP-PARA." in line)
    check = next(
        i for i, line in enumerate(spliced) if i > header and "UT-EARLY-EXIT =" in line
    )
    end_perform = next(i for i, line in enumerate(spliced) if "END-PERFORM" in line)
    assert check < end_perform


def test_nested_chain_perform_without_a_safe_span_goes_back_to_the_test():
    """No early-exit check fits after the glued PERFORM, so the terminators
    GOBACK to the test from the driver's call frame instead (2026-11-03)."""
    *_, plans, reasons = _plan("GLUED-PARA")
    assert plans and {p.exit_kind for p in plans} == {"RETURN"}
    assert reasons == []
