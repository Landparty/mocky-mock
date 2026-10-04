"""Unit tests for `report.record_rewrite`: matching a stub scan against a
recorded run, rendering values, and rewriting `.cut` text. See
docs/2026-08-04-record-expectations-design.md."""

from mockymock.analysis.assertion_labels import scan_assertion_labels
from mockymock.analysis.stub_expectations import scan_stub_expectations
from mockymock.dsl.parser import parse_cut
from mockymock.report.record_rewrite import (
    build_recording_report,
    field_pictures,
    numeric_scale,
    picture_for,
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


# --- PICTURE-aware rendering (signed / implied-decimal numerics) -------------
# GnuCOBOL -std=mvs (mockymock's only compile mode) DISPLAYs a signed
# USAGE DISPLAY item with a TRAILING separate sign and no decimal point
# (`005+`, `00350-`), and a signed COMP/COMP-3 item with a LEADING sign
# (`+00007`) -- verified in the mockymock-cobc container. Rendered by text
# shape alone these became `"005+"` (never equal to the field) or, for an
# unsigned `9(3)V99`, the bare 100x-too-large `00350`: goldens that failed
# on the very next run.


def test_numeric_scale_reads_plain_numeric_pictures():
    assert numeric_scale("9(5)") == 0
    assert numeric_scale("S9(3)V99") == 2
    assert numeric_scale("s9v9(4)") == 4


def test_numeric_scale_is_none_for_non_plain_numeric_pictures():
    assert numeric_scale(None) is None
    assert numeric_scale("X(10)") is None
    assert numeric_scale("ZZZ9.99") is None
    assert numeric_scale("9(3)PP") is None


def test_signed_display_integer_trailing_sign_renders_bare():
    assert render_expect_value("005+", "S9(3)") == "005"
    assert render_expect_value("005-", "S9(3)") == "-005"


def test_implied_decimal_gets_its_point_back():
    assert render_expect_value("00350", "9(3)V99") == "003.50"
    assert render_expect_value("00350-", "S9(3)V99") == "-003.50"
    assert render_expect_value("5", "9V99") == "0.05"


def test_binary_and_packed_leading_sign_renders_bare():
    assert render_expect_value("+00007", "S9(4)") == "00007"
    assert render_expect_value("-01225", "S9(3)V99") == "-012.25"


def test_pretty_display_text_is_left_as_is_apart_from_the_sign():
    assert render_expect_value("+003.50", "S9(3)V99") == "003.50"


def test_non_numeric_bytes_in_a_numeric_field_fall_back_to_quoting():
    assert render_expect_value("ABC", "9(3)") == '"ABC"'


def test_an_all_spaces_value_renders_as_spaces_not_a_zero_length_literal():
    # `""` is a zero-length literal: GnuCOBOL only warns ("a SPACE will be
    # assumed"), IBM Enterprise COBOL rejects it outright.
    assert render_expect_value("   ", "9(3)") == "SPACES"
    assert render_expect_value("     ", "X(5)") == "SPACES"
    assert render_expect_value("     ") == "SPACES"
    assert render_expect_value("") == "SPACES"


def test_numeric_looking_text_in_an_alphanumeric_field_is_quoted():
    # `IF WS-X NOT = -3` / `NOT = 1.5` against a PIC X field holding `-3` /
    # `1.5` is TRUE under GnuCOBOL -std=mvs (verified in the mockymock-cobc
    # container), so a bare golden failed on the very next run.
    assert render_expect_value("-3", "X(5)") == '"-3"'
    assert render_expect_value("1.5", "X(5)") == '"1.5"'
    assert render_expect_value("007", "XXX") == '"007"'
    assert render_expect_value("12", "A(2)") == '"12"'
    assert render_expect_value("12", "N(2)") == '"12"'
    # A numeric-edited or unknown PICTURE keeps the text-shape decision.
    assert render_expect_value("1.5", "Z9.9") == "1.5"
    assert render_expect_value("1.5") == "1.5"


def test_alphanumeric_picture_keeps_text_shape_rendering():
    assert render_expect_value("005+", "X(4)") == '"005+"'


def test_picture_for_strips_subscripts_but_not_reference_modification():
    pictures = {"WS-EL": "S9(3)"}
    assert picture_for("WS-EL(2)", pictures) == "S9(3)"
    assert picture_for("ws-el", pictures) == "S9(3)"
    assert picture_for("WS-EL(1:2)", pictures) is None
    assert picture_for("WS-OTHER", pictures) is None
    assert picture_for("WS-EL", None) is None


def test_field_pictures_covers_program_items_and_capture_targets():
    from cobolparser import parse_cobol

    from mockymock.splicer.captures import CapturePlan

    program = parse_cobol(
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. P.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01 WS-GRP.\n"
        "          05 WS-AMT PIC S9(3)V99.\n"
        "       PROCEDURE DIVISION.\n"
        "           STOP RUN.\n"
    ).ast
    plan = CapturePlan(
        target="UT-CAP-X-1",
        source_name="WS-AMT",
        declaration="01  UT-CAP-X-1  PIC S9(3)V99.",
        reset_line="MOVE ZERO TO UT-CAP-X-1",
    )
    pictures = field_pictures(program, [plan])
    assert pictures["WS-AMT"] == "S9(3)V99"
    assert pictures["UT-CAP-X-1"] == "S9(3)V99"
    assert "WS-GRP" not in pictures


def test_rewrite_renders_a_signed_field_from_its_picture():
    scan = _scan()
    suite_result = _TestSuiteResult(
        suite_name="S",
        results=[
            _TestResult(
                case_id="001", case_name="calc", recorded=[("WS-NET-TOTAL", "14550-")]
            )
        ],
    )
    report = build_recording_report(scan, suite_result)
    rewritten = rewrite_cut_text(CUT_TEXT, report, {"WS-NET-TOTAL": "S9(5)V99"})
    assert "EXPECT WS-NET-TOTAL TO BE -145.50" in rewritten


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


def test_same_field_stub_recorded_twice_in_one_case_keeps_both_values():
    """2026-08-12 audit Finding 10: build_recording_report collapsed a
    case's recorded (name, value) pairs with dict(), so two stubs for the
    SAME data-name in one TESTCASE (e.g. a counter captured before and
    after a step) both silently got the LAST recorded value -- the earlier
    golden was corrupted with no warning. Values must be consumed in
    emission order, which is stub line order (record_targets is built by
    appending stubs in scan order and the driver DISPLAYs in list order)."""
    text = """\
TESTSUITE "S"

TESTCASE "calc"
    PERFORM CALC-TOTALS
    *> STUB EXPECT WS-COUNT -- before the second step
    *> STUB EXPECT WS-COUNT -- after the second step
"""
    scan = _scan(text)
    suite_result = _TestSuiteResult(
        suite_name="S",
        results=[
            _TestResult(
                case_id="001",
                case_name="calc",
                recorded=[("WS-COUNT", "1"), ("WS-COUNT", "2")],
            )
        ],
    )
    report = build_recording_report(scan, suite_result)
    assert [(r.stub.line, r.value) for r in report.recorded] == [(5, "1"), (6, "2")]
    assert report.skipped == []


def test_more_stubs_than_recorded_values_skips_only_the_unmatched_tail():
    """When the same-name queue runs dry (fewer recorded values than
    stubs), only the surplus stubs are skipped -- the matched head keeps
    its correct values."""
    text = """\
TESTSUITE "S"

TESTCASE "calc"
    PERFORM CALC-TOTALS
    *> STUB EXPECT WS-COUNT -- first
    *> STUB EXPECT WS-COUNT -- second, never recorded
"""
    scan = _scan(text)
    suite_result = _TestSuiteResult(
        suite_name="S",
        results=[
            _TestResult(
                case_id="001",
                case_name="calc",
                recorded=[("WS-COUNT", "1")],
            )
        ],
    )
    report = build_recording_report(scan, suite_result)
    assert [(r.stub.line, r.value) for r in report.recorded] == [(5, "1")]
    assert len(report.skipped) == 1
    assert report.skipped[0].line == 6


def test_stub_with_only_an_orphan_record_is_skipped_with_the_real_reason():
    """2026-08-12 audit Finding 12 (half of it): when a stub's RECORD
    marker was parsed but could not be attributed to its case (an orphan
    record), the skip used to claim the case 'crashed before reaching the
    record point' -- the wrong diagnosis, with the right one sitting
    discarded in orphan_records. The orphan here carries the stub's OWN
    case id (the lost-START shape: the RECORD line parsed but no
    TestResult exists for its id), so the match must fire."""
    scan = _scan()
    suite_result = _TestSuiteResult(
        suite_name="S",
        results=[],  # case 001's START never parsed
        orphan_records=[("001", "WS-NET-TOTAL", "145.50")],
    )
    report = build_recording_report(scan, suite_result)
    assert report.recorded == []
    assert len(report.skipped) == 1
    assert "unattributable" in report.skipped[0].reason
    assert "crashed" not in report.skipped[0].reason


def test_unrelated_orphan_record_does_not_hijack_a_crashed_case_diagnosis():
    """Copilot review on PR #68: the first cut of the orphan-record match
    keyed on data-name alone, so ANY orphan for that name -- even one
    whose case id has nothing to do with this stub's case -- flipped a
    legitimate 'crashed before reaching the record point' diagnosis to
    the orphan reason. The match must key on (case_id, data_name)."""
    scan = _scan()
    suite_result = _TestSuiteResult(
        suite_name="S",
        # Case 001 really did start and crash before its record point...
        results=[_TestResult(case_id="001", case_name="calc")],
        # ...while an unrelated orphan for the same field name exists.
        orphan_records=[("999", "WS-NET-TOTAL", "145.50")],
    )
    report = build_recording_report(scan, suite_result)
    assert report.recorded == []
    assert len(report.skipped) == 1
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
    assert lines[4] == (
        "    *> CHARACTERIZATION: recorded by mockymock run --record-expectations"
    )
    assert lines[5] == "    EXPECT WS-NET-TOTAL TO BE 145.50"
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
    assert rewritten.splitlines()[5] == "        EXPECT WS-NET-TOTAL TO BE 5"


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


# --- CHARACTERIZATION labels -------------------------------------------------


def _record(text, recorded):
    scan = scan_stub_expectations(text, parse_cut(text))
    suite_result = _TestSuiteResult(
        suite_name="S",
        results=[_TestResult(case_id="001", case_name="calc", recorded=recorded)],
    )
    return rewrite_cut_text(text, build_recording_report(scan, suite_result))


def test_rewrite_can_skip_the_label():
    scan = _scan()
    suite_result = _TestSuiteResult(
        suite_name="S",
        results=[
            _TestResult(
                case_id="001", case_name="calc", recorded=[("WS-NET-TOTAL", "5")]
            )
        ],
    )
    report = build_recording_report(scan, suite_result)
    rewritten = rewrite_cut_text(CUT_TEXT, report, label=False)
    assert "CHARACTERIZATION" not in rewritten
    assert rewritten.splitlines()[4] == "    EXPECT WS-NET-TOTAL TO BE 5"


def test_consecutive_recorded_lines_share_one_label():
    text = """\
TESTSUITE "S"

TESTCASE "calc"
    PERFORM CALC-TOTALS
    *> STUB EXPECT WS-A -- first
    *> STUB EXPECT WS-B -- second
"""
    rewritten = _record(text, [("WS-A", "1"), ("WS-B", "2")])
    assert rewritten.count("CHARACTERIZATION") == 1
    labels = scan_assertion_labels(rewritten)
    assert [a.label for a in labels] == ["characterization", "characterization"]


def test_label_does_not_spread_onto_a_following_hand_written_intent_assertion():
    text = """\
TESTSUITE "S"

TESTCASE "calc"
    PERFORM CALC-TOTALS
    *> INTENT: BR-001 total is the sum
    *> STUB EXPECT WS-A -- recorded
    EXPECT WS-TOTAL TO BE 10
"""
    rewritten = _record(text, [("WS-A", "1")])
    labels = {a.text: a for a in scan_assertion_labels(rewritten)}
    assert labels["EXPECT WS-A TO BE 1"].label == "characterization"
    assert labels["EXPECT WS-TOTAL TO BE 10"].label == "intent"
    assert labels["EXPECT WS-TOTAL TO BE 10"].rule_ids == ["BR-001"]
    parse_cut(rewritten)  # still a valid .cut


def test_label_does_not_spread_onto_a_following_unlabelled_assertion():
    text = """\
TESTSUITE "S"

TESTCASE "calc"
    PERFORM CALC-TOTALS
    *> STUB EXPECT WS-A -- recorded
    EXPECT WS-TOTAL TO BE 10
"""
    rewritten = _record(text, [("WS-A", "1")])
    labels = {a.text: a for a in scan_assertion_labels(rewritten)}
    assert labels["EXPECT WS-TOTAL TO BE 10"].label is None
    parse_cut(rewritten)
