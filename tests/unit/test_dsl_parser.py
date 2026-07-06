import pytest

from mockymock.dsl.parser import CutParseError, parse_cut

ORDRPROC_CUT = """\
TESTSUITE "ORDRPROC discount calculation"

TESTCASE "10% discount reduces net amount correctly"
    MOCK CALL "DISCRATE"
        MOVE 0.10 TO WS-DISCOUNT-PCT
    END-MOCK
    MOVE 100.00 TO ORD-AMOUNT
    PERFORM PROCESS-ORDER
    EXPECT WS-NET-AMOUNT TO BE 90.00
    VERIFY "DISCRATE" WAS CALLED ONCE

TESTCASE "Zero discount leaves amount unchanged"
    MOCK CALL "DISCRATE"
        MOVE 0.00 TO WS-DISCOUNT-PCT
    END-MOCK
    MOVE 50.00 TO ORD-AMOUNT
    PERFORM PROCESS-ORDER
    EXPECT WS-NET-AMOUNT TO BE 50.00
"""


def test_parses_suite_name():
    suite = parse_cut(ORDRPROC_CUT)
    assert suite.name == "ORDRPROC discount calculation"


def test_parses_two_test_cases():
    suite = parse_cut(ORDRPROC_CUT)
    assert len(suite.test_cases) == 2
    assert suite.test_cases[0].name == "10% discount reduces net amount correctly"
    assert suite.test_cases[1].name == "Zero discount leaves amount unchanged"


def test_parses_mock_call_body():
    suite = parse_cut(ORDRPROC_CUT)
    case_one = suite.test_cases[0]
    assert len(case_one.mocks) == 1
    assert case_one.mocks[0].program_name == "DISCRATE"
    assert case_one.mocks[0].body_lines == ["MOVE 0.10 TO WS-DISCOUNT-PCT"]


def test_parses_setup_moves_and_perform_target():
    suite = parse_cut(ORDRPROC_CUT)
    case_one = suite.test_cases[0]
    assert case_one.setup_moves == [("100.00", "ORD-AMOUNT")]
    assert case_one.perform_target == "PROCESS-ORDER"


def test_parses_expect_and_verify():
    suite = parse_cut(ORDRPROC_CUT)
    case_one = suite.test_cases[0]
    assert case_one.expectations[0].data_name == "WS-NET-AMOUNT"
    assert case_one.expectations[0].expected_value == "90.00"
    assert case_one.verifications[0].program_name == "DISCRATE"
    assert case_one.verifications[0].expectation == "ONCE"


def test_second_case_has_no_verify():
    suite = parse_cut(ORDRPROC_CUT)
    assert suite.test_cases[1].verifications == []


def test_testcase_before_testsuite_raises():
    with pytest.raises(CutParseError):
        parse_cut('TESTCASE "orphan"\nPERFORM X\n')


def test_unrecognized_line_raises():
    with pytest.raises(CutParseError):
        parse_cut('TESTSUITE "X"\n\nTESTCASE "Y"\nNOT-A-REAL-DIRECTIVE\n')


def test_unterminated_mock_body_raises():
    text = (
        'TESTSUITE "s"\n'
        'TESTCASE "c"\n'
        '    MOCK CALL "X"\n'
        '        MOVE 0 TO RETURN-CODE\n'
        '    PERFORM MAIN\n'  # no END-MOCK: silently swallowed today
    )
    with pytest.raises(CutParseError, match="unterminated MOCK"):
        parse_cut(text)
