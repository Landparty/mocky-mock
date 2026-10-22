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
    """`.mockymock/<cut stem>.journal.jsonl` next to the `.cut`: one
    journal per suite, found by `mockymock report` without any flag (see
    `report.artifacts`; a journal still at its old place next to the
    `.cut` keeps being used)."""
    from mockymock.report.artifacts import journal_path

    return journal_path(cut_path)


def default_report_path(cut_path: Path) -> Path:
    """`.mockymock/<cut stem>.report.html` next to the `.cut`, beside the
    journal: one report per suite, so a program's second suite never
    overwrites the first one's report (issues #192, #353)."""
    from mockymock.report.artifacts import artifact_path

    return artifact_path(cut_path, "report")


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


_ENTRY_FIELDS = ("step", "summary", "status", "command", "decision")


def parse_batch(text: str) -> list[dict[str, Any]]:
    """Entries for `mockymock journal --from`: a JSON array of objects, or
    one object per line (the journal's own format). Every entry is checked
    before any is written, so a bad line appends nothing rather than half a
    batch; each must carry `step` and `summary`, and may carry `status`,
    `command` and `decision` (issue #353: one process per program instead of
    one per step)."""
    stripped = text.strip()
    if not stripped:
        raise JournalError("no entries to append")
    raw: list[Any]
    if stripped.startswith("["):
        try:
            loaded = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise JournalError(f"not a JSON array ({exc.msg})") from exc
        raw = loaded if isinstance(loaded, list) else [loaded]
    else:
        raw = []
        for number, line in enumerate(stripped.split("\n"), start=1):
            if not line.strip():
                continue
            try:
                raw.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise JournalError(f"line {number}: not JSON ({exc.msg})") from exc
    entries: list[dict[str, Any]] = []
    for number, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise JournalError(f"entry {number}: not a JSON object")
        unknown = sorted(set(item) - set(_ENTRY_FIELDS))
        if unknown:
            raise JournalError(
                f"entry {number}: unknown field(s) {', '.join(unknown)} "
                f"(expected: {', '.join(_ENTRY_FIELDS)})"
            )
        if not all(isinstance(item.get(k, ""), str) for k in _ENTRY_FIELDS):
            raise JournalError(f"entry {number}: every field must be a string")
        if (
            not str(item.get("step", "")).strip()
            or not str(item.get("summary", "")).strip()
        ):
            raise JournalError(f"entry {number}: step and summary must not be empty")
        status = item.get("status", "ok")
        if status not in STATUSES:
            raise JournalError(
                f"entry {number}: unknown status {status!r} "
                f"(expected one of: {', '.join(STATUSES)})"
            )
        entries.append(item)
    return entries


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
