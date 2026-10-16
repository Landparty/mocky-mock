"""A mocked boundary statement's own conditional clause bodies, lifted
verbatim so the splice can still run them (issue #209).

The splicer replaces a mocked statement's whole span -- `READ f AT END ...
NOT AT END ... END-READ` included -- with its dispatch block. Before #209
that deleted the program's own clause bodies with it: a mocked READ fed N
records and the `NOT AT END PERFORM PROCESS-REC` that is the code under
test never ran. `lift_clause_bodies` recovers each clause body's text
from the normalized source so `splicer.injector.build_site_dispatch` can
re-emit it after the mock, guarded by the mocked outcome (the
`UT-MOCK-STATUS` field):

=================================  ===================================
clause                             runs when `UT-MOCK-STATUS` ...
=================================  ===================================
AT END                             starts with "1" (e.g. "10")
INVALID KEY                        starts with "2" (e.g. "23")
NOT AT END / NOT INVALID KEY       starts with "0" (the default "00")
NOT ON EXCEPTION / NOT ON OVERFLOW starts with "0"
ON EXCEPTION / ON OVERFLOW         is "EX"
=================================  ===================================

Fail closed: a statement whose clause bodies cannot be lifted exactly
keeps the old behaviour (the bodies are dropped with the statement).
`clause_bodies_liftable` is the AST half of that decision and
`lift_clause_bodies` adds the text half; see their docstrings for what
refuses.
"""

from __future__ import annotations

from dataclasses import dataclass

from cobolparser.models.statements.call import CallStatement
from cobolparser.models.statements.control import GoStatement, StopStatement
from cobolparser.models.statements.io import (
    IODeleteStatement,
    IOReadStatement,
    IORewriteStatement,
    IOStartStatement,
    IOWriteStatement,
)
from cobolparser.models.statements.misc import (
    AlterStatement,
    CancelStatement,
    ExitStatement,
    GobackStatement,
    NextSentenceStatement,
    ReturnStatement,
)

from mockymock.analysis.mock_surface import (
    _BOUNDARY_STATEMENT_TYPES,
    _NESTED_STATEMENT_ATTRS,
    _nested_statement_lists,
)

#: The field a mock's outcome is read from. Declared by the driver.
OUTCOME_FIELD = "UT-MOCK-STATUS"

#: The `UT-MOCK-STATUS` value that selects ON EXCEPTION / ON OVERFLOW.
EXCEPTION_OUTCOME = "EX"

#: Statement type -> (its clause attributes that may be lifted, its own
#: explicit scope terminator).
_LIFTABLE: tuple[tuple[type, tuple[str, ...], str], ...] = (
    (
        IOReadStatement,
        (
            "at_end_clause",
            "not_at_end_clause",
            "invalid_key_clause",
            "not_invalid_key_clause",
        ),
        "END-READ",
    ),
    (ReturnStatement, ("at_end_clause", "not_at_end_clause"), "END-RETURN"),
    (IOWriteStatement, ("invalid_key_clause", "not_invalid_key_clause"), "END-WRITE"),
    (
        IORewriteStatement,
        ("invalid_key_clause", "not_invalid_key_clause"),
        "END-REWRITE",
    ),
    (
        IODeleteStatement,
        ("invalid_key_clause", "not_invalid_key_clause"),
        "END-DELETE",
    ),
    (IOStartStatement, ("invalid_key_clause", "not_invalid_key_clause"), "END-START"),
    (
        CallStatement,
        ("on_exception", "not_on_exception", "on_overflow", "not_on_overflow"),
        "END-CALL",
    ),
)

#: Clause attribute -> the header phrases that may introduce it (the
#: optional noise word AT/KEY/ON present or not), longest first.
_HEADERS: dict[str, tuple[tuple[str, ...], ...]] = {
    "at_end_clause": (("AT", "END"), ("END",)),
    "not_at_end_clause": (("NOT", "AT", "END"), ("NOT", "END")),
    "invalid_key_clause": (("INVALID", "KEY"), ("INVALID",)),
    "not_invalid_key_clause": (("NOT", "INVALID", "KEY"), ("NOT", "INVALID")),
    "on_exception": (("ON", "EXCEPTION"), ("EXCEPTION",)),
    "not_on_exception": (("NOT", "ON", "EXCEPTION"), ("NOT", "EXCEPTION")),
    "on_overflow": (("ON", "OVERFLOW"), ("OVERFLOW",)),
    "not_on_overflow": (("NOT", "ON", "OVERFLOW"), ("NOT", "OVERFLOW")),
}

