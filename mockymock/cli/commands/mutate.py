"""`mockymock mutate`: mutation testing of a program against its suite."""

from __future__ import annotations

import argparse

from mockymock._lines import read_utf8_source, split_source_lines
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
