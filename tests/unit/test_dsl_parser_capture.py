"""CAPTURE ARG <n> INTO <target>: grammar, category restriction, index
validation, and duplicate-in-body rejection -- mirrors
test_dsl_parser_file_status.py's structure for the sibling FILE-STATUS IS
sugar."""

import pytest

from mockymock.dsl.parser import CutParseError, parse_cut


def _mock(cut: str):
    return parse_cut(cut).test_cases[0].mocks[0]


def test_capture_parses_index_and_target():
    cut = """\
TESTSUITE "s"
TESTCASE "c"
    MOCK CALL "DISCRATE"
        CAPTURE ARG 1 INTO WS-CAPTURED-RATE
    END-MOCK
    PERFORM MAIN-PROCESS
"""
    assert _mock(cut).captures == [(1, "WS-CAPTURED-RATE")]


def test_capture_works_on_bare_dyncall_key():
    cut = """\
TESTSUITE "s"
TESTCASE "c"
    MOCK CALL WS-PGM-NAME
        CAPTURE ARG 2 INTO WS-CAPTURED-ARG2
    END-MOCK
    PERFORM MAIN-PROCESS
"""
    assert _mock(cut).captures == [(2, "WS-CAPTURED-ARG2")]


def test_capture_target_may_be_subscripted():
    cut = """\
TESTSUITE "s"
TESTCASE "c"
    MOCK CALL "DISCRATE"
        CAPTURE ARG 1 INTO WS-TABLE(1, 1)
    END-MOCK
    PERFORM MAIN-PROCESS
"""
    assert _mock(cut).captures == [(1, "WS-TABLE(1, 1)")]


def test_multiple_captures_in_one_body_are_kept_in_declared_order():
    cut = """\
TESTSUITE "s"
TESTCASE "c"
    MOCK CALL "DISCRATE"
        CAPTURE ARG 2 INTO WS-SECOND
        CAPTURE ARG 1 INTO WS-FIRST
    END-MOCK
    PERFORM MAIN-PROCESS
"""
    assert _mock(cut).captures == [(2, "WS-SECOND"), (1, "WS-FIRST")]


def test_capture_index_zero_is_a_parse_error():
    cut = """\
TESTSUITE "s"
TESTCASE "c"
    MOCK CALL "DISCRATE"
        CAPTURE ARG 0 INTO WS-CAPTURED-RATE
    END-MOCK
    PERFORM MAIN-PROCESS
"""
    with pytest.raises(CutParseError, match="positive integer"):
        parse_cut(cut)


def test_capture_non_numeric_index_is_a_parse_error():
    cut = """\
TESTSUITE "s"
TESTCASE "c"
    MOCK CALL "DISCRATE"
        CAPTURE ARG FIRST INTO WS-CAPTURED-RATE
    END-MOCK
    PERFORM MAIN-PROCESS
"""
    with pytest.raises(CutParseError, match="positive integer"):
        parse_cut(cut)


def test_capture_overly_large_numeric_index_is_a_parse_error():
    index = "1" * 5000
    cut = f"""\
TESTSUITE "s"
TESTCASE "c"
    MOCK CALL "DISCRATE"
        CAPTURE ARG {index} INTO WS-CAPTURED-RATE
    END-MOCK
    PERFORM MAIN-PROCESS
"""
    with pytest.raises(CutParseError, match="positive integer"):
        parse_cut(cut)


def test_capture_outside_call_category_is_a_parse_error():
    cut = """\
TESTSUITE "s"
TESTCASE "c"
    MOCK OPEN INV-FILE
        CAPTURE ARG 1 INTO WS-CAPTURED
    END-MOCK
    PERFORM MAIN-PROCESS
"""
    with pytest.raises(CutParseError, match="CAPTURE ARG is only valid"):
        parse_cut(cut)


def test_duplicate_capture_arg_in_one_body_is_a_parse_error():
    cut = """\
TESTSUITE "s"
TESTCASE "c"
    MOCK CALL "DISCRATE"
        CAPTURE ARG 1 INTO WS-FIRST
        CAPTURE ARG 1 INTO WS-FIRST-AGAIN
    END-MOCK
    PERFORM MAIN-PROCESS
"""
    with pytest.raises(CutParseError, match="duplicate CAPTURE ARG 1"):
        parse_cut(cut)


def test_directive_with_no_capture_lines_has_empty_captures_list():
    cut = """\
TESTSUITE "s"
TESTCASE "c"
    MOCK CALL "DISCRATE"
        MOVE 0 TO RETURN-CODE
    END-MOCK
    PERFORM MAIN-PROCESS
"""
    assert _mock(cut).captures == []


def test_capture_missing_into_is_a_parse_error():
    cut = """\
TESTSUITE "s"
TESTCASE "c"
    MOCK CALL "DISCRATE"
        CAPTURE ARG 1 WS-CAPTURED-RATE
    END-MOCK
    PERFORM MAIN-PROCESS
"""
    with pytest.raises(CutParseError, match="malformed CAPTURE statement"):
        parse_cut(cut)


def test_capture_with_from_instead_of_into_is_a_parse_error():
    cut = """\
TESTSUITE "s"
TESTCASE "c"
    MOCK CALL "DISCRATE"
        CAPTURE ARG 1 FROM WS-CAPTURED-RATE
    END-MOCK
    PERFORM MAIN-PROCESS
"""
    with pytest.raises(CutParseError, match="malformed CAPTURE statement"):
        parse_cut(cut)


def test_capture_with_negative_index_is_a_parse_error():
    cut = """\
TESTSUITE "s"
TESTCASE "c"
    MOCK CALL "DISCRATE"
        CAPTURE ARG -1 INTO WS-CAPTURED-RATE
    END-MOCK
    PERFORM MAIN-PROCESS
"""
    with pytest.raises(CutParseError, match="positive integer"):
        parse_cut(cut)


def test_capture_works_on_mock_mq_key():
    cut = """\
TESTSUITE "s"
TESTCASE "c"
    MOCK MQ "SOMESERVICE"
        CAPTURE ARG 1 INTO WS-CAPTURED-ARG1
    END-MOCK
    PERFORM MAIN-PROCESS
"""
    assert _mock(cut).captures == [(1, "WS-CAPTURED-ARG1")]
