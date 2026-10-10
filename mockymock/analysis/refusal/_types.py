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
    MockCategory.INITIATE: "UNMOCKED_REPORT_WRITER",
    MockCategory.GENERATE: "UNMOCKED_REPORT_WRITER",
    MockCategory.TERMINATE: "UNMOCKED_REPORT_WRITER",
}
# every file-op category shares one code
_UNMOCKED_FILE_OP_CODE = "UNMOCKED_FILE_OP"

# Detected-but-unmockable boundary sites (mock_surface `category=None`),
# keyed by the site's `label`: the refusal code check_test_case emits
# when one is reachable, and the explanation appended to its message.
# CANCEL / "dynamic CALL" / the terminator labels / "SORT/MERGE" have
# their own dedicated branches in check_test_case; everything here shares
# one generic "paragraph X (line N) contains <label> ..." shape. Every
# label mock_surface can emit with category=None must either be handled
# there or appear here -- `_UNSUPPORTED_STATEMENT_LABEL` is the catch-all
# for a statement class mock_surface does not know at all (fail closed:
# unknown semantics are never assumed side-effect-free).
_UNSUPPORTED_STATEMENT_LABEL = "unsupported statement"
_UNSUPPORTED_SITE_CODES: dict[str, tuple[str, str]] = {
    "INVOKE": (
        "UNSUPPORTED_INVOKE",
        "an INVOKE method call on an object reference is an external "
        "dependency mockymock has no mock category for (object-oriented "
        "COBOL -- CLASS-ID / OBJECT REFERENCE / INVOKE -- is outside the "
        "GnuCOBOL toolchain mockymock compiles with); isolate the paragraph "
        "with MOCK PARAGRAPH, or PERFORM a caller whose flow never reaches it",
    ),
    "CHAIN": (
        "UNSUPPORTED_CHAIN",
        "CHAIN transfers control to another program without returning (a "
        "Micro Focus extension) -- an external program dependency mockymock "
        "cannot mock the way it mocks CALL, since nothing after it in the "
        "test case would run; isolate the paragraph with MOCK PARAGRAPH, or "
        "PERFORM a caller whose flow never reaches it",
    ),
    "communication": (
        "UNSUPPORTED_COMMUNICATION",
        "SEND/RECEIVE/ENABLE/DISABLE/PURGE go through the COBOL-85 "
        "Communication Module's message control system (a CD in the "
        "COMMUNICATION SECTION) -- an external message queue mockymock has "
        "no mock category for; isolate the paragraph with MOCK PARAGRAPH, or "
        "PERFORM a caller whose flow never reaches it",
    ),
    "STOP literal": (
        "UNSUPPORTED_STOP_LITERAL",
        "STOP <literal> displays the literal and then waits for the operator "
        "on the console before continuing -- a console read like an "
        "unmocked ACCEPT, so under a test runner it reads whatever stdin is "
        "attached (or blocks until the executor timeout); replace it with "
        "DISPLAY, or isolate the paragraph with MOCK PARAGRAPH",
    ),
    _UNSUPPORTED_STATEMENT_LABEL: (
        "UNSUPPORTED_STATEMENT",
        "mockymock does not model this statement: it is neither one of the "
        "pass-through statements known to touch nothing outside the program "
        "nor a mockable boundary, so its effects cannot be verified or "
        "mocked (fail closed rather than assume it is side-effect free); "
        "isolate the paragraph with MOCK PARAGRAPH, or PERFORM a caller "
        "whose flow never reaches it",
    ),
}


@dataclass
class RefusalReason:
    code: str
    message: str
    # Literal .cut text that would resolve this reason -- only ever set
    # for UNMOCKED_* codes (a boundary is reachable but no MOCK directive
    # in the test case matches it), where the fix is entirely mechanical:
    # `dsl.generator.directive_snippet` renders it, the same renderer
    # `generate`'s own scaffold uses, so the two can never disagree.
    # None for every other reason -- an UNSUPPORTED_* refusal, a
    # structural gate like DECLARATIVES/ALTER, AMBIGUOUS_MOCK, or any
    # site directive_snippet itself declines to render (an unparsed CALL
    # literal, an unrepresentable quote in a key/prefix) -- has no
    # mechanical fix. See
    # docs/2026-09-15-actionable-refusals-and-fill-design.md.
    suggested_fix: str | None = None


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
