from cobolparser import parse_cobol

from mockymock.splicer.reset import reset_move_lines

SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SAMPLE.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-DISCOUNT-PCT    PIC 9V99.
       01  WS-NET-AMOUNT      PIC 9(5)V99.
       01  WS-EOF-FLAG        PIC X VALUE "N".
       01  WS-ORDER-STATUS    PIC XX.

       PROCEDURE DIVISION.
       MAIN-PARA.
           STOP RUN.
"""


def _ast():
    result = parse_cobol(SOURCE, filename="sample.cbl")
    assert result.success, result.errors
    return result.ast


def test_item_with_value_clause_resets_to_that_value():
    lines = reset_move_lines(_ast())
    assert 'MOVE "N" TO WS-EOF-FLAG' in lines


def test_numeric_item_without_value_clause_resets_to_zero():
    lines = reset_move_lines(_ast())
    assert "MOVE 0 TO WS-DISCOUNT-PCT" in lines
    assert "MOVE 0 TO WS-NET-AMOUNT" in lines


def test_alphanumeric_item_without_value_clause_resets_to_spaces():
    lines = reset_move_lines(_ast())
    assert "MOVE SPACES TO WS-ORDER-STATUS" in lines


def test_one_line_per_top_level_item():
    lines = reset_move_lines(_ast())
    assert len(lines) == 4
