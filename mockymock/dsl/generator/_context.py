"""ProgramContext (per-program source facts) and the low-level helpers it
and every boundary family share."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from mockymock._decimal import decimal_point_is_comma
from mockymock.analysis.exact_counts import exact_count_scope
from mockymock.analysis.loops import (
    LoopGuard,
    loop_guards,
    looped_paragraphs_and_statements,
    names_set_on_reply,
    site_in_loop,
)
from mockymock.analysis.mock_surface import (
    BoundarySite,
    MockSurface,
    _all_paragraphs,
    _nested_statement_lists,
)
from mockymock.dsl.generator.keys import _read_mock_key, split_read_files
from mockymock.dsl.model import MockCategory, MockTestCase, MockTestSuite
from mockymock.report.record_rewrite import field_pictures

#: CALL-level DL/I interfaces whose USING list is (function, PCB, ...).
DEFAULT_DLI_CALL_INTERFACES = frozenset({"CBLTDLI", "CEETDLI"})

if TYPE_CHECKING:
    from cobolparser.models.program import CobolProgram


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


# --- Lifting a READ's own AT END imperative verbatim -------------------------


def _data_name_counts(program) -> dict[str, int]:
    from mockymock._cobol_layout import compute_program_data_items

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
    from mockymock._cobol_layout import compute_program_data_items

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
    split = split_read_files(surface)
    plain: dict[str, tuple[str, bool]] = {}
    excluded: set[str] = set()
    for site in surface.boundary_sites:
        if site.category is not MockCategory.READ or not site.keys:
            continue
        name = site.keys[0].upper()
        # A file read in several forms is decided per form: its browse
        # (`MOCK READ <file> NEXT`) ends on "10" even when a keyed READ of
        # the same file answers "23" (issue #417).
        key = _read_mock_key(site, split)
        statement = site.statement
        sequential = (
            not getattr(statement, "at_end_clause", None)
            and not getattr(statement, "invalid_key_clause", None)
            and not getattr(statement, "key_name", None)
            and (
                (getattr(statement, "access_mode", None) or "").upper() == "NEXT"
                or access.get(name, "") in ("", "SEQUENTIAL")
            )
        )
        if not sequential or name not in status_fields:
            excluded.add(key)
            continue
        _, was_looped = plain.get(key, ("", False))
        plain[key] = (status_fields[name], was_looped or site_in_loop(site, looped))
    return {key: entry for key, entry in plain.items() if key not in excluded}


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
    program: CobolProgram | None = None
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
    #: False: never `main_line_thru` (cli.commands.generate._main_line_or_bare).
    main_line: bool = True
    #: `main_line_thru`'s answer per entry (uppercased).
    _main_line: dict[str, str | None] = field(
        default_factory=dict, repr=False, compare=False
    )
    #: `SPECIAL-NAMES. DECIMAL-POINT IS COMMA.`: every numeric literal the
    #: scaffold writes uses a comma (issue #230).
    decimal_comma: bool = False
    #: File key -> `_record_length_move`'s answer, computed once per file.
    record_length_moves: dict[str, str | None] = field(default_factory=dict)
    #: Steps every generated case runs before its PERFORM so the program
    #: starts the way a real invocation would -- see `_commarea_setup_lines`.
    setup_lines: list[str] = field(default_factory=list)
    #: Field name (uppercased) -> (delimiter, INTO targets) for every field
    #: the program splits with `UNSTRING <field> DELIMITED BY "<literal>"`,
    #: so a generated record holds the delimiters its parse looks for --
    #: see `_unstring_layouts`.
    unstring_layouts: dict[str, tuple[str, list[str]]] = field(default_factory=dict)
    #: Dynamic CALL identifier -> (the program names it can hold, whether
    #: that list is complete) -- see `_dynamic_call_targets`.
    dynamic_targets: dict[str, tuple[list[str], bool]] = field(default_factory=dict)
    #: The CALL names taken for the DL/I call interface (USING function,
    #: PCB, ...): CBLTDLI and CEETDLI plus the config's `ims_call_names`,
    #: a site's own wrappers around them (CBLTBNC2, CBLTBNC3).
    dli_interfaces: frozenset[str] = DEFAULT_DLI_CALL_INTERFACES

    @classmethod
    def build(
        cls,
        program,
        lines: list[str],
        surface: MockSurface,
        ims_call_names: tuple[str, ...] = (),
    ) -> ProgramContext:
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
            unstring_layouts=_unstring_layouts(program),
            status_read_eof=_status_driven_reads(
                program, surface, looped_paragraphs_and_statements(program)
            ),
            guards=loop_guards(program),
            data_items=_layout_items(program),
            surface=surface,
            decimal_comma=decimal_point_is_comma(program),
            setup_lines=_commarea_setup_lines(program, lines),
            dynamic_targets=_dynamic_call_targets(program, surface),
            dli_interfaces=DEFAULT_DLI_CALL_INTERFACES
            | {name.upper() for name in ims_call_names},
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

    def condition_owners(self, name: str) -> set[str]:
        """The field(s) `name` is a level-88 condition of, uppercased."""
        wanted = name.upper()
        owners: set[str] = set()
        for item in self.data_items:
            parts = str(item.get("qualified_name") or "").upper().split(".")
            if item.get("level") == 88 and parts[-1] == wanted and len(parts) > 1:
                owners.add(parts[-2])
        return owners

    def paragraph_statements(self, name: str | None) -> list:
        """The statements of the PROCEDURE DIVISION paragraph `name`, or
        [] when there is none (or no parsed program)."""
        procedure = (
            self.program.get_division("PROCEDURE") if self.program is not None else None
        )
        if procedure is None or not name:
            return []
        wanted = name.upper()
        for paragraph in _all_paragraphs(procedure):
            if str(getattr(paragraph, "paragraph_name", "") or "").upper() == wanted:
                return list(paragraph.statements)
        return []

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

    def thru_exit(self, entry: str) -> str | None:
        """The paragraph every `PERFORM entry THRU <exit>` in the program
        names, or None when the program PERFORMs `entry` bare anywhere, with
        two different exits, or not at all. A scaffold PERFORMing such a
        paragraph bare tested a flow the program never runs: its GO TO
        <exit> left the PERFORM, fell through every paragraph below, and ran
        off the end of the program, so the case crashed and every later case
        never ran (INTCALC's 2200-CALCULATE-INTEREST THRU 2200-EXIT)."""
        procedure = (
            self.program.get_division("PROCEDURE") if self.program is not None else None
        )
        if procedure is None:
            return None

        def walk(statements):
            for statement in statements:
                yield statement
                for nested in _nested_statement_lists(statement):
                    yield from walk(nested)

        wanted = entry.upper()
        exits: dict[str | None, str | None] = {}
        for paragraph in _all_paragraphs(procedure):
            for statement in walk(paragraph.statements):
                if type(statement).__name__ != "PerformStatement":
                    continue
                target = str(getattr(statement, "target_paragraph", "") or "")
                if target.upper() != wanted:
                    continue
                thru = getattr(statement, "thru_paragraph", None)
                exits[str(thru).upper() if thru else None] = str(thru) if thru else None
        if len(exits) != 1:
            return None
        return next(iter(exits.values()))

    def reachable_from(
        self, entry: str, follow_whenever: bool = True, thru: str | None = None
    ) -> set[str] | None:
        """Paragraph/section names a `PERFORM entry` can execute, or None
        when that can't be established (no program, unknown entry, or a
        flow the reachability model itself refuses) -- callers then keep
        every site, as before. `follow_whenever=False` leaves out the
        `EXEC SQL WHENEVER` handlers, as lint does for a case whose mocks
        can never make one fire (issue #244)."""
        if self.program is None:
            return None
        from mockymock.analysis.refusal._reachability import _reachable_paragraphs

        reached, reasons = _reachable_paragraphs(
            self.program,
            entry,
            thru,
            neutralized_goto=self.neutralized_goto,
            follow_whenever=follow_whenever,
            # Generated mocks never raise a CICS condition (issue #268), so
            # no HANDLE CONDITION label is reached through one.
            cics_conditions=frozenset(),
        )
        if reasons or entry not in reached:
            return None
        return reached

    def main_line_thru(self, entry: str) -> str | None:
        """The program's last paragraph when a case PERFORMing `entry`
        should run the whole main line (`PERFORM entry THRU <last>`), else
        None (2026-11-02).

        That is when `entry` is the program's first paragraph, the real
        program carries on past it (its last statement is not a STOP RUN,
        GOBACK or EXIT PROGRAM: it falls through, or GO TOs on, as the NIST
        CCVS85 programs' `OPEN-FILES` does), and every STOP RUN/GOBACK the
        longer range reaches can end it (`find_terminator_plans` refuses
        none). A bare `PERFORM entry` tests that first paragraph alone and
        returns at its end, where the program never stops; THRU the last
        paragraph, the run goes on as the program does, and a terminator
        it falls into ends the case (`TerminatorPlan.exit_kind`
        "PROGRAM"). A program whose terminators sit in paragraphs it also
        PERFORMs keeps the bare PERFORM: the range would be refused."""
        if not self.main_line:
            return None
        key = entry.upper()
        if key not in self._main_line:
            self._main_line[key] = self._compute_main_line_thru(entry)
        return self._main_line[key]

    def _compute_main_line_thru(self, entry: str) -> str | None:
        if self.program is None or self.surface is None:
            return None
        from cobolparser.models.statements.control import StopStatement
        from cobolparser.models.statements.misc import ExitStatement, GobackStatement

        from mockymock.analysis.refusal import (
            find_terminator_plans,
            program_last_paragraph,
        )
        from mockymock.analysis.refusal._reachability import _source_ordered_paragraphs
        from mockymock.splicer.source_map import collect_scope_map

        procedure = self.program.get_division("PROCEDURE")
        ordered = _source_ordered_paragraphs(procedure) if procedure else None
        if not ordered:
            return None
        from mockymock.analysis.declaratives import declarative_paragraphs

        # DECLARATIVES come first in the source; the main line starts after.
        in_declaratives = declarative_paragraphs(self.program)
        main = [p for p in ordered if p.paragraph_name not in in_declaratives]
        if not main:
            return None
        first = main[0]
        if str(first.paragraph_name or "").upper() != entry.upper():
            return None
        last = program_last_paragraph(self.program)
        if last is None or last.upper() == entry.upper():
            return None
        statements = list(first.statements)
        if statements:
            final = statements[-1]
            if (
                isinstance(final, GobackStatement)
                or (isinstance(final, StopStatement) and final.stop_type == "RUN")
                or (isinstance(final, ExitStatement) and final.exit_type == "PROGRAM")
            ):
                return None
        suite = MockTestSuite(
            name="MAIN-LINE",
            test_cases=[
                MockTestCase(
                    name="main line",
                    perform_target=str(first.paragraph_name),
                    perform_thru=last,
                )
            ],
        )
        try:
            _plans, reasons = find_terminator_plans(
                self.surface,
                self.program,
                suite,
                collect_scope_map(self.program, self.lines),
                self.lines,
            )
        except Exception:  # noqa: BLE001 - any doubt keeps the bare PERFORM
            return None
        return None if reasons else last

    def whenever_quiet(self, directive_lines: list[str]) -> bool:
        """True when a TESTCASE with these MOCK lines provably never makes
        an emulated `EXEC SQL WHENEVER ... GO TO` fire -- the same
        judgement lint makes (`sql_whenever.whenever_can_fire`), read off
        the lines through the real .cut parser. False on any doubt."""
        if self.program is None:
            return False
        from mockymock.analysis.sql_whenever import whenever_actions, whenever_can_fire
        from mockymock.dsl.parser import CutParseError, parse_cut

        if not whenever_actions(self.program):
            return False
        text = "\n".join(
            ['TESTSUITE "x"', 'TESTCASE "x"']
            + [f"    {line}" for line in directive_lines]
            + ["    PERFORM X"]
        )
        try:
            (case,) = parse_cut(text).test_cases
        except (CutParseError, ValueError):
            return False
        return not whenever_can_fire(self.program, case.mocks)

    def exact_count_scope(
        self, entry: str, reachable: set[str], loops_exact: bool = False
    ) -> tuple[set[str], set[int]] | None:
        """`analysis.exact_counts.exact_count_scope` for `PERFORM entry`."""
        return exact_count_scope(
            self.program,
            entry,
            reachable,
            neutralized_goto=self.neutralized_goto,
            loops_exact=loops_exact,
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
            # Different items agree too when one synthesized field mirrors
            # them all (DLI-GU and DLI-ISRT, both PIC X(4)): the splicer's
            # `plan_captures` accepts exactly that.
            arguments = [argument for argument in resolved if argument is not None]
            if len(arguments) != len(resolved) or any(
                kind != "item" for kind, _ in arguments
            ):
                continue  # a literal: nothing to observe
            items = [data_items.get(name) for _, name in arguments]
            target = capture_target_name(category, key, index)
            declarations = {
                _declaration_for(target, item) if item is not None else None
                for item in items
            }
            if len(declarations) != 1 or None in declarations:
                continue  # layouts disagree, or one cannot be mirrored
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


def _commarea_setup_lines(program, lines: list[str]) -> list[str]:
    """`MOVE LENGTH OF DFHCOMMAREA TO EIBCALEN` for a CICS LINK server
    whose `IF EIBCALEN ...` guard ABENDs (issue #245).

    The reset zeroes EIBCALEN before every case, so without this the
    generated happy path always took the guard. Since a mocked ABEND ends
    the run (#215) it stopped there, and the scaffold's own VERIFYs for the
    READ/REWRITE behind the guard failed. A real LINK passes the
    commarea, so its length is what the program sees. Only a guard that
    ABENDs counts: `IF EIBCALEN = 0` in a pseudo-conversational program
    picks its genuine first-time path and is left alone."""
    procedure = program.get_division("PROCEDURE") if program is not None else None
    if procedure is None or not _declares(program, "DFHCOMMAREA"):
        return []

    def walk(statements):
        for statement in statements:
            yield statement
            for nested in _nested_statement_lists(statement):
                yield from walk(nested)

    def abends(statements) -> bool:
        return any(
            str(getattr(s, "cics_command", "") or "").upper() == "ABEND"
            for s in walk(statements)
        )

    for paragraph in _all_paragraphs(procedure):
        for statement in walk(paragraph.statements):
            then = list(getattr(statement, "then_statements", None) or [])
            if type(statement).__name__ != "IfStatement" or not then:
                continue
            start = statement.location.line
            end = max(start, then[0].location.line - 1)
            condition = " ".join(lines[start - 1 : end]).upper()
            if re.search(r"\bEIBCALEN\b", condition) and abends(then):
                return ["MOVE LENGTH OF DFHCOMMAREA TO EIBCALEN"]
    return []


def _declares(program, name: str) -> bool:
    data_division = program.get_division("DATA")
    wanted = name.upper()

    def walk(node) -> bool:
        for child in getattr(node, "children", []):
            if getattr(child, "level", None) is not None and (
                str(getattr(child, "name", "") or "").upper() == wanted
            ):
                return True
            if walk(child):
                return True
        return False

    return data_division is not None and walk(data_division)


def _dynamic_call_targets(
    program, surface: MockSurface
) -> dict[str, tuple[list[str], bool]]:
    """Identifier (uppercased) -> (the program names a dynamic CALL through
    it can reach, whether that list is complete), from cobol-parser's
    `DynamicCallAnalyzer` (VALUE clauses and MOVEs of literals). The
    no-program sentinels a dispatcher tests first (SPACES, LOW-VALUES,
    ZERO) and all-digit values are not program names and are left out."""
    sites = [
        site
        for site in surface.boundary_sites
        if site.category is MockCategory.DYNCALL and site.keys
    ]
    if not sites:
        return {}
    try:
        from cobolparser.analysis.value_tracker import DynamicCallAnalyzer

        DynamicCallAnalyzer().analyze(program)
    except Exception:  # noqa: BLE001 -- an analysis gap never breaks generate
        return {}
    targets: dict[str, tuple[list[str], bool]] = {}
    for site in sites:
        statement = site.statement
        names = list(targets.get(site.keys[0], ([], True))[0])
        for value in getattr(statement, "possible_values", None) or []:
            name = str(value).strip(" '\"\x00\xff").upper()
            if name and not name.isdigit() and '"' not in name and name not in names:
                names.append(name)
        get_metadata = getattr(statement, "get_metadata", None)
        incomplete = bool(
            get_metadata("possible_values_incomplete") if get_metadata else False
        )
        complete = targets.get(site.keys[0], ([], True))[1] and not incomplete
        targets[site.keys[0]] = (names, complete)
    return {key: value for key, value in targets.items() if value[0]}


def _reply_watched_names(
    site: BoundarySite, reply_args: set[str], context: ProgramContext
) -> set[str]:
    """Every data name that follows `site`'s reply: the reply arguments and
    what is declared under them, plus -- one hop -- any flag the site's own
    paragraph sets in a branch on that reply (issue #188: `PERFORM ...
    UNTIL NO-MORE-MSGS` where `SET NO-MORE-MSGS TO TRUE` sits under `WHEN
    MQ-REASON-CODE = MQRC-NO-MSG-AVAIL`). A flag that is an 88 brings its
    own field (and the field's other 88s) along, so an UNTIL on either
    spelling matches."""
    watched = set().union(*(context.names_under(name) for name in reply_args))
    statements = context.paragraph_statements(site.paragraph_name)
    for flag in names_set_on_reply(statements, watched):
        watched |= context.names_under(flag)
        for owner in context.condition_owners(flag):
            watched |= context.names_under(owner)
    return watched


def _unstring_layouts(program) -> dict[str, tuple[str, list[str]]]:
    """Field -> (delimiter, INTO targets) for each `UNSTRING <field>
    DELIMITED BY "<one literal>" INTO ...` in `program`. A field split
    more than one way, or with a delimiter that is not one literal, is
    left out: there is no single shape to give it."""
    found: dict[str, tuple[str, list[str]] | None] = {}
    try:
        statements = program.find_all_by_type("UnstringStatement")
    except Exception:  # noqa: BLE001 -- no AST walk, no layouts
        return {}
    for statement in statements:
        source_name = str(getattr(statement, "source_operand", "") or "").upper()
        delimiters = list(getattr(statement, "delimiters", None) or [])
        targets = [
            str(entry.get("target") or "").upper()
            for entry in getattr(statement, "into_targets", None) or []
            if isinstance(entry, dict)
        ]
        if (
            not re.fullmatch(r"[A-Z0-9][A-Z0-9-]*", source_name)
            or len(delimiters) != 1
            or not isinstance(delimiters[0], str)
            or not delimiters[0]
            or len(targets) < 2
            or not all(re.fullmatch(r"[A-Z0-9][A-Z0-9-]*", t) for t in targets)
        ):
            continue
        delimiter = _delimiter_literal(delimiters[0])
        if delimiter is None:
            continue
        layout = (delimiter, targets)
        if source_name in found and found[source_name] != layout:
            found[source_name] = None
        else:
            found.setdefault(source_name, layout)
    return {name: layout for name, layout in found.items() if layout is not None}


def _delimiter_literal(text: str) -> str | None:
    """The characters an UNSTRING delimiter operand stands for, or None
    when it names a data item or figurative constant. cobol-parser 3.1
    keeps a literal's quotes (`'"|"'`); earlier releases stripped them,
    so an unquoted operand made only of punctuation is read as that
    literal too."""
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        quote = text[0]
        content = text[1:-1].replace(quote * 2, quote)
        return content or None
    if re.search(r"[A-Za-z0-9]", text):
        return None
    return text


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


def _comment_text(text: str) -> str:
    """`text` on one `*>` comment line: line breaks folded to spaces."""
    return " ".join(text.split())
