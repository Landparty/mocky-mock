"""Notes propagation through the mutation kill loop (mockymock.mutation.runner).

`run_static_checks`' `StaticCheckResult.notes` -- a paragraph-scoped
PARSE_WARNING/UNRESOLVED_COPYBOOK waived rather than refused (see
mockymock/analysis/refusal.py's module docstring) -- must never go silent.
`run`/`debug`/`export`/`lint` all print it; `mockymock mutate` reaches the
same `run_static_checks` gate once per baseline/mutant via
`_run_suite_once`, and a waived COPY is compiled with its line commented
out regardless of whether the caller is watching. These tests exercise the
threading/aggregation logic in `run_mutation`/`_run_one_mutant` directly
(monkeypatching `_run_suite_once` and the Docker toolchain check) rather
than a real compile+run, which needs a live Docker daemon this suite does
not assume.

`docker_toolchain` is imported locally inside `_run_suite_once`/
`run_mutation`, not at this module's top level (runner.py has no
docker-free constraint like cli/checks.py, but the deferred-import habit
carries over) -- `from X import Y` still binds to the one shared module
object in `sys.modules`, so patching the attribute on the real
`mockymock.runtime.docker_toolchain` module (not on `runner`, which never
gets a module-level `docker_toolchain` name) is what actually takes
effect at call time.
"""

from __future__ import annotations

from pathlib import Path

import mockymock.mutation.runner as runner
from mockymock.mutation.operators import Mutant
from mockymock.runtime import docker_toolchain


def _fake_docker(monkeypatch) -> None:
    monkeypatch.setattr(docker_toolchain, "ensure_toolchain", lambda: None)


def _mutant(line: int = 5) -> Mutant:
    return Mutant(
        line=line,
        operator="move-literal",
        original="    MOVE 1 TO WS-X.",
        mutated="    MOVE 2 TO WS-X.",
        description="MOVE literal changed",
    )


def test_baseline_notes_are_returned_even_with_no_mutants(monkeypatch, tmp_path):
    """A green baseline that waived a scoped warning must surface that
    note even when the program has nothing left to mutate -- the compile
    already happened on doctored source by that point."""
    _fake_docker(monkeypatch)
    calls: list[str] = []

    def fake_run_suite_once(
        source_text, source_name, cut_path, copybook_paths, timeout
    ):
        calls.append(source_text)
        return "passed", "", ["parse warning waived: ..."]

    monkeypatch.setattr(runner, "_run_suite_once", fake_run_suite_once)
    monkeypatch.setattr(runner, "generate_mutants", lambda lines: [])

    program = tmp_path / "P.cbl"
    program.write_text("DISPLAY 1.\n")
    cut = tmp_path / "P.cut"
    cut.write_text('TESTSUITE "s"\n')

    problems, outcome, notes = runner.run_mutation(program, cut, None)
    assert outcome is None  # "no mutable statements" short-circuits
    assert problems  # the no-mutants problem
    assert notes == ["parse warning waived: ..."]
    assert len(calls) == 1  # only the baseline ran


def test_baseline_not_green_still_surfaces_its_notes(monkeypatch, tmp_path):
    _fake_docker(monkeypatch)

    def fake_run_suite_once(
        source_text, source_name, cut_path, copybook_paths, timeout
    ):
        return "failed", "case 'x' failed", ["unresolved COPY statement waived: ..."]

    monkeypatch.setattr(runner, "_run_suite_once", fake_run_suite_once)

    program = tmp_path / "P.cbl"
    program.write_text("DISPLAY 1.\n")
    cut = tmp_path / "P.cut"
    cut.write_text('TESTSUITE "s"\n')

    problems, outcome, notes = runner.run_mutation(program, cut, None)
    assert outcome is None
    assert any("baseline run is not green" in p for p in problems)
    assert notes == ["unresolved COPY statement waived: ..."]


def test_notes_from_baseline_and_every_mutant_are_merged_and_deduped(
    monkeypatch, tmp_path
):
    _fake_docker(monkeypatch)
    monkeypatch.setattr(
        runner, "generate_mutants", lambda lines: [_mutant(5), _mutant(6)]
    )

    # (status _run_suite_once would actually return, detail, notes) per
    # call: baseline first, then one per mutant in order.
    responses = iter(
        [
            ("passed", "", ["waived: dropped content in DIRTY-PARA"]),  # baseline
            ("passed", "", ["waived: dropped content in DIRTY-PARA"]),  # mutant 1
            ("failed", "boom", ["waived: unresolved COPY in OTHER-PARA"]),  # mutant 2
        ]
    )

    def fake_run_suite_once(
        source_text, source_name, cut_path, copybook_paths, timeout
    ):
        return next(responses)

    monkeypatch.setattr(runner, "_run_suite_once", fake_run_suite_once)

    program = tmp_path / "P.cbl"
    program.write_text("\n".join(["x"] * 10) + "\n")
    cut = tmp_path / "P.cut"
    cut.write_text('TESTSUITE "s"\n')

    problems, outcome, notes = runner.run_mutation(program, cut, None)
    assert problems == []
    assert outcome is not None
    assert len(outcome.results) == 2
    assert outcome.results[0].status == "survived"  # mutant 1: "passed" -> survived
    assert outcome.results[1].status == "killed"  # mutant 2: "failed" -> killed
    # Deduped: the baseline's note and mutant 1's identical note collapse
    # into one entry; mutant 2's distinct note is appended after it.
    assert notes == [
        "waived: dropped content in DIRTY-PARA",
        "waived: unresolved COPY in OTHER-PARA",
    ]


def test_docker_unavailable_returns_no_notes(monkeypatch):
    def raise_unavailable():
        raise docker_toolchain.DockerNotAvailableError("no docker")

    monkeypatch.setattr(docker_toolchain, "ensure_toolchain", raise_unavailable)

    problems, outcome, notes = runner.run_mutation(
        Path("unused.cbl"), Path("unused.cut"), None
    )
    assert outcome is None
    assert problems == ["no docker"]
    assert notes == []
