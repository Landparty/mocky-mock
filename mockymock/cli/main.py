"""mockymock CLI entry point: `main()`.

The parser is built in `mockymock/cli/parser.py`, from each subcommand's
own `register_<name>` in `mockymock/cli/commands/`, next to its `_cmd_*`
handler. A few names are re-exported here for callers that import them
from `mockymock.cli.main`."""

from __future__ import annotations

import argparse
import sys

from mockymock.cli._common import _apply_config_to_args as _apply_config_to_args
from mockymock.cli._common import _resolve_program_and_cut as _resolve_program_and_cut
from mockymock.cli._common import _write_report_file as _write_report_file
from mockymock.cli.commands.collect import (
    _cmd_collect,
    _print_command_error,
)
from mockymock.cli.commands.collect import _collect_boundaries as _collect_boundaries
from mockymock.cli.commands.environment import _cmd_doctor
from mockymock.cli.commands.fixtures import _cmd_fixtures
from mockymock.cli.commands.run import (
    _can_rerun_left_over_cases as _can_rerun_left_over_cases,
)
from mockymock.cli.commands.run import _cmd_run_suite as _cmd_run_suite
from mockymock.cli.commands.run import (
    _compile_failure_diagnosis as _compile_failure_diagnosis,
)
from mockymock.cli.commands.run import _merge_rerun_reports as _merge_rerun_reports
from mockymock.cli.commands.run import _per_pair_report_path as _per_pair_report_path
from mockymock.cli.parser import build_parser as build_parser


def _subcommand_names(parser: argparse.ArgumentParser) -> list[str]:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return list(action.choices)
    return []


def _reject_unknown_command(
    parser: argparse.ArgumentParser, argv: list[str]
) -> int | None:
    """Exit status 2 with a "did you mean" line when the first word is not a
    command; None when it is (or there is none). argparse's own message
    listed all twenty choices and suggested nothing."""
    import difflib

    first = next((a for a in argv if not a.startswith("-")), None)
    names = _subcommand_names(parser)
    if first is None or first in names:
        return None
    if (
        argv
        and argv[0].startswith("-")
        and argv[0] not in ("-h", "--help", "--version")
    ):
        return None  # a bad top-level flag: argparse's own message names it
    close = difflib.get_close_matches(first, names, n=1, cutoff=0.6)
    hint = f" (did you mean '{close[0]}'?)" if close else ""
    print(
        f"mockymock: unknown command '{first}'{hint}\n"
        "Run 'mockymock --help' to list every command.",
        file=sys.stderr,
    )
    return 2


def _parse_command_line(
    parser: argparse.ArgumentParser, argv: list[str] | None
) -> argparse.Namespace:
    """`parser.parse_args`, with a pointer to --cut when the stray argument
    is a .cut file (`mockymock run PROG.cbl PROG.cut`)."""
    args, extras = parser.parse_known_args(argv)
    if extras:
        cut = next((e for e in extras if e.lower().endswith(".cut")), None)
        message = f"unrecognized arguments: {' '.join(extras)}"
        if cut is not None:
            message += f" (to name the test file, use --cut {cut})"
        command = getattr(args, "command", None)
        sub = dict.fromkeys(_subcommand_names(parser))
        if command in sub:
            for action in parser._actions:
                if isinstance(action, argparse._SubParsersAction):
                    action.choices[command].error(message)
        parser.error(message)
    return args


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        # The real command line: a runner that times this process out
        # must not leave its cobc / test binary running.
        from mockymock.runtime.native_toolchain import install_termination_handler

        install_termination_handler()
    parser = build_parser()
    command_line = sys.argv[1:] if argv is None else argv
    if not command_line:
        parser.print_help()
        return 2
    rejected = _reject_unknown_command(parser, command_line)
    if rejected is not None:
        return rejected
    try:
        args = _parse_command_line(parser, argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1
    if not hasattr(args, "func"):
        parser.print_help()
        return 1

    from mockymock.project.config import ConfigError, load_config

    try:
        args._config = load_config()
    except ConfigError as exc:
        args._config = None
        # Only a subcommand that would actually read the config fails on
        # a malformed one. `collect`/`setup`/`dashboard`/... run on with
        # defaults, and `doctor` re-loads it itself to report the error
        # as a WARN check (that is the situation it exists to explain).
        consumes_config = (
            hasattr(args, "copybook_path") or hasattr(args, "seed")
        ) and args.func is not _cmd_doctor
        if consumes_config:
            if args.func is _cmd_collect and getattr(args, "json", False):
                import json

                # `collect --json` promises machine-readable stdout on
                # every failure (the VS Code extension parses it).
                print(json.dumps({"version": 1, "error": str(exc)}, indent=2))
            elif args.func is _cmd_fixtures:
                # `fixtures` keeps stdout JSON-only; errors go to stderr.
                print(str(exc), file=sys.stderr)
            else:
                print(str(exc))
            return 1

    from mockymock._lines import SourceEncodingError
    from mockymock.runtime.toolchain import ToolchainNotAvailableError

    try:
        return args.func(args)
    except SourceEncodingError as exc:
        # A non-UTF-8 .cbl/.cut: one clean line in each command's own
        # error convention instead of a UnicodeDecodeError traceback.
        _print_command_error(args, str(exc))
        return 1
    except ToolchainNotAvailableError as exc:
        # Most commands report this themselves; one raised before they
        # can (MOCKYMOCK_TOOLCHAIN=bogus) was a traceback.
        _print_command_error(args, str(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
