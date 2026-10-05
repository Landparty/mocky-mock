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


def _one_case_suite():
    from mockymock.dsl.model import ExpectDirective, MockTestCase, MockTestSuite

    case = MockTestCase(
        name="rc",
        perform_target="MAIN-PARA",
        expectations=[ExpectDirective("RETURN-CODE", "0")],
    )
    return MockTestSuite(name="rc", test_cases=[case])


def test_140_each_case_and_the_final_stop_run_reset_return_code() -> None:
    from mockymock.splicer.driver import build_driver
    from mockymock.splicer.naming import TallyRegistry

    suite = _one_case_suite()
    lines = [
        line.strip()
        for line in build_driver(suite, [], TallyRegistry(suite)).procedure_lines
    ]
    stop = lines.index("STOP RUN.")
    assert lines[stop - 1] == "MOVE 0 TO RETURN-CODE"
    case_start = lines.index("UT-TESTCASE-001.")
    perform = lines.index("PERFORM MAIN-PARA")
    assert "MOVE 0 TO RETURN-CODE" in lines[case_start:perform]
