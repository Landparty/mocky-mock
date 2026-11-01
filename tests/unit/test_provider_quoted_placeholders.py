"""A PROVIDER placeholder inside a quoted literal gets the row value's
content, not its quotes (issue #376)."""

from __future__ import annotations

from mockymock.dsl.parser import parse_cut

CUT = '''\
TESTSUITE "s"
PROVIDER P
    HEADER State, Name
    ROW "NY", "O'Hare, IL"
    ROW TX, Arizona
    ROW 'CA', "Say ""hi"""
TESTCASE "t" USING PROVIDER P
    MOVE "{State}" TO WS-A
    MOVE {State} TO WS-B
    MOVE 'x{Name}' TO WS-C
    PERFORM X
    EXPECT WS-MSG TO BE "State: {Name}"
'''


def _rows():
    suite = parse_cut(CUT)
    return [
        (
            [value for value, _ in case.setup_moves],
            [e.expected_value for e in case.expectations],
        )
        for case in suite.test_cases
    ]


def test_quoted_placeholder_takes_the_value_content() -> None:
    assert _rows() == [
        (['"NY"', '"NY"', "'xO''Hare, IL'"], ['"State: O\'Hare, IL"']),
        (['"TX"', "TX", "'xArizona'"], ['"State: Arizona"']),
        (['"CA"', "'CA'", "'xSay \"hi\"'"], ['"State: Say ""hi"""']),
    ]
