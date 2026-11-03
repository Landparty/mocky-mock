"""`run` builds the cases a crash kept from running again (2026-11-03,
NIST IX102A/IC114A: one looping case reported every later case NOT RUN)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from mockymock.cli import main as cli


def _report(cases: list[dict]) -> str:
    return json.dumps({"cases": cases, "summary": {}})


def test_not_run_cases_take_the_rerun_results(tmp_path: Path) -> None:
    path = tmp_path / "report.json"
    path.write_text(
        _report(
            [
                {"name": "a", "line": 3, "status": "crashed", "risky": False},
                {"name": "b", "line": 9, "status": "not_run", "risky": False},
                {"name": "c", "line": 20, "status": "not_run", "risky": False},
            ]
        )
    )
    rerun = _report(
        [
            {"name": "b", "line": 9, "status": "passed", "risky": False},
            {"name": "c", "line": 20, "status": "failed", "risky": True},
        ]
    )
    cli._merge_rerun_reports(path, [rerun])
    report = json.loads(path.read_text())
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


def test_outputs_about_one_whole_binary_are_not_rerun() -> None:
    plain = argparse.Namespace(case=None, tag=None, json_report="r.json")
    assert cli._can_rerun_left_over_cases(plain)
    for flag in ("case", "junit_xml", "coverage", "trace", "baseline"):
        args = argparse.Namespace(**{**vars(plain), flag: ["x"]})
        assert not cli._can_rerun_left_over_cases(args), flag


def test_run_reruns_until_nothing_is_left(monkeypatch, capsys) -> None:
    calls: list[list[str] | None] = []
    left = {None: ["b", "c"], ("b", "c"): ["c"], ("c",): []}

    def fake_suite(args: argparse.Namespace) -> int:
        calls.append(args.case)
        args.not_run_after_crash = left[tuple(args.case) if args.case else None]
        return 1 if args.case != ["c"] else 0

    monkeypatch.setattr(cli, "_cmd_run_suite", fake_suite)
    args = argparse.Namespace(case=None, tag=None, json_report=None)
    assert cli._cmd_run(args) == 1
    assert calls == [None, ["b", "c"], ["c"]]
    assert "running them again without the case that stopped it" in (
        capsys.readouterr().out
    )


def test_run_stops_when_every_rerun_crashes_on_its_first_case(
    monkeypatch, capsys
) -> None:
    names = ["a", "b", "c", "d", "e", "f"]
    calls: list[list[str] | None] = []

    def fake_suite(args: argparse.Namespace) -> int:
        calls.append(args.case)
        chosen = args.case or names
        args.not_run_after_crash = list(chosen[1:])
        return 1

    monkeypatch.setattr(cli, "_cmd_run_suite", fake_suite)
    args = argparse.Namespace(case=None, tag=None, json_report=None)
    assert cli._cmd_run(args) == 1
    # The first run, then two reruns that each ran only their first case.
    assert calls == [None, names[1:], names[2:]]
    assert "3 case(s) left not run" in capsys.readouterr().out
