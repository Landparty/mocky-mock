"""Behaviour baselines: record what a suite's program sends out, compare later.

`mockymock run --record-baseline FILE` writes one JSON document per suite
run: for each test case, every mocked boundary it reached in order, the
bytes of each value it sent there, the program's own DISPLAY output and
the RETURN-CODE it ended with (`splicer.behaviour`). `mockymock run
--baseline FILE` runs the suite the same way and compares each case with
the recorded one.

The baseline is only meaningful with the same mocks: a changed `.cut`
changes what the boundaries answer, so the comparison says when the
suite file differs from the one the baseline was recorded with.

See docs/2026-11-01-baseline-design.md.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mockymock.report.results import BehaviourEvent, TestResult, TestSuiteResult

FORMAT = "mockymock-baseline"
#: 2 (2026-11-02): adds the `SQL CURSOR <name>` event after a cursor OPEN
#: and the end-of-case `RETURNED LINKAGE` event. A version-1 baseline is
#: still read: the comparison leaves those events out of the new run.
VERSION = 2
READABLE_VERSIONS = (1, 2)


class BaselineError(ValueError):
    """A baseline file that cannot be read or is not a baseline."""


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _status(result: TestResult) -> str:
    if result.crashed:
        return "crashed"
    return "passed" if result.passed else "failed"


def _case_document(result: TestResult) -> dict[str, Any]:
    return {
        "name": result.case_name,
        "status": _status(result),
        "return_code": result.return_code,
        "events": [{"label": e.label, "data": list(e.data)} for e in result.events],
        "output": list(result.output),
    }


def build_baseline(
    suite_result: TestSuiteResult,
    inputs: dict[str, str],
    tool_version: str,
) -> dict[str, Any]:
    """The baseline document for one run. `inputs` maps each input file's
    role ("cut", "program", "real:ORDVAL") to its SHA-256."""
    return {
        "format": FORMAT,
        "version": VERSION,
        "suite": suite_result.suite_name,
        "recorded_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "mockymock": tool_version,
        "inputs": dict(sorted(inputs.items())),
        "cases": [_case_document(result) for result in suite_result.results],
    }


def write_baseline(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def load_baseline(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BaselineError(f"cannot read baseline {path}: {exc}") from exc
    if not isinstance(document, dict) or document.get("format") != FORMAT:
        raise BaselineError(f"{path} is not a mockymock baseline")
    if document.get("version") not in READABLE_VERSIONS:
        raise BaselineError(
            f"{path} is baseline version {document.get('version')!r}; this "
            f"mockymock reads versions {', '.join(map(str, READABLE_VERSIONS))}"
        )
    if not isinstance(document.get("cases"), list):
        raise BaselineError(f"{path} has no cases list")
    return document


@dataclass
class CaseComparison:
    """One test case compared with its baseline.

    `verdict` is "same", "differs", "new" (no baseline for this case) or
    "not-run" (in the baseline, not in this run)."""

    name: str
    verdict: str
    differences: list[str] = field(default_factory=list)


@dataclass
class BaselineComparison:
    suite: str
    cases: list[CaseComparison]
    #: Input files whose hash differs from the baseline's, by role.
    changed_inputs: list[str] = field(default_factory=list)
    #: What the comparison could not cover (an older baseline format).
    notes: list[str] = field(default_factory=list)

    @property
    def matches(self) -> bool:
        """True when no case's behaviour differs from the baseline."""
        return all(case.verdict != "differs" for case in self.cases)

    def counts(self) -> dict[str, int]:
        counts = {"same": 0, "differs": 0, "new": 0, "not-run": 0}
        for case in self.cases:
            counts[case.verdict] += 1
        return counts

    def to_dict(self) -> dict[str, Any]:
        return {
            "suite": self.suite,
            "matches": self.matches,
            "counts": self.counts(),
            "changed_inputs": list(self.changed_inputs),
            "notes": list(self.notes),
            "cases": [
                {"name": c.name, "verdict": c.verdict, "differences": c.differences}
                for c in self.cases
            ],
        }


def _describe_event(event: dict[str, Any] | None) -> str:
    if event is None:
        return "nothing"
    data = event.get("data") or []
    if not data:
        return str(event.get("label"))
    shown = ", ".join(_short(value) for value in data)
    return f"{event.get('label')} [{shown}]"


def _short(value: str, limit: int = 48) -> str:
    return value if len(value) <= limit else value[:limit] + "..."


def _event_difference(
    index: int, expected: dict[str, Any] | None, actual: dict[str, Any] | None
) -> str:
    if expected is not None and actual is not None:
        if expected.get("label") == actual.get("label"):
            for position, (old, new) in enumerate(
                zip(expected.get("data") or [], actual.get("data") or [], strict=False),
                start=1,
            ):
                if old != new:
                    return (
                        f"event {index + 1} ({expected.get('label')}): value "
                        f"{position} was {_short(old)}, now {_short(new)}"
                        f"{_text_hint(old, new)}"
                    )
            return (
                f"event {index + 1} ({expected.get('label')}): sent "
                f"{len(expected.get('data') or [])} value(s), now "
                f"{len(actual.get('data') or [])}"
            )
    return (
        f"event {index + 1}: was {_describe_event(expected)}, "
        f"now {_describe_event(actual)}"
    )


