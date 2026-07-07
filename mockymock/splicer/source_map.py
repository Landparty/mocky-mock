"""Statement span detection on cobolparser's normalized free-form text.

cobolparser's SourceLocation gives only a statement's start line. A
statement's span end is derived as "one line before whatever comes next":
the next statement in the same paragraph, or the next paragraph's or
SECTION's header if this is the last statement in its paragraph, or
end-of-file if it's the very last paragraph's last statement. SECTION
header lines are boundaries in their own right -- without them the span
of a section's last statement would extend over (and comment out) the
following `X SECTION.` header.

Because a top-level splice comments out whole lines, `annotate_nested_sites`
also stamps top-level sites with an `unspliceable_reason` when the
statement does not own its line (sibling code before it -- including a
one-line paragraph header -- or another top-level statement/paragraph
header sharing the line). The refusal gate turns that into
UNSUPPORTED_MOCK_TARGET_LAYOUT / UNSPLICEABLE_EXEC before the splicer
could delete the sibling code.

For NESTED statements (inside IF/EVALUATE/inline-PERFORM bodies) the plain
boundary list is not enough: the AST has no location data for block words
(ELSE, WHEN, END-IF, ...), so "whatever comes next" could be a terminator
the span must NOT swallow. `collect_scope_map` recovers those locations by
re-lexing the normalized text with cobolparser's own CobolLexer (tokens
carry line/column), and `annotate_nested_sites` stamps every nested
BoundarySite with either a validated replacement span or the precise
reason none exists (fail closed). See
docs/2026-07-05-nested-mock-targets-design.md for the safety rules.
"""

from __future__ import annotations

from dataclasses import dataclass

from cobolparser.lexer import CobolLexer
from cobolparser.models.program import CobolDivision, CobolParagraph
from cobolparser.models.sql_statements import ExecSQLStatement
from cobolparser.parsers.statements.ibm_exec_statements import (
    ExecCicsStatement,
    ExecImsStatement,
)

from mockymock.analysis.mock_surface import (
    BoundarySite,
    MockSurface,
    _nested_statement_lists,
)
from mockymock.dsl.model import EXEC_CATEGORIES, MockCategory


def collect_boundaries(program) -> list[int]:
    """Every SECTION-header, paragraph-header, and statement-start line,
    sorted ascending.

    SECTION headers must be boundaries too: a paragraph's last statement
    followed by an `X SECTION.` header has no paragraph-header boundary
    between them, so without the section line the statement's span would
    swallow (and comment out) the header.

    cobolparser emits a phantom paragraph literally named "." for the
    sentence-terminating period line after an EXEC ... END-EXEC block
    (verified empirically: a program with two EXEC SQL paragraphs yields
    two extra paragraphs named "." anchored at the END-EXEC lines). Those
    are not real headers -- treating them as boundaries would cut an EXEC
    statement's span one line short of its END-EXEC, leaving a dangling
    END-EXEC in the spliced output -- so they are excluded.
    """
    procedure = program.get_division("PROCEDURE")
    if procedure is None:
        return []
    lines: set[int] = set()
    for section in procedure._sections.values():
        if (section.section_name or "").strip("."):
            lines.add(section.location.line)
    for paragraph in _all_paragraphs(procedure):
        # Phantom paragraphs ("." after END-EXEC, "" for a section's
        # pre-paragraph statements) contribute no header boundary, but any
        # statements they hold (section bodies) are real boundaries.
        if paragraph.paragraph_name.strip("."):
            lines.add(paragraph.location.line)
        for statement in paragraph.statements:
            lines.add(statement.location.line)
    return sorted(lines)


def statement_span(statement, boundaries: list[int], last_line: int) -> tuple[int, int]:
    """Return (start_line, end_line), both 1-indexed and inclusive."""
    start = statement.location.line
    later = [b for b in boundaries if b > start]
    end = (later[0] - 1) if later else last_line
    return start, end


def _all_paragraphs(procedure_division: CobolDivision) -> list[CobolParagraph]:
    paragraphs = list(procedure_division.paragraphs)
    for section in procedure_division._sections.values():
        paragraphs.extend(section.paragraphs)
    return paragraphs


