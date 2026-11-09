"""The call-frame driver (2026-11-03): a terminator no EXIT verb returns
from GOBACKs to the test out of a CALL of the driver's own entry."""

from cobolparser import parse_cobol

from mockymock.dsl.model import MockTestCase, MockTestSuite
from mockymock.splicer.driver import (
    CALL_FRAME_ENTRY,
    build_driver,
    call_frame_lines,
)
from mockymock.splicer.injector import build_terminator_neutralization
from mockymock.splicer.insertion import mark_recursive
from mockymock.splicer.naming import TallyRegistry
from mockymock.splicer.reset import reset_move_lines


def _suite() -> MockTestSuite:
    return MockTestSuite(
        name="S",
        test_cases=[
            MockTestCase(name="a", perform_target="MAIN-LINE"),
            MockTestCase(name="b", perform_target="P1", perform_thru="P2"),
        ],
    )


def test_the_frame_runs_each_cases_perform_and_goes_back():
    lines = [line.strip() for line in call_frame_lines(_suite())]
    assert lines[0] == "UT-RUN-CASE."
    assert lines[1] == f'ENTRY "{CALL_FRAME_ENTRY}"'
    assert lines[2:9] == [
        "EVALUATE UT-CURRENT-CASE",
        'WHEN "001"',
        "PERFORM MAIN-LINE",
        'WHEN "002"',
        "PERFORM P1 THRU P2",
        "END-EVALUATE",
        "GOBACK.",
    ]


def test_a_call_frame_driver_calls_the_entry_instead_of_performing():
    suite = _suite()
    plain = build_driver(suite, reset_lines=[], registry=TallyRegistry(suite))
    framed = build_driver(
        suite, reset_lines=[], registry=TallyRegistry(suite), call_frame=True
    )
    assert not plain.call_frame and framed.call_frame
    plain_text = "\n".join(plain.procedure_lines)
    framed_text = "\n".join(framed.procedure_lines)
    assert CALL_FRAME_ENTRY not in plain_text
    assert framed_text.count(f'CALL "{CALL_FRAME_ENTRY}"') == 2
    assert f'ENTRY "{CALL_FRAME_ENTRY}"' in framed_text


def test_the_return_neutralization_sets_the_flag_and_goes_back():
    assert [line.strip() for line in build_terminator_neutralization("RETURN")] == [
        'MOVE "Y" TO UT-EARLY-EXIT',
        "GOBACK",
    ]
    lines = build_terminator_neutralization("RETURN", return_code="12")
    assert lines[0].strip() == "MOVE 12 TO RETURN-CODE"


def test_mark_recursive_marks_the_first_program_id_once():
    lines = [
        "       IDENTIFICATION DIVISION.",
        "       PROGRAM-ID. DEEP.",
        "       PROGRAM-ID. INNER.",
    ]
    marked = mark_recursive(lines)
    assert marked[1].strip() == "PROGRAM-ID. DEEP IS RECURSIVE."
    assert marked[2] == lines[2]
    assert mark_recursive(marked) == marked


def test_mark_recursive_leaves_an_initial_program_alone():
    lines = ["       PROGRAM-ID. DEEP IS INITIAL."]
    assert mark_recursive(lines) == lines


def test_a_custom_currency_picture_resets_as_numeric_edited():
    """NIST NC107A: `PIC WWWWW` under `CURRENCY SIGN IS "W"`; a
    `MOVE SPACES TO` it is rejected by cobc."""
    source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CURR.
       ENVIRONMENT DIVISION.
       CONFIGURATION SECTION.
       SPECIAL-NAMES.
           CURRENCY SIGN IS "W".
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-AMOUNT  PIC WWWWW.
       01  WS-TEXT    PIC X(4).
       PROCEDURE DIVISION.
       MAIN-PARA.
           STOP RUN.
"""
    result = parse_cobol(source, filename="curr.cbl")
    assert result.success, result.errors
    lines = reset_move_lines(result.ast)
    assert not any("SPACES TO WS-AMOUNT" in line for line in lines)
    assert any("SPACES TO WS-TEXT" in line for line in lines)


def test_mark_recursive_finds_a_name_on_the_line_after_program_id():
    """NIST IC222A: `PROGRAM-ID.` alone, the name on the next line."""
    lines = ["       PROGRAM-ID.", "", "           IC222A.", "       AUTHOR. X."]
    marked = mark_recursive(lines)
    assert marked[2].strip() == "IC222A IS RECURSIVE."
    assert marked[0] == lines[0] and marked[3] == lines[3]


def test_the_end_of_program_trap_goes_before_a_nested_program():
    from mockymock.splicer.insertion import _insert_end_of_program_trap

    lines = [
        "       IDENTIFICATION DIVISION.",
        "       PROGRAM-ID. OUTER.",
        "       PROCEDURE DIVISION.",
        "       MAIN-PARA.",
        "           STOP RUN.",
        "       IDENTIFICATION DIVISION.",
        "       PROGRAM-ID. INNER.",
        "       PROCEDURE DIVISION.",
        "       INNER-PARA.",
        "           GOBACK.",
        "       END PROGRAM INNER.",
        "       END PROGRAM OUTER.",
    ]
    result = list(lines)
    _insert_end_of_program_trap(result, set())
    trap = next(
        i for i, line in enumerate(result) if "UT-END-OF-PROGRAM SECTION" in line
    )
    inner = next(i for i, line in enumerate(result) if "PROGRAM-ID. INNER" in line)
    assert result.index(lines[4]) < trap < inner
