"""The mutation kill loop: baseline run, then patch/splice/compile/run per
mutant, classifying each as killed / survived / stillborn / timeout, or
error when the Docker toolchain failed under it, or equivalent when it
provably cannot change the program (neither is scored).

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
import time
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
from mockymock.report.record_rewrite import numeric_edited_fields


@dataclass(frozen=True)
class SuiteRun:
    """One full splice/compile/run pass reduced to a verdict.

    `status` is one of "passed" / "failed" / "stillborn" / "timeout" /
    "error" -- the last meaning the toolchain failed under the pass (the
    container died, the daemon went away), so it says nothing about the
    program or the suite (issue #347);
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
    #: Every case the run reported, in order.
    case_names: tuple[str, ...] = ()
    #: The cases that failed, set only when the run is still scorable
    #: without them: every one of them failed an EXPECT/VERIFY and ran to
    #: its END, and at least one other case passed. A baseline like that
    #: is scored against its passing cases (see `run_mutation`).
    failing_cases: tuple[str, ...] = ()


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
    excluded_cases: tuple[str, ...] = (),
    expected_cases: tuple[str, ...] = (),
) -> SuiteRun:
    """Run one full splice/compile/run pass over `source_text` and reduce
    it to a `SuiteRun`.

    `collect_coverage` additionally compiles with GnuCOBOL's `--coverage`
    and runs gcov afterwards, remapping the result onto `source_text`'s own
    line numbers. A gcov pass that produces nothing is not an error -- the
    verdict stands and `coverage` is left None, with the reason appended to
    `notes` so a silently-ungated run is never mistaken for a gated one.

    `excluded_cases` are the baseline's failing cases: a pass whose only
    failures are in them, and which reported every one of
    `expected_cases`, is "passed".
    """
    from mockymock.analysis.flow_mocks import find_flow_mock_plans
    from mockymock.analysis.refusal import (
        find_goto_exit_plans,
        find_terminator_plans,
        needs_call_frame,
        program_end_thru,
    )
    from mockymock.cli._common import _insert_driver
    from mockymock.cli.checks import (
        REAL_CALL_UNSUPPORTED,
        extra_reset_lines_for,
        extra_working_storage,
        run_static_checks,
    )
    from mockymock.report.coverage import map_coverage_to_original, parse_gcov
    from mockymock.report.results import parse_stdout
    from mockymock.runtime.executor import TIMEOUT_EXIT_CODE
    from mockymock.runtime.sandbox import sandbox_dir_maybe_kept
    from mockymock.runtime.toolchain import active as active_toolchain
    from mockymock.splicer import cics_eib
    from mockymock.splicer.driver import build_driver
    from mockymock.splicer.linkage import extra_reset_lines
    from mockymock.splicer.naming import TallyRegistry
    from mockymock.splicer.orchestrator import splice_program
    from mockymock.splicer.reset import reset_move_lines
    from mockymock.splicer.source_map import collect_boundaries
    from mockymock.splicer.sqlca import sqlca_reset_lines, transform_data_division_exec

    toolchain = active_toolchain()

    with sandbox_dir_maybe_kept(root=toolchain.WORK_ROOT, keep=False) as tmp:
        source_path = tmp / source_name
        source_path.write_text(source_text, encoding="utf-8", newline="\n")

        checked = run_static_checks(source_path, cut_path, copybook_paths)
        if checked.problems:
            return SuiteRun("stillborn", checked.problems[0], phase="checks")
        if checked.real_programs:
            return SuiteRun("stillborn", REAL_CALL_UNSUPPORTED, phase="checks")
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
            fallthrough_traps=checked.fallthrough_traps,
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
            numeric_edited=numeric_edited_fields(result.ast, checked.captures),
            program_end=program_end_thru(result.ast, terminator_plans),
            call_frame=needs_call_frame(terminator_plans),
        )
        instrumented = _insert_driver(lines, artifact)

        instrumented_path = tmp / f"instrumented_{source_name}"
        instrumented_path.write_text(
            "\n".join(instrumented) + "\n", encoding="utf-8", newline="\n"
        )
        identity = toolchain.container_identity()
        compiled = toolchain.compile_source(
            instrumented_path, coverage=collect_coverage
        )
        if not compiled.success:
            fault = _toolchain_fault(compiled.stderr or "")
            if fault is not None:
                return SuiteRun("error", fault, notes, phase="compile")
            return SuiteRun(
                "stillborn",
                _compile_error_detail(compiled.stderr or compiled.stdout),
                notes,
                phase="compile",
            )
        assert compiled.binary_path is not None  # implied by compiled.success

        started = time.monotonic()
        execution = toolchain.run_binary(
            compiled.binary_path, timeout_seconds=timeout_seconds
        )
        elapsed = time.monotonic() - started
        suite_result = parse_stdout(execution.stdout)
        if not _verdict_is_the_programs(execution, suite_result):
            fault = _run_fault(execution, identity, elapsed, timeout_seconds)
            if fault is not None:
                return SuiteRun("error", fault, notes)
        if execution.exit_code == TIMEOUT_EXIT_CODE or (
            execution.exit_code == SIGKILL_EXIT_CODE
            and not _verdict_is_the_programs(execution, suite_result)
        ):
            # 137 past the deadline is `timeout -k` escalating to SIGKILL
            # on a binary that ignored the SIGTERM: still a timeout (the
            # early 137 was ruled out by _run_fault above).
            return SuiteRun("timeout", f"no exit within {timeout_seconds}s", notes)
        status, detail = _classify_execution(execution, suite_result)
        if status == "failed" and excluded_cases:
            status, detail = _classify_without(
                suite_result, excluded_cases, expected_cases
            )
        failing = _cleanly_failing_cases(suite_result) if status == "failed" else ()
        case_names = tuple(case.case_name for case in suite_result.results)

        coverage: dict[int, bool] | None = None
        if collect_coverage and (status == "passed" or failing):
            # Must run while the sandbox still exists: gcov reads the
            # .gcda the binary wrote next to itself.
            gcov = toolchain.run_gcov(instrumented_path)
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
        return SuiteRun(
            status,
            detail,
            notes,
            coverage,
            case_names=case_names,
            failing_cases=failing,
        )


