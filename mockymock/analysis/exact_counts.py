"""Which boundary sites run on every pass through a test case's entry
paragraph, so that a fixture bundle's per-site `call_count` for them can
be trusted as written (issue #160).

A site qualifies only when nothing between the entry and the site decides
whether it runs: the site sits at the top level of its paragraph (or in an
inline PERFORM body there), and the paragraph is reached from the entry
through a chain of top-level PERFORMs alone, each paragraph on it entered
by nothing but such PERFORMs -- no PERFORM inside an IF/EVALUATE/AT
END, no GO TO, no SORT/MERGE or XML PARSE procedure, no fall-through
from a GO TO target. A site behind `IF SQLCODE NOT = 0` (LOANPMT's ROLLBACK), or
in a paragraph PERFORMed only from inside `IF RECORD-OK` (DEPTMQP's
MQPUT), does not.

Looping PERFORMs (UNTIL / VARYING / TIMES) count as top-level edges: how
many times a loop runs is what the bundle's row data already models
(`analysis.loops`), and is left to it. An early exit (`IF ... GOBACK`, or
a GO TO the splicer turns into EXIT PARAGRAPH) is not modeled either: the
statements after it are still treated as running.
"""

from __future__ import annotations

from typing import Any

from cobolparser.models.statements.control import (
    GoStatement,
    PerformStatement,
    StopStatement,
)
from cobolparser.models.statements.misc import GobackStatement

from mockymock.analysis.mock_surface import _all_paragraphs, _nested_statement_lists


def _unconditional(statements: list):
    """Statements in `statements` that run whenever the list does: the
    list itself and, recursively, every inline PERFORM body in it."""
    for statement in statements:
        yield statement
        if isinstance(statement, PerformStatement):
            yield from _unconditional(statement.inline_statements or [])


def _conditional_performs(statements: list):
    """Every PERFORM nested under something other than an inline PERFORM
    (an IF/EVALUATE branch, an AT END / INVALID KEY body, ...), less the ones in a branch that
    ends the run (`IF NOT MQ-CONNECTED PERFORM 3000-FINALIZE STOP RUN`):
    a paragraph reached that way and also on the straight path still runs
    once either way -- the branch stops the program before the straight
    path gets to it. (Like an early GOBACK, what the stop skips is not
    modeled.)"""
    for statement in _unconditional(statements):
        if isinstance(statement, PerformStatement):
            continue
        for nested in _nested_statement_lists(statement):
            yield from _branch_performs(nested)


def _branch_performs(statements: list):
    ends_run = any(_stops_run(statement) for statement in statements)
    for statement in statements:
        if isinstance(statement, PerformStatement) and statement.target_paragraph:
            if not ends_run:
                yield statement
        for nested in _nested_statement_lists(statement):
            yield from _branch_performs(nested)


def _stops_run(statement) -> bool:
    if isinstance(statement, GobackStatement):
        return True
    return isinstance(statement, StopStatement) and statement.stop_type == "RUN"


def _walk(statements: list):
    for statement in statements:
        yield statement
        for nested in _nested_statement_lists(statement):
            yield from _walk(nested)


