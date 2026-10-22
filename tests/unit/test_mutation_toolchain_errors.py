"""Issue #347: a mutant the Docker toolchain failed under (the container
died mid-run) must never be scored. It is retried once after a restart,
then reported as `error`, left out of the score, and `mutate` exits
non-zero on the incomplete score whatever --fail-under says."""

from __future__ import annotations

import json

import mockymock.mutation.runner as runner
from mockymock.mutation.operators import Mutant
from mockymock.mutation.report import (
    MutantResult,
    MutationOutcome,
    format_console,
    to_json_dict,
)
from mockymock.mutation.runner import SuiteRun
from mockymock.report.results import parse_stdout
from mockymock.runtime import docker_toolchain
from mockymock.runtime.executor import ExecutionResult


def _mutant(line: int) -> Mutant:
    return Mutant(
        line=line,
        operator="move-literal",
        original="    MOVE 1 TO WS-X.",
        mutated="    MOVE 2 TO WS-X.",
        description=f"MOVE literal on line {line}",
    )


def _program(tmp_path):
    program = tmp_path / "P.cbl"
    program.write_text("\n".join(["x"] * 40) + "\n")
    cut = tmp_path / "P.cut"
    cut.write_text('TESTSUITE "s"\n')
    return program, cut


def _drive(monkeypatch, tmp_path, verdicts, *, restarts=None):
    """run_mutation over one mutant per line in `verdicts`: a green
    baseline, then each mutant's scripted SuiteRun sequence (one entry per
    attempt). Returns the outcome and how many restarts were asked for."""
    restarted: list[int] = []

    def ensure() -> None:
        restarted.append(1)
        if restarts is not None and len(restarted) > 1 and not restarts:
            raise docker_toolchain.DockerNotAvailableError("daemon gone")

    monkeypatch.setattr(docker_toolchain, "ensure_toolchain", ensure)
    lines = list(verdicts)
    monkeypatch.setattr(
        runner, "generate_mutants", lambda source: [_mutant(n) for n in lines]
    )
    scripts = {n: list(seq) for n, seq in verdicts.items()}

    def fake(source_text, source_name, cut_path, copybook_paths, timeout, **kw):
        for n, seq in scripts.items():
            if "MOVE 2" in source_text.splitlines()[n - 1]:
                return seq.pop(0)
        return SuiteRun("passed", "")

    monkeypatch.setattr(runner, "_run_suite_once", fake)
    program, cut = _program(tmp_path)
    problems, outcome, _ = runner.run_mutation(program, cut, None, coverage_gate=False)
    assert problems == []
    assert outcome is not None
    # The first ensure_toolchain call is run_mutation's own up-front check.
    return outcome, len(restarted) - 1


ERROR = SuiteRun("error", "toolchain failure: container mockymock-cobc stopped")


def test_errored_mutant_is_retried_once_after_a_restart(monkeypatch, tmp_path):
    outcome, restarts = _drive(
        monkeypatch, tmp_path, {5: [ERROR, SuiteRun("failed", "expected 1")]}
    )
    assert restarts == 1
    assert [r.status for r in outcome.results] == ["killed"]
    assert outcome.complete


def test_a_mutant_that_errors_twice_is_reported_not_scored(monkeypatch, tmp_path):
    outcome, _ = _drive(
        monkeypatch,
        tmp_path,
        {
            5: [SuiteRun("failed", "expected 1")],
            6: [SuiteRun("passed", "")],
            7: [ERROR, ERROR],
        },
    )
    assert [r.status for r in outcome.results] == ["killed", "survived", "error"]
    assert outcome.errors == 1
    assert not outcome.complete
    # The score covers the two mutants that were tested, not three.
    assert outcome.score == 0.5
    assert outcome.survived == 1


def test_no_retry_when_the_toolchain_cannot_be_restarted(monkeypatch, tmp_path):
    outcome, _ = _drive(monkeypatch, tmp_path, {5: [ERROR]}, restarts=False)
    assert [r.status for r in outcome.results] == ["error"]


