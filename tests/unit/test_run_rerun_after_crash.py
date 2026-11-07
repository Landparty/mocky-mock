"""`run` builds the cases a crash kept from running again (2026-11-03,
NIST IX102A/IC114A: one looping case reported every later case NOT RUN)."""

from __future__ import annotations

import argparse

from mockymock.cli.commands import run as cli


def _report(cases: list[dict]) -> dict:
    return {"cases": cases, "summary": {}}


def test_not_run_cases_take_the_rerun_results() -> None:
    first = (
        _report(
            [
                {"name": "a", "line": 3, "status": "crashed", "risky": False},
                {"name": "b", "line": 9, "status": "not_run", "risky": False},
                {"name": "c", "line": 20, "status": "not_run", "risky": False},
            ]
        ),
        [1, 2, 3],
    )
    rerun = (
        _report(
            [
                {"name": "b", "line": 9, "status": "passed", "risky": False},
                {"name": "c", "line": 20, "status": "failed", "risky": True},
            ]
        ),
        [2, 3],
    )
    report = cli._merge_rerun_reports(first, [rerun])
    assert [case["status"] for case in report["cases"]] == [
        "crashed",
        "passed",
        "failed",
    ]
    assert report["cases"][1]["rerun"] is True
    assert report["summary"] == {
        "testsRun": 3,
        "casesFailed": 1,
        "casesCrashed": 1,
        "casesNotRun": 0,
        "casesRisky": 1,
    }


def test_rerun_entries_match_by_position_not_name_or_line() -> None:
    """Two cases share a name, and --record-expectations moved the lines
    between the runs: only the position says which entry is which."""
    first = (
        _report(
            [
                {"name": "same", "line": 3, "status": "crashed"},
                {"name": "same", "line": 7, "status": "not_run"},
                {"name": "other", "line": 11, "status": "not_run"},
            ]
        ),
        [1, 2, 3],
    )
    rerun = (
        _report(
            [
                {"name": "other", "line": 13, "status": "failed"},
                {"name": "same", "line": 8, "status": "passed"},
            ]
        ),
        [3, 2],
    )
    report = cli._merge_rerun_reports(first, [rerun])
    assert [(c["line"], c["status"]) for c in report["cases"]] == [
        (3, "crashed"),
        (8, "passed"),
        (13, "failed"),
    ]


def test_outputs_about_one_whole_binary_are_not_rerun() -> None:
    plain = argparse.Namespace(case=None, tag=None, json_report="r.json")
    assert cli._can_rerun_left_over_cases(plain)
    for flag in ("case", "junit_xml", "coverage", "trace", "baseline"):
        args = argparse.Namespace(**{**vars(plain), flag: ["x"]})
        assert not cli._can_rerun_left_over_cases(args), flag


def test_run_reruns_until_nothing_is_left(monkeypatch, capsys) -> None:
    calls: list[list[int] | None] = []
    left = {None: [2, 3], (2, 3): [3], (3,): []}

    def fake_suite(args: argparse.Namespace) -> int:
        chosen = getattr(args, "case_positions", None)
        calls.append(chosen)
        args.not_run_after_crash = left[tuple(chosen) if chosen else None]
        return 1 if chosen != [3] else 0

    monkeypatch.setattr(cli, "_cmd_run_suite", fake_suite)
    args = argparse.Namespace(case=None, tag=None, json_report=None)
    assert cli._cmd_run(args) == 1
    assert calls == [None, [2, 3], [3]]
    assert "running them again without the case that stopped it" in (
        capsys.readouterr().out
    )


def test_run_stops_when_every_rerun_crashes_on_its_first_case(
    monkeypatch, capsys
) -> None:
    positions = [1, 2, 3, 4, 5, 6]
    calls: list[list[int] | None] = []

    def fake_suite(args: argparse.Namespace) -> int:
        chosen = getattr(args, "case_positions", None)
        calls.append(chosen)
        args.not_run_after_crash = list((chosen or positions)[1:])
        return 1

    monkeypatch.setattr(cli, "_cmd_run_suite", fake_suite)
    args = argparse.Namespace(case=None, tag=None, json_report=None)
    assert cli._cmd_run(args) == 1
    # The first run, then two reruns that each ran only their first case.
    assert calls == [None, positions[1:], positions[2:]]
    assert "3 case(s) left not run" in capsys.readouterr().out


# Regression: bug hunt of 2026-11-05 (running suites). Crash reruns pick cases
# by position.
from mockymock.cli.checks import filter_suite_cases
from mockymock.dsl.parser import parse_cut
from mockymock.report.json_report import not_run_case_positions, report_case_positions
from mockymock.report.results import parse_stdout

DUPLICATE_NAMES = """\
TESTSUITE "dup"
TESTCASE "same"
    PERFORM A
TESTCASE "same"
    PERFORM B
TESTCASE "other"
    PERFORM B
"""


# --- crash reruns pick cases by position ------------------------------------


def test_case_positions_pick_one_of_two_cases_sharing_a_name() -> None:
    suite = parse_cut(DUPLICATE_NAMES)
    assert filter_suite_cases(suite, None, None, [2, 3]) == []
    assert [case.line for case in suite.test_cases] == [4, 6]


def test_not_run_cases_are_named_by_position() -> None:
    suite = parse_cut(DUPLICATE_NAMES)
    ran = parse_stdout(
        "__MOCKYMOCK__ TESTSUITE: dup\n__MOCKYMOCK__ CASE 001 START: same\n"
    )
    assert not_run_case_positions(ran, suite) == [2, 3]
    assert report_case_positions(ran, suite) == [1, 2, 3]
