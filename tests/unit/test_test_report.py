"""mockymock.report.test_report: the joined report behind `mockymock report`.
Docker-free: run/coverage/mutation results are fed in as the JSON files
those commands write, which is exactly the --run-json path."""

import json
import shutil
from pathlib import Path

import pytest

from mockymock.report.journal import append_entry
from mockymock.report.test_report import ReportOptions, build_report

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"

LABELLED_CUT = """\
TESTSUITE "ORDRPROC discount calculation"

TESTCASE "10% discount reduces net amount correctly"
    MOCK CALL "DISCRATE"
        CAPTURE ARG 1 INTO WS-CAPTURED-AMOUNT
        MOVE 0.10 TO WS-DISCOUNT-PCT
    END-MOCK
    MOVE 100.00 TO ORD-AMOUNT
    PERFORM PROCESS-ORDER
    *> INTENT: BR-001 net = amount - amount * discount (ORDRPROC.cbl:14)
    EXPECT WS-NET-AMOUNT TO BE 90.00
    *> CHARACTERIZATION: the amount passed through
    EXPECT WS-CAPTURED-AMOUNT TO BE 100.00
    VERIFY "DISCRATE" WAS CALLED ONCE

TESTCASE "Zero discount leaves amount unchanged"
    MOCK CALL "DISCRATE"
        MOVE 0.00 TO WS-DISCOUNT-PCT
    END-MOCK
    MOVE 50.00 TO ORD-AMOUNT
    PERFORM PROCESS-ORDER
    EXPECT WS-NET-AMOUNT TO BE 50.00
"""


@pytest.fixture
def ordrproc(tmp_path):
    shutil.copy(EXAMPLES / "ordrproc" / "ORDRPROC.cbl", tmp_path / "ORDRPROC.cbl")
    (tmp_path / "ORDRPROC.cut").write_text(LABELLED_CUT, encoding="utf-8")
    return tmp_path


def _write(path: Path, value) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _run_json(tmp_path, first="passed", second="passed", failures=None):
    return _write(
        tmp_path / "run.json",
        {
            "version": 1,
            "cases": [
                {
                    "name": "10% discount reduces net amount correctly",
                    "line": 3,
                    "status": first,
                    "failures": failures or [],
                },
                {
                    "name": "Zero discount leaves amount unchanged",
                    "line": 16,
                    "status": second,
                    "failures": [],
                },
            ],
            "summary": {"testsRun": 2},
        },
    )


def _coverage_json(tmp_path):
    return _write(
        tmp_path / "coverage.json",
        {
            "version": 1,
            "original": {
                "percentage": 83.33,
                "totalExecutable": 6,
                "totalCovered": 5,
                "lines": [
                    {"line": 12, "covered": True},
                    {"line": 14, "covered": False},
                ],
            },
        },
    )


def _mutation_json(tmp_path, score=0.9, survivors=()):
    return _write(
        tmp_path / "mutation.json",
        {
            "score": score,
            "totals": {"generated": 10, "killed": 9, "survived": len(survivors)},
            "mutants": [
                {
                    "line": line,
                    "operator": "AOR",
                    "description": "replace - with +",
                    "original": "A - B",
                    "mutated": "A + B",
                    "status": "survived",
                }
                for line in survivors
            ],
        },
    )


def _options(tmp_path, **kwargs):
    defaults = {
        "program": tmp_path / "ORDRPROC.cbl",
        "cut": tmp_path / "ORDRPROC.cut",
        "probe_toolchain": False,
        "scenarios": "none",
    }
    defaults.update(kwargs)
    return ReportOptions(**defaults)


def _step(report, step_id):
    return next(s for s in report["steps"] if s["id"] == step_id)


def test_static_only_report_runs_every_step_and_claims_only_l0(ordrproc):
    report = build_report(_options(ordrproc))
    assert [s["id"] for s in report["steps"]] == [
        "environment",
        "understand",
        "rules",
        "inventory",
        "lint",
        "scenarios",
        "run",
        "coverage",
        "mutation",
        "dialect",
        "verdict",
    ]
    assert _step(report, "lint")["status"] == "ok"
    assert _step(report, "run")["status"] == "skipped"
    assert _step(report, "mutation")["status"] == "skipped"
    assert {c["level"] for c in report["cases"]} == {"L0"}
    assert report["summary"]["notRun"] == 2


def test_assertion_labels_reach_cases_and_summary(ordrproc):
    report = build_report(_options(ordrproc))
    first = report["cases"][0]
    assert first["assertions"] == {
        "total": 3,
        "intent": 1,
        "characterization": 2,
        "unlabelled": 0,
    }
    assert report["summary"]["intentShare"] == pytest.approx(25.0)


def test_paragraphs_record_which_cases_reach_them(ordrproc):
    report = build_report(_options(ordrproc))
    (paragraph,) = report["paragraphs"]
    assert paragraph["name"] == "PROCESS-ORDER"
    assert len(paragraph["testedBy"]) == 2
    assert paragraph["line"] == 12


