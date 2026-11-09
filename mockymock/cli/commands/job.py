"""`mockymock job`: run a JCL job stream end to end."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from mockymock.cli._common import _write_report_file


def _cmd_job(args: argparse.Namespace) -> int:
    """`mockymock job`: 0 passed / recorded, 1 failed, 3 incomplete (a gap)."""
    import json

    # Each COBOL step runs the CLI itself in-process (a job step is a
    # `mockymock run`), so the job runner is handed this entry point.
    from mockymock.cli.main import main as cli_main
    from mockymock.jobstream.runner import (
        JobOptions,
        format_job_console,
        run_job_stream,
    )

    jcl = Path(args.jcl)
    if not jcl.is_file():
        print(f"mockymock job: no such JCL file {jcl}", file=sys.stderr)
        return 2
    if args.record and not args.expected:
        print(
            "mockymock job: --record needs --expected (where to write)", file=sys.stderr
        )
        return 2
    try:
        import cobolparser.jcl  # noqa: F401
    except ImportError:
        print(
            "mockymock job: reading JCL needs jcl-parser "
            "(pip install 'cobol-parser[jcl]')",
            file=sys.stderr,
        )
        return 2
    copybook_paths = list(args.copybook_path)
    config = getattr(args, "_config", None)
    if not copybook_paths and config is not None:
        copybook_paths = list(getattr(config, "copybook_paths", []) or [])
    options = JobOptions(
        jcl=jcl,
        sources=[Path(p) for p in (args.src or [str(jcl.parent)])],
        data=Path(args.data),
        expected=Path(args.expected) if args.expected else None,
        copybook_paths=[str(p) for p in copybook_paths],
        proc_paths=list(args.proclib),
        record=args.record,
        generate_inputs=args.generate_inputs,
        input_rows=args.rows,
        seed=args.seed,
        work_dir=Path(args.work_dir) if args.work_dir else None,
        keep=args.keep,
        timeout=args.timeout,
        command=cli_main,
    )
    report = run_job_stream(options)
    print(format_job_console(report))
    if args.json_report:
        _write_report_file(
            "job",
            "--json-report",
            args.json_report,
            json.dumps(report, indent=2) + "\n",
        )
    verdict = report.get("verdict")
    if verdict in ("passed", "recorded"):
        return 0
    if verdict == "failed":
        return 1
    return 3
