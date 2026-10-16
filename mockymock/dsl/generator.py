"""Scaffolds a starter .cut file from a MockSurface -- with or without a
cobol-parser fixture bundle.

**Without a bundle** (`bundle=None`): one TESTCASE per paragraph that has
at least one mockable boundary site; the TESTCASE mocks ALL of that
paragraph's mockable sites (deduped by key) -- a scaffold that mocked only
some of them would walk users straight into the refusal gate's UNMOCKED_*
checks (an unmocked CALL has nowhere to link, unmocked file I/O would hit
a nonexistent sandbox file, unmocked EXEC cannot compile, unmocked console
ACCEPT reads stdin). Placeholder bodies are minimal-but-runnable (MOVE 0
TO RETURN-CODE for calls, MOVE 0 TO SQLCODE for SQL, empty for file ops)
and are expected to be replaced with real mock behavior. Nested sites
count as mockable only when `annotate_nested_sites` gave them a validated
splice span; unspliceable nested sites are skipped here and reported by
the CLI's unsupported-boundaries listing instead. The scaffold only covers
each paragraph's OWN sites: boundaries reached transitively through
PERFORM still need their MOCK directives added by hand.

**With a bundle** (`mockymock generate --with-data`, Phase 8 of the
`gen-fixtures` program-scoped test-data initiative): one TESTCASE per
*scenario* instead of per paragraph, `PERFORM <scenario.entry>`, mock
bodies built from the scenario's own generated fixture data (a plain body
for a single-invocation boundary, a tally-branching `EVALUATE` for a
multi-row `READ` sequence, `ROWS (...)` sugar for a multi-row SQL cursor
fetch), and per-scenario `EXPECT`/`VERIFY`/`*> STUB EXPECT` lines from the
bundle's tier 1/2/3 expectations. See
docs/plans/2026-08-02-program-data-generation-implementation.md's Phase 8
and cobol-parser's docs/fixture-bundle-schema.md.

Every mockable site this program's own `mock_surface.analyze()` finds
gets a MOCK directive in every generated TESTCASE, one way or another:
real fixture data when the bundle supplied it, or a placeholder body
(reusing the ordinary bundle-less `_directive_for` logic) otherwise -- an
OUT-direction boundary the bundle only stubbed (a WRITE, a SQL
INSERT/UPDATE/DELETE: the program produces that value, so there's nothing
to mock with), or one the bundle doesn't mention at all (a genuine
key-set gap between the two independent walks, reported by
`_warn_on_key_mismatch` but not otherwise treated specially). Leaving a
reachable site unmocked would make `run`/`lint` refuse the generated
`.cut` outright with UNMOCKED_*, which is worse than a placeholder a
human can improve on. See `_bundle_mock_directives`.

Explicitly out of scope for v1 (see that plan's own Phase 8 section):
collapsing scenarios that differ only in field values on the same
mock/entry shape into one `TESTCASE ... USING PROVIDER` -- every scenario
gets its own TESTCASE, even near-duplicates.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field, replace

from mockymock.analysis.clause_bodies import (
    OUTCOME_FIELD,
    lift_clause_bodies,
    scan_words,
)
from mockymock.analysis.exact_counts import exact_count_scope
from mockymock.analysis.loops import (
    LoopGuard,
    loop_guard_words,
    loop_guards,
    looped_paragraphs_and_statements,
    site_in_loop,
)
from mockymock.analysis.mock_surface import (
    BoundarySite,
    MockSurface,
    _all_paragraphs,
)
from mockymock.dsl.fixture_bundle import (
    BoundaryFixture,
    Expectation,
    FieldSpec,
    FixtureBundle,
    Scenario,
)
from mockymock.dsl.model import (
    EXEC_CATEGORIES,
    FILE_OP_CATEGORIES,
    REPORT_WRITER_CATEGORIES,
    MockCategory,
    MockDirective,
    MockTestCase,
    MockTestSuite,
)
from mockymock.report.record_rewrite import (
    field_pictures,
    picture_for,
    render_expect_value,
)
from mockymock.splicer.naming import TallyRegistry
from mockymock.splicer.reset import _POINTER_USAGES

_PLACEHOLDER_BODIES: dict[MockCategory, list[str]] = {
    MockCategory.CALL: ["MOVE 0 TO RETURN-CODE"],
    MockCategory.DYNCALL: ["MOVE 0 TO RETURN-CODE"],
    MockCategory.SQL: ["MOVE 0 TO SQLCODE"],
}

#: Numeric-family FieldSpec categories (see cobol-parser's
#: docs/fixture-bundle-schema.md) render bare; everything else is quoted.
_NUMERIC_FIELD_CATEGORIES = frozenset({"numeric", "numeric-edited", "float"})

#: A status/terminal code equal to one of these means "success" -- nothing
#: to override, since OPEN/CLOSE/READ/etc.'s implicit default-success MOVE
#: (injector.build_site_dispatch) already covers it.
_DEFAULT_SUCCESS_CODES = frozenset({"00", "0"})

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


# --- Lifting a READ's own AT END imperative verbatim -------------------------


def _data_name_counts(program) -> dict[str, int]:
    from cobolparser.generators.data.layout_offsets import compute_program_data_items

    try:
        items = compute_program_data_items(program).get("items", [])
    except Exception:  # pragma: no cover - never break generate over this
        return {}
    counts: dict[str, int] = {}
    for item in items:
        name = str(item.get("name") or "").upper()
        if name and name != "FILLER":
            counts[name] = counts.get(name, 0) + 1
    return counts


def _layout_items(program) -> list[dict]:
    from cobolparser.generators.data.layout_offsets import compute_program_data_items

    try:
        return list(compute_program_data_items(program).get("items", []))
    except Exception:  # pragma: no cover - never break generate over this
        return []


def _select_access_modes(program) -> dict[str, str]:
    """Uppercased file name -> its SELECT's ACCESS MODE (uppercased, '' when
    the clause is omitted, which means SEQUENTIAL)."""
    environment = program.get_division("ENVIRONMENT") if program else None
    io_section = (
        environment.get_section_by_name("INPUT-OUTPUT") if environment else None
    )
    file_control = (
        io_section.get_paragraph_by_name("FILE-CONTROL")
        if io_section is not None and hasattr(io_section, "get_paragraph_by_name")
        else None
    )
    modes: dict[str, str] = {}
    for statement in getattr(file_control, "statements", None) or []:
        name = getattr(statement, "file_name", None)
        if name:
            modes[name.upper()] = (
                getattr(statement, "access_mode", None) or ""
            ).upper()
    return modes


def _status_driven_reads(
    program, surface: MockSurface, looped: tuple[set[str], set[int]]
) -> dict[str, tuple[str, bool]]:
    """`ProgramContext.status_read_eof`: every file whose READs end their
    loop through the FILE STATUS field alone. cobol-parser's bundle only
    gives a READ fixture a `terminal` when the statement has an `AT END`
    clause, so a `READ IN-FILE` with no clause, looped `UNTIL WS-FS =
    "10"`, got rows and no end-of-file branch: the implicit `MOVE "00"`
    reported success forever and the generated suite hung. Only plain
    sequential reads qualify -- a random/keyed READ (a `KEY IS` phrase, an
    `INVALID KEY` clause, or a READ without NEXT on a file not accessed
    sequentially) answers "23", not "10", once its rows run out."""
    from mockymock.analysis.mock_surface import analyze_file_status_fields

    status_fields = analyze_file_status_fields(program)
    access = _select_access_modes(program)
    plain: dict[str, bool] = {}
    excluded: set[str] = set()
    for site in surface.boundary_sites:
        if site.category is not MockCategory.READ or not site.keys:
            continue
        key = site.keys[0].upper()
        statement = site.statement
        sequential = (
            not getattr(statement, "at_end_clause", None)
            and not getattr(statement, "invalid_key_clause", None)
            and not getattr(statement, "key_name", None)
            and (
                (getattr(statement, "access_mode", None) or "").upper() == "NEXT"
                or access.get(key, "") in ("", "SEQUENTIAL")
            )
        )
        if not sequential or key not in status_fields:
            excluded.add(key)
            continue
        plain[key] = plain.get(key, False) or site_in_loop(site, looped)
    return {
        key: (status_fields[key], is_looped)
        for key, is_looped in plain.items()
        if key not in excluded
    }


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


def _qualified_reference(qualified_name: str, column: str, leaf: str) -> str:
    """`IN-REC.CUST-ID` -> `CUST-ID OF IN-REC`, keeping any subscript the
    bundle's column carries (`CUST-ID(2)` -> `CUST-ID OF IN-REC (2)`): the
    bundle's dotted form is not COBOL, and a bare leaf declared under two
    records is "ambiguous" to cobc (issue #144)."""
    parts = [part for part in qualified_name.split(".") if part]
    if len(parts) < 2:
        return column
    reference = " OF ".join(reversed(parts))
    subscript = column[len(leaf) :] if column.upper().startswith(leaf.upper()) else ""
    return f"{reference} {subscript.strip()}" if subscript.strip() else reference


@dataclass(frozen=True)
class ProgramContext:
    """Facts about the program under test that the scaffold needs beyond
    what `MockSurface` carries.

    `lines` is `run_static_checks`' normalized (free-form, comments blanked)
    line list; `statement_starts` is `splicer.source_map.collect_boundaries`'
    output for the same program -- the SAME two inputs the splicer's own
    `statement_span` uses to decide what text a boundary splice deletes.
    Using the splicer's own span source here is what makes a lifted `AT END`
    clause exactly the text that will be deleted, rather than a
    reconstruction that could drift from it.

    `capture_lines` holds the `CAPTURE ARG <n> INTO <target>` lines each
    CALL/DYNCALL boundary can safely be scaffolded with, precomputed by
    `build` so the body builders need only this one object -- see
    `_capture_lines_by_key`.

    Optional throughout: without it the scaffold falls back to the
    AST-driven `AT END` replication (and then the honest TODO comment), and
    emits no captures.
    """

    lines: list[str]
    statement_starts: list[int]
    capture_lines: dict[tuple[MockCategory, str], list[str]] = field(
        default_factory=dict
    )
    #: Name (uppercased, unqualified) -> PICTURE for every elementary data
    #: item (`report.record_rewrite.field_pictures`), so a bundle's
    #: `field_equals` value is rendered from the field's real type rather
    #: than from the text's shape -- see `_render_expectation`.
    pictures: dict[str, str] = field(default_factory=dict)
    #: `analysis.loops.looped_paragraphs_and_statements` for the program:
    #: which boundary sites can run more than once per PERFORM (a cursor
    #: FETCH in a `PERFORM ... UNTIL SQLCODE = 100` loop, issue #141).
    looped: tuple[set[str], set[int]] = field(default_factory=lambda: (set(), set()))
    #: The parsed program and the GO TO targets the splicer turns into EXIT
    #: PARAGRAPH -- the same two inputs `lint`'s reachability walk uses, so
    #: `reachable_from` agrees with what lint will check (issue #143).
    program: object = None
    neutralized_goto: frozenset[str] = frozenset()
    #: Name (uppercased, unqualified) -> how many data items declare it,
    #: so a bundle's `RECORD.FIELD` name is rendered as a bare leaf only
    #: when the leaf is unique (issue #144).
    name_counts: dict[str, int] = field(default_factory=dict)
    #: READ key (file name, uppercased) -> (its FILE STATUS field, whether
    #: any of its READ sites runs in a loop), for a file every READ of which
    #: is a plain sequential read with no AT END / INVALID KEY clause -- the
    #: `PERFORM UNTIL <status> = "10"` idiom. See `_status_read_eof`.
    status_read_eof: dict[str, tuple[str, bool]] = field(default_factory=dict)
    #: Every looping PERFORM with the data names its UNTIL reads, so a CALL
    #: whose loop waits on the CALL's own reply can be ended (issue #156).
    guards: list[LoopGuard] = field(default_factory=list)
    #: cobol-parser's flat data-item layout (`compute_program_data_items`),
    #: for the names under a CALL argument (a PCB's status field, an 88).
    data_items: list[dict] = field(default_factory=list)
    surface: MockSurface | None = None

    @classmethod
    def build(cls, program, lines: list[str], surface: MockSurface) -> ProgramContext:
        from mockymock.analysis.refusal import neutralized_goto_targets
        from mockymock.splicer.source_map import collect_boundaries, collect_scope_map

        return cls(
            lines=list(lines),
            statement_starts=collect_boundaries(program),
            capture_lines=_capture_lines_by_key(program, surface, lines),
            pictures=field_pictures(program),
            looped=looped_paragraphs_and_statements(program),
            program=program,
            neutralized_goto=neutralized_goto_targets(
                program, collect_scope_map(program, lines), lines
            ),
            name_counts=_data_name_counts(program),
            status_read_eof=_status_driven_reads(
                program, surface, looped_paragraphs_and_statements(program)
            ),
            guards=loop_guards(program),
            data_items=_layout_items(program),
            surface=surface,
        )

    def names_under(self, name: str) -> set[str]:
        """`name` plus every data item declared under it, condition names
        (88s) included, uppercased."""
        wanted = name.upper()
        names = {wanted}
        for item in self.data_items:
            parts = str(item.get("qualified_name") or "").upper().split(".")
            if wanted in parts[:-1]:
                names.add(parts[-1])
        return names

    def literal_value(self, name: str) -> str | None:
        """The alphanumeric VALUE literal `name` is declared with, read from
        the source text, or None."""
        pattern = re.compile(
            rf"(?<![A-Za-z0-9-]){re.escape(name)}(?![A-Za-z0-9-])[^.]*?"
            r"\bVALUE\s+(?:IS\s+)?([\"'])(.*?)\1",
            re.IGNORECASE,
        )
        for line in self.lines:
            if len(line) > 6 and line[6] in "*/":
                continue
            match = pattern.search(line)
            if match:
                return match.group(2)
        return None

    def references(self, name: str) -> bool:
        """True when `name` appears as a whole COBOL word in the program."""
        pattern = re.compile(
            rf"(?<![A-Za-z0-9-]){re.escape(name)}(?![A-Za-z0-9-])", re.IGNORECASE
        )
        return any(pattern.search(line) for line in self.lines)

    def is_unique_name(self, name: str) -> bool:
        """True unless `name` is known to be declared more than once. An
        empty map (no program, or a layout walk that failed) keeps the old
        behavior: every name is treated as unique."""
        return self.name_counts.get(name.upper(), 1) <= 1

    def reachable_from(self, entry: str) -> set[str] | None:
        """Paragraph/section names a `PERFORM entry` can execute, or None
        when that can't be established (no program, unknown entry, or a
        flow the reachability model itself refuses) -- callers then keep
        every site, as before."""
        if self.program is None:
            return None
        from mockymock.analysis.refusal._reachability import _reachable_paragraphs

        reached, reasons = _reachable_paragraphs(
            self.program, entry, neutralized_goto=self.neutralized_goto
        )
        if reasons or entry not in reached:
            return None
        return reached

    def exact_count_scope(
        self, entry: str, reachable: set[str]
    ) -> tuple[set[str], set[int]] | None:
        """`analysis.exact_counts.exact_count_scope` for `PERFORM entry`."""
        return exact_count_scope(
            self.program, entry, reachable, neutralized_goto=self.neutralized_goto
        )

    def captures_for(self, category: MockCategory, key: str) -> list[str]:
        return self.capture_lines.get((category, key), [])

    def statement_text(self, line: int) -> str | None:
        """The full source text of the statement starting at 1-based
        `line`, with its original line breaks preserved."""
        if line < 1 or line > len(self.lines):
            return None
        later = [start for start in self.statement_starts if start > line]
        end = (later[0] - 1) if later else len(self.lines)
        while end > line and not self.lines[end - 1].strip():
            end -= 1
        return "\n".join(self.lines[line - 1 : end])


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
    if not body:
        return []
    return [
        f"*> replicated verbatim from this program's own READ ... AT END "
        f"clause (line {site.line}) -- the splicer replaces the whole READ, "
        f"deleting it",
        *body,
    ]


def _capture_lines_by_key(
    program, surface: MockSurface, lines: list[str] | None = None
) -> dict[tuple[MockCategory, str], list[str]]:
    """`CAPTURE ARG <n> INTO <target>` lines for every CALL/DYNCALL boundary
    whose arguments mockymock can safely synthesize storage for.

    Asserting on what a mocked `CALL` actually RECEIVED is usually the most
    interesting assertion in a test, and `CAPTURE ARG` has supported it
    since 2026-08-11 -- but only as hand-authoring, because the target had
    to be an existing data item of a compatible type. `splicer.captures`
    now declares a `UT-CAP-`-prefixed target on demand, which is what makes
    scaffolding one possible at all.

    Two things are checked here so the generated `.cut` never trips the
    `UNRESOLVED_CAPTURE_TARGET` refusal that backs that synthesis -- a
    scaffold that emits a refusable file is worse than one that emits less:

    1. Every physical site sharing this (category, key) must name the SAME
       data item at that argument position. One synthesized field cannot
       mirror two layouts, and picking either would make the capture wrong
       at one of the sites.
    2. That item's layout must be mirrorable at all (not a table, not a
       PICTURE-less COMP-1/POINTER item, not a group holding non-DISPLAY
       data whose bytes an alphanumeric copy would render unreadable).

    A literal argument (`USING "ABC"`, `BY CONTENT 42`) is never captured:
    its value is fixed by the source, so the capture asserts nothing. It is
    told apart from a data-name by `splicer.captures._site_argument` -- the
    splicer's own resolver, given the normalized `lines` -- because
    cobolparser reports `"ABC"` by its unquoted value. Comparing bare names
    instead scaffolded a capture of the literal "ABC" whenever an item ABC
    existed, and, where one site passed the literal and another the item,
    a capture the splicer then refused as UNRESOLVED_CAPTURE_TARGET.

    An argument failing any check is simply not captured; the rest of
    that boundary's arguments still are.
    """
    from mockymock.splicer.captures import (
        _declaration_for,
        _site_argument,
        capture_target_name,
    )
    from mockymock.splicer.source_map import collect_boundaries

    data_items = _capture_data_items(program)
    boundaries = collect_boundaries(program) if lines is not None else []
    by_key: dict[tuple[MockCategory, str], list[BoundarySite]] = {}
    for site in surface.boundary_sites:
        if site.category not in (MockCategory.CALL, MockCategory.DYNCALL):
            continue
        for key in site.keys:
            by_key.setdefault((site.category, key), []).append(site)

    result: dict[tuple[MockCategory, str], list[str]] = {}
    # Two keys can sanitize to the same target body (they differ only in
    # punctuation, or only past the length cap). Sharing one field between
    # two different CALLs would silently make each capture assert on
    # whichever fired last, so names are made unique here the same way
    # `TallyRegistry` makes tally names unique.
    taken: set[str] = set(data_items)
    for (category, key), sites in sorted(
        by_key.items(), key=lambda item: (item[0][0].value, item[0][1])
    ):
        argument_lists = [
            getattr(site.statement, "using_parameters", None) or [] for site in sites
        ]
        if not argument_lists or not argument_lists[0]:
            continue
        capture_lines: list[str] = []
        for index in range(1, len(argument_lists[0]) + 1):
            if any(len(arguments) < index for arguments in argument_lists):
                continue  # a site with fewer arguments: CAPTURE_ARG_OUT_OF_RANGE
            resolved = {
                _site_argument(site, index, lines, boundaries) for site in sites
            }
            # One argument across every site, not one site: two CALLs
            # passing the same item agree. (Comparing the set's size against
            # the site count dropped every capture of any key with 2+ sites.)
            if len(resolved) != 1:
                continue  # disagreement between sites
            argument = next(iter(resolved))
            if argument is None or argument[0] != "item":
                continue  # a literal: nothing to observe
            source_name = argument[1]
            item = data_items.get(source_name)
            if item is None:
                continue
            target = capture_target_name(category, key, index)
            if _declaration_for(target, item) is None:
                continue
            if target in taken:
                suffix = 2
                while f"{target}-{suffix}" in taken:
                    suffix += 1
                target = f"{target}-{suffix}"
            taken.add(target)
            capture_lines.append(f"CAPTURE ARG {index} INTO {target}")
        if capture_lines:
            result[(category, key)] = capture_lines
    return result


def _capture_data_items(program) -> dict[str, dict]:
    from mockymock.splicer.captures import _data_item_index

    try:
        return _data_item_index(program)
    except Exception:  # pragma: no cover - a layout walk must never break generate
        return {}


def _capture_stub_lines(targets: list[str]) -> list[str]:
    """One `*> STUB EXPECT` comment per scaffolded capture, so the value a
    capture makes visible does not sit in the file with nothing pointing at
    it. `mockymock run --record-expectations` promotes these to real
    `EXPECT` lines from an actual run, which is exactly the workflow that
    makes a captured argument useful without the author having to guess the
    value up front."""
    return [
        f"*> STUB EXPECT {target} -- the value the program actually passed "
        f"to this CALL"
        for target in targets
    ]


def _capture_targets(lines: list[str]) -> list[str]:
    """The targets of the `CAPTURE ARG` lines in an already-built mock body,
    in order. Read back off the emitted text rather than recomputed, so the
    stub comments can never name a capture the body did not actually
    declare."""
    targets: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.upper().startswith("CAPTURE ARG "):
            targets.append(stripped.rsplit(" ", 1)[-1])
    return targets


def _verification_comment_lines(scenario: Scenario) -> list[str]:
    """A `*>` note when cobol-parser could not verify that this scenario's
    own generated data actually reaches the branch it is named for.

    A scenario name is a claim; before the bundle carried a verdict, the
    only way to check it was to run the case under `--trace`. Surfacing an
    `unverified` verdict here means a reader of the generated `.cut` sees
    the caveat next to the TESTCASE it applies to, instead of trusting a
    label. Nothing is emitted for a verified scenario -- a note on every
    case would be noise, and would train people to skip these.
    """
    verification = scenario.verification or {}
    if verification.get("status") != "unverified":
        return []
    reasons = [
        f"{entry.get('field')}: {entry.get('detail')}"
        for entry in verification.get("fields") or []
        if entry.get("status") != "satisfied"
    ] + list(verification.get("gaps") or [])
    lines = [
        "*> UNVERIFIED: this scenario's generated data was not confirmed to "
        "reach the branch it is named for:"
    ]
    lines.extend(f"*>   - {reason}" for reason in reasons)
    return lines


def _quote_safe(name: str) -> str:
    """The .cut grammar cannot represent a double quote inside a quoted
    name (`"[^"]*"` -- no escape syntax), so a name containing one would
    make the emitted scaffold unparseable. Substitute single quotes."""
    return name.replace('"', "'")


def scaffold_cut(
    suite_name: str,
    surface: MockSurface,
    bundle: FixtureBundle | None = None,
    placeholder_keys: frozenset[tuple[str, str]] = frozenset(),
    source: ProgramContext | None = None,
) -> str:
    """Generate a starter .cut file. Without a bundle: one TESTCASE per
    paragraph with placeholder mock bodies (today's original behavior).
    With a bundle: one TESTCASE per scenario, mock bodies built from the
    bundle's own generated fixture data. See the module docstring.

    `placeholder_keys` (`mockymock generate --placeholder CATEGORY:KEY`,
    bundle-side string category paired with the fixture's own key,
    e.g. `("READ", "ORDER-FILE")`) only has an effect with a bundle --
    without one, every site already gets a placeholder body, so there is
    nothing left to downgrade. See `_bundle_directive_for`.

    `source` (the normalized program text plus its statement-start lines)
    lets a generated `MOCK READ` lift the program's own `AT END` imperative
    verbatim into its exhaustion branch instead of emitting a TODO comment
    -- see `_lifted_at_end_lines`. Optional: without it the scaffold falls
    back to the AST-driven replication and then to that TODO."""
    if bundle is None:
        return _scaffold_placeholder(suite_name, surface, source)
    return _scaffold_with_bundle(suite_name, surface, bundle, placeholder_keys, source)


def directive_snippet(site: BoundarySite, surface: MockSurface) -> str | None:
    """Render the exact `.cut` text a bundle-less scaffold would emit for
    this one boundary site: a `MOCK ... END-MOCK` block, 4-space-indented
    header/footer and 8-space-indented body, matching
    `_scaffold_placeholder`'s own rendering exactly. `None` for a site
    `_directive_for` itself declines to render (category=None, an
    unrepresentable key/prefix, an unparsed CALL literal, ...) -- those
    have no mechanical fix to suggest.

    This is the one place both the refusal gate
    (`RefusalReason.suggested_fix`, see docs/2026-09-15-actionable-
    refusals-and-fill-design.md) and `generate --fill` get their fix
    text from -- neither re-renders a directive independently, so the
    two can never drift apart, and a scaffold produced by plain
    `generate` always matches what a refusal message would have
    suggested for the same site. That includes declining the sites the
    scaffold itself skips (a nested site with no recorded span, a
    top-level site the splicer cannot rewrite): suggesting a MOCK the
    next lint would refuse as UNSUPPORTED_NESTED_MOCK_TARGET /
    UNSPLICEABLE is not a fix."""
    if site.category is None:
        return None
    if site.nested and site.span is None:
        return None
    if not site.nested and site.unspliceable_reason:
        return None
    rendered = _directive_for(site, surface)
    if rendered is None:
        return None
    header, body = rendered
    lines = [f"    {header}"]
    lines.extend(f"        {body_line}" for body_line in body)
    lines.append("    END-MOCK")
    return "\n".join(lines)


# --- placeholder scaffold (no bundle) ----------------------------------------


def _scaffold_placeholder(
    suite_name: str, surface: MockSurface, context: ProgramContext | None = None
) -> str:
    sites_by_paragraph: dict[str, list[BoundarySite]] = {}
    unnamed: list[BoundarySite] = []
    for site in surface.boundary_sites:
        if site.category is None or (site.nested and site.span is None):
            continue
        if not site.paragraph_name:
            # A statement between `PROCEDURE DIVISION.` and the first
            # paragraph header belongs to no paragraph (cobolparser names
            # the holder ""), and a test case can only enter the program
            # through `PERFORM <paragraph>`. Scaffolding it emitted a bare
            # `PERFORM ` line, which the .cut parser rejects -- taking
            # every other generated test case in the file down with it.
            unnamed.append(site)
            continue
        sites_by_paragraph.setdefault(site.paragraph_name, []).append(site)

    lines = [f'TESTSUITE "{_quote_safe(suite_name)}"', ""]
    if unnamed:
        lines.append(
            "*> Not scaffolded: these boundaries sit before the first "
            "paragraph header,"
        )
        lines.append(
            "*> where no PERFORM can reach them. Move them into a named "
            "paragraph to test them."
        )
        lines.extend(
            f"*>   {label} at line {line}"
            for label, line in dict.fromkeys(
                (site.label, site.line) for site in unnamed
            )
        )
        lines.append("")
    for paragraph_name, own_sites in sites_by_paragraph.items():
        sites = _reachable_sites(paragraph_name, own_sites, sites_by_paragraph, context)
        directives = _directives_for(sites, surface, context)
        labels = ", ".join(dict.fromkeys(site.label for site in sites))
        lines.append(
            f'TESTCASE "{_quote_safe(f"{paragraph_name} boundaries: {labels}")}"'
        )
        captured: list[str] = []
        for directive_line, body in directives:
            lines.append(f"    {directive_line}")
            lines.extend(f"        {body_line}" for body_line in body)
            lines.append("    END-MOCK")
            captured.extend(_capture_targets(body))
        lines.append(f"    PERFORM {paragraph_name}")
        lines.extend(f"    {line}" for line in _capture_stub_lines(captured))
        lines.append("")
    return "\n".join(lines)


def _reachable_sites(
    entry: str,
    own_sites: list[BoundarySite],
    sites_by_paragraph: dict[str, list[BoundarySite]],
    context: ProgramContext | None,
) -> list[BoundarySite]:
    """Every boundary site a `PERFORM entry` can reach: the paragraph's own
    sites first, then those of every paragraph it reaches (PERFORM, GO TO,
    fall-through), in source order. A scaffold that mocked only the entry
    paragraph's own sites failed the very lint it has to pass whenever the
    paragraph PERFORMs another that touches a boundary (UNMOCKED_*; the
    enterprise corpus's DB2SP, whose 0000-MAIN PERFORMs the paragraph that
    opens its result-set cursor). Falls back to the own sites when
    reachability can't be established, as the bundle-driven scaffold does
    (issue #143)."""
    reachable = context.reachable_from(entry) if context is not None else None
    if reachable is None:
        return own_sites
    sites = list(own_sites)
    for paragraph_name, paragraph_sites in sites_by_paragraph.items():
        if paragraph_name != entry and paragraph_name in reachable:
            sites.extend(paragraph_sites)
    return sites


def _directives_for(
    sites: list[BoundarySite],
    surface: MockSurface,
    context: ProgramContext | None = None,
) -> list[tuple[str, list[str]]]:
    directives: list[tuple[str, list[str]]] = []
    seen: set[tuple[MockCategory | None, str]] = set()
    for site in sites:
        directive = _directive_for(site, surface, context)
        if directive is None:
            continue
        key_id = (site.category, directive[0])
        if key_id in seen:
            continue
        seen.add(key_id)
        directives.append(directive)
    return directives


def _with_captures(
    category: MockCategory,
    key: str,
    body: list[str],
    context: ProgramContext | None,
) -> list[str]:
    """Prepend this boundary's scaffolded `CAPTURE ARG` lines to a mock
    body. First, deliberately: `injector.build_site_dispatch` emits the
    capture MOVEs before the body's own statements so a capture always
    reflects what the real caller passed, and keeping the `.cut` in the
    same order means the file reads the way it executes."""
    if context is None:
        return body
    return context.captures_for(category, key) + body


def _placeholder_body_for(category: MockCategory, key: str) -> list[str]:
    """The body `_directive_for` gives `(category, key)` outside a fixture
    bundle: `_PLACEHOLDER_BODIES`'s entry (CALL/DYNCALL/SQL), or ACCEPT's
    own `MOVE SPACES TO <key>`, or empty for everything else (the file-op
    verbs, CICS, DLI). Factored out of `_directive_for` so the
    bundle-driven scaffold's `--placeholder` downgrade (`_bundle_directive_for`)
    can reuse the exact same body a bundle-less scaffold would have
    emitted for this site, rather than a second, driftable copy of this
    per-category logic."""
    if category is MockCategory.ACCEPT:
        return [f"MOVE SPACES TO {key}"]
    return list(_PLACEHOLDER_BODIES.get(category, []))


def _directive_for(
    site: BoundarySite, surface: MockSurface, context: ProgramContext | None = None
) -> tuple[str, list[str]] | None:
    category = site.category
    if category is None:
        # scaffold_cut filters these out already; guard for direct callers
        return None

    if category is MockCategory.CALL:
        if not site.keys:
            # a static CALL whose literal never parsed: emitting
            # `MOCK CALL ""` would be rejected at parse time (empty key),
            # so skip it like the file-op/ACCEPT branches do; run's
            # refusal gate will name the unmocked site.
            return None
        key = site.keys[0]
        if '"' in key:
            # The .cut grammar cannot represent a quote inside a quoted
            # key, and _quote_safe's substitution is no fix for a KEY --
            # the directive would silently stop matching its site. Skip
            # it like an unparsed key: run's refusal gate names the
            # unmocked site loudly (2026-08-12 audit Finding 20).
            return None
        keyword = "MQ" if site.is_mq else "CALL"
        body = _placeholder_body_for(category, key) + _call_loop_end_lines(
            site, context, None
        )
        return f'MOCK {keyword} "{key}"', _with_captures(category, key, body, context)

    if category is MockCategory.DYNCALL:
        # bare key = dynamic CALL through this identifier; quoting it would
        # turn the directive into a static-literal mock that never matches
        key = site.keys[0]
        return f"MOCK CALL {key}", _with_captures(
            category, key, _placeholder_body_for(category, key), context
        )

    if category in FILE_OP_CATEGORIES:
        if not site.keys:
            return None  # no usable key parsed; run's refusal gate will name it
        key = site.keys[0]
        return f"MOCK {category.value} {key}", _placeholder_body_for(category, key)

    if category is MockCategory.ACCEPT:
        if not site.keys:
            return None
        key = site.keys[0]
        return f"MOCK ACCEPT {key}", _placeholder_body_for(category, key)

    if category in REPORT_WRITER_CATEGORIES:
        # INITIATE/GENERATE/TERMINATE: bare report name, empty body (the
        # splice alone is the mock -- nothing flows back into the program).
        if not site.keys:
            return None
        key = site.keys[0]
        return f"MOCK {category.value} {key}", _placeholder_body_for(category, key)

    # SQL / CICS / DLI: shortest word-prefix of this site's normalized text
    # that is unique among the program's sites of the same category, so the
    # scaffold never generates an AMBIGUOUS_MOCK pair.
    prefix = _unique_prefix(site, surface)
    if '"' in prefix:
        # Same unrepresentable-quote skip as the CALL branch above: an
        # EXEC statement whose unique prefix runs into a string literal
        # containing a double quote cannot be written as a quoted key.
        return None
    body = _placeholder_body_for(category, prefix)
    if category is MockCategory.DLI:
        body = body + _dli_loop_end_lines(site, context, None)
    return f'MOCK {category.value} "{prefix}"', body


#: DL/I get-next calls and the DIBSTAT each returns once nothing is left:
#: GB (end of database) for GN/GHN, GE (no more under this parent) for the
#: within-parent forms.
_DLI_GET_NEXT_END = {"GN": "GB", "GHN": "GB", "GNP": "GE", "GHNP": "GE"}


def _dli_loop_end_lines(
    site: BoundarySite,
    context: ProgramContext | None,
    tally: str | None,
) -> list[str]:
    """A get-next DL/I call in a loop, in a program that tests DIBSTAT:
    an empty mock body leaves DIBSTAT blank ("found") on every call, so a
    `PERFORM UNTIL` scan never ends (EXECDLI, found with #145). Report the
    end status after the first call -- with a tally, so one segment is
    still returned -- or on the first call when no tally name is known."""
    if context is None or not context.references("DIBSTAT"):
        return []
    words = (site.match_text or "").split()
    end_status = _DLI_GET_NEXT_END.get(words[0].upper()) if words else None
    if end_status is None or not site_in_loop(site, context.looped):
        return []
    if tally is None:
        return [f'MOVE "{end_status}" TO DIBSTAT']
    return [
        f"IF {tally} > 1",
        f'    MOVE "{end_status}" TO DIBSTAT',
        "END-IF",
    ]


#: CALL-level DL/I interfaces whose USING list is (function, PCB, ...).
_DLI_CALL_INTERFACES = frozenset({"CBLTDLI", "CEETDLI"})

#: The PCB status a DL/I call reports once nothing more matches: GB (end of
#: database) for an unqualified get-next, GE (not found) for the rest.
_DLI_CALL_END = {
    "GU": "GE",
    "GHU": "GE",
    "GN": "GB",
    "GHN": "GB",
    "GNP": "GE",
    "GHNP": "GE",
}


def _call_end_reply(
    site: BoundarySite, context: ProgramContext
) -> tuple[tuple[tuple[str, str], ...], set[str]] | None:
    """The reply a real MQGET or DL/I get call gives once there is nothing
    left to return, as (value, target) MOVEs, plus the argument names that
    reply is written to -- or None when `site` is no such call.

    MQGET answers MQCC_FAILED (2) with MQRC_NO_MSG_AVAILABLE (2033) in its
    CompCode/Reason arguments (8th and 9th). A CBLTDLI/CEETDLI get call
    puts its status at bytes 11-12 of every DB PCB (after the 8-byte DBD
    name and 2-byte level), whatever the program named that field."""
    using = list(getattr(site.statement, "using_parameters", None) or [])
    names = [str(getattr(param, "name", "") or "") for param in using]
    key = site.keys[0].upper() if site.keys else ""
    if key == "MQGET":
        if len(names) < 9 or not names[7] or not names[8]:
            return None
        return (("2", names[7]), ("2033", names[8])), {names[7], names[8]}
    if key in _DLI_CALL_INTERFACES:
        if len(names) < 2 or not names[0] or not names[1]:
            return None
        function = context.literal_value(names[0]) or names[0]
        end_status = _DLI_CALL_END.get(function.strip().upper())
        if end_status is None:
            return None
        return ((f'"{end_status}"', f"{names[1]}(11:2)"),), {names[1]}
    return None


def _row_already_ends(
    body: list[str], site: BoundarySite, context: ProgramContext | None
) -> bool:
    """True when the fixture row itself MOVEs the end-of-data status (2033,
    or the PCB's GB/GE) into the reply field: the loop then ends on the
    first call and the bundle's own count stands."""
    if context is None:
        return False
    reply = _call_end_reply(site, context)
    if reply is None:
        return False
    value, _ = reply[0][-1]
    watched = set().union(*(context.names_under(name) for name in reply[1]))
    for line in body:
        match = re.match(r"MOVE\s+(.+?)\s+TO\s+(\S+)$", line)
        if match and match.group(2).upper() in watched:
            if match.group(1).strip('"').strip() == value.strip('"'):
                return True
    return False


def _call_loop_end_lines(
    site: BoundarySite,
    context: ProgramContext | None,
    tally: str | None,
) -> list[str]:
    """A looped MQGET or DL/I get CALL whose loop waits on the call's own
    reply (`PERFORM UNTIL WS-REASON = 2033`, `UNTIL PCB-STATUS = "GB"`):
    a mock that replays its row on every call never satisfies that guard,
    so the run spins until the executor timeout (issue #156). Report end of
    data after the first call -- with a tally, so the fixture row is still
    returned once -- the way a READ mock reports AT END after its rows.

    One MOCK directive answers every site of its key, so the reply is only
    synthesized when every site would get the same one; a key mixing, say,
    a GU and an ISRT through CBLTDLI gets a TODO comment instead."""
    if context is None or site.category is not MockCategory.CALL or not site.keys:
        return []
    sites = [
        other
        for other in (context.surface.boundary_sites if context.surface else [])
        if other.category is MockCategory.CALL and site.keys[0] in other.keys
    ] or [site]
    replies = [_call_end_reply(other, context) for other in sites]
    waits_on_reply = any(
        reply is not None
        and site_in_loop(other, context.looped)
        and loop_guard_words(other, context.guards)
        & set().union(*(context.names_under(name) for name in reply[1]))
        for other, reply in zip(sites, replies, strict=True)
    )
    if not waits_on_reply:
        return []
    if len({reply[0] if reply else None for reply in replies}) != 1:
        return [
            f"*> TODO: a loop waits on this CALL's reply, but its "
            f"{len(sites)} sites need different end-of-data replies -- "
            f"end the loop by hand (e.g. MOCK CALL ... ROWS ... TERMINAL), "
            f"or this mock never ends it"
        ]
    first = replies[0]
    assert first is not None  # one distinct reply, and some site has one
    moves = [f"MOVE {value} TO {target}" for value, target in first[0]]
    if tally is None:
        return moves
    return [f"IF {tally} > 1", *(f"    {move}" for move in moves), "END-IF"]


def _unique_prefix(site: BoundarySite, surface: MockSurface) -> str:
    words = (site.match_text or "").split()
    if not words:
        return ""
    others = [
        other.match_text or ""
        for other in surface.boundary_sites
        if other.category is site.category and other is not site
    ]
    for length in range(1, len(words) + 1):
        prefix = " ".join(words[:length])
        collisions = [o for o in others if o.startswith(prefix)]
        if not collisions:
            return prefix
    return " ".join(words)


# --- bundle-driven scaffold (mockymock generate --with-data) -----------------


def _directive_header(category: MockCategory, key: str, site: BoundarySite) -> str:
    """The `MOCK ...` opening line for `(category, key)`, in the exact
    syntax `site` (a matching mockymock BoundarySite) requires -- mirrors
    `_directive_for`'s header logic exactly, factored out so the
    bundle-driven path can reuse it without also inheriting the
    placeholder-body choice."""
    if category is MockCategory.CALL:
        keyword = "MQ" if site.is_mq else "CALL"
        return f'MOCK {keyword} "{key}"'
    if category is MockCategory.DYNCALL:
        return f"MOCK CALL {key}"
    if category in FILE_OP_CATEGORIES:
        return f"MOCK {category.value} {key}"
    if category is MockCategory.ACCEPT:
        return f"MOCK ACCEPT {key}"
    if category in REPORT_WRITER_CATEGORIES:
        return f"MOCK {category.value} {key}"
    return f'MOCK {category.value} "{key}"'  # SQL / CICS / DLI


def _mockymock_boundary_keys(
    surface: MockSurface,
) -> dict[tuple[MockCategory, str], BoundarySite]:
    """First-seen site per (category, key) among surface's mockable sites.

    A multi-file `OPEN`/`CLOSE` (`OPEN INPUT A OUTPUT B`) is one physical
    `BoundarySite` whose `.keys` tuple names *every* file on the
    statement -- registers one dict entry per key, all pointing at the
    same site, since cobol-parser's own `BoundaryInventoryAnalyzer`
    independently reports one `Boundary` per file name for exactly this
    shape (`_classify_file_op`), not one per statement. Every other
    category's `.keys` is always a single entry, so this loop is a no-op
    widening for them. SQL/CICS/DLI key on `_unique_prefix` instead, since
    they have no `.keys` at all (only free-form `match_text`)."""
    keys: dict[tuple[MockCategory, str], BoundarySite] = {}
    for site in surface.boundary_sites:
        if site.category is None or (site.nested and site.span is None):
            continue
        if site.category in EXEC_CATEGORIES:
            prefix = _unique_prefix(site, surface)
            if '"' in prefix:
                # Unrepresentable in the .cut grammar (see _directive_for's
                # quote skip) -- excluding it here makes the bundle path
                # degrade through the existing loud machinery: the key
                # shows up "only in the fixture bundle" in
                # _warn_on_key_mismatch and is left unmocked.
                continue
            pair = (site.category, prefix)
            if pair not in keys:
                keys[pair] = site
            continue
        for key in site.keys:
            if site.category is MockCategory.CALL and '"' in key:
                continue  # same unrepresentable-quote skip as above
            pair = (site.category, key)
            if pair not in keys:
                keys[pair] = site
    return keys


def _bundle_boundary_keys(bundle: FixtureBundle) -> set[tuple[str, str]]:
    """Every (category string, key) pair appearing in ANY scenario's
    fixtures, or as a boundary-level (`"CATEGORY:KEY"`-shaped ref)
    expectation, across the whole bundle -- the union mockymock's own key
    set is compared against (see `_warn_on_key_mismatch`).

    Boundary-level expectations matter here as much as fixtures do: an
    OUT-direction boundary (a WRITE, a SQL INSERT/UPDATE/DELETE) gets NO
    fixture at all (see fixture-bundle-schema.md), only a `kind="stub"`
    expectation -- that `ref` is the *only* place such a boundary's
    (category, key) appears in the bundle, so skipping stub refs here
    would misreport every OUT-direction boundary as a mismatch.
    """
    keys: set[tuple[str, str]] = set()
    for scenario in bundle.scenarios:
        for fixture in scenario.fixtures:
            keys.add((fixture.category, fixture.key))
        for expectation in scenario.expectations:
            if expectation.kind in ("call_count", "stub"):
                category_str, sep, key = expectation.ref.partition(":")
                if sep and _is_known_category(category_str):
                    keys.add((category_str, key))
    return keys


def _known_unmockable_keys(surface: MockSurface) -> set[tuple[str, str]]:
    """(category, key) pairs whose only sites are nested inside a clause
    body with no span -- the shape mockymock already reports as "not
    mockable" and `_mockymock_boundary_keys` skips. cobol-parser's bundle
    still lists them, so without this set every such key showed up as a
    "boundary key mismatch ... should not happen" (issue #164). A key with
    at least one mockable site is in mockymock's own key set and never
    reaches this filter.

    A non-interactive ACCEPT (`ACCEPT X FROM DATE YYYYMMDD`) is in the same
    position: mockymock records it as nothing to mock, while cobol-parser's
    bundle can still list it when a date-format qualifier follows the
    source (BATCHSEQ)."""
    keys: set[tuple[str, str]] = {
        (MockCategory.ACCEPT.value, accept.target)
        for accept in surface.non_interactive_accepts
    }
    for site in surface.boundary_sites:
        if site.category is None or not (site.nested and site.span is None):
            continue
        if site.category in EXEC_CATEGORIES:
            keys.add((site.category.value, _unique_prefix(site, surface)))
            continue
        for key in site.keys:
            keys.add((site.category.value, key))
    return keys


def _warn_on_key_mismatch(
    mockymock_keys: dict[tuple[MockCategory, str], BoundarySite],
    bundle_keys: set[tuple[str, str]],
    unmockable_keys: set[tuple[str, str]],
) -> None:
    """Loud, never-silent warning when the two independent boundary walks
    (mockymock's own `mock_surface.analyze()` and cobol-parser's bundle)
    disagree on the (category, key) set -- this mismatch is the
    integration's primary failure mode (see the Phase 8 plan's "the join"
    step). A mockymock-only key gets a placeholder mock body as usual (see
    `_bundle_directive_for`); a bundle-only key has nothing to attach a
    MOCK directive to at all and is simply not mocked -- its `EXPECT`/
    `VERIFY` lines are dropped too (`_render_expectation`), since emitting
    either without a matching MOCK directive would fail `mockymock lint`.
    """
    mockymock_set = {(category.value, key) for category, key in mockymock_keys}
    only_in_mockymock = mockymock_set - bundle_keys
    # A key mockymock already lists as "not mockable" is an expected gap,
    # not a disagreement between the two walks.
    only_in_bundle = bundle_keys - mockymock_set - unmockable_keys
    if not only_in_mockymock and not only_in_bundle:
        return
    print(
        "mockymock generate --with-data: WARNING: boundary key mismatch "
        "between this program's own boundary analysis and the fixture "
        "bundle. This should not happen for a program the two independent "
        "walks agree on (see this repo's own "
        "tests/unit/test_fixture_bundle_contract.py) -- mismatched "
        "keys are handled defensively, not silently: a mockymock-only key "
        "falls back to a placeholder mock body; a bundle-only key is left "
        "unmocked (its expectations are dropped rather than emitted "
        "without a matching MOCK directive, which mockymock lint would "
        "refuse).",
        file=sys.stderr,
    )
    if only_in_mockymock:
        print(
            "  only in this program's own boundary analysis (no bundle "
            "fixture/expectation) -- falls back to a placeholder body:",
            file=sys.stderr,
        )
        for category, key in sorted(only_in_mockymock):
            print(f"    {category} {key}", file=sys.stderr)
    if only_in_bundle:
        print(
            "  only in the fixture bundle (no matching boundary site in "
            "this program) -- left unmocked:",
            file=sys.stderr,
        )
        for category, key in sorted(only_in_bundle):
            print(f"    {category} {key}", file=sys.stderr)


def _first_paragraph(program) -> str | None:
    """The first named PROCEDURE DIVISION paragraph, by source line.

    The fallback entry for a scenario cobol-parser left without one: an IMS
    program opening with `ENTRY 'DLITCBL' USING ...` comes back with
    `entry=''` because the ENTRY statement sits in an unnamed leading
    paragraph (issue #150)."""
    procedure = program.get_division("PROCEDURE") if program is not None else None
    if procedure is None:
        return None
    named = [
        paragraph
        for paragraph in _all_paragraphs(procedure)
        if getattr(paragraph, "paragraph_name", "")
    ]
    if not named:
        return None
    first = min(
        named,
        key=lambda paragraph: getattr(getattr(paragraph, "location", None), "line", 0),
    )
    return str(first.paragraph_name)


def _build_shadow_tally_registry(
    bundle: FixtureBundle,
    mockymock_keys: dict[tuple[MockCategory, str], BoundarySite],
    fallback_entry: str | None = None,
) -> TallyRegistry:
    """A `TallyRegistry` built over every (category, key) that will
    actually get a MOCK directive in the generated file, in the same
    first-appearance order the real, fully-parsed suite will eventually
    present them in -- so a hand-rolled tally-branching mock body (see
    `_read_body`) can reference the *exact* `UT-...-TALLY` field name the
    real splice pipeline will independently compute, without this
    generator needing its own parsed `MockTestSuite` to run a real
    registry over (the .cut text doesn't exist yet -- this IS how it gets
    built)."""
    case = MockTestCase(name="_shadow", perform_target="_SHADOW")
    seen: set[tuple[MockCategory, str]] = set()
    for scenario in bundle.scenarios:
        if not (scenario.entry or fallback_entry):
            continue
        for fixture in scenario.fixtures:
            try:
                category = MockCategory(fixture.category)
            except ValueError:
                continue
            pair = (category, fixture.key)
            if pair in mockymock_keys and pair not in seen:
                seen.add(pair)
                case.mocks.append(MockDirective(category, fixture.key))
    # Then the placeholder-mocked keys, in the order their directives are
    # written: a looped DL/I get-next placeholder body needs its tally too.
    for pair in mockymock_keys:
        if pair not in seen:
            seen.add(pair)
            case.mocks.append(MockDirective(*pair))
    suite = MockTestSuite(name="_shadow", test_cases=[case])
    return TallyRegistry(suite)


def _bundle_rendered_value(raw_value: str, field_category: str) -> str:
    """Bare for a numeric-family FieldSpec category (see cobol-parser's
    fixture-bundle-schema.md), quoted (with embedded `"` doubled,
    mirroring driver._display_text's escaping) otherwise. Unlike
    `report.record_rewrite.render_expect_value`, this decides from the
    FieldSpec's own resolved category -- exact, not a text-shape guess --
    since a bundle row always carries one."""
    if field_category in _NUMERIC_FIELD_CATEGORIES:
        return raw_value
    escaped = raw_value.replace('"', '""')
    return f'"{escaped}"'


def _row_target(spec: FieldSpec, source: ProgramContext | None) -> str:
    if source is None or source.is_unique_name(spec.name):
        return spec.column
    return _qualified_reference(spec.qualified_name, spec.column, spec.name)


# A mock body cannot MOVE a generated value into a POINTER-family item
# (it takes only SET, and NULL is its only data-free value) or an INDEX
# item (its content is implementation-defined). cobol-parser's bundle lays
# them out as numeric fields holding "0", and `MOVE 0 TO <pointer>` is a
# compile error ("invalid MOVE statement").
def _row_move_line(row: dict[str, str], spec: FieldSpec, target: str) -> str | None:
    usage = (spec.usage or "").upper()
    if usage in _POINTER_USAGES:
        return f"SET {target} TO NULL"
    if usage == "INDEX":
        return None
    return f"MOVE {_bundle_rendered_value(row.get(spec.column, ''), spec.category)} TO {target}"


def _row_move_lines(
    row: dict[str, str],
    fixture: BoundaryFixture,
    source: ProgramContext | None = None,
) -> list[str]:
    lines = (
        _row_move_line(row, spec, _row_target(spec, source)) for spec in fixture.layout
    )
    return [line for line in lines if line is not None]


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


def _sql_status_lines(fixture: BoundaryFixture) -> list[str]:
    lines = [f"MOVE {code} TO {name}" for name, code in fixture.status.items()]
    if not any(name.upper() == "SQLCODE" for name in fixture.status):
        lines.append("MOVE 0 TO SQLCODE")
    return lines


def _single_row_body(
    fixture: BoundaryFixture, source: ProgramContext | None = None
) -> list[str]:
    """ACCEPT / CALL / DYNCALL / CICS / DLI (always single-invocation), and
    SQL's own single-row/status-override fallback (see `_sql_wants_rows`).
    MOVEs every field the fixture generated, then -- SQL only -- an
    explicit status MOVE (SQL has no implicit default the way file-op
    categories do: every existing hand-written SQL mock in this codebase
    sets SQLCODE itself, always)."""
    body: list[str] = []
    if fixture.sequence:
        body.extend(_row_move_lines(fixture.sequence[0], fixture, source))
    if fixture.category == "SQL":
        body.extend(_sql_status_lines(fixture))
        return body
    for field_name, code in fixture.status.items():
        body.append(f'MOVE "{code}" TO {field_name}')
    return body


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
    if at_end and source is not None and not site.nested:
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
    replicated, at_end, lifted = _at_end_handling(fixture, site, source)
    needs_exhaustion_branch = bool(fixture.terminal) or bool(at_end)

    if not sequence:
        return _read_exhaustion_lines(fixture, replicated, at_end, lifted)

    if len(sequence) == 1 and not needs_exhaustion_branch:
        return _row_move_lines(sequence[0], fixture, source)

    tally = registry.name(category, fixture.key)
    body = ["EVALUATE TRUE"]
    for index, row in enumerate(sequence, start=1):
        body.append(f"    WHEN {tally} = {index}")
        body.extend(f"        {line}" for line in _row_move_lines(row, fixture, source))
    if needs_exhaustion_branch:
        body.append("    WHEN OTHER")
        body.extend(
            f"        {line}"
            for line in _read_exhaustion_lines(fixture, replicated, at_end, lifted)
        )
    body.append("END-EVALUATE")
    return body


def _is_looped_fetch(
    fixture: BoundaryFixture, site: BoundarySite, source: ProgramContext | None
) -> bool:
    """A cursor FETCH that runs inside a looping PERFORM (issue #141). Its
    mock must report SQLCODE 100 once the generated rows run out -- a
    single-row body reporting success on every call never ends the loop
    -- and it is called once more than it has rows: the exhausting call.
    Other SQL in a loop (a per-record SELECT INTO) is left alone: making
    its second call "not found" would change what the program does."""
    if source is None or not fixture.sequence:
        return False
    if not fixture.key.upper().startswith("FETCH"):
        return False
    return site_in_loop(site, source.looped)


def _sql_wants_rows(fixture: BoundaryFixture, looped_fetch: bool = False) -> bool:
    """`ROWS (...)` sugar hardcodes SQLCODE 0-on-match/100-on-exhaustion --
    not in `splicer/injector.build_rows_block` itself (generalized to a
    `row_suffix_moves`/`exhausted_moves` parameter pair so it can also
    drive `MOCK READ ... ROWS`), but at its SQL call site inside
    `splicer/injector.build_site_dispatch`, which passes the literal
    `["MOVE 0 TO SQLCODE"]`/`["MOVE 100 TO SQLCODE"]` -- it cannot express
    an error-status override, so a scenario pinning one (an "error status"
    fixed-family scenario, or a branch witness on SQLCODE) must fall back
    to a plain body with an explicit MOVE instead."""
    return (len(fixture.sequence) > 1 or looped_fetch) and all(
        code in _DEFAULT_SUCCESS_CODES for code in fixture.status.values()
    )


#: The exhausted-branch SQLCODE `splicer/injector.py`'s own
#: `build_rows_block` call site hardcodes for a `MOCK SQL ... ROWS` mock
#: (DB2's real "not found" code, `exhausted_moves=["MOVE 100 TO
#: SQLCODE"]`) -- mirrored here, not derived from any fixture data (there
#: is none once a cursor is exhausted), so a `--placeholder` downgrade of
#: a fixture that would have used ROWS sugar (`_sql_wants_rows`) replicates
#: the SAME termination signal instead of silently reverting to permanent
#: success (`_placeholder_body_for`'s ordinary `MOVE 0 TO SQLCODE`) --
#: see `_bundle_directive_for`'s own downgrade branch. A cursor
#: FETCH loop keyed on `PERFORM UNTIL SQLCODE = 100` would otherwise never
#: terminate, the SQL analogue of the READ infinite-loop hazard
#: `_read_exhaustion_lines` closes (fix round 1, unify-with-data Task 4).
_SQL_ROWS_EXHAUSTED_BODY = ["MOVE 100 TO SQLCODE"]


def _sql_rows_directive(
    category: MockCategory, key: str, fixture: BoundaryFixture
) -> list[str]:
    lines = [f'MOCK {category.value} "{key}" ROWS']
    for row in fixture.sequence:
        pairs = ", ".join(
            f"{spec.column} = {_bundle_rendered_value(row.get(spec.column, ''), spec.category)}"
            for spec in fixture.layout
        )
        lines.append(f"    ( {pairs} )")
    lines.append("END-MOCK")
    return lines


@dataclass
class CallCountOverride:
    """A `--placeholder`-downgraded fixture's corrected tier-1 `call_count`
    expectation (fix round 2, unify-with-data Task 4): the runnable-by-
    construction invariant covers the WHOLE generated `.cut`, assertions
    included -- a downgrade that changes what a mock's body actually does
    at runtime can also change how many times the program actually
    reaches it (see `_bundle_directive_for`'s own downgrade branch: a
    downgraded READ signals EOF on its very first call, so a
    `PERFORM ... UNTIL <eof-flag>` loop calls it exactly once, not the
    bundle's original un-downgraded sequence length). Rendering the
    bundle's original count unchanged would pin a `VERIFY ... WAS CALLED
    N TIMES` the generated file cannot itself satisfy.

    `count`: the value implied by the downgraded body's OWN construction --
    the body guarantees this boundary signals end-of-data on call 1, so
    `count=1` is exact ASSUMING the program stops reading/fetching this
    boundary once that end-of-data signal fires, which is the same
    assumption the rest of this engine already makes about every
    program-flow-driven call count (it isn't independently verified
    against the PROCEDURE DIVISION's actual control flow). A program that
    reads the same file/cursor a fixed number of times unconditionally,
    ignoring the EOF/SQLCODE-100 signal, would still see a stale count
    here. `demote_reason`: set instead of `count` when the downgraded
    body carries no way to know the real count at all (e.g. a READ whose
    source `AT END` clause has no FILE STATUS field and nothing
    `_replicated_at_end_statements` could safely replicate -- an entirely
    empty exhaustion body, not an "exact by construction" one) --
    `_render_expectation` renders a `*>` comment naming the reason
    instead of a speculative number in that case."""

    count: int | None = None
    demote_reason: str | None = None
    #: False when the override comes from a looped FETCH's own exhausting
    #: call (issue #141) rather than a --placeholder downgrade; only the
    #: wording of the cascade demotion below depends on it.
    from_placeholder: bool = True
    #: Whether `_bundle_mock_directives` demotes the counts of the other
    #: boundaries in this one's paragraph. False for a status-driven READ
    #: loop's own end-of-file call (`_status_read_eof`): the loop body still
    #: runs once per row, exactly as the bundle counted it -- the same as
    #: for a READ whose AT END clause the bundle already counted.
    cascades: bool = True


def _bundle_directive_for(
    fixture: BoundaryFixture,
    mockymock_keys: dict[tuple[MockCategory, str], BoundarySite],
    registry: TallyRegistry,
    placeholder_keys: frozenset[tuple[str, str]] = frozenset(),
    source: ProgramContext | None = None,
) -> tuple[list[str], CallCountOverride | None] | None:
    """The full `MOCK ... END-MOCK` (or `MOCK ... ROWS ... END-MOCK`) block
    for one scenario's boundary fixture, or None if this (category, key)
    has no matching mockymock boundary site (already reported by
    `_warn_on_key_mismatch`). Also returns a `CallCountOverride` when this
    fixture's downgrade also changes its real call count (see that
    class's own docstring) -- `None` when the bundle's original tier-1
    `call_count` expectation still holds.

    `placeholder_keys` (`mockymock generate --placeholder CATEGORY:KEY`,
    repeatable) names fixtures whose body should be DOWNGRADED to strip
    the seeded data while KEEPING any loop-termination machinery that
    data drove -- checked against the fixture's own `(category, key)`
    (bundle-side string category, matching how the CLI parses
    `--placeholder`'s value), not `mockymock_keys`'s MockCategory keying.
    The fixture stays MOCKED either way; only its body (and, for SQL's
    ROWS-sugar directive line, the directive line itself) loses the row
    data. Every generated `.cut` must be RUNNABLE by construction (fix
    round 1, unify-with-data Task 4) -- so the two categories whose
    non-downgraded body embeds loop-termination sugar get a DEDICATED
    downgrade instead of the ordinary, category-generic
    `_placeholder_body_for`, which would silently drop it:

    - READ: `_read_exhaustion_lines` (the SAME helper `_read_body` uses
      for its own `WHEN OTHER` branch and its own empty-sequence case) --
      an "immediately at end" body, not an empty one, so a program's own
      `PERFORM ... UNTIL <eof-flag>` loop still terminates, after exactly
      ONE call -- `CallCountOverride(count=1)` when the body actually
      carries a real termination MOVE (`fixture.terminal` or a replicated
      `AT END` MOVE), else `CallCountOverride(demote_reason=...)` since an
      empty body's real call count cannot be known.
    - SQL, when this fixture would have used `ROWS` sugar
      (`_sql_wants_rows`): `_SQL_ROWS_EXHAUSTED_BODY` (`MOVE 100 TO
      SQLCODE`, mirroring `splicer/injector.py`'s own hardcoded
      exhausted-branch value for `MOCK SQL ... ROWS`), not the ordinary
      SQL placeholder's `MOVE 0 TO SQLCODE` (permanent "more rows
      available"), which would hang a `PERFORM UNTIL SQLCODE = 100`
      cursor-fetch loop the same way an empty READ body would --
      `CallCountOverride(count=1)` unconditionally, since this body is
      always an unconditional, real `MOVE` (no replication gap possible).

    Every other category's downgrade has no loop-termination sugar to
    lose (OPEN/CLOSE/etc.'s STATUS_ONLY body is a single-shot per-call
    status override; CALL/DYNCALL/ACCEPT/CICS/DLI/a single-row SQL
    fixture never emit ROWS sugar at all), so `_placeholder_body_for`
    stays correct for them and no override of THEIR OWN call count is
    needed. Only the downgraded boundary's own call_count is recomputed
    here -- a DIFFERENT boundary's call count that is itself program-flow-
    driven by how many times the now-downgraded loop executes, e.g. a CALL
    made once per row inside the same READ loop being downgraded, is NOT
    known here at all (this function sees one fixture at a time). That
    cascade is handled one level up, by `_bundle_mock_directives`'s own
    post-pass over the `CallCountOverride`s this function returns: every
    OTHER declared boundary in the SAME paragraph as a loop-driving
    downgrade (`site.paragraph_name`, mockymock's own analysis, not the
    bundle's `fixture.paragraph`) gets its own call_count demoted to a
    `*>` comment too, on the same "same paragraph as the READ/FETCH loop"
    heuristic the ordinary READ-loop-with-inline-CALL shape satisfies
    exactly. A boundary reached only through a nested PERFORM from inside
    that paragraph is not caught by this heuristic and can still go
    stale -- review the VERIFYs on any other boundary inside the same loop
    as a downgraded one before trusting the generated file."""
    try:
        category = MockCategory(fixture.category)
    except ValueError:
        return None
    site = mockymock_keys.get((category, fixture.key))
    if site is None:
        return None

    call_count_override: CallCountOverride | None = None
    status_eof_loop = False
    if category is MockCategory.READ:
        fixture, status_eof_loop = _status_read_eof(fixture, source)
    looped_fetch = category is MockCategory.SQL and _is_looped_fetch(
        fixture, site, source
    )
    if (fixture.category, fixture.key) in placeholder_keys:
        if category is MockCategory.READ:
            replicated, at_end, lifted = _at_end_handling(fixture, site, source)
            body = _read_exhaustion_lines(fixture, replicated, at_end, lifted)
            if fixture.terminal or replicated or lifted:
                call_count_override = CallCountOverride(count=1)
            else:
                call_count_override = CallCountOverride(
                    demote_reason=(
                        "downgraded READ body carries no termination "
                        "signal at all (no FILE STATUS field, and this "
                        "program's AT END clause could not be "
                        "auto-replicated) -- the real call count is not "
                        "known by construction"
                    )
                )
        elif category is MockCategory.SQL and _sql_wants_rows(fixture, looped_fetch):
            body = list(_SQL_ROWS_EXHAUSTED_BODY)
            call_count_override = CallCountOverride(count=1)
        else:
            body = _placeholder_body_for(category, fixture.key)
            end_lines = _call_loop_end_lines(site, source, None)
            body = body + end_lines
            if end_lines and not end_lines[0].startswith("*>"):
                call_count_override = CallCountOverride(count=1)
    elif fixture.direction == "STATUS_ONLY":
        body = _status_only_body(fixture)
    elif category is MockCategory.READ:
        body = _read_body(fixture, registry, category, site, source)
        if status_eof_loop:
            call_count_override = CallCountOverride(
                count=len(fixture.sequence) + 1,
                from_placeholder=False,
                cascades=False,
            )
    elif category is MockCategory.SQL and _sql_wants_rows(fixture, looped_fetch):
        # A looped FETCH runs once per row plus the call that finds the
        # cursor exhausted; the bundle counts only the rows.
        override = (
            CallCountOverride(count=len(fixture.sequence) + 1, from_placeholder=False)
            if looped_fetch
            else None
        )
        return _sql_rows_directive(category, fixture.key, fixture), override
    else:
        body = _single_row_body(fixture, source)
        if category is MockCategory.DLI and registry.known(category, fixture.key):
            body = body + _dli_loop_end_lines(
                site, source, registry.name(category, fixture.key)
            )
        if category is MockCategory.CALL and registry.known(category, fixture.key):
            end_lines = _call_loop_end_lines(
                site, source, registry.name(category, fixture.key)
            )
            if (
                end_lines
                and not end_lines[0].startswith("*>")
                and not _row_already_ends(body, site, source)
            ):
                # The row answers the first call and the end-of-data reply
                # the second, which ends the loop waiting on it.
                call_count_override = CallCountOverride(count=2, from_placeholder=False)
            body = body + end_lines

    body = _with_captures(category, fixture.key, body, source)
    lines = [_directive_header(category, fixture.key, site)]
    lines.extend(f"    {line}" for line in body)
    lines.append("END-MOCK")
    return lines, call_count_override


def _merged_status_only_body(fixtures: list[BoundaryFixture]) -> list[str]:
    """Merge STATUS_ONLY bodies across every fixture sharing one physical
    site (see `_bundle_directive_for_group`): the first non-default status
    code found across ANY of them, so an override on just one of a
    multi-file OPEN/CLOSE's files (e.g. an "error status" scenario
    targeting only the input file) is not silently lost just because it
    wasn't the file whose key the single MOCK directive happened to use."""
    for fixture in fixtures:
        body = _status_only_body(fixture)
        if body:
            return body
    return []


def _bundle_directive_for_group(
    fixtures: list[BoundaryFixture],
    mockymock_keys: dict[tuple[MockCategory, str], BoundarySite],
    registry: TallyRegistry,
    placeholder_keys: frozenset[tuple[str, str]] = frozenset(),
    source: ProgramContext | None = None,
) -> tuple[list[str], CallCountOverride | None] | None:
    """Like `_bundle_directive_for`, but for every fixture that resolves
    to the SAME physical mockymock `BoundarySite` (only possible for
    STATUS_ONLY -- a multi-file `OPEN`/`CLOSE` is one physical statement
    even though cobol-parser's `BoundaryInventoryAnalyzer` reports one
    `Boundary` per file, see `_mockymock_boundary_keys`). Declaring a
    separate MOCK directive per file would double-match the one physical
    site and refuse AMBIGUOUS_MOCK -- exactly one directive is emitted,
    keyed on the first fixture's own key, with every group member's status
    merged in (see `_merged_status_only_body`). Never returns a
    `CallCountOverride`: STATUS_ONLY (the only category that groups) has
    no loop-termination concept for a downgrade to lose -- see
    `_bundle_directive_for`'s own docstring.

    `placeholder_keys` is checked against EVERY group member's own
    `(category, key)`, not just the primary's: the shared MOCK directive
    is keyed on the primary fixture, but a user naming the group's
    SECONDARY file (e.g. `--placeholder OPEN:RPT-FILE` when INV-FILE is
    primary) must still trigger the downgrade -- that key genuinely has a
    fixture, so silently no-op'ing on it would be exactly the
    matched-nothing case the CLI's own unmatched-placeholder warning
    exists to catch, made worse by staying silent instead.

    A group holding any non-STATUS_ONLY fixture is not a multi-file
    statement: it is several statements on one file that mockymock mocks
    as one site (a priming READ plus the READ inside the loop). Those
    render from the first fixture alone, whose rows end the loop; merging
    them as status-only left the READ mock empty and the loop endless."""
    if len(fixtures) == 1 or any(f.direction != "STATUS_ONLY" for f in fixtures):
        return _bundle_directive_for(
            fixtures[0], mockymock_keys, registry, placeholder_keys, source
        )
    primary = fixtures[0]
    try:
        category = MockCategory(primary.category)
    except ValueError:
        return None
    site = mockymock_keys.get((category, primary.key))
    if site is None:
        return None
    if any((f.category, f.key) in placeholder_keys for f in fixtures):
        body = _placeholder_body_for(category, primary.key)
    else:
        body = _merged_status_only_body(fixtures)
    lines = [_directive_header(category, primary.key, site)]
    lines.extend(f"    {line}" for line in body)
    lines.append("END-MOCK")
    return lines, None


def _bundle_mock_directives(
    scenario: Scenario,
    surface: MockSurface,
    mockymock_keys: dict[tuple[MockCategory, str], BoundarySite],
    registry: TallyRegistry,
    placeholder_keys: frozenset[tuple[str, str]] = frozenset(),
    source: ProgramContext | None = None,
) -> tuple[
    list[str],
    set[tuple[MockCategory, str]],
    dict[tuple[MockCategory, str], CallCountOverride],
]:
    """Every `MOCK ... END-MOCK` block this scenario's TESTCASE needs: real
    fixture data grouped and deduplicated by physical site (see
    `_bundle_directive_for_group`) for everything the bundle generated
    data for, plus a placeholder body (reusing the ordinary,
    already-tested `_directive_for`) for every OTHER mockymock-known site
    -- an OUT-direction boundary the bundle only stubbed (no fixture at
    all, per fixture-bundle-schema.md), or one the bundle doesn't mention
    at all (a genuine key-set gap `_warn_on_key_mismatch` already
    reported). Either way, a boundary this program's own analysis found is
    always mocked with *something*: leaving it unmocked would make the
    generated `.cut` fail `run`/`lint`'s UNMOCKED_* check outright, which
    is worse than a placeholder body a human can improve on. This mirrors
    the ordinary bundle-less scaffold's own "mock everything mockable,
    unconditionally" philosophy (see the module docstring).

    Also returns the exact (category, key) pairs this TESTCASE actually
    declared a MOCK directive for -- when a physical site's OTHER keys
    (a multi-file OPEN/CLOSE's non-primary file) were folded into that one
    directive rather than getting their own, `VERIFY`/`EXPECT` rendering
    (`_render_expectation`) must know to skip them: a `VERIFY OPEN
    RPT-FILE` with no literal `MOCK OPEN RPT-FILE` in this same TESTCASE
    is VERIFY_WITHOUT_MOCK even though "RPT-FILE" is a perfectly valid key
    for the shared site in general.

    And (fix round 2) the `CallCountOverride` `_bundle_directive_for`/
    `_bundle_directive_for_group` computed for each (category, key) whose
    downgrade changed its real call count -- collected here rather than
    recomputed at expectation-rendering time, so `_render_expectation`
    reads the SAME downgrade decision the body rendering above it just
    made instead of re-deriving it from `placeholder_keys` a second time.
    """
    fixtures_by_site: dict[int, list[BoundaryFixture]] = {}
    site_order: list[int] = []
    for fixture in scenario.fixtures:
        try:
            category = MockCategory(fixture.category)
        except ValueError:
            continue
        site = mockymock_keys.get((category, fixture.key))
        if site is None:
            continue  # already reported by _warn_on_key_mismatch
        site_id = id(site)
        if site_id not in fixtures_by_site:
            fixtures_by_site[site_id] = []
            site_order.append(site_id)
        fixtures_by_site[site_id].append(fixture)

    lines: list[str] = []
    declared_keys: set[tuple[MockCategory, str]] = set()
    call_count_overrides: dict[tuple[MockCategory, str], CallCountOverride] = {}
    covered_site_ids: set[int] = set()
    for site_id in site_order:
        group = fixtures_by_site[site_id]
        result = _bundle_directive_for_group(
            group, mockymock_keys, registry, placeholder_keys, source
        )
        if result is not None:
            directive, override = result
            lines.extend(directive)
            try:
                key_pair = (MockCategory(group[0].category), group[0].key)
                declared_keys.add(key_pair)
                if override is not None:
                    call_count_overrides[key_pair] = override
            except ValueError:
                pass
        covered_site_ids.add(site_id)

    for (category, key), site in mockymock_keys.items():
        if id(site) in covered_site_ids:
            continue
        covered_site_ids.add(id(site))
        placeholder = _directive_for(site, surface)
        if placeholder is None:
            continue
        directive_line, body = placeholder
        if category is MockCategory.DLI and registry.known(category, key):
            body = body + _dli_loop_end_lines(
                site, source, registry.name(category, key)
            )
        if category is MockCategory.CALL and registry.known(category, key):
            body = body + _call_loop_end_lines(
                site, source, registry.name(category, key)
            )
        lines.append(directive_line)
        lines.extend(f"    {line}" for line in body)
        lines.append("END-MOCK")
        declared_keys.add((category, key))

    # Issue #47: a loop-driving downgrade's own CallCountOverride (READ
    # ROWS / SQL ROWS -- the only categories `_bundle_directive_for` ever
    # attaches one to) changes how many times ITS OWN loop runs, which can
    # make any OTHER boundary reached only inside that loop stale too (a
    # CALL made once per row, for instance) -- the bundle's original count
    # assumed the loop's un-downgraded row count. "Reached only inside
    # that loop" is approximated by "declared in the SAME paragraph as the
    # downgraded boundary's own statement" (`site.paragraph_name`,
    # mockymock's own program analysis -- not the bundle's `fixture.
    # paragraph`, so this holds even for a bundle that leaves it blank):
    # exact for the ordinary READ/FETCH-loop-with-inline-CALL shape the
    # issue's own repro uses, though a boundary reached through a nested
    # PERFORM from inside that paragraph still isn't caught. Demoting
    # reuses the same `*>` comment `CallCountOverride.demote_reason`
    # already renders for a downgraded boundary's own unknowable count.
    for (loop_category, loop_key), loop_override in list(call_count_overrides.items()):
        if not loop_override.cascades:
            continue
        loop_site = mockymock_keys.get((loop_category, loop_key))
        if loop_site is None:
            continue
        for other_key_pair in declared_keys:
            if other_key_pair == (loop_category, loop_key):
                continue
            if other_key_pair in call_count_overrides:
                continue
            other_site = mockymock_keys.get(other_key_pair)
            if other_site is None:
                continue
            if other_site.paragraph_name != loop_site.paragraph_name:
                continue
            why = (
                "downgraded by --placeholder -- how many times that loop "
                "actually executes changed"
                if loop_override.from_placeholder
                else "a loop that runs once more than it has rows"
            )
            call_count_overrides[other_key_pair] = CallCountOverride(
                demote_reason=(
                    f"in the same paragraph as {loop_category.value}:"
                    f"{loop_key}, {why}, so this call count is no longer "
                    f"known by construction"
                ),
                from_placeholder=loop_override.from_placeholder,
            )
    return lines, declared_keys, call_count_overrides


def _is_known_category(category_str: str) -> bool:
    try:
        MockCategory(category_str)
    except ValueError:
        return False
    return True


def _is_boundary_level_ref(ref: str) -> bool:
    """True when `ref` is a `"CATEGORY:KEY"` boundary reference rather
    than a COBOL data-name -- COBOL names never contain a colon, so
    checking for one of the known category strings before it is an
    unambiguous, precise test."""
    category_str, sep, _ = ref.partition(":")
    return bool(sep) and _is_known_category(category_str)


def _rendered_call_count_refs(
    expectations: list[Expectation],
    declared_keys: set[tuple[MockCategory, str]],
    call_count_overrides: dict[tuple[MockCategory, str], CallCountOverride],
) -> set[tuple[MockCategory, str]]:
    """The boundaries this TESTCASE will actually emit a real `VERIFY ...
    WAS CALLED n TIMES` line for.

    Needed by `_render_expectation`'s tier-3 branch: a boundary-level stub
    expectation is redundant only when that same boundary genuinely got a
    live count assertion here, and "genuinely" excludes both the keys with
    no MOCK directive of their own and the counts demoted to a `*>` comment
    by a `--placeholder` downgrade. Deriving it once, from the same
    `declared_keys`/`call_count_overrides` the rendering itself reads, keeps
    the two decisions from drifting apart."""
    rendered: set[tuple[MockCategory, str]] = set()
    for expectation in expectations:
        if expectation.kind != "call_count":
            continue
        category_str, _, key = expectation.ref.partition(":")
        try:
            category = MockCategory(category_str)
        except ValueError:
            continue
        if (category, key) not in declared_keys:
            continue
        override = call_count_overrides.get((category, key))
        if override is not None and override.demote_reason is not None:
            continue
        rendered.add((category, key))
    return rendered


def _describe_boundary_ref(ref: str) -> str:
    """`"WRITE:INV-REC"` -> `WRITE INV-REC`, matching how a MOCK/VERIFY
    directive for that boundary reads in the `.cut`. Falls back to the raw
    ref for a category this mockymock doesn't know."""
    category_str, sep, key = ref.partition(":")
    if not sep:
        return ref
    try:
        return MockDirective(MockCategory(category_str), key).describe()
    except ValueError:
        return ref


def _render_expectation(
    expectation: Expectation,
    declared_keys: set[tuple[MockCategory, str]],
    call_count_overrides: (
        dict[tuple[MockCategory, str], CallCountOverride] | None
    ) = None,
    counted_boundaries: set[tuple[MockCategory, str]] | None = None,
    pictures: dict[str, str] | None = None,
    source: ProgramContext | None = None,
) -> list[str]:
    """Tier 1 (`call_count`) -> `VERIFY ... WAS CALLED n TIMES`; tier 2
    (`field_equals`) -> `EXPECT <name> TO BE <value>`; tier 3 (`stub`) ->
    a `*> STUB EXPECT ...` comment.

    A boundary-level tier-3 ref (`"WRITE:INV-REC"` rather than a data-name)
    is dropped ONLY when this same TESTCASE actually emits a live `VERIFY
    ... WAS CALLED` for that boundary -- `counted_boundaries`, from
    `_rendered_call_count_refs`. It used to be dropped unconditionally on
    that reasoning, which was wrong whenever the count assertion did not in
    fact get rendered (no MOCK directive of its own for that key, or a
    `--placeholder` downgrade demoting the count to a comment): the bundle
    knew something about an OUT boundary -- most visibly every `WRITE:` stub
    under `--scenarios all` -- and the generated `.cut` said nothing at all
    about it. A `*>` comment is inert, so surfacing it can never break the
    generated file; silently dropping it opened a gap between what the
    analysis knew and what reached the file, which is the one thing a
    scaffold must not do.

    `declared_keys` (from `_bundle_mock_directives`) -- not the broader
    `mockymock_keys` -- is what call_count is checked against: a key that
    only exists because it shares a physical site with the key a MOCK
    directive actually used (a multi-file OPEN/CLOSE's non-primary file)
    has no *literal* MOCK of its own in this TESTCASE, and VERIFYing it
    anyway is VERIFY_WITHOUT_MOCK.

    `call_count_overrides` (fix round 2, also from `_bundle_mock_directives`,
    same seam that decided each fixture's body) supersedes the bundle's own
    `expectation.value` for a `call_count` ref whose fixture was
    `--placeholder`-downgraded in a way that changed its real call count
    (see `CallCountOverride`'s own docstring) -- rendering the bundle's
    original, now-stale count would pin an assertion the generated `.cut`
    cannot itself satisfy, which is exactly the runnable-by-construction
    violation this fix closes. A `demote_reason` renders as a `*>` comment
    instead of a `VERIFY` line -- the real count is not known by
    construction in that case, and a speculative number would be worse
    than no assertion at all.
    """
    if expectation.kind == "call_count":
        category_str, _, key = expectation.ref.partition(":")
        try:
            category = MockCategory(category_str)
        except ValueError:
            return []
        if (category, key) not in declared_keys:
            return []  # no literal MOCK directive for this key in this TESTCASE
        directive_text = MockDirective(category, key).describe()
        override = (call_count_overrides or {}).get((category, key))
        if override is not None and override.demote_reason is not None:
            return [
                f"*> VERIFY {directive_text} WAS CALLED <count not exact "
                f"by construction"
                f"{' after --placeholder downgrade' if override.from_placeholder else ''}"
                f" -- {override.demote_reason}>"
            ]
        value = (
            override.count
            if override is not None and override.count is not None
            else expectation.value
        )
        return [f"VERIFY {directive_text} WAS CALLED {value} TIMES"]
    if expectation.kind == "field_equals":
        ref = _expect_name(expectation.ref, source)
        if ref is None:
            return [
                f"*> STUB EXPECT {expectation.ref} -- the program folds it to "
                f"{expectation.value}, but its name is declared under more "
                f"than one record and EXPECT takes no OF qualification"
            ]
        expectation = Expectation(
            kind=expectation.kind,
            ref=ref,
            value=expectation.value,
            note=expectation.note,
        )
        # The PICTURE decides bare vs quoted, exactly as it does for
        # `run --record-expectations`: a folded "-3" / "1.5" / "007" held in
        # a PIC X field rendered bare is an EXPECT that fails on the very
        # first run (GnuCOBOL compares it as text). `A OF B` qualification
        # is looked up by its first word, the item itself.
        picture = picture_for(expectation.ref.split()[0], pictures)
        rendered = render_expect_value(str(expectation.value), picture)
        return [f"EXPECT {expectation.ref} TO BE {rendered}"]
    # kind == "stub"
    note = f" -- {expectation.note}" if expectation.note else ""
    if _is_boundary_level_ref(expectation.ref):
        category_str, _, key = expectation.ref.partition(":")
        try:
            pair = (MockCategory(category_str), key)
        except ValueError:
            pair = None
        if pair is not None and pair in (counted_boundaries or set()):
            return []  # already asserted by this case's own VERIFY ... WAS CALLED
        return [f"*> STUB EXPECT {_describe_boundary_ref(expectation.ref)}{note}"]
    return [
        f"*> STUB EXPECT {_expect_name(expectation.ref, source) or expectation.ref}{note}"
    ]


def _expect_name(ref: str, source: ProgramContext | None) -> str | None:
    """A bundle names a field `RECORD.FIELD` (its schema's qualified form),
    which spliced into an EXPECT is a cobc syntax error (issue #144). The
    leaf is the COBOL name when it is unique; None when it is declared
    under more than one record -- the DSL has no `OF`."""
    base, paren, rest = ref.partition("(")
    if "." not in base:
        return ref
    leaf = base.rsplit(".", 1)[-1].strip()
    if source is not None and not source.is_unique_name(leaf):
        return None
    return leaf + paren + rest


def _merged_call_counts(expectations: list[Expectation]) -> list[Expectation]:
    """The bundle carries one `call_count` per call SITE, but a VERIFY (and
    the splicer's tally) counts per (category, key): two `CALL "FMT"`
    statements rendered as two `VERIFY ... 1 TIMES` lines that both failed
    with "got 2" (issue #142). Sum them into one expectation per ref, kept
    at the first one's position. READ and RETURN are the exception: every
    site of one file consumes the same sequential stream, so each site's
    count already covers the whole stream and the largest one is kept."""
    merged: list[Expectation] = []
    by_ref: dict[str, Expectation] = {}
    for expectation in expectations:
        if expectation.kind != "call_count":
            merged.append(expectation)
            continue
        existing = by_ref.get(expectation.ref)
        if existing is None:
            copy = Expectation(
                kind=expectation.kind,
                ref=expectation.ref,
                value=expectation.value,
                note=expectation.note,
            )
            by_ref[expectation.ref] = copy
            merged.append(copy)
        elif isinstance(existing.value, int) and isinstance(expectation.value, int):
            if expectation.ref.partition(":")[0] in ("READ", "RETURN"):
                existing.value = max(existing.value, expectation.value)
            else:
                existing.value += expectation.value
    return merged


def _sites_for_key(
    category: MockCategory,
    key: str,
    surface: MockSurface,
    reachable: set[str] | None = None,
) -> list[BoundarySite]:
    return [
        site
        for site in surface.boundary_sites
        if site.category is category
        and (reachable is None or site.paragraph_name in reachable)
        and (
            _unique_prefix(site, surface) == key
            if category in EXEC_CATEGORIES
            else key in site.keys
        )
    ]


_SEVERAL_SITES_REASON = (
    "called from several sites, some inside an IF/EVALUATE/loop, so how "
    "many of them this case reaches is not known"
)
_CONDITIONAL_SITE_REASON = (
    "called only under an IF/EVALUATE, or from a paragraph PERFORMed "
    "conditionally, so whether this case reaches it is not known"
)
_UNREACHED_SITE_REASON = (
    "also called from a paragraph this case's PERFORM never reaches (a CICS "
    "HANDLE CONDITION target, or code nothing PERFORMs), which the bundle's "
    "count includes"
)


def _conditional_call_count_keys(
    expectations: list[Expectation],
    surface: MockSurface,
    reachable: set[str] | None = None,
    scope: tuple[set[str], set[int]] | None = None,
) -> list[tuple[tuple[MockCategory, str], str]]:
    """Keys whose bundle count (`_merged_call_counts`) is not exact, each
    with the reason. The bundle counts every site once per scenario whether
    or not its branch runs, so a count is kept only when every site runs on
    every pass: `scope` is `analysis.exact_counts.exact_count_scope` for
    this case's entry (issue #160 -- a single site behind `IF SQLCODE NOT =
    0`, or one in a paragraph PERFORMed only from inside `IF RECORD-OK`).
    Without a scope, any nested site is enough to demote (issue #142 for
    several sites, #160 for one). `_merged_call_counts` sums the bundle's
    per-site counts over every site of the key, so a key that also has a
    site outside `reachable` (ACCTINQ's CICS RETURN in its HANDLE
    CONDITION NOTFND paragraph) carries a count this case cannot reach --
    READ/RETURN excepted, whose merged count is the largest one, not a
    sum."""
    keys: list[tuple[tuple[MockCategory, str], str]] = []
    for expectation in expectations:
        if expectation.kind != "call_count":
            continue
        category_str, _, key = expectation.ref.partition(":")
        try:
            category = MockCategory(category_str)
        except ValueError:
            continue
        sites = _sites_for_key(category, key, surface, reachable)
        if (
            reachable is not None
            and category not in (MockCategory.READ, MockCategory.RETURN)
            and len(_sites_for_key(category, key, surface)) > len(sites)
        ):
            keys.append(((category, key), _UNREACHED_SITE_REASON))
        elif len(sites) > 1 and any(site.nested for site in sites):
            keys.append(((category, key), _SEVERAL_SITES_REASON))
        elif scope is None:
            if any(site.nested for site in sites):
                keys.append(((category, key), _CONDITIONAL_SITE_REASON))
        elif any(not _site_in_scope(site, scope) for site in sites):
            keys.append(((category, key), _CONDITIONAL_SITE_REASON))
    return keys


def _site_in_scope(site: BoundarySite, scope: tuple[set[str], set[int]]) -> bool:
    paragraphs, statement_ids = scope
    return site.paragraph_name in paragraphs and id(site.statement) in statement_ids


def _unlooped_read_counts(
    expectations: list[Expectation],
    surface: MockSurface,
    reachable: set[str] | None,
    source: ProgramContext,
) -> dict[tuple[MockCategory, str], int]:
    """A READ outside any loop (a run-parameter card read once at start-up)
    runs once per site, whatever number of rows the bundle generated for
    it; the bundle counts the rows (DORMACCT: "10 TIMES, got 1")."""
    counts: dict[tuple[MockCategory, str], int] = {}
    for expectation in expectations:
        if expectation.kind != "call_count":
            continue
        category_str, _, key = expectation.ref.partition(":")
        if category_str != MockCategory.READ.value:
            continue
        sites = _sites_for_key(MockCategory.READ, key, surface, reachable)
        if sites and not any(
            site.nested or site_in_loop(site, source.looped) for site in sites
        ):
            counts[(MockCategory.READ, key)] = len(sites)
    return counts


def _scaffold_with_bundle(
    suite_name: str,
    surface: MockSurface,
    bundle: FixtureBundle,
    placeholder_keys: frozenset[tuple[str, str]] = frozenset(),
    source: ProgramContext | None = None,
) -> str:
    mockymock_keys = _mockymock_boundary_keys(surface)
    _warn_on_key_mismatch(
        mockymock_keys,
        _bundle_boundary_keys(bundle),
        _known_unmockable_keys(surface),
    )
    fallback_entry = _first_paragraph(source.program) if source is not None else None
    registry = _build_shadow_tally_registry(bundle, mockymock_keys, fallback_entry)

    lines = [f'TESTSUITE "{_quote_safe(suite_name)}"', ""]
    skipped_scenarios = 0
    for scenario in bundle.scenarios:
        entry = scenario.entry or fallback_entry
        if not entry:
            # Nothing to PERFORM -- can't scaffold a TESTCASE for this
            # scenario at all. Should not happen for a real program with a
            # non-empty PROCEDURE DIVISION; reported below, not per-scenario.
            skipped_scenarios += 1
            continue
        lines.append(f'TESTCASE "{_quote_safe(scenario.name)}"')
        lines.extend(f"    {line}" for line in _verification_comment_lines(scenario))
        # Only the sites this case can reach: a mock for a boundary in a
        # paragraph nothing PERFORMs from the entry (or reached only via a
        # CICS HANDLE) is UNMATCHED_MOCK to the very lint this file has to
        # pass (issue #143). Its VERIFY goes with it -- `_render_expectation`
        # drops counts for keys that got no MOCK directive.
        reachable = source.reachable_from(entry) if source is not None else None
        scenario_keys = (
            mockymock_keys
            if reachable is None
            else {
                pair: site
                for pair, site in mockymock_keys.items()
                if site.paragraph_name in reachable
            }
        )
        directive_lines, declared_keys, call_count_overrides = _bundle_mock_directives(
            scenario, surface, scenario_keys, registry, placeholder_keys, source
        )
        lines.extend(f"    {line}" for line in directive_lines)
        lines.append(f"    PERFORM {entry}")
        lines.extend(
            f"    {line}"
            for line in _capture_stub_lines(_capture_targets(directive_lines))
        )
        expectations = _merged_call_counts(scenario.expectations)
        scope = (
            source.exact_count_scope(entry, reachable)
            if source is not None and reachable is not None
            else None
        )
        for key_pair, reason in _conditional_call_count_keys(
            expectations, surface, reachable, scope
        ):
            call_count_overrides.setdefault(
                key_pair,
                CallCountOverride(demote_reason=reason, from_placeholder=False),
            )
        if source is not None:
            for key_pair, count in _unlooped_read_counts(
                expectations, surface, reachable, source
            ).items():
                call_count_overrides.setdefault(
                    key_pair, CallCountOverride(count=count, from_placeholder=False)
                )
        counted_boundaries = _rendered_call_count_refs(
            expectations, declared_keys, call_count_overrides
        )
        for expectation in expectations:
            lines.extend(
                f"    {line}"
                for line in _render_expectation(
                    expectation,
                    declared_keys,
                    call_count_overrides,
                    counted_boundaries,
                    source.pictures if source is not None else None,
                    source,
                )
            )
        lines.append("")

    if skipped_scenarios:
        print(
            f"mockymock generate --with-data: WARNING: {skipped_scenarios} "
            f"scenario(s) had no entry paragraph and could not be scaffolded "
            f"as a TESTCASE",
            file=sys.stderr,
        )
    return "\n".join(lines)
