"""Statement span detection on cobolparser's normalized free-form text.

cobolparser's SourceLocation gives only a statement's start line. A
statement's span end is derived as "one line before whatever comes next":
the next statement in the same paragraph, or the next paragraph's header
if this is the last statement in its paragraph, or end-of-file if it's the
very last paragraph's last statement.

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
    """Every paragraph-header and statement-start line, sorted ascending.

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
    for paragraph in _all_paragraphs(procedure):
        if paragraph.paragraph_name.strip(".") == "":
            continue
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


@dataclass
class ScopeMap:
    boundaries: list[ScopeBoundary]  # sorted by (line, column)


def collect_scope_map(program, lines: list[str]) -> ScopeMap:
    """Every span boundary relevant to nested statements: paragraph headers,
    statement starts at EVERY depth, and scope-word token locations from
    re-lexing `lines`. Tokens inside EXEC ... END-EXEC ranges are excluded:
    embedded SQL/CICS text may legally contain WHEN/ELSE/CASE words that are
    not COBOL block words.
    """
    boundaries: list[ScopeBoundary] = []
    exec_starts: list[int] = []
    procedure = program.get_division("PROCEDURE")
    if procedure is None:
        return ScopeMap([])

    for paragraph in _all_paragraphs(procedure):
        if paragraph.paragraph_name.strip(".") == "":
            continue  # phantom END-EXEC paragraphs, see collect_boundaries
        boundaries.append(
            ScopeBoundary(paragraph.location.line, paragraph.location.column, "")
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
    statements, boundaries: list[ScopeBoundary], exec_starts: list[int]
) -> None:
    for statement in statements:
        boundaries.append(
            ScopeBoundary(statement.location.line, statement.location.column, "")
        )
        if isinstance(statement, _EXEC_STATEMENT_TYPES):
            exec_starts.append(statement.location.line)
        for nested in _nested_statement_lists(statement):
            _collect_statement_starts(nested, boundaries, exec_starts)


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
    `unspliceable_reason` it has none. Idempotent; must run before the
    refusal gate and the splicer look at nested sites."""
    for site in surface.boundary_sites:
        if not site.nested or site.category is None:
            continue
        span, reason = _nested_site_span(site, scope_map, lines)
        site.span = span
        site.unspliceable_reason = reason


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
