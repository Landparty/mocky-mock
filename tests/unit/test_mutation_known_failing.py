"""A suite with a known-failing case is scored against its passing cases."""

from __future__ import annotations

from mockymock.mutation import runner
from mockymock.mutation.report import MutationOutcome, format_console, to_json_dict
from mockymock.report.results import TestResult, TestSuiteResult


def _suite(*cases: tuple[str, bool, bool]) -> TestSuiteResult:
    """(name, failed, ended) per case."""
    results = [
        TestResult(
            case_id=str(i),
            case_name=name,
            failure_reasons=["expected X = 1, got 2"] if failed else [],
            ended=ended,
        )
        for i, (name, failed, ended) in enumerate(cases, start=1)
    ]
    return TestSuiteResult(
        suite_name="s",
        results=results,
        tests_run=len(results),
        failures=sum(1 for _, failed, _ in cases if failed),
    )


def test_a_suite_failing_only_assertions_is_scorable_without_them():
    suite = _suite(("good", False, True), ("bad", True, True))
    assert runner._cleanly_failing_cases(suite) == ("bad",)


def test_a_crashed_case_or_an_all_red_suite_is_not_scorable():
    assert (
        runner._cleanly_failing_cases(_suite(("a", False, True), ("b", True, False)))
        == ()
    )
    assert runner._cleanly_failing_cases(_suite(("a", True, True))) == ()


def test_only_a_baseline_passing_case_kills_a_mutant():
    expected = ("good", "bad")
    same = _suite(("good", False, True), ("bad", True, True))
    assert runner._classify_without(same, ("bad",), expected) == ("passed", "")
    killed = _suite(("good", True, True), ("bad", True, True))
    assert runner._classify_without(killed, ("bad",), expected)[0] == "failed"


def test_a_mutant_that_stops_the_run_short_is_killed():
    short = _suite(("good", False, True))
    status, detail = runner._classify_without(short, ("bad",), ("good", "bad"))
    assert status == "failed"
    assert "every case" in detail


def test_the_excluded_cases_are_reported():
    outcome = MutationOutcome(program="P.cbl", cut="P.cut", excluded_cases=["bad"])
    assert to_json_dict(outcome)["excludedCases"] == ["bad"]
    assert "scored without 1 case(s)" in format_console(outcome)
