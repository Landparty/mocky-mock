"""Which boundary sites can run more than once per PERFORM of the program:
the ones inside a looping PERFORM (UNTIL / VARYING / TIMES), either in its
inline body or anywhere reachable from its out-of-line target.

Used by `generate --with-data` (issue #141): a cursor FETCH inside such a
loop must be mocked with `ROWS` so the call after the last row reports
SQLCODE 100 -- a single-row body reports success forever and the loop
never ends -- and its exact call count is then the row count plus that
final, exhausting call.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from cobolparser.models.statements.control import (
    EvaluateStatement,
    GoStatement,
    IfStatement,
    PerformStatement,
)
from cobolparser.models.statements.data import MoveStatement, SetStatement

from mockymock.analysis.mock_surface import (
    BoundarySite,
    _all_paragraphs,
    _nested_statement_lists,
)


def _walk(statements: list):
    for statement in statements:
        yield statement
        for nested in _nested_statement_lists(statement):
            yield from _walk(nested)


#: Every statement of a list, nested bodies included, in order.
walk_statements = _walk


def _is_loop(statement: PerformStatement) -> bool:
    return getattr(statement, "perform_type", "SIMPLE") != "SIMPLE"


@dataclass(frozen=True)
class LoopGuard:
    """One looping PERFORM: the paragraphs/sections its target reaches, the
    ids of the statements in its inline body, and the data names its UNTIL
    condition reads (uppercased; empty for `PERFORM n TIMES`). `varying`
    names the loop's own VARYING / AFTER control items, which the program
    advances itself (issue #286)."""

    paragraphs: frozenset[str]
    statement_ids: frozenset[int]
    words: frozenset[str]
    varying: frozenset[str] = frozenset()
    until_text: str = ""


_WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]*")
_LITERAL_RE = re.compile(r"\"[^\"]*\"|'[^']*'")


def _until_text(statement: PerformStatement) -> str:
    condition = getattr(statement, "until_condition", None)
    return " ".join(str(op) for op in getattr(condition, "operands", None) or [])


def _condition_words(statement: PerformStatement) -> frozenset[str]:
    condition = getattr(statement, "until_condition", None)
    text = " ".join(str(op) for op in getattr(condition, "operands", None) or [])
    text = _LITERAL_RE.sub(" ", text)
    return frozenset(
        word.upper() for word in _WORD_RE.findall(text) if not word.isdigit()
    )


def _varying_words(statement: PerformStatement) -> frozenset[str]:
    """The VARYING / AFTER control items of `statement`, plus the words of
    each AFTER clause's own UNTIL (uppercased)."""
    words: set[str] = set()
    clauses = [getattr(statement, "varying_clause", None)]
    clauses += list(getattr(statement, "after_clauses", None) or [])
    for clause in clauses:
        if not isinstance(clause, dict):
            continue
        variable = clause.get("variable")
        if isinstance(variable, str) and variable:
            words.add(variable.upper())
        condition = clause.get("until_condition")
        text = " ".join(str(op) for op in getattr(condition, "operands", None) or [])
        text = _LITERAL_RE.sub(" ", text)
        words |= {word.upper() for word in _WORD_RE.findall(text) if not word.isdigit()}
    return frozenset(words)


def loop_guards(program) -> list[LoopGuard]:
    """Every looping PERFORM in the program, as a `LoopGuard`."""
    # Imported here: refusal imports the generator, which imports this.
    from mockymock.analysis.refusal._reachability import (
        _find_flow_statements,
        _reachable_paragraphs,
    )

    procedure = program.get_division("PROCEDURE") if program is not None else None
    if procedure is None:
        return []
    guards: list[LoopGuard] = []

    def reachable(target: str | None, thru: str | None) -> set[str]:
        if not target:
            return set()
        reached, _ = _reachable_paragraphs(program, target, thru)
        return set(reached)

    for paragraph in _all_paragraphs(procedure):
        for statement in _walk(paragraph.statements):
            if not isinstance(statement, PerformStatement) or not _is_loop(statement):
                continue
            paragraphs = reachable(statement.target_paragraph, statement.thru_paragraph)
            body = statement.inline_statements or []
            statement_ids = {id(nested) for nested in _walk(body)}
            for flow in _find_flow_statements(body):
                if isinstance(flow, PerformStatement):
                    paragraphs |= reachable(flow.target_paragraph, flow.thru_paragraph)
            guards.append(
                LoopGuard(
                    frozenset(paragraphs),
                    frozenset(statement_ids),
                    _condition_words(statement),
                    _varying_words(statement),
                    _until_text(statement),
                )
            )
    return guards


