"""Issue #329: `TESTCASE "x" USING PROVIDER P TAGS "t"` matched no
TESTCASE grammar, so under an open PROVIDER it was reported as a
statement "not allowed inside PROVIDER ... closed by the next TESTCASE".
TAGS is now accepted on either side of USING PROVIDER."""

import pytest

from mockymock.dsl.parser import CutParseError, parse_cut

HEAD = """\
TESTSUITE "p1"

PROVIDER P
    HEADER A, R
    ROW 1, 2
    ROW 5, 10

"""

BODY = """\
    MOVE {A} TO WS-A
    PERFORM 0000-MAIN
    EXPECT WS-B TO BE {R}
"""


@pytest.mark.parametrize(
    "header",
    [
        'TESTCASE "double" USING PROVIDER P TAGS "x" "y"',
        'TESTCASE "double" TAGS "x" "y" USING PROVIDER P',
    ],
    ids=["after", "before"],
)
def test_tags_on_either_side_of_using_provider(header):
    suite = parse_cut(HEAD + header + "\n" + BODY)
    assert len(suite.test_cases) == 2
    for case in suite.test_cases:
        assert case.tags == ["x", "y"]
        assert case.template_name == "double"
    assert suite.test_cases[1].expectations[0].expected_value == "10"


def test_two_tags_lists_are_rejected():
    header = 'TESTCASE "double" TAGS "x" USING PROVIDER P TAGS "y"'
    with pytest.raises(CutParseError, match="two TAGS lists"):
        parse_cut(HEAD + header + "\n" + BODY)
