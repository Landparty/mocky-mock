"""mockymock CLI entry point."""

from __future__ import annotations

import argparse
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
        f"mockymock setup: container {docker_toolchain.CONTAINER} ready "
        f"({version})"
    )
    return 0


def _cmd_generate(args: argparse.Namespace) -> int:
    from cobolparser import parse_cobol
    from cobolparser.preprocess import expand_copybooks

    from mockymock.analysis.mock_surface import analyze
    from mockymock.analysis.refusal import check_unresolved_copybooks
    from mockymock.dsl.generator import scaffold_cut

    source_path = Path(args.program)
    raw_source = source_path.read_text()
    if args.copybook_path:
        expansion = expand_copybooks(raw_source, copybook_paths=args.copybook_path)
        raw_source = expansion.expanded_source
    result = parse_cobol(raw_source, filename=source_path.name)
    if not result.success:
        print(f"mockymock generate: {len(result.errors)} parse error(s):")
        for error in result.errors:
            print(f"  {error}")
        return 1

    copybook_reasons = check_unresolved_copybooks(raw_source)
    for reason in copybook_reasons:
        print(f"mockymock generate: refused ({reason.code}): {reason.message}")
    if copybook_reasons:
        return 1

    surface = analyze(result.ast)
    cut_text = scaffold_cut(result.ast.program_name, surface)

    output_path = Path(args.output) if args.output else source_path.with_suffix(".cut")
    output_path.write_text(cut_text)
    print(
        f"mockymock generate: wrote {len(surface.static_call_sites())} "
        f"test case(s) -> {output_path}"
    )
    _report_unsupported_boundaries(surface)
    return 0


def _report_unsupported_boundaries(surface) -> None:
    """Name every detected boundary point v1 cannot mock, so the scaffold is
    never mistaken for complete coverage of the program's outputs. Test cases
    whose PERFORM target reaches one of these are refused by `run`."""
    findings: list[str] = []
    for site in surface.dynamic_call_sites():
        findings.append(
            f"dynamic CALL in paragraph '{site.paragraph_name}' (line {site.line})"
        )
    findings.extend(
        f"file I/O in paragraph '{name}'"
        for name in sorted(surface.file_io_paragraphs)
    )
    findings.extend(
        f"EXEC SQL/CICS/DLI in paragraph '{name}'"
        for name in sorted(surface.exec_paragraphs)
    )
    findings.extend(
        f"console ACCEPT in paragraph '{name}'"
        for name in sorted(surface.console_accept_paragraphs)
    )
    if not findings:
        return
    print(
        f"mockymock generate: {len(findings)} boundary point(s) detected that "
        f"are not mockable in v1 (test cases reaching them will be refused):"
    )
    for finding in findings:
        print(f"  - {finding}")


def _cmd_run(args: argparse.Namespace) -> int:
    from cobolparser import parse_cobol
    from cobolparser.preprocess import expand_copybooks, normalize_fixed_format

    from mockymock.analysis.mock_surface import analyze
    from mockymock.analysis.refusal import (
        check_nested_exec,
        check_test_case,
        check_unresolved_copybooks,
        check_whole_program,
    )
    from mockymock.dsl.parser import parse_cut
    from mockymock.report.formatters import format_console, format_junit_xml
    from mockymock.report.results import parse_stdout
    from mockymock.runtime import docker_toolchain
    from mockymock.runtime.sandbox import sandbox_dir
    from mockymock.splicer.driver import build_driver
    from mockymock.splicer.naming import TallyRegistry
    from mockymock.splicer.orchestrator import splice_program
    from mockymock.splicer.reset import reset_move_lines
    from mockymock.splicer.source_map import collect_boundaries
    from mockymock.splicer.sqlca import transform_data_division_exec

    try:
        docker_toolchain.ensure_toolchain()
    except docker_toolchain.DockerNotAvailableError as exc:
        print(f"mockymock run: {exc}")
        return 1

    source_path = Path(args.program)
    raw_source = source_path.read_text()
    if args.copybook_path:
        expansion = expand_copybooks(raw_source, copybook_paths=args.copybook_path)
        raw_source = expansion.expanded_source
    result = parse_cobol(raw_source, filename=source_path.name)

    for reason in check_whole_program(result):
        print(f"mockymock run: refused ({reason.code}): {reason.message}")
    if not result.success:
        return 1

    copybook_reasons = check_unresolved_copybooks(raw_source)
    for reason in copybook_reasons:
        print(f"mockymock run: refused ({reason.code}): {reason.message}")
    if copybook_reasons:
        return 1

    suite = parse_cut(Path(args.cut).read_text())
    surface = analyze(result.ast)

    nested_exec_reasons = check_nested_exec(surface)
    for reason in nested_exec_reasons:
        print(f"mockymock run: refused ({reason.code}): {reason.message}")
    if nested_exec_reasons:
        return 1

    normalized = normalize_fixed_format(raw_source.splitlines())
    lines = normalized.splitlines()

    # Pre-check the DATA DIVISION EXEC SQL blocks before doing any work; the
    # actual transform runs after splicing (it inserts/removes lines, which
    # would shift the AST-derived statement spans the splicer relies on).
    _, data_exec_reasons = transform_data_division_exec(lines)
    for reason in data_exec_reasons:
        print(f"mockymock run: refused ({reason.code}): {reason.message}")
    if data_exec_reasons:
        return 1

    refused = False
    for case in suite.test_cases:
        for reason in check_test_case(surface, result.ast, case):
            print(f"mockymock run: refused ({reason.code}): {reason.message}")
            refused = True
    if refused:
        return 1

    boundaries = collect_boundaries(result.ast)
    registry = TallyRegistry(suite)
    lines = splice_program(lines, boundaries, surface, suite, registry)
    lines, _ = transform_data_division_exec(lines)

    reset_lines = reset_move_lines(result.ast)
    artifact = build_driver(suite, reset_lines, registry)

    instrumented = _insert_driver(lines, artifact)

    with sandbox_dir(root=docker_toolchain.WORK_ROOT) as tmp:
        instrumented_path = tmp / source_path.with_suffix(".cbl").name
        instrumented_path.write_text(
            "\n".join(instrumented) + "\n", newline="\n"
        )

        compiled = docker_toolchain.compile_source(instrumented_path)
        if not compiled.success:
            print("mockymock run: compile failed:")
            print(compiled.stderr)
            return 1

        executed = docker_toolchain.run_binary(compiled.binary_path)

    suite_result = parse_stdout(executed.stdout)
    print(format_console(suite_result))

    if args.junit_xml:
        Path(args.junit_xml).write_text(format_junit_xml(suite_result))

    return 0 if suite_result.all_passed else 1


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
            result.extend(f"       {ws_line}" for ws_line in artifact.working_storage_lines)
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
        "run", help="Splice, compile, run, and assert a COBOL program against a .cut file"
    )
    run_parser.add_argument("program")
    run_parser.add_argument("--cut", required=True)
    run_parser.add_argument("--junit-xml")
    run_parser.add_argument(
        "--copybook-path",
        action="append",
        help="Directory to search for copybooks (repeatable)",
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
