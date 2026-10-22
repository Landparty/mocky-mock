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
        "analysis",
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


def test_boundaries_name_the_cases_that_mock_them(ordrproc):
    report = build_report(_options(ordrproc))
    (call,) = [b for b in report["boundaries"] if b["kind"] == "CALL"]
    assert call["target"] == "DISCRATE"
    assert call["paragraph"] == "PROCESS-ORDER"
    assert call["mockable"] is True
    assert len(call["mockedBy"]) == 2
    assert call["reachedUnmockedBy"] == []


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


def test_scenario_gap_without_coverage_does_not_claim_no_test_reaches_it():
    from mockymock.report.test_report import _findings

    arm = {
        "status": "missed",
        "arm_key": "P@24:5/ELSE",
        "parent_proc": "P",
        "reason": "IF@24/ELSE: field not boundary-fed: WS-STATUS",
    }
    kwargs = {
        "cases": [],
        "assertions": [],
        "paragraphs": [],
        "rules": [],
        "rules_available": False,
        "lint_problems": [],
        "risks": [],
        "mutation": None,
        "scenario_coverage": {"total_arms": 2, "details": [arm]},
        "program_lines": [],
    }
    (gap,) = _findings(coverage=None, **kwargs)
    assert "run with coverage" in gap["title"]
    assert "no test reaches" not in gap["title"]
    assert gap["items"] == [
        "P line 24 (ELSE branch): it tests WS-STATUS, which no mocked file, "
        "call or database read sets"
    ]
    (gap,) = [
        f
        for f in _findings(coverage={"uncoveredLines": [24]}, **kwargs)
        if f["category"] == "scenario-gap"
    ]
    assert gap["title"].startswith("1 branch of 2 never ran")


def test_mutation_threshold_is_applied_exactly_not_after_rounding(ordrproc):
    """Issue #282: 399/499 = 79.96% used to round to 80.0, read `ok` and
    earn L3, while `mutate --fail-under 80` failed the same mutants."""
    path = _write(
        ordrproc / "mutation.json",
        {
            "score": 399 / 499,
            "totals": {
                "generated": 499,
                "killed": 399,
                "timeouts": 0,
                "survived": 100,
            },
            "mutants": [],
        },
    )
    report = build_report(
        _options(
            ordrproc,
            run_json=_run_json(ordrproc),
            coverage_json=_coverage_json(ordrproc),
            mutation_json=path,
            mutation_threshold=80.0,
        )
    )
    step = _step(report, "mutation")
    assert step["status"] == "warn"
    assert "79.9%" in step["summary"]
    assert "80.0%" not in step["summary"]
    assert "L3" not in {c["level"] for c in report["cases"]}
    from mockymock.report.html_report import render_html

    html = render_html(report)
    assert '<span class="value">79.9%</span>' in html
    assert '<span class="value">80%</span>' not in html


def test_an_incomplete_mutation_score_neither_passes_nor_earns_l2(ordrproc):
    """Issue #347: mutants the Docker toolchain failed under are left out
    of the score, so a high score over the rest must not pass the
    threshold or read as complete."""
    path = _write(
        ordrproc / "mutation.json",
        {
            "score": 1.0,
            "complete": False,
            "totals": {
                "generated": 10,
                "killed": 9,
                "timeouts": 0,
                "survived": 0,
                "errors": 1,
            },
            "mutants": [],
        },
    )
    report = build_report(
        _options(
            ordrproc,
            run_json=_run_json(ordrproc),
            coverage_json=_coverage_json(ordrproc),
            mutation_json=path,
        )
    )
    step = _step(report, "mutation")
    assert step["status"] == "warn"
    assert "INCOMPLETE: 1 mutant(s) could not be evaluated" in step["summary"]
    assert {c["level"] for c in report["cases"]} <= {"L0", "L1"}
    assert report["summary"]["mutationUnevaluated"] == 1
    from mockymock.report.html_report import render_html

    assert "incomplete: 1 mutant not evaluated" in render_html(report)


def test_a_run_that_never_compiled_fails_the_run_step(ordrproc):
    """Issue #260: `run` records a failure before any case started (a
    compile error) as a synthetic "mockymock run" case. The report dropped
    it, marked the run step ok and raised no finding."""
    path = _write(
        ordrproc / "run.json",
        {
            "version": 1,
            "cases": [
                {
                    "name": "mockymock run",
                    "line": None,
                    "status": "failed",
                    "failures": [
                        {
                            "message": "X.cbl: in paragraph 'P':\n"
                            "X.cbl:47: error: 'WS-CAPX' is not defined\n"
                        }
                    ],
                },
                {
                    "name": "10% discount reduces net amount correctly",
                    "line": 3,
                    "status": "not_run",
                    "failures": [],
                },
                {
                    "name": "Zero discount leaves amount unchanged",
                    "line": 16,
                    "status": "not_run",
                    "failures": [],
                },
            ],
            "orphanFailures": [],
            "summary": {"testsRun": 1, "casesFailed": 1, "casesCrashed": 0},
        },
    )
    report = build_report(_options(ordrproc, run_json=path))
    step = _step(report, "run")
    assert step["status"] == "fail"
    assert "'WS-CAPX' is not defined" in step["summary"]
    assert report["summary"]["runFailed"] is True
    run_failures = [f for f in report["findings"] if f["category"] == "run-failure"]
    assert len(run_failures) == 1
    assert run_failures[0]["severity"] == "high"
    assert "WS-CAPX" in run_failures[0]["detail"]


