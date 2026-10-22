"""The assistant's step journal: what was done, why, and what came of it.

`mockymock report` can recompute everything a tool decides (which cases
pass, which mutants survive), but not what the assistant that built the
suite decided along the way -- which paragraph it started with, why it
parked one, which business rule an EXPECT came from. The `cobol-test`
skill records each of those as one JSON line with `mockymock journal`,
and the report shows them as a timeline next to its own computed steps.

One JSON object per line, appended, never rewritten:

    {"time": "2026-10-04T13:20:01Z", "step": "plan", "status": "ok",
     "summary": "...", "command": "...", "decision": "..."}

`step` is free text (the skill uses its own step names); `status` is one
of STATUSES. Unknown keys are kept, so a later skill version can add
fields without breaking an older report.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

STATUSES = ("ok", "warn", "fail", "skipped", "info")


class JournalError(Exception):
    pass


def default_journal_path(cut_path: Path) -> Path:
    """`<cut stem>.journal.jsonl` next to the `.cut`: one journal per
    suite, found by `mockymock report` without any flag."""
    return cut_path.with_name(f"{cut_path.stem}.journal.jsonl")


def default_report_path(cut_path: Path) -> Path:
    """`<cut stem>.report.html` next to the `.cut`, the same place as the
    journal: one report per suite, so a program's second suite never
    overwrites the first one's report (issue #192)."""
    return cut_path.with_name(f"{cut_path.stem}.report.html")


def append_entry(
    path: Path,
    *,
    step: str,
    summary: str,
    status: str = "ok",
    command: str | None = None,
    decision: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    if status not in STATUSES:
        raise JournalError(
            f"unknown status {status!r} (expected one of: {', '.join(STATUSES)})"
        )
    if not step.strip() or not summary.strip():
        raise JournalError("--step and --summary must not be empty")
    entry: dict[str, Any] = {
        "time": (now or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "step": step.strip(),
        "status": status,
        "summary": summary.strip(),
    }
    if command:
        entry["command"] = command
    if decision:
        entry["decision"] = decision
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def read_journal(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """Entries in file order, plus one problem line per line that is not a
    JSON object -- reported, never silently dropped."""
    entries: list[dict[str, Any]] = []
    problems: list[str] = []
    if not path.is_file():
        return entries, problems
    # Split on "\n" only: `str.splitlines()` also breaks on U+2028/U+2029
    # and NEL, which json.dumps(ensure_ascii=False) leaves raw inside a
    # string, so one entry carrying them read back as unparseable pieces.
    for number, raw in enumerate(path.read_text(encoding="utf-8").split("\n"), start=1):
        if not raw.strip():
            continue
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            problems.append(f"{path.name}:{number}: not JSON ({exc.msg})")
            continue
        if not isinstance(value, dict):
            problems.append(f"{path.name}:{number}: not a JSON object")
            continue
        entries.append(value)
    return entries, problems
