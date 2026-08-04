"""Unit tests for `report.record_rewrite`: matching a stub scan against a
recorded run, rendering values, and rewriting `.cut` text. See
docs/2026-08-04-record-expectations-design.md."""

from mockymock.analysis.stub_expectations import scan_stub_expectations
from mockymock.dsl.parser import parse_cut
from mockymock.report.record_rewrite import (
    build_recording_report,
    render_expect_value,
    rewrite_cut_text,
)
from mockymock.report.results import TestResult as _TestResult
from mockymock.report.results import TestSuiteResult as _TestSuiteResult

CUT_TEXT = """\
TESTSUITE "S"

TESTCASE "calc"
    PERFORM CALC-TOTALS
    *> STUB EXPECT WS-NET-TOTAL -- computed in CALC-TOTALS
"""


def _scan(text=CUT_TEXT):
    return scan_stub_expectations(text, parse_cut(text))


# --- render_expect_value -----------------------------------------------------


def test_renders_a_plain_integer_bare():
    assert render_expect_value("12345") == "12345"


def test_renders_a_negative_decimal_bare():
    assert render_expect_value("-3.50") == "-3.50"


def test_renders_alphanumeric_text_quoted_and_trimmed():
    assert render_expect_value("SMITH               ") == '"SMITH"'


def test_renders_embedded_quote_doubled():
    assert render_expect_value('OK"WEIRD') == '"OK""WEIRD"'


def test_leading_zeros_are_preserved_bare():
    # A COBOL numeric literal legally carries leading zeros; DISPLAY of a
    # PIC 9(5) field commonly renders them (e.g. "00090").
    assert render_expect_value("00090.00") == "00090.00"


def test_spaces_around_digits_are_not_bare_numeric():
    # Falls to the quoted path deliberately -- see the design doc's
    # numeric-edited PICTURE caveat. Only trailing whitespace is trimmed
    # (the safe, comparison-preserving direction for a padded alphanumeric
    # field); a leading space is left exactly as DISPLAY rendered it.
    assert render_expect_value("  42") == '"  42"'


# --- build_recording_report --------------------------------------------------


def test_stub_with_a_matching_recorded_value_is_recorded():
    scan = _scan()
    suite_result = _TestSuiteResult(
        suite_name="S",
        results=[
            _TestResult(
                case_id="001",
                case_name="calc",
                recorded=[("WS-NET-TOTAL", "145.50")],
            )
        ],
    )
    report = build_recording_report(scan, suite_result)
    assert len(report.recorded) == 1
    assert report.recorded[0].value == "145.50"
    assert report.recorded[0].stub.data_name == "WS-NET-TOTAL"
    assert report.skipped == []


def test_stub_whose_case_never_recorded_is_skipped_as_crashed():
    scan = _scan()
    suite_result = _TestSuiteResult(
        suite_name="S",
        results=[_TestResult(case_id="001", case_name="calc")],  # no recorded values
    )
    report = build_recording_report(scan, suite_result)
    assert report.recorded == []
    assert len(report.skipped) == 1
    assert report.skipped[0].data_name == "WS-NET-TOTAL"
    assert "crashed before reaching the record point" in report.skipped[0].reason


def test_pre_existing_scan_skips_pass_through_unchanged():
    text = """\
TESTSUITE "S"

*> STUB EXPECT WS-EARLY -- before any case
TESTCASE "calc"
    PERFORM CALC-TOTALS
"""
    scan = _scan(text)
    suite_result = _TestSuiteResult(suite_name="S", results=[])
    report = build_recording_report(scan, suite_result)
    assert report.recorded == []
    assert len(report.skipped) == 1
    assert report.skipped[0].data_name == "WS-EARLY"
    assert "not inside any TESTCASE" in report.skipped[0].reason


# --- rewrite_cut_text ---------------------------------------------------------


def test_rewrite_replaces_the_stub_line_with_a_real_expect():
    scan = _scan()
    suite_result = _TestSuiteResult(
        suite_name="S",
        results=[
            _TestResult(
                case_id="001", case_name="calc", recorded=[("WS-NET-TOTAL", "145.50")]
            )
        ],
    )
    report = build_recording_report(scan, suite_result)
    rewritten = rewrite_cut_text(CUT_TEXT, report)
    assert rewritten is not None
    lines = rewritten.splitlines()
    assert lines[4] == "    EXPECT WS-NET-TOTAL TO BE 145.50"
    # Every other line is untouched.
    original_lines = CUT_TEXT.splitlines()
    for i in (0, 1, 2, 3):
        assert lines[i] == original_lines[i]


def test_rewrite_preserves_the_stub_s_own_indentation():
    text = """\
TESTSUITE "S"

TESTCASE "calc"
    PERFORM CALC-TOTALS
        *> STUB EXPECT WS-NET-TOTAL -- extra-indented
"""
    scan = _scan(text)
    suite_result = _TestSuiteResult(
        suite_name="S",
        results=[
            _TestResult(
                case_id="001", case_name="calc", recorded=[("WS-NET-TOTAL", "5")]
            )
        ],
    )
    report = build_recording_report(scan, suite_result)
    rewritten = rewrite_cut_text(text, report)
    assert rewritten.splitlines()[4] == "        EXPECT WS-NET-TOTAL TO BE 5"


def test_rewrite_quotes_alphanumeric_values():
    scan = _scan()
    suite_result = _TestSuiteResult(
        suite_name="S",
        results=[
            _TestResult(
                case_id="001", case_name="calc", recorded=[("WS-NET-TOTAL", "OK")]
            )
        ],
    )
    report = build_recording_report(scan, suite_result)
    rewritten = rewrite_cut_text(CUT_TEXT, report)
    assert 'EXPECT WS-NET-TOTAL TO BE "OK"' in rewritten


def test_rewrite_returns_none_when_nothing_was_recorded():
    scan = _scan()
    suite_result = _TestSuiteResult(
        suite_name="S", results=[_TestResult(case_id="001", case_name="calc")]
    )
    report = build_recording_report(scan, suite_result)
    assert rewrite_cut_text(CUT_TEXT, report) is None


def test_rewrite_is_idempotent_on_a_second_pass():
    """The core "never overwrite a hand-edited EXPECT" guarantee: once a
    stub becomes a real EXPECT line, a second scan over the rewritten text
    finds zero remaining stubs, so a second recording pass changes
    nothing."""
    scan = _scan()
    suite_result = _TestSuiteResult(
        suite_name="S",
        results=[
            _TestResult(
                case_id="001", case_name="calc", recorded=[("WS-NET-TOTAL", "145.50")]
            )
        ],
    )
    report = build_recording_report(scan, suite_result)
    rewritten = rewrite_cut_text(CUT_TEXT, report)
    assert rewritten is not None

    second_suite = parse_cut(rewritten)
    second_scan = scan_stub_expectations(rewritten, second_suite)
    assert second_scan.stubs == []

    second_report = build_recording_report(second_scan, suite_result)
    assert rewrite_cut_text(rewritten, second_report) is None


def test_rewrite_preserves_trailing_newline_presence():
    no_trailing_newline = CUT_TEXT.rstrip("\n")
    scan = scan_stub_expectations(no_trailing_newline, parse_cut(no_trailing_newline))
    suite_result = _TestSuiteResult(
        suite_name="S",
        results=[
            _TestResult(
                case_id="001", case_name="calc", recorded=[("WS-NET-TOTAL", "5")]
            )
        ],
    )
    report = build_recording_report(scan, suite_result)
    rewritten = rewrite_cut_text(no_trailing_newline, report)
    assert rewritten is not None
    assert not rewritten.endswith("\n")
