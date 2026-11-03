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

import re
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

from mockymock.analysis.clause_bodies import (
    _NESTABLE_BOUNDARY_TYPES,
    _spec,
    clause_header_positions,
)
from mockymock.analysis.mock_surface import (
    _TERMINATOR_LABELS,
    BoundarySite,
    MockSurface,
    _nested_statement_lists,
)
from mockymock.dsl.model import EXEC_CATEGORIES, MockCategory

# Category-None sites the splicer still replaces: the terminators, and a
# STOP <literal>, which becomes CONTINUE (the operator answers at once).
_SPLICED_UNMOCKED_LABELS = _TERMINATOR_LABELS | {"STOP literal"}


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


# A compiler-directing line (`>>IF`/`>>ELSE`/`>>END-IF`/`>>DEFINE`/...,
# `REPLACE ... .`, `REPLACE OFF.`) is kept by normalize_fixed_format but is
# never an AST statement, so it is not in any boundary list. Without this
# test a directive directly after a mocked statement fell inside its span and
# was commented out with it: a lost `REPLACE OFF.` left the REPLACE active
# over the rest of the program, a lost `>>END-IF` failed cobc (#310).
#: `END DECLARATIVES.` is no AST node either, and ends the last USE
#: procedure's last statement the same way (2026-11-03, NIST SQ212A: a
#: STOP RUN's splice commented it out and cobc read the rest of the
#: program as declaratives).
_DIRECTIVE_LINE = re.compile(
    r"\s*(>>|REPLACE\b|END\s+DECLARATIVES\b"
    # The end of the program's own PROCEDURE DIVISION in a multi-program
    # source (2026-11-03, NIST IC2xx): its END PROGRAM, or the header of a
    # program nested in it or stacked after it.
    r"|END\s+PROGRAM\b|(IDENTIFICATION|ID)\s+DIVISION\b)",
    re.IGNORECASE,
)


def _trim_trailing_blank_lines(start: int, end: int, lines: list[str]) -> int:
    """Cut `end` before the first compiler-directing line after `start`,
    then walk it back to the last non-blank line, never past `start`."""
    for line_no in range(start + 1, end + 1):
        if _DIRECTIVE_LINE.match(lines[line_no - 1]):
            end = line_no - 1
            break
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
        # XML/JSON GENERATE/PARSE and RECEIVE carry statement bodies (ON
        # EXCEPTION / NO DATA / WITH DATA) since cobol-parser 2026-09-02,
        # so a boundary nested inside one is bounded by its terminator.
        "END-XML",
        "END-JSON",
        "END-RECEIVE",
    }
)