def test_console_and_json_say_the_score_is_incomplete():
    outcome = MutationOutcome(program="P.cbl", cut="P.cut")
    outcome.results = [
        MutantResult(mutant=_mutant(5), status="killed"),
        MutantResult(mutant=_mutant(6), status="error", detail=ERROR.detail),
    ]
    text = format_console(outcome)
    assert "1 not evaluated" in text
    assert "INCOMPLETE" in text
    assert "container mockymock-cobc stopped" in text
    data = to_json_dict(outcome)
    assert data["complete"] is False
    assert data["totals"]["errors"] == 1
    json.dumps(data)


def test_complete_outcome_reports_no_errors():
    outcome = MutationOutcome(program="P.cbl", cut="P.cut")
    outcome.results = [MutantResult(mutant=_mutant(5), status="killed")]
    assert "INCOMPLETE" not in format_console(outcome)
    assert to_json_dict(outcome)["complete"] is True


def test_baseline_toolchain_failure_is_not_blamed_on_the_suite(monkeypatch, tmp_path):
    monkeypatch.setattr(docker_toolchain, "ensure_toolchain", lambda: None)
    monkeypatch.setattr(runner, "generate_mutants", lambda source: [_mutant(5)])
    monkeypatch.setattr(runner, "_run_suite_once", lambda *a, **k: ERROR)
    program, cut = _program(tmp_path)
    problems, outcome, _ = runner.run_mutation(program, cut, None)
    assert outcome is None
    assert "Docker toolchain failed, not the suite" in problems[0]


# -- what counts as a toolchain fault ---------------------------------------


def test_docker_cli_error_text_is_a_fault_without_asking_the_container(
    monkeypatch,
):
    monkeypatch.setattr(
        docker_toolchain,
        "toolchain_failure",
        lambda: (_ for _ in ()).throw(AssertionError),
    )
    fault = runner._toolchain_fault(
        "Error response from daemon: container abc is not running\n"
    )
    assert fault == (
        "toolchain failure: Error response from daemon: container abc is not running"
    )


def test_a_stopped_container_is_a_fault(monkeypatch):
    monkeypatch.setattr(
        docker_toolchain, "_inspect_container", lambda timeout=30: (False, "img")
    )
    assert runner._toolchain_fault("") == (
        "toolchain failure: container mockymock-cobc stopped"
    )


def test_a_running_container_is_not_a_fault(monkeypatch):
    monkeypatch.setattr(
        docker_toolchain, "_inspect_container", lambda timeout=30: (True, "img")
    )
    assert runner._toolchain_fault("cobc: error: something") is None


def test_a_vanished_container_or_daemon_is_a_fault(monkeypatch):
    monkeypatch.setattr(docker_toolchain, "_inspect_container", lambda timeout=30: None)
    assert "no longer exists" in docker_toolchain.toolchain_failure()

    def down(timeout=30):
        raise docker_toolchain.DockerNotAvailableError("Docker is required\nmore")

    monkeypatch.setattr(docker_toolchain, "_inspect_container", down)
    assert docker_toolchain.toolchain_failure() == "Docker is required"


def test_an_assertion_failure_is_the_programs_own_verdict():
    stdout = (
        "__MOCKYMOCK__ TESTSUITE: s\n"
        "__MOCKYMOCK__ CASE 001 START: c\n"
        "__MOCKYMOCK__ CASE 001 FAIL: expected WS-X = 1, got 9\n"
        "__MOCKYMOCK__ CASE 001 END\n"
        "__MOCKYMOCK__ SUMMARY: RUN=1 FAILURES=1\n"
    )
    execution = ExecutionResult(exit_code=1, stdout=stdout, stderr="")
    assert runner._verdict_is_the_programs(execution, parse_stdout(stdout))


def test_a_crash_or_empty_run_is_checked_against_the_toolchain():
    crashed = "__MOCKYMOCK__ TESTSUITE: s\n__MOCKYMOCK__ CASE 001 START: c\n"
    for stdout, code in ((crashed, 137), ("", 1), ("", 124)):
        execution = ExecutionResult(exit_code=code, stdout=stdout, stderr="")
        assert not runner._verdict_is_the_programs(execution, parse_stdout(stdout))
