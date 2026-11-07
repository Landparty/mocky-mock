"""Paragraph, branch and statement coverage from GnuCOBOL's statement trace.

`mockymock run --branch-coverage FILE` compiles the suite with
`-ftraceall` (the trace `run --trace` already uses) and reads the trace of
the WHOLE run, every case, instead of gcov. Two reasons
(docs/2026-11-06-branch-coverage-design.md):

* the trace works on every GnuCOBOL 3.x, while gcov needs `cobc
  --coverage` (3.2 and later);
* the trace keeps the ORDER statements ran in, which is what tells an IF's
  false outcome from its true one: line counts alone cannot, when the IF has
  no ELSE.

What is measured, per program (the program under test and every `USE REAL
CALL` program linked in, each under its own PROGRAM-ID):

* paragraphs: every paragraph of the AST, entered or not;
* branches: an `IF` has a true and a false outcome, an `EVALUATE` one
  outcome per WHEN group, `WHEN OTHER`, or "no WHEN matched" when it has no
  OTHER. An outcome is covered when the first statement traced after the IF
  (after the EVALUATE's own WHEN tests) is the first statement of that
  branch. A branch with no statement of its own is decided by elimination
  when only one such outcome is possible, and otherwise the occurrence is
  counted as unattributed: exact by construction, or absent;
* statements: the AST's statement lines, run or not.

Lines are the AST's (normalized-source) lines while measuring and are
reported as the ORIGINAL file's lines (`lines_to_origin`), a copybook's
lines naming the copybook.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from mockymock.report.trace import TraceEntry

if TYPE_CHECKING:
    from mockymock.report.unreachable import Unreachable

BRANCH_COVERAGE_JSON_VERSION = 1

#: Outcome labels.
TRUE = "true"
FALSE = "false"
OTHER = "WHEN OTHER"
NO_WHEN = "no WHEN matched"

#: Where a normalized line came from: (file name or None for the program
#: file itself, line in it), or None when it maps nowhere.
Origin = tuple[str | None, int] | None


@dataclass
class Outcome:
    label: str
    #: Normalized line of the branch's first statement (None: empty branch).
    first_line: int | None
    hits: int = 0


@dataclass
class BranchPoint:
    kind: str  # "IF" | "EVALUATE"
    line: int  # normalized line of the IF / EVALUATE
    outcomes: list[Outcome]
    #: Why the outcomes cannot be told apart from the trace (None: they can).
    not_measurable: str | None = None
    #: Executions whose outcome the trace could not attribute.
    unattributed: int = 0


@dataclass
class Paragraph:
    name: str
    line: int
    hits: int = 0


@dataclass
class ProgramPoints:
    """The coverage points of one program, from its AST."""

    program_id: str
    paragraphs: list[Paragraph] = field(default_factory=list)
    branches: list[BranchPoint] = field(default_factory=list)
    statement_lines: set[int] = field(default_factory=set)
    executed_lines: set[int] = field(default_factory=set)


def _is_statement(node: object) -> bool:
    return type(node).__name__.endswith("Statement") and _line(node) is not None


def _line(node: object) -> int | None:
    location = getattr(node, "location", None)
    line = getattr(location, "line", None)
    return line if isinstance(line, int) and line > 0 else None


def _first_line(statements: Iterable[object] | None) -> int | None:
    for statement in statements or ():
        line = _line(statement)
        if line is not None:
            return line
    return None


def _walk(node: object) -> Iterable[object]:
    yield node
    for child in getattr(node, "children", None) or ():
        yield from _walk(child)


def _when_label(when: object, lines: list[str]) -> str:
    line = _line(when)
    if line is not None and 0 < line <= len(lines):
        text = " ".join(lines[line - 1].split())
        if text:
            return text[:60]
    return "WHEN"


def program_points(ast: object, lines: list[str]) -> ProgramPoints:
    """Paragraphs, IF / EVALUATE branch points and statement lines of the
    PROCEDURE DIVISION of `ast`, at the normalized lines `lines` numbers."""
    program_id = str(getattr(ast, "program_name", "") or "").upper()
    points = ProgramPoints(program_id=program_id)
    division = getattr(ast, "procedure_division", None)
    if division is None:
        return points
    for node in _walk(division):
        name = type(node).__name__
        if name == "CobolParagraph":
            line = _line(node)
            paragraph = str(getattr(node, "paragraph_name", "") or "")
            if line is not None and paragraph:
                points.paragraphs.append(Paragraph(paragraph.upper(), line))
            continue
        if not _is_statement(node):
            continue
        line = _line(node)
        assert line is not None
        points.statement_lines.add(line)
        if name == "IfStatement":
            points.branches.append(_if_point(node, line))
        elif name == "EvaluateStatement":
            points.branches.append(_evaluate_point(node, line, lines))
    # Two branch statements of one kind on one line: the trace names a line,
    # not a statement, so their executions cannot be told apart.
    per_line = Counter((b.kind, b.line) for b in points.branches)
    for branch in points.branches:
        if per_line[(branch.kind, branch.line)] > 1:
            branch.not_measurable = (
                f"several {branch.kind} statements on one line: the trace "
                "cannot tell their executions apart"
            )
    points.paragraphs.sort(key=lambda p: p.line)
    points.branches.sort(key=lambda b: b.line)
    return points


def _if_point(node: object, line: int) -> BranchPoint:
    then_first = _first_line(getattr(node, "then_statements", None))
    else_first = _first_line(getattr(node, "else_statements", None))
    point = BranchPoint(
        kind="IF",
        line=line,
        outcomes=[Outcome(TRUE, then_first), Outcome(FALSE, else_first)],
    )
    if then_first is not None and then_first == else_first:
        point.not_measurable = "THEN and ELSE start on the same line"
    elif then_first is None and else_first is None:
        point.not_measurable = "neither branch has a statement of its own"
    return point


def _evaluate_point(node: object, line: int, lines: list[str]) -> BranchPoint:
    groups_of = getattr(node, "when_groups", None)
    groups = groups_of() if callable(groups_of) else []
    outcomes: list[Outcome] = []
    for group in groups:
        if not group:
            continue
        # The body hangs off the group's last WHEN (stacked WHENs share it).
        body = getattr(group[-1], "statements", None)
        outcomes.append(Outcome(_when_label(group[0], lines), _first_line(body)))
    default = getattr(node, "default_when", None)
    if default is not None:
        outcomes.append(
            Outcome(OTHER, _first_line(getattr(default, "statements", None)))
        )
    else:
        outcomes.append(Outcome(NO_WHEN, None))
    point = BranchPoint(kind="EVALUATE", line=line, outcomes=outcomes)
    firsts = [o.first_line for o in outcomes if o.first_line is not None]
    if len(firsts) != len(set(firsts)):
        point.not_measurable = "two WHEN bodies start on the same line"
    return point


def measure(
    points: ProgramPoints, entries: list[TraceEntry], to_normalized: dict[int, int]
) -> None:
    """Fold one program's trace `entries` (instrumented lines, in execution
    order) into `points`. `to_normalized` maps the program's instrumented
    lines to its normalized ones; unmapped entries are the splicer's own
    code and are skipped, so "the next statement" is always one of the
    program's own."""
    mapped: list[tuple[int, TraceEntry]] = []
    for entry in entries:
        normalized = to_normalized.get(entry.line)
        if normalized is not None:
            mapped.append((normalized, entry))
    paragraph_at = {p.line: p for p in points.paragraphs}
    branch_at = {(b.kind, b.line): b for b in points.branches}
    for index, (normalized, entry) in enumerate(mapped):
        if entry.paragraph is not None:
            paragraph = paragraph_at.get(normalized)
            if paragraph is not None:
                paragraph.hits += 1
            continue
        points.executed_lines.add(normalized)
        statement = (entry.statement or "").upper()
        if statement not in ("IF", "EVALUATE"):
            continue
        branch = branch_at.get((statement, normalized))
        if branch is None or branch.not_measurable:
            continue
        following = index + 1
        if statement == "EVALUATE":
            while following < len(mapped) and (
                (mapped[following][1].statement or "").upper() == "WHEN"
            ):
                following += 1
        if following >= len(mapped):
            branch.unattributed += 1
            continue
        next_line, next_entry = mapped[following]
        outcome = _outcome_of(
            branch, next_line if next_entry.paragraph is None else None
        )
        if outcome is None:
            branch.unattributed += 1
        else:
            outcome.hits += 1


