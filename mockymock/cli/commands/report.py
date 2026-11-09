"""`mockymock report`: every check on one program/.cut pair, joined into one report."""

from __future__ import annotations

import argparse
from pathlib import Path

from mockymock.cli._args import _timeout_seconds
from mockymock.cli._common import _apply_config_to_args, _resolve_program_and_cut


def _cmd_report(args: argparse.Namespace) -> int:
    """Join every check mockymock and cobol-parser can make on one
    program/.cut pair into a single report -- the steps taken, a
    verification level per test case, and the findings -- written as JSON
    and/or a self-contained HTML page. See report/test_report.py."""
    import json

    from mockymock.report.artifacts import artifact_path
    from mockymock.report.html_report import render_html
    from mockymock.report.journal import default_journal_path
    from mockymock.report.test_report import ReportOptions, build_report

    pair = _resolve_program_and_cut("mockymock report", args)
    if pair is None:
        return 1
    source_path, cut_path = pair
    _apply_config_to_args(args, source_path)
    # `not 0 <= x <= 100`, not `x < 0 or x > 100`: NaN fails every
    # comparison, so it passed the old check and gated nothing.
    if not 0 <= args.mutation_threshold <= 100:
        print("mockymock report: --mutation-threshold must be between 0 and 100")
        return 1
    journal = Path(args.journal) if args.journal else default_journal_path(cut_path)
    options = ReportOptions(
        program=source_path,
        cut=cut_path,
        copybook_paths=list(args.copybook_path or []),
        run_json=Path(args.run_json) if args.run_json else None,
        coverage_json=Path(args.coverage_json) if args.coverage_json else None,
        mutation_json=Path(args.mutation_json) if args.mutation_json else None,
        journal=journal,
        execute=args.execute,
        mutate=args.mutate,
        scenarios=args.scenarios,
        seed=args.seed,
        timeout=args.timeout,
        mutation_threshold=args.mutation_threshold,
        reuse=not args.rerun,
    )
    report = build_report(options)
    html_path = Path(args.output) if args.output else artifact_path(cut_path, "report")
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(render_html(report), encoding="utf-8")
    # The JSON always goes with the HTML (into .mockymock/ by default),
    # so the two are never in different folders; --json moves it.
    json_path = Path(args.json) if args.json else html_path.with_suffix(".json")
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    for step in report["steps"]:
        print(
            f"mockymock report: [{step['status']:>7}] {step['title']}: {step['summary']}"
        )
    summary = report["summary"]
    findings = summary["findings"]
    print(
        f"mockymock report: {findings['high']} high, {findings['medium']} medium, "
        f"{findings['low']} low finding(s)"
    )
    print(f"mockymock report: wrote {html_path}")
    print(f"mockymock report: wrote {json_path}")
    failed = summary["failed"] or summary.get("runFailed")
    return 1 if failed or summary["levels"].get("none") else 0


def register_report(subparsers: argparse._SubParsersAction) -> None:
    """Add `mockymock report` to the top-level parser."""
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
