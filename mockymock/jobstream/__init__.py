"""Integration tests level 3: run a whole JCL job (`mockymock job`).

See docs/2026-11-06-real-files-and-job-runs-design.md.
"""

from mockymock.jobstream.runner import JobOptions, run_job_stream

__all__ = ["JobOptions", "run_job_stream"]
