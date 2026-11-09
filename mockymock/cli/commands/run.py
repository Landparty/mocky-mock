"""`mockymock run`: splice, compile and run a suite (or a directory of
suites), with the crash-isolation reruns, baseline and coverage reports."""

from __future__ import annotations

import argparse
import os
import re
import shutil
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType

from mockymock._lines import read_utf8_source, split_source_lines
from mockymock.cli._args import _percent, _timeout_seconds
from mockymock.cli._common import (
    _apply_config_to_args,
    _layout,
    _print_cics_eib_synthesis,
    _print_linkage_neutralization,
    _report_broken_claims,
    _resolve_program_and_cut,
    _save_result,
    _several_suites,
    _write_report_file,
)
from mockymock.engine.build import BuildOptions, build_instrumented
from mockymock.report.artifacts import fingerprint


def _write_failure_reports(
    args: argparse.Namespace,
    command: str,
    suite_name: str,
    reason: str,
    *,
    cut_suite=None,
    cut_file: Path | None = None,
    program_file: Path | None = None,
) -> None:
    """Write `run`'s --junit-xml/--json-report for an exit that never
    produced a TestSuiteResult at all -- a static refusal or a compile
    failure. Without this, those two exit paths returned 1 with nothing
    written, so a CI pipeline that always publishes whatever the configured
    report path holds (the common pattern) saw "no test results found"
    instead of a visible failure -- worse than a failing test, since it can
    read as "nothing ran" rather than "something failed" (carried-over open
    item from the 2026-08-10 framework audit). Reuses the ordinary
    formatters via one synthetic TestResult standing in for the whole run,
    rather than a bespoke report shape only this path would exercise.

    `cut_suite`/`cut_file`/`program_file`, when known, go into the JSON
    report so an editor can still place the failure (issue #204): without
    them `cutFile`, `programFile` and the suite line were all null."""
    if not args.junit_xml and not args.json_report:
        return

    from mockymock.report.formatters import format_junit_xml
    from mockymock.report.json_report import build_json_report, format_json_report
    from mockymock.report.results import TestResult, TestSuiteResult

    suite_result = TestSuiteResult(
        suite_name=suite_name,
        results=[
            TestResult(
                case_id="0",
                case_name=f"mockymock {command}",
                failure_reasons=[reason],
                ended=True,
            )
        ],
        tests_run=1,
        failures=1,
    )
    if args.junit_xml:
        _write_report_file(
            command, "--junit-xml", args.junit_xml, format_junit_xml(suite_result)
        )
    if args.json_report:
        _write_report_file(
            command,
            "--json-report",
            args.json_report,
            format_json_report(
                build_json_report(
                    suite_result,
                    cut_suite=cut_suite,
                    cut_file=str(cut_file) if cut_file is not None else None,
                    program_file=(
                        str(program_file) if program_file is not None else None
                    ),
                )
            ),
        )


def _hint_pending_stubs(cut_text: str, suite, suite_result, risky: list[str]) -> None:
    """Point a risky case that still holds `*> STUB EXPECT` comments (the
    ones `generate` writes for what a program returns) at the run that
    turns them into EXPECTs: those cases are risky only because nobody ran
    it yet."""
    from mockymock.analysis.stub_expectations import scan_stub_expectations

    try:
        scan = scan_stub_expectations(cut_text, suite)
    except Exception:  # noqa: BLE001 -- a hint, never a failure
        return
    stubbed = {f"{stub.case_index:03d}" for stub in scan.stubs}
    pending = [
        result.case_name
        for result in suite_result.results
        if result.case_id in risky and result.case_id in stubbed
    ]
    if pending:
        print(
            f"mockymock run: {len(pending)} risky case(s) still hold "
            "`*> STUB EXPECT` comments -- re-run with --record-expectations "
            "to turn them into EXPECTs, then check the values recorded: "
            + ", ".join(repr(name) for name in pending)
        )


def _per_pair_report_path(base: str, cut_path: Path, test_root: Path) -> str:
    """Insert the .cut file's path (relative to `test_root`, separators
    folded to '-') before the extension: 'report.xml' + 'ORDRPROC.cut'
    -> 'report-ORDRPROC.xml'; 'svc1/ORDRPROC.cut' -> 'report-svc1-
    ORDRPROC.xml'. Used so directory-mode output files don't have every
    discovered pair overwrite the same single file -- the relative path,
    not just the stem, because two suites with the same stem in
    different directories (a monorepo's svc1/PROG.cut and svc2/PROG.cut)
    are exactly the case a per-pair name exists to keep apart."""
    base_path = Path(base)
    try:
        relative = cut_path.relative_to(test_root)
    except ValueError:
        try:
            relative = cut_path.resolve().relative_to(test_root.resolve())
        except ValueError:
            relative = Path(cut_path.name)
    tag = "-".join(relative.with_suffix("").parts)
    return str(base_path.with_name(f"{base_path.stem}-{tag}{base_path.suffix}"))


def _report_tag_root(cut_files: list[Path], test_root: Path) -> Path:
    """What `_per_pair_report_path` names each suite's report relative to:
    the test root when every suite lies under it (directory mode), else
    the deepest folder holding all of them. `run PROG.cbl` with several
    suites gets them from `find_suites` -- a sibling `src/pay/PROG.cut`
    beside `tests/pay/PROG.cut`, or suites in different folders that name
    PROG with a PROGRAM line -- which need not lie under the test root;
    naming those by file name alone gave two of them one report file, and
    the second suite's report silently replaced the first's."""

    def under(path: Path) -> bool:
        try:
            path.relative_to(test_root)
            return True
        except ValueError:
            return False

    if all(under(path) for path in cut_files):
        return test_root
    return Path(os.path.commonpath([str(p.resolve().parent) for p in cut_files]))


# Every `run` flag naming an output file: each gets a per-pair name in
# directory mode, or the second suite silently overwrites the first's.
_RUN_OUTPUT_PATH_FLAGS = (
    "junit_xml",
    "json_report",
    "coverage_json",
    "coverage_out",
    "trace_json",
    "branch_coverage",
)


