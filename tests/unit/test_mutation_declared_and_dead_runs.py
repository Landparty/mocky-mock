"""Follow-ups to #347 and #349 from the field-run plan.

* A run cut off by the toolchain while the container is up again
  afterwards -- restarted by another --jobs worker, or a binary the
  out-of-memory killer SIGKILLed -- is a toolchain fault, never a kill.
* A suite's `<stem>.equivalent.json` declares mutants a person has
  reviewed as equivalent: never built, reported, left out of the score,
  and an entry that matches nothing is reported rather than ignored."""

from __future__ import annotations

import json
from types import SimpleNamespace

import mockymock.mutation.runner as runner
from mockymock.mutation.declared import (
    DECLARED_PREFIX,
    declared_equivalents_path,
    load_declarations,
    match_declarations,
)
from mockymock.mutation.operators import Mutant
from mockymock.mutation.report import MutantResult, MutationOutcome, format_console
from mockymock.mutation.runner import SuiteRun
from mockymock.report.artifacts import fingerprint
from mockymock.runtime import docker_toolchain


def _execution(exit_code: int, stderr: str = ""):
    return SimpleNamespace(exit_code=exit_code, stderr=stderr, stdout="")


def _no_docker_fault(monkeypatch, identity="abc 2026-10-25T00:00:00Z"):
    monkeypatch.setattr(docker_toolchain, "toolchain_failure", lambda: None)
    monkeypatch.setattr(docker_toolchain, "container_identity", lambda: identity)


def test_a_container_restarted_mid_run_is_a_toolchain_fault(monkeypatch):
    _no_docker_fault(monkeypatch, identity="def 2026-10-25T00:00:09Z")
    fault = runner._run_fault(_execution(1), "abc 2026-10-25T00:00:00Z", 2.0, 15)
    assert fault is not None and "restarted during the run" in fault


def test_an_early_sigkill_is_a_toolchain_fault(monkeypatch):
    _no_docker_fault(monkeypatch)
    fault = runner._run_fault(_execution(137), "abc 2026-10-25T00:00:00Z", 2.0, 15)
    assert fault is not None
    assert "exit 137" in fault and "--jobs 1" in fault


def test_a_sigkill_past_the_deadline_is_left_to_the_timeout_check(monkeypatch):
    _no_docker_fault(monkeypatch)
    assert runner._run_fault(_execution(137), "abc 2026-10-25T00:00:00Z", 20.5, 15) is (
        None
    )


def test_an_ordinary_crash_in_a_steady_container_is_the_programs(monkeypatch):
    _no_docker_fault(monkeypatch)
    assert runner._run_fault(_execution(1), "abc 2026-10-25T00:00:00Z", 2.0, 15) is (
        None
    )


def test_incomplete_score_points_at_memory_for_an_oom_kill():
    mutant = Mutant(5, "move-literal", "x", "y", "d")
    outcome = MutationOutcome(program="P.cbl", cut="P.cut")
    outcome.results = [
        MutantResult(mutant=mutant, status="killed"),
        MutantResult(
            mutant=mutant,
            status="error",
            detail="toolchain failure: binary killed by SIGKILL (exit 137) ...",
        ),
    ]
    assert "re-run with --jobs 1" in format_console(outcome)


def _mutants():
    return [
        Mutant(
            212,
            "arith-verb-swap",
            "000212     ADD 1 TO WS-RETRY-COUNT                                     ",
            "000212     SUBTRACT 1 FROM WS-RETRY-COUNT                              ",
            "ADD -> SUBTRACT",
        ),
        Mutant(
            300,
            "rel-op",
            "           IF WS-A > WS-B",
            "           IF WS-A >= WS-B",
            "> -> >=",
        ),
        Mutant(
            300,
            "rel-op",
            "           IF WS-A > WS-B",
            "           IF WS-A < WS-B",
            "> -> <",
        ),
    ]


def _write(tmp_path, entries) -> object:
    cut = tmp_path / "P.cut"
    cut.write_text('TESTSUITE "s"\n')
    declared_equivalents_path(cut).write_text(json.dumps({"equivalent": entries}))
    return cut


