"""Shared dataclasses and constants for the refusal package.

Split out of the former monolithic `refusal.py` (2026-08-26 audit) so
`_reachability.py`, `_plans.py`, and `_gates.py` can all depend on
`RefusalReason`/`ParagraphScopedRefusal`/`_UNANNOTATED` without importing
each other for it -- `_plans.py` constructs `RefusalReason`s of its own
(e.g. inside `find_terminator_plans`) and must not need to import from
`_gates.py` to do so.
"""

from __future__ import annotations

from dataclasses import dataclass

from mockymock.dsl.model import MockCategory

_UNMOCKED_CODES = {
    MockCategory.CALL: "UNMOCKED_CALL",
    MockCategory.DYNCALL: "UNMOCKED_CALL",
    MockCategory.SQL: "UNMOCKED_SQL",
    MockCategory.CICS: "UNMOCKED_CICS",
    MockCategory.DLI: "UNMOCKED_DLI",
    MockCategory.ACCEPT: "UNMOCKED_CONSOLE_ACCEPT",
}
# every file-op category shares one code
_UNMOCKED_FILE_OP_CODE = "UNMOCKED_FILE_OP"


@dataclass
class RefusalReason:
    code: str
    message: str


@dataclass
class ParagraphScopedRefusal:
    """A refusal whose evidence is provably confined to one PROCEDURE
    DIVISION paragraph's own body (see the module docstring): held back by
    the *_scoped check variants and resolved by resolve_scoped_refusals
    against union_executed_paragraphs -- `reason` refuses when some
    selected test case can execute `paragraph_name`; `waiver_note` is the
    transparency line printed instead when none can. `blank_span` is only
    set for an unresolved COPY statement: the 1-based inclusive
    normalized-line span, verified to own its lines outright, that
    cli.checks.run_static_checks comments out of the spliced source when
    the refusal is waived (the raw COPY text would otherwise still reach
    cobc, which cannot compile an unresolvable COPY).

    `neutralize_span` plays the same role for a waived CICS
    `DFHRESP(...)`/`DFHVALUE(...)` macro call -- (1-based line, 0-based
    start column, 0-based end column) of the call text, which
    run_static_checks overwrites in place with
    `CICS_MACRO_PLACEHOLDER`, space-padded to the identical width so no
    line or column any AST location indexes into ever moves. Same
    reasoning as `blank_span`: the unexpanded macro would otherwise still
    reach cobc, which has no CICS translator and cannot resolve it. At
    most one of the two spans is ever set."""

    paragraph_name: str
    reason: RefusalReason
    waiver_note: str
    blank_span: tuple[int, int] | None = None
    neutralize_span: tuple[int, int, int] | None = None


_UNANNOTATED = "nested-site spliceability was not annotated"