def _run_directory(
    args: argparse.Namespace, cut_files: list[Path] | None = None
) -> int:
    """`mockymock run` with neither a program nor --cut given: discover
    every .cut file under the test root (the config file's own
    test_root, default '.') and run each against its sibling program.
    Reuses _cmd_run's own single-pair code path unchanged, via a shallow
    copy of args with program/cut filled in, rather than a parallel
    implementation -- so a plain `mockymock run PROG.cbl --cut PROG.cut`
    invocation is completely untouched by this function ever existing.
    See docs/2026-09-15-cli-ergonomics-design.md."""
    import copy

    from mockymock.project.discovery import (
        DiscoveryError,
        discover_cut_files,
        read_program_line,
        resolve_program_path,
    )

    config = getattr(args, "_config", None)
    test_root = Path((config.test_root if config else None) or ".")
    layout = _layout(args)
    if cut_files is None:
        cut_files = discover_cut_files(test_root)
    if not cut_files:
        print(f"mockymock run: no .cut files found under {test_root}")
        return 1

    # --case/--tag pick a subset across the whole project, like `pytest
    # -m`: a suite with no selected case is skipped (no report written), and
    # only a selector that matches nothing in ANY suite is an error. Each
    # suite then gets only the selectors it actually matches, so its own
    # typo check never refuses it (issue #254).
    selections = _directory_selections(args, cut_files)
    if selections is None:
        return 1

    exit_code = 0
    ran = 0
    skipped_unselected = 0
    unresolved: list[str] = []
    broken_claims = 0
    tag_root = _report_tag_root(cut_files, test_root)
    for cut_path in cut_files:
        selection = selections.get(cut_path)
        if selection is not None and not selection[0] and not selection[1]:
            print(f"== {cut_path} == skipped: no selected TESTCASE")
            skipped_unselected += 1
            continue
        try:
            program_path = resolve_program_path(None, cut_path, layout)
        except DiscoveryError as exc:
            unresolved.append(str(exc))
            if read_program_line(cut_path) is not None:
                broken_claims += 1
            _write_skipped_suite_reports(args, cut_path, tag_root, str(exc))
            continue
        ran += 1
        sub_args = copy.copy(args)
        sub_args.program = str(program_path)
        sub_args.cut = str(cut_path)
        if selection is not None:
            sub_args.case = selection[0] or None
            sub_args.tag = selection[1] or None
        for flag in _RUN_OUTPUT_PATH_FLAGS:
            if getattr(args, flag, None):
                setattr(
                    sub_args,
                    flag,
                    _per_pair_report_path(getattr(args, flag), cut_path, tag_root),
                )
        print(f"== {cut_path} ==")
        exit_code = _cmd_run(sub_args) or exit_code

    for reason in unresolved:
        print(f"mockymock run: {reason}")
    summary = (
        f"mockymock run: {ran} suite(s) run, {len(unresolved)} .cut file(s) "
        f"skipped (no program found)"
    )
    if skipped_unselected:
        summary += f", {skipped_unselected} with no selected TESTCASE"
    print(summary)
    if ran == 0 or _report_broken_claims("run", broken_claims):
        return 1
    return exit_code


def _write_skipped_suite_reports(
    args: argparse.Namespace, cut_path: Path, tag_root: Path, reason: str
) -> None:
    """A failing --junit-xml / --json-report entry for a directory-mode
    suite skipped because its program was not found (issue #303), so a
    CI collector sees the skip instead of a smaller, clean build."""
    if not getattr(args, "junit_xml", None) and not getattr(args, "json_report", None):
        return
    import copy

    from mockymock.dsl.parser import CutParseError, parse_cut

    try:
        cut_suite = parse_cut(read_utf8_source(cut_path))
    except (CutParseError, OSError, UnicodeDecodeError):
        cut_suite = None
    sub_args = copy.copy(args)
    for flag in ("junit_xml", "json_report"):
        if getattr(args, flag, None):
            setattr(
                sub_args,
                flag,
                _per_pair_report_path(getattr(args, flag), cut_path, tag_root),
            )
    _write_failure_reports(
        sub_args,
        "run",
        cut_suite.name if cut_suite is not None else cut_path.stem,
        reason,
        cut_suite=cut_suite,
        cut_file=cut_path,
    )


def _directory_selections(
    args: argparse.Namespace, cut_files: list[Path]
) -> dict[Path, tuple[list[str], list[str]]] | None:
    """Per .cut file, the --case names and --tag tags it matches, or an
    empty dict when no selector was given. A file that cannot be read or
    parsed is left out, so it still runs and reports its own problem. None
    (after printing why) when a selector matches nothing in any suite."""
    from mockymock.dsl.parser import parse_cut

    case_names = list(getattr(args, "case", None) or [])
    tag_names = list(getattr(args, "tag", None) or [])
    if not case_names and not tag_names:
        return {}
    selections: dict[Path, tuple[list[str], list[str]]] = {}
    for cut_path in cut_files:
        try:
            suite = parse_cut(read_utf8_source(cut_path))
        except Exception:  # noqa: BLE001 -- the suite's own run reports it
            continue
        names = {case.name for case in suite.test_cases}
        tags = {tag for case in suite.test_cases for tag in case.tags}
        selections[cut_path] = (
            [name for name in case_names if name in names],
            [tag for tag in tag_names if tag in tags],
        )
    if len(selections) < len(cut_files):
        return selections  # an unparsed suite might hold the selected case
    unmatched = [
        f"no TESTCASE named {name!r} in any suite"
        for name in case_names
        if not any(name in sel[0] for sel in selections.values())
    ] + [
        f"no TESTCASE carries tag {tag!r} in any suite"
        for tag in tag_names
        if not any(tag in sel[1] for sel in selections.values())
    ]
    if unmatched:
        for problem in unmatched:
            print(f"mockymock run: {problem}")
        return None
    return selections


#: The most times `run` builds the cases a crash kept from running again.
_MAX_ISOLATION_RERUNS = 25


#: Reruns in a row in which only the first case ran, and crashed, before
#: `run` stops rerunning.
_MAX_STALLED_RERUNS = 2


def _cmd_run(args: argparse.Namespace) -> int:
    """`run` for one suite. When the binary crashes or times out part-way
    (one case looping forever, an abend), every case after it used to be
    reported NOT RUN and nothing was learned about them, nor recorded
    under --record-expectations (2026-11-03, NIST IX102A: a looping happy
    path hid five cases). Those cases are built and run again on their
    own, and again after each further crash, so one bad case costs only
    itself. The --json-report, and the result saved for `mockymock
    report`, get their results merged in.

    The left-over cases are picked by their position in the suite, never
    by name: TESTCASE names need not be unique, and a name shared with the
    case that crashed reran that case instead of the ones left over."""
    exit_code = _cmd_run_suite(args)
    remaining = list(getattr(args, "not_run_after_crash", None) or [])
    if not remaining or not _can_rerun_left_over_cases(args):
        return exit_code
    import copy
    import json

    reruns: list[tuple[dict, list[int | None]]] = []
    stalled = 0
    for _ in range(_MAX_ISOLATION_RERUNS):
        print(
            f"mockymock run: the test binary stopped before {len(remaining)} "
            f"case(s) could run; running them again without the case that "
            f"stopped it"
        )
        sub_args = copy.copy(args)
        sub_args.case_positions = remaining
        sub_args.not_run_after_crash = None
        sub_args.run_report = None
        # The rerun's report is merged into the first run's below, never
        # written over the user's --json-report file.
        sub_args.json_report = None
        exit_code = _cmd_run_suite(sub_args) or exit_code
        if getattr(sub_args, "run_report", None) is not None:
            reruns.append(sub_args.run_report)
        left = list(getattr(sub_args, "not_run_after_crash", None) or [])
        if not left or len(left) >= len(remaining):
            break
        # Only the first left-over case ran, and it crashed too: when that
        # happens twice running, the cases share whatever hangs (a loop in
        # code they all reach), and running each to its own timeout would
        # outlast any job limit (NIST RL107A).
        stalled = stalled + 1 if len(left) == len(remaining) - 1 else 0
        if stalled >= _MAX_STALLED_RERUNS:
            print(
                f"mockymock run: {len(left)} case(s) left not run -- the "
                f"cases before them each stopped the binary too, so they "
                f"likely share the cause"
            )
            break
        remaining = left
    first = getattr(args, "run_report", None)
    if first is None or not reruns:
        return exit_code
    merged = _merge_rerun_reports(first, reruns)
    text = json.dumps(merged, indent=2) + "\n"
    if args.json_report:
        _write_report_file("run", "--json-report", args.json_report, text)
    saved = getattr(args, "saved_run_report", None)
    if saved is not None and Path(saved).is_file():
        try:
            Path(saved).write_text(text, encoding="utf-8")
        except OSError:
            pass
    return exit_code


