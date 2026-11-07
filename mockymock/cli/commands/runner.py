"""`mockymock runner`: claim and run LegacyLens change-impact oracle jobs."""

from __future__ import annotations

import argparse
from pathlib import Path


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
