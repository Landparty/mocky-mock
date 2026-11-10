"""`mockymock mutate`: mutation testing of a program against its suite."""

from __future__ import annotations

import argparse

from mockymock._lines import read_utf8_source, split_source_lines
from mockymock.cli._args import _percent, _timeout_seconds
from mockymock.cli._common import (
    _apply_config_to_args,
    _resolve_program_and_cut,
    _save_result,
    _write_report_file,
)
from mockymock.report.artifacts import fingerprint


def _cmd_mutate(args: argparse.Namespace) -> int:
    """Mutation-test a program/.cut pair: generate mutants, run the suite
    against each, and report which ones survived (see
    docs/2026-07-29-mutation-testing-design.md)."""
    import json

    from mockymock.mutation.operators import generate_mutants
    from mockymock.mutation.report import (
        MutantResult,
        format_console,
        to_json_dict,
    )
    from mockymock.mutation.runner import run_mutation

    pair = _resolve_program_and_cut("mockymock mutate", args)
    if pair is None:
        return 1
    source_path, cut_path = pair
    _apply_config_to_args(args, source_path)

    if args.list:
        # --list never runs anything, so flags that only mean something
        # for a real mutation run would be silently ignored -- refuse the
        # combination instead (2026-08-12 audit Finding 16). --timeout is
        # exempt only because argparse always materializes its default.
        ignored = [
            flag
            for flag, value in (
                ("--json-report", args.json_report),
                ("--fail-under", args.fail_under),
                ("--jobs", args.jobs if args.jobs != 1 else None),
                ("--no-coverage-gate", None if args.coverage_gate else True),
            )
            if value is not None
        ]
        if ignored:
            print(
                f"mockymock mutate: --list only lists mutants and would "
                f"ignore {', '.join(ignored)} -- drop --list to run the "
                f"mutation suite, or drop the other flag(s)"
            )
            return 1
        mutants = generate_mutants(split_source_lines(read_utf8_source(source_path)))
        for mutant in mutants:
            print(f"line {mutant.line} [{mutant.operator}] {mutant.description}")
        print(f"{len(mutants)} mutant(s)")
        return 0

    if args.jobs < 1:
        print(f"mockymock mutate: --jobs must be at least 1 (got {args.jobs})")
        return 1

    def on_progress(result: MutantResult) -> None:
        marker = {
            "killed": "killed   ",
            "survived": "SURVIVED ",
            "stillborn": "stillborn",
            "timeout": "timeout  ",
            "error": "ERROR    ",
            "equivalent": "equiv    ",
        }[result.status]
        if not result.ran and result.status == "survived":
            # Same verdict, different evidence: say so rather than letting
            # it read as a mutant that was built and beat the suite.
            marker = "uncovered"
        print(
            f"  {marker} line {result.mutant.line} "
            f"[{result.mutant.operator}] {result.mutant.description}"
        )

    mutation_inputs = fingerprint(source_path, cut_path, args.copybook_path)
    problems, outcome, notes = run_mutation(
        source_path,
        cut_path,
        args.copybook_path,
        timeout_seconds=args.timeout,
        on_progress=on_progress,
        jobs=args.jobs,
        coverage_gate=args.coverage_gate,
    )
    for note in notes:
        print(f"mockymock mutate: {note}")
    if problems or outcome is None:
        for problem in problems:
            print(f"mockymock mutate: {problem}")
        return 1

    print(format_console(outcome))
    mutation_text = json.dumps(to_json_dict(outcome), indent=2) + "\n"
    if outcome.complete:
        # An incomplete outcome (#347) is not a result worth reusing.
        _save_result(
            "mutate",
            cut_path,
            source_path,
            "mutation",
            mutation_text,
            args,
            mutation_inputs,
        )
    if args.json_report:
        # Same convention as run's report flags: an auxiliary report file
        # that can't be written is reported cleanly, and the exit code
        # stands on the mutation outcome itself.
        if _write_report_file(
            "mutate",
            "--json-report",
            args.json_report,
            mutation_text,
        ):
            print(f"mockymock mutate: wrote JSON report -> {args.json_report}")

    score = outcome.score
    if not outcome.complete:
        # Whatever --fail-under says: a score over only the mutants the
        # toolchain happened to finish is not the suite's score, and
        # exiting 0 on it would let a dying container pass (or fail) a
        # gate on a number it made up (issue #347).
        print(
            f"mockymock mutate: {outcome.errors} mutant(s) could not be "
            "evaluated because the Docker toolchain failed -- the score is "
            "incomplete; re-run once Docker is healthy"
        )
        return 1
    if args.fail_under is not None:
        if outcome.score_below(args.fail_under):
            shown = "n/a" if score is None else f"{score * 100:.1f}%"
            print(
                f"mockymock mutate: mutation score {shown} is below "
                f"--fail-under {args.fail_under}"
            )
            return 1
    return 0


def register_mutate(subparsers: argparse._SubParsersAction) -> None:
    """Add `mockymock mutate` to the top-level parser."""
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