def _apply_file_checks(
    suite,
    suite_result,
    snapshots: dict[str, bytes],
    cut_path: Path,
    layouts: dict,
    record: bool,
) -> None:
    """EXPECT FILE / SAVE FILE (splicer.real_files.check_files): a differing
    or missing file fails its case; a recorded golden file is announced."""
    from mockymock.splicer.real_files import check_files

    by_id = {result.case_id: result for result in suite_result.results}
    ran = {
        index
        for index in range(1, len(suite.test_cases) + 1)
        if (r := by_id.get(f"{index:03d}")) is not None and r.ended
    }
    for outcome in check_files(suite, snapshots, cut_path.parent, layouts, record, ran):
        result = by_id.get(f"{outcome.case_index:03d}")
        if outcome.recorded:
            print(
                f"mockymock run: --record-expectations: recorded golden file "
                f"{outcome.check.path} for EXPECT FILE {outcome.check.file}"
            )
        if outcome.failure is None or result is None:
            continue
        if result.passed:
            suite_result.failures += 1
        result.failure_reasons.append(outcome.failure)


def _write_branch_coverage(
    args: argparse.Namespace,
    trace_text: str,
    suite_result,
    cut_path: Path,
    source_path: Path,
    ast,
    normalized_lines: list[str],
    instrumented: list[str],
    source_location_map: dict[int, tuple[str, int]] | None,
    real_programs,
    real_sources: list[tuple[str, list[str]]],
    suite=None,
) -> None:
    """`run --branch-coverage FILE`: measure every program of the run from
    the whole trace and write the JSON document (report.branch_coverage).
    The program under test's points no test can reach are marked
    (report.unreachable)."""
    from mockymock.report.branch_coverage import (
        format_branch_coverage_console,
        format_branch_coverage_json,
        measure,
        origin_lookup,
        program_points,
        program_report,
        split_by_program,
    )
    from mockymock.report.coverage import (
        build_normalized_line_map,
        build_normalized_to_original_map,
    )
    from mockymock.report.trace import parse_trace

    if not trace_text:
        print(
            "mockymock run: branch coverage not written -- the binary wrote "
            "no trace (it may have died before running a statement)"
        )
        return
    entries = parse_trace(trace_text)
    main_points = program_points(ast, normalized_lines)
    units = [
        (
            main_points,
            build_normalized_line_map(instrumented, normalized_lines),
            str(source_path),
            origin_lookup(
                source_location_map or None,
                build_normalized_to_original_map(
                    normalized_lines,
                    split_source_lines(read_utf8_source(source_path)),
                ),
            ),
        )
    ]
    instrumented_real = dict(real_sources)
    for prepared in real_programs or ():
        real_lines = instrumented_real.get(f"real_{prepared.program_id.upper()}.cbl")
        if real_lines is None:
            continue
        points = program_points(prepared.ast, list(prepared.lines))
        points.program_id = prepared.program_id.upper()
        try:
            original = split_source_lines(read_utf8_source(prepared.spec.source))
        except OSError:
            original = []
        units.append(
            (
                points,
                build_normalized_line_map(real_lines, list(prepared.lines)),
                str(prepared.spec.source),
                origin_lookup(
                    None,
                    build_normalized_to_original_map(list(prepared.lines), original),
                ),
            )
        )
    per_program = split_by_program(entries, [unit[0].program_id for unit in units])
    reports = []
    for index, (points, to_normalized, program_file, lookup) in enumerate(units):
        measure(points, per_program.get(points.program_id, []), to_normalized)
        unreachable = None
        if index == 0 and suite is not None:
            from mockymock.report.unreachable import classify

            unreachable = classify(ast, points, suite)
        reports.append(program_report(points, program_file, lookup, unreachable))
    text = format_branch_coverage_json(
        reports, str(cut_path), cases_run=len(suite_result.results)
    )
    _write_report_file("run", "--branch-coverage", args.branch_coverage, text)
    print(format_branch_coverage_console(reports))


def _can_rerun_left_over_cases(args: argparse.Namespace) -> bool:
    """Whether `run`'s outputs survive running the left-over cases in a
    second binary: not under a case/tag selection (that run already chose
    its cases), and not for the outputs that describe one binary as a
    whole (JUnit, coverage, trace, a behaviour baseline)."""
    whole_binary = (
        "case",
        "tag",
        "junit_xml",
        "coverage",
        "coverage_out",
        "coverage_json",
        "coverage_fail_under",
        "trace",
        "trace_json",
        "branch_coverage",
        "record_baseline",
        "baseline",
    )
    return not any(getattr(args, flag, None) for flag in whole_binary)


def _merge_rerun_reports(
    first: tuple[dict, list[int | None]],
    reruns: list[tuple[dict, list[int | None]]],
) -> dict:
    """The first run's JSON report with each not-run case replaced by the
    entry a rerun reported for it, and its summary counted again. Each
    report comes with the suite position of every case entry
    (`json_report.report_case_positions`), which is how an entry is
    matched: a name can be shared, and `--record-expectations` moves
    every line below a recorded value between the runs."""
    report, positions = first
    report = dict(report)
    cases = list(report.get("cases", []))
    by_position = {
        position: index
        for index, position in enumerate(positions)
        if position is not None and index < len(cases)
    }
    for rerun, rerun_positions in reruns:
        for entry, position in zip(
            rerun.get("cases", []), rerun_positions, strict=False
        ):
            index = by_position.get(position) if position is not None else None
            if index is None or entry.get("status") == "not_run":
                continue
            if cases[index].get("status") == "not_run":
                cases[index] = dict(entry, rerun=True)
    report["cases"] = cases
    statuses = [entry.get("status") for entry in cases]
    summary = dict(report.get("summary") or {})
    summary["testsRun"] = sum(1 for status in statuses if status != "not_run")
    summary["casesFailed"] = statuses.count("failed")
    summary["casesCrashed"] = statuses.count("crashed")
    summary["casesNotRun"] = statuses.count("not_run")
    summary["casesRisky"] = sum(1 for entry in cases if entry.get("risky"))
    report["summary"] = summary
    return report


