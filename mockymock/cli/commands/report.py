"""`mockymock report`: every check on one program/.cut pair, joined into one report."""

from __future__ import annotations

import argparse
from pathlib import Path

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
