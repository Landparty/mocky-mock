"""Issue #252 (option 1): .cut data-names may be qualified with OF/IN, the
only way to name a field declared under two records."""

import pytest

from mockymock.analysis.cut_names import check_cut_data_names
from mockymock.analysis.stub_expectations import scan_stub_expectations
from mockymock.dsl.parser import CutParseError, parse_cut
from mockymock.report.record_rewrite import picture_for
from mockymock.report.results import _RECORD_RE

PROGRAM_LINES = [
    "       01  IN-REC.",
    "           05  CUST-ID    PIC X(5).",
    "       01  OUT-REC.",
    "           05  CUST-ID    PIC X(5).",
    "           05  CUST-TAB   PIC X OCCURS 3.",
]

CUT = (
    'TESTSUITE "q"\nTESTCASE "c"\n'
    '    MOVE "A0001" TO CUST-ID OF IN-REC\n'
    "    PERFORM MAIN-PARA\n"
    '    EXPECT CUST-ID OF OUT-REC TO BE "A0001"\n'
    '    EXPECT CUST-TAB IN OUT-REC (2) NOT TO BE "X"\n'
)


def test_qualified_move_and_expect_parse_verbatim():
    case = parse_cut(CUT).test_cases[0]
    assert case.setup_moves == [('"A0001"', "CUST-ID OF IN-REC")]
    names = [e.data_name for e in case.expectations]
    assert names == ["CUST-ID OF OUT-REC", "CUST-TAB IN OUT-REC (2)"]


def test_qualified_capture_target_parses():
    suite = parse_cut(
        'TESTSUITE "q"\nTESTCASE "c"\n    MOCK CALL "SVC"\n'
        "        CAPTURE ARG 1 INTO CUST-ID OF OUT-REC\n    END-MOCK\n"
        "    PERFORM MAIN-PARA\n"
    )
    assert suite.test_cases[0].mocks[0].captures[0][1] == "CUST-ID OF OUT-REC"


def test_each_qualifier_word_is_checked():
    assert check_cut_data_names(parse_cut(CUT), PROGRAM_LINES) == []
    typo = CUT.replace("OF OUT-REC TO", "OF OUT-RECX TO")
    reasons = check_cut_data_names(parse_cut(typo), PROGRAM_LINES)
    assert [r.message for r in reasons] == [
        ".cut line 5: EXPECT OUT-RECX is not a data item"
    ]


def test_dotted_name_hint_suggests_cobol_qualification():
    with pytest.raises(CutParseError, match="'CUST-ID OF IN-REC'"):
        parse_cut(CUT.replace("CUST-ID OF OUT-REC", "IN-REC.CUST-ID"))


def test_qualified_stub_is_recordable_and_reads_back():
    cut = CUT + "    *> STUB EXPECT CUST-ID OF OUT-REC\n"
    scan = scan_stub_expectations(cut, parse_cut(cut))
    assert [s.data_name for s in scan.stubs] == ["CUST-ID OF OUT-REC"]
    assert scan.skipped == []
    m = _RECORD_RE.match("__MOCKYMOCK__ RECORD 001 CUST-ID OF OUT-REC: A0001")
    assert m is not None and m.group("name") == "CUST-ID OF OUT-REC"
    assert picture_for("CUST-ID OF OUT-REC (1)", {"CUST-ID": "X(5)"}) == "X(5)"