# The scope terminator that belongs to the mocked statement itself and is
# therefore part of its span, not a boundary after it (CALL ... END-CALL).
_VERB_TERMINATORS: dict[MockCategory, str] = {
    MockCategory.CALL: "END-CALL",
    MockCategory.DYNCALL: "END-CALL",
    MockCategory.READ: "END-READ",
    # RETURN ... AT END ... END-RETURN, the SORT OUTPUT PROCEDURE loop
    # (issue #340); `clause_bodies._LIFTABLE` already lifts its clauses.
    MockCategory.RETURN: "END-RETURN",
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
    # A boundary statement's clause header (`AT END`, `NOT INVALID KEY`,
    # `ON EXCEPTION`, ...; `word` holds its name): the AST locates none, but
    # a statement nested in a clause body must stop before the next one.
    clause_header: bool = False
    # A paragraph or SECTION header (top_level too).
    header: bool = False


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
    words that are not COBOL block words. Clause headers of every READ /
    WRITE / CALL / ... with clause bodies are boundaries too
    (`ScopeBoundary.clause_header`).
    """
    boundaries: list[ScopeBoundary] = []
    exec_starts: list[int] = []
    with_clauses: list = []
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
                    header=True,
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
                    header=True,
                )
            )
        _collect_statement_starts(
            paragraph.statements, boundaries, exec_starts, with_clauses
        )
    for statement in with_clauses:
        for line, column, name in clause_header_positions(statement, lines):
            boundaries.append(ScopeBoundary(line, column, name, clause_header=True))

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
    with_clauses: list,
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
        nested_lists = _nested_statement_lists(statement)
        if nested_lists and _spec(statement) is not None:
            with_clauses.append(statement)
        for nested in nested_lists:
            _collect_statement_starts(
                nested, boundaries, exec_starts, with_clauses, top_level=False
            )


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
    docs/2026-07-08-goback-stop-run-support-design.md. `EXEC SQL WHENEVER`
    sites (`surface.whenever_sites`) are spliced too, so they get the same
    validation.

    A site nested in another boundary's clause body (`READ ... NOT AT END
    CALL "X"`) gets a span too when that is safe (`_in_boundary_problem`):
    the splicer splices it in place when nothing replaces the enclosing
    statement, or inside the enclosing statement's lifted clause body when
    a mock does (`orchestrator.splice_program`)."""
    parents = boundary_parents(surface)
    for site in [*surface.boundary_sites, *surface.whenever_sites]:
        if site.category is None and site.label not in _SPLICED_UNMOCKED_LABELS:
            continue
        if site.nested:
            span, reason, lead = _nested_site_span(site, scope_map, lines, parents)
            site.span = span
            site.unspliceable_reason = reason
            site.span_lead = lead
        else:
            site.unspliceable_reason = _top_level_site_problem(site, scope_map, lines)
            site.span_lead = (
                closed_sentence_lead(cast(ASTNode, site.statement), lines)
                if site.unspliceable_reason is None
                else None
            )


def boundary_parents(surface: MockSurface) -> dict[int, BoundarySite]:
    """`id(statement)` of every boundary site nested in another boundary's
    clause body -> the nearest enclosing boundary site."""
    sites = {id(site.statement): site for site in surface.boundary_sites}
    parents: dict[int, BoundarySite] = {}
    for site in sites.values():
        stack = list(_nested_statement_lists(site.statement))
        while stack:
            for child in stack.pop():
                if id(child) in sites:
                    # Its own walk covers what is nested in it.
                    parents[id(child)] = site
                    continue
                stack.extend(_nested_statement_lists(child))
    return parents


def _in_boundary_problem(
    site: BoundarySite, parents: dict[int, BoundarySite]
) -> str | None:
    """Why a site nested in another boundary's clause body cannot get a
    span of its own, or None when it can: a mockable, non-EXEC site whose
    every enclosing boundary is a READ / RETURN / WRITE / REWRITE / DELETE
    / START / CALL, the statements whose clause bodies the splice lifts
    and re-runs (`analysis.clause_bodies`) -- so the site survives a mock
    of the enclosing statement inside the lifted copy."""
    removed = (
        "nested inside another boundary statement's clause body -- "
        "splicing the enclosing statement removes this site"
    )
    if site.category is None or site.category in EXEC_CATEGORIES:
        return removed
    if not isinstance(site.statement, _NESTABLE_BOUNDARY_TYPES):
        return removed
    parent = parents.get(id(site.statement))
    seen: set[int] = set()
    while parent is not None and id(parent.statement) not in seen:
        seen.add(id(parent.statement))
        if _spec(parent.statement) is None:
            return (
                f"nested inside the clause body of the {parent.label} at line "
                f"{parent.line}, whose clause bodies are not re-run after a "
                f"mock -- splicing that statement removes this site"
            )
        parent = parents.get(id(parent.statement))
    return None


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
      one-line paragraph `P1. CALL "X".`) -- the sibling would be deleted.
      Statements before it that close their sentence (`PERFORM A. CLOSE
      F.`) are the exception: the splice emits them back on a line of
      their own (`closed_sentence_lead`, `BoundarySite.span_lead`);
    - another top-level statement or paragraph/SECTION header after it on
      the same line (`CALL "A" CALL "B".`) -- ditto, and two mocked
      statements on one line would corrupt each other's replacement.

    Nested statements inside the site's own clause bodies (e.g. a CALL's
    ON EXCEPTION handler) share its span legitimately and are not checked
    here -- they are part of the statement being replaced.
    """
    return statement_top_level_problem(
        cast(ASTNode, site.statement), scope_map, lines, allow_lead=True
    )


def statement_top_level_problem(
    statement, scope_map: ScopeMap, lines: list[str], allow_lead: bool = False
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
    lead = closed_sentence_lead(statement, lines) if allow_lead else None
    if lead is None and lines[start - 1][: column - 1].strip():
        return "does not start its own line"
    if lead is not None and any(
        b.header and b.column < column for b in scope_map.at_line(start)
    ):
        # A one-line paragraph `P1. CALL "X".`: a MOCK PARAGRAPH splices
        # that same header line, so the lead is not split off.
        return "does not start its own line"
    if any(
        b.top_level and b.column != column and (lead is None or b.column > column)
        for b in scope_map.at_line(start)
    ):
        return "shares its line with another statement or paragraph header"
    return None


def closed_sentence_lead(statement, lines: list[str]) -> str | None:
    """The code before `statement` on its start line when that code ends
    a sentence (`PERFORM END-ROUTINE THRU END-ROUTINE-13. CLOSE PRINT-FILE.`,
    or a one-line paragraph `P1. CALL "X".`), else None.

    A splice can then keep that code: it emits it back on a line of its
    own ahead of the replacement (`BoundarySite.span_lead`), and the
    sentence it closes is complete without the statement. A lead that
    does not end with a period is part of the statement's own sentence
    (`MOVE A TO B CALL "X"`) and is never split off."""
    start = statement.location.line
    column = statement.location.column
    prefix = lines[start - 1][: column - 1]
    if not prefix.strip():
        return None
    code = _code_before(prefix)
    if code is None or not code.rstrip().endswith("."):
        return None
    return prefix.rstrip()


def _code_before(prefix: str) -> str | None:
    """`prefix` (the start of a line, up to a statement) as code, or None
    when it holds a `*>` comment or an unclosed literal: then the
    statement's column cannot be trusted to follow a closed sentence."""
    quote: str | None = None
    for index, char in enumerate(prefix):
        if quote is not None:
            if char == quote:
                quote = None
        elif char in "'\"":
            quote = char
        elif prefix.startswith("*>", index):
            return None
    return None if quote is not None else prefix


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


