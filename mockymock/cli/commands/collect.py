"""`mockymock collect` (test discovery for editors) and `explain` (refusal codes).

Also holds `_print_command_error`, the per-command fatal-error printer
`main` and `collect` share (it compares `args.func` against
`_cmd_collect`/`_cmd_fixtures`, so it lives next to them)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from mockymock._lines import read_utf8_source
from mockymock.cli._common import _apply_config_to_args, _check_input_files
from mockymock.cli.commands.fixtures import _cmd_fixtures
from mockymock.debugging_lines import activate_debugging_lines


def _collect_boundaries(
    source_path: Path, copybook_paths: list[str] | None
) -> list[dict]:
    """Every genuinely mockable boundary site in `source_path` (category
    is not None), whole-program -- NOT reachability-filtered by any one
    TESTCASE's PERFORM target, since this feeds editor completion for
    "every key this program could ever need mocked," not one particular
    test case's own reachable set (that's what `lint`'s refusal gate is
    for). Sites are returned in source order. See
    docs/2026-09-15-cut-editor-intelligence-design.md."""
    from cobolparser import parse_cobol
    from cobolparser.preprocess import expand_copybooks

    from mockymock.analysis.flow_targets import normalize_flow_targets
    from mockymock.analysis.mock_surface import analyze
    from mockymock.dsl.generator import directive_snippet

    raw_source = read_utf8_source(source_path)
    # `line` is shown against the .cbl the user has open, but sites are
    # numbered in the EXPANDED source: every COPY above a site shifted it
    # by the copybook's length (a 4-line WORKING-STORAGE copybook put a
    # line-9 CALL at "line 12"). Map back through cobol-parser's source map
    # where the installed release fills one in (1.8.x returns it empty,
    # and the expanded numbering is then kept as before).
    origin_line: dict[int, int] = {}
    if copybook_paths:
        expansion = expand_copybooks(
            raw_source, copybook_paths=copybook_paths, preserve_source_locations=True
        )
        raw_source = expansion.expanded_source
        origin_line = _main_file_lines(expansion.source_location_map or {})

    raw_source = activate_debugging_lines(raw_source)
    result = parse_cobol(raw_source, filename=source_path.name)
    normalize_flow_targets(result.ast)
    if result.errors or result.ast is None:
        raise ValueError(
            "; ".join(str(error) for error in result.errors) or "parse failed"
        )

    surface = analyze(result.ast)
    boundaries = []
    for site in surface.boundary_sites:
        if site.category is None:
            continue
        # `directive` is the exact MOCK header a scaffold would write for
        # this site (quoted key for CALL/MQ/SQL/CICS/DLI, the shortest
        # unique text prefix for SQL/CICS/DLI whose `key` is null) -- so
        # a consumer inserts what the DSL parses rather than re-deriving
        # the quoting rules. None when the scaffold itself would skip it.
        snippet = directive_snippet(site, surface)
        boundaries.append(
            {
                "category": site.category.value,
                "key": site.keys[0] if site.keys else None,
                "keys": list(site.keys),
                "directive": snippet.splitlines()[0].strip() if snippet else None,
                "label": site.label,
                "paragraph": site.paragraph_name,
                "line": origin_line.get(site.line, site.line),
                "matchText": site.match_text,
            }
        )
    return sorted(boundaries, key=lambda b: b["line"])


def _main_file_lines(source_map: dict[int, tuple[str, int]]) -> dict[int, int]:
    """Expanded line -> line of the program file itself, from a
    `CopybookExpansion.source_location_map` (`<main>` entries are the
    program's own lines). A line that came from a copybook maps to the
    COPY statement that pulled it in: the first program line after the
    last one emitted before it."""
    mapping: dict[int, int] = {}
    last_main = 0
    for expanded in sorted(source_map):
        origin_file, origin = source_map[expanded]
        if origin_file == "<main>":
            last_main = origin
            mapping[expanded] = origin
        else:
            mapping[expanded] = last_main + 1
    return mapping


def _cmd_explain(args: argparse.Namespace) -> int:
    """`mockymock explain <CODE>`: print (or list) the catalogued
    explanation for a refusal code, so `.cut` authors and editor
    tooltips get one shared source of truth instead of re-deriving what
    a code means from the message text alone. See
    docs/2026-09-15-cut-editor-intelligence-design.md."""
    import json

    from mockymock.analysis.refusal import REFUSAL_EXPLANATIONS

    if args.code is None or args.list:
        codes = sorted(REFUSAL_EXPLANATIONS)
        if args.json:
            print(json.dumps({"version": 1, "codes": codes}, indent=2))
        else:
            print(f"{len(codes)} catalogued refusal code(s):")
            for code in codes:
                print(f"  {code}")
        return 0

    code = args.code.upper()
    explanation = REFUSAL_EXPLANATIONS.get(code)
    if explanation is None:
        if args.json:
            print(
                json.dumps(
                    {
                        "version": 1,
                        "code": code,
                        "error": "not catalogued",
                        "knownCodes": sorted(REFUSAL_EXPLANATIONS),
                    },
                    indent=2,
                )
            )
        else:
            print(f"mockymock explain: {code!r} is not a catalogued refusal code.")
            print("Run 'mockymock explain --list' to see every code this covers.")
        return 1

    if args.json:
        print(
            json.dumps(
                {"version": 1, "code": code, "explanation": explanation}, indent=2
            )
        )
    else:
        print(code)
        print(f"  {explanation}")
        print("  See .okf/analysis.md's refusal table for the full picture.")
    return 0


def _cmd_collect(args: argparse.Namespace) -> int:
    """Authoritative test discovery for editor integrations: parse a .cut
    file (no .cbl, no Docker, no toolchain) and report its suite/cases with
    line numbers and tags. --json emits the machine-readable form the VS
    Code extension consumes; the default is a human-readable listing.

    --boundaries (2026-09-15) additionally reports every mockable boundary
    site in the paired program -- see docs/2026-09-15-cut-editor-intelligence-design.md.
    Requires --json and a program argument (no human-readable form is
    planned for it). The boundaries are the program's, whatever state the
    suite is in: --cut may be omitted, and a .cut that fails to parse (a
    half-written MOCK block in an editor) still gets them, beside the
    `error` (mocky-mock-vscode#100)."""
    import json

    from mockymock.dsl.parser import CutParseError, parse_cut

    if args.boundaries and not args.json:
        print("mockymock collect: --boundaries requires --json")
        return 1
    if args.boundaries and not args.program:
        # With --json every failure is a JSON error object on stdout: the
        # VS Code extension parses it (issue #309).
        _print_command_error(args, "--boundaries requires a program argument")
        return 1
    if args.cut is None and not args.boundaries:
        _print_command_error(
            args, "--cut is required (it may be omitted only with --boundaries)"
        )
        return 1

    cut_path = Path(args.cut) if args.cut is not None else None
    check_paths = [cut_path] if cut_path is not None else []
    program_path = Path(args.program) if args.program else None
    if program_path is not None:
        check_paths.append(program_path)
    if args.json:
        missing = [path for path in check_paths if not path.is_file()]
        if missing:
            _print_command_error(
                args, "; ".join(f"no such file: {path}" for path in missing)
            )
            return 1
    elif not _check_input_files("mockymock collect", *check_paths):
        return 1
    suite = None
    suite_error: str | None = None
    if cut_path is not None:
        try:
            suite = parse_cut(read_utf8_source(cut_path))
        except CutParseError as exc:
            if not args.boundaries:
                if args.json:
                    print(json.dumps({"version": 1, "error": str(exc)}, indent=2))
                else:
                    print(f"mockymock collect: invalid .cut file {cut_path}: {exc}")
                return 1
            suite_error = str(exc)

    boundaries = None
    if args.boundaries:
        assert program_path is not None  # checked above
        # Same copybook lookup lint/run use (config file + the program's
        # copybooks/ folder): without it a site inside a copybook vanished
        # from the list and completion offered nothing for it (issue #200).
        _apply_config_to_args(args, program_path)
        try:
            boundaries = _collect_boundaries(program_path, args.copybook_path)
        except Exception as exc:  # noqa: BLE001 -- surfaced verbatim to the caller
            print(json.dumps({"version": 1, "error": str(exc)}, indent=2))
            return 1

    if args.json:
        payload: dict[str, object] = {
            "version": 1,
            "cutFile": str(cut_path) if cut_path is not None else None,
            "suite": (
                {"name": suite.name, "line": suite.line} if suite is not None else None
            ),
            "cases": [
                {"name": case.name, "line": case.line, "tags": list(case.tags)}
                for case in (suite.test_cases if suite is not None else [])
            ],
        }
        if suite_error is not None:
            payload["error"] = suite_error
        if boundaries is not None:
            payload["boundaries"] = boundaries
        print(json.dumps(payload, indent=2))
        return 1 if suite_error is not None else 0
    else:
        assert suite is not None  # --cut is required without --boundaries
        print(f"TESTSUITE {suite.name!r} (line {suite.line})")
        for case in suite.test_cases:
            tag_note = f"  [tags: {', '.join(case.tags)}]" if case.tags else ""
            print(f"  TESTCASE {case.name!r} (line {case.line}){tag_note}")
        print(f"{len(suite.test_cases)} test case(s)")
    return 0


def _print_command_error(args: argparse.Namespace, message: str) -> None:
    """Print a fatal error the way `main`'s config-error path does:
    `collect --json` as a JSON error object on stdout (the VS Code
    extension parses it), `fixtures` on stderr (its stdout is JSON-only),
    everything else as a plain `mockymock <command>:` line on stdout."""
    if args.func is _cmd_collect and getattr(args, "json", False):
        import json

        print(json.dumps({"version": 1, "error": message}, indent=2))
    elif args.func is _cmd_fixtures:
        print(f"mockymock fixtures: {message}", file=sys.stderr)
    else:
        print(f"mockymock {args.command}: {message}")