def exact_count_scope(
    program,
    entry: str,
    reachable: set[str],
    neutralized_goto: frozenset[str] = frozenset(),
) -> tuple[set[str], set[int]] | None:
    """(paragraph/section names, ids of statements) whose boundary sites
    run on every `PERFORM entry` -- see the module docstring -- or None
    when the program's paragraphs can't be laid out (the caller then keeps
    its older, coarser check)."""
    from mockymock.analysis.refusal._reachability import (
        _expand_thru_range,
        _find_sort_merge_statements,
        _find_xml_parse_statements,
        _go_statement_target,
        _reachable_paragraphs,
        _source_ordered_paragraphs,
    )

    procedure = program.get_division("PROCEDURE") if program is not None else None
    if procedure is None:
        return None
    ordered = _source_ordered_paragraphs(procedure)
    by_name: dict[str, Any] = {}
    for paragraph in _all_paragraphs(procedure):
        by_name.setdefault(paragraph.paragraph_name, paragraph)
    section_members: dict[str, list[str]] = {
        name: [p.paragraph_name for p in section.paragraphs]
        for name, section in getattr(procedure, "_sections", {}).items()
        if name
    }

    def members(target: str | None, thru: str | None) -> list[str] | None:
        """Paragraph names one PERFORM of `target` [THRU `thru`] executes
        directly, or None when the range can't be resolved."""
        if not target:
            return None
        if thru:
            names, problem = _expand_thru_range(ordered, target, thru, "")
            return None if problem is not None else names
        if target in section_members:
            return list(section_members[target])
        return [target] if target in by_name else None

    # Edges out of every reachable paragraph: the top-level PERFORMs, and
    # every other way it hands control to a paragraph.
    straight: dict[str, list[str]] = {}
    other: dict[str, set[str]] = {}
    go_to: set[str] = set()
    range_ends: set[str] = set()
    for name in reachable:
        paragraph = by_name.get(name)
        if paragraph is None:
            continue
        targets: list[str] = []
        others: set[str] = set()
        for statement in _unconditional(paragraph.statements):
            if isinstance(statement, PerformStatement) and statement.target_paragraph:
                names = members(statement.target_paragraph, statement.thru_paragraph)
                if names is None:
                    return None
                targets.extend(names)
        for statement in _walk(paragraph.statements):
            if isinstance(statement, PerformStatement) and statement.thru_paragraph:
                range_ends.add(statement.thru_paragraph)
            elif isinstance(statement, GoStatement):
                found = _go_targets(statement, neutralized_goto, _go_statement_target)
                go_to |= found
                others |= found
        for statement in _conditional_performs(paragraph.statements):
            names = members(statement.target_paragraph, statement.thru_paragraph)
            others.update(names or [statement.target_paragraph])
        for statement in _find_sort_merge_statements(paragraph.statements):
            for attr in ("input_procedure", "output_procedure"):
                if getattr(statement, attr, None):
                    others.add(getattr(statement, attr))
        for statement in _find_xml_parse_statements(paragraph.statements):
            if getattr(statement, "processing_procedure", None):
                others.add(statement.processing_procedure)
        straight[name] = targets
        other[name] = others

    # Whatever a non-straight edge reaches may run a different number of
    # times. A GO TO target also falls through into the paragraphs after
    # it -- unless it is the end of a PERFORM ... THRU range (the `GO TO
    # nnnn-EXIT` idiom), where the range's own return stops it.
    tainted: set[str] = set()
    stack = [target for targets in other.values() for target in targets]
    for target in go_to - range_ends:
        reached, _ = _reachable_paragraphs(
            program, target, neutralized_goto=neutralized_goto
        )
        stack.extend(reached)
    while stack:
        name = stack.pop()
        if name in tainted:
            continue
        tainted.add(name)
        stack.extend(section_members.get(name, []))
        stack.extend(straight.get(name, []))
        stack.extend(other.get(name, set()))

    start = members(entry, None) or []
    exact: set[str] = set()
    stack = [name for name in start if name not in tainted]
    while stack:
        name = stack.pop()
        if name in exact:
            continue
        exact.add(name)
        stack.extend(t for t in straight.get(name, []) if t not in tainted)
    statement_ids = {
        id(statement)
        for name in exact
        if name in by_name
        for statement in _unconditional(by_name[name].statements)
    }
    return exact, statement_ids


def _go_targets(statement, neutralized_goto, single_target) -> set[str]:
    target = single_target(statement)
    if target is not None and target in neutralized_goto:
        return set()
    targets = list(statement.target_paragraphs or [])
    if not targets and statement.target_paragraph:
        targets = [statement.target_paragraph]
    return set(targets)
