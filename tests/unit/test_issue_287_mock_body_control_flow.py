"""Issue #287: a MOCK body that leaves the body -- PERFORM <paragraph>,
GO TO, GOBACK, STOP RUN, EXIT PROGRAM -- is refused at its .cut line: its
target's boundaries are never gated, and a terminator ends the whole test
binary."""

import pytest

from mockymock.dsl.parser import CutParseError, parse_cut


def _parse(body):
    return parse_cut(
        'TESTSUITE "s"\nTESTCASE "flow from a mock body"\n'
        '    MOCK CALL "VALIDATE"\n'
        "        MOVE 0 TO WS-RC\n" + body + "    END-MOCK\n"
        "    PERFORM 1000-PROCESS\n"
    )


@pytest.mark.parametrize(
    "body,word",
    [
        ("        PERFORM 9000-REJECT\n", "PERFORM 9000-REJECT"),
        ("        PERFORM 9000-REJECT THRU 9000-EXIT\n", "PERFORM 9000-REJECT"),
        ("        PERFORM 9000-REJECT 3 TIMES\n", "PERFORM 9000-REJECT"),
        ("        GO TO 9000-REJECT\n", "GO TO"),
        ("        GOBACK\n", "GOBACK"),
        ("        IF WS-RC > 0 STOP RUN END-IF\n", "STOP RUN"),
        ("        EXIT PROGRAM\n", "EXIT PROGRAM"),
    ],
)
def test_leaving_the_body_is_refused_at_its_line(body, word):
    with pytest.raises(CutParseError, match=f"line 5: {word}"):
        _parse(body)


@pytest.mark.parametrize(
    "body",
    [
        "        PERFORM VARYING WS-I FROM 1 BY 1 UNTIL WS-I > 3\n"
        "            ADD 1 TO WS-RC\n        END-PERFORM\n",
        "        PERFORM 3 TIMES\n            ADD 1 TO WS-RC\n        END-PERFORM\n",
        "        PERFORM WS-N TIMES\n            ADD 1 TO WS-RC\n        END-PERFORM\n",
        "        PERFORM UNTIL WS-RC > 3\n            ADD 1 TO WS-RC\n"
        "        END-PERFORM\n",
        '        MOVE "GOBACK OR PERFORM X" TO WS-MSG\n',
        "        MOVE 1 TO WS-GOBACK-FLAG  *> no STOP RUN here\n",
    ],
)
def test_inline_performs_and_literals_are_fine(body):
    _parse(body)


def test_an_unterminated_mock_still_reports_the_missing_end_mock():
    with pytest.raises(CutParseError, match="unterminated MOCK"):
        parse_cut(
            'TESTSUITE "s"\nTESTCASE "c"\n    MOCK CALL "X"\n'
            "        MOVE 0 TO RETURN-CODE\n    PERFORM MAIN\n"
        )