def goto_loop_paragraphs(program) -> set[str]:
    """Paragraphs inside a GO TO loop: a GO TO back to its own paragraph or
    an earlier one makes every paragraph from that target to the GO TO's own
    a loop body (source order), the `GO TO FETCH-LOOP` style written without
    PERFORM UNTIL (#450)."""
    procedure = program.get_division("PROCEDURE") if program is not None else None
    if procedure is None:
        return set()
    ordered = sorted(
        _all_paragraphs(procedure),
        key=lambda p: getattr(getattr(p, "location", None), "line", 0) or 0,
    )
    names = [str(getattr(p, "paragraph_name", "") or "").upper() for p in ordered]
    position = {name: i for i, name in enumerate(names) if name}
    looped: set[str] = set()
    for end, paragraph in enumerate(ordered):
        for statement in _walk(list(paragraph.statements)):
            if not isinstance(statement, GoStatement):
                continue
            for target in statement.target_paragraphs:
                start = position.get(str(target or "").upper())
                if start is not None and start <= end:
                    looped.update(n for n in names[start : end + 1] if n)
    return looped


def looped_paragraphs_and_statements(program) -> tuple[set[str], set[int]]:
    """(paragraph/section names reachable from a looping PERFORM's target or
    inside a GO TO loop, ids of statements nested inside a looping inline
    PERFORM's body)."""
    paragraphs: set[str] = set()
    statement_ids: set[int] = set()
    for guard in loop_guards(program):
        paragraphs |= guard.paragraphs
        statement_ids |= guard.statement_ids
    paragraphs |= goto_loop_paragraphs(program)
    return paragraphs, statement_ids


def site_in_loop(site: BoundarySite, looped: tuple[set[str], set[int]]) -> bool:
    paragraphs, statement_ids = looped
    return site.paragraph_name in paragraphs or id(site.statement) in statement_ids


def loop_guard_words(site: BoundarySite, guards: list[LoopGuard]) -> set[str]:
    """The data names read by the UNTIL conditions of every loop `site`
    runs inside (issue #156)."""
    words: set[str] = set()
    for guard in guards:
        if site.paragraph_name in guard.paragraphs or id(site.statement) in (
            guard.statement_ids
        ):
            words |= guard.words
    return words


_EXPRESSION_ATTRS = (
    "left_operand",
    "right_operand",
    "left_condition",
    "right_condition",
    "operands",
    "condition_tree",
)


def loop_exit_literal(
    site: BoundarySite, guards: list[LoopGuard], name: str
) -> str | None:
    """The literal an enclosing loop's UNTIL compares `name` equal to
    (`UNTIL WS-IN = "END"` -> `"END"`, quoted as in the source), or None.
    Used to end a SYSIN control-card loop around `ACCEPT WS-IN` (issue
    #263)."""
    pattern = re.compile(
        rf"(?<![\w-]){re.escape(name)}\s*(?:=|(?:IS\s+)?EQUALS?(?:\s+TO)?)\s*"
        r"(\"[^\"]*\"|'[^']*')",
        re.IGNORECASE,
    )
    for guard in guards:
        if site.paragraph_name in guard.paragraphs or id(site.statement) in (
            guard.statement_ids
        ):
            match = pattern.search(guard.until_text)
            if match:
                return match.group(1)
    return None


def loop_control_words(site: BoundarySite, guards: list[LoopGuard]) -> set[str]:
    """Every data name a loop `site` runs inside is controlled by: its
    VARYING / AFTER items and the words of its UNTIL conditions. A mock
    that writes one of them resets the program's own loop (issue #286)."""
    words: set[str] = set()
    for guard in guards:
        if site.paragraph_name in guard.paragraphs or id(site.statement) in (
            guard.statement_ids
        ):
            words |= guard.words | guard.varying
    return words