def test_a_normal_run_is_not_a_run_failure(ordrproc):
    report = build_report(_options(ordrproc, run_json=_run_json(ordrproc)))
    assert _step(report, "run")["status"] == "ok"
    assert report["summary"]["runFailed"] is False


# -- reuse of saved run/mutate results (issue #352) --------------------------


def _save(ordrproc, kind, path):
    from mockymock.report.artifacts import save_result

    save_result(
        ordrproc / "ORDRPROC.cut",
        ordrproc / "ORDRPROC.cbl",
        kind,
        path.read_text(encoding="utf-8"),
        [],
    )


def _never_run(monkeypatch):
    import mockymock.report.test_report as test_report

    def boom(args, timeout):
        raise AssertionError(f"re-ran {args[0]}")

    monkeypatch.setattr(test_report, "_run_cli", boom)


def test_execute_and_mutate_reuse_saved_results(ordrproc, monkeypatch):
    _save(ordrproc, "run", _run_json(ordrproc))
    _save(ordrproc, "coverage", _coverage_json(ordrproc))
    _save(ordrproc, "mutation", _mutation_json(ordrproc))
    _never_run(monkeypatch)
    report = build_report(
        _options(ordrproc, execute=True, mutate=True, probe_toolchain=False)
    )
    run = _step(report, "run")
    assert "Reused the saved result of `mockymock run`" in run["summary"]
    assert run["status"] == "ok"
    assert report["summary"]["coverage"] == pytest.approx(83.33)
    assert "Reused the saved result of `mockymock mutate`" in (
        _step(report, "mutation")["summary"]
    )
    assert [c["level"] for c in report["cases"]] == ["L3", "L3"]


def test_a_saved_run_without_coverage_says_so(ordrproc, monkeypatch):
    _save(ordrproc, "run", _run_json(ordrproc))
    _never_run(monkeypatch)
    report = build_report(_options(ordrproc, execute=True, probe_toolchain=False))
    coverage = _step(report, "coverage")
    assert coverage["status"] == "skipped"
    assert "was not a --coverage run" in coverage["summary"]


def test_a_changed_suite_or_program_is_run_again(ordrproc, monkeypatch):
    from mockymock.report.artifacts import fresh_result

    _save(ordrproc, "run", _run_json(ordrproc))
    cut, program = ordrproc / "ORDRPROC.cut", ordrproc / "ORDRPROC.cbl"
    assert fresh_result(cut, program, "run", []) is not None
    cut.write_text(LABELLED_CUT + "\n", encoding="utf-8")
    assert fresh_result(cut, program, "run", []) is None
    _save(ordrproc, "run", _run_json(ordrproc))
    program.write_text(program.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    assert fresh_result(cut, program, "run", []) is None


def test_a_changed_copybook_directory_is_run_again(ordrproc):
    from mockymock.report.artifacts import fresh_result, save_result

    books = ordrproc / "copybooks"
    books.mkdir()
    (books / "A.cpy").write_text("01 A PIC X.\n", encoding="utf-8")
    cut, program = ordrproc / "ORDRPROC.cut", ordrproc / "ORDRPROC.cbl"
    save_result(cut, program, "run", "{}", [str(books)])
    assert fresh_result(cut, program, "run", [str(books)]) is not None
    (books / "A.cpy").write_text("01 A PIC XX.\n", encoding="utf-8")
    assert fresh_result(cut, program, "run", [str(books)]) is None


def test_rerun_ignores_saved_results(ordrproc, monkeypatch):
    import mockymock.report.test_report as test_report

    _save(ordrproc, "run", _run_json(ordrproc))
    calls: list[str] = []

    def fake(args, timeout):
        calls.append(args[0])
        return 1, "no docker"

    monkeypatch.setattr(test_report, "_run_cli", fake)
    build_report(_options(ordrproc, execute=True, reuse=False, probe_toolchain=False))
    assert calls == ["run"]


def test_orphan_labels_are_named_in_the_inventory(ordrproc):
    """Issue #346: a label covering nothing is reported with its line."""
    (ordrproc / "ORDRPROC.cut").write_text(
        LABELLED_CUT + "    *> INTENT: after the last assertion\n",
        encoding="utf-8",
    )
    inventory = _step(build_report(_options(ordrproc)), "inventory")
    assert inventory["status"] == "warn"
    assert "1 INTENT/CHARACTERIZATION label(s) cover no assertion" in (
        inventory["summary"]
    )
    assert inventory["details"]["orphanLabels"][0]["line"] == 23
