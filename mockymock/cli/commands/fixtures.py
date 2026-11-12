"""`mockymock fixtures`: a cobol-parser FixtureBundle as JSON for editors."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from mockymock._lines import read_utf8_source
from mockymock.cli._common import _apply_config_to_args, _check_rows_non_negative
from mockymock.debugging_lines import activate_debugging_lines
from mockymock.dsl.fixture_bundle import bundle_dict


def _cmd_fixtures(args: argparse.Namespace) -> int:
    """Print a cobol-parser FixtureBundle as JSON for editor integrations
    (the VS Code tree view consumes this). Unlike every other subcommand,
    stdout must be EXACTLY the JSON document -- every diagnostic, including
    the plain "no such file" gate, goes to stderr instead of the
    `_check_input_files` convention the rest of the CLI uses.

    Runs the same three fail-closed static gates as `_cmd_generate` (minus
    the linkage-layout check, which only matters to the splicer that
    `generate`/`run` feed -- `fixtures` never splices): a lossy copybook
    decode (`check_expansion_warnings`), a clean-looking parse that still
    dropped content (`check_whole_program`'s PARSE_WARNING), and any
    unresolved COPY statement (`check_unresolved_copybooks`). Skipping
    these would let e.g. a COPY-bearing program with no --copybook-path
    silently exit 0 with an empty-fixtures bundle and a coverage summary
    claiming everything resolved -- exactly the input `generate` refuses
    with UNRESOLVED_COPYBOOK, so the two commands must agree."""
    from cobolparser import parse_cobol
    from cobolparser.preprocess import CopybookNotFoundError, expand_copybooks

    from mockymock.analysis.flow_targets import normalize_flow_targets
    from mockymock.analysis.refusal import (
        check_expansion_warnings,
        check_unresolved_copybooks,
        check_whole_program,
    )
    from mockymock.project.discovery import copybook_not_found_hint

    source_path = Path(args.program)
    if not source_path.is_file():
        print(f"mockymock fixtures: no such file: {source_path}", file=sys.stderr)
        return 1

    if not _check_rows_non_negative("fixtures", args.rows):
        return 1

    _apply_config_to_args(args, source_path)

    # Mirrors _cmd_generate's order: expand copybooks (if any --copybook-path
    # was given) before the parse gate below, so the gate sees the same
    # source generate_with_scenarios_from_file will eventually parse itself
    # -- gating on the raw, unexpanded source would let an unresolvable COPY
    # slide past as a no-op (cobolparser tolerates unexpanded COPY under
    # FAIL_FAST) instead of being refused here. generate_with_scenarios_from_file
    # still re-expands and re-parses internally; that duplicate work is the
    # price of a correctness gate rather than one that just happens to work.
    raw_source = read_utf8_source(source_path)
    if args.copybook_path:
        try:
            expansion = expand_copybooks(raw_source, copybook_paths=args.copybook_path)
        except CopybookNotFoundError as exc:
            print(f"mockymock fixtures: {exc}", file=sys.stderr)
            print(copybook_not_found_hint(exc), file=sys.stderr)
            return 1
        except Exception as exc:  # noqa: BLE001 -- surfaced verbatim to the caller
            print(f"mockymock fixtures: {exc}", file=sys.stderr)
            return 1
        expansion_reasons = check_expansion_warnings(expansion)
        for reason in expansion_reasons:
            print(
                f"mockymock fixtures: refused ({reason.code}): {reason.message}",
                file=sys.stderr,
            )
        if expansion_reasons:
            return 1
        raw_source = expansion.expanded_source

    # ProgramFixtureGenerator only raises when the AST comes back None
    # (missing file, unresolved copybook under strict_copybooks). A source
    # file that merely fails to parse (no recognizable COBOL division, bad
    # syntax) still yields a placeholder AST -- generate_with_scenarios_from_file
    # would happily return an empty bundle for it instead of failing, which
    # would look like a real (if boring) program to the VS Code tree view.
    # Parse the (possibly copybook-expanded) source once up front so that
    # case is refused like every other command.
    raw_source = activate_debugging_lines(raw_source)
    result = parse_cobol(raw_source, filename=source_path.name)
    normalize_flow_targets(result.ast)
    if not result.success:
        print(
            f"mockymock fixtures: {len(result.errors)} parse error(s):", file=sys.stderr
        )
        for error in result.errors:
            print(f"  {error}", file=sys.stderr)
        return 1

    # success=True is not enough: cobolparser reports dropped statements
    # (unsupported verbs, multi-program units, unparsed clause leftovers)
    # as warnings on an otherwise clean parse. A bundle built from an
    # incomplete AST would silently miss boundaries, so refuse -- same
    # check _cmd_generate runs on the same signal.
    warning_reasons = check_whole_program(result)
    for reason in warning_reasons:
        print(
            f"mockymock fixtures: refused ({reason.code}): {reason.message}",
            file=sys.stderr,
        )
    if warning_reasons:
        return 1

    copybook_reasons = check_unresolved_copybooks(raw_source)
    for reason in copybook_reasons:
        print(
            f"mockymock fixtures: refused ({reason.code}): {reason.message}",
            file=sys.stderr,
        )
    if copybook_reasons:
        return 1

    from mockymock.dsl.entry_parameters import fixture_generator

    generator = fixture_generator(args.rows)
    try:
        bundle = generator.generate_with_scenarios_from_file(
            str(source_path),
            copybook_paths=args.copybook_path,
            mode=args.scenarios,
            seed=args.seed,
        )
    except CopybookNotFoundError as exc:
        print(f"mockymock fixtures: {exc}", file=sys.stderr)
        print(copybook_not_found_hint(exc), file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 -- surfaced verbatim to the caller
        print(f"mockymock fixtures: {exc}", file=sys.stderr)
        return 1
    # Always the version 1 shape mocky-mock documents and reads, whatever
    # version the installed cobol-parser writes by default (#461).
    print(json.dumps(bundle_dict(bundle), indent=2))
    return 0


def register_fixtures(subparsers: argparse._SubParsersAction) -> None:
    """Add `mockymock fixtures` to the top-level parser."""
    fixtures_parser = subparsers.add_parser(
        "fixtures",
        help=(
            "Print a FixtureBundle (scenarios, mock data, expectations) as "
            "JSON for editor integrations"
        ),
    )
    fixtures_parser.add_argument("program")
    fixtures_parser.add_argument(
        "--scenarios",
        choices=["happy", "branches", "all"],
        default="happy",
        help="Which scenario set to generate (default happy)",
    )
    fixtures_parser.add_argument("--seed", type=int, help="Deterministic RNG seed")
    fixtures_parser.add_argument(
        "--rows",
        type=int,
        help=(
            "Rows to generate per data table (generator default). A "
            "scenario family that pins its own row count (e.g. "
            "--scenarios all's fixed 'empty input' family) ignores this "
            "and always generates zero rows for that scenario"
        ),
    )
    fixtures_parser.add_argument(
        "--copybook-path",
        action="append",
        help="Directory to search for copybooks (repeatable)",
    )
    fixtures_parser.add_argument(
        "--extra-copybook-path",
        action="append",
        help=(
            "Directory to search for copybooks after the --copybook-path / "
            "config file list (repeatable; adds to it instead of replacing it)"
        ),
    )
    fixtures_parser.set_defaults(func=_cmd_fixtures)
