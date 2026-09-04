"""The two cost levers in `mockymock.mutation.runner`: the coverage gate
and the parallel worker pool (docs/2026-07-29-mutation-testing-design.md's
deferred items 1 and 3).

Both are tested the same way `test_mutation_notes.py` tests the kill loop
-- by monkeypatching `_run_suite_once` and the Docker toolchain check --
since a real splice/compile/run needs a live Docker daemon this suite
does not assume. What that leaves untested is the cross-process execution
itself; `test_worker_arguments_survive_pickling` covers the one failure
mode that would surface only there.
"""

from __future__ import annotations

import pickle

import mockymock.mutation.runner as runner
from mockymock.mutation.operators import Mutant
from mockymock.mutation.report import MutantResult, format_console, to_json_dict
from mockymock.mutation.runner import SuiteRun
from mockymock.runtime import docker_toolchain


def _fake_docker(monkeypatch) -> None:
    monkeypatch.setattr(docker_toolchain, "ensure_toolchain", lambda: None)


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


def _run(monkeypatch, tmp_path, lines, baseline, **kwargs):
    """Drive run_mutation with one mutant per line in `lines`, a scripted
    baseline, and every mutant that does get built coming back green.
    Returns (outcome, list of source_texts _run_suite_once saw)."""
    _fake_docker(monkeypatch)
    monkeypatch.setattr(
        runner, "generate_mutants", lambda source: [_mutant(n) for n in lines]
    )
    seen: list[str] = []
    first = True

    def fake_run_suite_once(
        source_text, source_name, cut_path, copybook_paths, timeout, **kw
    ):
        nonlocal first
        seen.append(source_text)
        if first:
            first = False
            return baseline
        return SuiteRun("passed", "")

    monkeypatch.setattr(runner, "_run_suite_once", fake_run_suite_once)
    program, cut = _program(tmp_path)
    problems, outcome, _ = runner.run_mutation(program, cut, None, **kwargs)
    assert problems == []
    assert outcome is not None
    return outcome, seen


# --- the coverage gate -------------------------------------------------


def test_uncovered_line_is_a_survivor_without_being_built(monkeypatch, tmp_path):
    """A line the whole suite never executes cannot change what any case
    observes, so `survived` is already the answer -- building the mutant
    to confirm it is the work this gate skips."""
    outcome, seen = _run(
        monkeypatch,
        tmp_path,
        [5, 6],
        SuiteRun("passed", "", coverage={5: True, 6: False}),
    )
    assert [(r.mutant.line, r.status, r.ran) for r in outcome.results] == [
        (5, "survived", True),
        (6, "survived", False),
    ]
    assert len(seen) == 2  # baseline + the covered mutant only
    assert outcome.not_compiled == 1


def test_an_unmappable_line_is_always_built(monkeypatch, tmp_path):
    """`map_coverage_to_original` omits lines it cannot place (driver
    insertions, boundary replacements, continuation merges). Absent means
    unknown, and unknown must never be read as uncovered."""
    outcome, seen = _run(
        monkeypatch, tmp_path, [5, 9], SuiteRun("passed", "", coverage={5: True})
    )
    assert [r.ran for r in outcome.results] == [True, True]
    assert len(seen) == 3
    assert outcome.not_compiled == 0


def test_no_coverage_at_all_builds_everything(monkeypatch, tmp_path):
    outcome, seen = _run(monkeypatch, tmp_path, [5, 6], SuiteRun("passed", ""))
    assert [r.ran for r in outcome.results] == [True, True]
    assert len(seen) == 3


def test_gate_can_be_turned_off(monkeypatch, tmp_path):
    outcome, seen = _run(
        monkeypatch,
        tmp_path,
        [5, 6],
        SuiteRun("passed", "", coverage={5: True, 6: False}),
        coverage_gate=False,
    )
    assert [r.ran for r in outcome.results] == [True, True]
    assert len(seen) == 3