def _outcome_of(branch: BranchPoint, next_line: int | None) -> Outcome | None:
    """The outcome a branch took, given the line of the next statement run
    (None: the next entry was a paragraph, not a statement)."""
    for outcome in branch.outcomes:
        if outcome.first_line is not None and outcome.first_line == next_line:
            return outcome
    # No branch body started: the one outcome without a statement of its own.
    empty = [o for o in branch.outcomes if o.first_line is None]
    return empty[0] if len(empty) == 1 else None


def split_by_program(
    entries: list[TraceEntry], programs: list[str]
) -> dict[str, list[TraceEntry]]:
    """Trace entries per PROGRAM-ID (upper case), in order. `programs`
    names the ones wanted; the rest (the hexdump helper) are dropped."""
    wanted = {p.upper() for p in programs}
    out: dict[str, list[TraceEntry]] = {p.upper(): [] for p in programs}
    for entry in entries:
        program = (entry.program or "").upper()
        if program in wanted:
            out[program].append(entry)
    return out


def _where(origin: Origin) -> dict[str, object]:
    if origin is None:
        return {"line": None}
    file, line = origin
    return {"line": line, "file": file} if file else {"line": line}


def program_report(
    points: ProgramPoints,
    program_file: str,
    lines_to_origin: Callable[[int], Origin],
    unreachable: Unreachable | None = None,
) -> dict[str, object]:
    """One program's entry of the JSON document. With `unreachable`
    (report.unreachable), every never-run point no test can reach carries
    an `unreachable` reason and each section counts them: `covered` of
    `total - unreachable` is the coverage of what tests can reach."""
    paragraphs: list[dict[str, object]] = []
    for p in points.paragraphs:
        entry: dict[str, object] = {
            "name": p.name,
            **_where(lines_to_origin(p.line)),
            "hits": p.hits,
        }
        reason = unreachable.paragraphs.get(p.name) if unreachable else None
        if reason and not p.hits:
            entry["unreachable"] = reason
        paragraphs.append(entry)
    branches: list[dict[str, object]] = []
    measured_total = measured_covered = 0
    not_measurable = 0
    unreachable_outcomes = 0
    for branch in points.branches:
        never = (
            unreachable.outcomes.get((branch.kind, branch.line), {})
            if unreachable
            else {}
        )
        outcomes: list[dict[str, object]] = []
        for index, o in enumerate(branch.outcomes):
            outcome: dict[str, object] = {
                "label": o.label,
                "hits": o.hits,
                "covered": o.hits > 0,
            }
            if not o.hits and index in never:
                outcome["unreachable"] = never[index]
                if not branch.not_measurable:
                    unreachable_outcomes += 1
            outcomes.append(outcome)
        item: dict[str, object] = {
            "kind": branch.kind,
            **_where(lines_to_origin(branch.line)),
            "outcomes": outcomes,
        }
        if branch.unattributed:
            item["unattributed"] = branch.unattributed
        if branch.not_measurable:
            item["notMeasurable"] = branch.not_measurable
            not_measurable += 1
        else:
            measured_total += len(branch.outcomes)
            measured_covered += sum(1 for o in branch.outcomes if o.hits > 0)
        branches.append(item)
    statements = sorted(points.statement_lines)
    uncovered = [line for line in statements if line not in points.executed_lines]
    uncovered_items: list[dict[str, object]] = []
    for line in uncovered:
        where = _where(lines_to_origin(line))
        reason = unreachable.statements.get(line) if unreachable else None
        if reason:
            where["unreachable"] = reason
        uncovered_items.append(where)
    report: dict[str, object] = {
        "programId": points.program_id,
        "programFile": program_file,
        "paragraphs": {
            "total": len(paragraphs),
            "covered": sum(1 for p in paragraphs if p["hits"]),
            "items": paragraphs,
        },
        "branches": {
            "total": measured_total,
            "covered": measured_covered,
            "notMeasurable": not_measurable,
            "items": branches,
        },
        "statements": {
            "total": len(statements),
            "covered": len(statements) - len(uncovered),
            "uncovered": uncovered_items,
        },
    }
    if unreachable is not None:
        report["paragraphs"]["unreachable"] = sum(  # type: ignore[index]
            1 for p in paragraphs if "unreachable" in p
        )
        report["branches"]["unreachable"] = unreachable_outcomes  # type: ignore[index]
        report["statements"]["unreachable"] = sum(  # type: ignore[index]
            1 for s in uncovered_items if "unreachable" in s
        )
        report["unreachableScope"] = unreachable.scope
        if unreachable.note:
            report["unreachableNote"] = unreachable.note
    return report


