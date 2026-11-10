"""`mockymock runner`: claim and run LegacyLens change-impact oracle jobs."""

from __future__ import annotations

import argparse
from pathlib import Path

from mockymock.cli._args import _positive_seconds


def _cmd_runner(args: argparse.Namespace) -> int:
    """Claim and run LegacyLens change-impact oracle jobs
    (docs/2026-11-01-runner-design.md)."""

    import os

    from mockymock.runner import RunnerClient, RunnerClientError, serve
    from mockymock.runner.logs import LOGGER, configure_logging

    try:
        configure_logging(args.log_level, args.log_format, args.log_file)
    except (OSError, ValueError) as exc:
        print(f"mockymock runner: cannot open the log: {exc}")
        return 2
    url = args.url or os.environ.get("LEGACYLENS_URL", "")
    token = os.environ.get(args.token_env, "")
    if not url:
        print("mockymock runner: no backend URL (--url or LEGACYLENS_URL)")
        return 2
    if not token:
        print(
            f"mockymock runner: {args.token_env} is not set (the backend's RUNNER_TOKEN)"
        )
        return 2
    client = RunnerClient(url, token)
    work_dir = Path(args.work_dir) if args.work_dir else None
    if work_dir is not None:
        work_dir.mkdir(parents=True, exist_ok=True)
    try:
        ran = serve(
            client,
            runner_name=args.name,
            once=args.once,
            poll_interval=args.poll_interval,
            timeout=args.suite_timeout,
            work_dir=work_dir,
            keep=args.keep,
        )
    except RunnerClientError as exc:
        LOGGER.error("runner stopped", extra={"error": str(exc)})
        print(f"mockymock runner: {exc}")
        return 1
    except KeyboardInterrupt:
        LOGGER.info("runner interrupted")
        return 0
    LOGGER.info("runner finished", extra={"jobs": ran})
    print(f"mockymock runner: ran {ran} job(s)")
    return 0


def register_runner(subparsers: argparse._SubParsersAction) -> None:
    """Add `mockymock runner` to the top-level parser."""
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