def _cmd_run_suite(args: argparse.Namespace) -> int:
    import json

    from mockymock._decimal import decimal_point_is_comma
    from mockymock.analysis.stub_expectations import scan_stub_expectations
    from mockymock.dsl.model import MockCategory
    from mockymock.engine.checks import (
        run_static_checks,
    )
    from mockymock.report.coverage import (
        build_copybook_line_map,
        build_original_line_map,
        format_coverage_console,
        format_coverage_json,
        map_coverage_to_original,
        parse_gcov,
        summarize_original,
    )
    from mockymock.report.formatters import (
        CLEAN_EXIT_CRASH_DETAIL,
        format_console,
        format_junit_xml,
    )
    from mockymock.report.json_report import (
        build_json_report,
        format_json_report,
        not_run_case_names,
        not_run_case_positions,
        readable_suite,
        report_case_positions,
        risky_case_ids,
    )
    from mockymock.report.record_rewrite import (
        address_fields,
        build_recording_report,
        clock_value_fields,
        field_pictures,
        rewrite_cut_text,
    )
    from mockymock.report.results import parse_stdout
    from mockymock.report.trace import (
        case_entries,
        format_trace_console,
        format_trace_json,
        parse_trace,
    )
    from mockymock.runtime.executor import TIMEOUT_EXIT_CODE
    from mockymock.runtime.sandbox import sandbox_dir_maybe_kept
    from mockymock.runtime.toolchain import active as active_toolchain
    from mockymock.splicer.reset import index_names

    toolchain = active_toolchain()

    # `mockymock run PROG.cut` is the natural mistake: the positional is the
    # COBOL source, so a .cut there is the suite. Take it as --cut and let the
    # program be inferred from it, rather than failing on a missing file.
    if args.program and args.program.lower().endswith(".cut") and args.cut is None:
        args.cut, args.program = args.program, None

    # Directory-wide mode: no program, no --cut -- discover every .cut
    # file under the test root and run each against its sibling program.
    # See docs/2026-09-15-cli-ergonomics-design.md.
    if args.program is None and args.cut is None:
        return _run_directory(args)
    if (several := _several_suites(args)) is not None:
        return _run_directory(args, several)

    # Input existence is the one check that runs even before anything else:
    # a typo'd path must fail in milliseconds with no traceback.
    pair = _resolve_program_and_cut("mockymock run", args)
    if pair is None:
        return 1
    source_path, cut_path = pair

    _apply_config_to_args(args, source_path)
    # Taken before anything runs: `--record-expectations` rewrites the .cut,
    # and the saved result belongs to the suite as it ran (issue #352).
    case_positions = getattr(args, "case_positions", None)
    saved_inputs = (
        fingerprint(source_path, cut_path, args.copybook_path)
        if not args.case and not args.tag and not case_positions
        else None
    )

    # Asking for the coverage JSON, or a coverage report file, is asking
    # for coverage.
    if args.coverage_json:
        args.coverage = True
    if args.coverage_out:
        args.coverage = True
    # ... and so is asking for the coverage gate: --coverage-fail-under is
    # the `run` counterpart of `mutate --fail-under`, so it must be usable
    # on its own in a CI lane without also remembering --coverage.
    if args.coverage_fail_under is not None:
        args.coverage = True

    # Asking for the trace JSON is asking for the trace.
    if args.trace_json:
        args.trace = True
    if args.trace and (len(args.case or []) != 1 or args.tag):
        # The suite compiles and runs as ONE binary, and the trace file is a
        # separate stream from stdout with no shared timestamps -- so an
        # unscoped trace interleaves every case with nothing to segment it
        # by. Requiring a single case makes attribution true by
        # construction. See docs/2026-07-21-debug-trace-design.md.
        print(
            "mockymock run: --trace requires exactly one --case (and no "
            "--tag): the suite runs as a single binary, so an unscoped "
            "trace cannot be attributed to one case"
        )
        return 1

    # Static checks run BEFORE the toolchain comes up (see the lint design
    # doc): a bad .cut/.cbl fails fast with the real problem regardless of
    # Docker state, instead of paying a multi-minute image build (or a
    # misleading "Docker not available" error) first.
    checked = run_static_checks(
        source_path,
        cut_path,
        args.copybook_path,
        case_names=args.case,
        tag_names=args.tag,
        case_positions=case_positions,
    )
    for note in checked.notes:
        print(f"mockymock run: {note}")
    for warning in checked.warnings:
        print(f"mockymock run: {warning}")
    if checked.linkage is not None:
        _print_linkage_neutralization(
            "run",
            checked.linkage,
            applied=True,
            address_of=checked.linkage_address_of,
        )
    if checked.cics_eib is not None:
        _print_cics_eib_synthesis("run", checked.cics_eib, applied=True)
    if checked.problems:
        for problem in checked.problems:
            if problem.startswith("  "):
                print(problem)  # indented parse-error detail lines
            else:
                print(f"mockymock run: {problem}")
        _write_failure_reports(
            args,
            "run",
            checked.suite.name if checked.suite is not None else "",
            "\n".join(checked.problems),
            cut_suite=checked.suite,
            cut_file=cut_path,
            program_file=source_path,
        )
        return 1

    try:
        toolchain.ensure_toolchain()
    except toolchain.ToolchainNotAvailableError as exc:
        print(f"mockymock run: {exc}")
        return 1

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
    # The original-coverage remap needs the pre-splice normalized lines;
    # splice_program mutates nothing, but keep our own copy to be explicit.
    normalized_lines = list(lines)

    # USE REAL FILE: each real file's ASSIGN names a file in the sandbox,
    # and every FROM source must exist before anything compiles.
    real_fixtures: dict[tuple[int, str], tuple[Path, str]] = {}
    if checked.real_file_selects:
        from mockymock.splicer.real_files import FIXTURES_DIR, rewrite_assigns

        lines, assign_problems = rewrite_assigns(
            lines, checked.real_file_selects, set(checked.real_file_selects)
        )
        for index, case in enumerate(suite.test_cases, start=1):
            for real in case.real_files:
                if real.source is None:
                    continue
                fixture = (cut_path.parent / real.source).resolve()
                if not fixture.is_file():
                    assign_problems.append(
                        f"USE REAL FILE {real.file} FROM {real.source!r} "
                        f"(.cut line {real.line}): no such file {fixture}"
                    )
                real_fixtures[(index, real.file)] = (
                    fixture,
                    f"{FIXTURES_DIR}/{index:03d}-{real.file}",
                )
        if assign_problems:
            for problem in assign_problems:
                print(f"mockymock run: {problem}")
            return 1

    # --record-baseline / --baseline: every mocked boundary reports what it
    # was sent (splicer.behaviour, report.baseline). A baseline to compare
    # with is read before anything compiles, so a bad path fails fast.
    behaviour = bool(args.record_baseline or args.baseline)
    baseline_document = None
    if args.baseline:
        from mockymock.report.baseline import BaselineError, load_baseline

        try:
            baseline_document = load_baseline(Path(args.baseline))
        except BaselineError as exc:
            print(f"mockymock run: --baseline: {exc}")
            return 2

    # --record-expectations: scan the raw .cut text (not the parsed suite --
    # a "*> STUB EXPECT" line is an ordinary comment to parse_cut) against
    # the POST-filter `suite` (--case/--tag already applied by
    # run_static_checks) so a stub's case_index always means what
    # build_driver means by it. See
    # docs/2026-08-04-record-expectations-design.md.
    # Untranslated newlines, like `generate --fill`: the rewrite below
    # must keep a CRLF .cut CRLF (issue #199), so it is written back with
    # newline="" and rewrite_cut_text joins with the file's own newline.
    cut_text = read_utf8_source(cut_path, keep_newlines=True)
    stub_scan = (
        scan_stub_expectations(cut_text, suite) if args.record_expectations else None
    )
    record_targets: dict[int, list[str]] = {}
    if stub_scan is not None:
        for stub in stub_scan.stubs:
            record_targets.setdefault(stub.case_index, []).append(stub.data_name)

    built = build_instrumented(
        checked,
        BuildOptions(
            copybook_paths=args.copybook_path,
            trace=args.trace,
            behaviour=behaviour,
            record_targets=record_targets,
        ),
        lines=lines,
    )
    record_conditions = built.condition_names
    real_programs = checked.real_programs
    real_sources = built.extra_sources
    instrumented = built.source()
    if checked.real_file_selects:
        from mockymock.splicer.real_files import insert_case_staging

        instrumented = insert_case_staging(
            instrumented,
            suite,
            {key: sandbox for key, (_, sandbox) in real_fixtures.items()},
        )
    # --branch-coverage reads the statement trace of the whole run, so the
    # binary is compiled with -ftraceall even without --trace.
    trace_compile = bool(args.trace or getattr(args, "branch_coverage", None))

    # --verbose needs the sandbox retained too: the instrumented-source path
    # it prints on compile failure must still exist by the time the user
    # reads it, but plain --verbose (no --keep-sandbox) shouldn't leave
    # cruft behind after a run that actually succeeds -- see the explicit
    # cleanup below.
    with sandbox_dir_maybe_kept(
        root=toolchain.WORK_ROOT, keep=args.keep_sandbox or args.verbose
    ) as tmp:
        if args.keep_sandbox:
            print(f"mockymock run: keeping sandbox {tmp}")

        instrumented_path = tmp / source_path.with_suffix(".cbl").name
        instrumented_path.write_text(
            "\n".join(instrumented) + "\n", encoding="utf-8", newline="\n"
        )
        if checked.real_file_selects:
            from mockymock.splicer.real_files import FILES_DIR, FIXTURES_DIR, OUT_DIR

            for folder in (FILES_DIR, FIXTURES_DIR, OUT_DIR):
                (tmp / folder).mkdir(exist_ok=True)
            for source, sandbox in real_fixtures.values():
                shutil.copyfile(source, tmp / sandbox)
        extra_sources = []
        for name, real_lines in real_sources:
            real_path = tmp / name
            real_path.write_text(
                "\n".join(real_lines) + "\n", encoding="utf-8", newline="\n"
            )
            extra_sources.append(real_path)

        compiled = (
            toolchain.compile_source(
                instrumented_path,
                coverage=args.coverage,
                trace=trace_compile,
                extra_sources=extra_sources,
            )
            if extra_sources
            else toolchain.compile_source(
                instrumented_path, coverage=args.coverage, trace=trace_compile
            )
        )
        if not compiled.success:
            print("mockymock run: compile failed:")
            print(compiled.stderr)
            diagnosis = _compile_failure_diagnosis(
                toolchain,
                tmp,
                normalized_lines,
                compiled.stderr,
                real_programs=[
                    (
                        f"real_{prepared.program_id.upper()}.cbl",
                        prepared.program_id,
                        list(prepared.lines),
                    )
                    for prepared in real_programs
                ],
            )
            if diagnosis:
                print(f"mockymock run: {diagnosis}")
            if args.verbose or args.keep_sandbox:
                print(f"mockymock run: instrumented source at {instrumented_path}")
            # Deliberately no cleanup here even under plain --verbose: the
            # path just printed must still resolve after this function
            # returns, which is the whole point of printing it. Contrast
            # the try/finally below, guarding the run_binary/run_gcov
            # phase -- unlike a compile failure, an exception there prints
            # no path pointing at the sandbox, so leaving it behind would
            # just leak silently instead of helping anyone (audit finding
            # F10; a `return 1` from *this* branch used to be lumped in
            # with that same fix, which broke the documented, tested
            # --verbose-survives-a-compile-failure contract below).
            _write_failure_reports(
                args,
                "run",
                suite.name,
                compiled.stderr,
                cut_suite=suite,
                cut_file=cut_path,
                program_file=source_path,
            )
            return 1

        # try/finally, not just a statement after the `with`: plain --verbose
        # (no --keep-sandbox) asks sandbox_dir_maybe_kept to retain `tmp` for
        # this phase and relies on this cleanup running afterward. A bare
        # statement placed after the `with` block used to rely on this
        # phase never raising -- an exception from run_binary/run_gcov
        # skipped it and leaked the directory permanently, with no printed
        # path (unlike the compile-failure branch above) to tell anyone it
        # was there (audit finding F10).
        try:
            assert compiled.binary_path is not None  # implied by compiled.success
            trace_path = (
                tmp / f"{instrumented_path.stem}.trace" if trace_compile else None
            )
            executed = toolchain.run_binary(
                compiled.binary_path,
                timeout_seconds=args.timeout,
                trace_path=trace_path,
            )

            # Must be read while the sandbox still exists -- the context
            # manager removes it on exit unless --keep-sandbox was given.
            trace_text = ""
            if trace_path is not None and trace_path.exists():
                trace_text = trace_path.read_text(encoding="utf-8", errors="replace")
            file_snapshots: dict[str, bytes] = {}
            if checked.real_file_selects:
                from mockymock.splicer.real_files import OUT_DIR

                for snapshot in sorted((tmp / OUT_DIR).glob("*")):
                    file_snapshots[f"{OUT_DIR}/{snapshot.name}"] = snapshot.read_bytes()

            coverage_text = None
            coverage_report = None
            instrumented_name = instrumented_path.name
            if args.coverage:
                gcov_result = toolchain.run_gcov(instrumented_path)
                if gcov_result.success:
                    # Only the raw gcov parse happens inside the sandbox
                    # (the .gcov file dies with it); the console text is
                    # formatted below, once the original-.cbl remap the
                    # headline number comes from has been computed.
                    coverage_report = parse_gcov(gcov_result.gcov_text)
                else:
                    coverage_text = (
                        f"mockymock run: coverage: {gcov_result.stderr.rstrip()}"
                    )
        finally:
            if args.verbose and not args.keep_sandbox:
                shutil.rmtree(tmp, ignore_errors=True)

    suite_result = parse_stdout(executed.stdout)
    if checked.real_file_selects:
        _apply_file_checks(
            suite,
            suite_result,
            file_snapshots,
            cut_path,
            checked.real_file_layouts,
            record=bool(args.record_expectations),
        )

    # Real evidence about why the binary died beats the formatters'
    # default STOP-RUN hypothesis: a timeout (exit 124, with run_binary's
    # infinite-loop hint on stderr) and a runtime abort (nonzero exit,
    # libcob's message on stderr) are distinct failure modes and must not
    # both render as a generic crash.
    if executed.exit_code == TIMEOUT_EXIT_CODE:
        crash_detail = "binary timed out (exit 124); see stderr below"
    elif executed.exit_code != 0:
        crash_detail = f"binary exited with code {executed.exit_code}"
    elif any(result.crashed for result in suite_result.results):
        # A clean exit with a case left unfinished: control never came back
        # to the driver. Saying so beats a bare [CRASH] (issue #238).
        crash_detail = CLEAN_EXIT_CRASH_DETAIL
    else:
        crash_detail = None
    not_run = not_run_case_names(suite_result, suite)

    def suite_position(position: int | None) -> int | None:
        """A position in the selected cases as one in the whole suite."""
        if position is None or not case_positions:
            return position
        chosen = sorted(set(case_positions))
        return chosen[position - 1] if 0 < position <= len(chosen) else None

    if crash_detail is not None and not_run:
        # For `_cmd_run`: the cases this crash kept from running, by their
        # position in the whole suite.
        args.not_run_after_crash = [
            position
            for position in (
                suite_position(p) for p in not_run_case_positions(suite_result, suite)
            )
            if position is not None
        ]
    # Under --record-expectations the run exists to fill in the missing
    # assertions, so labelling its cases risky would only be noise.
    risky = [] if stub_scan is not None else risky_case_ids(suite_result, suite)
    # A numeric EXPECT's "got" is the field's raw DISPLAY image; the
    # console and the JSON report show the value it holds (issue #374).
    pictures = field_pictures(result.ast, checked.captures)
    decimal_comma = decimal_point_is_comma(result.ast)
    # The JUnit XML reads the same rendered reasons: a CI page showing
    # "expected 123.45, got -0012345" left the reader to place the implied
    # decimal point and sign themselves.
    readable = readable_suite(suite_result, suite, pictures, decimal_comma)
    print(
        format_console(
            readable,
            crash_detail=crash_detail,
            not_run=not_run,
            risky=risky,
        )
    )
    if risky:
        _hint_pending_stubs(cut_text, suite, suite_result, risky)
    if executed.stderr:
        print("mockymock run: binary stderr:")
        print(executed.stderr.rstrip("\n"))

    if stub_scan is not None:
        # Best-effort and cumulative, never gating the run's own exit code
        # (see the design doc's "Best-effort, cumulative reporting" and
        # "Never overwrite a hand-edited EXPECT" sections): every stub the
        # scanner found ends up in exactly one of recorded/skipped, and the
        # file is only ever touched when at least one stub was recorded.
        recording = build_recording_report(
            stub_scan,
            suite_result,
            address_fields(result.ast),
            pictures,
            condition_names=record_conditions,
            index_names={name.upper() for name in index_names(result.ast)},
            clock_fields=clock_value_fields(result.ast),
            clock_pinned={
                (index, directive.key.upper())
                for index, case in enumerate(suite.test_cases, start=1)
                for directive in case.mocks
                if directive.category is MockCategory.ACCEPT
            },
        )
        rewritten = rewrite_cut_text(
            cut_text,
            recording,
            pictures,
            decimal_comma=decimal_comma,
        )
        if rewritten is not None:
            cut_path.write_text(rewritten, encoding="utf-8", newline="")
        print(
            f"mockymock run: --record-expectations: recorded "
            f"{len(recording.recorded)}, skipped {len(recording.skipped)}"
        )
        for item in recording.recorded:
            print(
                f"  recorded {item.stub.data_name} (line {item.stub.line}) "
                f"= {item.value}"
            )
        for skip in recording.skipped:
            print(f"  skipped {skip.data_name} (line {skip.line}): {skip.reason}")
        if rewritten is not None:
            print(f"mockymock run: rewrote {cut_path}")

    if args.junit_xml:
        _write_report_file(
            "run",
            "--junit-xml",
            args.junit_xml,
            format_junit_xml(readable, crash_detail=crash_detail, not_run=not_run),
        )

    run_report = build_json_report(
        suite_result,
        cut_suite=suite,
        crash_detail=crash_detail,
        cut_file=str(cut_path),
        program_file=str(source_path),
        pictures=pictures,
        decimal_comma=decimal_comma,
    )
    # For `_cmd_run`, which merges the reruns of left-over cases into it.
    args.run_report = (
        run_report,
        [suite_position(p) for p in report_case_positions(suite_result, suite)],
    )
    run_json_text = format_json_report(run_report)
    if args.json_report:
        _write_report_file("run", "--json-report", args.json_report, run_json_text)
    if saved_inputs is not None:
        from mockymock.report.artifacts import artifact_path

        _save_result(
            "run", cut_path, source_path, "run", run_json_text, args, saved_inputs
        )
        args.saved_run_report = artifact_path(cut_path, "run")

    # The original-.cbl remap is what BOTH the console headline and the
    # --coverage-fail-under gate read, so it is computed once here for
    # every --coverage run -- not only when --coverage-json asked for it,
    # as it was when the instrumented number was the only one printed.
    original_coverage = None
    if coverage_report is not None:
        original_source_lines = split_source_lines(read_utf8_source(source_path))
        mapped = map_coverage_to_original(
            coverage_report,
            instrumented,
            normalized_lines,
            original_source_lines,
        )
        original_coverage = summarize_original(mapped, original_source_lines)
        coverage_text = format_coverage_console(
            coverage_report,
            instrumented_name,
            original=original_coverage,
            program_name=source_path.name,
        )
        coverage_json_text = format_coverage_json(
            coverage_report,
            mapped,
            program_file=str(source_path),
            instrumented_name=instrumented_name,
        )
        if args.coverage_json:
            _write_report_file(
                "run", "--coverage-json", args.coverage_json, coverage_json_text
            )
        if saved_inputs is not None:
            _save_result(
                "run",
                cut_path,
                source_path,
                "coverage",
                coverage_json_text,
                args,
                saved_inputs,
            )
    elif args.coverage_json:
        print(
            "mockymock run: coverage JSON not written -- the gcov pass "
            "failed (see the coverage error above)"
        )

    if coverage_text is not None:
        print(coverage_text)
        if args.coverage_out:
            _write_report_file(
                "run", "--coverage-out", args.coverage_out, coverage_text + "\n"
            )

    # The coverage gate is the `run` counterpart of `mutate --fail-under`,
    # and is judged against the ORIGINAL program's coverage -- gating on
    # the instrumented number would make the threshold move whenever
    # mockymock's own injected line count changed, which says nothing about
    # the program under test. A failed gcov pass fails the gate rather than
    # passing it silently: "no number" must never read as "good enough".
    # Recorded, not returned on, so --trace still prints below: the gate is
    # folded into this command's single final exit-code decision instead.
    coverage_gate_failed = False
    if args.coverage_fail_under is not None:
        if original_coverage is None:
            print(
                f"mockymock run: coverage gate failed -- no coverage was "
                f"measured (the gcov pass failed; see above), so "
                f"--coverage-fail-under {args.coverage_fail_under} cannot "
                f"be satisfied"
            )
            coverage_gate_failed = True
        elif original_coverage.percentage < args.coverage_fail_under:
            print(
                f"mockymock run: coverage {original_coverage.percentage:.2f}% "
                f"is below --coverage-fail-under {args.coverage_fail_under}"
            )
            coverage_gate_failed = True

    if getattr(args, "branch_coverage", None):
        _write_branch_coverage(
            args,
            trace_text,
            suite_result,
            cut_path,
            source_path,
            result.ast,
            normalized_lines,
            instrumented,
            checked.source_location_map,
            real_programs,
            real_sources,
            suite,
        )

    if args.trace:
        if not trace_text:
            print(
                "mockymock run: no execution trace produced -- the binary "
                "wrote no trace file (it may have died before executing a "
                "single statement)"
            )
        else:
            # Exactly one case is selected (enforced above), but the trace
            # also holds the BEFORE-ALL/AFTER-ALL steps run around it, so
            # it is cut to the case's own span (case_entries, #334).
            selected = args.case[0]
            case_result = next(
                (r for r in suite_result.results if r.case_name == selected), None
            )
            model_case = next((c for c in suite.test_cases if c.name == selected), None)
            trace_json = format_trace_json(
                case_entries(
                    parse_trace(trace_text),
                    instrumented,
                    case_result.case_id if case_result is not None else None,
                ),
                build_original_line_map(
                    instrumented,
                    normalized_lines,
                    split_source_lines(read_utf8_source(source_path)),
                ),
                case_result.mock_hits if case_result is not None else [],
                selected,
                model_case.line if model_case is not None else None,
                str(cut_path),
                str(source_path),
                build_copybook_line_map(
                    instrumented, normalized_lines, checked.source_location_map
                ),
                original_lines=split_source_lines(read_utf8_source(source_path)),
            )
            if args.trace_json:
                _write_report_file("run", "--trace-json", args.trace_json, trace_json)
            print(format_trace_console(json.loads(trace_json)))

    # A nonzero binary exit is a failed run even when every case that got
    # to print its markers passed (e.g. libcob aborted after the SUMMARY
    # line, or the timeout killed a straggler). A tripped
    # --coverage-fail-under gate fails the command the same way, so a green
    # suite under an unmet coverage floor still exits nonzero in CI.
    if (
        suite_result.results
        and suite_result.tests_run == 0
        and all(result.passed for result in suite_result.results)
    ):
        # Every case printed a clean END, yet the driver never reached its
        # SUMMARY line: something the program ran after the last case
        # ended the binary before AFTER-ALL. Exiting 1 under an all-PASS
        # report without saying why read as a mockymock bug (issue #264).
        print(
            "mockymock run: every case passed, but the test binary ended "
            "without printing its SUMMARY line -- program code that ran "
            "after the last case (a STOP RUN, GOBACK, or abend) stopped it "
            "before AFTER-ALL, so the run is not counted as passed"
        )
    baseline_differs = False
    if behaviour:
        baseline_differs = _finish_baseline(
            args, suite_result, cut_path, source_path, real_programs, baseline_document
        )
    if coverage_gate_failed or baseline_differs:
        return 1
    return 0 if suite_result.all_passed and executed.exit_code == 0 else 1


