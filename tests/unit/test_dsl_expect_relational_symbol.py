"""`EXPECT X TO BE > 0 AND < 10` read `> 0 AND < 10` as the value of a
plain `TO BE`: lint passed and the generated `IF NOT (X = > 0 AND < 10)`
failed to compile. A value that starts with a relational symbol is now
refused at its .cut line, as a dangling comparison word already was;
the symbols stay legal in the abbreviated tail."""

import pytest

from mockymock.dsl.parser import CutParseError, parse_cut


def _cut(expect_line: str) -> str:
    return f'TESTSUITE "ops"\nTESTCASE "case"\n    PERFORM MAIN\n    {expect_line}\n'


@pytest.mark.parametrize(
    "line",
    [
        "EXPECT WS-X TO BE > 0 AND < 10",
        "EXPECT WS-X TO BE >5",
        "EXPECT WS-X NOT TO BE < 5",
        "EXPECT WS-X TO BE >= 5",
        "EXPECT WS-X TO BE = 5",
        "EXPECT WS-X TO BE GREATER THAN > 5",
    ],
)
def test_a_leading_relational_symbol_fails_closed(line):
    with pytest.raises(CutParseError, match="malformed EXPECT comparison"):
        parse_cut(_cut(line))


@pytest.mark.parametrize(
    ("line", "operator", "value"),
    [
        ("EXPECT WS-X TO BE GREATER THAN 0 AND < 10", ">", "0 AND < 10"),
        ('EXPECT WS-X TO BE ">"', "=", '">"'),
        ("EXPECT WS-X TO BE 7 OR 8", "=", "7 OR 8"),
    ],
)
def test_symbols_in_the_tail_or_quoted_still_parse(line, operator, value):
    (expectation,) = parse_cut(_cut(line)).test_cases[0].expectations
    assert (expectation.operator, expectation.expected_value) == (operator, value)


def test_a_provider_row_substituting_a_leading_symbol_is_refused_at_its_row():
    text = (
        'TESTSUITE "s"\n'
        "PROVIDER Ranges\n"
        "    HEADER Bound\n"
        "    ROW 5\n"
        "    ROW > 5\n"
        'TESTCASE "range" USING PROVIDER Ranges\n'
        "    PERFORM MAIN\n"
        "    EXPECT WS-X TO BE {Bound}\n"
    )
    with pytest.raises(CutParseError, match=r"line 5: malformed EXPECT comparison"):
        parse_cut(text)