def test_passing_run_with_strong_mutation_reaches_l3(ordrproc):
    report = build_report(
        _options(
            ordrproc,
            run_json=_run_json(ordrproc),
            coverage_json=_coverage_json(ordrproc),
            mutation_json=_mutation_json(ordrproc),
        )
    )
    # COMPUTE with no division: no blocking dialect risk in PROCESS-ORDER.
    assert [c["level"] for c in report["cases"]] == ["L3", "L3"]
    assert report["summary"]["mutationScore"] == pytest.approx(90.0)
    assert report["summary"]["coverage"] == pytest.approx(83.33)


def test_weak_mutation_score_caps_cases_at_l1(ordrproc):
    report = build_report(
        _options(
            ordrproc,
            run_json=_run_json(ordrproc),
            mutation_json=_mutation_json(ordrproc, score=0.5, survivors=(14,)),
        )
    )
    assert [c["level"] for c in report["cases"]] == ["L1", "L1"]
    categories = {f["category"] for f in report["findings"]}
    assert "missing-assertion" in categories


def test_hinted_survivor_is_an_untestable_mutant_not_a_missing_assertion(ordrproc):
    path = _mutation_json(ordrproc, score=0.5, survivors=(14,))
    data = json.loads(path.read_text())
    data["mutants"][0]["hint"] = "probably untestable from WS-X's starting value"
    path.write_text(json.dumps(data))
    report = build_report(
        _options(ordrproc, run_json=_run_json(ordrproc), mutation_json=path)
    )
    findings = [f for f in report["findings"] if f.get("line") == 14]
    assert [f["category"] for f in findings] == ["untestable-mutant"]
    assert "WS-X's starting value" in findings[0]["detail"]


def test_failed_intent_assertion_is_a_suspected_bug(ordrproc):
    failures = [
        {
            "message": "expected WS-NET-AMOUNT = 90.00, got 0099.00",
            "kind": "expect",
            "line": 11,
            "expected": "90.00",
            "actual": "0099.00",
        }
    ]
    report = build_report(
        _options(
            ordrproc, run_json=_run_json(ordrproc, first="failed", failures=failures)
        )
    )
    suspected = [f for f in report["findings"] if f["category"] == "suspected-bug"]
    assert len(suspected) == 1
    assert "expected 90.00" in suspected[0]["detail"]
    assert report["findings"][0]["category"] == "suspected-bug"
    assert report["cases"][0]["level"] == "L0"
    assert report["summary"]["failed"] == 1


def test_failed_unlabelled_assertion_is_a_plain_test_failure(ordrproc):
    failures = [{"message": "boom", "kind": "expect", "line": 22}]
    report = build_report(
        _options(ordrproc, run_json=_run_json(ordrproc, second="failed"))
    )
    report2 = build_report(
        _options(
            ordrproc,
            run_json=_run_json(ordrproc, first="failed", failures=failures),
        )
    )
    assert not [f for f in report["findings"] if f["category"] == "suspected-bug"]
    assert [f["category"] for f in report2["findings"]][0] == "test-failure"


def test_missing_result_files_are_reported_not_guessed(ordrproc):
    report = build_report(_options(ordrproc, run_json=ordrproc / "nope.json"))
    run = _step(report, "run")
    assert run["status"] == "fail"
    assert "does not exist" in run["summary"]


def test_lint_refusal_leaves_cases_without_a_level(ordrproc):
    cut = LABELLED_CUT.replace(
        """    MOCK CALL "DISCRATE"
        MOVE 0.00 TO WS-DISCOUNT-PCT
    END-MOCK
""",
        "",
    )
    (ordrproc / "ORDRPROC.cut").write_text(cut, encoding="utf-8")
    report = build_report(_options(ordrproc, run_json=_run_json(ordrproc)))
    assert _step(report, "lint")["status"] == "fail"
    assert all(c["level"] is None for c in report["cases"])
    assert report["findings"][0]["category"] == "refused"


def test_journal_entries_are_included(ordrproc):
    journal = ordrproc / "ORDRPROC.journal.jsonl"
    append_entry(journal, step="plan", summary="one paragraph, one rule")
    with journal.open("a", encoding="utf-8") as handle:
        handle.write("not json\n")
    report = build_report(_options(ordrproc, journal=journal))
    assert report["journal"][0]["summary"] == "one paragraph, one rule"
    assert len(report["journalProblems"]) == 1


def test_scenarios_step_reports_branch_arms(ordrproc):
    report = build_report(_options(ordrproc, scenarios="branches"))
    step = _step(report, "scenarios")
    assert step["status"] in ("ok", "warn")
    assert "scenarioCoverage" in step["details"]


def test_copybook_program_maps_lines_back_to_the_original_source(tmp_path):
    shutil.copytree(EXAMPLES / "cpyproc", tmp_path / "cpyproc")
    root = tmp_path / "cpyproc"
    report = build_report(
        ReportOptions(
            program=root / "CPYPROC.cbl",
            cut=root / "CPYPROC.cut",
            copybook_paths=[str(root / "copybooks")],
            probe_toolchain=False,
            scenarios="none",
        )
    )
    understand = _step(report, "understand")
    assert understand["details"]["copybooksExpanded"] is True
    original = (root / "CPYPROC.cbl").read_text(encoding="utf-8").splitlines()
    for paragraph in report["paragraphs"]:
        if paragraph["line"] is not None:
            assert paragraph["name"] in original[paragraph["line"] - 1]
