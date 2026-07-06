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


LEVEL_77_AND_GROUP_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SAMPLE2.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       77  WS-RETRY-LIMIT     PIC 9(2) VALUE 3.
       77  WS-SCRATCH         PIC X(8).
       01  WS-ORDER.
           05  WS-ORDER-QTY   PIC 9(3).
           05  WS-ORDER-DESC  PIC X(20).
       01  WS-TOTAL           PIC 9(5)V99.

       PROCEDURE DIVISION.
       MAIN-PARA.
           STOP RUN.
"""


def _ast_77_and_group():
    result = parse_cobol(LEVEL_77_AND_GROUP_SOURCE, filename="sample2.cbl")
    assert result.success, result.errors
    return result.ast


def test_level_77_item_with_value_resets_to_declared_value():
    lines = reset_move_lines(_ast_77_and_group())
    assert "MOVE 3 TO WS-RETRY-LIMIT" in lines


def test_level_77_item_without_value_resets_to_type_default():
    lines = reset_move_lines(_ast_77_and_group())
    assert "MOVE SPACES TO WS-SCRATCH" in lines


def test_group_item_without_value_is_initialized_not_space_filled():
    """MOVE SPACES TO a group would write spaces over its numeric children,
    corrupting them for the next test case's arithmetic. INITIALIZE sets
    numeric children to zero and alphanumeric children to spaces."""
    lines = reset_move_lines(_ast_77_and_group())
    assert "INITIALIZE WS-ORDER" in lines
    assert "MOVE SPACES TO WS-ORDER" not in lines


def test_every_top_level_item_is_covered():
    lines = reset_move_lines(_ast_77_and_group())
    assert len(lines) == 4


GROUP_WITH_CHILD_VALUES_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SAMPLE3.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  MQ-CONSTANTS.
           05  MQCC-OK       PIC S9(9) VALUE +0.
           05  MQCC-FAIL     PIC S9(9) VALUE +2.

       PROCEDURE DIVISION.
       MAIN-PARA.
           STOP RUN.
"""


def _ast_group_with_child_values():
    result = parse_cobol(GROUP_WITH_CHILD_VALUES_SOURCE, filename="sample3.cbl")
    assert result.success, result.errors
    return result.ast


def test_group_children_value_clauses_are_restored():
    lines = reset_move_lines(_ast_group_with_child_values())
    assert "INITIALIZE MQ-CONSTANTS" in lines
    assert any("MOVE +2 TO MQCC-FAIL" in ln for ln in lines)


NESTED_GROUP_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SAMPLE4.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-OUTER.
           05  WS-MIDDLE.
               10  WS-INNER-FLAG   PIC X VALUE "Y".
               10  WS-INNER-COUNT  PIC 9(3).
           05  WS-PLAIN            PIC X(4).

       PROCEDURE DIVISION.
       MAIN-PARA.
           STOP RUN.
"""


def _ast_nested_group():
    result = parse_cobol(NESTED_GROUP_SOURCE, filename="sample4.cbl")
    assert result.success, result.errors
    return result.ast


def test_nested_group_child_value_clause_is_restored():
    """A VALUE clause on a deeply-nested child (group-within-group) must
    still be restored after the outer INITIALIZE -- proves recursion."""
    lines = reset_move_lines(_ast_nested_group())
    assert "INITIALIZE WS-OUTER" in lines
    assert any('MOVE "Y" TO WS-INNER-FLAG' in ln for ln in lines)


def test_value_less_group_still_emits_only_initialize():
    """Regression guard: a group with no VALUE clauses anywhere among its
    children must still produce a bare INITIALIZE and no spurious MOVEs."""
    lines = reset_move_lines(_ast_77_and_group())
    order_related = [ln for ln in lines if "WS-ORDER" in ln]
    assert order_related == ["INITIALIZE WS-ORDER"]
