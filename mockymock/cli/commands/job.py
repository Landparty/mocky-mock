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


def register_job(subparsers: argparse._SubParsersAction) -> None:
    """Add `mockymock job` to the top-level parser."""
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
