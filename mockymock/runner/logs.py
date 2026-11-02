"""Logging of the oracle runner: one timeline per job, and the process log.

Every step of a job (download, unpack, each suite's generate and run, the
report) is recorded twice:

* in the job's own log (:class:`JobLog`), a timestamped text the runner
  posts with the result, so the backend keeps it with the job and the
  LegacyLens UI can show it next to the verdict;
* in the ``mockymock.runner`` logger, with the job id and the step's fields
  as ``extra``, for whoever operates the runner (stderr, ``--log-file``,
  ``--log-format json`` for a log collector).

Standard library only, like the rest of the runner.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger("mockymock.runner")

#: Characters of a job's log posted to the backend (the tail is kept).
MAX_JOB_LOG_CHARS = 50_000

#: LogRecord attributes that are not a step's own fields.
_STANDARD_ATTRS = frozenset(
    vars(logging.LogRecord("", 0, "", 0, "", None, None)).keys()
) | {"message", "asctime"}


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _format_fields(fields: dict[str, Any]) -> str:
    parts = []
    for key, value in fields.items():
        if value is None or value == "":
            continue
        text = str(value)
        if any(ch.isspace() for ch in text) or not text:
            text = json.dumps(text)
        parts.append(f"{key}={text}")
    return " ".join(parts)


class JobLog:
    """The timeline of one job: kept as text, mirrored to the logger."""

    def __init__(self, job_id: str = "", logger: logging.Logger = LOGGER) -> None:
        self.job_id = job_id
        self.logger = logger
        self._lines: list[str] = []
        self._started = time.monotonic()

    def event(self, message: str, level: int = logging.INFO, **fields: Any) -> None:
        """Record one step: ``message`` plus its ``fields`` (ids, counts,
        exit codes, durations)."""
        suffix = _format_fields(fields)
        self._lines.append(
            f"{_now()} {logging.getLevelName(level):<7} {message}"
            + (f"  {suffix}" if suffix else "")
        )
        extra = {"job_id": self.job_id or None, **fields}
        self.logger.log(
            level,
            message,
            extra={
                # A field named like a LogRecord attribute would raise.
                (f"field_{k}" if k in _STANDARD_ATTRS else k): v
                for k, v in extra.items()
                if v is not None
            },
        )

    def warning(self, message: str, **fields: Any) -> None:
        self.event(message, logging.WARNING, **fields)

    def error(self, message: str, **fields: Any) -> None:
        self.event(message, logging.ERROR, **fields)

    def elapsed_ms(self) -> int:
        return int((time.monotonic() - self._started) * 1000)

    def text(self) -> str:
        """The job's log, its tail kept when it is long."""
        text = "\n".join(self._lines) + ("\n" if self._lines else "")
        if len(text) <= MAX_JOB_LOG_CHARS:
            return text
        return "(earlier lines cut)\n" + text[-MAX_JOB_LOG_CHARS:]


def _cobc_version() -> str | None:
    """The first line of ``cobc --version`` (native toolchain), if any."""
    home = os.environ.get("MOCKYMOCK_GNUCOBOL_HOME")
    candidates = [str(Path(home) / "bin" / "cobc")] if home else []
    found = shutil.which("cobc")
    if found:
        candidates.append(found)
    for cobc in candidates:
        try:
            completed = subprocess.run(
                [cobc, "--version"],
                capture_output=True,
                text=True,
                errors="replace",
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        first = (completed.stdout or completed.stderr).strip().splitlines()
        if first:
            return first[0]
    return None


def environment() -> dict[str, Any]:
    """What the runner runs on: logged once per job, since a compare that
    differs on another toolchain is a toolchain question first."""
    from mockymock import __version__

    return {
        "mockymock": __version__,
        "python": platform.python_version(),
        "platform": platform.platform(terse=True),
        "toolchain": os.environ.get("MOCKYMOCK_TOOLCHAIN") or "default",
        "cobc": _cobc_version(),
    }


class JsonFormatter(logging.Formatter):
    """One JSON object per line: time, level, logger, message, and every
    field the step passed (job_id, entry, exit_code, duration_ms...)."""

    def format(self, record: logging.LogRecord) -> str:
        out: dict[str, Any] = {
            "time": datetime.fromtimestamp(record.created, UTC)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in vars(record).items():
            if key not in _STANDARD_ATTRS and not key.startswith("_"):
                out[key] = value
        if record.exc_info:
            out["exception"] = self.formatException(record.exc_info)
        return json.dumps(out, default=str)


class TextFormatter(logging.Formatter):
    """``time LEVEL message key=value ...``."""

    def format(self, record: logging.LogRecord) -> str:
        fields = {
            key: value
            for key, value in vars(record).items()
            if key not in _STANDARD_ATTRS and not key.startswith("_")
        }
        line = (
            f"{datetime.fromtimestamp(record.created, UTC).isoformat(timespec='seconds')} "
            f"{record.levelname:<7} {record.getMessage()}"
        )
        suffix = _format_fields(fields)
        if suffix:
            line += f"  {suffix}"
        if record.exc_info:
            line += "\n" + self.formatException(record.exc_info)
        return line


def configure_logging(
    level: str = "INFO", fmt: str = "text", file: str | None = None
) -> logging.Handler:
    """Send the runner's log to stderr, or to ``file`` (appended), as text
    or JSON lines. Returns the handler it installed."""
    handler: logging.Handler = (
        logging.FileHandler(file, encoding="utf-8")
        if file
        else logging.StreamHandler(sys.stderr)
    )
    handler.setFormatter(JsonFormatter() if fmt == "json" else TextFormatter())
    LOGGER.handlers = [handler]
    LOGGER.setLevel(level.upper())
    LOGGER.propagate = False
    return handler