def _baseline_inputs(
    cut_path: Path, source_path: Path, real_programs
) -> dict[str, str]:
    """SHA-256 of every file a baseline depends on, by role."""
    from mockymock.report.baseline import sha256_file

    inputs = {"cut": sha256_file(cut_path), "program": sha256_file(source_path)}
    for prepared in real_programs or ():
        inputs[f"real:{prepared.program_id.upper()}"] = sha256_file(
            Path(prepared.spec.source)
        )
    return inputs


def _finish_baseline(
    args: argparse.Namespace,
    suite_result,
    cut_path: Path,
    source_path: Path,
    real_programs,
    baseline_document,
) -> bool:
    """Write the --record-baseline file and/or compare with --baseline.
    True when the run's behaviour differs from the baseline."""
    import json

    from mockymock import __version__
    from mockymock.report.baseline import (
        build_baseline,
        compare,
        format_comparison,
        write_baseline,
    )

    inputs = _baseline_inputs(cut_path, source_path, real_programs)
    differs = False
    if baseline_document is not None:
        comparison = compare(baseline_document, suite_result, inputs)
        print(format_comparison(comparison))
        if args.baseline_json:
            _write_report_file(
                "run",
                "--baseline-json",
                args.baseline_json,
                json.dumps(comparison.to_dict(), indent=2) + "\n",
            )
        differs = not comparison.matches
    if args.record_baseline:
        document = build_baseline(suite_result, inputs, __version__)
        target = Path(args.record_baseline)
        try:
            write_baseline(target, document)
        except OSError as exc:
            print(f"mockymock run: --record-baseline: cannot write {target}: {exc}")
            return True
        print(
            f"mockymock run: recorded a baseline of {len(document['cases'])} "
            f"case(s) to {target}"
        )
    return differs


