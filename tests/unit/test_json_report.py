"""Tests for the machine-readable JSON run report
(`mockymock.report.json_report`)."""

import json

from mockymock.dsl.parser import parse_cut
from mockymock.report.json_report import (
    build_json_report,
    format_json_report,
)
from mockymock.report.results import parse_stdout

CUT_TEXT = """\
TESTSUITE "ORDRPROC discount calculation"

TESTCASE "happy path" TAGS "fast"
    MOCK CALL "DISCRATE"
        MOVE 0.10 TO WS-DISCOUNT-PCT
    END-MOCK
    PERFORM PROCESS-ORDER
    EXPECT WS-NET-AMOUNT TO BE 90.00
    VERIFY "DISCRATE" WAS CALLED ONCE

TESTCASE "failing case"
    MOCK CALL "DISCRATE"
    END-MOCK
    PERFORM PROCESS-ORDER
    EXPECT WS-NET-AMOUNT TO BE 50.00
    EXPECT WS-STATUS TO BE "OK"
    VERIFY "DISCRATE" WAS CALLED 2 TIMES

TESTCASE "never reached"
    PERFORM PROCESS-ORDER
    EXPECT WS-NET-AMOUNT TO BE 10.00
"""

STDOUT_ALL_RUN = """\
__MOCKYMOCK__ TESTSUITE: ORDRPROC discount calculation
__MOCKYMOCK__ CASE 001 START: happy path
__MOCKYMOCK__ CASE 001 END
__MOCKYMOCK__ CASE 002 START: failing case
__MOCKYMOCK__ CASE 002 FAIL: expected WS-NET-AMOUNT = 50.00, got 090.00
__MOCKYMOCK__ CASE 002 FAIL: VERIFY CALL DISCRATE WAS CALLED 2 TIMES, got 1
__MOCKYMOCK__ CASE 002 END
__MOCKYMOCK__ CASE 003 START: never reached
__MOCKYMOCK__ CASE 003 END
__MOCKYMOCK__ SUMMARY: RUN=3 FAILURES=2
"""

STDOUT_CRASH = """\
__MOCKYMOCK__ TESTSUITE: ORDRPROC discount calculation
__MOCKYMOCK__ CASE 001 START: happy path
__MOCKYMOCK__ CASE 001 END
__MOCKYMOCK__ CASE 002 START: failing case
"""


def _report(stdout: str, crash_detail: str | None = None) -> dict:
    return build_json_report(
        parse_stdout(stdout),
        cut_suite=parse_cut(CUT_TEXT),
        crash_detail=crash_detail,
        cut_file="PROG.cut",
        program_file="PROG.cbl",
    )


def test_suite_metadata_and_files():
    report = _report(STDOUT_ALL_RUN)
    assert report["version"] == 1
    assert report["suite"]["name"] == "ORDRPROC discount calculation"
    assert report["suite"]["line"] == 1
    assert report["cutFile"] == "PROG.cut"
    assert report["programFile"] == "PROG.cbl"


def test_passed_case_carries_line_and_tags():
    report = _report(STDOUT_ALL_RUN)
    happy = report["cases"][0]
    assert happy["name"] == "happy path"
    assert happy["status"] == "passed"
    assert happy["line"] == 3
    assert happy["tags"] == ["fast"]
    assert happy["failures"] == []


def test_expect_failure_attributes_line_expected_actual():
    report = _report(STDOUT_ALL_RUN)
    failing = report["cases"][1]
    assert failing["status"] == "failed"
    expect_failure = failing["failures"][0]
    assert expect_failure["kind"] == "expect"
    assert expect_failure["expected"] == "50.00"
    assert expect_failure["actual"] == "090.00"
    # Line 15 is `EXPECT WS-NET-AMOUNT TO BE 50.00` in CUT_TEXT.
    assert expect_failure["line"] == 15


