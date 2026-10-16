"""Issue #243: a typo in a one-line MOVE inside a MOCK body is refused by
lint at its .cut line instead of surfacing as a cobc error at a line of
the deleted sandbox copy."""

from mockymock.analysis.cut_names import check_cut_data_names
from mockymock.dsl.parser import parse_cut

PROGRAM_LINES = [
    "       01  WS-RC       PIC XX.",
    "       01  WS-CNT      PIC 9.",
    "       01  WS-TAB.",
    "           05  WS-ROW  PIC X OCCURS 3.",
]


def _messages(body):
    suite = parse_cut(
        'TESTSUITE "ty"\nTESTCASE "typo in mock body"\n'
        '    MOCK CALL "SUBPGM"\n'
        + body
        + "    END-MOCK\n    PERFORM CALC-PARA\n    EXPECT WS-CNT TO BE 1\n"
    )
    return [r.message for r in check_cut_data_names(suite, PROGRAM_LINES)]


def test_typo_in_mock_body_move_target_is_refused_at_its_line():
    assert _messages('        MOVE "00" TO WS-RCX\n') == [
        '.cut line 4: MOCK CALL "SUBPGM" body MOVE target WS-RCX is not a ' "data item"
    ]


def test_every_target_and_a_bare_value_are_checked():
    messages = _messages("        MOVE WS-RCZ TO WS-RC WS-CNTX  *> note\n")
    assert messages == [
        '.cut line 4: MOCK CALL "SUBPGM" body MOVE target WS-CNTX is not a '
        "data item",
        '.cut line 4: MOCK CALL "SUBPGM" body MOVE value WS-RCZ is neither a '
        "literal nor a data item -- quote it if it is text",
    ]


def test_valid_and_unchecked_body_lines_pass():
    body = (
        '        MOVE "00" TO WS-RC\n'
        "        MOVE 1 TO WS-ROW (2) WS-CNT\n"
        "        MOVE ZERO TO RETURN-CODE\n"
        "        MOVE LENGTH OF WS-TAB TO WS-CNT\n"
        "        IF WS-CNT = 1 MOVE 2 TO WS-NOPE END-IF\n"
        "        MOVE WS-RC\n"
        "             TO WS-RC\n"
    )
    assert _messages(body) == []
