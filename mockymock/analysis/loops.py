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

from cobolparser.models.statements.control import PerformStatement

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


def _is_loop(statement: PerformStatement) -> bool:
    return getattr(statement, "perform_type", "SIMPLE") != "SIMPLE"


@dataclass(frozen=True)
class LoopGuard:
    """One looping PERFORM: the paragraphs/sections its target reaches, the
    ids of the statements in its inline body, and the data names its UNTIL
    condition reads (uppercased; empty for `PERFORM n TIMES`)."""

    paragraphs: frozenset[str]
    statement_ids: frozenset[int]
    words: frozenset[str]


_WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]*")
_LITERAL_RE = re.compile(r"\"[^\"]*\"|'[^']*'")


def _condition_words(statement: PerformStatement) -> frozenset[str]:
    condition = getattr(statement, "until_condition", None)
    text = " ".join(str(op) for op in getattr(condition, "operands", None) or [])
    text = _LITERAL_RE.sub(" ", text)
    return frozenset(
        word.upper() for word in _WORD_RE.findall(text) if not word.isdigit()
    )


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
                )
            )
    return guards


def looped_paragraphs_and_statements(program) -> tuple[set[str], set[int]]:
    """(paragraph/section names reachable from a looping PERFORM's target,
    ids of statements nested inside a looping inline PERFORM's body)."""
    paragraphs: set[str] = set()
    statement_ids: set[int] = set()
    for guard in loop_guards(program):
        paragraphs |= guard.paragraphs
        statement_ids |= guard.statement_ids
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