def _text_hint(old: str, new: str) -> str:
    """The values as text, when both are printable ASCII."""
    shown = []
    for value in (old, new):
        try:
            raw = bytes.fromhex(value.rstrip("+"))
        except ValueError:
            return ""
        if not raw or any(byte < 0x20 or byte > 0x7E for byte in raw):
            return ""
        shown.append(_short(raw.decode("ascii")))
    return f' ("{shown[0]}" -> "{shown[1]}")'


def compare_case(expected: dict[str, Any], actual: dict[str, Any]) -> list[str]:
    """Every difference between a recorded case and a new run of it."""
    differences: list[str] = []
    if expected.get("status") != actual.get("status"):
        differences.append(
            f"status was {expected.get('status')}, now {actual.get('status')}"
        )
    old_events = expected.get("events") or []
    new_events = actual.get("events") or []
    for index in range(max(len(old_events), len(new_events))):
        old = old_events[index] if index < len(old_events) else None
        new = new_events[index] if index < len(new_events) else None
        if old != new:
            differences.append(_event_difference(index, old, new))
            break
    if len(old_events) != len(new_events):
        differences.append(
            f"{len(old_events)} boundary event(s) recorded, {len(new_events)} now"
        )
    old_output = expected.get("output") or []
    new_output = actual.get("output") or []
    if old_output != new_output:
        for index in range(max(len(old_output), len(new_output))):
            old_line = old_output[index] if index < len(old_output) else None
            new_line = new_output[index] if index < len(new_output) else None
            if old_line != new_line:
                differences.append(
                    f"output line {index + 1} was {old_line!r}, now {new_line!r}"
                )
                break
    if expected.get("return_code") != actual.get("return_code"):
        differences.append(
            f"RETURN-CODE was {expected.get('return_code')}, "
            f"now {actual.get('return_code')}"
        )
    return differences


def compare(
    baseline: dict[str, Any], suite_result: TestSuiteResult, inputs: dict[str, str]
) -> BaselineComparison:
    """Compare a run with a baseline, case by case (matched by name)."""
    recorded = {case.get("name"): case for case in baseline.get("cases", [])}
    legacy = baseline.get("version") == 1
    seen: set[str] = set()
    cases: list[CaseComparison] = []
    for result in suite_result.results:
        seen.add(result.case_name)
        expected = recorded.get(result.case_name)
        if expected is None:
            cases.append(CaseComparison(result.case_name, "new"))
            continue
        actual = _case_document(result)
        if legacy:
            actual = _as_version_1(actual)
        differences = compare_case(expected, actual)
        cases.append(
            CaseComparison(
                result.case_name, "differs" if differences else "same", differences
            )
        )
    for name in recorded:
        if name not in seen:
            cases.append(CaseComparison(str(name), "not-run"))
    old_inputs = baseline.get("inputs") or {}
    changed = sorted(
        role
        for role in set(old_inputs) | set(inputs)
        if old_inputs.get(role) != inputs.get(role)
    )
    notes = (
        [
            "baseline version 1: cursor inputs and returned LINKAGE were not "
            "recorded, so they are not compared; record a new baseline to "
            "cover them"
        ]
        if legacy
        else []
    )
    return BaselineComparison(
        suite=suite_result.suite_name, cases=cases, changed_inputs=changed, notes=notes
    )


def _as_version_1(case: dict[str, Any]) -> dict[str, Any]:
    """A case document without the events version 1 did not record."""
    from mockymock.splicer.behaviour import V2_EVENT_PREFIXES

    events = [
        event
        for event in case.get("events") or []
        if not str(event.get("label", "")).startswith(V2_EVENT_PREFIXES)
    ]
    return {**case, "events": events}


def format_comparison(comparison: BaselineComparison) -> str:
    """Console text for a comparison."""
    counts = comparison.counts()
    lines = [
        f"baseline: {counts['same']} same, {counts['differs']} differ, "
        f"{counts['new']} new, {counts['not-run']} not run"
    ]
    for case in comparison.cases:
        tag = {
            "same": "SAME",
            "differs": "DIFFERS",
            "new": "NEW",
            "not-run": "NOT RUN",
        }[case.verdict]
        lines.append(f"  [{tag}] {case.name}")
        lines.extend(f"      {difference}" for difference in case.differences)
    if comparison.changed_inputs:
        lines.append(
            "  changed since the baseline: " + ", ".join(comparison.changed_inputs)
        )
        if "cut" in comparison.changed_inputs:
            lines.append(
                "  the .cut file changed: its mocks may answer differently "
                "than when the baseline was recorded"
            )
    lines.extend(f"  note: {note}" for note in comparison.notes)
    return "\n".join(lines)


__all__ = [
    "BaselineComparison",
    "BaselineError",
    "BehaviourEvent",
    "CaseComparison",
    "build_baseline",
    "compare",
    "compare_case",
    "format_comparison",
    "load_baseline",
    "sha256_file",
    "write_baseline",
]
