"""File I/O replies: READ bodies, AT END / INVALID KEY replication and
lifting, file-status-only bodies and read exhaustion."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any, cast

from mockymock.analysis.clause_bodies import (
    OUTCOME_FIELD,
    lift_clause_bodies,
    scan_words,
)
from mockymock.analysis.loops import loop_guard_words
from mockymock.analysis.mock_surface import (
    BoundarySite,
    _all_paragraphs,
    analyze_file_status_fields,
)
from mockymock.dsl.fixture_bundle import BoundaryFixture
from mockymock.dsl.generator._context import _DEFAULT_SUCCESS_CODES, ProgramContext
from mockymock.dsl.generator.keys import _read_mock_key, split_read_files
from mockymock.dsl.generator.rows import _row_move_lines
from mockymock.dsl.generator.sql import _sql_status_lines
from mockymock.dsl.model import MockCategory
from mockymock.splicer.naming import TallyRegistry

if TYPE_CHECKING:
    from cobolparser.models.program import CobolProgram


#: Mirrors cobolparser's own lexer.py CobolLexer.FIGURATIVE_CONSTANTS
#: vocabulary (minus ALL, which always prefixes a literal rather than
#: standing alone) -- a MOVE source in this set is exactly as safe to copy
#: verbatim as a quoted/numeric literal, see _is_safe_literal_source.
_FIGURATIVE_CONSTANTS = frozenset(
    {
        "ZERO",
        "ZEROS",
        "ZEROES",
        "SPACE",
        "SPACES",
        "HIGH-VALUE",
        "HIGH-VALUES",
        "LOW-VALUE",
        "LOW-VALUES",
        "QUOTE",
        "QUOTES",
    }
)


def _is_safe_literal_source(source: str) -> bool:
    """True for a MOVE source this generator can safely replicate verbatim
    into a mock body: a quoted string literal, a numeric literal, or a
    figurative constant -- never a bare identifier, whose value in the
    mock's own splice-time context is not the real program's runtime
    state at that point. See _replicated_at_end_statements."""
    if not source:
        return False
    if len(source) >= 2 and source[0] in ('"', "'") and source[-1] == source[0]:
        return True
    if source.upper() in _FIGURATIVE_CONSTANTS:
        return True
    digits = source[1:] if source[0] in "+-" else source
    return digits.replace(".", "", 1).isdigit()


#: `SetStatement.set_type` values that assign a *constant* to a level-88
#: condition name and so are safe to replicate verbatim into a mock body,
#: by the same standard `_is_safe_literal_source` applies to a `MOVE`
#: source: the statement names no identifier whose runtime value differs
#: between the real program's context and the mock's. Every other
#: `set_type` (`TO` an identifier/index, `UP_BY`, `DOWN_BY`) does, and is
#: left unreplicated. A replicated `SET ... TO FALSE` compiles iff the
#: original did (it needs the 88's own `FALSE` phrase either way), so it
#: is no less safe than `TRUE`.
_CONSTANT_SET_TYPES = frozenset({"TRUE", "FALSE"})


def _replicated_set_lines(clause_statement: object) -> list[str]:
    """`SET <88-condition-name> TO TRUE` lines replicated out of an `AT
    END` clause -- the condition-name spelling of the same EOF-flag idiom
    `_replicated_at_end_statements` handles for `MOVE`.

    `SET WS-FIN-FICHIER TO TRUE` against an `88 WS-FIN-FICHIER VALUE "O"`
    is at least as common in the wild as `MOVE "Y" TO WS-EOF`, and fails
    identically when it is dropped: the mock moves the FILE STATUS field,
    the application-level flag is never flipped, and the program's own
    `PERFORM UNTIL <condition-name>` loop spins forever. Skipped (leaving
    `_read_exhaustion_lines`'s TODO comment to flag the gap honestly)
    when the statement carries additional `groups` -- a multi-group `SET
    A TO TRUE B TO FALSE` -- since replicating only the first group would
    be a silent *partial* replication, which is worse than none."""
    if type(clause_statement).__name__ != "SetStatement":
        return []
    if getattr(clause_statement, "groups", None):
        return []
    set_type = getattr(clause_statement, "set_type", None)
    if set_type not in _CONSTANT_SET_TYPES:
        return []
    return [
        f"SET {target} TO {set_type}"
        for target in getattr(clause_statement, "targets", [])
    ]


def _replicated_at_end_statements(statement: object) -> list[str]:
    """Extra lines for a READ mock's exhaustion (`WHEN OTHER`)
    branch: the splicer replaces the *whole* READ statement (see
    splicer/orchestrator.py's own module docstring), which also deletes
    its `AT END` clause's own statements. When that clause is the only
    place the program sets its own application-level EOF flag -- the
    "READ ... AT END MOVE 'Y' TO WS-EOF" idiom (see
    examples/invupdt/INVUPDT.cut's own hand-written mock doing the exact
    same thing by hand), or its condition-name spelling "READ ... AT END
    SET WS-FIN-FICHIER TO TRUE" -- a generated mock that moves only the
    FILE STATUS field never flips that flag, so the program's own
    `PERFORM ... UNTIL WS-EOF = ...` loop never terminates: an infinite
    loop, not a wrong value, at runtime (found via
    examples/fixtures/FIXTUREDEMO's own Docker-gated CI run timing out).
    Deliberately conservative: only a `MOVE` whose source is a literal or
    figurative constant (`_is_safe_literal_source`) and a constant-valued
    `SET` (`_replicated_set_lines`) are replicated; anything else in the
    clause (a bare-identifier source, IF, PERFORM, ...) is left
    unreplicated -- a known, narrower gap than the one this closes, not
    silently guessed at. All or nothing: when any statement in the clause
    is not one of those two shapes, nothing is replicated (issue #217)."""
    at_end = getattr(statement, "at_end_clause", None) or []
    lines: list[str] = []
    for clause_statement in at_end:
        if type(clause_statement).__name__ == "MoveStatement":
            source = getattr(clause_statement, "source", None)
            targets = getattr(clause_statement, "targets", [])
            if not source or not _is_safe_literal_source(source) or not targets:
                return []
            for target in targets:
                lines.append(f"MOVE {source} TO {target}")
            continue
        replicated = _replicated_set_lines(clause_statement)
        if not replicated:
            # All or nothing (issue #217): a clause replicated only in
            # part silently dropped its other statements -- `MOVE "Y" TO
            # WS-EOF` kept, `MOVE WS-READ-CNT TO WS-TRAILER-CNT` lost --
            # and `run --record-expectations` then recorded the wrong
            # values as goldens. Returning nothing hands the clause to
            # `_lifted_at_end_lines`, which copies it whole, or to the TODO.
            return []
        lines.extend(replicated)
    return lines


def _status_read_eof(
    fixture: BoundaryFixture, source: ProgramContext | None
) -> tuple[BoundaryFixture, bool]:
    """`fixture` with an end-of-file `terminal` (`{<status field>: "10"}`)
    when the bundle gave it none and the file's READs are status-driven
    (`ProgramContext.status_read_eof`), plus whether that READ runs in a
    loop -- such a loop calls it once more than it has rows, the call that
    finds the end of the file. `(fixture, False)` otherwise."""
    if fixture.terminal or source is None:
        return fixture, False
    entry = source.status_read_eof.get(fixture.key.upper())
    if entry is None:
        return fixture, False
    status_field, looped = entry
    return replace(fixture, terminal={status_field: "10"}), looped


_scan_words = scan_words


#: Word sequences that end a READ's AT END imperative. `NOT AT END` must be
#: checked before `AT END` anywhere this list is used against a scan, since
#: it shares its tail.
_AT_END_TERMINATORS: tuple[tuple[str, ...], ...] = (
    ("NOT", "AT", "END"),
    ("END-READ",),
    ("INVALID", "KEY"),
    ("NOT", "INVALID", "KEY"),
    (".",),
)


def _extract_at_end_imperative(statement_text: str) -> str | None:
    """The text of a READ's `AT END` imperative, exactly as the program
    wrote it -- original line breaks and all -- or None when it cannot be
    located unambiguously.

    Purely positional: the words are located outside quoted literals, and
    the answer is a slice of the input, never a reconstruction. That is the
    whole point -- an AST-driven re-render can only cover the statement
    shapes it knows about, while the program's own text is by definition
    the statement the splicer is about to delete.
    """
    words = list(_scan_words(statement_text))
    start = None
    for index in range(len(words) - 1):
        if words[index][2] == "AT" and words[index + 1][2] == "END":
            if index > 0 and words[index - 1][2] == "NOT":
                continue
            start = words[index + 1][1]
            start_word = index + 2
            break
    if start is None:
        return None

    end = len(statement_text)
    for index in range(start_word, len(words)):
        for terminator in _AT_END_TERMINATORS:
            if (
                tuple(w[2] for w in words[index : index + len(terminator)])
                == terminator
            ):
                end = words[index][0]
                break
        else:
            continue
        break
    lifted = statement_text[start:end].strip()
    return lifted or None


def _body_lines_parse(body: list[str]) -> bool:
    """Whether the `.cut` parser takes `body` as MOCK body lines: it refuses
    one that leaves the body (`PERFORM <paragraph>`, GO TO, GOBACK, STOP
    RUN, EXIT PROGRAM -- issue #287), and an `AT END PERFORM 9000-EOF`
    copied in verbatim made the whole generated `.cut` unreadable."""
    from mockymock.dsl.parser import CutParseError, _reject_body_control_flow

    try:
        for line_no, line in enumerate(body, 1):
            _reject_body_control_flow(line, line_no, "READ")
    except CutParseError:
        return False
    return True


def _lifted_at_end_lines(
    site: BoundarySite, source: ProgramContext | None
) -> list[str]:
    """The program's own `AT END` imperative, re-indented for a `.cut` MOCK
    body, or `[]` when it could not be lifted safely.

    The splicer replaces the WHOLE `READ` statement, which deletes its `AT
    END` clause with it -- so a generated mock that moves only the FILE
    STATUS field never runs the program's own end-of-data handling, and a
    `PERFORM ... UNTIL <eof-flag>` loop keyed on it spins until the executor
    timeout. That is a 30-second hang with no diagnosis, which is a far
    worse outcome than any of the shapes this refuses on.

    Refused (returning `[]`, leaving the caller's TODO comment) when the
    lifted text carries a sentence-terminating period of its own: a period
    inside the spliced `EVALUATE` branch would close the enclosing sentence
    early and silently restructure the generated program's control flow.
    Likewise when a line of it would not parse as a MOCK body line
    (`_body_lines_parse`).
    """
    if source is None:
        return []
    statement_text = source.statement_text(site.line)
    if statement_text is None:
        return []
    lifted = _extract_at_end_imperative(statement_text)
    if lifted is None:
        return []
    if any(word == "." for _, _, word in _scan_words(lifted)):
        return []
    body = [line.strip() for line in lifted.splitlines() if line.strip()]
    if not body or not _body_lines_parse(body):
        return []
    return [
        f"*> replicated verbatim from this program's own READ ... AT END "
        f"clause (line {site.line}) -- the splicer replaces the whole READ, "
        f"deleting it",
        *body,
    ]


def _end_of_file_placeholder(
    site: BoundarySite,
    context: ProgramContext | None,
    file_status_fields: dict[str, str] | None = None,
) -> list[str]:
    """A READ or RETURN placeholder's body when the statement has an AT END
    clause: report end of file on the first call, and carry the program's
    own AT END handling. An empty body answered every call with a record,
    so the commonest batch loop, `PERFORM ... UNTIL WS-EOF = "Y"` around
    `READ ... AT END MOVE "Y" TO WS-EOF`, ran until --timeout from lint's
    suggested fix, `generate --fill` and `--per-paragraph` alike (issue
    #302; RETURN, the SORT OUTPUT PROCEDURE shape, is #262).

    With a `ProgramContext` this is exactly what a bundle READ fixture's
    exhaustion branch is (`_at_end_handling` / `_read_exhaustion_lines`).
    Without one (lint's suggestion): the FILE STATUS field gets "10", or,
    for a file with none, the splice's outcome field does, so the splice
    re-runs the statement's own AT END clause; the clause's replicable
    statements (idempotent MOVEs/SETs) are added too, for a site the splice
    cannot lift the clause from."""
    if site.category not in (MockCategory.READ, MockCategory.RETURN):
        return []
    if not getattr(site.statement, "at_end_clause", None) or not site.keys:
        return []
    key = site.keys[0]
    if file_status_fields is None and context is not None and context.program:
        file_status_fields = analyze_file_status_fields(cast(Any, context.program))
    status = (
        (file_status_fields or {}).get(key.upper())
        if site.category is MockCategory.READ
        else None
    )
    if context is not None:
        fixture = BoundaryFixture(
            category=site.category.value,
            key=key,
            paragraph=site.paragraph_name,
            line=site.line,
            direction="IN",
            terminal={status: "10"} if status else None,
        )
        replicated, at_end, lifted = _at_end_handling(fixture, site, context)
        return _read_exhaustion_lines(fixture, replicated, at_end, lifted)
    lines = [f'MOVE "10" TO {status or OUTCOME_FIELD}']
    replicated = _replicated_at_end_statements(site.statement)
    lines.extend(replicated)
    if site.nested and not replicated:
        lines.append(
            "*> TODO: this program's AT END clause could not be "
            "auto-replicated -- add its loop-guard statement by hand, "
            "or this mock will never end the program's read loop"
        )
    return lines


def _status_only_body(fixture: BoundaryFixture) -> list[str]:
    """OPEN/CLOSE/DELETE/START/UNLOCK: nothing to generate, only a status
    code. The implicit default-success MOVE (injector.build_site_dispatch)
    already covers "00"/"0" -- only a non-default status needs the
    `FILE-STATUS IS` sugar (always usable as a quoted 2-char literal, no
    need to map to a mnemonic name).

    SQL (OPEN/CLOSE/COMMIT of a cursor or unit of work) has no implicit
    default: its body always sets SQLCODE, or the value a previous call or
    case left there leaks into this one (issue #148)."""
    if fixture.category == "SQL":
        return _sql_status_lines(fixture)
    for code in fixture.status.values():
        if code not in _DEFAULT_SUCCESS_CODES:
            return [f'FILE-STATUS IS "{code}"']
    return []


def _read_exhaustion_lines(
    fixture: BoundaryFixture,
    replicated: list[str],
    at_end: list[object],
    lifted: list[str] | None = None,
) -> list[str]:
    """The lines that fire once a READ mock's rows are exhausted:
    `fixture.terminal`'s status code MOVE(s) plus whatever of the
    program's own `AT END` clause `_replicated_at_end_statements` could safely
    replicate (or a TODO comment when it couldn't, see `_read_body`'s own
    docstring on that gating). Factored out of `_read_body` so this exact
    termination behavior -- not an empty body -- is what fires both for
    the `WHEN OTHER` branch of a multi-row EVALUATE AND for a
    `sequence`-less fixture (fix round 1, unify-with-data Task 4: `--rows
    0` on the self-generating path, or a bundle's own "empty input"
    scenario family on `--fixtures`) AND for a `--placeholder`-downgraded
    READ fixture (`_bundle_directive_for`). An empty/no-op body in any of
    these three places would silently drop the program's own EOF-flag
    idiom and hang its `PERFORM ... UNTIL <eof-flag>` loop forever --
    exactly the class of bug commit 3ad3378 fixed for the ordinary
    multi-row case; this closes the same gap for the zero-row and
    downgraded cases too. `run --with-data`/`--placeholder`/`--rows 0`
    correctness is judged against real execution (a real Docker run), not
    `lint`, which cannot see a splice-time infinite loop."""
    lines: list[str] = []
    for field_name, code in (fixture.terminal or {}).items():
        lines.append(f'MOVE "{code}" TO {field_name}')
    lines.extend(replicated)
    if at_end and not replicated:
        # The AST-driven replication above covers the two idioms it can
        # prove safe. Everything else used to become a TODO comment -- and
        # a TODO left in place is not a visible gap, it is a 30-second hang
        # at the executor timeout with no diagnosis, since the program's own
        # loop guard never gets set. Lifting the clause's own source text is
        # both more general and more faithful than any re-render: it is
        # exactly the text the splicer is deleting.
        lines.extend(lifted or [])
        if not lifted:
            lines.append(
                "*> TODO: this program's AT END clause could not be "
                "auto-replicated -- add its loop-guard statement by hand, "
                "or this mock will never end the program's read loop"
            )
    return lines


def _at_end_handling(
    fixture: BoundaryFixture, site: BoundarySite, source: ProgramContext | None
) -> tuple[list[str], list[object], list[str]]:
    """(replicated, at_end, lifted) for a READ mock's exhaustion branch --
    see `_read_exhaustion_lines`.

    When the splicer itself re-runs this READ's own AT END clause after the
    mock (`analysis.clause_bodies`, issue #209: it does for a top-level
    READ whose clause bodies it can lift exactly), the branch must only
    report end-of-file -- copying the clause in here too would run it
    twice. A file with a FILE STATUS field reports it through
    `fixture.terminal`'s MOVE; one without sets `UT-MOCK-STATUS`, the
    splicer's own outcome field. Otherwise the clause is replicated or
    lifted into the branch as before."""
    at_end = getattr(site.statement, "at_end_clause", None) or []
    if at_end and source is not None and (not site.nested or site.span is not None):
        lifted_clauses = lift_clause_bodies(site.statement, source.lines)
        if lifted_clauses and any(c.attr == "at_end_clause" for c in lifted_clauses):
            signal = [
                f"*> end of file: the splice runs this READ's own AT END "
                f"clause (line {site.line}) after the mock"
            ]
            if not fixture.terminal:
                signal.append(f'MOVE "10" TO {OUTCOME_FIELD}')
            return signal, at_end, []
    replicated = _replicated_at_end_statements(site.statement)
    lifted = _lifted_at_end_lines(site, source) if at_end and not replicated else []
    return replicated, at_end, lifted


def _keyed_read_loop_not_found(
    fixture: BoundaryFixture,
    source: ProgramContext | None,
    require_loop: bool = True,
) -> dict[str, str] | None:
    """The record-not-found reply ({field: "23"}) a keyed READ mock gives
    once its rows run out, when a READ of that file with an INVALID KEY
    clause the splice re-runs (`lift_clause_bodies`) runs in a loop -- a
    PERFORM UNTIL or a GO TO back to its own paragraph or an earlier one --
    and has no AT END clause. Such a loop ends only on INVALID KEY (NIST
    IX102A: `IF COUNT = 0 ... GO TO READ-TEST-F2-05` around `READ ...
    INVALID KEY GO TO ...-1`); a mock answering "00" forever hung the
    run. The splice takes the clause on UT-MOCK-STATUS's "2x", and the
    file's FILE STATUS field gets the same code. None otherwise.

    With `require_loop` False the loop is not needed: a mock with no rows
    (the "empty input" scenario) stands for a file with no records, and a
    keyed READ of it can only
    fail with "23" -- answering "00" ran the NOT INVALID KEY path on
    whatever the record area held (issue #415). INVALID KEY is coded only
    on a keyed READ (random access, or `READ ... KEY IS`), so the clause
    is what marks the READ as keyed."""
    if source is None or source.surface is None:
        return None
    from mockymock.analysis.mock_surface import analyze_file_status_fields

    key = fixture.key.upper()
    # A split file's fixture is keyed `<file> <form>` (issue #417).
    split = split_read_files(source.surface)
    looped = keyed = False
    for site in source.surface.boundary_sites:
        if site.category is not MockCategory.READ or not site.keys:
            continue
        if _read_mock_key(site, split) != key:
            continue
        statement = site.statement
        if getattr(statement, "at_end_clause", None):
            return None
        if not getattr(statement, "invalid_key_clause", None):
            continue
        if _clause_goes_back(site, source.program):
            return None
        lifted = lift_clause_bodies(statement, source.lines)
        if not lifted or not any(c.attr == "invalid_key_clause" for c in lifted):
            continue
        keyed = True
        # A loop with an UNTIL (not `PERFORM n TIMES`, which ends by its
        # count), or a GO TO loop.
        if loop_guard_words(site, source.guards) or _in_goto_loop(site, source.program):
            looped = True
    if not (looped if require_loop else keyed):
        return None
    reply = {OUTCOME_FIELD: "23"}
    status = (
        analyze_file_status_fields(source.program).get(key)
        if source.program is not None
        else None
    )
    if status:
        reply[status] = "23"
    return reply


def _paragraph_order(
    site: BoundarySite, program: CobolProgram | None
) -> tuple[list, set[str]] | None:
    """(the paragraphs from `site`'s own on, in source order; the names of
    that paragraph and every one before it), or None when unknown."""
    name = (site.paragraph_name or "").upper()
    procedure = program.get_division("PROCEDURE") if program is not None else None
    if not name or procedure is None:
        return None
    paragraphs = sorted(
        _all_paragraphs(procedure),
        key=lambda p: getattr(getattr(p, "location", None), "line", 0) or 0,
    )
    names = [str(getattr(p, "paragraph_name", "") or "").upper() for p in paragraphs]
    if name not in names:
        return None
    start = names.index(name)
    return paragraphs[start:], set(names[: start + 1])


def _goes_back(statements: list, earlier: set[str]) -> bool:
    """Whether `statements` (nested bodies included) GO TO one of
    `earlier`."""
    from cobolparser.models.statements.control import GoStatement

    from mockymock.analysis.loops import walk_statements

    return any(
        isinstance(statement, GoStatement)
        and any(str(t or "").upper() in earlier for t in statement.target_paragraphs)
        for statement in walk_statements(statements)
    )


def _in_goto_loop(site: BoundarySite, program: CobolProgram | None) -> bool:
    """Whether `site`'s paragraph, or one after it, holds a GO TO back to
    that paragraph or one before it (source order): the `GO TO READ-TEST`
    loop of programs written without PERFORM UNTIL."""
    order = _paragraph_order(site, program)
    if order is None:
        return False
    following, earlier = order
    return any(_goes_back(list(p.statements), earlier) for p in following)


def _clause_goes_back(site: BoundarySite, program: CobolProgram | None) -> bool:
    """Whether `site`'s INVALID KEY clause GOes TO its own paragraph or an
    earlier one: a retry, which a not-found reply would repeat forever
    (NIST RL107A: `READ RL-FR7 INVALID KEY ... GO TO TEST-13` inside
    TEST-13)."""
    order = _paragraph_order(site, program)
    if order is None:
        return True
    clause = list(getattr(site.statement, "invalid_key_clause", None) or [])
    return _goes_back(clause, order[1])


def _read_body(
    fixture: BoundaryFixture,
    registry: TallyRegistry,
    category: MockCategory,
    site: BoundarySite,
    source: ProgramContext | None = None,
) -> list[str]:
    """READ's multi-row sequence: a tally-branching `EVALUATE TRUE` chain,
    one `WHEN <tally> = N` per generated row, `WHEN OTHER` moving
    `fixture.terminal`'s status code(s) once the sequence is exhausted (a
    file-status field is always alphanumeric, so its terminal code is
    always quoted -- unlike SQL's SQLCODE), plus whatever of the original
    `AT END` clause's own statements `_replicated_at_end_statements` can safely
    replicate -- the program's own EOF-flag idiom, not just its FILE
    STATUS field, since the splicer deletes the real clause entirely. See
    `_read_exhaustion_lines` for the exhaustion content itself.

    Whether an exhaustion branch is needed at all is gated on the source
    `AT END` clause existing (`at_end` below), deliberately NOT on
    `fixture.terminal` alone: a file with no `FILE STATUS` clause (e.g.
    INVUPDT's `INV-FILE`) has `fixture.terminal is None` -- correctly, per
    `_resolve_status_field`'s "exact by construction, or absent" rule on
    the cobol-parser side -- even though the program's own `AT END`
    handler still fires and still needs replicating; gating on
    `fixture.terminal` alone silently produced an `EVALUATE` with no
    `WHEN OTHER` at all for exactly that program (found via a real Docker
    run, not by lint, which cannot see a splice-time no-op), leaving the
    application's own loop-guard flag untouched forever -- an infinite
    loop. When `at_end` is non-empty but nothing in it was safely
    replicable (an identifier-sourced MOVE, a `SET ... UP BY`, an IF,
    ...), a comment flags the gap rather than silently emitting nothing.

    An EMPTY `sequence` (fix round 1, unify-with-data Task 4: `--rows 0`
    on the self-generating path, or a bundle's own "empty input" scenario
    family on `--fixtures`) is handled first, unconditionally: every READ
    call is immediately exhausted (there is no row-selecting branch to
    choose between at all), so the exhaustion content fires directly with
    no `EVALUATE`/tally lookup -- NOT the empty body a naive `if not
    sequence: return []` would have produced, which would drop the
    program's own EOF-flag idiom exactly like an unmocked `AT END` clause
    would and hang its loop forever, the same failure mode `WHEN OTHER`
    exists to prevent for the ordinary multi-row case.

    Mirrors `ROWS` sugar's own internal `EVALUATE`/`WHEN tally = N` shape
    (see .okf/splicer.md) for consistency. `MOCK READ ... ROWS
    ( ... ) TERMINAL ( ... )` is real hand-authoring grammar as of the
    unify-with-data Task 2 DSL/splicer work (`dsl/parser.py`,
    `splicer/injector.build_rows_block`/`build_site_dispatch`) -- but this
    bundle-driven scaffold still emits its own hand-rolled `EVALUATE`
    here rather than that sugar; wiring the scaffold to emit `ROWS`
    syntax for READ instead of duplicating its shape is future work (see
    docs/2026-07-31-csv-sourced-rows-design.md, which also still proposes
    the separate, unimplemented `ROWS FROM CSV` row-source extension for
    both `READ` and `SQL`)."""
    sequence = fixture.sequence
    status_lines = [
        f'MOVE "{code}" TO {name}'
        for name, code in fixture.status.items()
        if code not in _DEFAULT_SUCCESS_CODES
    ]
    if any(
        not code.startswith("0")
        for code in fixture.status.values()
        if code not in _DEFAULT_SUCCESS_CODES
    ):
        # A failed READ (23 record not found, 35, 46, 9x ...) returns no
        # record: the status alone, which the splice turns into the
        # statement's INVALID KEY clause (or none) like the real READ.
        return status_lines
    replicated, at_end, lifted = _at_end_handling(fixture, site, source)
    needs_exhaustion_branch = bool(fixture.terminal) or bool(at_end)
    if not needs_exhaustion_branch and len(sequence) != 1:
        # In a loop, or with no rows at all (issue #415): the read after the
        # last row finds no record.
        not_found = _keyed_read_loop_not_found(
            fixture, source, require_loop=bool(sequence)
        )
        if not_found:
            # The rows are the records the file holds: the read after the
            # last finds none, as the real keyed READ would.
            fixture = replace(fixture, terminal=not_found)
            needs_exhaustion_branch = True

    if not sequence:
        return _read_exhaustion_lines(fixture, replicated, at_end, lifted)

    if len(sequence) == 1 and not needs_exhaustion_branch:
        # A successful status other than 00 (02: another record has this
        # alternate key; 04: length mismatch) comes with the record.
        return _row_move_lines(sequence[0], fixture, source) + status_lines

    row_lines = [
        _row_move_lines(row, fixture, source) + status_lines for row in sequence
    ]
    if not needs_exhaustion_branch and not any(row_lines):
        # Rows that move nothing (a keyed READ of a record holding only its
        # key, NIST IX301M): every call does the same nothing.
        return []
    tally = registry.name(category, fixture.key)
    body = ["EVALUATE TRUE"]
    for index, lines in enumerate(row_lines, start=1):
        body.append(f"    WHEN {tally} = {index}")
        # A WHEN with no statement joins the next WHEN's condition, and a
        # last one before END-EVALUATE fails cobc 3.1 ("invalid
        # expression", NIST IX301M).
        body.extend(f"        {line}" for line in lines or ["CONTINUE"])
    if needs_exhaustion_branch:
        body.append("    WHEN OTHER")
        body.extend(
            f"        {line}"
            for line in _read_exhaustion_lines(fixture, replicated, at_end, lifted)
        )
    body.append("END-EVALUATE")
    return body


def _merged_status_only_body(fixtures: list[BoundaryFixture]) -> list[str]:
    """Merge STATUS_ONLY bodies across every fixture sharing one physical
    site (see `_bundle_directive_for_group`), so an override on just one
    of a multi-file OPEN/CLOSE's files (e.g. an "error status" scenario
    targeting only the input file) is not silently lost just because it
    wasn't the file whose key the single MOCK directive happened to use.

    `FILE-STATUS IS` sets the status field of the directive's own file
    (the first fixture's), so a failure of another file of the statement
    is a `MOVE` to that file's own field: `OPEN INPUT PARM-FILE CUST-KSDS`
    failing CUST-KSDS with 35 used to set PARM-FILE's status instead. For
    each field the first non-default code wins."""
    if not fixtures or fixtures[0].category == "SQL":
        for fixture in fixtures:
            sql_body = _status_only_body(fixture)
            if sql_body:
                return sql_body
        return []
    own_fields = {name.upper() for name in fixtures[0].status}
    codes: dict[str, str] = {}
    for fixture in fixtures:
        for name, code in fixture.status.items():
            if code not in _DEFAULT_SUCCESS_CODES:
                codes.setdefault(name, code)
    body: list[str] = []
    for name, code in codes.items():
        if name.upper() in own_fields:
            if not any(line.startswith("FILE-STATUS IS") for line in body):
                body.insert(0, f'FILE-STATUS IS "{code}"')
        else:
            body.append(f'MOVE "{code}" TO {name}')
    return body