def _cleanly_failing_cases(suite_result) -> tuple[str, ...]:
    """The failing cases of a run that can still be scored without them,
    or () when it cannot: a case crashed (the cases after it never ran),
    the output has anomalies, or nothing passed at all."""
    results = suite_result.results
    if (
        not results
        or suite_result.orphan_failures
        or suite_result.duplicate_case_starts
        or suite_result.tests_run != len(results)
        or any(case.crashed for case in results)
        or all(not case.passed for case in results)
    ):
        return ()
    return tuple(case.case_name for case in results if not case.passed)


def _classify_without(
    suite_result, excluded: tuple[str, ...], expected: tuple[str, ...]
) -> tuple[str, str]:
    """(status, detail) of a mutant's run with the baseline's failing
    cases left out. Killed only by a case that passed in the baseline;
    a run that stopped short of the baseline's cases (a crash took the
    rest with it) is killed too."""
    if tuple(case.case_name for case in suite_result.results) != expected:
        return "failed", "the run did not report every case the baseline did"
    if suite_result.duplicate_case_starts:
        return "failed", "duplicate CASE START markers in the run"
    if suite_result.orphan_failures:
        return "failed", "a CASE FAIL had no matching CASE START"
    for case in suite_result.results:
        if case.case_name in excluded:
            continue
        if case.failure_reasons:
            return "failed", case.failure_reasons[0]
        if case.crashed:
            return "failed", f"case {case.case_name!r} crashed"
    return "passed", ""


def _restart_toolchain() -> bool:
    """Bring the toolchain container back up after a failure; whether it
    is up. Safe from several worker processes at once -- ensure_toolchain
    already settles the races on `docker run --name`."""
    from mockymock.runtime.toolchain import active as active_toolchain

    toolchain = active_toolchain()

    try:
        toolchain.ensure_toolchain()
    except toolchain.ToolchainNotAvailableError:
        return False
    return True


def _verdict_is_the_programs(execution, suite_result) -> bool:
    """Whether a run's outcome is certainly the program's own: a clean
    green run, or a case that reported an assertion failure. Anything else
    -- a crash, a timeout, no case output, a bare non-zero exit -- is also
    exactly what a container dying mid-run looks like, so the caller asks
    the toolchain before believing it."""
    if execution.exit_code == 0 and suite_result.all_passed:
        return True
    return any(case.failure_reasons for case in suite_result.results)


#: A process killed by SIGKILL (128 + 9): the kernel's out-of-memory
#: killer inside the container's `--memory 1g`, or `timeout -k`
#: escalating once the deadline has passed.
SIGKILL_EXIT_CODE = 137


