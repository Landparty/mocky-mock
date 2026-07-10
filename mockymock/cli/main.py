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
    from cobolparser import parse_cobol
    from cobolparser.preprocess import expand_copybooks, normalize_fixed_format

    from mockymock.analysis.linkage import linkage_plan
    from mockymock.analysis.mock_surface import analyze
    from mockymock.analysis.refusal import (
        check_expansion_warnings,
        check_linkage_layout,
        check_nested_exec,
        check_terminator_layout,
        check_test_case,
        check_unresolved_copybooks,
        check_whole_program,
        find_terminator_plans,
    )
    from mockymock.dsl.parser import CutParseError, parse_cut
    from mockymock.report.formatters import format_console, format_junit_xml
    from mockymock.report.results import parse_stdout
    from mockymock.runtime import docker_toolchain
    from mockymock.runtime.executor import TIMEOUT_EXIT_CODE
    from mockymock.runtime.sandbox import sandbox_dir_maybe_kept
    from mockymock.splicer.driver import build_driver
    from mockymock.splicer.linkage import extra_reset_lines, neutralize
    from mockymock.splicer.naming import TallyRegistry
    from mockymock.splicer.orchestrator import splice_program
    from mockymock.splicer.reset import reset_move_lines
    from mockymock.splicer.source_map import (
        annotate_nested_sites,
        collect_boundaries,
        collect_scope_map,
    )
    from mockymock.splicer.sqlca import transform_data_division_exec

    # Input existence is the one check that runs even before the toolchain
    # comes up: ensure_toolchain can spend minutes building the image, and
    # a typo'd path must not pay that cost (or traceback afterwards).
    source_path = Path(args.program)
    cut_path = Path(args.cut)
    if not _check_input_files("mockymock run", source_path, cut_path):
        return 1

    try:
        docker_toolchain.ensure_toolchain()
    except docker_toolchain.DockerNotAvailableError as exc:
        print(f"mockymock run: {exc}")
        return 1

    raw_source = source_path.read_text()
    if args.copybook_path:
        expansion = expand_copybooks(raw_source, copybook_paths=args.copybook_path)
        expansion_reasons = check_expansion_warnings(expansion)
        for reason in expansion_reasons:
            print(f"mockymock run: refused ({reason.code}): {reason.message}")
        if expansion_reasons:
            return 1
        raw_source = expansion.expanded_source
    result = parse_cobol(raw_source, filename=source_path.name)

    whole_program_reasons = check_whole_program(result)
    for reason in whole_program_reasons:
        print(f"mockymock run: refused ({reason.code}): {reason.message}")
    # The PARSE_ERROR reason only carries a count; print the individual
    # errors too (matching `generate`) so a non-parsing program is
    # diagnosable from the CLI output alone.
    if not result.success:
        for error in result.errors:
            print(f"  {error}")
    if whole_program_reasons:
        return 1

    copybook_reasons = check_unresolved_copybooks(raw_source)
    for reason in copybook_reasons:
        print(f"mockymock run: refused ({reason.code}): {reason.message}")
    if copybook_reasons:
        return 1

    try:
        suite = parse_cut(cut_path.read_text())
    except CutParseError as exc:
        print(f"mockymock run: invalid .cut file {cut_path}: {exc}")
        return 1
    surface = analyze(result.ast)

    normalized = normalize_fixed_format(raw_source.splitlines())
    lines = normalized.splitlines()

    linkage_reasons = check_linkage_layout(result.ast, lines)
    for reason in linkage_reasons:
        print(f"mockymock run: refused ({reason.code}): {reason.message}")
    if linkage_reasons:
        return 1

    # Comment-only, so it never shifts any line number the rest of this
    # pipeline derives from `result.ast`'s locations -- safe to apply here,
    # before every other line-based step. `plan` is None (no-op) for an
    # ordinary CALL-only program.
    linkage = linkage_plan(result.ast)
    if linkage is not None:
        _print_linkage_neutralization("run", linkage, applied=True)
        lines = neutralize(lines, result.ast, linkage)

    # Nested-site spliceability must be annotated before any refusal check
    # or splice looks at nested sites (unannotated nested sites refuse).
    scope_map = collect_scope_map(result.ast, lines)
    annotate_nested_sites(surface, scope_map, lines)

    nested_exec_reasons = check_nested_exec(surface)
    for reason in nested_exec_reasons:
        print(f"mockymock run: refused ({reason.code}): {reason.message}")
    if nested_exec_reasons:
        return 1

    # Pre-check the DATA DIVISION EXEC SQL blocks before doing any work; the
    # actual transform runs after splicing (it inserts/removes lines, which
    # would shift the AST-derived statement spans the splicer relies on).
    _, data_exec_reasons = transform_data_division_exec(
        lines, copybook_paths=args.copybook_path
    )
    for reason in data_exec_reasons:
        print(f"mockymock run: refused ({reason.code}): {reason.message}")
    if data_exec_reasons:
        return 1

    refused = False
    for case in suite.test_cases:
        for reason in check_test_case(surface, result.ast, case):
            print(f"mockymock run: refused ({reason.code}): {reason.message}")
            refused = True
    for reason in check_terminator_layout(surface, result.ast, suite, scope_map, lines):
        print(f"mockymock run: refused ({reason.code}): {reason.message}")
        refused = True
    if refused:
        return 1

    boundaries = collect_boundaries(result.ast)
    registry = TallyRegistry(suite)
    terminator_plans, _ = find_terminator_plans(
        surface, result.ast, suite, scope_map, lines
    )
    lines = splice_program(
        lines, boundaries, surface, suite, registry, terminator_plans
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

        compiled = docker_toolchain.compile_source(instrumented_path)
        if not compiled.success:
            print("mockymock run: compile failed:")
            print(compiled.stderr)
            if args.verbose or args.keep_sandbox:
                print(f"mockymock run: instrumented source at {instrumented_path}")
            return 1

        assert compiled.binary_path is not None  # implied by compiled.success
        executed = docker_toolchain.run_binary(compiled.binary_path)

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

    # A nonzero binary exit is a failed run even when every case that got
    # to print its markers passed (e.g. libcob aborted after the SUMMARY
    # line, or the timeout killed a straggler).
    return 0 if suite_result.all_passed and executed.exit_code == 0 else 1


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
    run_parser.set_defaults(func=_cmd_run)

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
