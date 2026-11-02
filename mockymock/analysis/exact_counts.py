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

A site also has to run exactly ONCE per pass (issue #290): the bundle
gives every site `call_count` 1 however often it really runs. So a looping
PERFORM (UNTIL / VARYING / TIMES) is not a straight edge -- its target, and
everything an inline loop's body holds, is out of scope -- and neither is a
paragraph PERFORMed by more than one straight statement (`PERFORM CALL-B`
twice in a row). READ/RETURN are the exception: their counts come from the
bundle's row data (`analysis.loops` models how many times a read loop runs),
so a caller checking them asks for `loops_exact=True`, the older scope that
treats looping PERFORMs as straight edges.

A site after a statement that may end the run -- one holding a STOP RUN /
GOBACK / EXIT PROGRAM / CICS RETURN in an IF/EVALUATE/AT END body, or a
conditional or looping PERFORM of code that holds one -- is out of scope
too: the scenarios that take that branch (`gen-fixtures`' error-status
family is built to) never reach it. So is one after a branch holding a GO
TO (`READ F AT END GO TO P-END`): the empty-input scenario jumps past it. A GO TO the splicer turns into EXIT
PARAGRAPH is still not modeled: the statements after it are treated as
running.
"""

from __future__ import annotations

from typing import Any

from cobolparser.models.statements.control import (
    GoStatement,
    PerformStatement,
    StopStatement,
)
from cobolparser.models.statements.misc import ExitStatement, GobackStatement

from mockymock.analysis.mock_surface import (
    _all_paragraphs,
    _nested_statement_lists,
    is_cics_terminator,
)


def _unconditional(statements: list, loops_exact: bool = True):
    """Statements in `statements` that run whenever the list does: the
    list itself and, recursively, every inline PERFORM body in it -- only
    the non-looping ones unless `loops_exact`."""
    for statement in statements:
        yield statement
        if isinstance(statement, PerformStatement) and (
            loops_exact or not _is_loop(statement)
        ):
            yield from _unconditional(statement.inline_statements or [], loops_exact)


def _is_loop(statement: PerformStatement) -> bool:
    return getattr(statement, "perform_type", "SIMPLE") != "SIMPLE"


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
    if isinstance(statement, ExitStatement) and statement.exit_type == "PROGRAM":
        return True
    if is_cics_terminator(statement):
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
    loops_exact: bool = False,
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
        _section_range,
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
    # What one `PERFORM <section>` runs: its first paragraph and the ones
    # reached from it by fall-through, not a member after an EXIT SECTION
    # / GOBACK / GO TO that ends the range.
    section_ranges: dict[str, list[str]] = {
        name: [p.paragraph_name for p in _section_range(section)]
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
        if target in section_ranges:
            return list(section_ranges[target])
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
        for statement in _unconditional(paragraph.statements, loops_exact):
            if isinstance(statement, PerformStatement) and statement.target_paragraph:
                names = members(statement.target_paragraph, statement.thru_paragraph)
                if names is None:
                    return None
                if loops_exact or not _is_loop(statement):
                    targets.extend(names)
                else:
                    others.update(names)
        if not loops_exact:
            # A PERFORM nested in an inline loop's body runs once per pass
            # of the loop: whatever it reaches is not exact either.
            for statement in _unconditional(paragraph.statements):
                if isinstance(statement, PerformStatement) and _is_loop(statement):
                    for inner in _walk(statement.inline_statements or []):
                        if (
                            isinstance(inner, PerformStatement)
                            and inner.target_paragraph
                        ):
                            names = members(
                                inner.target_paragraph, inner.thru_paragraph
                            )
                            others.update(names or [inner.target_paragraph])
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
    start = members(entry, None) or []
    if not loops_exact:
        # Reached by two straight PERFORMs, a paragraph runs twice a pass --
        # and so does one the entry's own section range falls into that a
        # straight PERFORM also names.
        seen: set[str] = set()
        for targets in [start, *straight.values()]:
            for target in targets:
                if target in seen:
                    stack.append(target)
                seen.add(target)
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
        for statement in _unconditional(by_name[name].statements, loops_exact)
    }
    before_stop = _before_first_conditional_stop(
        start, exact, by_name, members, loops_exact
    )
    return exact, statement_ids & before_stop


def _before_first_conditional_stop(
    start: list[str],
    exact: set[str],
    by_name: dict[str, Any],
    members,
    loops_exact: bool,
) -> set[int]:
    """Ids of the straight-path statements that run before the first one
    that may end the run on some pass (see the module docstring), in
    execution order: the entry's statements, each straight PERFORM's
    target expanded in place."""
    stops_cache: dict[str, bool] = {}

    def may_stop_in(name: str, visiting: frozenset[str]) -> bool:
        """Whether running `name` can reach a terminator at all."""
        if name in stops_cache:
            return stops_cache[name]
        paragraph = by_name.get(name)
        if paragraph is None or name in visiting:
            return False
        found = False
        for statement in _walk(paragraph.statements):
            if _stops_run(statement):
                found = True
            elif isinstance(statement, PerformStatement) and statement.target_paragraph:
                names = members(statement.target_paragraph, statement.thru_paragraph)
                found = any(
                    may_stop_in(t, visiting | {name})
                    for t in names or [statement.target_paragraph]
                )
            if found:
                break
        stops_cache[name] = found
        return found

    def may_stop(statement, straight_targets: list[str]) -> set[str] | None:
        """None when `statement` cannot end the run other than through a
        straight PERFORM (walked in place instead). Otherwise the
        paragraphs every stopping branch PERFORMs at its top level before
        its own terminator: they run once on either path (DEPTMQP's `IF NOT
        MQ-CONNECTED PERFORM 3000-FINALIZE STOP RUN`), so their counts
        stay exact."""
        stops = False
        rescued: set[str] | None = None
        for nested in _nested_statement_lists(statement):
            top_stop = next(
                (k for k, inner in enumerate(nested) if _stops_run(inner)), None
            )
            if top_stop is not None:
                stops = True
                ran = {
                    t
                    for inner in nested[:top_stop]
                    if isinstance(inner, PerformStatement)
                    and inner.target_paragraph
                    and not inner.inline_statements
                    and not _is_loop(inner)
                    for t in members(inner.target_paragraph, inner.thru_paragraph) or []
                }
                rescued = ran if rescued is None else rescued & ran
                nested = nested[:top_stop]
            for inner in _walk(nested):
                # A GO TO in a branch (`READ ... AT END GO TO P-END`) skips
                # the rest of the straight path just as a STOP RUN does
                # (NIST RW301M's empty input never reached its OPEN).
                if (
                    _stops_run(inner)
                    or isinstance(inner, GoStatement)
                    or (
                        isinstance(inner, PerformStatement)
                        and inner.target_paragraph
                        and any(
                            may_stop_in(t, frozenset())
                            for t in members(
                                inner.target_paragraph, inner.thru_paragraph
                            )
                            or [inner.target_paragraph]
                        )
                    )
                ):
                    return set()
        if (
            isinstance(statement, PerformStatement)
            and statement.target_paragraph
            and not straight_targets
            and any(
                may_stop_in(t, frozenset())
                for t in members(statement.target_paragraph, statement.thru_paragraph)
                or [statement.target_paragraph]
            )
        ):
            return set()
        return (rescued or set()) if stops else None

    kept: set[int] = set()
    # None until the first statement that may end the run; then the
    # paragraphs whose statements still count (see may_stop).
    rescue: set[str] | None = None

    def visit(name: str, path: frozenset[str]) -> None:
        nonlocal rescue
        paragraph = by_name.get(name)
        if paragraph is None or name in path:
            return
        for statement in _unconditional(paragraph.statements, loops_exact):
            if rescue is None or name in rescue:
                kept.add(id(statement))
            straight_targets: list[str] = []
            if (
                isinstance(statement, PerformStatement)
                and statement.target_paragraph
                and not statement.inline_statements
                and (loops_exact or not _is_loop(statement))
            ):
                straight_targets = [
                    t
                    for t in members(
                        statement.target_paragraph, statement.thru_paragraph
                    )
                    or []
                    if t in exact
                ]
            if rescue is None:
                rescued = may_stop(statement, straight_targets)
                if rescued is not None:
                    rescue = rescued
            for target in straight_targets:
                visit(target, path | {name})

    for name in start:
        if name in exact:
            visit(name, frozenset())
    return kept


def _go_targets(statement, neutralized_goto, single_target) -> set[str]:
    target = single_target(statement)
    if target is not None and target in neutralized_goto:
        return set()
    targets = list(statement.target_paragraphs or [])
    if not targets and statement.target_paragraph:
        targets = [statement.target_paragraph]
    return set(targets)
