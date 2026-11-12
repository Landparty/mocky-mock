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

from bisect import bisect_right
from dataclasses import dataclass

from cobolparser.models.statements.call import CallStatement
from cobolparser.models.statements.control import StopStatement
from cobolparser.models.statements.io import (
    IOAcceptStatement,
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
    ReleaseStatement,
    ReturnStatement,
)

from mockymock.analysis.mock_surface import (
    _BOUNDARY_STATEMENT_TYPES,
    _FILE_OP_SPECS,
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

#: Boundary statements a lifted body may hold: a CALL, a file op, RELEASE /
#: RETURN or a console ACCEPT nested in the clause (READ ... NOT AT END
#: CALL "X", CALL ... ON EXCEPTION WRITE ERR-REC). Each is a boundary site
#: of its own: when a case mocks it, the splicer splices its dispatch into
#: the lifted copy (`splicer.orchestrator`), at the span
#: `splicer.source_map.annotate_nested_sites` validated for it; when no
#: case does, it is copied as it stands, and the refusal gate refuses any
#: case that reaches it unmocked, exactly as anywhere else in the program.
#: EXEC blocks stay forbidden: an unmocked one has to be trapped, and a
#: nested one has no validated span.
_NESTABLE_BOUNDARY_TYPES: tuple[type, ...] = (
    CallStatement,
    *(statement_type for statement_type, _ in _FILE_OP_SPECS),
    ReleaseStatement,
    ReturnStatement,
    IOAcceptStatement,
)

#: Statements that may not run from a lifted body: any other boundary (an
#: EXEC block, SORT/MERGE, ...), and anything that leaves the program or
#: rewrites its control flow -- the test driver's PERFORM would not get
#: control back the way the splicer's terminator transforms guarantee. A GO
#: TO may: the lifted body is spliced into the same paragraph, so its
#: target and the PERFORM range it jumps within are unchanged (issue #319).
_FORBIDDEN_TYPES: tuple[type, ...] = (
    *(
        statement_type
        for statement_type in _BOUNDARY_STATEMENT_TYPES
        if statement_type not in _NESTABLE_BOUNDARY_TYPES
    ),
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
#: are file ops (AT END, INVALID KEY, END-OF-PAGE) belongs to a nested
#: boundary statement (`_NESTABLE_BOUNDARY_TYPES`), safe on the same terms.
_PHRASE_OWNERS: dict[str, frozenset[str]] = {
    "SIZE": frozenset({"ADD", "SUBTRACT", "MULTIPLY", "DIVIDE", "COMPUTE"}),
    "OVERFLOW": frozenset({"STRING", "UNSTRING", "CALL"}),
    "EXCEPTION": frozenset({"CALL", "ACCEPT", "DISPLAY", "XML", "JSON"}),
    "END": frozenset({"SEARCH", "READ", "RETURN"}),
    "INVALID": frozenset({"READ", "WRITE", "REWRITE", "DELETE", "START"}),
    "EOP": frozenset({"WRITE"}),
    "END-OF-PAGE": frozenset({"WRITE"}),
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
    selects it, and its source text as one stripped line per source line.

    `source_lines` is the same body exactly as it stands in the source
    (one line per entry, trailing blanks dropped; the first line keeps its
    indentation when the body starts its line). The splice emits these, so
    every whole body line stays text-equal to its source line and the
    instrumented -> original line map (`report.coverage.
    build_original_line_map`, used by trace, coverage and the debugger)
    pairs it with the line it came from (issue #332).

    `closers` are the END-IF / END-EVALUATE / END-SEARCH the sentence
    period closed for the last body (issue #319). `lines` ends with them
    too; `source_lines` does not (no source line holds them), so the splice
    emits them after the verbatim lines.

    `source_line_numbers` holds the 1-indexed line each `source_lines`
    entry came from: the splicer splices a boundary nested in the body
    (`_NESTABLE_BOUNDARY_TYPES`) by replacing the entries its span covers."""

    attr: str
    guard: str
    lines: tuple[str, ...]
    source_lines: tuple[str, ...] = ()
    closers: tuple[str, ...] = ()
    source_line_numbers: tuple[int, ...] = ()


def _spec(statement: object) -> tuple[tuple[str, ...], str] | None:
    for statement_type, attrs, terminator in _LIFTABLE:
        if isinstance(statement, statement_type):
            return attrs, terminator
    return None


def _walk(statements: list):
    """Every statement in `statements`, any depth -- except inside a nested
    boundary's own clause bodies: those belong to that boundary, which is
    spliced (and its own bodies lifted and checked) on its own account."""
    for statement in statements:
        yield statement
        if isinstance(statement, _NESTABLE_BOUNDARY_TYPES):
            continue
        for nested in _nested_statement_lists(statement):
            yield from _walk(nested)


def _walk_all(statements: list):
    """Every statement in `statements`, any depth, nested boundaries' own
    clause bodies included."""
    for statement in statements:
        yield statement
        for nested in _nested_statement_lists(statement):
            yield from _walk_all(nested)


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


def _header_begin(words: list, index: int, attr: str) -> int | None:
    """The index in `words` of the first word of `attr`'s header, which
    ends right before `words[index]` (the body's first word), or None when
    no spelling of it (`_HEADERS`) does."""
    for header in _HEADERS[attr]:
        begin = index - len(header)
        if begin < 0:
            continue
        if tuple(w for _, _, w in words[begin:index]) != header:
            continue
        if header[0] != "NOT" and begin > 0 and words[begin - 1][2] == "NOT":
            continue
        return begin
    return None


def clause_header_positions(
    statement: object, lines: list[str]
) -> list[tuple[int, int, str]]:
    """`(line, column, clause name)` of every clause header of `statement`
    (a READ / RETURN / WRITE / REWRITE / DELETE / START / CALL with clause
    bodies), both 1-indexed against `lines` -- or [] when it has none or
    any of them cannot be matched exactly.

    `splicer.source_map.collect_scope_map` records these as span
    boundaries: the AST locates no clause header, and a statement nested
    in a clause body (`READ ... AT END CALL "X" NOT AT END ...`) must stop
    before the next one. Only the text up to the last body's first
    statement is scanned, so a program's every statement can afford it."""
    spec = _spec(statement)
    location = getattr(statement, "location", None)
    start_line = getattr(location, "line", None)
    if spec is None or not start_line:
        return []
    firsts: list[tuple[int, int, str]] = []
    for attr in spec[0]:
        body = getattr(statement, attr, None)
        if not body:
            continue
        body_location = getattr(body[0], "location", None)
        line = getattr(body_location, "line", None)
        column = getattr(body_location, "column", None)
        if not line or not column or line < start_line or line > len(lines):
            return []
        firsts.append((line, column, attr))
    if not firsts:
        return []
    window = lines[start_line - 1 : max(line for line, _, _ in firsts)]
    offsets = [0]
    for text_line in window:
        offsets.append(offsets[-1] + len(text_line) + 1)
    words = list(scan_words("\n".join(window)))
    index_at = {start: index for index, (start, _, _) in enumerate(words)}
    positions: list[tuple[int, int, str]] = []
    for line, column, attr in firsts:
        index = index_at.get(offsets[line - start_line] + column - 1)
        begin = None if index is None else _header_begin(words, index, attr)
        if begin is None:
            return []
        offset = words[begin][0]
        row = bisect_right(offsets, offset) - 1
        positions.append(
            (start_line + row, offset - offsets[row] + 1, _clause_name(attr))
        )
    return sorted(positions)


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
    verb = terminator.removeprefix("END-")
    same_kind = any(
        type(nested) is type(statement)
        for attr in attrs
        for nested in _walk_all(getattr(statement, attr, None) or [])
    )
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
        begin = _header_begin(words, index, attr)
        if begin is None:
            return None, f"its {_clause_name(attr)} header could not be matched"
        header_starts.append(words[begin][0])
        body_word_indexes.append(index)

    lifted: list[LiftedClause] = []
    for position, (offset, attr) in enumerate(clauses):
        at_period = False
        if position + 1 < len(clauses):
            end = header_starts[position + 1]
        else:
            end = None
            # A statement of its own kind in a body (CALL ... ON EXCEPTION
            # CALL "ERRLOG" ... END-CALL END-CALL) takes the next
            # terminator first: a terminator closes the nearest statement
            # it has not closed yet.
            open_inner = 0
            for start, _, word in words[body_word_indexes[position] :]:
                if word == verb:
                    open_inner += 1
                elif word == terminator and open_inner:
                    open_inner -= 1
                elif word in (terminator, "."):
                    end = start
                    at_period = word == "."
                    break
            if end is None:
                return None, f"its {_clause_name(attr)} body has no end"
            if same_kind and (at_period or open_inner):
                return None, (
                    f"its {_clause_name(attr)} body holds a statement of its "
                    f"own kind without a {terminator} of its own, so which "
                    f"{terminator} closes which cannot be determined"
                )
        body_text = text[offset:end]
        problem, closers = _body_problem(
            [w for _, _, w in scan_words(body_text)], at_period
        )
        if problem is not None:
            return None, f"its {_clause_name(attr)} body cannot be lifted: {problem}"
        body_lines = tuple(
            line.strip() for line in body_text.split("\n") if line.strip()
        ) + tuple(closers)
        # The body exactly as it stands in the source (issue #332), so the
        # line map pairs each emitted line with its source line. The
        # END-IF / END-EVALUATE / END-SEARCH a sentence period closed
        # (issue #319) exists in no source line; it rides separately.
        line_start = text.rfind("\n", 0, offset) + 1
        lead = text[line_start:offset]
        # A body that shares its line with the clause header (`AT END MOVE
        # ...`) keeps its source column: the header is blanked rather than
        # dropped, or the fixed-format export put the body at column 1
        # (issue #454).
        verbatim = (lead if not lead.strip() else " " * len(lead)) + body_text
        first_line = start_line + text.count("\n", 0, offset)
        numbered = [
            (first_line + index, line.rstrip())
            for index, line in enumerate(verbatim.split("\n"))
            if line.strip()
        ]
        lifted.append(
            LiftedClause(
                attr,
                _GUARDS[attr],
                body_lines,
                tuple(line for _, line in numbered),
                tuple(closers),
                tuple(number for number, _ in numbered),
            )
        )
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
        if clause.source_lines:
            # Verbatim, then the scope closers the period supplied (#319).
            body = clause.source_lines + tuple(
                f"{indent}        {closer}" for closer in clause.closers
            )
        else:
            body = tuple(f"{indent}        {line}" for line in clause.lines)
        by_guard.setdefault(clause.guard, []).extend(body)
    for guard, guarded in by_guard.items():
        lines.append(f"{indent}    WHEN {guard}")
        lines.extend(guarded)
    lines.append(f"{indent}END-EVALUATE")
    return lines
