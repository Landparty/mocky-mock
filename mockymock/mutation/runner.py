"""The mutation kill loop: baseline run, then patch/splice/compile/run per
mutant, classifying each as killed / survived / stillborn / timeout.

Serial in v1, one full pipeline pass per mutant -- correctness over
throughput (see docs/2026-07-29-mutation-testing-design.md for the
coverage-filtering and mutant-schemata upgrade path). The per-mutant
pipeline is deliberately the same sequence `_cmd_run` performs, rebuilt
from the same building blocks against a patched copy of the source, so a
mutant's verdict can never diverge from what `mockymock run` would say
about that same mutated program.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from mockymock.mutation.operators import Mutant, generate_mutants
from mockymock.mutation.report import MutantResult, MutationOutcome


def _run_suite_once(
    source_text: str,
    source_name: str,
    cut_path: Path,
    copybook_paths: list[str] | None,
    timeout_seconds: int,
) -> tuple[str, str, list[str]]:
    """Run one full splice/compile/run pass over `source_text` and reduce
    it to a (status, detail, notes) triple with status in {"passed",
    "failed", "stillborn", "timeout"}. `detail` carries the first refusal/
    compile/failure line for diagnostics. `notes` is
    `StaticCheckResult.notes` (e.g. a paragraph-scoped PARSE_WARNING/
    UNRESOLVED_COPYBOOK waived and, for a waived COPY, commented out of
    the source this pass goes on to compile) -- empty whenever
    `checked.problems` was non-empty, since the pipeline never reaches
    that gate in that case. The caller must not discard this: staying
    silent about a waiver here would mean `mockymock mutate` compiles
    doctored source with no visible sign of it, breaking the same
    transparency guarantee `run`/`debug`/`export`/`lint` keep."""
    from mockymock.analysis.flow_mocks import find_flow_mock_plans
    from mockymock.analysis.refusal import find_terminator_plans
    from mockymock.cli.checks import run_static_checks
    from mockymock.cli.main import _insert_driver
    from mockymock.report.results import parse_stdout
    from mockymock.runtime import docker_toolchain
    from mockymock.runtime.executor import TIMEOUT_EXIT_CODE
    from mockymock.runtime.sandbox import sandbox_dir_maybe_kept
    from mockymock.splicer.driver import build_driver
    from mockymock.splicer.linkage import extra_reset_lines
    from mockymock.splicer.naming import TallyRegistry
    from mockymock.splicer.orchestrator import splice_program
    from mockymock.splicer.reset import reset_move_lines
    from mockymock.splicer.source_map import collect_boundaries
    from mockymock.splicer.sqlca import transform_data_division_exec

    with sandbox_dir_maybe_kept(root=docker_toolchain.WORK_ROOT, keep=False) as tmp:
        source_path = tmp / source_name
        source_path.write_text(source_text, encoding="utf-8", newline="\n")

        checked = run_static_checks(source_path, cut_path, copybook_paths)
        if checked.problems:
            return "stillborn", checked.problems[0], []
        notes = checked.notes

        result = checked.parse_result
        suite = checked.suite
        surface = checked.surface
        lines = checked.lines
        scope_map = checked.scope_map
        assert (
            result is not None
            and suite is not None
            and surface is not None
            and lines is not None
            and scope_map is not None
        )  # implied by checked.problems being empty

        boundaries = collect_boundaries(result.ast)
        registry = TallyRegistry(suite)
        terminator_plans, _ = find_terminator_plans(
            surface, result.ast, suite, scope_map, lines
        )
        flow_plans, _ = find_flow_mock_plans(result.ast, suite, lines)
        lines = splice_program(
            lines,
            boundaries,
            surface,
            suite,
            registry,
            terminator_plans,
            flow_plans,
            checked.file_status_fields,
            trace=False,
        )
        lines, _ = transform_data_division_exec(lines, copybook_paths=copybook_paths)

        reset_lines = reset_move_lines(result.ast)
        if checked.linkage is not None:
            reset_lines = reset_lines + extra_reset_lines(checked.linkage)
        artifact = build_driver(suite, reset_lines, registry)
        instrumented = _insert_driver(lines, artifact)

        instrumented_path = tmp / f"instrumented_{source_name}"
        instrumented_path.write_text(
            "\n".join(instrumented) + "\n", encoding="utf-8", newline="\n"
        )
        compiled = docker_toolchain.compile_source(instrumented_path)
        if not compiled.success:
            first_error = (compiled.stderr or compiled.stdout).strip().splitlines()
            return (
                "stillborn",
                first_error[0] if first_error else "compile failed",
                notes,
            )
        assert compiled.binary_path is not None  # implied by compiled.success

        execution = docker_toolchain.run_binary(
            compiled.binary_path, timeout_seconds=timeout_seconds
        )
        if execution.exit_code == TIMEOUT_EXIT_CODE:
            return "timeout", f"no exit within {timeout_seconds}s", notes
        suite_result = parse_stdout(execution.stdout)
        status, detail = _classify_execution(execution, suite_result)
        return status, detail, notes


def _classify_execution(execution, suite_result) -> tuple[str, str]:
    """Reduces one execution's exit code + parsed stdout to a (status,
    detail) pair. Split out of _run_suite_once so this decision --
    notably which anomaly explains all_passed being False when no
    individual case reports a failure or crash -- is testable without a
    real compile/run."""
    if execution.exit_code == 0 and suite_result.all_passed:
        return "passed", ""
    for case in suite_result.results:
        if case.failure_reasons:
            return "failed", case.failure_reasons[0]
        if case.crashed:
            return "failed", f"case {case.case_name!r} crashed"
    # all_passed is False but no individual case explains why: name the
    # actual anomaly rather than a misleading "binary exited 0" when the
    # exit code, in fact, was 0 (audit finding F28).
    if suite_result.duplicate_case_starts:
        return "failed", "duplicate CASE START markers in the run"
    if suite_result.orphan_failures:
        return "failed", "a CASE FAIL had no matching CASE START"
    if suite_result.tests_run == 0:
        return "failed", "no test cases reported running"
    if suite_result.failures:
        return (
            "failed",
            f"SUMMARY reported {suite_result.failures} failure(s) with no "
            f"attributable case",
        )
    return "failed", f"binary exited {execution.exit_code}"


def run_mutation(
    source_path: Path,
    cut_path: Path,
    copybook_paths: list[str] | None,
    timeout_seconds: int = 15,
    on_progress: Callable[[MutantResult], None] | None = None,
) -> tuple[list[str], MutationOutcome | None, list[str]]:
    """Baseline-check the suite, then run every generated mutant.

    Returns (problems, outcome, notes): non-empty `problems` means the run
    never got to scoring (Docker down, red/empty baseline, no mutants) and
    `outcome` is None. `on_progress` is called once per classified mutant,
    in order, for live console reporting. `notes` is the union, in first-
    seen order, of every `StaticCheckResult.notes` produced along the way
    (baseline and every mutant) -- a paragraph-scoped PARSE_WARNING/
    UNRESOLVED_COPYBOOK waived somewhere in the run. The caller must
    print these: `_run_suite_once`'s docstring explains why staying
    silent here would break this repo's transparency guarantee for a
    waiver, and a waived COPY is compiled with its line commented out, not
    just skipped over."""
    from mockymock.runtime import docker_toolchain

    try:
        docker_toolchain.ensure_toolchain()
    except docker_toolchain.DockerNotAvailableError as exc:
        return [str(exc)], None, []

    all_notes: list[str] = []

    def _merge_notes(notes: list[str]) -> None:
        for note in notes:
            if note not in all_notes:
                all_notes.append(note)

    original_text = source_path.read_text(encoding="utf-8")
    status, detail, baseline_notes = _run_suite_once(
        original_text, source_path.name, cut_path, copybook_paths, timeout_seconds
    )
    _merge_notes(baseline_notes)
    if status != "passed":
        return (
            [
                f"baseline run is not green ({status}"
                + (f": {detail}" if detail else "")
                + ") -- mutation scoring is only meaningful against a passing "
                "suite; fix the suite first"
            ],
            None,
            all_notes,
        )

    original_lines = original_text.splitlines()
    mutants = generate_mutants(original_lines)
    if not mutants:
        return (
            [
                "no mutable statements found (every PROCEDURE DIVISION line is "
                "a boundary/terminator statement or matched no operator)"
            ],
            None,
            all_notes,
        )

    outcome = MutationOutcome(program=str(source_path), cut=str(cut_path))
    for mutant in mutants:
        result, mutant_notes = _run_one_mutant(
            mutant,
            original_lines,
            source_path.name,
            cut_path,
            copybook_paths,
            timeout_seconds,
        )
        outcome.results.append(result)
        _merge_notes(mutant_notes)
        if on_progress is not None:
            on_progress(outcome.results[-1])
    return [], outcome, all_notes


def _run_one_mutant(
    mutant: Mutant,
    original_lines: list[str],
    source_name: str,
    cut_path: Path,
    copybook_paths: list[str] | None,
    timeout_seconds: int,
) -> tuple[MutantResult, list[str]]:
    """Same (result, notes) shape as _run_suite_once, since a mutation can
    in principle change which paragraphs are reachable (a stmt-delete
    mutant can remove a statement other statements' reachability doesn't
    otherwise depend on) -- notes are therefore collected per mutant, not
    assumed stable from the baseline."""
    patched = list(original_lines)
    patched[mutant.line - 1] = mutant.mutated
    status, detail, notes = _run_suite_once(
        "\n".join(patched) + "\n",
        source_name,
        cut_path,
        copybook_paths,
        timeout_seconds,
    )
    if status == "passed":
        return MutantResult(mutant=mutant, status="survived"), notes
    if status == "failed":
        return MutantResult(mutant=mutant, status="killed", detail=detail), notes
    if status == "timeout":
        return MutantResult(mutant=mutant, status="timeout", detail=detail), notes
    return MutantResult(mutant=mutant, status="stillborn", detail=detail), notes