def _start_line_lead(
    statement, scope_map: ScopeMap, lines: list[str]
) -> tuple[str, ScopeBoundary | None] | None:
    """What precedes `statement` on its start line: `("", None)` when
    nothing does, `(header text, its boundary)` when only the clause header
    whose body it opens does (`AT END CALL "X"`), None when anything else
    does. A splice in place re-emits that header on a line of its own
    (`BoundarySite.span_lead`)."""
    start = statement.location.line
    column = statement.location.column
    prefix = lines[start - 1][: column - 1]
    if not prefix.strip():
        return "", None
    before = [b for b in scope_map.at_line(start) if b.column < column]
    if (
        len(before) == 1
        and before[0].clause_header
        and not prefix[: before[0].column - 1].strip()
    ):
        return prefix.rstrip(), before[0]
    return None


def _nested_site_span(
    site: BoundarySite,
    scope_map: ScopeMap,
    lines: list[str],
    parents: dict[int, BoundarySite] | None = None,
) -> tuple[tuple[int, int] | None, str | None, str | None]:
    """(span, reason there is none, header lead -- see `_start_line_lead`)."""
    statement = cast(ASTNode, site.statement)
    if site.nested_in_boundary:
        problem = _in_boundary_problem(site, parents or {})
        if problem is not None:
            return None, problem, None
    lead = _start_line_lead(statement, scope_map, lines)
    if lead is None:
        return None, "does not start its own line", None
    lead_text, lead_boundary = lead
    if _nested_statement_lists(statement):
        span, reason = _nested_clause_site_span(site, scope_map, lines, lead_boundary)
        return span, reason, (lead_text or None) if span else None

    start = statement.location.line
    column = statement.location.column

    own_terminator = (
        _VERB_TERMINATORS.get(site.category, "") if site.category is not None else ""
    )

    def relevant(boundary: ScopeBoundary) -> bool:
        return not (own_terminator and boundary.word == own_terminator)

    if any(
        relevant(b)
        and b is not lead_boundary
        and not (b.column == column and b.word == "")
        for b in scope_map.at_line(start)
    ):
        return None, "shares its start line with another statement or scope word", None

    nxt = next(
        (b for b in scope_map.iter_after_line(start) if relevant(b)),
        None,
    )
    if nxt is None:
        return None, "no following statement or scope word to bound the span", None
    if lines[nxt.line - 1][: nxt.column - 1].strip():
        return (
            None,
            (
                f"the next scope word or statement (line {nxt.line}) does not "
                f"start its own line"
            ),
            None,
        )

    end = _trim_trailing_blank_lines(start, nxt.line - 1, lines)
    if site.category in EXEC_CATEGORIES:
        if not any(
            "END-EXEC" in lines[line_no - 1].upper()
            for line_no in range(start, end + 1)
        ):
            return (
                None,
                "its END-EXEC terminator falls outside the computed span",
                None,
            )
    return (start, end), None, lead_text or None


