"""The mutation kill loop: baseline run, then patch/splice/compile/run per
mutant, classifying each as killed / survived / stillborn / timeout.

Two cost levers sit on top of that loop, both from
docs/2026-07-29-mutation-testing-design.md's deferred list:

* **Coverage gating** (deferred item 1). The baseline is compiled with
  GnuCOBOL's `--coverage` and its gcov output is remapped onto the
  ORIGINAL source, so any mutant on a line the whole suite provably never
  executed is classified `survived` from that evidence alone, without a
  splice/compile/run of its own. That is not an approximation: a line no
  test case reaches cannot change what any test case observes.
* **Parallel workers** (deferred item 3, `jobs`). Each mutant already runs
  in its own sandbox under `WORK_ROOT`, and the per-mutant static-check
  pass is CPU-bound pure Python, so the work is spread across processes
  rather than threads. Results are consumed in submission order, so the
  report, the progress stream and the notes union stay byte-identical to a
  serial run.

What has not changed is the per-mutant pipeline itself: it is deliberately
the same sequence `_cmd_run` performs, rebuilt from the same building
blocks against a patched copy of the source, so a mutant's verdict can
never diverge from what `mockymock run` would say about that same mutated
program.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path

from mockymock._lines import read_utf8_source, split_source_lines
from mockymock.mutation.operators import Mutant, generate_mutants
from mockymock.mutation.report import (
    MutantResult,
    MutationOutcome,
    StillbornReason,
)


@dataclass(frozen=True)
class SuiteRun:
    """One full splice/compile/run pass reduced to a verdict.

    `status` is one of "passed" / "failed" / "stillborn" / "timeout";
    `detail` carries the first refusal/compile/failure line for
    diagnostics. `notes` is `StaticCheckResult.notes` (e.g. a
    paragraph-scoped PARSE_WARNING/UNRESOLVED_COPYBOOK waived and, for a
    waived COPY, commented out of the source this pass goes on to
    compile) -- empty whenever `checked.problems` was non-empty, since the
    pipeline never reaches that gate in that case. The caller must not
    discard this: staying silent about a waiver here would mean
    `mockymock mutate` compiles doctored source with no visible sign of
    it, breaking the same transparency guarantee `run`/`debug`/`export`/
    `lint` keep.

    `coverage` maps ORIGINAL 1-based line numbers to whether the run
    executed them; it is populated only when the caller asked for it and
    the gcov pass succeeded, and only covers lines that remap
    unambiguously (see `report.coverage.map_coverage_to_original`). A line
    absent from it is unknown, never "uncovered".

    `phase` says how far the pass got -- "checks" (the refusal gate
    stopped it, before any compiler ran), "compile", or "run". The public
    `stillborn` status deliberately covers the first two (a mutant that
    does not build says nothing about the suite either way); this field
    exists so callers can tell whether a *compiler* was even involved,
    which is what decides whether a `--coverage` build could have been to
    blame for the verdict.
    """

    status: str
    detail: str
    notes: list[str] = field(default_factory=list)
    coverage: dict[int, bool] | None = None
    phase: str = "run"


#: Detail recorded on a mutant the baseline's own coverage decided.
NOT_COMPILED_DETAIL = (
    "line never executed by the suite (baseline coverage); not compiled"
)


def _run_suite_once(
    source_text: str,
    source_name: str,
    cut_path: Path,
    copybook_paths: list[str] | None,
    timeout_seconds: int,
    *,
    collect_coverage: bool = False,
) -> SuiteRun:
    """Run one full splice/compile/run pass over `source_text` and reduce
    it to a `SuiteRun`.

    `collect_coverage` additionally compiles with GnuCOBOL's `--coverage`
    and runs gcov afterwards, remapping the result onto `source_text`'s own
    line numbers. A gcov pass that produces nothing is not an error -- the
    verdict stands and `coverage` is left None, with the reason appended to
    `notes` so a silently-ungated run is never mistaken for a gated one.
    """
    from mockymock.analysis.flow_mocks import find_flow_mock_plans
    from mockymock.analysis.refusal import find_goto_exit_plans, find_terminator_plans
    from mockymock.cli.checks import (
        extra_reset_lines_for,
        extra_working_storage,
        run_static_checks,
    )
    from mockymock.cli.main import _insert_driver
    from mockymock.report.coverage import map_coverage_to_original, parse_gcov
    from mockymock.report.results import parse_stdout
    from mockymock.runtime import docker_toolchain
    from mockymock.runtime.executor import TIMEOUT_EXIT_CODE
    from mockymock.runtime.sandbox import sandbox_dir_maybe_kept
    from mockymock.splicer import cics_eib
    from mockymock.splicer.driver import build_driver
    from mockymock.splicer.linkage import extra_reset_lines
    from mockymock.splicer.naming import TallyRegistry
    from mockymock.splicer.orchestrator import splice_program
    from mockymock.splicer.reset import reset_move_lines
    from mockymock.splicer.source_map import collect_boundaries
    from mockymock.splicer.sqlca import sqlca_reset_lines, transform_data_division_exec

    with sandbox_dir_maybe_kept(root=docker_toolchain.WORK_ROOT, keep=False) as tmp:
        source_path = tmp / source_name
        source_path.write_text(source_text, encoding="utf-8", newline="\n")

        checked = run_static_checks(source_path, cut_path, copybook_paths)
        if checked.problems:
            return SuiteRun("stillborn", checked.problems[0], phase="checks")
        notes = list(checked.notes)

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
        # The original-source coverage remap needs the pre-splice
        # normalized lines, exactly as `_cmd_run` keeps its own copy.
        normalized_lines = list(lines)

        boundaries = collect_boundaries(result.ast)
        registry = TallyRegistry(suite)
        terminator_plans, _ = find_terminator_plans(
            surface, result.ast, suite, scope_map, lines
        )
        goto_exit_plans, _ = find_goto_exit_plans(result.ast, scope_map, lines)
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
            goto_exit_plans=goto_exit_plans,
            trace=False,
        )
        lines, _ = transform_data_division_exec(lines, copybook_paths=copybook_paths)

        reset_lines = reset_move_lines(result.ast) + sqlca_reset_lines(lines)
        if checked.linkage is not None:
            reset_lines = reset_lines + extra_reset_lines(checked.linkage)
        if checked.cics_eib is not None:
            reset_lines = reset_lines + cics_eib.reset_lines(checked.cics_eib)
        # Synthesized CAPTURE targets need the same between-case reset the
        # run/debug/export pipelines give them. The suite compiles to ONE
        # binary here too, so without this a case that never reached its
        # CALL would assert against the previous case's captured value --
        # and a mutant could then be "killed" by that stale value rather
        # than by the mutation, silently inflating the score.
        reset_lines = reset_lines + extra_reset_lines_for(checked)
        artifact = build_driver(
            suite,
            reset_lines,
            registry,
            extra_working_storage_lines=extra_working_storage(checked),
            snapshot=checked.snapshot,
        )
        instrumented = _insert_driver(lines, artifact)

        instrumented_path = tmp / f"instrumented_{source_name}"
        instrumented_path.write_text(
            "\n".join(instrumented) + "\n", encoding="utf-8", newline="\n"
        )
        compiled = docker_toolchain.compile_source(
            instrumented_path, coverage=collect_coverage
        )
        if not compiled.success:
            return SuiteRun(
                "stillborn",
                _compile_error_detail(compiled.stderr or compiled.stdout),
                notes,
                phase="compile",
            )
        assert compiled.binary_path is not None  # implied by compiled.success

        execution = docker_toolchain.run_binary(
            compiled.binary_path, timeout_seconds=timeout_seconds
        )
        if execution.exit_code == TIMEOUT_EXIT_CODE:
            return SuiteRun("timeout", f"no exit within {timeout_seconds}s", notes)
        suite_result = parse_stdout(execution.stdout)
        status, detail = _classify_execution(execution, suite_result)

        coverage: dict[int, bool] | None = None
        if collect_coverage and status == "passed":
            # Must run while the sandbox still exists: gcov reads the
            # .gcda the binary wrote next to itself.
            gcov = docker_toolchain.run_gcov(instrumented_path)
            if gcov.success:
                coverage = {
                    entry.line: entry.covered
                    for entry in map_coverage_to_original(
                        parse_gcov(gcov.gcov_text),
                        instrumented,
                        normalized_lines,
                        split_source_lines(source_text),
                    )
                }
            else:
                notes.append(
                    "baseline coverage unavailable "
                    f"({gcov.stderr.strip() or 'gcov produced nothing'}) -- "
                    "every mutant will be compiled and run"
                )
        return SuiteRun(status, detail, notes, coverage)


def _compile_error_detail(output: str | None) -> str:
    """The line of cobc's output that says why a mutant did not compile.
    cobc opens with a `<sandbox path>: in paragraph 'X':` context line,
    which says nothing; the first `error:` line does, and its line number
    is the instrumented copy's, so only the message from `error:` on is
    kept."""
    lines = [line.strip() for line in (output or "").splitlines() if line.strip()]
    for line in lines:
        _, marker, message = line.partition(" error: ")
        if marker:
            return f"error: {message}"
    return lines[0] if lines else "compile failed"


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


def _coverage_build_could_be_to_blame(run: SuiteRun) -> bool:
    """Whether a not-green baseline might be an artifact of having asked
    for coverage, and so is worth one plain re-run before it is believed.

    Only two shapes qualify. A compile that failed under `--coverage`
    might well succeed without it. A run that timed out might have been
    the instrumented binary's own overhead. Everything else is the
    program's own verdict: a refusal-gate stop happens before any compiler
    is invoked at all, and a suite whose cases genuinely fail fails the
    same way either way -- gcov instrumentation does not change what the
    COBOL computes. Re-running those would only double the wait for the
    most common failure there is, a red suite."""
    if run.status == "passed":
        return False
    return run.phase == "compile" or run.status == "timeout"


def default_jobs() -> int:
    """A conservative parallel-worker count: never more than four, and
    never more than the machine has cores. The ceiling is not about CPUs
    -- it is the shared `mockymock-cobc` container's `--memory 1g`, which
    every concurrent `cobc` draws from at once (see
    `runtime/docker_toolchain.py`'s hardening flags)."""
    return max(1, min(4, os.cpu_count() or 1))


def run_mutation(
    source_path: Path,
    cut_path: Path,
    copybook_paths: list[str] | None,
    timeout_seconds: int = 15,
    on_progress: Callable[[MutantResult], None] | None = None,
    jobs: int = 1,
    coverage_gate: bool = True,
) -> tuple[list[str], MutationOutcome | None, list[str]]:
    """Baseline-check the suite, then run every generated mutant.

    Returns (problems, outcome, notes): non-empty `problems` means the run
    never got to scoring (Docker down, red/empty baseline, no mutants) and
    `outcome` is None. `on_progress` is called once per classified mutant,
    in mutant order, for live console reporting -- including the ones
    `coverage_gate` decided without running, so the stream never skips a
    line. `notes` is the union, in first-seen order, of every
    `StaticCheckResult.notes` produced along the way (baseline and every
    mutant) -- a paragraph-scoped PARSE_WARNING/UNRESOLVED_COPYBOOK waived
    somewhere in the run, plus a line explaining any baseline coverage the
    gate asked for and did not get. The caller must print these:
    `_run_suite_once`'s docstring explains why staying silent here would
    break this repo's transparency guarantee for a waiver, and a waived
    COPY is compiled with its line commented out, not just skipped over.

    `jobs` > 1 spreads the per-mutant pipeline across that many worker
    processes. `coverage_gate` compiles the baseline with `--coverage` and
    classifies any mutant on a provably unexecuted line as `survived`
    without building it.
    """
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

    original_text = read_utf8_source(source_path)
    baseline = _run_suite_once(
        original_text,
        source_path.name,
        cut_path,
        copybook_paths,
        timeout_seconds,
        collect_coverage=coverage_gate,
    )
    if coverage_gate and _coverage_build_could_be_to_blame(baseline):
        # A `--coverage` build is a different compile, and a slower
        # binary, than the one `mockymock run` performs, so it must never
        # be the reason a green suite is reported red. Re-run the baseline
        # exactly as `run` would before believing it.
        plain = _run_suite_once(
            original_text,
            source_path.name,
            cut_path,
            copybook_paths,
            timeout_seconds,
        )
        if plain.status == "passed":
            baseline = replace(
                plain,
                notes=[
                    *plain.notes,
                    "baseline coverage unavailable (the --coverage build did "
                    f"not come back green: {baseline.detail or baseline.status})"
                    " -- every mutant will be compiled and run",
                ],
            )
    _merge_notes(baseline.notes)
    if baseline.status != "passed":
        return (
            [
                f"baseline run is not green ({baseline.status}"
                + (f": {baseline.detail}" if baseline.detail else "")
                + ") -- mutation scoring is only meaningful against a passing "
                "suite; fix the suite first"
            ],
            None,
            all_notes,
        )

    original_lines = split_source_lines(original_text)
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

    # Belt and braces: `collect_coverage=False` already means no coverage
    # comes back, but the gate must be off because the caller turned it
    # off, not because a downstream detail happened to agree.
    coverage = baseline.coverage if coverage_gate else None
    # False, not falsy: a line absent from the map is unknown (it did not
    # remap unambiguously), and unknown must always be compiled.
    decided = {
        index: MutantResult(
            mutant=mutant, status="survived", detail=NOT_COMPILED_DETAIL, ran=False
        )
        for index, mutant in enumerate(mutants)
        if coverage is not None and coverage.get(mutant.line) is False
    }
    to_run = [(index, m) for index, m in enumerate(mutants) if index not in decided]

    outcome = MutationOutcome(program=str(source_path), cut=str(cut_path))
    try:
        ran = _run_mutants(
            [mutant for _, mutant in to_run],
            original_lines,
            source_path.name,
            cut_path,
            copybook_paths,
            timeout_seconds,
            jobs,
        )
    except Exception as exc:  # noqa: BLE001 -- worker pool failure, surfaced as-is
        return (
            [
                f"mutant workers failed ({exc}) -- retry with --jobs 1 to run "
                "the mutants one at a time"
            ],
            None,
            all_notes,
        )

    by_index = dict(decided)
    for (index, _), (result, notes) in zip(to_run, ran, strict=True):
        by_index[index] = result
        _merge_notes(notes)
    _attach_zero_baseline_hints(
        [r for r in by_index.values() if r.status == "survived" and r.ran],
        source_path,
        cut_path,
        copybook_paths,
    )
    for index in range(len(mutants)):
        outcome.results.append(by_index[index])
        if on_progress is not None:
            on_progress(outcome.results[-1])
    return [], outcome, all_notes


def _attach_zero_baseline_hints(
    survivors: list[MutantResult],
    source_path: Path,
    cut_path: Path,
    copybook_paths: list[str] | None,
) -> None:
    """Set `hint` on each survivor `zero_baseline_hint` explains. Survivors
    the baseline's coverage decided are left alone: they sit on lines no
    test reaches, and seeding a field would not change that. Best effort:
    a static-check pass that fails here just means no hints, never a
    different verdict."""
    candidates = [r for r in survivors if r.mutant.operator == "arith-verb-swap"]
    if not candidates:
        return
    from mockymock.cli.checks import run_static_checks
    from mockymock.mutation.zero_baseline import zero_baseline_hint

    try:
        checked = run_static_checks(source_path, cut_path, copybook_paths)
    except Exception:  # noqa: BLE001 -- hints are advisory
        return
    if checked.parse_result is None or checked.suite is None:
        return
    for result in candidates:
        result.hint = zero_baseline_hint(
            result.mutant,
            checked.parse_result.ast,
            checked.suite,
            checked.source_location_map,
        )


def _run_mutants(
    mutants: list[Mutant],
    original_lines: list[str],
    source_name: str,
    cut_path: Path,
    copybook_paths: list[str] | None,
    timeout_seconds: int,
    jobs: int,
) -> list[tuple[MutantResult, list[str]]]:
    """Run every mutant and return its (result, notes) pair in the same
    order. Serial below two workers or two mutants; otherwise one process
    per worker, consumed in submission order so the resulting report does
    not depend on which mutant happened to finish first."""
    if jobs <= 1 or len(mutants) <= 1:
        return [
            _run_one_mutant(
                mutant,
                original_lines,
                source_name,
                cut_path,
                copybook_paths,
                timeout_seconds,
            )
            for mutant in mutants
        ]

    from concurrent.futures import ProcessPoolExecutor

    # The source is passed once per worker through the initializer, not
    # once per task: on a large program pickling it per mutant would cost
    # more than the parallelism buys back.
    with ProcessPoolExecutor(
        max_workers=min(jobs, len(mutants)),
        initializer=_init_worker,
        initargs=(
            original_lines,
            source_name,
            cut_path,
            copybook_paths,
            timeout_seconds,
        ),
    ) as pool:
        return list(pool.map(_run_one_mutant_in_worker, mutants))


#: Per-worker-process copy of everything `_run_one_mutant` needs besides
#: the mutant itself, set once by the pool initializer.
_WORKER_ARGS: dict[str, object] = {}


def _init_worker(
    original_lines: list[str],
    source_name: str,
    cut_path: Path,
    copybook_paths: list[str] | None,
    timeout_seconds: int,
) -> None:
    _WORKER_ARGS.update(
        original_lines=original_lines,
        source_name=source_name,
        cut_path=cut_path,
        copybook_paths=copybook_paths,
        timeout_seconds=timeout_seconds,
    )


def _run_one_mutant_in_worker(mutant: Mutant) -> tuple[MutantResult, list[str]]:
    return _run_one_mutant(
        mutant,
        _WORKER_ARGS["original_lines"],  # type: ignore[arg-type]
        _WORKER_ARGS["source_name"],  # type: ignore[arg-type]
        _WORKER_ARGS["cut_path"],  # type: ignore[arg-type]
        _WORKER_ARGS["copybook_paths"],  # type: ignore[arg-type]
        _WORKER_ARGS["timeout_seconds"],  # type: ignore[arg-type]
    )


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
    run = _run_suite_once(
        "\n".join(patched) + "\n",
        source_name,
        cut_path,
        copybook_paths,
        timeout_seconds,
    )
    if run.status == "passed":
        return MutantResult(mutant=mutant, status="survived"), run.notes
    if run.status == "failed":
        return (
            MutantResult(mutant=mutant, status="killed", detail=run.detail),
            run.notes,
        )
    if run.status == "timeout":
        return (
            MutantResult(mutant=mutant, status="timeout", detail=run.detail),
            run.notes,
        )
    # `SuiteRun.phase` already distinguishes the two ways a mutant can be
    # stillborn ("checks" -- a static gate refused it before any compiler
    # ran; "compile" -- GnuCOBOL rejected it). Carrying it through is what
    # lets the report say WHICH, instead of a bare count that makes a line
    # whose every mutant failed to compile look like a line with no mutants.
    # Assigned as literals, not narrowed from `run.phase` (a plain `str`):
    # a membership test does not narrow to `StillbornReason` for a type
    # checker, and widening the field to `str` would give up the guarantee
    # that only these two values ever reach the report.
    reason: StillbornReason | None = None
    if run.phase == "checks":
        reason = "checks"
    elif run.phase == "compile":
        reason = "compile"
    return (
        MutantResult(
            mutant=mutant,
            status="stillborn",
            detail=run.detail,
            stillborn_reason=reason,
        ),
        run.notes,
    )
