"""v2 grammar: MOCK for file ops / SQL / CICS / DLI / ACCEPT / MQ, comment
lines, and the generalized VERIFY key syntax."""

import pytest

from mockymock.dsl.model import MockCategory
from mockymock.dsl.parser import CutParseError, parse_cut

ALL_BOUNDARIES_CUT = """\
TESTSUITE "ORDRPROC all boundaries"

*> scaffold hint: INFILE is read in a loop until WS-EOF is set
TESTCASE "reads two records then EOF"
    MOCK OPEN INFILE
    END-MOCK
    MOCK READ INFILE
        IF UT-READ-INFILE-TALLY > 2
            MOVE "Y" TO WS-EOF
        END-IF
    END-MOCK
    MOCK WRITE OUT-REC
    END-MOCK
    MOCK CLOSE INFILE
    END-MOCK
    MOCK SQL "UPDATE ORDERS"
        MOVE 0 TO SQLCODE
    END-MOCK
    MOCK CICS "READ FILE"
        MOVE 0 TO EIBRESP
    END-MOCK
    MOCK DLI "GU"
    END-MOCK
    MOCK MQ "MQPUT"
        MOVE 0 TO MQ-COMPCODE
    END-MOCK
    MOCK ACCEPT WS-USER-CHOICE
        MOVE "1" TO WS-USER-CHOICE
    END-MOCK
    PERFORM MAIN-PARA
    EXPECT WS-TOTAL TO BE 2
    VERIFY READ INFILE WAS PERFORMED 3 TIMES
    VERIFY SQL "UPDATE ORDERS" WAS PERFORMED ONCE
    VERIFY MQ "MQPUT" WAS CALLED AT LEAST ONCE
    VERIFY WRITE OUT-REC WAS PERFORMED 2 TIMES
    VERIFY "LEGACY" WAS CALLED NEVER
"""


def _case():
    return parse_cut(ALL_BOUNDARIES_CUT).test_cases[0]


def test_parses_all_mock_categories():
    mocks = _case().mocks
    got = {(m.category, m.key) for m in mocks}
    assert (MockCategory.OPEN, "INFILE") in got
    assert (MockCategory.READ, "INFILE") in got
    assert (MockCategory.WRITE, "OUT-REC") in got
    assert (MockCategory.CLOSE, "INFILE") in got
    assert (MockCategory.SQL, "UPDATE ORDERS") in got
    assert (MockCategory.CICS, "READ FILE") in got
    assert (MockCategory.DLI, "GU") in got
    assert (MockCategory.ACCEPT, "WS-USER-CHOICE") in got


def test_mq_is_sugar_for_call():
    mocks = _case().mocks
    mq = [m for m in mocks if m.key == "MQPUT"]
    assert len(mq) == 1
    assert mq[0].category is MockCategory.CALL


def test_multiline_mock_body_preserved():
    read_mock = next(m for m in _case().mocks if m.category is MockCategory.READ)
    assert read_mock.body_lines == [
        "IF UT-READ-INFILE-TALLY > 2",
        'MOVE "Y" TO WS-EOF',
        "END-IF",
    ]


def test_empty_mock_body_allowed():
    open_mock = next(m for m in _case().mocks if m.category is MockCategory.OPEN)
    assert open_mock.body_lines == []


def test_comment_lines_are_skipped():
    suite = parse_cut(ALL_BOUNDARIES_CUT)
    assert len(suite.test_cases) == 1


def test_verify_generalized_keys():
    verifications = _case().verifications
    got = {(v.category, v.key, v.expectation) for v in verifications}
    assert (MockCategory.READ, "INFILE", "3 TIMES") in got
    assert (MockCategory.SQL, "UPDATE ORDERS", "ONCE") in got
    assert (MockCategory.CALL, "MQPUT", "AT LEAST ONCE") in got
    assert (MockCategory.WRITE, "OUT-REC", "2 TIMES") in got
    # bare quoted form stays CALL for v1 back-compat
    assert (MockCategory.CALL, "LEGACY", "NEVER") in got


def test_bare_file_keys_uppercased():
    cut = """\
TESTSUITE "x"
TESTCASE "y"
    MOCK READ infile
    END-MOCK
    PERFORM p
"""
    mock = parse_cut(cut).test_cases[0].mocks[0]
    assert mock.key == "INFILE"


def test_mock_call_still_parses():
    cut = """\
TESTSUITE "x"
TESTCASE "y"
    MOCK CALL "DISCRATE"
        MOVE 1 TO X
    END-MOCK
    PERFORM p
    VERIFY "DISCRATE" WAS CALLED ONCE
"""
    case = parse_cut(cut).test_cases[0]
    assert case.mocks[0].category is MockCategory.CALL
    assert case.mocks[0].key == "DISCRATE"
    assert case.verifications[0].category is MockCategory.CALL


def test_quoted_category_requires_quotes():
    with pytest.raises(CutParseError):
        parse_cut('TESTSUITE "x"\nTESTCASE "y"\n    MOCK SQL SELECT\n    END-MOCK\n    PERFORM p\n')


def test_file_category_rejects_quoted_key():
    with pytest.raises(CutParseError):
        parse_cut('TESTSUITE "x"\nTESTCASE "y"\n    MOCK READ "INFILE"\n    END-MOCK\n    PERFORM p\n')