_EXEC_RE = re.compile(r"\bEXEC\s+(SQL|CICS|DLI|SQLIMS)\b", re.IGNORECASE)


_UNRECOGNIZED_OPTION_RE = re.compile(r"unrecognized option '(?P<option>--?[\w-]+)'")


def _compile_failure_diagnosis(
    toolchain: ModuleType,
    tmp: Path,
    normalized_lines: list[str],
    stderr: str = "",
    real_programs: Sequence[tuple[str, str, list[str]]] = (),
) -> str | None:
    """Whose compile failure this is, when that can be told: the program
    as mockymock read it (copybooks expanded, nothing spliced) is compiled
    on its own. It failing too means the program itself does not compile
    under GnuCOBOL; it compiling means mockymock's changes broke it. None
    when the program holds EXEC blocks (cobc cannot compile those without
    mockymock's rewrite, so the check would prove nothing) or when the
    check cannot run.

    A cobc that rejects one of the flags the run itself asked for
    (`--coverage` on GnuCOBOL older than 3.2) is told apart first: the
    probe compiles without that flag, so it succeeded and the failure
    used to be reported as a mockymock bug.

    `real_programs` are the USE REAL CALL programs linked into the run, as
    (file name in the sandbox, PROGRAM-ID, lines as mockymock read them):
    they are compiled with the probe, unchanged. A real program that does
    not compile was reported as "the program compiles on its own, so ... a
    mockymock bug" (2026-11-05): only the program under test was probed."""
    option = _UNRECOGNIZED_OPTION_RE.search(stderr)
    if option is not None:
        return (
            f"this GnuCOBOL does not support {option.group('option')}, which "
            f"the requested run needs (--coverage needs GnuCOBOL 3.2 or "
            f"later) -- drop the option, or run with the mockymock-cobc "
            f"Docker image"
        )
    if _holds_exec(normalized_lines):
        return None
    # A real program with EXEC blocks cannot be probed either; an error in
    # one leaves the verdict open.
    reals = [real for real in real_programs if not _holds_exec(real[2])]
    unprobed = {name for name, _, _ in real_programs} - {name for name, _, _ in reals}
    if any(f"{name}:" in stderr for name in unprobed):
        return None
    probe = tmp / "UTPROBE" / "PROBE.cbl"
    try:
        probe.parent.mkdir(exist_ok=True)
        probe.write_text("\n".join(normalized_lines) + "\n", encoding="utf-8")
        extra: list[Path] = []
        for name, _, lines in reals:
            extra.append(probe.parent / name)
            extra[-1].write_text("\n".join(lines) + "\n", encoding="utf-8")
        result = (
            toolchain.compile_source(probe, extra_sources=extra)
            if extra
            else toolchain.compile_source(probe)
        )
    except Exception:  # noqa: BLE001 -- a diagnosis must never hide the failure
        return None
    if not result.success:
        for name, program_id, _ in reals:
            first = next(
                (
                    line.strip()
                    for line in result.stderr.splitlines()
                    if f"{name}:" in line and "error:" in line
                ),
                "",
            )
            if first:
                first = re.sub(rf"^.*?{re.escape(name)}:(\d+):", r"line \1:", first)
                return (
                    f"the real program {program_id} (USE REAL CALL) does not "
                    f"compile under GnuCOBOL even without mockymock's changes "
                    f"({first}) -- fix it, or mock its CALL instead"
                )
    if result.success:
        return (
            "the program compiles on its own, so the code mockymock added "
            "broke the compile -- a mockymock bug; please report it with "
            "this program"
        )
    first = next(
        (line.strip() for line in result.stderr.splitlines() if "error:" in line),
        "",
    )
    # `PROBE.cbl:58: error: ...` -> `line 58: error: ...` (the normalized
    # lines keep the program's own line numbers).
    first = re.sub(r"^.*?PROBE\.cbl:(\d+):", r"line \1:", first)
    return (
        "the program does not compile under GnuCOBOL even without "
        "mockymock's changes"
        + (f" ({first})" if first else "")
        + " -- fix that first; generated tests cannot run before it compiles"
    )


