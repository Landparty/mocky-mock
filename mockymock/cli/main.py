"""mockymock CLI entry point.

Holds `main()` and `build_parser()` (with its help-polish helpers).
Each subcommand's `_cmd_*` lives in `mockymock/cli/commands/` and the
helpers they share in `mockymock/cli/_common.py`; they are imported
here so `build_parser`'s `set_defaults(func=...)` and `main()`'s
`args.func is ...` checks resolve through this module's globals, and
re-exported for callers that import them from `mockymock.cli.main`."""

from __future__ import annotations

import argparse
import math
import re
import sys

from mockymock import __version__
from mockymock.cli._common import _apply_config_to_args as _apply_config_to_args
from mockymock.cli._common import _resolve_program_and_cut as _resolve_program_and_cut
from mockymock.cli._common import _write_report_file as _write_report_file
from mockymock.cli.commands.analyze import _cmd_analyze
from mockymock.cli.commands.clean import _cmd_clean
from mockymock.cli.commands.collect import (
    _cmd_collect,
    _cmd_explain,
    _print_command_error,
)
from mockymock.cli.commands.collect import _collect_boundaries as _collect_boundaries
from mockymock.cli.commands.debug import _cmd_debug
from mockymock.cli.commands.environment import _cmd_dashboard, _cmd_doctor, _cmd_setup
from mockymock.cli.commands.export import _cmd_export
from mockymock.cli.commands.fixtures import _cmd_fixtures
from mockymock.cli.commands.generate import _cmd_generate
from mockymock.cli.commands.init import _cmd_init
from mockymock.cli.commands.job import _cmd_job
from mockymock.cli.commands.journal import _cmd_journal
from mockymock.cli.commands.lint import _cmd_lint
from mockymock.cli.commands.mutate import _cmd_mutate
from mockymock.cli.commands.report import _cmd_report
from mockymock.cli.commands.run import (
    _can_rerun_left_over_cases as _can_rerun_left_over_cases,
)
from mockymock.cli.commands.run import _cmd_run
from mockymock.cli.commands.run import _cmd_run_suite as _cmd_run_suite
from mockymock.cli.commands.run import (
    _compile_failure_diagnosis as _compile_failure_diagnosis,
)
from mockymock.cli.commands.run import _merge_rerun_reports as _merge_rerun_reports
from mockymock.cli.commands.run import _per_pair_report_path as _per_pair_report_path
from mockymock.cli.commands.runner import _cmd_runner
from mockymock.cli.commands.skills import (
    _cmd_skills_install,
    _cmd_skills_mode,
    _cmd_skills_plugin,
)
from mockymock.cli.commands.suites import _cmd_suites


def _timeout_seconds(value: str) -> int:
    """argparse `type=` for `--timeout`: a whole number of seconds, at
    least 1. coreutils `timeout 0` disables the container-side kill, so a
    hung binary outlived its `docker exec` as an orphan at 100% CPU, and a
    negative value made `timeout` itself fail with exit 125 (issue
    #306)."""
    try:
        seconds = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid int value: {value!r}") from None
    if seconds < 1:
        raise argparse.ArgumentTypeError("--timeout must be at least 1 second")
    return seconds


def _percent(value: str) -> float:
    """argparse `type=` for a percentage gate (`--coverage-fail-under`,
    `--fail-under`): a finite number from 0 to
    100. A plain `type=float` took `nan` -- every `<` comparison with it
    is false, so `--coverage-fail-under nan` silently never failed, and
    `mutate --fail-under nan` crashed with a traceback after the whole
    mutation run -- and took `150`, a gate no suite can ever pass."""
    try:
        number = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid number: {value!r}") from None
    if not math.isfinite(number) or not 0 <= number <= 100:
        raise argparse.ArgumentTypeError(
            f"must be a percentage from 0 to 100, got {value!r}"
        )
    return number


def _positive_seconds(value: str) -> float:
    """argparse `type=` for the runner's `--poll-interval` and
    `--suite-timeout`: a finite number of seconds above 0. A negative
    poll interval crashed the runner on its first idle `sleep()`, 0 made
    it claim jobs in a busy loop against the backend, and a timeout of 0
    or less killed every suite before it started."""
    try:
        seconds = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid number: {value!r}") from None
    if not math.isfinite(seconds) or seconds <= 0:
        raise argparse.ArgumentTypeError(
            f"must be a number of seconds above 0, got {value!r}"
        )
    return seconds


