"""Corpus-sweep snapshots, per-category tallies and run-to-run diffs.

`scripts/corpus_sweep.py` runs `mockymock generate` over a corpus of COBOL
programs; this module turns what each run printed into a snapshot that can
be saved as JSON, tallies the blockers per category, and diffs one snapshot
against an earlier one so progress and regressions show per category
instead of being tallied by hand.

A program is *blocked* when `generate` exited non-zero, raised, or ran past
the sweep's timeout. Its blocker categories are what it printed:

- a `refused (<CODE>)` code, counted under that code;
- `PARSE_ERROR` for the "N parse error(s)" header;
- `UNRESOLVED_COPYBOOK` for a copybook the search could not find, also when
  it comes from the path that prints the cobol-parser error plus the
  `--copybook-path` hint instead of the refusal code (with
  `--copybook-path` given), so one category holds both;
- `NO_TEST_CASE` / `NO_SCENARIO` for the two "nothing to scaffold" exits;
- `EXCEPTION` / `TIMEOUT` for a crash or a run cut off by the sweep;
- `OTHER` when it failed without any of the above (the first line it
  printed is kept as the program's `detail`).

Unmockable boundary points ("N boundary point(s) detected that are not
mockable") are tallied separately, for blocked and clean programs alike:
they do not fail `generate`, but a case reaching one is refused by `run`.

Programs are keyed by a label that has to stay the same from run to run
(a path relative to the corpus root), since the diff matches on it.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SNAPSHOT_FORMAT = "mockymock-sweep"
SNAPSHOT_VERSION = 1

EXCEPTION = "EXCEPTION"
TIMEOUT = "TIMEOUT"
PARSE_ERROR = "PARSE_ERROR"
UNRESOLVED_COPYBOOK = "UNRESOLVED_COPYBOOK"
NO_TEST_CASE = "NO_TEST_CASE"
NO_SCENARIO = "NO_SCENARIO"
OTHER = "OTHER"

_REFUSED_RE = re.compile(r"refused \(([A-Z_]+)\):")
_PARSE_ERROR_HEADER_RE = re.compile(r"(\d+) parse error\(s\)")
_BOUNDARY_HEADER_RE = re.compile(r"(\d+) boundary point\(s\) detected")
# Boundary finding lines look like:
#   "  - CALL in paragraph 'FOO' (line 12)"
#   "  - nested SORT/MERGE in paragraph 'FOO' (line 12) -- reason text"
_BOUNDARY_LINE_RE = re.compile(r"^  - (nested )?(.+?) in paragraph '")
# The line `copybook_not_found_hint` always prints after the
# cobol-parser CopybookNotFoundError message.
_COPYBOOK_HINT = "Pass its location with --copybook-path"
_NO_TEST_CASE = "no test case to write"
_NO_SCENARIO = "zero scenarios -- nothing to scaffold"
_GENERATE_PREFIX = "mockymock generate: "


@dataclass
class ProgramResult:
    """One program's outcome in one sweep."""

    label: str
    exit_code: int | None = None  # None if generate raised or timed out
    blockers: dict[str, int] = field(default_factory=dict)
    boundaries: dict[str, int] = field(default_factory=dict)
    detail: str | None = None

    @property
    def blocked(self) -> bool:
        return bool(self.blockers)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": "blocked" if self.blocked else "clean",
            "exit_code": self.exit_code,
            "blockers": dict(sorted(self.blockers.items())),
            "boundaries": dict(sorted(self.boundaries.items())),
            "detail": self.detail,
        }

    @classmethod
    def from_dict(cls, label: str, data: Mapping[str, Any]) -> ProgramResult:
        return cls(
            label=label,
            exit_code=data.get("exit_code"),
            blockers={str(k): int(v) for k, v in data.get("blockers", {}).items()},
            boundaries={str(k): int(v) for k, v in data.get("boundaries", {}).items()},
            detail=data.get("detail"),
        )


def _bump(counts: dict[str, int], key: str, by: int = 1) -> None:
    counts[key] = counts.get(key, 0) + by


