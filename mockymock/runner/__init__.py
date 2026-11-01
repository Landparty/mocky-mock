"""`mockymock runner`: the worker that runs LegacyLens change-impact oracle jobs.

LegacyLens (the backend) never compiles or runs COBOL. It queues baseline
and compare jobs for a load module, and this runner claims them over the
backend's runner API (`/api/v1/runner`, `X-Runner-Token`), runs each suite
of the job's pack with `mockymock run --record-baseline` or `--baseline`,
and posts the outcome back. See docs/2026-11-01-runner-design.md.
"""

from mockymock.runner.client import RunnerClient, RunnerClientError
from mockymock.runner.jobs import (
    JobPackError,
    SuiteOutcome,
    extract_pack,
    run_job,
    run_pack,
    serve,
)

__all__ = [
    "JobPackError",
    "RunnerClient",
    "RunnerClientError",
    "SuiteOutcome",
    "extract_pack",
    "run_job",
    "run_pack",
    "serve",
]
