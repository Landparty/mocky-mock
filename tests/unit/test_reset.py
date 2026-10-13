from cobolparser import parse_cobol

from mockymock.splicer.reset import cobol_literal, reset_move_lines

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


def test_occurs_child_with_value_is_restored_through_initialize_to_value():
    """Issue #156: an OCCURS child's VALUE was left at INITIALIZE's zero
    fill, so tests saw different starting data from the real program. An
    unsubscripted `MOVE 7 TO WS-CELL` is illegal COBOL, so the group is
    reset with INITIALIZE's ALL TO VALUE phrase, which restores every
    occurrence and the non-OCCURS sibling's VALUE in one statement."""
    lines = reset_move_lines(_ast_edited_and_occurs())
    assert "INITIALIZE WS-GRP ALL TO VALUE THEN TO DEFAULT" in lines
    assert "INITIALIZE WS-GRP" not in lines
    assert not any("WS-CELL" in ln for ln in lines)
    assert not any("WS-NAMED" in ln for ln in lines)


NESTED_OCCURS_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SAMPLE7B.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-TABLE.
           05  WS-ROW         OCCURS 3 TIMES.
               10  WS-FLAG    PIC X VALUE "Y".
               10  WS-AMT     PIC 9(3).
       01  WS-PLAIN-TABLE.
           05  WS-SLOT        PIC 9 OCCURS 4 TIMES.
           05  WS-LABEL       PIC X(3) VALUE "ABC".

       PROCEDURE DIVISION.
       MAIN-PARA.
           STOP RUN.
"""


def test_value_under_an_occurs_group_uses_initialize_to_value():
    """A VALUE on a child of an OCCURS group is inside the table too; a
    table without any VALUE keeps the plain INITIALIZE plus restores."""
    result = parse_cobol(NESTED_OCCURS_SOURCE, filename="sample7b.cbl")
    assert result.success, result.errors
    lines = reset_move_lines(result.ast)
    assert "INITIALIZE WS-TABLE ALL TO VALUE THEN TO DEFAULT" in lines
    assert "INITIALIZE WS-PLAIN-TABLE" in lines
    assert 'MOVE "ABC" TO WS-LABEL' in lines


# --- REDEFINES children (two REDEFINES of the same nested item) ---------------

REDEFINES_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SAMPLE8.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-RECORD.
           05  VARIABLE           PIC X(08).
           05  VARIABLE-NAME REDEFINES VARIABLE PIC 9(08).
           05  BARIABLE REDEFINES VARIABLE.
               10  BARIABLE-B1  PIC X(04).
               10  BARIABLE-B2  PIC X(04).

       PROCEDURE DIVISION.
       MAIN-PARA.
           STOP RUN.
"""


def _ast_redefines():
    result = parse_cobol(REDEFINES_SOURCE, filename="sample8.cbl")
    assert result.success, result.errors
    return result.ast


def test_group_with_redefines_children_resets_via_single_initialize():
    """WS-RECORD has no VALUE clause, so the whole group -- including
    VARIABLE and both of its REDEFINES siblings, which alias the same
    storage -- resets via one INITIALIZE. Neither REDEFINES child declares
    its own VALUE, so no extra per-child MOVE should be emitted for them."""
    lines = reset_move_lines(_ast_redefines())
    assert lines == ["INITIALIZE WS-RECORD"]


TOP_LEVEL_REDEFINES_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SAMPLE9.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-CODE            PIC X(4) VALUE "AB12".
       01  WS-CODE-NUM        REDEFINES WS-CODE PIC 9(4).
       01  WS-DATE.
           05  WS-YYYY        PIC 9(4) VALUE 2026.
           05  WS-MM          PIC 99   VALUE 9.
       01  WS-DATE-X          REDEFINES WS-DATE PIC X(6).
       01  WS-AFTER           PIC X.

       PROCEDURE DIVISION.
       MAIN-PARA.
           STOP RUN.
"""


def test_top_level_redefines_item_does_not_clobber_the_redefined_value():
    """A top-level REDEFINES item shares its storage with the item it
    redefines. Resetting it too (`MOVE 0 TO WS-CODE-NUM`, `MOVE SPACES TO
    WS-DATE-X`) ran AFTER the redefined item's own VALUE-restoring line and
    overwrote it, so every test case -- the first included -- saw "0000"
    where the program declared VALUE "AB12" (verified end-to-end with
    GnuCOBOL: `EXPECT WS-OUT TO BE "AB12"` failed with `got 0000`)."""
    result = parse_cobol(TOP_LEVEL_REDEFINES_SOURCE, filename="sample9.cbl")
    assert result.success, result.errors
    assert reset_move_lines(result.ast) == [
        'MOVE "AB12" TO WS-CODE',
        "INITIALIZE WS-DATE",
        "MOVE 2026 TO WS-YYYY",
        "MOVE 9 TO WS-MM",
        "MOVE SPACES TO WS-AFTER",
    ]


# Embedded-quote literals: cobolparser wraps a VALUE clause's DECODED content
# in double quotes, and versions through 1.8.0 did not re-double an embedded
# quote when doing so -- CICS's DFHAID copybook declares exactly that shape
# (`DFHTRIG PIC X VALUE IS '"'`), which reached the reset paragraph as an
# unterminated three-quote literal and desynchronized cobc's tokenizer.
QUOTE_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. DFHAIDS.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  DFHTRIG            PIC X VALUE IS '"'.
       01  WS-MIXED           PIC X(3) VALUE 'A"B'.
       01  WS-PLAIN           PIC XX VALUE "OK".

       PROCEDURE DIVISION.
       MAIN-PARA.
           STOP RUN.
"""


def test_value_clause_with_embedded_quote_is_reset_with_a_valid_literal():
    result = parse_cobol(QUOTE_SOURCE, filename="dfhaids.cbl")
    assert result.success, result.errors
    lines = reset_move_lines(result.ast)
    # Four quote characters: the two delimiters plus the doubled content.
    assert 'MOVE """" TO DFHTRIG' in lines
    assert 'MOVE "A""B" TO WS-MIXED' in lines
    assert 'MOVE "OK" TO WS-PLAIN' in lines


def test_cobol_literal_doubles_unescaped_quotes():
    quote = chr(34)
    # The malformed shape cobolparser <= 1.8.0 produces for a one-character
    # literal holding a quote: three quotes in, four (a valid literal) out.
    assert cobol_literal(quote * 3) == quote * 4
    assert cobol_literal('"A' + quote + 'B"') == '"A' + quote * 2 + 'B"'


def test_cobol_literal_is_idempotent_against_a_fixed_parser():
    """The fixed cobolparser already doubles the embedded quote, so an
    already-well-formed literal must pass through untouched -- otherwise
    bumping the dependency floor would silently double it a second time."""
    quote = chr(34)
    assert cobol_literal(quote * 4) == quote * 4
    assert cobol_literal(cobol_literal(quote * 3)) == quote * 4
    assert cobol_literal('"A' + quote * 2 + 'B"') == '"A' + quote * 2 + 'B"'


def test_cobol_literal_leaves_non_literal_clauses_alone():
    for clause in ("0", "-5", "SPACES", "ZERO", "HIGH-VALUES", "WS-OTHER-ITEM"):
        assert cobol_literal(clause) == clause


def test_cobol_literal_handles_the_all_repetition_prefix():
    quote = chr(34)
    assert cobol_literal("ALL " + quote * 3) == "ALL " + quote * 4
    assert cobol_literal('ALL "="') == 'ALL "="'