def classify_output(label: str, exit_code: int, stdout: str) -> ProgramResult:
    """Tally what one `mockymock generate` run printed. Blockers are
    recorded only for a non-zero exit: a clean run can still print a
    refusal-shaped line for a case it wrote on purpose (`--per-paragraph`
    scaffolds are meant to be pruned)."""
    result = ProgramResult(label=label, exit_code=exit_code)
    lines = stdout.splitlines()

    in_boundary_block = False
    for line in lines:
        if _BOUNDARY_HEADER_RE.search(line):
            in_boundary_block = True
            continue
        if in_boundary_block:
            boundary_match = _BOUNDARY_LINE_RE.match(line)
            if boundary_match is None:
                in_boundary_block = line.startswith("  - ")
                continue
            nested_prefix, name = boundary_match.groups()
            _bump(result.boundaries, f"nested {name}" if nested_prefix else name)

    if exit_code == 0:
        return result

    header_match = _PARSE_ERROR_HEADER_RE.search(stdout)
    if header_match:
        _bump(result.blockers, PARSE_ERROR, int(header_match.group(1)))
    for line in lines:
        refused_match = _REFUSED_RE.search(line)
        if refused_match:
            _bump(result.blockers, refused_match.group(1))
        elif _COPYBOOK_HINT in line:
            _bump(result.blockers, UNRESOLVED_COPYBOOK)
        elif _NO_TEST_CASE in line:
            _bump(result.blockers, NO_TEST_CASE)
        elif _NO_SCENARIO in line:
            _bump(result.blockers, NO_SCENARIO)

    if not result.blockers:
        _bump(result.blockers, OTHER)
        result.detail = _first_message(lines)
    return result


def _first_message(lines: Iterable[str]) -> str | None:
    for line in lines:
        text = line.strip()
        if text:
            return text.removeprefix(_GENERATE_PREFIX.strip()).strip()
    return None


def crashed(label: str, traceback_text: str) -> ProgramResult:
    """A run that raised: the last traceback line names the error."""
    tail = traceback_text.strip().splitlines()
    return ProgramResult(
        label=label, blockers={EXCEPTION: 1}, detail=tail[-1] if tail else None
    )


def timed_out(label: str, seconds: float) -> ProgramResult:
    return ProgramResult(
        label=label, blockers={TIMEOUT: 1}, detail=f"no result after {seconds:g}s"
    )


# --- snapshots ------------------------------------------------------------


@dataclass
class SweepSnapshot:
    """Every program's outcome in one sweep, keyed by label."""

    programs: dict[str, ProgramResult]
    generated_at: str = ""
    corpus: list[str] = field(default_factory=list)

    @classmethod
    def from_results(
        cls, results: Iterable[ProgramResult], corpus: Iterable[str] = ()
    ) -> SweepSnapshot:
        programs: dict[str, ProgramResult] = {}
        for result in results:
            # Two programs sharing a label would make the diff guess; keep
            # both under distinct keys instead.
            key, n = result.label, 2
            while key in programs:
                key, n = f"{result.label} ({n})", n + 1
            result.label = key
            programs[key] = result
        return cls(
            programs=programs,
            generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
            corpus=list(corpus),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": SNAPSHOT_FORMAT,
            "version": SNAPSHOT_VERSION,
            "generated_at": self.generated_at,
            "corpus": self.corpus,
            "programs": {
                label: result.to_dict()
                for label, result in sorted(self.programs.items())
            },
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> SweepSnapshot:
        if data.get("format") != SNAPSHOT_FORMAT:
            raise ValueError(
                f"not a sweep snapshot (format is {data.get('format')!r}, "
                f"expected {SNAPSHOT_FORMAT!r})"
            )
        version = data.get("version")
        if version != SNAPSHOT_VERSION:
            raise ValueError(
                f"unsupported sweep snapshot version {version!r} "
                f"(this mockymock reads version {SNAPSHOT_VERSION})"
            )
        return cls(
            programs={
                label: ProgramResult.from_dict(label, entry)
                for label, entry in data.get("programs", {}).items()
            },
            generated_at=str(data.get("generated_at", "")),
            corpus=list(data.get("corpus", [])),
        )

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(self.to_dict(), indent=2) + "\n", encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> SweepSnapshot:
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))

    @property
    def blocked_count(self) -> int:
        return sum(1 for r in self.programs.values() if r.blocked)

    @property
    def clean_count(self) -> int:
        return len(self.programs) - self.blocked_count

    def blocker_tally(self) -> dict[str, int]:
        """How many programs each blocker category blocks (a program
        refused twice for one code counts once)."""
        tally: dict[str, int] = {}
        for result in self.programs.values():
            for category in result.blockers:
                _bump(tally, category)
        return tally

    def boundary_tally(self) -> dict[str, int]:
        """How many unmockable boundary points of each category, corpus-wide."""
        tally: dict[str, int] = {}
        for result in self.programs.values():
            for category, count in result.boundaries.items():
                _bump(tally, category, count)
        return tally


