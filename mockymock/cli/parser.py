"""The `mockymock` argument parser.

`build_parser` creates the top-level parser and asks each subcommand
module in `cli/commands/` to add its own subparser (`register_<name>`),
in the order `mockymock --help` lists them. Each command's flags live
next to its handler; this module holds only the top-level parser and the
help polish applied to all of them."""

from __future__ import annotations

import argparse

from mockymock import __version__
from mockymock.cli.commands import (
    analyze,
    clean,
    collect,
    debug,
    environment,
    export,
    fixtures,
    generate,
    init,
    job,
    journal,
    lint,
    mutate,
    report,
    run,
    runner,
    skills,
    suites,
)

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

    environment.register_setup(subparsers)
    init.register_init(subparsers)
    suites.register_suites(subparsers)
    generate.register_generate(subparsers)
    fixtures.register_fixtures(subparsers)
    run.register_run(subparsers)
    debug.register_debug(subparsers)
    lint.register_lint(subparsers)
    mutate.register_mutate(subparsers)
    collect.register_collect(subparsers)
    collect.register_explain(subparsers)
    environment.register_dashboard(subparsers)
    environment.register_doctor(subparsers)
    report.register_report(subparsers)
    journal.register_journal(subparsers)
    clean.register_clean(subparsers)
    runner.register_runner(subparsers)
    job.register_job(subparsers)
    analyze.register_analyze(subparsers)
    export.register_export(subparsers)
    skills.register_skills(subparsers)

    _polish_help(parser)
    return parser
