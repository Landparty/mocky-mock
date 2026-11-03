"""Generated cases mock a CALL for every program a reachable CANCEL names
(2026-11-03, NIST IC203A/IC205A): with no real module loaded, the CANCEL
is a no-op, and the refusal gate accepts it only when such a mock exists."""

from cobolparser import parse_cobol

from mockymock.analysis.mock_surface import analyze
from mockymock.dsl.generator import _cancel_cover_lines

SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CANCOVER.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  ID1                PIC X(8) VALUE "SUBA".
       01  ID2                PIC X(8) VALUE "SUBB".
       PROCEDURE DIVISION.
       MAIN-PARA.
           CALL ID1.
           CANCEL ID1, "SUBC", ID2.
       OTHER-PARA.
           CANCEL "SUBD".
"""


def _surface():
    result = parse_cobol(SOURCE, filename="cancover.cbl")
    assert result.success, result.errors
    return analyze(result.ast)


def test_each_name_the_case_does_not_mock_gets_an_empty_call_mock():
    lines = _cancel_cover_lines(
        _surface(), {"MAIN-PARA"}, ["MOCK CALL ID1", "END-MOCK"]
    )
    mocks = [line for line in lines if line.startswith("MOCK")]
    assert mocks == ['MOCK CALL "SUBC"', "MOCK CALL ID2"]
    assert lines.count("END-MOCK") == 2


def test_a_literal_mock_does_not_cover_a_data_name_of_the_same_spelling():
    lines = _cancel_cover_lines(_surface(), {"MAIN-PARA"}, ['MOCK CALL "ID1"'])
    assert "MOCK CALL ID1" in lines


def test_a_cancel_the_case_cannot_reach_gets_no_mock():
    lines = _cancel_cover_lines(
        _surface(),
        {"MAIN-PARA"},
        ["MOCK CALL ID1", 'MOCK CALL "SUBC"', "MOCK CALL ID2"],
    )
    assert lines == []
    assert 'MOCK CALL "SUBD"' in _cancel_cover_lines(_surface(), None, [])