# --- diff -----------------------------------------------------------------


@dataclass
class CategoryChange:
    category: str
    before: int
    after: int
    # Programs in both runs that gained / lost this category; programs only
    # in one run are reported as added/removed, not here.
    gained: list[str] = field(default_factory=list)
    lost: list[str] = field(default_factory=list)

    @property
    def delta(self) -> int:
        return self.after - self.before


@dataclass
class SweepDiff:
    previous: SweepSnapshot
    current: SweepSnapshot
    categories: list[CategoryChange]
    boundaries: list[CategoryChange]
    newly_clean: list[str]
    newly_blocked: list[str]
    changed: list[str]  # still blocked, by a different set of categories
    added: list[str]
    removed: list[str]

    @property
    def regressions(self) -> list[str]:
        """Programs in both runs blocked by a category they were not
        blocked by before (newly blocked ones included)."""
        return sorted({p for c in self.categories for p in c.gained})

    @property
    def has_regressions(self) -> bool:
        return bool(self.regressions)


def _category_changes(
    previous: Mapping[str, ProgramResult],
    current: Mapping[str, ProgramResult],
    before: Mapping[str, int],
    after: Mapping[str, int],
    attr: str,
) -> list[CategoryChange]:
    common = sorted(previous.keys() & current.keys())
    changes: list[CategoryChange] = []
    for category in before.keys() | after.keys():
        change = CategoryChange(
            category, before.get(category, 0), after.get(category, 0)
        )
        for label in common:
            had = category in getattr(previous[label], attr)
            has = category in getattr(current[label], attr)
            if has and not had:
                change.gained.append(label)
            elif had and not has:
                change.lost.append(label)
        changes.append(change)
    changes.sort(key=lambda c: (-c.after, -c.before, c.category))
    return changes


def diff_snapshots(previous: SweepSnapshot, current: SweepSnapshot) -> SweepDiff:
    old, new = previous.programs, current.programs
    common = sorted(old.keys() & new.keys())
    newly_clean = [p for p in common if old[p].blocked and not new[p].blocked]
    newly_blocked = [p for p in common if new[p].blocked and not old[p].blocked]
    changed = [
        p
        for p in common
        if old[p].blocked
        and new[p].blocked
        and old[p].blockers.keys() != new[p].blockers.keys()
    ]
    return SweepDiff(
        previous=previous,
        current=current,
        categories=_category_changes(
            old, new, previous.blocker_tally(), current.blocker_tally(), "blockers"
        ),
        boundaries=_category_changes(
            old, new, previous.boundary_tally(), current.boundary_tally(), "boundaries"
        ),
        newly_clean=newly_clean,
        newly_blocked=newly_blocked,
        changed=changed,
        added=sorted(new.keys() - old.keys()),
        removed=sorted(old.keys() - new.keys()),
    )


# --- Markdown -------------------------------------------------------------


def _counts(counts: Mapping[str, int]) -> str:
    return ", ".join(f"{k} x{n}" if n > 1 else k for k, n in sorted(counts.items()))


def render_report(snapshot: SweepSnapshot) -> str:
    """The per-program table plus the per-category tallies."""
    programs = sorted(snapshot.programs.values(), key=lambda r: r.label)
    lines = [
        "# Corpus Sweep Report",
        "",
        f"Swept {len(programs)} COBOL program(s) with `mockymock generate` "
        "(parse-and-analyze only, no Docker/compile).",
        "",
        "| Program | Status | Generate Exit | Blockers | "
        "Unmockable Boundaries (by category) |",
        "|---|---|---|---|---|",
    ]
    for result in programs:
        blockers = _counts(result.blockers) or "-"
        if result.detail:
            blockers += f" ({result.detail.replace('|', '/')})"
        exit_display = "-" if result.exit_code is None else str(result.exit_code)
        lines.append(
            f"| {result.label} | {'blocked' if result.blocked else 'clean'} | "
            f"{exit_display} | {blockers} | {_counts(result.boundaries) or '-'} |"
        )
    lines += [
        "",
        "## Totals",
        "",
        f"- Programs swept: {len(programs)}",
        f"- Generate exited 0 (clean): {snapshot.clean_count}",
        f"- Blocked: {snapshot.blocked_count}",
        "",
        "### Blockers by category (programs)",
        "",
    ]
    lines += _tally_table(snapshot.blocker_tally())
    lines += ["", "### Unmockable-boundary categories (sites)", ""]
    lines += _tally_table(snapshot.boundary_tally())
    lines.append("")
    return "\n".join(lines)


