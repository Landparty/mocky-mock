"""Bug hunt round 10 (DSL / report / analysis): each test reproduces a
defect found by exercising the pure-Python paths, and pins its fix."""

from __future__ import annotations

import pytest
from cobolparser import parse_cobol

from mockymock.analysis import mock_surface
from mockymock.analysis.refusal import check_test_case
from mockymock.analysis.stub_expectations import scan_stub_expectations
from mockymock.dsl.model import MockCategory
from mockymock.dsl.parser import CutParseError, parse_cut
from mockymock.report.formatters import format_console, format_junit_xml
from mockymock.report.record_rewrite import render_expect_value
from mockymock.report.results import parse_stdout

# --- ACCEPT ... FROM DATE YYYYMMDD read as console input ------------------

_DATE_ACCEPT_SOURCE = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. DATEACC.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-D PIC X(8).
       PROCEDURE DIVISION.
       MAIN-P.
           ACCEPT WS-D FROM DATE YYYYMMDD
           ACCEPT WS-D FROM DAY YYYYDDD
           DISPLAY WS-D.
"""


def _surface(source: str):
    result = parse_cobol(source, filename="prog.cbl")
    assert result.ast is not None
    return result.ast, mock_surface.analyze(result.ast)


def test_accept_from_date_with_format_is_not_a_console_boundary():
    _, surface = _surface(_DATE_ACCEPT_SOURCE)
    assert [
        s for s in surface.boundary_sites if s.category is MockCategory.ACCEPT
    ] == []
    assert [a.from_source for a in surface.non_interactive_accepts] == [
        "DATE YYYYMMDD",
        "DAY YYYYDDD",
    ]


def test_accept_from_date_with_format_is_not_refused():
    program, surface = _surface(_DATE_ACCEPT_SOURCE)
    case = parse_cut('TESTSUITE "s"\nTESTCASE "c"\nPERFORM MAIN-P\n').test_cases[0]
    assert check_test_case(surface, program, case, {}) == []


def test_accept_from_console_is_still_a_boundary():
    source = _DATE_ACCEPT_SOURCE.replace("FROM DAY YYYYDDD", "FROM CONSOLE")
    _, surface = _surface(source)
    accepts = [s for s in surface.boundary_sites if s.category is MockCategory.ACCEPT]
    assert len(accepts) == 1


# --- stdout protocol split on form feed / VT / NEL ------------------------


@pytest.mark.parametrize("control", ["\x0c", "\x0b", "\x1c", "\x85", " "])
def test_fail_reason_keeps_value_past_a_control_character(control):
    stdout = (
        "__MOCKYMOCK__ TESTSUITE: s\n"
        "__MOCKYMOCK__ CASE 001 START: c\n"
        f"__MOCKYMOCK__ CASE 001 FAIL: expected WS-X = 1, got AB{control}CD\n"
        "__MOCKYMOCK__ CASE 001 END\n"
        "__MOCKYMOCK__ SUMMARY: RUN=1 FAILURES=000000001\n"
    )
    suite = parse_stdout(stdout)
    assert suite.results[0].failure_reasons == [f"expected WS-X = 1, got AB{control}CD"]


def test_recorded_value_keeps_value_past_a_form_feed():
    stdout = (
        "__MOCKYMOCK__ CASE 001 START: c\r\n"
        "__MOCKYMOCK__ RECORD 001 WS-X: AB\x0cCD\r\n"
        "__MOCKYMOCK__ CASE 001 END\r\n"
    )
    suite = parse_stdout(stdout)
    assert suite.results[0].recorded == [("WS-X", "AB\x0cCD")]
    assert suite.results[0].ended


def test_golden_with_a_control_character_is_a_hex_literal_that_parses():
    rendered = render_expect_value("AB\x0cCD   ", "X(8)")
    assert rendered == 'X"41420C4344"'
    suite = parse_cut(
        f'TESTSUITE "s"\nTESTCASE "c"\nPERFORM P\nEXPECT WS-X TO BE {rendered}\n'
    )
    assert suite.test_cases[0].expectations[0].expected_value == rendered
    # Plain text is unchanged.
    assert render_expect_value("SMITH  ", "X(7)") == '"SMITH"'


# --- EXPECT sentence period hidden by an inline comment -------------------


def test_expect_period_before_inline_comment_is_refused():
    with pytest.raises(CutParseError, match="ends with a period"):
        parse_cut('TESTSUITE "s"\nTESTCASE "c"\nPERFORM P\nEXPECT WS-X TO BE 5. *> x\n')


def test_expect_period_inside_inline_comment_is_accepted():
    suite = parse_cut(
        'TESTSUITE "s"\nTESTCASE "c"\nPERFORM P\nEXPECT WS-X TO BE "A" *> done.\n'
    )
    assert suite.test_cases[0].expectations[0].expected_value == '"A" *> done.'


# --- comma inside a (...) group split ROWS / TERMINAL / PROVIDER values ---


def test_rows_value_with_comma_subscript_is_one_value():
    suite = parse_cut(
        'TESTSUITE "s"\nTESTCASE "c"\nMOCK READ F ROWS\n'
        "( A = WS-TAB(1, 2), B = FUNCTION MAX(3, 4) )\n"
        "TERMINAL ( A = WS-TAB(2, 1) )\n"
        "END-MOCK\nPERFORM P\n"
    )
    mock = suite.test_cases[0].mocks[0]
    assert mock.rows == [[("A", "WS-TAB(1, 2)"), ("B", "FUNCTION MAX(3, 4)")]]
    assert mock.terminal_row == [("A", "WS-TAB(2, 1)")]


def test_provider_row_value_with_comma_subscript_is_one_value():
    suite = parse_cut(
        'TESTSUITE "s"\nPROVIDER P1\nHEADER Src, Want\n'
        "ROW WS-TAB(1, 2), 5\n"
        'TESTCASE "c" USING PROVIDER P1\nMOVE {Src} TO WS-X\nPERFORM P\n'
        "EXPECT WS-Y TO BE {Want}\n"
    )
    case = suite.test_cases[0]
    assert case.setup_moves == [("WS-TAB(1, 2)", "WS-X")]
    assert case.expectations[0].expected_value == "5"


def test_rows_quoted_comma_still_splits_correctly():
    suite = parse_cut(
        'TESTSUITE "s"\nTESTCASE "c"\nMOCK READ F ROWS\n'
        '( A = "X, (Y", B = 2 )\nEND-MOCK\nPERFORM P\n'
    )
    assert suite.test_cases[0].mocks[0].rows == [[("A", '"X, (Y"'), ("B", "2")]]


# --- JUnit/console: binary died before any CASE START ---------------------


def test_junit_reports_error_when_binary_died_before_first_case():
    suite = parse_stdout("__MOCKYMOCK__ TESTSUITE: s\n")
    xml = format_junit_xml(suite, crash_detail="binary exited with code 134")
    assert 'tests="1"' in xml
    assert 'errors="1"' in xml
    assert "binary exited with code 134" in xml
    console = format_console(suite, crash_detail="binary exited with code 134")
    assert "binary exited with code 134" in console


def test_junit_empty_clean_run_is_unchanged():
    xml = format_junit_xml(parse_stdout(""))
    assert 'tests="0"' in xml and 'errors="0"' in xml


# --- stub scanner classifies TESTCASE headers by the parser's grammar -----


def test_stub_in_case_named_using_provider_is_recorded():
    text = (
        'TESTSUITE "s"\n'
        'TESTCASE "reads USING PROVIDER data"\n'
        "PERFORM P\n"
        "*> STUB EXPECT WS-X\n"
    )
    scan = scan_stub_expectations(text, parse_cut(text))
    assert [(s.data_name, s.case_index) for s in scan.stubs] == [("WS-X", 1)]
    assert scan.skipped == []


def test_stub_in_provider_case_with_extra_spaces_is_skipped_as_provider():
    text = (
        'TESTSUITE "s"\nPROVIDER P1\nHEADER A\nROW 1\n'
        'TESTCASE "c"  USING  PROVIDER P1\n'
        "PERFORM P\n"
        "*> STUB EXPECT WS-X\n"
    )
    scan = scan_stub_expectations(text, parse_cut(text))
    assert scan.stubs == []
    assert "PROVIDER-templated" in scan.skipped[0].reason