def _run_fault(
    execution, identity_before: str | None, elapsed: float, timeout_seconds: int
) -> str | None:
    """Why a run with no verdict of the program's own was the toolchain's
    doing, or None. Asked only when `_verdict_is_the_programs` said no.

    Two causes leave the container up afterwards, so `_toolchain_fault`
    alone scored them as kills: another worker restarted the container
    mid-run (its identity changed), or the binary was SIGKILLed before its
    deadline, which in a container nothing else signals means the
    out-of-memory killer. Scored, either one moves the mutation score by a
    number that is Docker's, not the suite's."""
    from mockymock.runtime.toolchain import active as active_toolchain

    toolchain = active_toolchain()

    fault = _toolchain_fault(execution.stderr)
    if fault is not None:
        return fault
    if identity_before is not None:
        now = toolchain.container_identity()
        if now is not None and now != identity_before:
            return (
                f"toolchain failure: container {toolchain.CONTAINER} "
                "was restarted during the run"
            )
    if execution.exit_code == SIGKILL_EXIT_CODE and elapsed < timeout_seconds:
        return (
            "toolchain failure: binary killed by SIGKILL (exit 137) before its "
            "timeout -- most likely the container's 1 GB memory limit; "
            "re-run with --jobs 1"
        )
    return None


def _toolchain_fault(stderr: str) -> str | None:
    """Why a compile or run failed because of the toolchain rather than the
    COBOL, or None when the toolchain is fine. The docker CLI's own error
    text is the direct evidence; failing that, the container is asked
    whether it is still up, since a binary killed by the container going
    away leaves no message of its own."""
    from mockymock.runtime.toolchain import active as active_toolchain

    toolchain = active_toolchain()

    line = toolchain.docker_failure_line(stderr)
    if line is None:
        line = toolchain.toolchain_failure()
    return None if line is None else f"toolchain failure: {line}"


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
    `runtime/toolchain.py`'s hardening flags)."""
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
    from mockymock.runtime.toolchain import active as active_toolchain

    toolchain = active_toolchain()

    try:
        toolchain.ensure_toolchain()
    except toolchain.ToolchainNotAvailableError as exc:
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
    if baseline.status == "error":
        return (
            [
                f"the baseline run could not be evaluated ({baseline.detail}) "
                "-- the Docker toolchain failed, not the suite; check Docker "
                "and re-run"
            ],
            None,
            all_notes,
        )
    from mockymock.cli.checks import REAL_CALL_UNSUPPORTED

    if baseline.phase == "checks" and baseline.detail == REAL_CALL_UNSUPPORTED:
        # Not a red suite: mutate cannot link USE REAL CALL programs yet.
        # Saying "baseline is not green ... fix the suite first" sent people
        # to fix a suite that passes (cobol-test run on PAYMAIN, 2026-11-06).
        return ([REAL_CALL_UNSUPPORTED], None, all_notes)
    excluded: tuple[str, ...] = ()
    if baseline.status == "failed" and baseline.failing_cases:
        # A suite with a known-failing case is still worth scoring: the
        # cases that pass are tested against every mutant, and only they
        # can kill one. Leaving the whole suite unscored for one red case
        # is what the field run hit (RECFMT, 2026-10-25).
        excluded = baseline.failing_cases
        _merge_notes(
            [
                f"scored without {len(excluded)} case(s) that fail on the "
                "unmutated program: "
                + ", ".join(repr(name) for name in excluded)
                + " -- only the other "
                + f"{len(baseline.case_names) - len(excluded)} case(s) can "
                "kill a mutant"
            ]
        )
    elif baseline.status != "passed":
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
    # Provably equivalent mutants (issue #349) are never built: no test can
    # kill them, so they are reported, with why, and left out of the score.
    decided = _equivalent_mutants(
        mutants, original_lines, source_path, cut_path, copybook_paths
    )
    decided.update(_declared_equivalents(mutants, cut_path, decided, _merge_notes))
    decided.update(
        {
            index: MutantResult(
                mutant=mutant,
                status="survived",
                detail=NOT_COMPILED_DETAIL,
                ran=False,
            )
            for index, mutant in enumerate(mutants)
            if index not in decided
            and coverage is not None
            and coverage.get(mutant.line) is False
        }
    )
    to_run = [(index, m) for index, m in enumerate(mutants) if index not in decided]

    outcome = MutationOutcome(
        program=str(source_path), cut=str(cut_path), excluded_cases=list(excluded)
    )
    try:
        ran = _run_mutants(
            [mutant for _, mutant in to_run],
            original_lines,
            source_path.name,
            cut_path,
            copybook_paths,
            timeout_seconds,
            jobs,
            excluded,
            baseline.case_names if excluded else (),
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


def _equivalent_mutants(
    mutants: list[Mutant],
    original_lines: list[str],
    source_path: Path,
    cut_path: Path,
    copybook_paths: list[str] | None,
) -> dict[int, MutantResult]:
    """Index -> `equivalent` result for every mutant
    `equivalence.equivalence_reason` proves cannot change the program.
    Best effort: when the static pass that supplies the data-item facts
    fails, every mutant is built and scored as before."""
    candidates = [
        (index, m)
        for index, m in enumerate(mutants)
        if m.operator in ("stmt-delete", "arith-verb-swap")
    ]
    if not candidates:
        return {}
    from mockymock.cli.checks import run_static_checks
    from mockymock.mutation.equivalence import equivalence_reason

    try:
        checked = run_static_checks(source_path, cut_path, copybook_paths)
    except Exception:  # noqa: BLE001 -- no facts, no proof
        return {}
    if checked.parse_result is None:
        return {}
    decided: dict[int, MutantResult] = {}
    for index, mutant in candidates:
        reason = equivalence_reason(mutant, original_lines, checked.parse_result.ast)
        if reason:
            decided[index] = MutantResult(
                mutant=mutant, status="equivalent", detail=reason, ran=False
            )
    return decided


def _declared_equivalents(
    mutants: list[Mutant],
    cut_path: Path,
    decided: dict[int, MutantResult],
    report: Callable[[list[str]], None],
) -> dict[int, MutantResult]:
    """Index -> `equivalent` result for every mutant the suite's
    `<stem>.equivalent.json` declares (see `mutation.declared`) that the
    static proof has not already decided. Every ignored or stale entry is
    passed to `report` as a note."""
    from mockymock.mutation.declared import (
        DECLARED_PREFIX,
        declared_equivalents_path,
        load_declarations,
        match_declarations,
    )

    declarations, notes = load_declarations(declared_equivalents_path(cut_path))
    matched, stale = match_declarations(mutants, declarations)
    report(notes + stale)
    return {
        index: MutantResult(
            mutant=mutants[index],
            status="equivalent",
            detail=DECLARED_PREFIX + reason,
            ran=False,
        )
        for index, reason in matched.items()
        if index not in decided
    }


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
    excluded_cases: tuple[str, ...] = (),
    expected_cases: tuple[str, ...] = (),
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
                excluded_cases,
                expected_cases,
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
            excluded_cases,
            expected_cases,
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
    excluded_cases: tuple[str, ...] = (),
    expected_cases: tuple[str, ...] = (),
) -> None:
    _WORKER_ARGS.update(
        excluded_cases=excluded_cases,
        expected_cases=expected_cases,
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
        _WORKER_ARGS["excluded_cases"],  # type: ignore[arg-type]
        _WORKER_ARGS["expected_cases"],  # type: ignore[arg-type]
    )


