"""BEFORE-EACH / BEFORE-ALL mock scoping: grammar, position/uniqueness
rules, and desugar precedence into each TESTCASE's own mocks list."""

import pytest

from mockymock.dsl.model import MockCategory
from mockymock.dsl.parser import CutParseError, parse_cut

BASIC_CUT = """\
TESTSUITE "shared mocks"

BEFORE-ALL
    MOCK OPEN FILE1
    END-MOCK
END-BEFORE

BEFORE-EACH
    MOCK READ FILE2
        MOVE "default" TO WS-FIELD
    END-MOCK
END-BEFORE

TESTCASE "uses only shared mocks"
    PERFORM MAIN-PROCESS
    EXPECT WS-FIELD TO BE "default"

TESTCASE "overrides the shared READ mock"
    MOCK READ FILE2
        MOVE "override" TO WS-FIELD
    END-MOCK
    PERFORM MAIN-PROCESS
    EXPECT WS-FIELD TO BE "override"
"""


def test_before_all_and_before_each_mocks_appear_in_every_case():
    suite = parse_cut(BASIC_CUT)
    for case in suite.test_cases:
        keys = {(m.category, m.key) for m in case.mocks}
        assert (MockCategory.OPEN, "FILE1") in keys
        assert (MockCategory.READ, "FILE2") in keys


def test_testcase_mock_overrides_before_each_mock():
    suite = parse_cut(BASIC_CUT)
    first, second = suite.test_cases
    first_read = next(m for m in first.mocks if m.key == "FILE2")
    second_read = next(m for m in second.mocks if m.key == "FILE2")
    assert first_read.body_lines == ['MOVE "default" TO WS-FIELD']
    assert second_read.body_lines == ['MOVE "override" TO WS-FIELD']


def test_before_each_overrides_before_all_on_key_collision():
    cut = """\
TESTSUITE "precedence"

BEFORE-ALL
    MOCK OPEN FILE1
        MOVE "from-all" TO WS-FIELD
    END-MOCK
END-BEFORE

BEFORE-EACH
    MOCK OPEN FILE1
        MOVE "from-each" TO WS-FIELD
    END-MOCK
END-BEFORE

TESTCASE "one"
    PERFORM MAIN-PROCESS
"""
    suite = parse_cut(cut)
    mock = next(m for m in suite.test_cases[0].mocks if m.key == "FILE1")
    assert mock.body_lines == ['MOVE "from-each" TO WS-FIELD']


def test_duplicate_mock_within_before_each_is_a_parse_error():
    cut = """\
TESTSUITE "dup"

BEFORE-EACH
    MOCK OPEN FILE1
    END-MOCK
    MOCK OPEN FILE1
    END-MOCK
END-BEFORE

TESTCASE "one"
    PERFORM MAIN-PROCESS
"""
    with pytest.raises(CutParseError, match="duplicate MOCK"):
        parse_cut(cut)


def test_before_each_after_testcase_is_a_parse_error():
    cut = """\
TESTSUITE "late"

TESTCASE "one"
    PERFORM MAIN-PROCESS

BEFORE-EACH
    MOCK OPEN FILE1
    END-MOCK
END-BEFORE
"""
    with pytest.raises(CutParseError, match="before the first TESTCASE"):
        parse_cut(cut)


def test_second_before_each_is_a_parse_error():
    cut = """\
TESTSUITE "dup-block"

BEFORE-EACH
    MOCK OPEN FILE1
    END-MOCK
END-BEFORE

BEFORE-EACH
    MOCK OPEN FILE2
    END-MOCK
END-BEFORE

TESTCASE "one"
    PERFORM MAIN-PROCESS
"""
    with pytest.raises(CutParseError, match="second BEFORE-EACH"):
        parse_cut(cut)


def test_testcase_while_before_each_still_open_is_a_parse_error():
    cut = """\
TESTSUITE "unterminated-before"

BEFORE-EACH
    MOCK OPEN FILE1
    END-MOCK

TESTCASE "one"
    PERFORM MAIN-PROCESS
"""
    with pytest.raises(CutParseError, match="missing END-BEFORE"):
        parse_cut(cut)


def test_before_each_while_before_all_still_open_is_a_parse_error():
    cut = """\
TESTSUITE "nested-before"

BEFORE-ALL
    MOCK OPEN FILE1
    END-MOCK
BEFORE-EACH
    MOCK OPEN FILE2
    END-MOCK
END-BEFORE

TESTCASE "one"
    PERFORM MAIN-PROCESS
"""
    with pytest.raises(CutParseError, match="missing END-BEFORE"):
        parse_cut(cut)


def test_before_all_while_before_each_still_open_is_a_parse_error():
    cut = """\
TESTSUITE "nested-before-reverse"

BEFORE-EACH
    MOCK OPEN FILE1
    END-MOCK
BEFORE-ALL
    MOCK OPEN FILE2
    END-MOCK
END-BEFORE

TESTCASE "one"
    PERFORM MAIN-PROCESS
"""
    with pytest.raises(CutParseError, match="missing END-BEFORE"):
        parse_cut(cut)


def test_move_inside_before_each_is_rejected():
    cut = """\
TESTSUITE "no-move"

BEFORE-EACH
    MOVE 1 TO WS-FIELD
END-BEFORE

TESTCASE "one"
    PERFORM MAIN-PROCESS
"""
    with pytest.raises(CutParseError, match="not allowed inside BEFORE-EACH"):
        parse_cut(cut)


def test_unterminated_before_each_at_eof_is_a_parse_error():
    cut = """\
TESTSUITE "no-end"

BEFORE-EACH
    MOCK OPEN FILE1
    END-MOCK
"""
    with pytest.raises(CutParseError, match="unterminated BEFORE-EACH"):
        parse_cut(cut)


def test_verify_against_a_before_each_mock_is_allowed():
    cut = """\
TESTSUITE "verify shared"

BEFORE-EACH
    MOCK CLOSE FILE1
    END-MOCK
END-BEFORE

TESTCASE "one"
    PERFORM MAIN-PROCESS
    VERIFY CLOSE FILE1 WAS PERFORMED ONCE
"""
    suite = parse_cut(cut)
    verification = suite.test_cases[0].verifications[0]
    assert verification.category is MockCategory.CLOSE
    assert verification.key == "FILE1"


def test_file_with_no_before_blocks_parses_exactly_as_before():
    cut = """\
TESTSUITE "plain"

TESTCASE "one"
    MOCK OPEN FILE1
    END-MOCK
    PERFORM MAIN-PROCESS
"""
    suite = parse_cut(cut)
    assert [m.key for m in suite.test_cases[0].mocks] == ["FILE1"]
