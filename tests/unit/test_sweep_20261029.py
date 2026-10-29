"""Sweep blockers of 2026-10-29: the classic sectioned layout (every
SECTION's nameless main line is paragraph '') and terminators under a
PERFORM ... UNTIL loop."""

from cobolparser import parse_cobol
from cobolparser.preprocess import normalize_fixed_format

from mockymock.analysis.mock_surface import analyze
from mockymock.analysis.refusal import find_terminator_plans
from mockymock.analysis.refusal._reachability import _fallthrough_safe_sections
from mockymock.dsl.model import MockTestCase, MockTestSuite
from mockymock.splicer.injector import prefix_loop_conditions
from mockymock.splicer.source_map import annotate_nested_sites, collect_scope_map


def _analyze(source):
    result = parse_cobol(source, filename="X.cbl")
    assert result.success, result.errors
    lines = normalize_fixed_format(source.splitlines()).splitlines()
    surface = analyze(result.ast)
    scope_map = collect_scope_map(result.ast, lines)
    annotate_nested_sites(surface, scope_map, lines)
    return result.ast, surface, scope_map, lines


def _plans(source, target):
    program, surface, scope_map, lines = _analyze(source)
    suite = MockTestSuite(
        name="S", test_cases=[MockTestCase(name="c", perform_target=target)]
    )
    return find_terminator_plans(surface, program, suite, scope_map, lines)


# Each section's main line sits right under its header, ends at a
# `NNNN-EXIT. EXIT.` paragraph, and leaves early with GO TO NNNN-EXIT.
SECTION_EXIT_IDIOM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SECIDIOM.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-EOF-SW    PIC X VALUE 'N'.
           88 WS-EOF    VALUE 'Y'.
       01  WS-RC        PIC S9(4) COMP VALUE 0.
       PROCEDURE DIVISION.
       0000-MAINLINE SECTION.
           PERFORM 1000-INITIALIZE
           PERFORM 2000-PROCESS UNTIL WS-EOF
           GOBACK.
       0000-EXIT.
           EXIT.
       1000-INITIALIZE SECTION.
           PERFORM 2100-READ.
       1000-EXIT.
           EXIT.
       2000-PROCESS SECTION.
           CALL 'SUBPGM1' USING WS-RC
           IF WS-RC NOT = 0
              GO TO 2000-EXIT
           END-IF
           PERFORM 2100-READ.
       2000-EXIT.
           EXIT.
       2100-READ SECTION.
           CALL 'GETREC' USING WS-RC
           IF WS-RC = 4
              SET WS-EOF TO TRUE
           END-IF
           IF WS-RC > 4
              PERFORM 9999-ABEND
           END-IF.
       2100-EXIT.
           EXIT.
       9999-ABEND SECTION.
           MOVE 16 TO RETURN-CODE
           STOP RUN.
       9999-EXIT.
           EXIT.
"""


def test_a_goto_to_the_own_section_exit_keeps_the_section_safe():
    """`GO TO 2000-EXIT` in 2000-PROCESS's main line used to read as a jump
    in from outside: the enclosing section was looked up by the name ''
    and came back as the last section with a main line (9999-ABEND)."""
    program, _, _, _ = _analyze(SECTION_EXIT_IDIOM)
    assert "2000-PROCESS" in _fallthrough_safe_sections(program)


def test_the_section_exit_idiom_plans_both_terminators():
    """Refused before: falling past 2000-EXIT was taken to run on into the
    next section, and every main line ('') counted as fallen into."""
    plans, reasons = _plans(SECTION_EXIT_IDIOM, "0000-MAINLINE")
    assert reasons == []
    assert sorted(p.site.label for p in plans) == ["GOBACK", "STOP RUN"]
    assert {p.exit_kind for p in plans} == {"SECTION"}
    chain = {p.target_paragraph for p in plans[0].chain_performs}
    # Every PERFORMed section's main line is walked, not only the first ''.
    assert chain == {"1000-INITIALIZE", "2000-PROCESS", "2100-READ", "9999-ABEND"}
    assert [p.target_paragraph for p in plans[0].loop_performs] == ["2000-PROCESS"]


GO_TO_INTO_A_SECTION = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. GOTOSEC.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-RC        PIC S9(4) COMP VALUE 0.
       PROCEDURE DIVISION.
       A000-MAIN SECTION.
           PERFORM B000-WORK
           GOBACK.
       B000-WORK SECTION.
           CALL 'SUBPGM2' USING WS-RC
           IF WS-RC NOT = 0
              GO TO Z999-ERROR
           END-IF
           DISPLAY 'OK'.
       Z999-ERROR SECTION.
           MOVE 12 TO RETURN-CODE
           STOP RUN.
"""


def test_a_main_line_entered_by_go_to_is_refused():
    """Z999-ERROR is only ever entered by GO TO. Its STOP RUN was planned
    with EXIT SECTION because A000-MAIN's main line, also named '', is in
    section mode -- and EXIT SECTION there runs off the end of the
    program instead of returning to the test."""
    plans, reasons = _plans(GO_TO_INTO_A_SECTION, "A000-MAIN")
    assert [p.site.label for p in plans] == ["GOBACK"]
    assert len(reasons) == 1
    assert reasons[0].code == "UNSUPPORTED_TERMINATOR_LAYOUT"
    assert "main line of SECTION 'Z999-ERROR'" in reasons[0].message


ALSO_UNDER_A_THRU = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ALSOTHRU.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-RC        PIC S9(4) COMP VALUE 0.
       PROCEDURE DIVISION.
       0000-MAIN.
           PERFORM 1000-CHECK
           PERFORM 2000-STEP THRU 2000-EXIT
           GOBACK.
       1000-CHECK.
           IF WS-RC > 4
              PERFORM 9999-ABEND
           END-IF.
       2000-STEP.
           CALL 'SUBPGM3' USING WS-RC
           PERFORM 1000-CHECK.
       2000-EXIT.
           EXIT.
       9999-ABEND.
           STOP RUN.
"""


def test_a_terminator_also_reached_under_a_thru_is_refused():
    """9999-ABEND is on the plain chain (via 1000-CHECK) but also reached
    from inside the PERFORM ... THRU range, where nothing ends the range at
    the early exit: 2000-STEP would return into 2000-EXIT and the main line
    would carry on. Planned (and wrong) before."""
    plans, reasons = _plans(ALSO_UNDER_A_THRU, "0000-MAIN")
    stop_run = [r for r in reasons if "STOP RUN" in r.message]
    assert len(stop_run) == 1
    assert "PERFORM 2000-STEP THRU 2000-EXIT at line 9" in stop_run[0].message
    assert all(p.site.label != "STOP RUN" for p in plans)


def test_prefix_loop_conditions_extends_each_until():
    lines = [
        "    PERFORM 2000-PROCESS UNTIL WS-EOF",
        "    PERFORM 3000-X",
        "        UNTIL WS-NAME = 'UNTIL' *> UNTIL here is a comment",
        "    PERFORM 4000-Y UNTIL-FLAG",
    ]
    out = prefix_loop_conditions(lines, 1, 3)
    assert out[0] == '    PERFORM 2000-PROCESS UNTIL UT-EARLY-EXIT = "Y" OR WS-EOF'
    assert out[2] == (
        "        UNTIL UT-EARLY-EXIT = \"Y\" OR WS-NAME = 'UNTIL' "
        "*> UNTIL here is a comment"
    )
    # Outside the span, and a word that only starts with UNTIL, untouched.
    assert out[3] == lines[3]
    assert prefix_loop_conditions(lines, 4, 4) == lines
    assert len(out) == len(lines)