def format_branch_coverage_json(
    programs: list[dict[str, object]], cut_file: str, cases_run: int
) -> str:
    payload = {
        "version": BRANCH_COVERAGE_JSON_VERSION,
        "cutFile": cut_file,
        "casesRun": cases_run,
        "programs": programs,
    }
    return json.dumps(payload, indent=2) + "\n"


def _ratio(section: dict[str, object]) -> str:
    total = int(section["total"])  # type: ignore[call-overload]
    covered = int(section["covered"])  # type: ignore[call-overload]
    percent = 100.0 * covered / total if total else 100.0
    text = f"{covered}/{total} ({percent:.0f}%)"
    unreachable = int(section.get("unreachable") or 0)  # type: ignore[call-overload]
    if unreachable:
        reachable = total - unreachable
        share = 100.0 * covered / reachable if reachable else 100.0
        text += f" [{covered}/{reachable} reachable ({share:.0f}%)]"
    return text


def format_branch_coverage_console(programs: list[dict[str, object]]) -> str:
    lines = []
    for program in programs:
        lines.append(
            f"mockymock run: branch coverage: {program['programId']}: "
            f"paragraphs {_ratio(program['paragraphs'])}, "  # type: ignore[arg-type]
            f"branches {_ratio(program['branches'])}, "  # type: ignore[arg-type]
            f"statements {_ratio(program['statements'])}"  # type: ignore[arg-type]
        )
        missed = [
            str(p["name"])
            for p in program["paragraphs"]["items"]  # type: ignore[index]
            if not p["hits"] and not p.get("unreachable")
        ]
        if missed:
            lines.append(f"  paragraphs never entered: {', '.join(missed)}")
        for branch in program["branches"]["items"]:  # type: ignore[index]
            if branch.get("notMeasurable"):
                continue
            gaps = [
                o["label"]
                for o in branch["outcomes"]
                if not o["covered"] and not o.get("unreachable")
            ]
            if gaps:
                where = branch.get("line")
                lines.append(
                    f"  line {where}: {branch['kind']} never took: {', '.join(gaps)}"
                )
    return "\n".join(lines)


def origin_lookup(
    location_map: dict[int, tuple[str, int]] | None,
    to_original: dict[int, int],
) -> Callable[[int], Origin]:
    """Normalized line -> where it came from. `location_map` (a copybook
    expansion's source map, `"<main>"` for the program's own lines) wins;
    otherwise the fixed-format alignment `to_original`."""
    from pathlib import Path

    def lookup(line: int) -> Origin:
        origin = (location_map or {}).get(line)
        if origin is not None:
            file, number = origin
            return (None if file == "<main>" else Path(file).name, number)
        if line in to_original:
            return (None, to_original[line])
        return None

    return lookup
