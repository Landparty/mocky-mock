"""Tests for parsing GnuCOBOL's COB_TRACE_FILE output and formatting the
execution-trace report. Pure string parsing -- no Docker dependency,
mirroring test_coverage.py's design.

The sample below is verbatim real output from the mockymock-cobc container
(GnuCOBOL 3.2.0) with COB_TRACE_FORMAT='%P|%S|%L'.
"""

import json

from mockymock.report.trace import (
    TRACE_JSON_VERSION,
    TraceEntry,
    format_trace_console,
    format_trace_json,
    parse_trace,
)

TRACE_SAMPLE = "\n".join(
    [
        "Source: 'spike.cbl'",
        "Program-Id:  SPIKE",
        "Program-Id:  SPIKE           |    Entry: SPIKE                          |     8",
        "Program-Id:  SPIKE           |Paragraph: MAIN-PARA                      |     8",
        "Program-Id:  SPIKE           |           MOVE                           |     9",
        "Program-Id:  SPIKE           |           PERFORM                        |    10",
        "Program-Id:  SPIKE           |Paragraph: CALC-PARA                      |    14",
        "Program-Id:  SPIKE           |           ADD                            |    15",
    ]
)


def test_parse_trace_skips_header_lines():
    """The two preamble lines carry no | delimiters and must not become
    entries."""
    entries = parse_trace(TRACE_SAMPLE)
    assert [entry.line for entry in entries] == [8, 9, 10, 14, 15]


def test_parse_trace_strips_field_padding():
    entries = parse_trace(TRACE_SAMPLE)
    assert entries[1].statement == "MOVE"
    assert entries[1].paragraph is None


def test_parse_trace_distinguishes_paragraphs_from_statements():
    entries = parse_trace(TRACE_SAMPLE)
    paragraphs = [e.paragraph for e in entries if e.paragraph]
    assert paragraphs == ["MAIN-PARA", "CALC-PARA"]


def test_parse_trace_drops_program_entry_lines():
    """`Entry: SPIKE` is the program entry, not a user statement."""
    entries = parse_trace(TRACE_SAMPLE)
    assert not any("SPIKE" == e.statement for e in entries)


def test_parse_trace_tolerates_empty_input():
    assert parse_trace("") == []


def _payload(**overrides):
    args = {
        "entries": [
            TraceEntry(line=9, statement="MOVE", paragraph=None),
            TraceEntry(line=10, statement="ADD", paragraph=None),
        ],
        "line_map": {9: 42},
        "mock_hits": ["CALL 'CUSTLOOK'"],
        "case_name": "posts a credit",
        "case_line": 12,
        "cut_file": "t.cut",
        "program_file": "P.cbl",
    }
    args.update(overrides)
    return json.loads(format_trace_json(**args))


def test_trace_json_carries_the_contract_shape():
    payload = _payload()
    assert payload["version"] == TRACE_JSON_VERSION
    assert payload["cutFile"] == "t.cut"
    assert payload["programFile"] == "P.cbl"
    assert payload["case"] == {"name": "posts a credit", "line": 12}
    assert payload["truncated"] is False


def test_trace_json_drops_lines_with_no_original_counterpart():
    """Instrumented line 10 maps nowhere -- it is splicer-inserted, so it is
    not the user's code and must not appear in the path."""
    payload = _payload()
    assert payload["path"] == [{"line": 42, "statement": "MOVE"}]


def test_trace_json_numbers_mocks_from_one_in_firing_order():
    payload = _payload(mock_hits=["CALL 'A'", "READ F", "CALL 'B'"])
    assert payload["mocks"] == [
        {"order": 1, "label": "CALL 'A'"},
        {"order": 2, "label": "READ F"},
        {"order": 3, "label": "CALL 'B'"},
    ]


def test_trace_json_renders_paragraph_entries():
    payload = _payload(
        entries=[TraceEntry(line=9, statement=None, paragraph="CALC-PARA")],
        line_map={9: 42},
    )
    assert payload["path"] == [{"line": 42, "paragraph": "CALC-PARA"}]


