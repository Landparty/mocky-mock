"""Tests for parsing and formatting GnuCOBOL/gcov's per-line coverage
output. Pure string parsing -- no Docker dependency, mirrors
report/results.py's existing design."""

import pytest

from mockymock.report.coverage import (
    CoverageReport,
    UncoveredLine,
    build_original_line_map,
    format_coverage_console,
    parse_gcov,
)


def test_build_original_line_map_skips_inserted_lines():
    """The splicer's own lines must map nowhere: the trace report and the
    coverage report both mean "which of MY lines ran"."""
    original = [
        "      *comment",
        "       MOVE 1 TO WS-A",
        "       ADD 1 TO WS-A",
    ]
    normalized = ["MOVE 1 TO WS-A", "ADD 1 TO WS-A"]
    instrumented = ["MOVE 1 TO WS-A", "ADD 1 TO UT-TALLY-1", "ADD 1 TO WS-A"]

    mapping = build_original_line_map(instrumented, normalized, original)

    assert mapping[1] == 2
    assert mapping[3] == 3
    assert 2 not in mapping


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


def test_parse_gcov_records_covered_line_numbers():
    report = parse_gcov(SAMPLE_GCOV)
    assert report.covered_lines == [4, 6, 7]


ORIGINAL_CBL = [
    "000100 IDENTIFICATION DIVISION.",
    "000200 PROGRAM-ID. PROG.",
    "000300* a comment line the normalizer drops",
    "000400 PROCEDURE DIVISION.",
    "000500 MAIN-PARA.",
    '000600     DISPLAY "HELLO"',
    "000700     PERFORM SUB-PARA",
    "000800 SUB-PARA.",
    '000900     DISPLAY "NEVER"',
]

# What normalize_fixed_format extracts: columns 8-72, comments dropped.
NORMALIZED = [
    "IDENTIFICATION DIVISION.",
    "PROGRAM-ID. PROG.",
    "PROCEDURE DIVISION.",
    "MAIN-PARA.",
    '    DISPLAY "HELLO"',
    "    PERFORM SUB-PARA",
    "SUB-PARA.",
    '    DISPLAY "NEVER"',
]

# The instrumented source: splicer insertions around otherwise verbatim
# normalized lines (a working-storage addition and driver paragraphs).
INSTRUMENTED = [
    "IDENTIFICATION DIVISION.",
    "PROGRAM-ID. PROG.",
    "01  UT-FAIL-COUNT          PIC 9(9) VALUE 0.",
    "PROCEDURE DIVISION.",
    "UT-DRIVER-MAIN.",
    "    PERFORM UT-TESTCASE-001",
    "    STOP RUN.",
    "MAIN-PARA.",
    '    DISPLAY "HELLO"',
    "    PERFORM SUB-PARA",
    "SUB-PARA.",
    '    DISPLAY "NEVER"',
]


def test_map_coverage_to_original_maps_user_lines_only():
    from mockymock.report.coverage import map_coverage_to_original

    report = CoverageReport(
        total_executable=5,
        total_covered=4,
        # Instrumented lines: 6 (driver PERFORM), 9 (DISPLAY "HELLO"),
        # 10 (PERFORM SUB-PARA) covered; 12 (DISPLAY "NEVER") uncovered.
        covered_lines=[6, 9, 10],
        uncovered_lines=[UncoveredLine(line_number=12, text='DISPLAY "NEVER"')],
    )
    mapped = map_coverage_to_original(report, INSTRUMENTED, NORMALIZED, ORIGINAL_CBL)
    as_dict = {entry.line: entry.covered for entry in mapped}
    # Original lines 6 and 7 (1-based in ORIGINAL_CBL) ran; line 9 did not.
    # The driver's own PERFORM (instrumented line 6) maps nowhere.
    assert as_dict == {6: True, 7: True, 9: False}


def test_map_coverage_excludes_unmappable_instrumentation():
    from mockymock.report.coverage import map_coverage_to_original

    report = CoverageReport(
        total_executable=1,
        total_covered=1,
        covered_lines=[7],  # driver STOP RUN -- instrumentation only
        uncovered_lines=[],
    )
    mapped = map_coverage_to_original(report, INSTRUMENTED, NORMALIZED, ORIGINAL_CBL)
    assert mapped == []


def test_format_coverage_json_shape():
    import json

    from mockymock.report.coverage import (
        MappedLineCoverage,
        format_coverage_json,
    )

    report = CoverageReport(total_executable=4, total_covered=3)
    mapped = [
        MappedLineCoverage(line=6, covered=True),
        MappedLineCoverage(line=9, covered=False),
    ]
    payload = json.loads(
        format_coverage_json(report, mapped, "PROG.cbl", "PROG-instr.cbl")
    )
    assert payload["version"] == 1
    assert payload["programFile"] == "PROG.cbl"
    assert payload["instrumented"]["percentage"] == 75.0
    assert payload["instrumented"]["totalExecutable"] == 4
    assert payload["original"]["totalExecutable"] == 2
    assert payload["original"]["totalCovered"] == 1
    assert payload["original"]["lines"] == [
        {"line": 6, "covered": True},
        {"line": 9, "covered": False},
    ]
