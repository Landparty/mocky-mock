"""A failing numeric EXPECT reports the value the field holds, not its raw
DISPLAY image (issue #374)."""

from __future__ import annotations

import pytest

from mockymock.dsl.parser import parse_cut
from mockymock.report.formatters import format_console
from mockymock.report.json_report import build_json_report, readable_suite
from mockymock.report.record_rewrite import display_numeric_value
from mockymock.report.results import parse_stdout


@pytest.mark.parametrize(
    ("raw", "picture", "value"),
    [
        ("0001234-", "S9(5)V99", "-12.34"),
        ("-0000550", "S9(5)V99", "-5.50"),  # COMP-3: leading sign
        ("123", "9(3)PP", "12300"),  # GnuCOBOL 3.2
        ("00123", "9(3)PP", "12300"),  # GnuCOBOL 3.1 pads to the P positions
        ("12+", "SVPP99", "0.0012"),
        ("0012+", "SVPP99", "0.0012"),
        ("-0123", "S9(3)V9", "-12.3"),  # SIGN LEADING SEPARATE
        ("0000-", "S9(4)", "0"),
        ("00125.00", "9(5)V99", "125.00"),  # pretty-display
    ],
)
def test_display_numeric_value(raw: str, picture: str, value: str) -> None:
    assert display_numeric_value(raw, picture) == value


@pytest.mark.parametrize(
    ("raw", "picture"),
    [("ab", "X(2)"), ("12", None), ("1,234", "ZZZ9"), ("ABC", "9(3)")],
)
def test_display_numeric_value_leaves_others_alone(raw: str, picture: str) -> None:
    assert display_numeric_value(raw, picture) is None


def test_decimal_comma() -> None:
    assert display_numeric_value("0001234-", "S9(5)V99", decimal_comma=True) == "-12,34"


CUT = """\
TESTSUITE "nump"
TESTCASE "fail values"
    PERFORM 0000-MAIN
    EXPECT WS-A TO BE 12.34
    EXPECT WS-C TO BE 12400
    EXPECT WS-X TO BE "0013"
"""
STDOUT = (
    "__MOCKYMOCK__ TESTSUITE: nump\n"
    "__MOCKYMOCK__ CASE 001 START: fail values\n"
    "__MOCKYMOCK__ CASE 001 FAIL: expected WS-A = 12.34, got 0001234-\n"
    "__MOCKYMOCK__ CASE 001 FAIL: expected WS-C = 12400, got 123\n"
    '__MOCKYMOCK__ CASE 001 FAIL: expected WS-X = "0013", got 0012\n'
    "__MOCKYMOCK__ CASE 001 END\n"
    "__MOCKYMOCK__ SUMMARY: RUN=1 FAILURES=3\n"
)
PICTURES = {"WS-A": "S9(5)V99", "WS-C": "9(3)PP", "WS-X": "X(4)"}


def test_json_report_renders_actual_and_keeps_the_raw_image() -> None:
    report = build_json_report(
        parse_stdout(STDOUT), cut_suite=parse_cut(CUT), pictures=PICTURES
    )
    failures = report["cases"][0]["failures"]
    assert [(f["actual"], f.get("actualRaw")) for f in failures] == [
        ("-12.34", "0001234-"),
        ("12300", "123"),
        ("0012", None),  # alphanumeric: as displayed
    ]
    assert failures[0]["message"] == (
        "expected WS-A = 12.34, got -12.34 (displayed as 0001234-)"
    )
    # Without pictures the report is as before.
    plain = build_json_report(parse_stdout(STDOUT), cut_suite=parse_cut(CUT))
    assert plain["cases"][0]["failures"][1]["actual"] == "123"
    assert "actualRaw" not in plain["cases"][0]["failures"][1]


def test_console_line_shows_the_value() -> None:
    suite = parse_stdout(STDOUT)
    text = format_console(readable_suite(suite, parse_cut(CUT), PICTURES))
    assert "expected WS-C = 12400, got 12300 (displayed as 123)" in text
    assert 'expected WS-X = "0013", got 0012\n' in text + "\n"
    # The parsed result is untouched.
    assert suite.results[0].failure_reasons[1].endswith("got 123")
