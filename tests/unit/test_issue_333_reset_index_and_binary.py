"""Issue #333: the between-case reset skipped USAGE INDEX data items and
PICTURE-less numeric usages (BINARY-LONG, FLOAT-LONG, ...), so their
values leaked from one case into the next. INDEX items now get #189's
save/restore SET reset, the binary/float usages a MOVE 0 (or their VALUE),
and anything still skipped is reported."""

from cobolparser import parse_cobol

from mockymock.splicer.reset import (
    index_names,
    index_reset_lines,
    reset_move_lines,
    unreset_items,
)

PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. IDX.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-SAVE-IX          USAGE INDEX.
       01  WS-TAB.
           05  WS-ENT          PIC X OCCURS 9 INDEXED BY TX.
           05  WS-TAB-IX       USAGE INDEX OCCURS 2.
       01  WS-BL               USAGE BINARY-LONG.
       01  WS-BC               USAGE BINARY-CHAR VALUE 3.
       01  WS-FL               USAGE FLOAT-LONG.
       01  WS-GRP.
           05  WS-IN-IX        USAGE INDEX.
       PROCEDURE DIVISION.
       MAIN-PARA.
           GOBACK.
"""


def _ast():
    result = parse_cobol(PROGRAM, filename="IDX.cbl")
    assert result.success, result.errors
    return result.ast


def test_usage_index_items_join_the_index_save_restore():
    names = index_names(_ast())
    assert names == ["TX", "WS-SAVE-IX", "WS-IN-IX"]
    lines = index_reset_lines(names)
    assert "SET UT-IDX-SAVE-002 TO WS-SAVE-IX" in [line.strip() for line in lines]
    assert "SET WS-SAVE-IX TO UT-IDX-SAVE-002" in lines


def test_picless_binary_and_float_usages_are_reset():
    lines = reset_move_lines(_ast())
    assert "MOVE 0 TO WS-BL" in lines
    assert "MOVE 3 TO WS-BC" in lines
    assert "MOVE 0 TO WS-FL" in lines


def test_an_index_item_inside_a_table_is_reported_not_skipped_silently():
    assert unreset_items(_ast()) == ["WS-TAB-IX"]
