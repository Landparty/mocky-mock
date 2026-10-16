"""Issue #236: a trailing `*>` comment on any parsed .cut line is stripped
(outside quotes) and never reaches the driver; MOCK body lines keep theirs."""

from mockymock.dsl.parser import parse_cut

CUT = """\
TESTSUITE "s"   *> the suite
PROVIDER P
HEADER A, B
ROW -5, 3    *> swapped
TESTCASE "c" USING PROVIDER P   *> note
    MOVE {B} TO WS-N   *> set it
    MOCK READ F ROWS   *> rows
        ( F-A = 1 )    *> first
        TERMINAL ( WS-EOF = "Y" )   *> end
    END-MOCK   *> done
    MOCK CALL "X"
        MOVE 1 TO WS-A *> kept: COBOL
        CAPTURE ARG 1 INTO WS-C   *> cap
    END-MOCK
    PERFORM P1   *> run
    EXPECT F-ON(2) TO BE TRUE  *> note
    EXPECT WS-S TO BE "a *> b"   *> real comment
"""


def test_trailing_comments_are_stripped_from_parsed_lines() -> None:
    (case,) = parse_cut(CUT).test_cases
    assert case.setup_moves == [("3", "WS-N")]
    assert [(e.data_name, e.expected_value) for e in case.expectations] == [
        ("F-ON(2)", "TRUE"),
        ("WS-S", '"a *> b"'),
    ]
    read, call = case.mocks
    assert read.rows == [[("F-A", "1")]]
    assert read.terminal_row == [("WS-EOF", '"Y"')]
    assert call.captures == [(1, "WS-C")]
    assert call.body_lines == ["MOVE 1 TO WS-A *> kept: COBOL"]
    assert case.perform_target == "P1"
