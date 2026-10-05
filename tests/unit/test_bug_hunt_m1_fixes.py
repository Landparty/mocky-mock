"""Regression tests for the 2026-10-05 executed bug hunt (mocky-mock
issues #139-#150). The executed counterparts live in
tests/integration/test_bug_hunt_m1_fixes.py."""

from __future__ import annotations

from mockymock.report.results import parse_stdout


def test_139_marker_after_no_advancing_output_is_still_parsed() -> None:
    stdout = (
        "__MOCKYMOCK__ TESTSUITE: noadv\n"
        "__MOCKYMOCK__ CASE 001 START: one\n"
        "PROGRESS...__MOCKYMOCK__ CASE 001 FAIL: expected WS-A = 2, got 1\n"
        "__MOCKYMOCK__ CASE 001 END\n"
        "__MOCKYMOCK__ CASE 002 START: two\n"
        "PROGRESS...__MOCKYMOCK__ CASE 002 END\n"
        "__MOCKYMOCK__ SUMMARY: RUN=2 FAILURES=1\n"
    )
    suite = parse_stdout(stdout)
    one, two = suite.results
    assert one.failure_reasons == ["expected WS-A = 2, got 1"]
    assert one.ended and not one.passed
    assert two.passed
    assert not suite.all_passed
