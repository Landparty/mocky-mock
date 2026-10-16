"""Issue #270: an unterminated quoted literal in a .cut value is refused at
its line instead of being spliced into the driver."""

import pytest

from mockymock.dsl.parser import CutParseError, parse_cut

HEAD = 'TESTSUITE "s"\nTESTCASE "one"\n'


@pytest.mark.parametrize(
    "body, line",
    [
        ('    MOVE "ABCDE TO WS-NAME\n    PERFORM P\n', 3),
        ("    PERFORM P\n    EXPECT WS-X TO BE 'ABC\n", 4),
        (
            '    MOCK READ F ROWS\n        ( F-A = "X )\n    END-MOCK\n    PERFORM P\n',
            4,
        ),
        (
            '    MOCK READ F ROWS\n        ( F-A = "X" )\n'
            '        TERMINAL ( WS-EOF = "Y )\n    END-MOCK\n    PERFORM P\n',
            5,
        ),
    ],
)
def test_unterminated_literal_is_refused_at_its_line(body: str, line: int) -> None:
    with pytest.raises(CutParseError, match=rf"line {line}: .*unterminated"):
        parse_cut(HEAD + body)


def test_unterminated_provider_row_value_is_refused() -> None:
    with pytest.raises(CutParseError, match=r"line 4: ROW A value .*unterminated"):
        parse_cut(
            'TESTSUITE "s"\nPROVIDER P\nHEADER A\nROW "abc\n'
            'TESTCASE "c" USING PROVIDER P\n    MOVE {A} TO WS-A\n    PERFORM P\n'
        )


def test_doubled_quotes_and_closed_literals_still_parse() -> None:
    suite = parse_cut(
        HEAD + '    MOVE "A""B" TO WS-A\n    PERFORM P\n    EXPECT WS-A TO BE \'X\'\n'
    )
    assert suite.test_cases[0].setup_moves == [('"A""B"', "WS-A")]
