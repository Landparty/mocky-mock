"""TESTCASE TAGS parsing and .cut line-number recording on the DSL model."""

import pytest

from mockymock.dsl.parser import CutParseError, parse_cut

TAGGED_CUT = """\
TESTSUITE "TAGDEMO suite"

TESTCASE "untagged case"
    PERFORM MAIN-PARA
    EXPECT WS-A TO BE 1

TESTCASE "tagged case" TAGS "slow" "io"
    PERFORM MAIN-PARA
    EXPECT WS-B TO BE 2
    VERIFY "SUBPROG" WAS CALLED ONCE
"""


def test_untagged_case_has_empty_tags():
    suite = parse_cut(TAGGED_CUT)
    assert suite.test_cases[0].tags == []


def test_tags_parse_in_declaration_order():
    suite = parse_cut(TAGGED_CUT)
    assert suite.test_cases[1].tags == ["slow", "io"]


def test_single_tag_parses():
    suite = parse_cut('TESTSUITE "s"\nTESTCASE "c" TAGS "fast"\nPERFORM P\n')
    assert suite.test_cases[0].tags == ["fast"]


def test_empty_tag_is_rejected():
    with pytest.raises(CutParseError, match="empty tag"):
        parse_cut('TESTSUITE "s"\nTESTCASE "c" TAGS ""\n')


def test_unquoted_tag_is_rejected_as_unrecognized():
    with pytest.raises(CutParseError, match="unrecognized statement"):
        parse_cut('TESTSUITE "s"\nTESTCASE "c" TAGS slow\n')


def test_suite_and_case_lines_are_recorded():
    suite = parse_cut(TAGGED_CUT)
    assert suite.line == 1
    assert suite.test_cases[0].line == 3
    assert suite.test_cases[1].line == 7


def test_expect_and_verify_lines_are_recorded():
    suite = parse_cut(TAGGED_CUT)
    assert suite.test_cases[0].expectations[0].line == 5
    assert suite.test_cases[1].expectations[0].line == 9
    assert suite.test_cases[1].verifications[0].line == 10


def test_hand_built_directives_default_to_line_zero():
    """Back-compat: tests and callers that assemble the model by hand keep
    working without passing line numbers."""
    from mockymock.dsl.model import ExpectDirective, MockTestCase, MockTestSuite

    case = MockTestCase(name="c", expectations=[ExpectDirective("WS-A", "1")])
    suite = MockTestSuite(name="s", test_cases=[case])
    assert suite.line == 0
    assert case.line == 0
    assert case.tags == []
    assert case.expectations[0].line == 0