# Scope words that end (or continue) a block and therefore bound a nested
# statement's span. A closed set rather than a startswith("END-") test so
# that user identifiers like END-OF-FILE never register as boundaries.
_SCOPE_WORDS = frozenset(
    {
        "ELSE",
        "WHEN",
        "OTHERWISE",
        "END-IF",
        "END-EVALUATE",
        "END-PERFORM",
        "END-CALL",
        "END-READ",
        "END-WRITE",
        "END-REWRITE",
        "END-DELETE",
        "END-START",
        "END-ACCEPT",
        "END-EXEC",
        "END-SEARCH",
        "END-STRING",
        "END-UNSTRING",
        "END-COMPUTE",
        "END-ADD",
        "END-SUBTRACT",
        "END-MULTIPLY",
        "END-DIVIDE",
        "END-DISPLAY",
        "END-RETURN",
    }
)

# The scope terminator that belongs to the mocked statement itself and is
# therefore part of its span, not a boundary after it (CALL ... END-CALL).
_VERB_TERMINATORS: dict[MockCategory, str] = {
    MockCategory.CALL: "END-CALL",
    MockCategory.DYNCALL: "END-CALL",
    MockCategory.READ: "END-READ",
    MockCategory.WRITE: "END-WRITE",
    MockCategory.REWRITE: "END-REWRITE",
    MockCategory.DELETE: "END-DELETE",
    MockCategory.START: "END-START",
    MockCategory.ACCEPT: "END-ACCEPT",
}

_EXEC_STATEMENT_TYPES = (ExecSQLStatement, ExecCicsStatement, ExecImsStatement)


@dataclass
class ScopeBoundary:
    line: int
    column: int
    word: str  # uppercase scope word, or "" for statement/paragraph starts
    # True for paragraph/SECTION headers and depth-0 statement starts --
    # the entries the top-level "owns its line" guard checks against.
    top_level: bool = False


@dataclass
class ScopeMap:
    boundaries: list[ScopeBoundary]  # sorted by (line, column)


def collect_scope_map(program, lines: list[str]) -> ScopeMap:
    """Every span boundary relevant to nested statements: SECTION and
    paragraph headers, statement starts at EVERY depth, and scope-word token
    locations from re-lexing `lines`. Tokens inside EXEC ... END-EXEC ranges
    are excluded: embedded SQL/CICS text may legally contain WHEN/ELSE/CASE
    words that are not COBOL block words.
    """
    boundaries: list[ScopeBoundary] = []
    exec_starts: list[int] = []
    procedure = program.get_division("PROCEDURE")
    if procedure is None:
        return ScopeMap([])

    for section in procedure._sections.values():
        if (section.section_name or "").strip("."):
            boundaries.append(
                ScopeBoundary(
                    section.location.line,
                    section.location.column,
                    "",
                    top_level=True,
                )
            )
    for paragraph in _all_paragraphs(procedure):
        # Phantom paragraphs ("." after END-EXEC, "" for a section's
        # pre-paragraph statements) have no real header, but any statements
        # they hold (section bodies) still count.
        if paragraph.paragraph_name.strip("."):
            boundaries.append(
                ScopeBoundary(
                    paragraph.location.line,
                    paragraph.location.column,
                    "",
                    top_level=True,
                )
            )
        _collect_statement_starts(paragraph.statements, boundaries, exec_starts)

    exec_ranges = [_exec_range(lines, start) for start in exec_starts]
    lexer = CobolLexer("\n".join(lines), free_form=True)
    for token in lexer.tokenize():
        word = str(token.value or "").upper()
        if word not in _SCOPE_WORDS:
            continue
        if _inside_exec_range(exec_ranges, token.location.line, token.location.column):
            continue
        boundaries.append(ScopeBoundary(token.location.line, token.location.column, word))

    boundaries.sort(key=lambda b: (b.line, b.column))
    return ScopeMap(boundaries)


def _collect_statement_starts(
    statements,
    boundaries: list[ScopeBoundary],
    exec_starts: list[int],
    top_level: bool = True,
) -> None:
    for statement in statements:
        boundaries.append(
            ScopeBoundary(
                statement.location.line,
                statement.location.column,
                "",
                top_level=top_level,
            )
        )
        if isinstance(statement, _EXEC_STATEMENT_TYPES):
            exec_starts.append(statement.location.line)
        for nested in _nested_statement_lists(statement):
            _collect_statement_starts(nested, boundaries, exec_starts, top_level=False)


