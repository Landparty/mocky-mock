"""Issue #335: the JSON run report `.strip()`ped a failure's `actual`, so
a failure whose whole difference is leading spaces (a JUSTIFIED RIGHT
field, a right-aligned edited value) read as expected "ABC" vs actual ABC.
Only the separator is removed now; leading spaces belong to the value."""

from mockymock.dsl.parser import parse_cut
from mockymock.report.json_report import _attribute_failure

CUT = """\
TESTSUITE "s"
TESTCASE "a"
    PERFORM MAIN-PARA
    EXPECT WS-NAME TO BE "ABC"
"""


def test_actual_keeps_leading_spaces():
    case = parse_cut(CUT).test_cases[0]
    failure = _attribute_failure('expected WS-NAME = "ABC", got    ABC', case)
    assert failure.expected == '"ABC"'
    assert failure.actual == "   ABC"


def test_actual_keeps_leading_spaces_without_a_matching_expectation():
    failure = _attribute_failure("expected WS-OTHER = 1, got   12.50-  ", None)
    assert failure.actual == "  12.50-"
