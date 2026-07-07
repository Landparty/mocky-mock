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


GROUP_WITH_FILLER_CHILD_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SAMPLE5.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-HDR.
           05  FILLER         PIC X(5) VALUE "CIF  ".
           05  WS-NAMED       PIC X(3) VALUE "ABC".

       PROCEDURE DIVISION.
       MAIN-PARA.
           STOP RUN.
"""


def _ast_group_with_filler_child():
    result = parse_cobol(GROUP_WITH_FILLER_CHILD_SOURCE, filename="sample5.cbl")
    assert result.success, result.errors
    return result.ast


def test_filler_child_is_never_targeted_by_reset():
    """FILLER is unaddressable in COBOL -- MOVE ... TO FILLER is a syntax
    error. A group's FILLER child with a VALUE clause must be skipped when
    restoring child VALUEs after INITIALIZE (INITIALIZE also never disturbs
    FILLER, so there's nothing to restore anyway). Named siblings must still
    be restored normally."""
    lines = reset_move_lines(_ast_group_with_filler_child())
    assert "INITIALIZE WS-HDR" in lines
    assert any('MOVE "ABC" TO WS-NAMED' in ln for ln in lines)
    assert not any("TO FILLER" in ln for ln in lines)


# --- PICTURE-less usage-typed items (audit 2.3) -------------------------------

USAGE_TYPED_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SAMPLE6.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-PTR             USAGE POINTER.
       01  WS-IDX             USAGE INDEX.
       01  WS-SHORT           COMP-1.
       01  WS-LONG            USAGE COMP-2.
       01  WS-PLAIN           PIC X(4).

       PROCEDURE DIVISION.
       MAIN-PARA.
           STOP RUN.
"""


def _ast_usage_typed():
    result = parse_cobol(USAGE_TYPED_SOURCE, filename="sample6.cbl")
    assert result.success, result.errors
    return result.ast


def test_pointer_item_is_reset_with_set_to_null_not_move():
    """MOVE SPACES TO a POINTER item is illegal COBOL (cobc rejects it);
    SET ... TO NULL is the only legal reset."""
    lines = reset_move_lines(_ast_usage_typed())
    assert "SET WS-PTR TO NULL" in lines
    assert not any("MOVE" in ln and "WS-PTR" in ln for ln in lines)


def test_index_item_is_skipped_not_given_illegal_move():
    """USAGE INDEX items accept neither MOVE SPACES nor MOVE 0 -- skipping
    is the only reset that never emits illegal COBOL (documented fidelity
    limit)."""
    lines = reset_move_lines(_ast_usage_typed())
    assert not any("WS-IDX" in ln for ln in lines)


def test_comp1_and_comp2_items_reset_to_zero_not_spaces():
    """COMP-1/COMP-2 have no PICTURE, so the old picture-based numeric test
    classified them alphanumeric and emitted an illegal MOVE SPACES."""
    lines = reset_move_lines(_ast_usage_typed())
    assert "MOVE 0 TO WS-SHORT" in lines
    assert "MOVE 0 TO WS-LONG" in lines
    assert not any("MOVE SPACES TO WS-SHORT" in ln for ln in lines)
    assert not any("MOVE SPACES TO WS-LONG" in ln for ln in lines)


# --- numeric-edited PICs and OCCURS children (audit 2.4) ----------------------

EDITED_AND_OCCURS_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SAMPLE7.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-EDITED          PIC ZZZ9.
       01  WS-EDITED-BARE     PIC ZZZ.
       01  WS-GRP.
           05  WS-CELL        PIC 9 OCCURS 5 TIMES VALUE 7.
           05  WS-NAMED       PIC X(3) VALUE "ABC".

       PROCEDURE DIVISION.
       MAIN-PARA.
           STOP RUN.
"""


def _ast_edited_and_occurs():
    result = parse_cobol(EDITED_AND_OCCURS_SOURCE, filename="sample7.cbl")
    assert result.success, result.errors
    return result.ast


def test_numeric_edited_items_reset_to_zero_not_spaces():
    """PIC ZZZ9 / PIC ZZZ are numeric-edited: MOVE SPACES to them is
    rejected by cobc, MOVE 0 is the legal reset."""
    lines = reset_move_lines(_ast_edited_and_occurs())
    assert "MOVE 0 TO WS-EDITED" in lines
    assert "MOVE 0 TO WS-EDITED-BARE" in lines
    assert not any("MOVE SPACES TO WS-EDITED" in ln for ln in lines)


def test_occurs_child_with_value_is_skipped_not_given_unsubscripted_move():
    """Audit finding 2.4: `MOVE 7 TO WS-CELL` against an OCCURS child is
    illegal (needs a subscript) and cobc rejected the whole program.
    Skipping is the sound minimal fix (documented fidelity limit); the
    non-OCCURS sibling's VALUE must still be restored."""
    lines = reset_move_lines(_ast_edited_and_occurs())
    assert "INITIALIZE WS-GRP" in lines
    assert not any("WS-CELL" in ln for ln in lines)
    assert any('MOVE "ABC" TO WS-NAMED' in ln for ln in lines)