# argparse has no native notion of subcommand groups, so this is a
# formatted epilog block rather than a real grouping structure --
# purely presentational, and updated by hand whenever a subcommand is
# added or removed. See docs/2026-09-15-cli-ergonomics-design.md.
_COMMAND_GROUPS_EPILOG = """\
commands, grouped by how often you'll reach for them:

  Everyday:
    init       one command from a program to a .cut file with real assertions
    run        splice, compile, run, and assert a program against a .cut file
    generate   scaffold a starter .cut file from a COBOL program
    lint       static checks only, no Docker
    collect    list a .cut file's suite and test cases
    suites     which program each .cut suite tests, no Docker

  Diagnosing a failure:
    doctor     one-shot terminal readiness report (start here)
    explain    what a refusal code means and how to fix it
    debug      interactive Debug Adapter Protocol session
    analyze    run a cobol-parser analyzer and print its report
    dashboard  local status page for Docker/GnuCOBOL readiness

  Reporting:
    report     one HTML/JSON report: every step, a proof level per test
    journal    record an assistant's step for the report's timeline
    clean      remove the reports and saved results mockymock wrote

  Advanced:
    mutate     mutation-test a program against its .cut suite
    export     write mainframe-ready instrumented source
    fixtures   print a FixtureBundle as JSON for editor integrations
    skills     manage the packaged agent skills (Claude Code, GitHub Copilot)
    setup      build the GnuCOBOL image and start the toolchain container
    runner     run LegacyLens change-impact oracle jobs for the backend
    job        run a whole JCL job end to end and compare its datasets

Quick start:
  mockymock doctor                     is Docker / GnuCOBOL ready?
  mockymock init PROG.cbl              a first .cut suite with real assertions
  mockymock run PROG.cbl               run PROG.cut beside it
  mockymock run                        every .cut suite under this folder
  mockymock lint PROG.cbl              static checks only, no Docker

Toolchain: commands that compile use the mockymock-cobc Docker container
('mockymock setup' builds it). Without Docker, set MOCKYMOCK_GNUCOBOL_HOME
to a GnuCOBOL install (the folder holding bin/cobc) to compile natively;
MOCKYMOCK_TOOLCHAIN=auto|docker|native forces one.

Defaults: the nearest mockymock.toml (or pyproject.toml [tool.mockymock])
and cobol.yml, searched from this folder up, supply copybook paths,
test_root and per-command defaults; flags always win.

Run 'mockymock <command> --help' for a command's own options.
"""


#: Every command the epilog above names, in order; a test pins it against
#: the registered subcommands so a new one cannot be left out.
_GROUPED_COMMANDS = tuple(
    line.split()[0]
    for line in _COMMAND_GROUPS_EPILOG.split("Quick start:")[0].splitlines()
    if line.startswith("    ") and not line.startswith("     ")
)


class _TopLevelParser(argparse.ArgumentParser):
    """`mockymock` itself: the commands are listed once, grouped (the
    epilog), not a second time as argparse's flat `{setup,init,...}`
    block. Only the help screen changes; the subparsers action keeps
    every choice."""

    def format_help(self) -> str:
        formatter = self._get_formatter()
        formatter.add_usage(self.usage, self._actions, self._mutually_exclusive_groups)
        formatter.add_text(self.description)
        for group in self._action_groups:
            actions = [
                a
                for a in group._group_actions
                if not isinstance(a, argparse._SubParsersAction)
            ]
            if actions:
                formatter.start_section(group.title)
                formatter.add_arguments(actions)
                formatter.end_section()
        formatter.add_text(self.epilog)
        return formatter.format_help()


class _WrapDescriptionRawEpilog(argparse.HelpFormatter):
    """Rewraps a one-paragraph description as usual, but keeps text with
    its own line breaks (an examples epilog) as written."""

    def _fill_text(self, text: str, width: int, indent: str) -> str:
        if "\n" in text:
            return "".join(indent + line for line in text.splitlines(keepends=True))
        return super()._fill_text(text, width, indent)


_COMMAND_EXAMPLES = {
    "init": """\
examples:
  mockymock init PROG.cbl
  mockymock init PROG.cbl --copybook-path ./copybooks
""",
    "run": """\
examples:
  mockymock run PROG.cbl                     PROG.cut beside it
  mockymock run PROG.cbl --cut tests/PROG.happy.cut
  mockymock run                              every .cut under this folder
  mockymock run PROG.cbl --case "valid customer" --junit-xml junit.xml
  mockymock run PROG.cbl --coverage-fail-under 80

exit codes:
  0  every selected test case passed
  1  a case failed, or the suite could not run (refusal, compile error,
     no Docker / GnuCOBOL); the reason is printed
  2  a --baseline file could not be read, or a bad command line
""",
    "lint": """\
examples:
  mockymock lint PROG.cbl
  mockymock lint PROG.cut
  mockymock lint                             every .cut under this folder

exit codes:
  0  no problems found
  1  a refusal was reported, or a file could not be read
""",
    "generate": """\
examples:
  mockymock generate PROG.cbl                PROG.cut with empty mock bodies
  mockymock generate PROG.cbl --with-data    generated rows in the mocks
""",
}


def _polish_help(parser: argparse.ArgumentParser) -> None:
    """Help-text touches applied after every subparser is built: an
    examples epilog on the everyday commands, and FILE / DIR metavars
    instead of argparse's upper-cased dest (`--json-report JSON_REPORT`)."""
    for action in parser._actions:
        if not isinstance(action, argparse._SubParsersAction):
            continue
        for name, sub in action.choices.items():
            if name in _COMMAND_EXAMPLES:
                sub.epilog = _COMMAND_EXAMPLES[name]
                sub.formatter_class = _WrapDescriptionRawEpilog
            for option in sub._actions:
                _tidy_metavar(option)


_DIR_DESTS = ("copybook_path", "callee_path", "tests_dir", "work_dir", "root")


_FILE_SUFFIXES = ("_xml", "_json", "_report", "_out", "output", "_file", "cut")


def _tidy_metavar(option: argparse.Action) -> None:
    if not option.option_strings or option.metavar is not None:
        return
    if option.nargs == 0 or option.choices is not None:
        return
    dest = option.dest
    if dest.endswith(_DIR_DESTS):
        option.metavar = "DIR"
    elif dest.endswith(_FILE_SUFFIXES):
        option.metavar = "FILE"
    elif dest == "timeout" or dest.endswith("_timeout"):
        option.metavar = "SECONDS"


_SUITE_NAME_RE = re.compile(r"[A-Za-z0-9_-]+")


