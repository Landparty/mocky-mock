"""mockymock CLI entry point."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from mockymock import __version__


def _cmd_setup(args: argparse.Namespace) -> int:
    from mockymock.runtime.gnucobol_bootstrap import (
        GnuCobolNotFoundError,
        bootstrap,
    )

    try:
        info = bootstrap()
    except GnuCobolNotFoundError as exc:
        print(f"mockymock setup: {exc}")
        return 1
    print(f"mockymock setup: found cobc at {info.path} ({info.version})")
    return 0


def _cmd_generate(args: argparse.Namespace) -> int:
    from cobolparser import parse_cobol

    from mockymock.analysis.mock_surface import analyze
    from mockymock.dsl.generator import scaffold_cut

    source_path = Path(args.program)
    result = parse_cobol(source_path.read_text(), filename=source_path.name)
    if not result.success:
        print(f"mockymock generate: {len(result.errors)} parse error(s):")
        for error in result.errors:
            print(f"  {error}")
        return 1

    surface = analyze(result.ast)
    cut_text = scaffold_cut(result.ast.program_name, surface)

    output_path = Path(args.output) if args.output else source_path.with_suffix(".cut")
    output_path.write_text(cut_text)
    print(
        f"mockymock generate: wrote {len(surface.static_call_sites())} "
        f"test case(s) -> {output_path}"
    )
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    from cobolparser import parse_cobol
    from cobolparser.preprocess import normalize_fixed_format

    from mockymock.analysis.mock_surface import analyze
    from mockymock.analysis.refusal import check_test_case, check_whole_program
    from mockymock.dsl.parser import parse_cut
    from mockymock.report.formatters import format_console, format_junit_xml
    from mockymock.report.results import parse_stdout
    from mockymock.runtime.compiler import compile_source
    from mockymock.runtime.executor import run_binary
    from mockymock.runtime.sandbox import sandbox_dir
    from mockymock.splicer.driver import build_driver
    from mockymock.splicer.reset import reset_move_lines
    from mockymock.splicer.source_map import collect_boundaries

    source_path = Path(args.program)
    raw_source = source_path.read_text()
    result = parse_cobol(raw_source, filename=source_path.name)

    for reason in check_whole_program(result):
        print(f"mockymock run: refused ({reason.code}): {reason.message}")
    if not result.success:
        return 1

    suite = parse_cut(Path(args.cut).read_text())
    surface = analyze(result.ast)

    refused = False
    for case in suite.test_cases:
        mocked_names = {m.program_name for m in case.mocks}
        for reason in check_test_case(
            surface, result.ast, case.perform_target, mocked_names
        ):
            print(f"mockymock run: refused ({reason.code}): {reason.message}")
            refused = True
    if refused:
        return 1

    normalized = normalize_fixed_format(raw_source.splitlines())
    lines = normalized.splitlines()
    boundaries = collect_boundaries(result.ast)

    mocked_call_names = sorted(
        {m.program_name for case in suite.test_cases for m in case.mocks}
    )
    lines = _splice_call_sites(
        lines, boundaries, result.ast, surface, suite, mocked_call_names
    )

    reset_lines = reset_move_lines(result.ast)
    artifact = build_driver(suite, reset_lines, mocked_call_names)

    instrumented = _insert_driver(lines, artifact)

    with sandbox_dir() as tmp:
        instrumented_path = tmp / source_path.with_suffix(".cbl").name
        instrumented_path.write_text("\n".join(instrumented) + "\n")

        compiled = compile_source(instrumented_path)
        if not compiled.success:
            print("mockymock run: compile failed:")
            print(compiled.stderr)
            return 1

        executed = run_binary(compiled.binary_path)

    suite_result = parse_stdout(executed.stdout)
    print(format_console(suite_result))

    if args.junit_xml:
        Path(args.junit_xml).write_text(format_junit_xml(suite_result))

    return 0 if suite_result.all_passed else 1


def _splice_call_sites(
    lines: list[str],
    boundaries: list[int],
    program,
    surface,
    suite,
    mocked_call_names: list[str],
) -> list[str]:
    """Replace every static CALL statement to a mocked program with its
    EVALUATE UT-CURRENT-CASE dispatch block.

    All spans are computed up front from the original (pre-splice)
    `boundaries`/statement locations, then applied to `lines` in descending
    start-line order. Applying bottom-up keeps every not-yet-applied span's
    line numbers valid: `comment_and_replace` returns a list that has grown
    by `len(replacement)` lines, which would silently shift every later
    (higher-line-number) span if splices were applied top-down instead --
    verified concretely during Task 14 review: a second top-down splice
    landed one line short and commented out the following paragraph's
    header instead of its CALL statement.

    A paragraph can contain more than one static CALL to the same mocked
    program (e.g. two separate `CALL "X"` lines in one paragraph). Because
    the outer loop matches `MockSurface.static_call_sites()` by
    `paragraph_name` alone (one surface entry per call site) and the inner
    loop then re-scans every statement in that paragraph, naively appending
    a span per (site, matching statement) pair double-, triple-, or
    quadruple-counts the same statement once per site sharing its
    paragraph. `seen_statement_ids` dedupes by `id(statement)` so each
    physical CALL gets exactly one span regardless of how many sites in
    that paragraph reference it.
    """
    from mockymock.splicer.injector import build_call_dispatch
    from mockymock.splicer.source_map import statement_span
    from mockymock.splicer.stub_writer import comment_and_replace

    last_line = len(lines)
    spans: list[tuple[int, int, list[str]]] = []
    seen_statement_ids: set[int] = set()
    for call_name in mocked_call_names:
        for site in surface.static_call_sites():
            if site.program_name != call_name:
                continue
            for paragraph in _paragraphs_by_name(program):
                if paragraph.paragraph_name != site.paragraph_name:
                    continue
                for statement in paragraph.statements:
                    if (
                        getattr(statement, "called_program", None) != call_name
                        or statement.is_dynamic
                        or id(statement) in seen_statement_ids
                    ):
                        continue
                    seen_statement_ids.add(id(statement))
                    start, end = statement_span(statement, boundaries, last_line)
                    replacement = build_call_dispatch(call_name, suite)
                    spans.append((start, end, replacement))

    for start, end, replacement in sorted(spans, key=lambda s: s[0], reverse=True):
        lines = comment_and_replace(lines, start, end, replacement)
    return lines


def _paragraphs_by_name(program):
    from mockymock.analysis.mock_surface import _all_paragraphs

    procedure = program.get_division("PROCEDURE")
    return _all_paragraphs(procedure) if procedure else []


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
        "setup", help="Detect or install GnuCOBOL (cobc)"
    )
    setup_parser.set_defaults(func=_cmd_setup)

    generate_parser = subparsers.add_parser(
        "generate", help="Scaffold a starter .cut file from a COBOL program"
    )
    generate_parser.add_argument("program")
    generate_parser.add_argument("-o", "--output")
    generate_parser.set_defaults(func=_cmd_generate)

    run_parser = subparsers.add_parser(
        "run", help="Splice, compile, run, and assert a COBOL program against a .cut file"
    )
    run_parser.add_argument("program")
    run_parser.add_argument("--cut", required=True)
    run_parser.add_argument("--junit-xml")
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