def test_expect_failure_with_subscripted_data_name_attributes_correctly():
    """A `EXPECT WS-TABLE(1, 1) TO BE ...` failure must round-trip through
    the driver's DISPLAY text back to its own .cut line -- the subscript's
    internal comma+space must not confuse the `data_name == data_name`
    match in `_attribute_failure` (json_report.py)."""
    cut_text = (
        'TESTSUITE "s"\n\n'
        'TESTCASE "c"\n'
        "    PERFORM MAIN\n"
        "    EXPECT WS-TABLE(1, 1) TO BE 100\n"
    )
    stdout = (
        "__MOCKYMOCK__ TESTSUITE: s\n"
        "__MOCKYMOCK__ CASE 001 START: c\n"
        "__MOCKYMOCK__ CASE 001 FAIL: expected WS-TABLE(1, 1) = 100, got 000\n"
        "__MOCKYMOCK__ CASE 001 END\n"
        "__MOCKYMOCK__ SUMMARY: RUN=1 FAILURES=1\n"
    )
    report = build_json_report(
        parse_stdout(stdout),
        cut_suite=parse_cut(cut_text),
        crash_detail=None,
        cut_file="PROG.cut",
        program_file="PROG.cbl",
    )
    failure = report["cases"][0]["failures"][0]
    assert failure["kind"] == "expect"
    assert failure["expected"] == "100"
    assert failure["actual"] == "000"
    assert failure["line"] == 5


def test_verify_failure_attributes_line_expected_actual():
    report = _report(STDOUT_ALL_RUN)
    verify_failure = report["cases"][1]["failures"][1]
    assert verify_failure["kind"] == "verify"
    assert verify_failure["expected"] == "2 TIMES"
    assert verify_failure["actual"] == "1"
    # Line 17 is `VERIFY "DISCRATE" WAS CALLED 2 TIMES`.
    assert verify_failure["line"] == 17


def test_unmatched_failure_reason_falls_back_to_unknown_kind():
    stdout = STDOUT_ALL_RUN.replace(
        "expected WS-NET-AMOUNT = 50.00, got 090.00", "some freeform failure text"
    )
    report = _report(stdout)
    unknown = report["cases"][1]["failures"][0]
    assert unknown["kind"] == "unknown"
    assert unknown["line"] is None
    assert unknown["message"] == "some freeform failure text"


def test_crashed_case_and_not_run_synthesis():
    report = _report(STDOUT_CRASH, crash_detail="binary exited with code 139")
    by_name = {case["name"]: case for case in report["cases"]}
    assert by_name["failing case"]["status"] == "crashed"
    assert by_name["failing case"]["crashDetail"] == "binary exited with code 139"
    never = by_name["never reached"]
    assert never["status"] == "not_run"
    assert never["line"] == 19
    assert never["crashDetail"] == "binary exited with code 139"
    assert report["summary"]["casesCrashed"] == 1
    assert report["summary"]["casesNotRun"] == 1


def test_orphan_failures_are_reported():
    stdout = STDOUT_ALL_RUN + "__MOCKYMOCK__ CASE 007 FAIL: mystery\n"
    report = _report(stdout)
    assert report["orphanFailures"] == [{"caseId": "007", "message": "mystery"}]


def test_summary_counts():
    report = _report(STDOUT_ALL_RUN)
    assert report["summary"] == {
        "testsRun": 3,
        "casesFailed": 1,
        "casesCrashed": 0,
        "casesNotRun": 0,
    }


def test_format_json_report_round_trips():
    text = format_json_report(_report(STDOUT_ALL_RUN))
    assert text.endswith("\n")
    assert json.loads(text)["version"] == 1


def test_report_without_cut_suite_still_works():
    """The .cut model is optional: results alone produce a report with no
    lines/tags/not-run synthesis (belt-and-braces for callers that only
    have the binary's stdout)."""
    report = build_json_report(parse_stdout(STDOUT_ALL_RUN))
    assert report["cases"][0]["line"] is None
    assert report["cases"][0]["tags"] == []
    assert report["summary"]["casesNotRun"] == 0
