"""Tests for parsing and formatting GnuCOBOL/gcov's per-line coverage
output. Pure string parsing -- no Docker dependency, mirrors
report/results.py's existing design."""

import pytest

from mockymock.report.coverage import (
    CoverageReport,
    UncoveredLine,
    format_coverage_console,
    parse_gcov,
)

SAMPLE_GCOV = (
    "        -:    0:Source:PROG.cbl\n"
    "        -:    0:Graph:PROG.gcno\n"
    "        -:    0:Data:PROG.gcda\n"
    "        -:    0:Runs:1\n"
    "        -:    1:IDENTIFICATION DIVISION.\n"
    "        -:    2:PROGRAM-ID. PROG.\n"
    "        -:    3:\n"
    "       1*:    4:       01  WS-FLAG   PIC X VALUE 'N'.\n"
    "        -:    5:PROCEDURE DIVISION.\n"
    "       1*:    6:MAIN-PARA.\n"
    "       7*:    7:    DISPLAY 'HELLO'\n"
    "    #####:    8:    DISPLAY 'NEVER'\n"
    "        -:    9:.\n"
)


def test_parse_gcov_counts_covered_and_uncovered_executable_lines():
    report = parse_gcov(SAMPLE_GCOV)
    assert report.total_executable == 4  # lines 4, 6, 7, 8
    assert report.total_covered == 3  # lines 4, 6, 7
    assert len(report.uncovered_lines) == 1
    assert report.uncovered_lines[0].line_number == 8
    assert "DISPLAY 'NEVER'" in report.uncovered_lines[0].text


def test_parse_gcov_percentage_is_covered_over_executable():
    report = parse_gcov(SAMPLE_GCOV)
    assert report.percentage == pytest.approx(75.0)


def test_parse_gcov_strips_star_suffix_from_multi_block_line_counts():
    """gcov suffixes a line's count with '*' when the line maps to
    multiple basic blocks with differing counts -- not itself a sign the
    line is uncovered. The '*' must not break int parsing."""
    report = parse_gcov("       3*:    1:IF X = 1 THEN Y ELSE Z.\n")
    assert report.total_executable == 1
    assert report.total_covered == 1
    assert report.uncovered_lines == []


def test_parse_gcov_ignores_header_lines_with_line_number_zero():
    report = parse_gcov("        -:    0:Source:PROG.cbl\n")
    assert report.total_executable == 0
    assert report.total_covered == 0


def test_parse_gcov_percentage_is_100_when_no_executable_lines():
    report = parse_gcov("        -:    0:Source:PROG.cbl\n        -:    1:* comment\n")
    assert report.percentage == 100.0


def test_parse_gcov_ignores_malformed_lines_without_crashing():
    report = parse_gcov("not a gcov line at all\n       1*:    1:DISPLAY 'X'.\n")
    assert report.total_executable == 1
    assert report.total_covered == 1


def test_format_coverage_console_reports_percentage_and_counts():
    report = CoverageReport(total_executable=907, total_covered=692, uncovered_lines=[])
    text = format_coverage_console(report, "DEPTIMSM.cbl")
    assert "76.30% lines executed (692/907)" in text
    assert "DEPTIMSM.cbl" in text


def test_format_coverage_console_lists_uncovered_lines():
    report = CoverageReport(
        total_executable=2,
        total_covered=1,
        uncovered_lines=[UncoveredLine(line_number=8, text="    DISPLAY 'NEVER'")],
    )
    text = format_coverage_console(report, "PROG.cbl")
    assert "  8:     DISPLAY 'NEVER'" in text


def test_format_coverage_console_omits_uncovered_section_when_fully_covered():
    report = CoverageReport(total_executable=4, total_covered=4, uncovered_lines=[])
    text = format_coverage_console(report, "PROG.cbl")
    assert "uncovered lines" not in text