def test_gated_survivors_are_scored_like_any_other(monkeypatch, tmp_path):
    """The gate changes how a verdict was reached, never what it is: an
    uncovered-line mutant is a survivor, and a survivor drags the score
    down whether or not a compiler was involved."""
    outcome, _ = _run(
        monkeypatch, tmp_path, [5, 6], SuiteRun("passed", "", coverage={6: False})
    )
    outcome.results[0] = MutantResult(mutant=_mutant(5), status="killed")
    assert outcome.score == 0.5
    assert "never executes" in format_console(outcome)
    payload = to_json_dict(outcome)
    assert payload["totals"]["not_compiled"] == 1
    assert [m["ran"] for m in payload["mutants"]] == [True, False]


# --- the baseline's own coverage build ---------------------------------


def test_a_coverage_only_compile_failure_is_re_run_plain(monkeypatch, tmp_path):
    """`--coverage` is a different compile from the one `mockymock run`
    performs. It must never be the reason a green suite is called red."""
    _fake_docker(monkeypatch)
    monkeypatch.setattr(runner, "generate_mutants", lambda source: [_mutant(5)])
    calls: list[bool] = []

    def fake_run_suite_once(
        source_text, source_name, cut_path, copybook_paths, timeout, **kw
    ):
        wanted_coverage = kw.get("collect_coverage", False)
        calls.append(wanted_coverage)
        if wanted_coverage:
            return SuiteRun("stillborn", "gcov: no such option", phase="compile")
        return SuiteRun("passed", "")

    monkeypatch.setattr(runner, "_run_suite_once", fake_run_suite_once)
    program, cut = _program(tmp_path)
    problems, outcome, notes = runner.run_mutation(program, cut, None)
    assert problems == []
    assert outcome is not None
    assert calls[:2] == [True, False]  # coverage baseline, then a plain one
    assert any("baseline coverage unavailable" in note for note in notes)


def test_a_red_suite_is_not_re_run_just_because_coverage_was_asked_for():
    """gcov instrumentation does not change what the COBOL computes, and a
    refusal-gate stop happens before any compiler runs at all. Re-running
    those would only double the wait for the commonest failure there is."""
    blame = runner._coverage_build_could_be_to_blame
    assert not blame(SuiteRun("failed", "case 'x' failed", phase="run"))
    assert not blame(SuiteRun("stillborn", "refused (X): ...", phase="checks"))
    assert not blame(SuiteRun("passed", ""))
    assert blame(SuiteRun("stillborn", "cc1: error", phase="compile"))
    assert blame(SuiteRun("timeout", "no exit within 15s", phase="run"))


# --- the worker pool ---------------------------------------------------


def test_results_keep_mutant_order_and_notes_stay_deterministic(monkeypatch, tmp_path):
    """Whatever order the workers finish in, results are consumed in
    submission order -- so the report, the progress stream and the notes
    union read the same as a serial run."""
    _fake_docker(monkeypatch)
    lines = [11, 12, 13, 14]
    monkeypatch.setattr(
        runner, "generate_mutants", lambda source: [_mutant(n) for n in lines]
    )
    first = True

    def fake_run_suite_once(
        source_text, source_name, cut_path, copybook_paths, timeout, **kw
    ):
        nonlocal first
        if first:
            first = False
            return SuiteRun("passed", "")
        # The mutated line is the one that differs from the "x" filler.
        line = next(
            i + 1 for i, text in enumerate(source_text.splitlines()) if text != "x"
        )
        return SuiteRun("failed", f"line {line} died", [f"note {line}"])

    monkeypatch.setattr(runner, "_run_suite_once", fake_run_suite_once)
    program, cut = _program(tmp_path)
    seen: list[int] = []
    problems, outcome, notes = runner.run_mutation(
        program, cut, None, on_progress=lambda r: seen.append(r.mutant.line)
    )
    assert problems == []
    assert outcome is not None
    assert [r.mutant.line for r in outcome.results] == lines
    assert [r.detail for r in outcome.results] == [f"line {n} died" for n in lines]
    assert seen == lines
    assert notes == [f"note {n}" for n in lines]


