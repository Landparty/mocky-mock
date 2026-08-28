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

from bisect import bisect_right
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import cast

from cobolparser.lexer import CobolLexer
from cobolparser.models.ast_base import ASTNode
from cobolparser.models.program import CobolDivision, CobolParagraph
from cobolparser.models.sql_statements import ExecSQLStatement
from cobolparser.parsers.statements.ibm_exec_statements import (
    ExecCicsStatement,
    ExecImsStatement,
)

from mockymock.analysis.mock_surface import (
    _TERMINATOR_LABELS,
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


def statement_span(
    statement, boundaries: list[int], last_line: int, lines: list[str]
) -> tuple[int, int]:
    """Return (start_line, end_line), both 1-indexed and inclusive.

    cobolparser's normalize_fixed_format blanks out (rather than deletes)
    comment/blank/directive lines so later line numbers stay accurate --
    which means "one line before the next boundary" can land on one of
    those blank placeholders instead of the statement's true last content
    line. Trimmed back to the last non-blank line so the span's actual
    text always ends on real code.
    """
    start = statement.location.line
    later = [b for b in boundaries if b > start]
    end = (later[0] - 1) if later else last_line
    return start, _trim_trailing_blank_lines(start, end, lines)


def _trim_trailing_blank_lines(start: int, end: int, lines: list[str]) -> int:
    """Walk `end` back to the last non-blank line, never past `start`."""
    while end > start and not lines[end - 1].strip():
        end -= 1
    return end


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

    # Lazily-built line index over `boundaries`. Every query below used to
    # be a full linear scan (often materializing a filtered copy of the
    # whole list first), and `annotate_nested_sites` runs one query per
    # boundary site -- O(sites x boundaries), which is quadratic in program
    # size and was measured as the single dominant cost of the whole static
    # check pass on a large CICS program (13.3M generator steps on a
    # 29k-line file). `boundaries` is built once by `collect_scope_map` and
    # never mutated afterwards, so caching the index is safe; anything that
    # starts mutating it must call `invalidate()`.
    _by_line: dict[int, list[ScopeBoundary]] | None = field(
        default=None, init=False, repr=False, compare=False
    )
    _index_lines: list[int] | None = field(
        default=None, init=False, repr=False, compare=False
    )

    def invalidate(self) -> None:
        """Drop the cached line index -- required after any mutation of
        `boundaries`."""
        self._by_line = None
        self._index_lines = None

    def _index(self) -> tuple[dict[int, list[ScopeBoundary]], list[int]]:
        by_line = self._by_line
        index_lines = self._index_lines
        if by_line is None or index_lines is None:
            by_line = {}
            for boundary in self.boundaries:
                by_line.setdefault(boundary.line, []).append(boundary)
            index_lines = sorted(by_line)
            self._by_line = by_line
            self._index_lines = index_lines
        return by_line, index_lines

    def at_line(self, line: int) -> list[ScopeBoundary]:
        """Every boundary on `line`, in the same (line, column) order
        `boundaries` holds them in."""
        by_line, _ = self._index()
        return by_line.get(line, [])

    def iter_after_line(self, line: int) -> Iterator[ScopeBoundary]:
        """Every boundary on a line strictly greater than `line`, in
        (line, column) order -- the same sequence
        `[b for b in boundaries if b.line > line]` yields, without
        materializing it."""
        by_line, index_lines = self._index()
        for idx in range(bisect_right(index_lines, line), len(index_lines)):
            yield from by_line[index_lines[idx]]


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

    exec_index = _exec_line_index([_exec_range(lines, start) for start in exec_starts])
    lexer = CobolLexer("\n".join(lines), free_form=True)
    for token in lexer.tokenize():
        word = str(token.value or "").upper()
        if word not in _SCOPE_WORDS:
            continue
        if _inside_exec_range(exec_index, token.location.line, token.location.column):
            continue
        boundaries.append(
            ScopeBoundary(token.location.line, token.location.column, word)
        )

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


def _exec_line_index(
    ranges: list[tuple[int, int, int]],
) -> tuple[set[int], dict[int, int]]:
    """`_inside_exec_range`'s ranges, flattened into (fully-covered lines,
    end-line -> furthest END-EXEC end column).

    Scanning the range list per token is O(tokens x EXEC blocks), which on
    a CICS program -- where both grow with file size -- is quadratic; the
    flattened form answers each query in constant time and costs only one
    set entry per line actually inside an EXEC block. A line that is both
    interior to one range and the end line of another stays covered by the
    set, and `max` keeps the most permissive end column when several
    ranges end on the same line, so both are exactly what the linear scan
    returned."""
    inside: set[int] = set()
    end_columns: dict[int, int] = {}
    for start, end, end_column in ranges:
        inside.update(range(start, end))
        previous = end_columns.get(end)
        if previous is None or end_column > previous:
            end_columns[end] = end_column
    return inside, end_columns


def _inside_exec_range(
    index: tuple[set[int], dict[int, int]], line: int, column: int
) -> bool:
    inside, end_columns = index
    if line in inside:
        return True
    end_column = end_columns.get(line)
    return end_column is not None and column <= end_column


def annotate_nested_sites(
    surface: MockSurface, scope_map: ScopeMap, lines: list[str]
) -> None:
    """Stamp every nested BoundarySite with a validated `span` or the
    `unspliceable_reason` it has none, and every TOP-LEVEL site with the
    `unspliceable_reason` its whole-line span cannot be applied safely
    (statement does not own its source line -- see
    `_top_level_site_problem`; `span` stays None for top-level sites, the
    splicer keeps deriving it from `statement_span`). Idempotent; must run
    before the refusal gate and the splicer look at any site. Also
    validates STOP RUN/GOBACK terminator sites (category None, but not
    skipped like other detected-but-unmockable categories) through the
    identical rules -- see
    docs/2026-07-08-goback-stop-run-support-design.md."""
    for site in surface.boundary_sites:
        if site.category is None and site.label not in _TERMINATOR_LABELS:
            continue
        if site.nested:
            span, reason = _nested_site_span(site, scope_map, lines)
            site.span = span
            site.unspliceable_reason = reason
        else:
            site.unspliceable_reason = _top_level_site_problem(site, scope_map, lines)


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
    return statement_top_level_problem(cast(ASTNode, site.statement), scope_map, lines)


def statement_top_level_problem(
    statement, scope_map: ScopeMap, lines: list[str]
) -> str | None:
    """The reason a top-level STATEMENT's whole-line splice/insertion
    would corrupt sibling code, or None when it owns its line -- the same
    check `_top_level_site_problem` applies to BoundarySites, factored out
    so it can also be applied directly to a PerformStatement (which is
    never wrapped in a BoundarySite; used by
    refusal.find_terminator_plans to validate each intermediate PERFORM
    on a safe chain before it's cleared for the
    stub_writer.insert_lines_after early-exit-check instrumentation). See
    _top_level_site_problem's docstring for the exact rules; this is that
    function's body, unchanged, operating on `statement` directly instead
    of `site.statement`."""
    start = statement.location.line
    column = statement.location.column
    if lines[start - 1][: column - 1].strip():
        return "does not start its own line"
    if any(b.top_level and b.column != column for b in scope_map.at_line(start)):
        return "shares its line with another statement or paragraph header"
    return None


def nested_statement_span(
    statement, scope_map: ScopeMap, lines: list[str]
) -> tuple[tuple[int, int] | None, str | None]:
    """The validated replacement span for a NESTED statement that has no
    clause bodies or scope terminator of its own (e.g. a GO TO nested
    inside an IF/EVALUATE branch) -- the same "stop before the next
    scope-map boundary" rule `_nested_site_span` applies to BoundarySites,
    factored out to operate on a raw statement with no MockCategory/own-
    terminator concept (there is no `_VERB_TERMINATORS` entry to exclude,
    and no END-EXEC-style tail check). Callers must not use this for a
    statement that owns clause bodies of its own -- check
    `_nested_statement_lists(statement)` is empty first.

    Exists because `statement_span`'s boundary list
    (`collect_boundaries`) tracks only top-level statement/paragraph/
    SECTION-header lines -- it has no location data for block words like
    END-IF, so calling it on a nested statement can silently extend the
    computed span PAST the statement's own line and swallow the scope
    terminator that closes the block it's nested in. Verified concretely
    while building GO-TO-to-EXIT-PARAGRAPH splicing (docs/2026-08-17-
    goto-exit-paragraph-simplification-design.md): a `GO TO` nested
    inside an `IF`, replaced via `statement_span`, commented out its own
    `END-IF` too, turning `EXIT PARAGRAPH` into an unconditional
    statement instead of one gated by the `IF`."""
    start = statement.location.line
    column = statement.location.column
    if lines[start - 1][: column - 1].strip():
        return None, "does not start its own line"

    if any(not (b.column == column and b.word == "") for b in scope_map.at_line(start)):
        return None, "shares its start line with another statement or scope word"

    nxt = next(scope_map.iter_after_line(start), None)
    if nxt is None:
        return None, "no following statement or scope word to bound the span"
    if lines[nxt.line - 1][: nxt.column - 1].strip():
        return None, (
            f"the next scope word or statement (line {nxt.line}) does not "
            f"start its own line"
        )
    end = _trim_trailing_blank_lines(start, nxt.line - 1, lines)
    return (start, end), None


def _nested_site_span(
    site: BoundarySite, scope_map: ScopeMap, lines: list[str]
) -> tuple[tuple[int, int] | None, str | None]:
    statement = cast(ASTNode, site.statement)
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

    own_terminator = (
        _VERB_TERMINATORS.get(site.category, "") if site.category is not None else ""
    )

    def relevant(boundary: ScopeBoundary) -> bool:
        return not (own_terminator and boundary.word == own_terminator)

    if any(
        relevant(b) and not (b.column == column and b.word == "")
        for b in scope_map.at_line(start)
    ):
        return None, "shares its start line with another statement or scope word"

    nxt = next(
        (b for b in scope_map.iter_after_line(start) if relevant(b)),
        None,
    )
    if nxt is None:
        return None, "no following statement or scope word to bound the span"
    if lines[nxt.line - 1][: nxt.column - 1].strip():
        return None, (
            f"the next scope word or statement (line {nxt.line}) does not "
            f"start its own line"
        )

    end = _trim_trailing_blank_lines(start, nxt.line - 1, lines)
    if site.category in EXEC_CATEGORIES:
        if not any(
            "END-EXEC" in lines[line_no - 1].upper()
            for line_no in range(start, end + 1)
        ):
            return None, "its END-EXEC terminator falls outside the computed span"
    return (start, end), None