def _tally_table(tally: Mapping[str, int]) -> list[str]:
    if not tally:
        return ["(none)"]
    rows = ["| Category | Count |", "|---|---|"]
    rows += [
        f"| {category} | {count} |"
        for category, count in sorted(tally.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    return rows


def _signed(n: int) -> str:
    return f"+{n}" if n > 0 else str(n)


def _names(labels: list[str], limit: int = 8) -> str:
    if not labels:
        return "-"
    shown = ", ".join(labels[:limit])
    return shown if len(labels) <= limit else f"{shown}, +{len(labels) - limit} more"


def render_diff(diff: SweepDiff) -> str:
    """Progress and regressions per category against an earlier run."""
    prev, cur = diff.previous, diff.current
    lines = [
        "## Changes since the previous sweep",
        "",
        f"Compared with the sweep of {prev.generated_at or 'an unknown date'}.",
        "",
        "| | Previous | Current | Change |",
        "|---|---|---|---|",
        f"| Programs | {len(prev.programs)} | {len(cur.programs)} | "
        f"{_signed(len(cur.programs) - len(prev.programs))} |",
        f"| Clean | {prev.clean_count} | {cur.clean_count} | "
        f"{_signed(cur.clean_count - prev.clean_count)} |",
        f"| Blocked | {prev.blocked_count} | {cur.blocked_count} | "
        f"{_signed(cur.blocked_count - prev.blocked_count)} |",
        "",
    ]
    if diff.regressions:
        lines += [
            f"**{len(diff.regressions)} regression(s):** a program blocked by "
            "a category it was not blocked by before.",
            "",
        ]
    else:
        lines += ["No regressions.", ""]

    lines += ["### Blockers by category (programs)", ""]
    lines += _change_table(diff.categories, "Newly blocked", "Cleared")
    lines += ["", "### Unmockable-boundary categories (sites)", ""]
    lines += _change_table(diff.boundaries, "Gained", "Lost")

    sections = [
        ("Newly clean", diff.newly_clean),
        ("Newly blocked", diff.newly_blocked),
        ("Blocked for a different reason", diff.changed),
        ("Added to the corpus", diff.added),
        ("Removed from the corpus", diff.removed),
    ]
    lines += ["", "### Programs that changed", ""]
    if not any(labels for _, labels in sections):
        lines.append("(none)")
    for title, labels in sections:
        if not labels:
            continue
        lines.append(f"**{title} ({len(labels)}):**")
        lines.append("")
        for label in labels:
            lines.append(f"- {label}{_transition(diff, label)}")
        lines.append("")
    if lines[-1] != "":
        lines.append("")
    return "\n".join(lines)


def _transition(diff: SweepDiff, label: str) -> str:
    old = diff.previous.programs.get(label)
    new = diff.current.programs.get(label)
    before = _counts(old.blockers) if old is not None else ""
    after = _counts(new.blockers) if new is not None else ""
    if old is not None and new is not None:
        return f": {before or 'clean'} -> {after or 'clean'}"
    return f": {before or after}" if (before or after) else ""


def _change_table(changes: list[CategoryChange], gained: str, lost: str) -> list[str]:
    if not changes:
        return ["(none)"]
    rows = [
        f"| Category | Previous | Current | Change | {gained} | {lost} |",
        "|---|---|---|---|---|---|",
    ]
    for change in changes:
        rows.append(
            f"| {change.category} | {change.before} | {change.after} | "
            f"{_signed(change.delta) if change.delta else '0'} | "
            f"{_names(change.gained)} | {_names(change.lost)} |"
        )
    return rows