def _expression_words(node) -> set[str]:
    """Data names an IF condition / EVALUATE subject or WHEN selector reads
    (uppercased, literals and numbers dropped)."""
    if node is None:
        return set()
    if isinstance(node, str):
        text = _LITERAL_RE.sub(" ", node)
        return {w.upper() for w in _WORD_RE.findall(text) if not w.isdigit()}
    if isinstance(node, dict):
        return _expression_words(node.get("text") or node.get("value"))
    if isinstance(node, (list, tuple)):
        return set().union(*(_expression_words(item) for item in node))
    words: set[str] = set()
    for attr in _EXPRESSION_ATTRS:
        words |= _expression_words(getattr(node, attr, None))
    metadata = getattr(node, "_metadata", None) or {}
    words |= _expression_words(metadata.get("raw_condition"))
    return words


def _branch_condition_words(statement) -> set[str]:
    if isinstance(statement, IfStatement):
        return _expression_words(getattr(statement, "condition", None))
    if isinstance(statement, EvaluateStatement):
        words = _expression_words(list(getattr(statement, "subjects", None) or []))
        for when in getattr(statement, "when_clauses", None) or []:
            words |= _expression_words(list(getattr(when, "selectors", None) or []))
        return words
    return set()


def _equal_comparisons(node) -> list[tuple[str, str]]:
    """(data name, literal) for each `name = literal` an IF condition
    holds, through AND/OR but not under NOT (uppercased, quotes kept)."""
    if node is None or isinstance(node, (str, dict, list, tuple)):
        return []
    if str(getattr(node, "expression_type", "") or "").upper() == "NOT":
        return []
    found: list[tuple[str, str]] = []
    operator = str(getattr(node, "operator", "") or "").upper()
    left = getattr(node, "left_operand", None)
    right = getattr(node, "right_operand", None)
    if operator in {"EQUAL", "=", "EQUALS"} and isinstance(left, str):
        if isinstance(right, str):
            found.append((left.strip().upper(), right.strip().upper()))
    for attr in ("left_condition", "right_condition"):
        found += _equal_comparisons(getattr(node, attr, None))
    return found


def flag_branch_comparisons(
    statements: list, reply_names: set[str], flags: set[str]
) -> list[tuple[str, str]]:
    """The `name = literal` tests of the IFs on `reply_names` that write
    one of `flags` (`IF PCB-STATUS = 'GE'  MOVE 'Y' TO WS-EOF` under
    `PERFORM UNTIL AT-END-OF-DB`): what the reply must be for the loop to
    end."""
    found: list[tuple[str, str]] = []
    for statement in _walk(statements):
        if not isinstance(statement, IfStatement):
            continue
        if not _branch_condition_words(statement) & reply_names:
            continue
        if names_set_on_reply([statement], reply_names) & flags:
            found += _equal_comparisons(getattr(statement, "condition", None))
    return found


def names_set_on_reply(statements: list, reply_names: set[str]) -> set[str]:
    """Data names a SET ... TO TRUE or MOVE writes inside an IF/EVALUATE
    whose condition reads one of `reply_names` (uppercased base names).

    The flag a loop's UNTIL reads is often set one PERFORM away from it,
    in a branch on the CALL's reply (`WHEN MQ-REASON-CODE = MQRC-NO-MSG-
    AVAIL  SET NO-MORE-MSGS TO TRUE`): that flag follows the reply as
    surely as the reply itself (issue #188, a variant of #156)."""
    written: set[str] = set()
    for statement in _walk(statements):
        if not _branch_condition_words(statement) & reply_names:
            continue
        for nested_list in _nested_statement_lists(statement):
            for nested in _walk(nested_list):
                if isinstance(nested, SetStatement) and (
                    str(getattr(nested, "set_type", "") or "").upper() == "TRUE"
                ):
                    targets = getattr(nested, "targets", None) or []
                elif isinstance(nested, MoveStatement):
                    targets = getattr(nested, "targets", None) or []
                else:
                    continue
                for target in targets:
                    match = _WORD_RE.match(str(target).strip())
                    if match:
                        written.add(match.group(0).upper())
    return written
