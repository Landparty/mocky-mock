"""mockymock CLI entry point."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from mockymock import __version__


def _cmd_setup(args: argparse.Namespace) -> int:
    from mockymock.runtime import docker_toolchain

    try:
        docker_toolchain.ensure_toolchain()
        version = docker_toolchain.cobc_version()
    except docker_toolchain.DockerNotAvailableError as exc:
        print(f"mockymock setup: {exc}")
        return 1
    print(
        f"mockymock setup: container {docker_toolchain.CONTAINER} ready " f"({version})"
    )
    return 0


def _check_input_files(command: str, *paths: Path) -> bool:
    """Print a clean error for every input path that doesn't exist. Runs
    before any toolchain/parse work so a typo'd path fails in milliseconds
    with no traceback -- never after a multi-minute image build."""
    ok = True
    for path in paths:
        if not path.is_file():
            print(f"{command}: no such file: {path}")
            ok = False
    return ok


def _cmd_generate(args: argparse.Namespace) -> int:
    from cobolparser import parse_cobol
    from cobolparser.preprocess import expand_copybooks, normalize_fixed_format

    from mockymock.analysis.linkage import linkage_plan
    from mockymock.analysis.mock_surface import analyze
    from mockymock.analysis.refusal import (
        check_expansion_warnings,
        check_linkage_layout,
        check_unresolved_copybooks,
        check_whole_program,
    )
    from mockymock.dsl.generator import scaffold_cut
    from mockymock.splicer.source_map import annotate_nested_sites, collect_scope_map

    source_path = Path(args.program)
    if not _check_input_files("mockymock generate", source_path):
        return 1
    raw_source = source_path.read_text()
    if args.copybook_path:
        expansion = expand_copybooks(raw_source, copybook_paths=args.copybook_path)
        expansion_reasons = check_expansion_warnings(expansion)
        for reason in expansion_reasons:
            print(f"mockymock generate: refused ({reason.code}): {reason.message}")
        if expansion_reasons:
            return 1
        raw_source = expansion.expanded_source
    result = parse_cobol(raw_source, filename=source_path.name)
    if not result.success:
        print(f"mockymock generate: {len(result.errors)} parse error(s):")
        for error in result.errors:
            print(f"  {error}")
        return 1

    # success=True is not enough: cobolparser reports dropped statements
    # (unsupported verbs, multi-program units, unparsed clause leftovers)
    # as warnings on an otherwise clean parse. A scaffold built from an
    # incomplete AST would silently miss boundaries, so refuse.
    warning_reasons = check_whole_program(result)
    for reason in warning_reasons:
        print(f"mockymock generate: refused ({reason.code}): {reason.message}")
    if warning_reasons:
        return 1

    copybook_reasons = check_unresolved_copybooks(raw_source)
    for reason in copybook_reasons:
        print(f"mockymock generate: refused ({reason.code}): {reason.message}")
    if copybook_reasons:
        return 1

    lines = normalize_fixed_format(raw_source.splitlines()).splitlines()

    linkage_reasons = check_linkage_layout(result.ast, lines)
    for reason in linkage_reasons:
        print(f"mockymock generate: refused ({reason.code}): {reason.message}")
    if linkage_reasons:
        return 1
    linkage = linkage_plan(result.ast)
    if linkage is not None:
        _print_linkage_neutralization("generate", linkage, applied=False)

    surface = analyze(result.ast)
    annotate_nested_sites(surface, collect_scope_map(result.ast, lines), lines)
    cut_text = scaffold_cut(result.ast.program_name, surface)

    output_path = Path(args.output) if args.output else source_path.with_suffix(".cut")
    output_path.write_text(cut_text)
    case_count = cut_text.count("TESTCASE ")
    print(f"mockymock generate: wrote {case_count} test case(s) -> {output_path}")
    _report_unsupported_boundaries(surface)
    return 0


def _print_linkage_neutralization(command: str, plan, applied: bool) -> None:
    """Transparency for the ENTRY/LINKAGE neutralization transform: it never
    refuses (that's `check_linkage_layout`'s job) and edits source a `.cut`
    author didn't write, so say so rather than silently changing behavior.
    `applied` distinguishes `run` (the transform actually ran on this
    invocation) from `generate` (which never touches instrumented source --
    it only scaffolds a `.cut` from the AST -- so this only describes what
    a later `run` against this program will do). See
    docs/2026-07-08-ims-linkage-support-design.md."""
    entry_names = ", ".join(
        repr(e.entry_name) for e in plan.entry_statements if e.entry_name
    )
    item_names = ", ".join(item.name for item in plan.linkage_items)
    if applied:
        action = (
            f"neutralized ENTRY statement(s) ({entry_names}) and folded "
            f"LINKAGE SECTION into WORKING-STORAGE ({item_names})"
        )
    else:
        action = (
            f"a later `run` will neutralize ENTRY statement(s) "
            f"({entry_names}) and fold LINKAGE SECTION into WORKING-STORAGE "
            f"({item_names})"
        )
    print(
        f"mockymock {command}: {action} -- the driver never binds LINKAGE "
        f"SECTION storage, so this program's default entry gets real, "
        f"addressable storage instead"
    )


def _report_unsupported_boundaries(surface) -> None:
    """Name every detected boundary point that stays unmockable (the
    SORT/MERGE family, identifier-less dynamic CALLs, unspliceable nested
    sites), so the scaffold is never mistaken for complete coverage of the
    program's outputs. Test cases whose PERFORM target reaches one of
    these are refused by `run`.

    STOP RUN/GOBACK sites are reported separately and more cautiously:
    unlike the other category=None labels, `run` does not always refuse a
    test case reaching one -- check_terminator_layout (see
    docs/2026-07-08-goback-stop-run-support-design.md) may find it safe.
    `generate` has no specific test case's PERFORM target to evaluate
    reachability against, so it cannot know which outcome a future `.cut`
    will get -- claiming "will be refused" here would be wrong as often as
    it's right.
    """
    from mockymock.analysis.mock_surface import _TERMINATOR_LABELS

    findings: list[str] = []
    terminator_findings: list[str] = []
    for site in surface.boundary_sites:
        if site.category is None:
            if site.label in _TERMINATOR_LABELS:
                terminator_findings.append(
                    f"{site.label} in paragraph '{site.paragraph_name}' "
                    f"(line {site.line})"
                )
            else:
                findings.append(
                    f"{site.label} in paragraph '{site.paragraph_name}' "
                    f"(line {site.line})"
                )
        elif site.nested and site.span is None:
            findings.append(
                f"nested {site.label} in paragraph '{site.paragraph_name}' "
                f"(line {site.line}) -- {site.unspliceable_reason}"
            )
    if findings:
        print(
            f"mockymock generate: {len(findings)} boundary point(s) detected "
            f"that are not mockable (test cases reaching them will be "
            f"refused):"
        )
        for finding in findings:
            print(f"  - {finding}")
    if terminator_findings:
        print(
            f"mockymock generate: {len(terminator_findings)} STOP RUN/GOBACK "
            f"site(s) detected -- whether a test case reaching one is "
            f"refused depends on how it's reached; see "
            f"docs/2026-07-08-goback-stop-run-support-design.md:"
        )
        for finding in terminator_findings:
            print(f"  - {finding}")


def _cmd_run(args: argparse.Namespace) -> int:
    from mockymock.analysis.flow_mocks import find_flow_mock_plans
    from mockymock.analysis.refusal import find_terminator_plans
    from mockymock.cli.checks import run_static_checks
    from mockymock.report.coverage import (
        format_coverage_console,
        format_coverage_json,
        map_coverage_to_original,
        parse_gcov,
    )
    from mockymock.report.formatters import format_console, format_junit_xml
    from mockymock.report.json_report import build_json_report, format_json_report
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

    # Input existence is the one check that runs even before anything else:
    # a typo'd path must fail in milliseconds with no traceback.
    source_path = Path(args.program)
    cut_path = Path(args.cut)
    if not _check_input_files("mockymock run", source_path, cut_path):
        return 1

    # Asking for the coverage JSON is asking for coverage.
    if args.coverage_json:
        args.coverage = True

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
    )
    if checked.linkage is not None:
        _print_linkage_neutralization("run", checked.linkage, applied=True)
    if checked.problems:
        for problem in checked.problems:
            if problem.startswith("  "):
                print(problem)  # indented parse-error detail lines
            else:
                print(f"mockymock run: {problem}")
        return 1

    try:
        docker_toolchain.ensure_toolchain()
    except docker_toolchain.DockerNotAvailableError as exc:
        print(f"mockymock run: {exc}")
        return 1

    result = checked.parse_result
    suite = checked.suite
    surface = checked.surface
    lines = checked.lines
    scope_map = checked.scope_map
    linkage = checked.linkage
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

    boundaries = collect_boundaries(result.ast)
    registry = TallyRegistry(suite)
    terminator_plans, _ = find_terminator_plans(
        surface, result.ast, suite, scope_map, lines
    )
    flow_plans, _ = find_flow_mock_plans(result.ast, suite, lines)
    lines = splice_program(
        lines, boundaries, surface, suite, registry, terminator_plans, flow_plans
    )
    lines, _ = transform_data_division_exec(lines, copybook_paths=args.copybook_path)

    reset_lines = reset_move_lines(result.ast)
    if linkage is not None:
        # LINKAGE items `neutralize` folded into WORKING-STORAGE live under
        # the LINKAGE section in `result.ast` still (the transform edited
        # text, not the AST), so `reset_move_lines`'s WORKING-STORAGE walk
        # never sees them -- add their reset lines explicitly.
        reset_lines = reset_lines + extra_reset_lines(linkage)
    artifact = build_driver(suite, reset_lines, registry)

    instrumented = _insert_driver(lines, artifact)

    # --verbose needs the sandbox retained too: the instrumented-source path
    # it prints on compile failure must still exist by the time the user
    # reads it, but plain --verbose (no --keep-sandbox) shouldn't leave
    # cruft behind after a run that actually succeeds -- see the explicit
    # cleanup below.
    with sandbox_dir_maybe_kept(
        root=docker_toolchain.WORK_ROOT, keep=args.keep_sandbox or args.verbose
    ) as tmp:
        if args.keep_sandbox:
            print(f"mockymock run: keeping sandbox {tmp}")

        instrumented_path = tmp / source_path.with_suffix(".cbl").name
        instrumented_path.write_text("\n".join(instrumented) + "\n", newline="\n")

        compiled = docker_toolchain.compile_source(
            instrumented_path, coverage=args.coverage
        )
        if not compiled.success:
            print("mockymock run: compile failed:")
            print(compiled.stderr)
            if args.verbose or args.keep_sandbox:
                print(f"mockymock run: instrumented source at {instrumented_path}")
            return 1

        assert compiled.binary_path is not None  # implied by compiled.success
        executed = docker_toolchain.run_binary(compiled.binary_path)

        coverage_text = None
        coverage_report = None
        if args.coverage:
            gcov_result = docker_toolchain.run_gcov(instrumented_path)
            if gcov_result.success:
                coverage_report = parse_gcov(gcov_result.gcov_text)
                coverage_text = format_coverage_console(
                    coverage_report, instrumented_path.name
                )
            else:
                coverage_text = (
                    f"mockymock run: coverage: {gcov_result.stderr.rstrip()}"
                )

    if args.verbose and not args.keep_sandbox:
        shutil.rmtree(tmp, ignore_errors=True)

    suite_result = parse_stdout(executed.stdout)

    # Real evidence about why the binary died beats the formatters'
    # default STOP-RUN hypothesis: a timeout (exit 124, with run_binary's
    # infinite-loop hint on stderr) and a runtime abort (nonzero exit,
    # libcob's message on stderr) are distinct failure modes and must not
    # both render as a generic crash.
    if executed.exit_code == TIMEOUT_EXIT_CODE:
        crash_detail = "binary timed out (exit 124); see stderr below"
    elif executed.exit_code != 0:
        crash_detail = f"binary exited with code {executed.exit_code}"
    else:
        crash_detail = None
    print(format_console(suite_result, crash_detail=crash_detail))
    if executed.stderr:
        print("mockymock run: binary stderr:")
        print(executed.stderr.rstrip("\n"))

    if args.junit_xml:
        Path(args.junit_xml).write_text(
            format_junit_xml(suite_result, crash_detail=crash_detail)
        )

    if args.json_report:
        Path(args.json_report).write_text(
            format_json_report(
                build_json_report(
                    suite_result,
                    cut_suite=suite,
                    crash_detail=crash_detail,
                    cut_file=str(cut_path),
                    program_file=str(source_path),
                )
            )
        )

    if args.coverage_json:
        if coverage_report is None:
            print(
                "mockymock run: coverage JSON not written -- the gcov pass "
                "failed (see the coverage error above)"
            )
        else:
            mapped = map_coverage_to_original(
                coverage_report,
                instrumented,
                normalized_lines,
                source_path.read_text().splitlines(),
            )
            Path(args.coverage_json).write_text(
                format_coverage_json(
                    coverage_report,
                    mapped,
                    program_file=str(source_path),
                    instrumented_name=instrumented_path.name,
                )
            )

    if coverage_text is not None:
        print(coverage_text)
        if args.coverage_out:
            Path(args.coverage_out).write_text(coverage_text + "\n")

    # A nonzero binary exit is a failed run even when every case that got
    # to print its markers passed (e.g. libcob aborted after the SUMMARY
    # line, or the timeout killed a straggler).
    return 0 if suite_result.all_passed and executed.exit_code == 0 else 1


def _cmd_lint(args: argparse.Namespace) -> int:
    """Run every static refusal check with zero Docker dependency. This
    function must never import mockymock.runtime.docker_toolchain -- that
    structural guarantee (not just documentation) is what makes `lint`
    usable in editors, pre-commit hooks, and CI lanes with no daemon."""
    from mockymock.cli.checks import run_static_checks

    source_path = Path(args.program)
    cut_path = Path(args.cut)
    if not _check_input_files("mockymock lint", source_path, cut_path):
        return 1
    result = run_static_checks(source_path, cut_path, args.copybook_path)
    for problem in result.problems:
        if problem.startswith("  "):
            print(problem)
        else:
            print(f"mockymock lint: {problem}")
    if result.problems:
        problem_count = sum(1 for p in result.problems if not p.startswith("  "))
        print(f"mockymock lint: {problem_count} problem(s) found.")
        return 1
    print("mockymock lint: no problems found.")
    return 0


def _cmd_collect(args: argparse.Namespace) -> int:
    """Authoritative test discovery for editor integrations: parse a .cut
    file (no .cbl, no Docker, no toolchain) and report its suite/cases with
    line numbers and tags. --json emits the machine-readable form the VS
    Code extension consumes; the default is a human-readable listing."""
    import json

    from mockymock.dsl.parser import CutParseError, parse_cut

    cut_path = Path(args.cut)
    if not _check_input_files("mockymock collect", cut_path):
        return 1
    try:
        suite = parse_cut(cut_path.read_text())
    except CutParseError as exc:
        if args.json:
            print(json.dumps({"version": 1, "error": str(exc)}, indent=2))
        else:
            print(f"mockymock collect: invalid .cut file {cut_path}: {exc}")
        return 1

    if args.json:
        payload = {
            "version": 1,
            "cutFile": str(cut_path),
            "suite": {"name": suite.name, "line": suite.line},
            "cases": [
                {"name": case.name, "line": case.line, "tags": list(case.tags)}
                for case in suite.test_cases
            ],
        }
        print(json.dumps(payload, indent=2))
    else:
        print(f"TESTSUITE {suite.name!r} (line {suite.line})")
        for case in suite.test_cases:
            tag_note = f"  [tags: {', '.join(case.tags)}]" if case.tags else ""
            print(f"  TESTCASE {case.name!r} (line {case.line}){tag_note}")
        print(f"{len(suite.test_cases)} test case(s)")
    return 0


def _insert_driver(lines: list[str], artifact) -> list[str]:
    """Insert WORKING-STORAGE additions after that section's header, and
    procedure_lines right after the PROCEDURE DIVISION header."""
    result: list[str] = []
    inserted_ws = False
    inserted_proc = False
    for line in lines:
        result.append(line)
        upper = line.strip().upper()
        if not inserted_ws and upper.startswith("WORKING-STORAGE SECTION"):
            result.extend(
                f"       {ws_line}" for ws_line in artifact.working_storage_lines
            )
            inserted_ws = True
        if not inserted_proc and upper.startswith("PROCEDURE DIVISION"):
            result.append("")
            result.extend(artifact.procedure_lines)
            inserted_proc = True
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mockymock")
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command")

    setup_parser = subparsers.add_parser(
        "setup", help="Build the GnuCOBOL image and start the mockymock-cobc container"
    )
    setup_parser.set_defaults(func=_cmd_setup)

    generate_parser = subparsers.add_parser(
        "generate", help="Scaffold a starter .cut file from a COBOL program"
    )
    generate_parser.add_argument("program")
    generate_parser.add_argument("-o", "--output")
    generate_parser.add_argument(
        "--copybook-path",
        action="append",
        help="Directory to search for copybooks (repeatable)",
    )
    generate_parser.set_defaults(func=_cmd_generate)

    run_parser = subparsers.add_parser(
        "run",
        help="Splice, compile, run, and assert a COBOL program against a .cut file",
    )
    run_parser.add_argument("program")
    run_parser.add_argument("--cut", required=True)
    run_parser.add_argument("--junit-xml")
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
            "coverage after the run (gcov-based; reported against the "
            "instrumented source, not the original .cbl -- see "
            "docs/2026-07-17-coverage-reporting-design.md)"
        ),
    )
    run_parser.add_argument(
        "--coverage-out",
        help="Write the full coverage report (percentage + uncovered lines) to this file",
    )
    run_parser.add_argument(
        "--coverage-json",
        help=(
            "Write machine-readable coverage to this file, remapped onto "
            "the ORIGINAL .cbl's line numbers (splicer-inserted lines "
            "excluded). Implies --coverage"
        ),
    )
    run_parser.set_defaults(func=_cmd_run)

    lint_parser = subparsers.add_parser(
        "lint",
        help=(
            "Run every static refusal check on a program + .cut pair "
            "without Docker (fast, editor/CI friendly)"
        ),
    )
    lint_parser.add_argument("program")
    lint_parser.add_argument("--cut", required=True)
    lint_parser.add_argument(
        "--copybook-path",
        action="append",
        help="Directory to search for copybooks (repeatable)",
    )
    lint_parser.set_defaults(func=_cmd_lint)

    collect_parser = subparsers.add_parser(
        "collect",
        help=(
            "List a .cut file's suite and test cases (names, line numbers, "
            "tags) without running anything"
        ),
    )
    collect_parser.add_argument("--cut", required=True)
    collect_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of the human listing",
    )
    collect_parser.set_defaults(func=_cmd_collect)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 1
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