def _suite_name(value: str) -> str:
    """argparse `type=` for `--name` (#336): NAME becomes the middle of
    `<program>.<NAME>.cut`, so it must be one plain word -- a `/` would
    create folders no command pairs back to the program, and `..` would
    write outside the tests folder."""
    if not _SUITE_NAME_RE.fullmatch(value):
        raise argparse.ArgumentTypeError(
            f"invalid suite name {value!r}: NAME becomes the middle of "
            "<program>.<NAME>.cut, so use only letters, digits, '-' and '_'"
        )
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = _TopLevelParser(
        prog="mockymock",
        usage="mockymock <command> [options]",
        description=(
            "Unit-test COBOL programs: .cut suites mock their files, SQL,\n"
            "CICS and CALLs, then GnuCOBOL compiles and runs them."
        ),
        epilog=_COMMAND_GROUPS_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(
        dest="command", metavar="<command>", prog="mockymock"
    )

    setup_parser = subparsers.add_parser(
        "setup",
        help="Build the GnuCOBOL image and start the mockymock-cobc container",
        description=(
            "Build the GnuCOBOL image (from this package's Dockerfile) if "
            "it isn't already built or is stale, then start the long-lived "
            "mockymock-cobc container every other command compiles and runs "
            "against. Safe to re-run: a current image/container is left "
            "alone. See 'mockymock doctor' to check readiness without "
            "building or starting anything. With MOCKYMOCK_GNUCOBOL_HOME set "
            "(a bundled GnuCOBOL tree; MOCKYMOCK_TOOLCHAIN=auto|docker|native "
            "picks the backend) nothing is built: setup checks that tree and "
            "its C compiler instead."
        ),
    )
    setup_parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Force a fresh image build even if a current one is cached",
    )
    setup_parser.set_defaults(func=_cmd_setup)

    init_parser = subparsers.add_parser(
        "init",
        help=(
            "One command from a COBOL program to a .cut file with real, "
            "golden-recorded assertions"
        ),
        description=(
            "Composes 'generate --with-data' + 'run --record-expectations' "
            "into one step, so a first scaffold has real generated data "
            "and recorded expected values instead of empty mock bodies. "
            "Degrades to a plain data-driven scaffold (no run attempted) "
            "with a clear next step when Docker isn't set up yet. See "
            "docs/2026-09-15-init-command-design.md."
        ),
    )
    init_parser.add_argument("program")
    init_parser.add_argument(
        "-o",
        "--output",
        help="Where to write the .cut file (default: tests/<folder>/<program>.cut)",
    )
    init_parser.add_argument(
        "--name",
        type=_suite_name,
        help="Name a second suite for the program: writes <program>.<NAME>.cut",
    )
    init_parser.add_argument(
        "--seed", type=int, help="Seed for the fixture bundle's random data generation"
    )
    init_parser.add_argument(
        "--scenarios",
        choices=["happy", "branches", "all"],
        default="happy",
        help="Scenario strategy for the fixture bundle (default happy)",
    )
    init_parser.add_argument(
        "--copybook-path",
        action="append",
        help="Directory to search for copybooks (repeatable)",
    )
    init_parser.add_argument(
        "--extra-copybook-path",
        action="append",
        help=(
            "Directory to search for copybooks after the --copybook-path / "
            "config file list (repeatable; adds to it instead of replacing it)"
        ),
    )
    init_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite the output .cut file if it already exists",
    )
    init_parser.set_defaults(func=_cmd_init)

    suites_parser = subparsers.add_parser(
        "suites",
        help="List which program each .cut suite tests (no Docker)",
        description=(
            "Pair every .cut suite under the project with its program, "
            "or with PROGRAM, list that program's suites and where a new "
            "one would go. A suite names its program with a PROGRAM line, "
            "or by file name: PROG.cut / PROG.<topic>.cut beside the "
            "program, or under tests/ mirroring the program's folder."
        ),
    )
    suites_parser.add_argument("program", nargs="?")
    suites_parser.add_argument(
        "--name",
        type=_suite_name,
        help="With PROGRAM: report the path for <program>.<NAME>.cut",
    )
    suites_parser.add_argument(
        "--json", action="store_true", help="Machine-readable output"
    )
    suites_parser.set_defaults(func=_cmd_suites)

    generate_parser = subparsers.add_parser(
        "generate", help="Scaffold a starter .cut file from a COBOL program"
    )
    generate_parser.add_argument("program")
    generate_parser.add_argument(
        "-o",
        "--output",
        help=(
            "Where to write the .cut file (default: tests/<folder>/<program>.cut, "
            "mirroring the program's folder; beside the program when it "
            "already has a <program>.cut there)"
        ),
    )
    generate_parser.add_argument(
        "--name",
        type=_suite_name,
        help="Name a second suite for the program: writes <program>.<NAME>.cut",
    )
    generate_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite the output .cut file if it already exists",
    )
    generate_parser.add_argument(
        "--fill",
        metavar="CUT_FILE",
        help=(
            "Insert only the missing MOCK blocks an existing .cut file's "
            "test cases need (from the same UNMOCKED_* analysis 'lint' "
            "runs), writing back to CUT_FILE in place. Every existing "
            "directive, EXPECT, VERIFY, and comment is left untouched -- "
            "an existing MOCK block is never edited even if its body is "
            "empty or wrong. Mutually exclusive with -o/--output, "
            "--with-data, and --fixtures. See "
            "docs/2026-09-15-actionable-refusals-and-fill-design.md"
        ),
    )
    generate_parser.add_argument(
        "--copybook-path",
        action="append",
        help="Directory to search for copybooks (repeatable)",
    )
    generate_parser.add_argument(
        "--extra-copybook-path",
        action="append",
        help=(
            "Directory to search for copybooks after the --copybook-path / "
            "config file list (repeatable; adds to it instead of replacing it)"
        ),
    )
    generate_parser.add_argument(
        "--with-data",
        action="store_true",
        help=(
            "Data-driven mode, the default: one TESTCASE per scenario from "
            "a cobol-parser fixture bundle, mock bodies built from its own "
            "generated data. Passing it explicitly makes a generator "
            "failure fatal instead of falling back to --per-paragraph. "
            "Calls cobol-parser's Python API directly unless --fixtures is "
            "also given. See "
            "docs/plans/2026-08-02-program-data-generation-implementation.md's "
            "Phase 8"
        ),
    )
    generate_parser.add_argument(
        "--per-paragraph",
        action="store_true",
        help=(
            "One TESTCASE per paragraph that touches a boundary, with "
            "placeholder mock bodies, instead of one per scenario. Useful "
            "for isolating a leaf paragraph. Not valid with --with-data or "
            "--fixtures"
        ),
    )
    generate_parser.add_argument(
        "--fixtures",
        help=(
            "Consume a pre-generated fixture bundle JSON file (e.g. from "
            "cobol-parser's own 'gen-fixtures --format json') instead of "
            "calling cobol-parser's Python API. Implies --with-data"
        ),
    )
    generate_parser.add_argument(
        "--seed",
        type=int,
        help=(
            "Seed for the fixture bundle's random data generation "
            "(--with-data only, ignored with --fixtures). Omit to draw one; "
            "the bundle always reports which seed it used"
        ),
    )
    generate_parser.add_argument(
        "--scenarios",
        choices=["happy", "branches", "all"],
        default="happy",
        help=(
            "Scenario strategy for the fixture bundle (--with-data only, "
            "ignored with --fixtures): happy (one unconstrained scenario, "
            "default), branches (one scenario per reachable/satisfiable "
            "branch arm), all (branches + fixed empty-input/error-status/"
            "boundary-values families). Mirrors cobol-parser's own "
            "gen-fixtures --scenarios flag"
        ),
    )
    generate_parser.add_argument(
        "--rows",
        type=int,
        help=(
            "Rows to generate per data table on the --with-data "
            "self-generating path (generator default; invalid together "
            "with --fixtures, whose row count is already baked into the "
            "bundle). A scenario family that pins its own row count "
            "(e.g. --scenarios all's fixed 'empty input' family) ignores "
            "this and always generates zero rows for that scenario"
        ),
    )
    generate_parser.add_argument(
        "--placeholder",
        action="append",
        default=[],
        metavar="CATEGORY:KEY",
        help=(
            "Downgrade this boundary's mock body to its ordinary "
            "placeholder instead of bundle-seeded data (repeatable; the "
            "fixture stays mocked, just without generated data; valid "
            "with --with-data or --fixtures; an unmatched pair warns on "
            "stderr rather than silently doing nothing)"
        ),
    )
    generate_parser.add_argument(
        "--real",
        action="append",
        default=[],
        metavar="SUBPROGRAM.cbl",
        help=(
            "Load-module suite: run this subprogram for real instead of "
            "mocking its CALL (repeatable; USE REAL CALL, see "
            "docs/2026-11-01-real-call-integration-design.md). Its CALL "
            "mocks become USE REAL CALL lines and every boundary of the "
            "subprogram gets a placeholder MOCK in BEFORE-EACH"
        ),
    )
    generate_parser.add_argument(
        "--real-files",
        action="store_true",
        help=(
            "Integration tests level 2: make every sequential file real. "
            "Each scenario's generated READ records are written to a data "
            "file (encoded with the FD record layout) and staged with USE "
            "REAL FILE ... FROM; each output file gets an EXPECT FILE "
            "recorded by run --record-expectations. Indexed and relative "
            "files stay mocked (see docs/2026-11-06-real-files-and-job-runs-"
            "design.md)"
        ),
    )
    generate_parser.set_defaults(func=_cmd_generate)

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

    debug_parser = subparsers.add_parser(
        "debug",
        help=(
            "Start an interactive Debug Adapter Protocol session for a "
            "single test case (breakpoints, stepping, variable inspection)"
        ),
    )
    debug_parser.add_argument(
        "program", nargs="?", help="Omit to infer from --cut's sibling file"
    )
    debug_parser.add_argument(
        "--cut", help="Omit to infer from program's sibling .cut file"
    )
    debug_parser.add_argument(
        "--case",
        action="append",
        help="The single TESTCASE to debug (required, repeatable flag but exactly one value)",
    )
    debug_parser.add_argument(
        "--copybook-path",
        action="append",
        help="Directory to search for copybooks (repeatable)",
    )
    debug_parser.add_argument(
        "--extra-copybook-path",
        action="append",
        help=(
            "Directory to search for copybooks after the --copybook-path / "
            "config file list (repeatable; adds to it instead of replacing it)"
        ),
    )
    debug_parser.add_argument(
        "--dap-stdio",
        action="store_true",
        help="Run the DAP adapter on stdio (the mode the VS Code extension spawns)",
    )
    debug_parser.set_defaults(func=_cmd_debug)

    lint_parser = subparsers.add_parser(
        "lint",
        help=(
            "Run every static refusal check on a program + .cut pair "
            "without Docker (fast, editor/CI friendly)"
        ),
    )
    lint_parser.add_argument(
        "program",
        nargs="?",
        help=(
            "Omit to infer from --cut's sibling file; omit both to "
            "discover and lint every .cut file under the current "
            "directory (or the config file's test_root)"
        ),
    )
    lint_parser.add_argument(
        "--cut", help="Omit to infer from program's sibling .cut file"
    )
    lint_parser.add_argument(
        "--copybook-path",
        action="append",
        help="Directory to search for copybooks (repeatable)",
    )
    lint_parser.add_argument(
        "--extra-copybook-path",
        action="append",
        help=(
            "Directory to search for copybooks after the --copybook-path / "
            "config file list (repeatable; adds to it instead of replacing it)"
        ),
    )
    lint_parser.add_argument(
        "--case",
        action="append",
        help=(
            "Check only this TESTCASE (repeatable; combines with --tag as a "
            "union). File-wide problems are still reported"
        ),
    )
    lint_parser.add_argument(
        "--tag",
        action="append",
        help=(
            "Check only TESTCASEs carrying this tag (repeatable; combines "
            "with --case as a union)"
        ),
    )
    lint_parser.set_defaults(func=_cmd_lint)

    mutate_parser = subparsers.add_parser(
        "mutate",
        help=(
            "Mutation-test a program against its .cut suite: mutate "
            "statements one at a time and report which mutants the tests "
            "fail to kill"
        ),
    )
    mutate_parser.add_argument(
        "program", nargs="?", help="Omit to infer from --cut's sibling file"
    )
    mutate_parser.add_argument(
        "--cut", help="Omit to infer from program's sibling .cut file"
    )
    mutate_parser.add_argument(
        "--copybook-path",
        action="append",
        help="Directory to search for copybooks (repeatable)",
    )
    mutate_parser.add_argument(
        "--extra-copybook-path",
        action="append",
        help=(
            "Directory to search for copybooks after the --copybook-path / "
            "config file list (repeatable; adds to it instead of replacing it)"
        ),
    )
    mutate_parser.add_argument(
        "--list",
        action="store_true",
        help="Only list the mutants that would be run (no Docker needed)",
    )
    mutate_parser.add_argument(
        "--timeout",
        type=_timeout_seconds,
        default=15,
        help=(
            "Per-mutant run timeout in seconds (default 15); a mutant that "
            "exceeds it counts as killed -- a hang would be noticed too"
        ),
    )
    mutate_parser.add_argument(
        "--jobs",
        "-j",
        type=int,
        default=1,
        metavar="N",
        help=(
            "Run N mutants in parallel, each in its own sandbox and worker "
            "process (default 1). The useful ceiling is not the core count "
            "but the shared mockymock-cobc container's 1 GiB memory limit, "
            "which every concurrent cobc draws from at once -- raise this "
            "gradually and watch for compile failures on a large program"
        ),
    )
    mutate_parser.add_argument(
        "--no-coverage-gate",
        dest="coverage_gate",
        action="store_false",
        help=(
            "Build and run every mutant, including ones on lines the "
            "baseline proved the suite never executes. By default those are "
            "reported as survivors straight from the baseline's coverage, "
            "which is the same verdict for a fraction of the wall clock"
        ),
    )
    mutate_parser.add_argument(
        "--json-report",
        help="Write the full machine-readable mutation report to this file",
    )
    mutate_parser.add_argument(
        "--fail-under",
        type=_percent,
        help="Exit 1 if the mutation score (percent) is below this value",
    )
    mutate_parser.set_defaults(func=_cmd_mutate)

    collect_parser = subparsers.add_parser(
        "collect",
        help=(
            "List a .cut file's suite and test cases (names, line numbers, "
            "tags) without running anything"
        ),
    )
    collect_parser.add_argument(
        "program",
        nargs="?",
        help="Required only with --boundaries",
    )
    collect_parser.add_argument(
        "--cut",
        help="The .cut file to list (required, except with --boundaries)",
    )
    collect_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of the human listing",
    )
    collect_parser.add_argument(
        "--boundaries",
        action="store_true",
        help=(
            "Also report every mockable boundary site in program "
            "(category, key, paragraph, line) -- for editor completion. "
            "Requires --json and program. See "
            "docs/2026-09-15-cut-editor-intelligence-design.md"
        ),
    )
    collect_parser.add_argument(
        "--copybook-path",
        action="append",
        help="Directory to search for copybooks (repeatable; --boundaries only)",
    )
    collect_parser.add_argument(
        "--extra-copybook-path",
        action="append",
        help=(
            "Directory to search for copybooks after the --copybook-path / "
            "config file list (repeatable; adds to it instead of replacing it)"
        ),
    )
    collect_parser.set_defaults(func=_cmd_collect)

    explain_parser = subparsers.add_parser(
        "explain",
        help="Print the catalogued explanation for a refusal code",
        description=(
            "One shared source of truth for what a refusal code means, "
            "backing both this CLI and the mocky-mock-vscode extension's "
            "hover. See docs/2026-09-15-cut-editor-intelligence-design.md."
        ),
    )
    explain_parser.add_argument(
        "code", nargs="?", help="A refusal code, e.g. UNSUPPORTED_DECLARATIVES"
    )
    explain_parser.add_argument(
        "--list",
        action="store_true",
        help="List every catalogued code instead of explaining one",
    )
    explain_parser.add_argument(
        "--json", action="store_true", help="Machine-readable output"
    )
    explain_parser.set_defaults(func=_cmd_explain)

    dashboard_parser = subparsers.add_parser(
        "dashboard",
        help=(
            "Serve a local web page showing whether Docker and the "
            "GnuCOBOL toolchain are up (read-only; does not build or start "
            "anything), the 'mockymock report' test results found under "
            "the current directory, and whether the cobol-testing skills "
            "are installed for Claude Code and GitHub Copilot (with a button to install them)"
        ),
    )
    dashboard_parser.add_argument(
        "--port",
        type=int,
        # Resolved in _cmd_dashboard rather than here: importing
        # web.server for its DEFAULT_PORT would pull runtime.docker_toolchain
        # (and its Dockerfile read) into every `mockymock --help`, breaking
        # this module's deferred-import rule. test_cli_dashboard.py pins the
        # literal below against web.server.DEFAULT_PORT.
        default=None,
        help="Port to serve on (default 8765; 0 picks a free one)",
    )
    dashboard_parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Don't open a browser window automatically",
    )
    dashboard_parser.add_argument(
        "--reports-dir",
        default=None,
        help=(
            "Where to look for 'mockymock report' HTML pages "
            "(*.report.html; default: the current directory)"
        ),
    )
    dashboard_parser.set_defaults(func=_cmd_dashboard)

    doctor_parser = subparsers.add_parser(
        "doctor",
        help=(
            "Terminal-native readiness report (Docker/GnuCOBOL toolchain, "
            "cobol-parser, config file) -- read-only, never builds or "
            "starts anything"
        ),
        description=(
            "Reuses the same read-only probe 'mockymock dashboard' serves "
            "over HTTP, plus two checks of its own: whether cobol-parser "
            "is importable, and which project config file (if any) this "
            "invocation would load. Exits 0 when everything checked is "
            "ready, 1 otherwise. Never mutates anything -- suggests "
            "'mockymock setup', never runs it."
        ),
    )
    doctor_parser.add_argument(
        "--json",
        action="store_true",
        help="Machine-readable output for scripting",
    )
    doctor_parser.set_defaults(func=_cmd_doctor)

    report_parser = subparsers.add_parser(
        "report",
        help=(
            "Write one HTML (and optional JSON) report for a program and its "
            ".cut suite: every analysis step, a verification level per test "
            "case, and the findings"
        ),
    )
    report_parser.add_argument(
        "program", nargs="?", help="Omit to infer from --cut's sibling file"
    )
    report_parser.add_argument(
        "--cut", help="Omit to infer from program's sibling .cut file"
    )
    report_parser.add_argument(
        "-o",
        "--output",
        help=(
            "HTML report path (default: .mockymock/<cut stem>.report.html "
            "next to the .cut)"
        ),
    )
    report_parser.add_argument(
        "--json",
        help=(
            "Where to write the report as JSON (default: next to the HTML, "
            ".mockymock/<cut stem>.report.json)"
        ),
    )
    report_parser.add_argument(
        "--rerun",
        action="store_true",
        help=(
            "With --execute/--mutate, run the suite and the mutants again even "
            "when 'run'/'mutate' already saved results for this exact program, "
            "suite and copybooks"
        ),
    )
    report_parser.add_argument(
        "--copybook-path",
        action="append",
        help="Directory to search for copybooks (repeatable)",
    )
    report_parser.add_argument(
        "--extra-copybook-path",
        action="append",
        help=(
            "Directory to search for copybooks after the --copybook-path / "
            "config file list (repeatable; adds to it instead of replacing it)"
        ),
    )
    report_parser.add_argument(
        "--execute",
        action="store_true",
        help="Run the suite (with coverage) now; needs Docker",
    )
    report_parser.add_argument(
        "--mutate",
        action="store_true",
        help="Run mutation testing now; needs Docker and takes longer",
    )
    report_parser.add_argument(
        "--run-json", help="Read results from an earlier 'run --json-report'"
    )
    report_parser.add_argument(
        "--coverage-json", help="Read coverage from an earlier 'run --coverage-json'"
    )
    report_parser.add_argument(
        "--mutation-json", help="Read an earlier 'mutate --json-report'"
    )
    report_parser.add_argument(
        "--journal",
        help=(
            "Assistant journal to include (default: "
            ".mockymock/<cut stem>.journal.jsonl if present)"
        ),
    )
    report_parser.add_argument(
        "--scenarios",
        default="branches",
        choices=["happy", "branches", "all", "none"],
        help="happy, branches, all, or none: how to measure reachable branch arms (default: branches)",
    )
    report_parser.add_argument("--seed", type=int, help="Seed for fixture generation")
    report_parser.add_argument(
        "--timeout",
        type=_timeout_seconds,
        help="Per-run timeout in seconds passed to 'run'",
    )
    report_parser.add_argument(
        "--mutation-threshold",
        type=float,
        default=80.0,
        help="Mutation score (percent) a suite needs for its cases to reach L2 (default: 80)",
    )
    report_parser.set_defaults(func=_cmd_report)

    journal_parser = subparsers.add_parser(
        "journal",
        help="Append one assistant step to a suite's journal for 'mockymock report'",
    )
    journal_parser.add_argument(
        "--cut",
        help=(
            "The suite (or its program); the journal is "
            ".mockymock/<cut stem>.journal.jsonl next to the .cut"
        ),
    )
    journal_parser.add_argument("--file", help="Explicit journal path instead")
    journal_parser.add_argument("--step", help="Step name, e.g. plan")
    journal_parser.add_argument("--summary", help="What was done and what came of it")
    journal_parser.add_argument(
        "--from",
        dest="from_file",
        metavar="FILE",
        help=(
            "Append several entries at once from FILE ('-' for stdin): a JSON "
            "array of objects, or one object per line, each with step and "
            "summary and optionally status, command and decision"
        ),
    )
    journal_parser.add_argument(
        "--status",
        default=None,
        help="ok, warn, fail, skipped, or info (default: ok); with --from, "
        "the status of every entry that has none of its own",
    )
    journal_parser.add_argument(
        "--command",
        dest="command_text",
        help="The command that was run, if any",
    )
    journal_parser.add_argument("--decision", help="A decision taken, and why")
    journal_parser.set_defaults(func=_cmd_journal)

    clean_parser = subparsers.add_parser(
        "clean",
        help=(
            "Remove the reports and saved run/mutation results mockymock "
            "wrote (the .mockymock/ folders); journals are kept unless --all"
        ),
    )
    clean_parser.add_argument(
        "target",
        nargs="?",
        help=(
            "A .cut (that suite), a program (all its suites) or a directory "
            "(everything under it); default: the current directory"
        ),
    )
    clean_parser.add_argument(
        "--all",
        action="store_true",
        help="Also remove the assistant journals",
    )
    clean_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List what would be removed without removing it",
    )
    clean_parser.set_defaults(func=_cmd_clean)

    runner_parser = subparsers.add_parser(
        "runner",
        help=(
            "Claim LegacyLens change-impact oracle jobs, run each load "
            "module's suites with --record-baseline / --baseline, and report back"
        ),
    )
    runner_parser.add_argument(
        "--url",
        help="LegacyLens backend base URL (default: $LEGACYLENS_URL)",
    )
    runner_parser.add_argument(
        "--token-env",
        default="RUNNER_TOKEN",
        help="Environment variable holding the backend's runner token (default: RUNNER_TOKEN)",
    )
    runner_parser.add_argument(
        "--name", help="Runner name the backend records (default: mockymock@HOST)"
    )
    runner_parser.add_argument(
        "--once",
        action="store_true",
        help="Run the queued jobs, then exit instead of waiting for more",
    )
    runner_parser.add_argument(
        "--poll-interval",
        type=_positive_seconds,
        default=10.0,
        help="Seconds between claims when no job is queued (default: 10)",
    )
    runner_parser.add_argument(
        "--suite-timeout",
        type=_positive_seconds,
        default=900.0,
        help="Seconds one generate or run may take (default: 900)",
    )
    runner_parser.add_argument(
        "--work-dir",
        help="Folder jobs are unpacked in (default: the system temp folder)",
    )
    runner_parser.add_argument(
        "--keep",
        action="store_true",
        help="Keep each job's unpacked folder (for debugging)",
    )
    runner_parser.add_argument(
        "--log-file",
        help="Append the runner's log to this file (default: stderr)",
    )
    runner_parser.add_argument(
        "--log-format",
        choices=("text", "json"),
        default="text",
        help="text (default) or json: one JSON object per line, for a log collector",
    )
    runner_parser.add_argument(
        "--log-level",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        default="INFO",
        help="Lowest level logged (default: INFO)",
    )
    runner_parser.set_defaults(func=_cmd_runner)

    job_parser = subparsers.add_parser(
        "job",
        help=(
            "Run a whole JCL job end to end: COBOL steps on real files, "
            "IEFBR14/IEBGENER/SORT emulated, COND/IF on the real return codes, "
            "and compare every dataset it wrote with --expected"
        ),
    )
    job_parser.add_argument("jcl", help="The job's JCL member")
    job_parser.add_argument(
        "--src",
        action="append",
        default=[],
        help="Folder (or file) holding the steps' COBOL sources (repeatable)",
    )
    job_parser.add_argument(
        "--data",
        required=True,
        help="Folder of input datasets, one file per dataset name (PROD.CUST.MASTER)",
    )
    job_parser.add_argument(
        "--expected",
        help="Folder of expected datasets the job's outputs are compared with",
    )
    job_parser.add_argument(
        "--record",
        action="store_true",
        help="Write the job's outputs to --expected instead of comparing",
    )
    job_parser.add_argument(
        "--generate-inputs",
        action="store_true",
        help="Generate a missing input dataset from the reading program's record layout (written to --data)",
    )
    job_parser.add_argument(
        "--rows",
        type=int,
        default=10,
        help="Records per generated input dataset (default: 10)",
    )
    job_parser.add_argument(
        "--copybook-path",
        action="append",
        default=[],
        help="Copybook folder (repeatable)",
    )
    job_parser.add_argument(
        "--proclib",
        action="append",
        default=[],
        help="PROC library folder (repeatable)",
    )
    job_parser.add_argument(
        "--seed", type=int, default=0, help="Seed for generated values"
    )
    job_parser.add_argument(
        "--timeout",
        type=int,
        default=60,
        help="Seconds one step's program may run (default: 60)",
    )
    job_parser.add_argument("--json-report", help="Write the job report as JSON here")
    job_parser.add_argument(
        "--work-dir", help="Folder the run's datasets and step suites go in"
    )
    job_parser.add_argument(
        "--keep", action="store_true", help="Keep the work folder (for debugging)"
    )
    job_parser.set_defaults(func=_cmd_job)

    analyze_parser = subparsers.add_parser(
        "analyze",
        help=(
            "Run a cobol-parser analyzer subcommand (dead-code, "
            "program-flow, io-sequence, move-type-check, linkage-check, "
            "language-env, ims-dli, analyze) and print its JSON report"
        ),
    )
    analyze_parser.add_argument(
        "cobolparser_args",
        nargs=argparse.REMAINDER,
        metavar="COBOL_PARSER_ARGS",
        help=(
            "Arguments forwarded verbatim to cobol-parser's own CLI, e.g. "
            "'dead-code PROGRAM.cbl --compact'"
        ),
    )
    analyze_parser.set_defaults(func=_cmd_analyze)

    export_parser = subparsers.add_parser(
        "export",
        help=(
            "Write the instrumented COBOL source to a file, adjusted for "
            "a real fixed-format COBOL compile (e.g. z/OS) instead of "
            "GnuCOBOL-only"
        ),
    )
    export_parser.add_argument(
        "program", nargs="?", help="Omit to infer from --cut's sibling file"
    )
    export_parser.add_argument(
        "--cut", help="Omit to infer from program's sibling .cut file"
    )
    export_parser.add_argument("-o", "--output")
    export_parser.add_argument(
        "--copybook-path",
        action="append",
        help="Directory to search for copybooks (repeatable)",
    )
    export_parser.add_argument(
        "--extra-copybook-path",
        action="append",
        help=(
            "Directory to search for copybooks after the --copybook-path / "
            "config file list (repeatable; adds to it instead of replacing it)"
        ),
    )
    export_parser.add_argument(
        "--case",
        action="append",
        help=(
            "Include only the TESTCASE with this exact name (repeatable; "
            "combines with --tag as a union)"
        ),
    )
    export_parser.add_argument(
        "--tag",
        action="append",
        help=(
            "Include only TESTCASEs carrying this tag (repeatable; "
            "combines with --case as a union)"
        ),
    )
    export_parser.set_defaults(func=_cmd_export)

    skills_parser = subparsers.add_parser(
        "skills",
        help="Manage the packaged agent skills (Claude Code, GitHub Copilot)",
    )
    skills_subparsers = skills_parser.add_subparsers(dest="skills_command")

    # Bare `mockymock skills` (no subcommand) must print THIS parser's
    # usage, not fall through to main()'s top-level-help fallback -- the
    # user typed a valid subcommand and needs its own options, not all
    # twelve commands (2026-08-12 audit Finding 14).
    def _cmd_skills_help(args: argparse.Namespace) -> int:
        skills_parser.print_help()
        return 1

    skills_parser.set_defaults(func=_cmd_skills_help)
    skills_install_parser = skills_subparsers.add_parser(
        "install",
        help=(
            "Install the packaged agent skills (mockymock, cobol-analysis, "
            "cobol-test, mockymock-setup) so a Claude Code or GitHub Copilot session can use them"
        ),
    )
    skills_install_parser.add_argument(
        "--project",
        action="store_true",
        help=(
            "Install into the current directory (./.claude/skills/<name>, "
            "or ./.github/skills/<name> for copilot) instead of the home "
            "directory"
        ),
    )
    skills_install_parser.add_argument(
        "--target",
        default="claude",
        # Literal rather than skills_cmd.TARGETS: see the deferred-import
        # rule; test_cli_skills.py pins the two together.
        choices=["claude", "copilot", "all"],
        help=(
            "Which assistant to install for: claude (~/.claude/skills, the "
            "default), copilot (GitHub Copilot: ~/.copilot/skills) or all"
        ),
    )
    skills_install_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing install at the target path",
    )
    skills_install_parser.add_argument(
        "--skill",
        action="append",
        help=(
            "Install only this skill (repeatable): mockymock, cobol-analysis, "
            "cobol-test or mockymock-setup. Default: all four"
        ),
    )
    skills_install_parser.set_defaults(func=_cmd_skills_install)

    skills_plugin_parser = skills_subparsers.add_parser(
        "plugin",
        help=(
            "Write the cobol-testing Claude Code plugin as a local "
            "marketplace, for `/plugin marketplace add <dir>` without GitHub"
        ),
    )
    skills_plugin_parser.add_argument(
        "directory",
        nargs="?",
        help="Where to write it (default: ~/.mockymock/claude-plugin)",
    )
    skills_plugin_parser.add_argument(
        "--force",
        action="store_true",
        help="Replace an earlier export in that directory",
    )
    skills_plugin_parser.set_defaults(func=_cmd_skills_plugin)

    skills_mode_parser = skills_subparsers.add_parser(
        "mode",
        help=(
            "Show (or set) how much the AI assistant checks in while it builds a suite"
        ),
    )
    skills_mode_parser.add_argument(
        "--set",
        metavar="MODE",
        default=None,
        # Not `choices=MODES`: that would need mockymock.project.ai_mode
        # imported at parser-build time, and build_parser() runs on every
        # invocation including --help/--version. The valid set is spelled
        # out here instead and validated in _cmd_skills_mode;
        # tests/unit/test_cli_skills.py pins this text against MODES so the
        # two can't drift.
        help=(
            "Persist the mode to mockymock.toml: hands-on (propose first, "
            "wait for a yes), guided (narrate every step, stop at the "
            "checkpoints; the default), hands-off (run the whole workflow, "
            "report once at the end)"
        ),
    )
    skills_mode_parser.add_argument(
        "--json",
        action="store_true",
        help="Print the active mode and every mode's contract as JSON",
    )
    skills_mode_parser.set_defaults(func=_cmd_skills_mode)

    _polish_help(parser)
    return parser


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


if __name__ == "__main__":
    sys.exit(main())