def _holds_exec(lines: list[str]) -> bool:
    """Whether `lines` hold an EXEC block, which plain cobc cannot compile."""
    return any(_EXEC_RE.search(line.split("*>", 1)[0]) for line in lines)


def register_run(subparsers: argparse._SubParsersAction) -> None:
    """Add `mockymock run` to the top-level parser."""
    run_parser = subparsers.add_parser(
        "run",
        help="Splice, compile, run, and assert a COBOL program against a .cut file",
    )
    run_parser.add_argument(
        "program",
        nargs="?",
        help=(
            "COBOL source file. Omit to infer it from --cut's sibling "
            "file (same directory, same stem); omit both program and "
            "--cut to discover and run every .cut file under the "
            "current directory (or the config file's test_root)"
        ),
    )
    run_parser.add_argument(
        "--cut",
        help="Test file. Omit to infer it from program's sibling .cut file",
    )
    run_parser.add_argument(
        "--junit-xml",
        help="Write a JUnit XML report (one testcase per TESTCASE) to this file, "
        "for CI test dashboards",
    )
    run_parser.add_argument(
        "--json-report",
        help=(
            "Write a machine-readable run report (per-case status, .cut "
            "line numbers, expected/actual per failure, tags) to this file"
        ),
    )
    run_parser.add_argument(
        "--case",
        action="append",
        help=(
            "Run only the TESTCASE with this exact name (repeatable; "
            "combines with --tag as a union). The suite still runs as one "
            "compile + binary, just with only the selected cases spliced in"
        ),
    )
    run_parser.add_argument(
        "--tag",
        action="append",
        help=(
            "Run only TESTCASEs carrying this tag (repeatable; combines "
            "with --case as a union)"
        ),
    )
    run_parser.add_argument(
        "--copybook-path",
        action="append",
        help="Directory to search for copybooks (repeatable)",
    )
    run_parser.add_argument(
        "--extra-copybook-path",
        action="append",
        help=(
            "Directory to search for copybooks after the --copybook-path / "
            "config file list (repeatable; adds to it instead of replacing it)"
        ),
    )
    run_parser.add_argument(
        "--keep-sandbox",
        action="store_true",
        help="Do not delete the sandbox; print its path for inspection",
    )
    run_parser.add_argument(
        "--verbose",
        action="store_true",
        help="On compile failure, print the path to the instrumented source",
    )
    run_parser.add_argument(
        "--coverage",
        action="store_true",
        help=(
            "Compile with GnuCOBOL's --coverage flag and report per-line "
            "coverage after the run (gcov-based). The headline figure is "
            "the ORIGINAL .cbl's own coverage; the instrumented sandbox "
            "copy's higher number is reported below it for reference -- "
            "see docs/2026-07-17-coverage-reporting-design.md"
        ),
    )
    run_parser.add_argument(
        "--coverage-out",
        help="Write the full coverage report (percentage + uncovered lines) to this file",
    )
    run_parser.add_argument(
        "--coverage-fail-under",
        type=_percent,
        metavar="PERCENT",
        help=(
            "Exit nonzero when the ORIGINAL .cbl's line coverage is below "
            "this percentage -- the `run` counterpart of `mutate "
            "--fail-under`, so coverage can be CI-gated the same way. "
            "Implies --coverage"
        ),
    )
    run_parser.add_argument(
        "--coverage-json",
        help=(
            "Write machine-readable coverage to this file, remapped onto "
            "the ORIGINAL .cbl's line numbers (splicer-inserted lines "
            "excluded). Implies --coverage"
        ),
    )
    run_parser.add_argument(
        "--trace",
        action="store_true",
        help=(
            "Trace the executed path through the program for a single test "
            "case and print it after the run, together with the mocks that "
            "fired in order. Requires exactly one --case"
        ),
    )
    run_parser.add_argument(
        "--branch-coverage",
        metavar="FILE",
        help=(
            "Write paragraph, branch (IF true/false, each EVALUATE WHEN) and "
            "statement coverage of every case, for the program and every "
            "USE REAL CALL program, to this JSON file, and print a summary. "
            "Read from GnuCOBOL's statement trace, so it works on any "
            "GnuCOBOL 3.x (see docs/2026-11-06-branch-coverage-design.md)"
        ),
    )
    run_parser.add_argument(
        "--trace-json",
        help=(
            "Write the machine-readable execution trace (executed path "
            "remapped onto the ORIGINAL .cbl's line numbers, plus the "
            "ordered mock timeline) to this file. Implies --trace"
        ),
    )
    run_parser.add_argument(
        "--timeout",
        type=_timeout_seconds,
        default=30,
        help=(
            "Binary execution timeout in seconds (default 30); a mocked "
            "CALL that removes a loop's terminating condition can "
            "otherwise hang until this limit kills it -- give a "
            'retrieve-and-loop CALL a sequence instead, MOCK CALL "X" '
            "ROWS ( ... ) TERMINAL ( ... ), so later calls end the loop "
            "(mirrors mutate's own --timeout)"
        ),
    )
    run_parser.add_argument(
        "--record-expectations",
        action="store_true",
        help=(
            "Golden/characterization mode: run the suite, capture the real "
            "runtime value behind every '*> STUB EXPECT <name>' comment in "
            "the .cut file, and rewrite the file in place with those stubs "
            "turned into real EXPECT lines. Best-effort and cumulative -- "
            "recorded/skipped counts are printed, with a reason for every "
            "skip. Never touches a line that isn't a stub comment (so a "
            "hand-written or previously-recorded EXPECT is never "
            "overwritten), and never rewrites the file at all if nothing "
            "was recorded. Does not change the run's exit code. See "
            "docs/2026-08-04-record-expectations-design.md"
        ),
    )
    run_parser.add_argument(
        "--record-baseline",
        metavar="FILE",
        help=(
            "Record what every case sends out of the program (each mocked "
            "boundary in order, the bytes of every value passed to it, the "
            "program's DISPLAY output and RETURN-CODE) to FILE, as the "
            "baseline later runs are compared with. See "
            "docs/2026-11-01-baseline-design.md"
        ),
    )
    run_parser.add_argument(
        "--baseline",
        metavar="FILE",
        help=(
            "Compare this run's behaviour with a baseline recorded by "
            "--record-baseline, case by case (by name). Exits 1 when any "
            "case's behaviour differs, even if every EXPECT passed"
        ),
    )
    run_parser.add_argument(
        "--baseline-json",
        metavar="FILE",
        help="Write the --baseline comparison as JSON to FILE",
    )
    run_parser.set_defaults(func=_cmd_run)