def _descendants(statement) -> list:
    """Every statement inside `statement`'s own clause bodies, any depth."""
    found: list = []
    stack = list(_nested_statement_lists(statement))
    while stack:
        for child in stack.pop():
            found.append(child)
            stack.extend(_nested_statement_lists(child))
    return found


def _nested_clause_site_span(
    site: BoundarySite,
    scope_map: ScopeMap,
    lines: list[str],
    lead_boundary: ScopeBoundary | None = None,
) -> tuple[tuple[int, int] | None, str | None]:
    """The span of a nested statement WITH clause bodies of its own (READ
    ... AT END ... END-READ inside an inline PERFORM, CALL ... ON EXCEPTION
    ... END-CALL inside an IF; issue #258): from its first line to the
    line of its own explicit scope terminator, which is what makes its
    extent certain. Every boundary in between must belong to the
    statement itself -- a start of one of its own clause-body statements,
    or a scope word -- and the terminator must close its line. Without an
    explicit terminator the clause runs on to whatever closes the
    enclosing block, which is refused rather than guessed."""
    statement = cast(ASTNode, site.statement)
    start = statement.location.line
    column = statement.location.column
    if lead_boundary is None and lines[start - 1][: column - 1].strip():
        return None, "does not start its own line"
    own_terminator = (
        _VERB_TERMINATORS.get(site.category, "") if site.category is not None else ""
    )
    if not own_terminator:
        return None, (
            "has conditional clause bodies of its own (AT END/INVALID KEY/"
            "ON EXCEPTION/...) whose extent cannot be determined"
        )
    inner = _descendants(statement)
    descendants = {
        (child.location.line, child.location.column)
        for child in inner
        if getattr(child, "location", None) is not None
    }
    # A statement of its own kind in a clause body (CALL ... ON EXCEPTION
    # CALL "ERRLOG" ... END-CALL END-CALL): a terminator word closes the
    # nearest statement it has not closed yet, so each one opened inside
    # takes the next END-<verb> first. One that has none of its own takes
    # this statement's, which then has none and is refused below.
    same_kind = {
        (child.location.line, child.location.column)
        for child in inner
        if type(child) is type(statement)
        and getattr(child, "location", None) is not None
    }
    last_descendant = max(descendants, default=(start, column))

    terminator: ScopeBoundary | None = None
    candidates = [
        *(b for b in scope_map.at_line(start) if b.column > column),
        *scope_map.iter_after_line(start),
    ]
    open_inner = 0
    for boundary in candidates:
        if boundary.word == "":
            if (boundary.line, boundary.column) in descendants:
                open_inner += (boundary.line, boundary.column) in same_kind
                continue
            break  # a statement that is not part of this one
        if boundary.word == own_terminator and open_inner:
            open_inner -= 1
            continue
        if (
            boundary.word == own_terminator
            and (
                boundary.line,
                boundary.column,
            )
            > last_descendant
        ):
            terminator = boundary
            break
    if terminator is None and same_kind:
        return None, (
            f"has a statement of its own kind inside its clause bodies "
            f"without an {own_terminator} of its own, so which "
            f"{own_terminator} closes it cannot be determined"
        )
    if terminator is None:
        return None, (
            f"has conditional clause bodies of its own (AT END/INVALID KEY/"
            f"ON EXCEPTION/...) but no {own_terminator} of its own before the "
            f"next statement to bound them -- add {own_terminator} so its "
            f"extent is certain"
        )
    if any(
        b.line == terminator.line and b.column > terminator.column
        for b in scope_map.at_line(terminator.line)
    ):
        return None, (
            f"its {own_terminator} (line {terminator.line}) shares its line "
            f"with another statement or scope word"
        )
    after = lines[terminator.line - 1][
        terminator.column - 1 + len(own_terminator) :
    ].strip()
    if after not in ("", "."):
        return None, (
            f"its {own_terminator} (line {terminator.line}) is followed by "
            f"other code on the same line"
        )
    return (start, terminator.line), None
