"""FILE-STATUS IS sugar: mnemonic table, quoted-literal escape hatch,
category restriction, and duplicate-in-body rejection."""

import pytest

from mockymock.dsl.parser import CutParseError, parse_cut


def _mock(cut: str):
    return parse_cut(cut).test_cases[0].mocks[0]


def test_mnemonic_resolves_to_the_documented_code():
    cut = """\
TESTSUITE "s"
TESTCASE "c"
    MOCK OPEN FILE1
        FILE-STATUS IS FILE-NOT-FOUND
    END-MOCK
    PERFORM MAIN-PROCESS
"""
    assert _mock(cut).file_status == "35"


@pytest.mark.parametrize(
    "mnemonic,code",
    [
        ("SUCCESS", "00"),
        ("END-OF-FILE", "10"),
        ("DUPLICATE-KEY", "22"),
        ("RECORD-NOT-FOUND", "23"),
        ("FILE-NOT-FOUND", "35"),
        ("ALREADY-OPEN", "41"),
        ("NOT-OPEN", "42"),
        ("NO-CURRENT-RECORD", "43"),
    ],
)
def test_every_documented_mnemonic_resolves(mnemonic, code):
    cut = f"""\
TESTSUITE "s"
TESTCASE "c"
    MOCK READ FILE1
        FILE-STATUS IS {mnemonic}
    END-MOCK
    PERFORM MAIN-PROCESS
"""
    assert _mock(cut).file_status == code


def test_quoted_literal_code_is_the_escape_hatch():
    cut = """\
TESTSUITE "s"
TESTCASE "c"
    MOCK READ FILE1
        FILE-STATUS IS "92"
    END-MOCK
    PERFORM MAIN-PROCESS
"""
    assert _mock(cut).file_status == "92"


def test_unrecognized_mnemonic_is_a_parse_error():
    cut = """\
TESTSUITE "s"
TESTCASE "c"
    MOCK READ FILE1
        FILE-STATUS IS NOT-A-REAL-MNEMONIC
    END-MOCK
    PERFORM MAIN-PROCESS
"""
    with pytest.raises(CutParseError, match="unrecognized FILE-STATUS mnemonic"):
        parse_cut(cut)


def test_literal_not_two_characters_is_a_parse_error():
    cut = """\
TESTSUITE "s"
TESTCASE "c"
    MOCK READ FILE1
        FILE-STATUS IS "9"
    END-MOCK
    PERFORM MAIN-PROCESS
"""
    with pytest.raises(CutParseError, match="exactly two characters"):
        parse_cut(cut)


def test_file_status_inside_write_is_rejected():
    cut = """\
TESTSUITE "s"
TESTCASE "c"
    MOCK WRITE REC1
        FILE-STATUS IS SUCCESS
    END-MOCK
    PERFORM MAIN-PROCESS
"""
    with pytest.raises(CutParseError, match="only valid inside"):
        parse_cut(cut)


def test_file_status_inside_call_is_rejected():
    cut = """\
TESTSUITE "s"
TESTCASE "c"
    MOCK CALL "X"
        FILE-STATUS IS SUCCESS
    END-MOCK
    PERFORM MAIN-PROCESS
"""
    with pytest.raises(CutParseError, match="only valid inside"):
        parse_cut(cut)


def test_second_file_status_in_one_body_is_rejected():
    cut = """\
TESTSUITE "s"
TESTCASE "c"
    MOCK READ FILE1
        FILE-STATUS IS SUCCESS
        FILE-STATUS IS FILE-NOT-FOUND
    END-MOCK
    PERFORM MAIN-PROCESS
"""
    with pytest.raises(CutParseError, match="a second FILE-STATUS IS"):
        parse_cut(cut)


def test_mock_without_file_status_has_none():
    cut = """\
TESTSUITE "s"
TESTCASE "c"
    MOCK OPEN FILE1
    END-MOCK
    PERFORM MAIN-PROCESS
"""
    assert _mock(cut).file_status is None


def test_unquoted_numeric_code_is_a_parse_error():
    cut = """\
TESTSUITE "s"
TESTCASE "c"
    MOCK READ FILE1
        FILE-STATUS IS 92
    END-MOCK
    PERFORM MAIN-PROCESS
"""
    with pytest.raises(CutParseError, match="malformed FILE-STATUS"):
        parse_cut(cut)


def test_mnemonic_with_digits_is_a_parse_error():
    cut = """\
TESTSUITE "s"
TESTCASE "c"
    MOCK READ FILE1
        FILE-STATUS IS EOF10
    END-MOCK
    PERFORM MAIN-PROCESS
"""
    with pytest.raises(CutParseError, match="malformed FILE-STATUS"):
        parse_cut(cut)


def test_missing_value_is_a_parse_error():
    cut = """\
TESTSUITE "s"
TESTCASE "c"
    MOCK READ FILE1
        FILE-STATUS IS
    END-MOCK
    PERFORM MAIN-PROCESS
"""
    with pytest.raises(CutParseError, match="malformed FILE-STATUS"):
        parse_cut(cut)


def test_malformed_file_status_error_names_accepted_forms():
    cut = """\
TESTSUITE "s"
TESTCASE "c"
    MOCK READ FILE1
        FILE-STATUS IS 92
    END-MOCK
    PERFORM MAIN-PROCESS
"""
    with pytest.raises(CutParseError, match='SUCCESS') as exc_info:
        parse_cut(cut)
    assert '"xx"' in str(exc_info.value) or "two-character" in str(exc_info.value)
