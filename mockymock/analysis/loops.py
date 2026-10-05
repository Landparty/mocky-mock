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

from cobolparser.models.statements.control import PerformStatement

from mockymock.analysis.mock_surface import (
    BoundarySite,
    _all_paragraphs,
    _nested_statement_lists,
)
from mockymock.analysis.refusal._reachability import (
    _find_flow_statements,
    _reachable_paragraphs,
)


def _walk(statements: list):
    for statement in statements:
        yield statement
        for nested in _nested_statement_lists(statement):
            yield from _walk(nested)


def _is_loop(statement: PerformStatement) -> bool:
    return getattr(statement, "perform_type", "SIMPLE") != "SIMPLE"


def looped_paragraphs_and_statements(program) -> tuple[set[str], set[int]]:
    """(paragraph/section names reachable from a looping PERFORM's target,
    ids of statements nested inside a looping inline PERFORM's body)."""
    procedure = program.get_division("PROCEDURE") if program is not None else None
    if procedure is None:
        return set(), set()
    paragraphs: set[str] = set()
    statement_ids: set[int] = set()

    def add_reachable(target: str | None, thru: str | None) -> None:
        if target:
            reached, _ = _reachable_paragraphs(program, target, thru)
            paragraphs.update(reached)

    for paragraph in _all_paragraphs(procedure):
        for statement in _walk(paragraph.statements):
            if not isinstance(statement, PerformStatement) or not _is_loop(statement):
                continue
            add_reachable(statement.target_paragraph, statement.thru_paragraph)
            body = statement.inline_statements or []
            for nested in _walk(body):
                statement_ids.add(id(nested))
            for flow in _find_flow_statements(body):
                if isinstance(flow, PerformStatement):
                    add_reachable(flow.target_paragraph, flow.thru_paragraph)
    return paragraphs, statement_ids


def site_in_loop(site: BoundarySite, looped: tuple[set[str], set[int]]) -> bool:
    paragraphs, statement_ids = looped
    return site.paragraph_name in paragraphs or id(site.statement) in statement_ids