def _run_one_mutant(
    mutant: Mutant,
    original_lines: list[str],
    source_name: str,
    cut_path: Path,
    copybook_paths: list[str] | None,
    timeout_seconds: int,
    excluded_cases: tuple[str, ...] = (),
    expected_cases: tuple[str, ...] = (),
) -> tuple[MutantResult, list[str]]:
    """Same (result, notes) shape as _run_suite_once, since a mutation can
    in principle change which paragraphs are reachable (a stmt-delete
    mutant can remove a statement other statements' reachability doesn't
    otherwise depend on) -- notes are therefore collected per mutant, not
    assumed stable from the baseline."""
    patched = list(original_lines)
    patched[mutant.line - 1] = mutant.mutated
    patched_text = "\n".join(patched) + "\n"
    run = _run_suite_once(
        patched_text,
        source_name,
        cut_path,
        copybook_paths,
        timeout_seconds,
        excluded_cases=excluded_cases,
        expected_cases=expected_cases,
    )
    if run.status == "error" and _restart_toolchain():
        # One retry once the container is back: a container that died
        # once in a long run should cost that mutant a re-run, not its
        # verdict.
        run = _run_suite_once(
            patched_text,
            source_name,
            cut_path,
            copybook_paths,
            timeout_seconds,
            excluded_cases=excluded_cases,
            expected_cases=expected_cases,
        )
    if run.status == "error":
        # Never scored as anything: a mutant the toolchain failed under was
        # not tested, and calling it a survivor (or a kill) would move the
        # score by a number that is the container's, not the suite's.
        return MutantResult(mutant=mutant, status="error", detail=run.detail), (
            run.notes
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