def test_a_declaration_names_its_mutant_by_statement_text(tmp_path):
    cut = _write(
        tmp_path,
        [
            {
                "operator": "arith-verb-swap",
                "original": "add 1 to ws-retry-count.",
                "reason": "always 0 here",
            }
        ],
    )
    declarations, notes = load_declarations(declared_equivalents_path(cut))
    assert notes == []
    matched, stale = match_declarations(_mutants(), declarations)
    assert matched == {0: "always 0 here"} and stale == []


def test_a_moved_statement_keeps_its_declaration(tmp_path):
    cut = _write(
        tmp_path,
        [
            {
                "operator": "arith-verb-swap",
                "original": "ADD 1 TO WS-RETRY-COUNT",
                "line": 198,
                "reason": "r",
            }
        ],
    )
    matched, stale = match_declarations(
        _mutants(), load_declarations(declared_equivalents_path(cut))[0]
    )
    assert matched == {0: "r"} and stale == []


def test_mutated_narrows_to_one_mutation_on_the_line(tmp_path):
    cut = _write(
        tmp_path,
        [
            {
                "operator": "rel-op",
                "line": 300,
                "mutated": "IF WS-A >= WS-B",
                "reason": "r",
            }
        ],
    )
    matched, _ = match_declarations(
        _mutants(), load_declarations(declared_equivalents_path(cut))[0]
    )
    assert matched == {1: "r"}


def test_entries_without_a_reason_or_a_target_are_ignored_and_said(tmp_path):
    cut = _write(
        tmp_path,
        [
            {"operator": "rel-op", "line": 300},
            {"operator": "rel-op", "reason": "no target"},
            "not an object",
        ],
    )
    declarations, notes = load_declarations(declared_equivalents_path(cut))
    assert declarations == []
    assert [n.split(": ", 1)[1].split(" ")[0] for n in notes] == [
        "no",
        "needs",
        "not",
    ]


def test_a_stale_entry_is_reported(tmp_path):
    cut = _write(
        tmp_path,
        [{"operator": "stmt-delete", "original": "MOVE 1 TO WS-GONE", "reason": "r"}],
    )
    matched, stale = match_declarations(
        _mutants(), load_declarations(declared_equivalents_path(cut))[0]
    )
    assert matched == {}
    assert "matches no generated mutant" in stale[0]


def test_unreadable_file_is_reported_not_fatal(tmp_path):
    cut = tmp_path / "P.cut"
    declared_equivalents_path(cut).write_text("{not json")
    declarations, notes = load_declarations(declared_equivalents_path(cut))
    assert declarations == [] and "not read" in notes[0]


def test_declared_mutants_are_never_built_and_not_scored(monkeypatch, tmp_path):
    program = tmp_path / "P.cbl"
    program.write_text("\n".join(["x"] * 400) + "\n")
    cut = _write(
        tmp_path,
        [
            {"operator": "rel-op", "line": 300, "reason": "both directions agree"},
            {"operator": "stmt-delete", "line": 1, "reason": "stale"},
        ],
    )
    monkeypatch.setattr(docker_toolchain, "ensure_toolchain", lambda: None)
    monkeypatch.setattr(runner, "generate_mutants", lambda source: _mutants())
    built: list[str] = []

    def fake(source_text, *args, **kwargs):
        built.append(source_text)
        return SuiteRun("passed", "")

    monkeypatch.setattr(runner, "_run_suite_once", fake)
    problems, outcome, notes = runner.run_mutation(
        program, cut, None, coverage_gate=False
    )
    assert problems == [] and outcome is not None
    assert [r.status for r in outcome.results] == [
        "survived",
        "equivalent",
        "equivalent",
    ]
    assert outcome.results[1].detail == DECLARED_PREFIX + "both directions agree"
    # Baseline + the one undeclared mutant.
    assert len(built) == 2
    assert outcome.score == 0.0
    assert any("matches no generated mutant" in n for n in notes)


def test_the_declarations_are_part_of_the_reuse_fingerprint(tmp_path):
    program = tmp_path / "P.cbl"
    program.write_text("x\n")
    cut = tmp_path / "P.cut"
    cut.write_text('TESTSUITE "s"\n')
    before = fingerprint(program, cut, None)
    declared_equivalents_path(cut).write_text('{"equivalent": []}')
    assert fingerprint(program, cut, None) != before