def test_a_gated_mutant_still_reaches_on_progress_in_order(monkeypatch, tmp_path):
    """The gate must not punch holes in the live progress stream."""
    _fake_docker(monkeypatch)
    seen: list[tuple[int, bool]] = []
    outcome, _ = _run(
        monkeypatch,
        tmp_path,
        [5, 6, 7],
        SuiteRun("passed", "", coverage={5: True, 6: False, 7: True}),
        on_progress=lambda r: seen.append((r.mutant.line, r.ran)),
    )
    assert seen == [(5, True), (6, False), (7, True)]


def test_serial_below_two_workers_or_two_mutants(monkeypatch):
    """The pool is never spun up when it cannot pay for itself."""
    started: list[int] = []
    monkeypatch.setattr(
        runner,
        "_run_one_mutant",
        lambda mutant, *a: (MutantResult(mutant=mutant, status="survived"), []),
    )

    class _Boom:
        def __init__(self, *a, **k):
            started.append(1)
            raise AssertionError("a pool was created")

    monkeypatch.setattr("concurrent.futures.ProcessPoolExecutor", _Boom)
    args = (["x"], "P.cbl", None, None, 15)
    assert len(runner._run_mutants([_mutant(1), _mutant(2)], *args, 1)) == 2
    assert len(runner._run_mutants([_mutant(1)], *args, 8)) == 1
    assert started == []


def test_worker_plumbing_round_trips_without_a_pool(monkeypatch):
    """`_init_worker`/`_run_one_mutant_in_worker` are what each worker
    process actually calls; exercise them in-process so a rename or an
    argument-order slip cannot hide behind the pool boundary."""
    monkeypatch.setattr(
        runner,
        "_run_suite_once",
        lambda text, name, cut, paths, timeout, **kw: SuiteRun(
            "failed", f"{name}:{timeout}"
        ),
    )
    runner._init_worker(["a", "b", "c"], "P.cbl", "P.cut", ["books"], 42)
    result, notes = runner._run_one_mutant_in_worker(_mutant(2))
    assert (result.status, result.detail, notes) == ("killed", "P.cbl:42", [])


def test_worker_arguments_survive_pickling():
    """Everything crossing the process boundary must pickle: the initargs
    on the way in, the (MutantResult, notes) pair on the way back. This is
    the one parallel-path failure that no in-process test can reach."""
    mutant = _mutant(7)
    assert pickle.loads(pickle.dumps(mutant)) == mutant
    payload = (MutantResult(mutant=mutant, status="killed", detail="x"), ["note"])
    assert pickle.loads(pickle.dumps(payload))[0].mutant == mutant


def test_a_broken_worker_pool_is_reported_not_raised(monkeypatch, tmp_path):
    _fake_docker(monkeypatch)
    monkeypatch.setattr(runner, "generate_mutants", lambda source: [_mutant(5)])
    monkeypatch.setattr(
        runner, "_run_suite_once", lambda *a, **k: SuiteRun("passed", "")
    )

    def boom(*args, **kwargs):
        raise OSError("worker died")

    monkeypatch.setattr(runner, "_run_mutants", boom)
    program, cut = _program(tmp_path)
    problems, outcome, _ = runner.run_mutation(program, cut, None, jobs=4)
    assert outcome is None
    assert any("--jobs 1" in p for p in problems)


def test_default_jobs_is_capped_by_the_containers_memory_not_the_core_count(
    monkeypatch,
):
    monkeypatch.setattr(runner.os, "cpu_count", lambda: 64)
    assert runner.default_jobs() == 4
    monkeypatch.setattr(runner.os, "cpu_count", lambda: 2)
    assert runner.default_jobs() == 2
    monkeypatch.setattr(runner.os, "cpu_count", lambda: None)
    assert runner.default_jobs() == 1