#: Clause attribute -> the `WHEN` condition that selects it.
_GUARDS: dict[str, str] = {
    "at_end_clause": f'{OUTCOME_FIELD}(1:1) = "1"',
    "invalid_key_clause": f'{OUTCOME_FIELD}(1:1) = "2"',
    "not_at_end_clause": f'{OUTCOME_FIELD}(1:1) = "0"',
    "not_invalid_key_clause": f'{OUTCOME_FIELD}(1:1) = "0"',
    "not_on_exception": f'{OUTCOME_FIELD}(1:1) = "0"',
    "not_on_overflow": f'{OUTCOME_FIELD}(1:1) = "0"',
    "on_exception": f'{OUTCOME_FIELD} = "{EXCEPTION_OUTCOME}"',
    "on_overflow": f'{OUTCOME_FIELD} = "{EXCEPTION_OUTCOME}"',
}

#: Statements that may not run from a lifted body: another boundary (it
#: would run unmocked), and anything that leaves the enclosing paragraph
#: or sentence -- the test driver's PERFORM would not get control back the
#: way the splicer's other transforms guarantee.
_FORBIDDEN_TYPES: tuple[type, ...] = (
    *_BOUNDARY_STATEMENT_TYPES,
    GobackStatement,
    StopStatement,
    GoStatement,
    AlterStatement,
    NextSentenceStatement,
    CancelStatement,
)

#: Words that open a conditional phrase of a NESTED statement (SIZE ERROR,
#: ON OVERFLOW, SEARCH's AT END, ...). Inside a lifted body such a phrase
#: may legally be closed only by the enclosing statement's own terminator,
#: which the lift removes -- so a body holding one is not lifted.
_NESTED_PHRASE_WORDS = frozenset(
    {"SIZE", "OVERFLOW", "EXCEPTION", "INVALID", "END", "EOP", "END-OF-PAGE"}
)

#: Conditional verbs whose explicit terminator must appear in a lifted body
#: as often as the verb itself: an unterminated nested IF would otherwise
#: swallow the next guard `WHEN` of the splice.
_SCOPED_VERBS = {"IF": "END-IF", "EVALUATE": "END-EVALUATE", "SEARCH": "END-SEARCH"}


@dataclass(frozen=True)
class LiftedClause:
    """One clause body: its AST attribute name, the `WHEN` condition that
    selects it, and its source text as one stripped line per source line.

    `source_lines` is the same body exactly as it stands in the source
    (one line per entry, trailing blanks dropped; the first line keeps its
    indentation when the body starts its line). The splice emits these, so
    every whole body line stays text-equal to its source line and the
    instrumented -> original line map (`report.coverage.
    build_original_line_map`, used by trace, coverage and the debugger)
    pairs it with the line it came from (issue #332)."""

    attr: str
    guard: str
    lines: tuple[str, ...]
    source_lines: tuple[str, ...] = ()


def _spec(statement: object) -> tuple[tuple[str, ...], str] | None:
    for statement_type, attrs, terminator in _LIFTABLE:
        if isinstance(statement, statement_type):
            return attrs, terminator
    return None


def _walk(statements: list):
    for statement in statements:
        yield statement
        for nested in _nested_statement_lists(statement):
            yield from _walk(nested)


def clause_bodies_liftable(statement: object) -> bool:
    """True when `statement` has at least one clause body and every one of
    them may be lifted: each clause is one this module knows how to guard,
    and nothing in any body is another boundary, a terminator, a GO TO,
    ALTER, NEXT SENTENCE or CANCEL (`_FORBIDDEN_TYPES`), or `EXIT PROGRAM`.
    A statement with a clause outside that set (WRITE's AT END-OF-PAGE)
    is not lifted at all -- lifting half its clauses would leave the other
    half's header text inside the lifted body."""
    spec = _spec(statement)
    if spec is None:
        return False
    attrs, _ = spec
    present = [
        attr for attr in _NESTED_STATEMENT_ATTRS if getattr(statement, attr, None)
    ]
    if not present or any(attr not in attrs for attr in present):
        return False
    for attr in present:
        for nested in _walk(getattr(statement, attr)):
            if isinstance(nested, _FORBIDDEN_TYPES):
                return False
            if isinstance(nested, ExitStatement) and nested.exit_type == "PROGRAM":
                return False
    return True


def scan_words(text: str):
    """Yield `(start, end, upper_word)` for every word OUTSIDE a quoted
    literal, plus `(index, index + 1, ".")` for every sentence-terminating
    period (a period followed by whitespace or end of text -- COBOL's own
    rule, which is also what keeps a numeric literal's decimal point from
    being mistaken for one)."""
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if char in ('"', "'"):
            quote = char
            index += 1
            while index < length:
                if text[index] == quote:
                    if index + 1 < length and text[index + 1] == quote:
                        index += 2
                        continue
                    index += 1
                    break
                index += 1
            continue
        if char.isspace():
            index += 1
            continue
        if char == "." and (index + 1 >= length or text[index + 1].isspace()):
            yield index, index + 1, "."
            index += 1
            continue
        start = index
        while (
            index < length
            and not text[index].isspace()
            and text[index] not in ('"', "'")
        ):
            index += 1
        word = text[start:index]
        if word.endswith(".") and (index >= length or text[index].isspace()):
            yield start, index - 1, word[:-1].upper()
            yield index - 1, index, "."
            continue
        yield start, index, word.upper()


