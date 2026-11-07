"""Which coverage points no test can reach, for `run --branch-coverage`.

A coverage gap means one of two things: a test has not reached the code
yet, or nothing ever will. cobol-parser's `InputDependenceAnalyzer`
(cobol-parser 3.7+) tells them apart. It finds every IF / EVALUATE whose
answer no input can change -- nothing a mock returns, no FILE STATUS, no
ACCEPT, no LINKAGE item, no setup MOVE reaches its operands or the
decisions it runs under -- so every run from the program's entry point
evaluates it the same way. An outcome the measured run never took is then
unreachable, and so is the code behind it: the self-checking FAIL branch of
a validation program, or a paragraph nothing PERFORMs.

That argument only holds for runs that start at the program's entry point,
so the outcome-level claims are made only when every case (and every
BEFORE/AFTER hook) PERFORMs the entry paragraph and no case mocks a
paragraph or section. Otherwise only code no PERFORM, GO TO or fall-through
reaches at all is reported, which holds whatever the cases do.

Exact by construction, or absent: an older cobol-parser, an analysis that
gives up, or an outcome the trace could not attribute all leave the point a
plain gap.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from mockymock.report.branch_coverage import ProgramPoints

#: Why outcome-level claims were left out (the document's
#: `unreachableScope`).
SCOPE_FULL = "full"
SCOPE_STATIC = "static"


@dataclass
class Unreachable:
    """Coverage points no test can reach, at normalized lines."""

    paragraphs: dict[str, str] = field(default_factory=dict)
    outcomes: dict[tuple[str, int], dict[int, str]] = field(default_factory=dict)
    statements: dict[int, str] = field(default_factory=dict)
    #: SCOPE_FULL, or SCOPE_STATIC with `note` saying why.
    scope: str = SCOPE_FULL
    note: str | None = None


def suite_entries(suite: Any) -> tuple[set[str], set[str], bool]:
    """(paragraphs the suite PERFORMs, data names it MOVEs into, whether it
    mocks a paragraph or section)."""
    from mockymock.dsl.model import FLOW_CATEGORIES

    performs: set[str] = set()
    moves: set[str] = set()
    flow = False
    hooks = [
        *getattr(suite, "before_all_steps", []),
        *getattr(suite, "before_each_steps", []),
        *getattr(suite, "after_each_steps", []),
        *getattr(suite, "after_all_steps", []),
    ]
    for mock in [
        *getattr(suite, "before_all_mocks", []),
        *getattr(suite, "before_each_mocks", []),
    ]:
        flow = flow or mock.category in FLOW_CATEGORIES
    for case in getattr(suite, "test_cases", []):
        steps = [*hooks, *case.steps]
        for step in steps:
            if step.kind == "PERFORM" and step.target:
                performs.add(step.target.upper())
            elif step.kind == "MOVE" and step.target:
                moves.add(step.target)
        if case.perform_target:
            performs.add(case.perform_target.upper())
        moves.update(target for _value, target in case.setup_moves)
        flow = flow or any(m.category in FLOW_CATEGORIES for m in case.mocks)
    return performs, moves, flow


def classify(ast: Any, points: ProgramPoints, suite: Any) -> Unreachable | None:
    """The unreachable points of the program `points` measured, or None when
    cobol-parser cannot tell (too old, or the analysis gave up)."""
    try:
        from cobolparser.analysis.input_dependence import InputDependenceAnalyzer
    except ImportError:
        return None
    performs, moves, flow = suite_entries(suite)
    try:
        report = InputDependenceAnalyzer().analyze(ast, extra_inputs=sorted(moves))
    except Exception:  # noqa: BLE001 - a crash must not cost the coverage report
        return None
    if report.incomplete:
        return None
    entry = set(report.entry_names)
    scope, note = SCOPE_FULL, None
    if flow:
        scope, note = SCOPE_STATIC, "a case mocks a paragraph or section"
    elif not performs or not performs <= entry:
        others = sorted(performs - entry)
        scope = SCOPE_STATIC
        note = (
            f"a case starts at {', '.join(others[:3])}, not at the program's "
            f"entry point ({', '.join(report.entry_names) or 'none'})"
        )
    taken: dict[tuple[str, int], set[int]] = {}
    if scope == SCOPE_FULL:
        for branch in points.branches:
            if branch.not_measurable or branch.unattributed:
                continue
            hit = {i for i, o in enumerate(branch.outcomes) if o.hits > 0}
            if hit:
                taken[(branch.kind, branch.line)] = hit
    found = report.unreachable(
        taken, points.executed_lines if scope == SCOPE_FULL else None
    )
    return Unreachable(
        paragraphs=dict(found.paragraphs),
        outcomes={k: dict(v) for k, v in found.outcomes.items()},
        statements=dict(found.statements),
        scope=scope,
        note=note,
    )
