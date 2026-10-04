"""Finds the `mockymock report` HTML pages the dashboard lists and serves.

`mockymock report` writes `<program>.report.html` next to the program by
default, so the dashboard looks for that suffix under one root directory
(the directory the dashboard was started in, or `--reports-dir`). Nothing
here writes: the page lists what is on disk and shows it.

Two bounds keep a dashboard started in a large tree (a home directory, a
monorepo) responsive: hidden directories and well-known dependency/build
folders are skipped, and the walk stops at MAX_DEPTH levels and
MAX_REPORTS hits. A truncated listing says so (`truncated`), so a missing
report is never mistaken for one that was not written.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPORT_SUFFIX = ".report.html"
MAX_DEPTH = 6
MAX_REPORTS = 200
_SKIPPED_DIRS = frozenset(
    {"node_modules", "__pycache__", "venv", "build", "dist", "htmlcov"}
)


@dataclass(frozen=True)
class ReportFile:
    path: str  # posix, relative to the root: what /reports/<path> serves
    program: str
    modified: str
    size: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "program": self.program,
            "modified": self.modified,
            "size": self.size,
        }


def find_reports(root: Path) -> tuple[list[ReportFile], bool]:
    """Every `*.report.html` under `root`, newest first, and whether the
    walk stopped early at MAX_REPORTS."""
    root = root.resolve()
    found: list[tuple[float, ReportFile]] = []
    truncated = False
    for dirpath, dirnames, filenames in os.walk(root):
        current = Path(dirpath)
        depth = len(current.relative_to(root).parts)
        if depth >= MAX_DEPTH:
            dirnames[:] = []
        else:
            dirnames[:] = sorted(
                d for d in dirnames if not d.startswith(".") and d not in _SKIPPED_DIRS
            )
        for name in sorted(filenames):
            if not name.endswith(REPORT_SUFFIX):
                continue
            if len(found) >= MAX_REPORTS:
                truncated = True
                break
            file = current / name
            try:
                stat = file.stat()
            except OSError:
                continue
            found.append(
                (
                    stat.st_mtime,
                    ReportFile(
                        path=file.relative_to(root).as_posix(),
                        program=name[: -len(REPORT_SUFFIX)],
                        modified=datetime.fromtimestamp(
                            stat.st_mtime, tz=UTC
                        ).isoformat(timespec="seconds"),
                        size=stat.st_size,
                    ),
                )
            )
        if truncated:
            break
    found.sort(key=lambda item: (-item[0], item[1].path))
    return [report for _, report in found], truncated


def reports_payload(root: Path) -> dict[str, Any]:
    """`/api/reports`: the root searched and what was found under it."""
    reports, truncated = find_reports(root)
    return {
        "root": str(root.resolve()),
        "reports": [report.to_dict() for report in reports],
        "truncated": truncated,
    }


def resolve_report(root: Path, relative: str) -> Path | None:
    """Map a `/reports/<relative>` request to a report file under `root`,
    or None. Same containment rule as `server.resolve_static` (checked
    after `resolve()`, so `..` and symlinks out of the root are refused),
    and only `*.report.html` files are served: the dashboard must not
    become a way to read any file under the directory it was started in."""
    root = root.resolve()
    candidate = (root / relative.lstrip("/")).resolve()
    if not candidate.is_relative_to(root):
        return None
    if not candidate.name.endswith(REPORT_SUFFIX) or not candidate.is_file():
        return None
    return candidate