def _body_is_safe(words: list[str]) -> bool:
    if not words or "." in words:
        return False
    if any(word in _NESTED_PHRASE_WORDS for word in words):
        return False
    return all(
        words.count(verb) == words.count(terminator)
        for verb, terminator in _SCOPED_VERBS.items()
    )


def lift_clause_bodies(
    statement: object, lines: list[str]
) -> tuple[LiftedClause, ...] | None:
    """Every clause body of `statement`, located in `lines` (the normalized
    source the AST's line/column numbers index), or None when they cannot
    all be lifted exactly -- the caller then keeps the old behaviour.

    Purely positional: a body runs from its first statement's own
    line/column (from the AST) to the header of the next clause, or to the
    statement's own scope terminator / sentence period for the last one,
    and each header must be one of that clause's own spellings
    (`_HEADERS`). The answer is a slice of the source, never a re-render."""
    if not clause_bodies_liftable(statement):
        return None
    spec = _spec(statement)
    assert spec is not None
    attrs, terminator = spec
    location = getattr(statement, "location", None)
    start_line = getattr(location, "line", None)
    if not start_line or start_line > len(lines):
        return None
    window = lines[start_line - 1 :]
    offsets = [0]
    for line in window:
        offsets.append(offsets[-1] + len(line) + 1)
    text = "\n".join(window)

    def offset_of(node: object) -> int | None:
        node_location = getattr(node, "location", None)
        line = getattr(node_location, "line", None)
        column = getattr(node_location, "column", None)
        if not line or not column or line < start_line:
            return None
        index = line - start_line
        if index >= len(window):
            return None
        return offsets[index] + column - 1

    clauses: list[tuple[int, str]] = []
    for attr in attrs:
        body = getattr(statement, attr, None)
        if not body:
            continue
        first = offset_of(body[0])
        if first is None:
            return None
        clauses.append((first, attr))
    clauses.sort()

    words = list(scan_words(text))
    starts = [start for start, _, _ in words]

    def word_index_at(offset: int) -> int | None:
        for index, start in enumerate(starts):
            if start == offset:
                return index
            if start > offset:
                return None
        return None

    header_starts: list[int] = []
    body_word_indexes: list[int] = []
    for offset, attr in clauses:
        index = word_index_at(offset)
        if index is None:
            return None
        for header in _HEADERS[attr]:
            begin = index - len(header)
            if begin < 0:
                continue
            if tuple(w for _, _, w in words[begin:index]) != header:
                continue
            if header[0] != "NOT" and begin > 0 and words[begin - 1][2] == "NOT":
                continue
            header_starts.append(words[begin][0])
            break
        else:
            return None
        body_word_indexes.append(index)

    lifted: list[LiftedClause] = []
    for position, (offset, attr) in enumerate(clauses):
        if position + 1 < len(clauses):
            end = header_starts[position + 1]
        else:
            end = None
            for start, _, word in words[body_word_indexes[position] :]:
                if word in (terminator, "."):
                    end = start
                    break
            if end is None:
                return None
        body_text = text[offset:end]
        if not _body_is_safe([w for _, _, w in scan_words(body_text)]):
            return None
        body_lines = tuple(
            line.strip() for line in body_text.splitlines() if line.strip()
        )
        line_start = text.rfind("\n", 0, offset) + 1
        lead = text[line_start:offset]
        verbatim = (lead if not lead.strip() else "") + body_text
        source_lines = tuple(
            line.rstrip() for line in verbatim.splitlines() if line.strip()
        )
        lifted.append(LiftedClause(attr, _GUARDS[attr], body_lines, source_lines))
    return tuple(lifted)


def clause_guard_lines(lifted: tuple[LiftedClause, ...], indent: str = "") -> list[str]:
    """The `EVALUATE TRUE` that runs the lifted clause selected by the
    mocked outcome. EVALUATE, not a chain of IFs: its selection is made
    once, before any body runs, so a body that PERFORMs code reaching
    another mock (which rewrites `UT-MOCK-STATUS`) cannot select a second
    clause.

    The EVALUATE / WHEN / END-EVALUATE lines are indented by `indent`; the
    bodies are the program's own lines verbatim (`source_lines`), so the
    line map still pairs each with its source line (issue #332)."""
    lines = [f"{indent}EVALUATE TRUE"]
    by_guard: dict[str, list[str]] = {}
    for clause in lifted:
        body = clause.source_lines or tuple(
            f"{indent}        {line}" for line in clause.lines
        )
        by_guard.setdefault(clause.guard, []).extend(body)
    for guard, guarded in by_guard.items():
        lines.append(f"{indent}    WHEN {guard}")
        lines.extend(guarded)
    lines.append(f"{indent}END-EVALUATE")
    return lines