def _exec_range(lines: list[str], start: int) -> tuple[int, int, int]:
    """(start_line, end_line, end_column-of-END-EXEC's-last-char). Tokens up
    to that column on the end line belong to the EXEC block; anything after
    it on the same line (e.g. a glued END-IF) is real COBOL again."""
    for line_no in range(start, len(lines) + 1):
        index = lines[line_no - 1].upper().find("END-EXEC")
        if index != -1:
            return start, line_no, index + len("END-EXEC")
    return start, start, len(lines[start - 1])


def _inside_exec_range(
    ranges: list[tuple[int, int, int]], line: int, column: int
) -> bool:
    for start, end, end_column in ranges:
        if start <= line < end:
            return True
        if line == end and column <= end_column:
            return True
    return False


def annotate_nested_sites(
    surface: MockSurface, scope_map: ScopeMap, lines: list[str]
) -> None:
    """Stamp every nested BoundarySite with a validated `span` or the
    `unspliceable_reason` it has none, and every TOP-LEVEL site with the
    `unspliceable_reason` its whole-line span cannot be applied safely
    (statement does not own its source line -- see
    `_top_level_site_problem`; `span` stays None for top-level sites, the
    splicer keeps deriving it from `statement_span`). Idempotent; must run
    before the refusal gate and the splicer look at any site."""
    for site in surface.boundary_sites:
        if site.category is None:
            continue
        if site.nested:
            span, reason = _nested_site_span(site, scope_map, lines)
            site.span = span
            site.unspliceable_reason = reason
        else:
            site.unspliceable_reason = _top_level_site_problem(
                site, scope_map, lines
            )


def _top_level_site_problem(
    site: BoundarySite, scope_map: ScopeMap, lines: list[str]
) -> str | None:
    """The reason a top-level site's whole-line splice would corrupt sibling
    code, or None when it owns its line.

    A top-level span runs from the statement's start line to one line
    before the next boundary, and `comment_and_replace` comments out whole
    lines -- so the only way sibling code can be swallowed is by sharing
    the START line (any later top-level statement/header line is itself a
    boundary that ends the span before it):

    - code before the statement on its line (`MOVE ... CALL "X" ...` or a
      one-line paragraph `P1. CALL "X".`) -- the sibling would be deleted;
    - another top-level statement or paragraph/SECTION header after it on
      the same line (`CALL "A" CALL "B".`) -- ditto, and two mocked
      statements on one line would corrupt each other's replacement.

    Nested statements inside the site's own clause bodies (e.g. a CALL's
    ON EXCEPTION handler) share its span legitimately and are not checked
    here -- they are part of the statement being replaced.
    """
    statement = site.statement
    start = statement.location.line
    column = statement.location.column
    if lines[start - 1][: column - 1].strip():
        return "does not start its own line"
    if any(
        b.top_level and b.line == start and b.column != column
        for b in scope_map.boundaries
    ):
        return (
            "shares its line with another statement or paragraph header"
        )
    return None


def _nested_site_span(
    site: BoundarySite, scope_map: ScopeMap, lines: list[str]
) -> tuple[tuple[int, int] | None, str | None]:
    statement = site.statement
    if site.nested_in_boundary:
        return None, (
            "nested inside another boundary statement's clause body -- "
            "splicing the enclosing statement removes this site"
        )
    if _nested_statement_lists(statement):
        return None, (
            "has conditional clause bodies of its own (AT END/INVALID KEY/"
            "ON EXCEPTION/...) whose extent cannot be determined"
        )

    start = statement.location.line
    column = statement.location.column
    if lines[start - 1][: column - 1].strip():
        return None, "does not start its own line"

    own_terminator = _VERB_TERMINATORS.get(site.category, "")
    relevant = [
        b
        for b in scope_map.boundaries
        if not (own_terminator and b.word == own_terminator)
    ]

    if any(
        b.line == start and not (b.column == column and b.word == "")
        for b in relevant
    ):
        return None, "shares its start line with another statement or scope word"

    following = [b for b in relevant if b.line > start]
    if not following:
        return None, "no following statement or scope word to bound the span"
    nxt = following[0]
    if lines[nxt.line - 1][: nxt.column - 1].strip():
        return None, (
            f"the next scope word or statement (line {nxt.line}) does not "
            f"start its own line"
        )

    end = nxt.line - 1
    if site.category in EXEC_CATEGORIES:
        if not any(
            "END-EXEC" in lines[line_no - 1].upper()
            for line_no in range(start, end + 1)
        ):
            return None, "its END-EXEC terminator falls outside the computed span"
    return (start, end), None