def test_trace_json_flags_truncation_at_the_cap():
    from mockymock.report.trace import TRACE_ENTRY_CAP

    entries = [
        TraceEntry(line=1, statement="MOVE", paragraph=None)
        for _ in range(TRACE_ENTRY_CAP + 10)
    ]
    payload = _payload(entries=entries, line_map={1: 5})
    assert payload["truncated"] is True
    assert len(payload["path"]) == TRACE_ENTRY_CAP


def test_trace_json_case_line_may_be_absent():
    payload = _payload(case_line=None)
    assert payload["case"]["line"] is None


def test_console_report_lists_mocks_in_order_and_statement_count():
    text = format_trace_console(_payload(mock_hits=["CALL 'A'", "READ F"]))
    assert "posts a credit" in text
    assert "1. CALL 'A'" in text
    assert "2. READ F" in text
    assert "statements executed: 1" in text


def test_console_report_says_so_when_no_mocks_fired():
    assert "mocks fired: none" in format_trace_console(_payload(mock_hits=[]))


# Regression: open gaps the cobol-test run on PAYMAIN + PAYCALC found
# (2026-11-06); executed counterpart:
# tests/integration/test_open_gaps_2026_11_06.py. `run --trace` collapses a
# spliced statement and labels a USE REAL CALL as real.
from mockymock.splicer.injector import REAL_SUFFIX


def _entry(line, statement=None, paragraph=None):
    return TraceEntry(line=line, statement=statement, paragraph=paragraph)


def test_trace_collapses_a_spliced_statement_into_one_entry():
    # Instrumented lines 10-14 are the dispatch block replacing source line
    # 3 (a CALL); 20 is the next statement, line 4.
    entries = [
        _entry(9, paragraph="MAIN"),
        _entry(10, "EVALUATE"),
        _entry(11, "WHEN"),
        _entry(12, "ADD"),
        _entry(13, "DISPLAY"),
        _entry(14, "CALL"),
        _entry(20, "MOVE"),
        _entry(10, "EVALUATE"),  # the same block, run again
        _entry(11, "WHEN"),
    ]
    line_map = {9: 2, 10: 3, 11: 3, 12: 3, 13: 3, 14: 3, 20: 4}
    original = [
        "       MAIN.",
        "       MAIN.",
        "           CALL 'PAYCALC' USING PAY-AREA",
        "           MOVE 1 TO X",
    ]
    payload = json.loads(
        format_trace_json(
            entries,
            line_map,
            ["CALL PAYCALC" + REAL_SUFFIX, "READ F"],
            "c",
            1,
            "t.cut",
            "p.cbl",
            original_lines=original,
        )
    )
    assert payload["path"] == [
        {"line": 2, "paragraph": "MAIN"},
        {"line": 3, "statement": "CALL", "spliced": True},
        {"line": 4, "statement": "MOVE"},
        {"line": 3, "statement": "CALL", "spliced": True},
    ]
    assert payload["mocks"] == [
        {"order": 1, "label": "CALL PAYCALC", "real": True},
        {"order": 2, "label": "READ F"},
    ]
    console = format_trace_console(payload)
    assert "mocks and real calls, in order:" in console
    assert "1. CALL PAYCALC (real program, not mocked)" in console
    assert "CALL (mocked or linked by mockymock)" in console


def test_trace_keeps_plain_statements_on_one_line_apart():
    # Two statements on one instrumented line are two entries, as before.
    entries = [_entry(5, "MOVE"), _entry(5, "MOVE")]
    payload = json.loads(
        format_trace_json(entries, {5: 7}, [], "c", None, "t.cut", "p.cbl")
    )
    assert payload["path"] == [
        {"line": 7, "statement": "MOVE"},
        {"line": 7, "statement": "MOVE"},
    ]
    assert "mocks fired: none" in format_trace_console(payload)
