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

Fail closed: a mocked statement whose clause bodies cannot be lifted
exactly is refused (UNLIFTABLE_CLAUSE_BODY, issue #319) -- before, it
silently lost every body with the statement.
`clause_bodies_liftable` is the AST half of that decision and
`lift_clause_bodies` adds the text half; see their docstrings for what
refuses.
"""

from __future__ import annotations

from dataclasses import dataclass

from cobolparser.models.statements.call import CallStatement
from cobolparser.models.statements.control import StopStatement
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
#: would run unmocked), and anything that leaves the program or rewrites
#: its control flow -- the test driver's PERFORM would not get control back
#: the way the splicer's terminator transforms guarantee. A GO TO may: the
#: lifted body is spliced into the same paragraph, so its target and the
#: PERFORM range it jumps within are unchanged (issue #319).
_FORBIDDEN_TYPES: tuple[type, ...] = (
    *_BOUNDARY_STATEMENT_TYPES,
    GobackStatement,
    StopStatement,
    AlterStatement,
    NextSentenceStatement,
    CancelStatement,
)

#: Clause attribute -> how a refusal names it.
_CLAUSE_NAMES: dict[str, str] = {
    "at_end_clause": "AT END",
    "not_at_end_clause": "NOT AT END",
    "invalid_key_clause": "INVALID KEY",
    "not_invalid_key_clause": "NOT INVALID KEY",
    "at_eop_clause": "AT END-OF-PAGE",
    "not_at_eop_clause": "NOT AT END-OF-PAGE",
    "on_exception": "ON EXCEPTION",
    "not_on_exception": "NOT ON EXCEPTION",
    "on_overflow": "ON OVERFLOW",
    "not_on_overflow": "NOT ON OVERFLOW",
    "on_size_error": "ON SIZE ERROR",
    "not_on_size_error": "NOT ON SIZE ERROR",
    "no_data_clause": "NO DATA",
    "with_data_clause": "WITH DATA",
}

#: Statement type -> how a refusal names a forbidden statement.
_FORBIDDEN_NAMES: tuple[tuple[type, str], ...] = (
    (GobackStatement, "GOBACK"),
    (StopStatement, "STOP"),
    (AlterStatement, "ALTER"),
    (NextSentenceStatement, "NEXT SENTENCE"),
    (CancelStatement, "CANCEL"),
)


#: Conditional phrases a NESTED statement may carry (SIZE ERROR, ON
#: OVERFLOW, a SEARCH's AT END, ...), keyed by the word that opens them,
#: with the verbs that may own each. Inside a lifted body such a phrase is
#: safe only when its owner is closed by its own explicit terminator after
#: the phrase: otherwise the phrase would legally run to the enclosing
#: statement's terminator, which the lift removes, and swallow the next
#: guard `WHEN`. `SIZE` opens one only before `ERROR` -- `STRING ...
#: DELIMITED BY SIZE` is not a phrase (issue #326). A phrase whose owners
#: are all boundaries (INVALID KEY, END-OF-PAGE) never appears in a lifted
#: body, which holds no boundary; it is refused outright all the same.
_PHRASE_OWNERS: dict[str, frozenset[str]] = {
    "SIZE": frozenset({"ADD", "SUBTRACT", "MULTIPLY", "DIVIDE", "COMPUTE"}),
    "OVERFLOW": frozenset({"STRING", "UNSTRING", "CALL"}),
    "EXCEPTION": frozenset({"CALL", "ACCEPT", "DISPLAY", "XML", "JSON"}),
    "END": frozenset({"SEARCH"}),
    "INVALID": frozenset(),
    "EOP": frozenset(),
    "END-OF-PAGE": frozenset(),
}

#: Every verb that may own a conditional phrase.
_PHRASE_VERBS = frozenset().union(*_PHRASE_OWNERS.values())

#: Conditional verbs whose explicit terminator must appear in a lifted body
#: as often as the verb itself: an unterminated nested IF would otherwise
#: swallow the next guard `WHEN` of the splice.
_SCOPED_VERBS = {"IF": "END-IF", "EVALUATE": "END-EVALUATE", "SEARCH": "END-SEARCH"}


@dataclass(frozen=True)
class LiftedClause:
    """One clause body: its AST attribute name, the `WHEN` condition that
    selects it, and its source text as one stripped line per source line."""

    attr: str
    guard: str
    lines: tuple[str, ...]


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


def _clause_name(attr: str) -> str:
    return _CLAUSE_NAMES.get(attr, attr.upper())


def _statement_name(statement: object) -> str:
    for statement_type, name in _FORBIDDEN_NAMES:
        if isinstance(statement, statement_type):
            return name
    return "another boundary"


def _ast_problem(statement: object) -> str | None:
    """Why the AST alone rules the lift out, or None. Assumes `_spec`
    matched and at least one clause body is present."""
    spec = _spec(statement)
    assert spec is not None
    attrs, _ = spec
    present = [
        attr for attr in _NESTED_STATEMENT_ATTRS if getattr(statement, attr, None)
    ]
    for attr in present:
        if attr not in attrs:
            return f"its {_clause_name(attr)} clause cannot be re-run after a mock"
    for attr in present:
        for nested in _walk(getattr(statement, attr)):
            line = getattr(getattr(nested, "location", None), "line", None)
            where = f" at line {line}" if line else ""
            if isinstance(nested, _FORBIDDEN_TYPES):
                return (
                    f"its {_clause_name(attr)} body holds a "
                    f"{_statement_name(nested)} statement{where}, which "
                    f"cannot run from a lifted body"
                )
            if isinstance(nested, ExitStatement) and nested.exit_type == "PROGRAM":
                return (
                    f"its {_clause_name(attr)} body holds an EXIT PROGRAM "
                    f"statement{where}, which cannot run from a lifted body"
                )
    return None


def _has_clause_bodies(statement: object) -> bool:
    return _spec(statement) is not None and any(
        getattr(statement, attr, None) for attr in _NESTED_STATEMENT_ATTRS
    )


def clause_bodies_liftable(statement: object) -> bool:
    """True when `statement` has at least one clause body and every one of
    them may be lifted: each clause is one this module knows how to guard,
    and nothing in any body is another boundary, a terminator, ALTER, NEXT
    SENTENCE or CANCEL (`_FORBIDDEN_TYPES`), or `EXIT PROGRAM`. A GO TO
    is allowed (issue #319). A statement with a clause outside that set
    (WRITE's AT END-OF-PAGE) is not lifted at all -- lifting half its
    clauses would leave the other half's header text inside the lifted
    body."""
    return _has_clause_bodies(statement) and _ast_problem(statement) is None


def scan_words(text: str):
    """Yield `(start, end, upper_word)` for every word OUTSIDE a quoted
    literal, plus `(index, index + 1, ".")` for every sentence-terminating
    period (a period followed by whitespace or end of text -- COBOL's own
    rule, which is also what keeps a numeric literal's decimal point from
    being mistaken for one). An inline `*>` comment outside a literal is
    skipped to the end of its line: a period or apostrophe in it is not
    code (issue #327)."""
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if char == "*" and text.startswith("*>", index):
            newline = text.find("\n", index)
            index = length if newline < 0 else newline
            continue
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
            and not text.startswith("*>", index)
        ):
            index += 1
        word = text[start:index]
        if word.endswith(".") and (index >= length or text[index].isspace()):
            yield start, index - 1, word[:-1].upper()
            yield index - 1, index, "."
            continue
        yield start, index, word.upper()


def _nested_phrases_terminated(words: list[str]) -> bool:
    """True when every conditional phrase in `words` belongs to a nested
    statement closed by its own `END-<verb>` after the phrase. Tracks the
    open phrase-capable verbs as a stack: a terminator closes the nearest
    open verb of its name (and every unterminated verb nested inside it),
    a phrase marks the nearest open verb that may own it."""
    stack: list[list] = []  # [verb, has_phrase]
    for index, word in enumerate(words):
        if word in _PHRASE_VERBS:
            stack.append([word, False])
            continue
        if word.startswith("END-") and word[4:] in _PHRASE_VERBS:
            verb = word[4:]
            for depth in range(len(stack) - 1, -1, -1):
                if stack[depth][0] == verb:
                    if any(entry[1] for entry in stack[depth + 1 :]):
                        return False
                    del stack[depth:]
                    break
            continue
        owners = _PHRASE_OWNERS.get(word)
        if owners is None:
            continue
        if word == "SIZE" and (index + 1 >= len(words) or words[index + 1] != "ERROR"):
            continue
        for entry in reversed(stack):
            if entry[0] in owners:
                entry[1] = True
                break
        else:
            return False
    return not any(entry[1] for entry in stack)


def _body_problem(words: list[str], at_period: bool) -> tuple[str | None, list[str]]:
    """Why a body's words cannot be lifted (None when they can), and the
    explicit terminators to append to it. A body that ends at the sentence
    period may leave IF / EVALUATE / SEARCH open -- the period closes them
    -- so their END-xxx are appended, innermost first (issue #319); one
    ended by the next clause's header may not."""
    if not words or "." in words:
        return "a sentence period ends it early", []
    if not _nested_phrases_terminated(words):
        return (
            "it holds a nested conditional phrase (SIZE ERROR, OVERFLOW, "
            "EXCEPTION, AT END, ...) not closed by its own END-<verb>",
            [],
        )
    open_scopes: list[str] = []
    for word in words:
        if word in _SCOPED_VERBS:
            open_scopes.append(word)
        elif word in _SCOPED_VERBS.values():
            if not open_scopes or _SCOPED_VERBS[open_scopes[-1]] != word:
                return f"its {word} closes no open scope", []
            open_scopes.pop()
    if open_scopes and not at_period:
        return (
            f"an {open_scopes[-1]} in it has no {_SCOPED_VERBS[open_scopes[-1]]}"
            f" before the next clause",
            [],
        )
    return None, [_SCOPED_VERBS[verb] for verb in reversed(open_scopes)]


def _lift(
    statement: object, lines: list[str], column_offset: int = 0
) -> tuple[tuple[LiftedClause, ...] | None, str | None]:
    """The lifted clauses, or None and why not (None too when `statement`
    has no clause bodies this module handles)."""
    if not _has_clause_bodies(statement):
        return None, None
    problem = _ast_problem(statement)
    if problem is not None:
        return None, problem
    spec = _spec(statement)
    assert spec is not None
    attrs, terminator = spec
    unlocated = "its clause bodies could not be located in the source"
    location = getattr(statement, "location", None)
    start_line = getattr(location, "line", None)
    if not start_line or start_line > len(lines):
        return None, unlocated
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
        return offsets[index] + column_offset + column - 1

    clauses: list[tuple[int, str]] = []
    for attr in attrs:
        body = getattr(statement, attr, None)
        if not body:
            continue
        first = offset_of(body[0])
        if first is None:
            return None, unlocated
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
            return None, unlocated
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
            return None, f"its {_clause_name(attr)} header could not be matched"
        body_word_indexes.append(index)

    lifted: list[LiftedClause] = []
    for position, (offset, attr) in enumerate(clauses):
        at_period = False
        if position + 1 < len(clauses):
            end = header_starts[position + 1]
        else:
            end = None
            for start, _, word in words[body_word_indexes[position] :]:
                if word in (terminator, "."):
                    end = start
                    at_period = word == "."
                    break
            if end is None:
                return None, f"its {_clause_name(attr)} body has no end"
        body_text = text[offset:end]
        problem, closers = _body_problem(
            [w for _, _, w in scan_words(body_text)], at_period
        )
        if problem is not None:
            return None, f"its {_clause_name(attr)} body cannot be lifted: {problem}"
        body_lines = tuple(
            line.strip() for line in body_text.splitlines() if line.strip()
        ) + tuple(closers)
        lifted.append(LiftedClause(attr, _GUARDS[attr], body_lines))
    return tuple(lifted), None


def lift_clause_bodies(
    statement: object, lines: list[str], column_offset: int = 0
) -> tuple[LiftedClause, ...] | None:
    """Every clause body of `statement`, located in `lines` (the normalized
    source the AST's line/column numbers index), or None when it has none
    or they cannot all be lifted exactly (`clause_lift_problem` says why;
    the refusal gate refuses a mocked site in that case, issue #319).

    Purely positional: a body runs from its first statement's own
    line/column (from the AST) to the header of the next clause, or to the
    statement's own scope terminator / sentence period for the last one,
    and each header must be one of that clause's own spellings
    (`_HEADERS`). The answer is a slice of the source, never a re-render,
    plus the END-IF / END-EVALUATE / END-SEARCH a sentence period closed.
    `column_offset`: how far right of the AST's columns every line sits
    (`export` restores the 7-column sequence area first, issue #325)."""
    return _lift(statement, lines, column_offset)[0]


def clause_lift_problem(statement: object, lines: list[str]) -> str | None:
    """Why `statement`'s clause bodies cannot be lifted, or None when they
    can or it has none. A mocked site with a problem would lose its bodies
    with the statement, so the refusal gate refuses it
    (UNLIFTABLE_CLAUSE_BODY, issue #319)."""
    return _lift(statement, lines)[1]


def clause_guard_lines(lifted: tuple[LiftedClause, ...]) -> list[str]:
    """The `EVALUATE TRUE` that runs the lifted clause selected by the
    mocked outcome. EVALUATE, not a chain of IFs: its selection is made
    once, before any body runs, so a body that PERFORMs code reaching
    another mock (which rewrites `UT-MOCK-STATUS`) cannot select a second
    clause."""
    lines = ["EVALUATE TRUE"]
    by_guard: dict[str, list[str]] = {}
    for clause in lifted:
        by_guard.setdefault(clause.guard, []).extend(clause.lines)
    for guard, body in by_guard.items():
        lines.append(f"    WHEN {guard}")
        lines.extend(f"        {line}" for line in body)
    lines.append("END-EVALUATE")
    return lines
