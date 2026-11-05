"""Generates the UT-TESTSUITE-*/UT-TESTCASE-*/UT-RESET-WORKING-STORAGE
driver paragraphs, plus the WORKING-STORAGE bookkeeping fields they need.

These become the new PROCEDURE DIVISION entry point: prepended before the
program's own paragraphs, so the original first paragraph never runs
automatically (PROCEDURE DIVISION execution starts at the first paragraph
after the header, and the driver paragraphs come first).

`build_driver`'s optional `record_targets` param (case index -> data-names)
backs `mockymock run --record-expectations`: see
docs/2026-08-04-record-expectations-design.md and
`mockymock.analysis.stub_expectations`. Omitted or empty, it changes
nothing -- ordinary `run` output is unaffected.

`extra_working_storage_lines` backs CICS EIB field synthesis
(`splicer.cics_eib.working_storage_lines`, see
docs/2026-08-27-cics-eib-linkage-support-design.md): appended verbatim to
this function's own bookkeeping fields, so it reaches the same
`DriverArtifact.working_storage_lines` -> `cli.main._insert_driver`
insertion point with no separate splice mechanism needed.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from mockymock.dsl.model import SUITE_PHASE_ID, HookStep, MockTestCase, MockTestSuite
from mockymock.splicer.naming import TallyRegistry, assign, truth_set
from mockymock.splicer.snapshot import StateSnapshot

_SUITE_PARAGRAPH_NAME_RE = re.compile(r"[^A-Z0-9-]")


def _display_text(text: str) -> str:
    """Escape a value for embedding inside a COBOL "..." DISPLAY literal:
    a quote inside a quoted literal is written as two quotes. Without this,
    EXPECT values like "OK" split the generated DISPLAY literal and cobc
    reads the remainder as undefined identifiers."""
    return text.replace('"', '""')


#: A literal longer than this is split across lines by the driver: cobc
#: compiles the instrumented copy `-free`, where a source line over 512
#: bytes is truncated -- a recorded golden like DEPTMQC's 336-byte MQMD
#: (`X"4D44..."`, 675 characters) cut the generated IF in half.
_LONG_LITERAL = 120
#: Characters of literal content per continuation piece.
_LITERAL_CHUNK = 60
_SPLITTABLE_LITERAL_RE = re.compile(
    r"^(?P<prefix>[Xx]?)(?P<quote>[\"'])(?P<body>.*)(?P=quote)$"
)


def _literal_pieces(value: str) -> list[str] | None:
    """A long alphanumeric or hexadecimal literal as concatenated pieces
    (`X"4D44..."` -> `X"4D44..."`, `& X"2020..."`, ...), one per source
    line, or None when `value` is short or not one such literal. The `&`
    concatenation of literals is a literal to cobc (verified under
    `-free -std=mvs`, GnuCOBOL 3.1.2), so the comparison is unchanged. A
    hex piece keeps whole bytes; a quoted piece never splits a doubled
    quote."""
    text = value.strip()
    if len(text) <= _LONG_LITERAL:
        return None
    m = _SPLITTABLE_LITERAL_RE.match(text)
    if m is None:
        return None
    prefix, quote, body = m.group("prefix"), m.group("quote"), m.group("body")
    units: list[str] = []
    index = 0
    while index < len(body):
        if body[index] == quote:
            if body[index : index + 2] != quote * 2:
                return None  # a lone quote: not one literal
            units.append(quote * 2)
            index += 2
        elif prefix:
            units.append(body[index : index + 2])
            index += 2
        else:
            units.append(body[index])
            index += 1
    pieces: list[str] = []
    current = ""
    for unit in units:
        if current and len(current) + len(unit) > _LITERAL_CHUNK:
            pieces.append(f"{prefix}{quote}{current}{quote}")
            current = ""
        current += unit
    pieces.append(f"{prefix}{quote}{current}{quote}")
    return [pieces[0]] + [f"& {piece}" for piece in pieces[1:]]


def _operand_lines(head: str, value: str, indent: str) -> list[str]:
    """`head + value` as one line, or -- for a long literal -- the head with
    the literal's first piece, then each further `& piece` on its own
    line under `indent`."""
    pieces = _literal_pieces(value)
    if pieces is None:
        return [f"{head}{value}"]
    return [f"{head}{pieces[0]}"] + [f"{indent}{piece}" for piece in pieces[1:]]


_MOVE_HEAD_RE = re.compile(r"MOVE\s+", re.IGNORECASE)


def split_long_move(line: str, indent: str = "     ") -> list[str]:
    """`line` -- a `MOVE <value> TO <target>` statement, with its own
    leading indentation -- as one line, or, when `<value>` is one long
    literal, as `MOVE <first piece>` plus `& <piece>` lines under it
    (`_literal_pieces`), so no driver line passes cobc -free's 512-byte
    limit (issue #322). Anything else is returned unchanged: the value is
    whatever precedes the LAST ` TO `, and must be one whole literal, so a
    ` TO ` inside a literal can never split it wrongly."""
    stripped = line.lstrip()
    head = _MOVE_HEAD_RE.match(stripped)
    if head is None:
        return [line]
    to_at = stripped.upper().rfind(" TO ")
    if to_at <= head.end():
        return [line]
    pieces = _literal_pieces(stripped[head.end() : to_at])
    if pieces is None:
        return [line]
    lead = line[: len(line) - len(stripped)]
    lines = [f"{lead}MOVE {pieces[0]}"] + [
        f"{lead}{indent}{piece}" for piece in pieces[1:]
    ]
    lines[-1] += stripped[to_at:]
    return lines


#: Lines longer than this are wrapped (`wrap_words`), well under cobc
#: -free's 512-byte limit.
_WRAP_AT = 200


def wrap_words(line: str, width: int = 100) -> list[str]:
    """`line` as is when it is short, else wrapped at blanks onto lines of
    about `width` characters, each under the first's indentation plus four.
    A reset MOVE of an item nested 49 levels deep (NIST NC207A) names it
    with a 48-deep `IN` chain: past 512 bytes cobc truncated the line and
    the name came out ambiguous. A line holding a quote is left alone:
    a blank inside a literal is not a place to break it."""
    if len(line) <= _WRAP_AT or "'" in line or '"' in line:
        return [line]
    lead = line[: len(line) - len(line.lstrip())]
    words = line.split()
    lines: list[str] = []
    current = lead + words[0]
    for word in words[1:]:
        if len(current) + 1 + len(word) > width:
            lines.append(current)
            current = lead + "    " + word
        else:
            current += " " + word
    lines.append(current)
    return lines


def _display_operands(text: str) -> list[str]:
    """`text` as one or more quoted DISPLAY operands: one when short, else
    one per `_LITERAL_CHUNK` characters, so a long expected value never
    pushes the generated FAIL DISPLAY past cobc's line limit."""
    if len(text) <= _LONG_LITERAL:
        return [f'"{_display_text(text)}"']
    return [
        f'"{_display_text(text[start : start + _LITERAL_CHUNK])}"'
        for start in range(0, len(text), _LITERAL_CHUNK)
    ]


def _display_lines(indent: str, text: str, tail: str = "") -> list[str]:
    """`DISPLAY "<text>"<tail>` under `indent`, as one line when `text` is
    short, else with `text` cut into one quoted operand per line
    (`_display_operands`). A TESTSUITE / TESTCASE name or a MOCK SQL key is
    the user's own text and has no length limit: written into one DISPLAY
    literal, a long one pushed the line past cobc -free's 512 bytes, cobc
    truncated it and the instrumented program failed to compile with
    errors that blamed mockymock."""
    operands = _display_operands(text)
    if len(operands) == 1:
        return [f"{indent}DISPLAY {operands[0]}{tail}"]
    lines = [f"{indent}DISPLAY {operands[0]}"]
    lines.extend(f"{indent}    {operand}" for operand in operands[1:])
    lines[-1] += tail
    return lines


#: Closes a FAIL / RECORD marker that DISPLAYs a field's raw value (issue
#: #285): a value holding byte X'0A' -- a binary halfword of 10 in a group,
#: an LF in a PIC X -- splits its marker across lines, and every line
#: before this one is that value's continuation (no program code runs
#: between the two DISPLAYs). `report.results.parse_stdout` rejoins them.
VALUE_END_MARKER = "__MOCKYMOCK__ VALUE-END"
_VALUE_END_DISPLAY = f'               DISPLAY "{VALUE_END_MARKER}"'


#: The SECTION `cli.main._insert_driver` appends after the program's last
#: paragraph. Nothing PERFORMs it and the driver STOP RUNs before reaching
#: it, so control only arrives by running past the end of the program's
#: own code: a GO TO that left the PERFORMed range (a bare `PERFORM X`
#: whose GO TO X-EXIT then fell through every paragraph below). Before
#: it, the binary just ended -- `[CRASH] binary exited with code 4`, every
#: later case NOT RUN, and nothing saying why whenever the program had
#: set RETURN-CODE on the way (INTCALC). A SECTION, not a paragraph, so a
#: sectioned program's last SECTION still ends where it did.
END_OF_PROGRAM_TRAP = "UT-END-OF-PROGRAM"


def end_of_program_trap_lines() -> list[str]:
    """The `END_OF_PROGRAM_TRAP` section: fails the case that was running
    and names the likely cause, then lets the program end as before."""
    return [
        "",
        f"       {END_OF_PROGRAM_TRAP} SECTION.",
        f"       {END_OF_PROGRAM_TRAP}-PARA.",
        '           DISPLAY "__MOCKYMOCK__ CASE " FUNCTION TRIM(UT-CURRENT-CASE)',
        '               " FAIL: control ran past the last paragraph of the "',
        '               "program, so the binary ended mid-case -- a GO TO "',
        '               "left the PERFORMed range (PERFORM the paragraph "',
        '               "THRU its exit paragraph, as the program does?)"',
        "           ADD 1 TO UT-FAIL-COUNT.",
    ]


def end_of_program_lines_for(program_end: bool) -> list[str]:
    """What follows the program's last line: `program_end_lines()` when a
    main-line case runs THRU `UT-PROGRAM-END`, then the trap section."""
    return (program_end_lines() if program_end else []) + end_of_program_trap_lines()


@dataclass
class DriverArtifact:
    working_storage_lines: list[str]
    procedure_lines: list[str]
    # `build_driver(program_end=...)`: `cli.main._insert_driver` appends
    # the `UT-PROGRAM-END` paragraph after the program's last one.
    program_end: bool = False
    # `build_driver(call_frame=True)`: each case's PERFORM runs inside a
    # CALL of the program's own `CALL_FRAME_ENTRY`, so a terminator planned
    # with exit_kind "RETURN" can GOBACK to the case from any PERFORM depth;
    # `cli.main._insert_driver` marks the PROGRAM-ID RECURSIVE.
    call_frame: bool = False


#: The ENTRY a call-frame driver CALLs to run one case's PERFORM
#: (`build_driver(call_frame=True)`, 2026-11-03).
CALL_FRAME_ENTRY = "MOCKYMOCK-RUN-CASE"
CALL_FRAME_PARAGRAPH = "UT-RUN-CASE"


def call_frame_lines(suite: MockTestSuite) -> list[str]:
    """The paragraph a call-frame driver CALLs (`CALL_FRAME_ENTRY`): it
    runs the current case's PERFORM and returns. A terminator the case
    reaches GOBACKs out of it however deep in the program's own PERFORMs
    it sits (`TerminatorPlan.exit_kind` "RETURN"); GnuCOBOL's PERFORM
    stack is the CALL's own, so nothing of it is left behind."""
    lines = [
        f"       {CALL_FRAME_PARAGRAPH}.",
        f'           ENTRY "{CALL_FRAME_ENTRY}"',
        "           EVALUATE UT-CURRENT-CASE",
    ]
    for index, case in enumerate(suite.test_cases, start=1):
        lines.append(f'               WHEN "{index:03d}"')
        perform = f"                   PERFORM {case.perform_target}"
        if case.perform_thru:
            perform += f" THRU {case.perform_thru}"
        lines.append(perform)
    lines.append("           END-EVALUATE")
    lines.append("           GOBACK.")
    return lines


def program_end_lines() -> list[str]:
    """The paragraph a main-line case's terminator jumps to
    (`refusal.PROGRAM_END_PARAGRAPH`, `TerminatorPlan.exit_kind`
    "PROGRAM"): the end of that case's `PERFORM ... THRU` range, right
    after the program's last paragraph."""
    from mockymock.analysis.refusal import PROGRAM_END_PARAGRAPH

    return ["", f"       {PROGRAM_END_PARAGRAPH}.", "           EXIT."]


def _range_end(thru: str | None, program_end: str | None) -> str | None:
    """A PERFORM's THRU paragraph as the driver writes it: the program's
    last paragraph becomes `UT-PROGRAM-END` when the main line ends there."""
    if thru is not None and program_end is not None and thru == program_end:
        from mockymock.analysis.refusal import PROGRAM_END_PARAGRAPH

        return PROGRAM_END_PARAGRAPH
    return thru


_CASE_END_LINE_RE = re.compile(r'^\s*DISPLAY "__MOCKYMOCK__ CASE (\S+) END"\.$')


def build_driver(
    suite: MockTestSuite,
    reset_lines: list[str],
    registry: TallyRegistry,
    record_targets: dict[int, list[str]] | None = None,
    extra_working_storage_lines: list[str] | None = None,
    snapshot: StateSnapshot | None = None,
    condition_names: frozenset[str] | set[str] = frozenset(),
    numeric_edited: frozenset[str] | set[str] = frozenset(),
    behaviour: bool = False,
    returned: Sequence[str] = (),
    program_end: str | None = None,
    call_frame: bool = False,
) -> DriverArtifact:
    """`program_end` (`refusal.program_end_thru`): the program's last
    paragraph when a terminator ends the main line at `UT-PROGRAM-END`;
    every PERFORM THRU it then runs THRU `UT-PROGRAM-END` instead.

    `call_frame` (`refusal.needs_call_frame`): each case's own PERFORM
    runs inside a CALL of `CALL_FRAME_ENTRY` (`call_frame_lines`), for a
    terminator that GOBACKs to the case from inside the program's own
    PERFORMs."""
    # Collapse each run of non-COBOL-word characters to a single hyphen and
    # strip hyphens at the ends: a title like "X (via copybook)" must not
    # yield "X--VIA-COPYBOOK-" -- a COBOL word cannot end with a hyphen and
    # cobc rejects the paragraph header outright. Capped at IBM Enterprise
    # COBOL's 30-character user-defined-word limit (GnuCOBOL allows 63, but
    # `export` writes source for the IBM compiler, and every other generated
    # name already keeps to 30). Only its own header names this paragraph,
    # and the TESTSUITE marker DISPLAY carries the full suite name.
    sanitized = _SUITE_PARAGRAPH_NAME_RE.sub("-", suite.name.upper())
    sanitized = re.sub(r"-{2,}", "-", sanitized).strip("-")
    suite_paragraph = ("UT-TESTSUITE-" + sanitized)[:30].rstrip("-")

    # UT-CURRENT-CASE is X(9): case ids are zero-padded to 3 digits but grow
    # naturally past case 999 ("1000"), and a narrower field would truncate
    # the MOVE so case 1000 would execute case 100's mock branches. Tally
    # and fail-count fields are 9(9): at PIC 9(4) they silently wrapped at
    # 10,000, letting `VERIFY ... 500 TIMES` pass with 10,500 real calls
    # (batch loops of that size are realistic in the target domain).
    working_storage = [
        "01  UT-CURRENT-CASE        PIC X(9).",
        "01  UT-FAIL-COUNT          PIC 9(9) VALUE 0.",
        '01  UT-EARLY-EXIT          PIC X VALUE "N".',
        # The mocked outcome a replaced statement's own clause bodies are
        # selected by (analysis.clause_bodies, issue #209).
        '01  UT-MOCK-STATUS         PIC XX VALUE "00".',
    ]
    # Scratch field for VERIFY failure messages: tallies are PIC 9(9), so
    # displaying one directly prints "000000003"; moving it through this
    # Z-edited field and TRIMming yields a plain "3" in the FAIL line.
    if any(case.verifications for case in suite.test_cases):
        working_storage.append("01  UT-TALLY-EDITED        PIC Z(8)9.")
    if any(
        _compares_by_value(expectation, numeric_edited)
        for case in suite.test_cases
        for expectation in case.expectations
    ):
        working_storage.append(f"01  {_DEEDIT_FIELD}            PIC S9(18)V9(13).")
    for (category, key), tally in registry.items():
        working_storage.append(f"01  {tally}      PIC 9(9) VALUE 0.")
        working_storage.append(
            f"01  {registry.base_name(category, key)}      PIC 9(9) VALUE 0."
        )
    for category, key in _resumed_keys(suite):
        working_storage.append(
            f"01  {registry.start_name(category, key)}      PIC 9(9) VALUE 0."
        )
    for category, key in registry.rewound_keys():
        working_storage.append(
            f"01  {registry.rewind_name(category, key)}      PIC 9(9) VALUE 0."
        )
    if extra_working_storage_lines:
        working_storage.extend(extra_working_storage_lines)

    # BEFORE-ALL hands its state to every case through a snapshot taken
    # right after it (splicer.snapshot); without BEFORE-ALL steps there is
    # nothing to hand over, and each case starts from the reset as always.
    restore_state = bool(suite.before_all_steps and snapshot and snapshot.save_lines)

    procedure: list[str] = []
    procedure.append(f"       {suite_paragraph}.")
    procedure.extend(
        _display_lines("           ", f"__MOCKYMOCK__ TESTSUITE: {suite.name}")
    )
    if suite.before_all_steps:
        if reset_lines:
            procedure.append("           PERFORM UT-RESET-WORKING-STORAGE")
        procedure.extend(_suite_phase_lines(suite, registry, suite.before_all_steps))
        for resumed in _resumed_keys(suite):
            procedure.append(
                f"           MOVE {registry.name(*resumed)} TO "
                f"{registry.start_name(*resumed)}"
            )
            if registry.rewound(*resumed):
                # A case resumes the rows where BEFORE-ALL left them,
                # counted from BEFORE-ALL's last OPEN: each case starts
                # with no rewind of its own.
                procedure.append(
                    f"           SUBTRACT {registry.rewind_name(*resumed)} FROM "
                    f"{registry.start_name(*resumed)}"
                )
        if restore_state:
            procedure.append("           PERFORM UT-SAVE-STATE")
    for index in range(1, len(suite.test_cases) + 1):
        procedure.append(f"           PERFORM UT-TESTCASE-{index:03d}")
    if suite.after_all_steps:
        procedure.extend(_suite_phase_lines(suite, registry, suite.after_all_steps))
    procedure.append(
        f'           DISPLAY "__MOCKYMOCK__ SUMMARY: RUN={len(suite.test_cases)} '
        f'FAILURES=" UT-FAIL-COUNT'
    )
    # RETURN-CODE is whatever the last case's program left there, and STOP
    # RUN hands it to the OS: an all-pass suite whose last case set RC 8
    # exited 8, which `run` and `mutate` read as a failed binary (issue
    # #140). Pass/fail travels in the markers, not the exit status.
    procedure.append("           MOVE 0 TO RETURN-CODE")
    procedure.append("           STOP RUN.")
    procedure.append("")

    if reset_lines:
        procedure.append("       UT-RESET-WORKING-STORAGE.")
        for index, line in enumerate(reset_lines):
            last = index == len(reset_lines) - 1
            procedure.extend(wrap_words(f"           {line}" + ("." if last else "")))
        procedure.append("")

    if restore_state:
        assert snapshot is not None
        for paragraph, body in (
            ("UT-SAVE-STATE", snapshot.save_lines),
            ("UT-RESTORE-STATE", snapshot.restore_lines),
        ):
            procedure.append(f"       {paragraph}.")
            procedure.extend(f"           {line}" for line in body[:-1])
            procedure.append(f"           {body[-1]}.")
            procedure.append("")
        working_storage.extend(snapshot.working_storage_lines)

    for index, case in enumerate(suite.test_cases, start=1):
        procedure.extend(
            _build_testcase_paragraph(
                index,
                case,
                registry,
                bool(reset_lines),
                (record_targets or {}).get(index, []),
                suite=suite,
                restore_state=restore_state,
                condition_names=condition_names,
                numeric_edited=numeric_edited,
                call_frame=call_frame,
            )
        )
        procedure.append("")
    if call_frame:
        procedure.extend(call_frame_lines(suite))
        procedure.append("")

    if behaviour:
        # Baselines (`splicer.behaviour`): each case also reports what it
        # hands back to its caller (`returned`: the USING items or the
        # DFHCOMMAREA) and the RETURN-CODE it ended with, just before its
        # END marker.
        from mockymock.splicer.behaviour import LENGTH_DECLARATION, returned_lines

        working_storage.append(LENGTH_DECLARATION)
        with_rc: list[str] = []
        for line in procedure:
            match = _CASE_END_LINE_RE.match(line)
            if match is not None:
                with_rc.extend(returned_lines(list(returned), "           "))
                with_rc.append(
                    f'           DISPLAY "__MOCKYMOCK__ RC {match.group(1)}: " '
                    f"RETURN-CODE"
                )
            with_rc.append(line)
        procedure = with_rc

    if program_end is not None:
        procedure = [_with_program_end(line, program_end) for line in procedure]
    return DriverArtifact(
        working_storage_lines=working_storage,
        procedure_lines=procedure,
        program_end=program_end is not None,
        call_frame=call_frame,
    )


def _with_program_end(line: str, program_end: str) -> str:
    """`line` with a driver `PERFORM X THRU <program_end>` redirected to
    `UT-PROGRAM-END` (`_range_end`)."""
    match = re.fullmatch(r"(\s*PERFORM \S+ THRU )(\S+)", line)
    if match is None:
        return line
    return match.group(1) + str(_range_end(match.group(2), program_end))


def _step_lines(steps: list[HookStep]) -> list[str]:
    lines: list[str] = []
    for step in steps:
        if step.kind == "MOVE":
            lines.extend(
                split_long_move(f"           {assign(step.value, step.target)}")
            )
        else:
            thru = f" THRU {step.thru}" if step.thru else ""
            lines.append(f"           PERFORM {step.target}{thru}")
    return lines


def _tally_zero_lines(mocks, registry: TallyRegistry) -> list[str]:
    lines = []
    for category, key in dict.fromkeys((m.category, m.key) for m in mocks):
        lines.append(f"           MOVE 0 TO {registry.name(category, key)}")
        if registry.rewound(category, key):
            lines.append(f"           MOVE 0 TO {registry.rewind_name(category, key)}")
    return lines


def _resumed_keys(suite: MockTestSuite) -> list[tuple]:
    """BEFORE-ALL mock keys whose ROWS cursor each case resumes from where
    the BEFORE-ALL steps left it (only when there are steps to consume
    rows)."""
    if not suite.before_all_steps:
        return []
    return list(dict.fromkeys((m.category, m.key) for m in suite.before_all_mocks))


def _case_tally_start_lines(
    case: MockTestCase, registry: TallyRegistry, suite: MockTestSuite | None
) -> list[str]:
    """Case-start values of each mocked key's tally and VERIFY baseline.

    The tally is also the ROWS cursor (injector.build_rows_block), so it
    must continue across hook steps rather than restart: a row a priming
    READ in BEFORE-EACH or BEFORE-ALL consumed was handed out again in the
    case (issue #223). A key the case inherits from BEFORE-ALL resumes at
    the count BEFORE-ALL left (its -START field); every other key starts at
    0. The baseline starts equal to the tally, so VERIFY counts nothing
    that happened before the case."""
    resumed = set(_resumed_keys(suite)) if suite is not None else set()
    inherited = {id(m) for m in suite.before_all_mocks} if suite is not None else set()
    lines: list[str] = []
    seen: set[tuple] = set()
    for mock in case.mocks:
        key = (mock.category, mock.key)
        if key in seen:
            continue
        seen.add(key)
        tally = registry.name(*key)
        start = (
            registry.start_name(*key)
            if key in resumed and id(mock) in inherited
            else "0"
        )
        lines.append(f"           MOVE {start} TO {tally}")
        lines.append(f"           MOVE {tally} TO {registry.base_name(*key)}")
        if registry.rewound(*key):
            lines.append(f"           MOVE 0 TO {registry.rewind_name(*key)}")
    return lines


def _tally_baseline_lines(mocks, registry: TallyRegistry) -> list[str]:
    """After a BEFORE-EACH PERFORM: VERIFY counts from here on, while the
    tally (the ROWS cursor) keeps the rows the hook consumed."""
    return [
        f"           MOVE {registry.name(*key)} TO {registry.base_name(*key)}"
        for key in dict.fromkeys((m.category, m.key) for m in mocks)
    ]


def _suite_phase_lines(
    suite: MockTestSuite, registry: TallyRegistry, steps: list[HookStep]
) -> list[str]:
    """BEFORE-ALL/AFTER-ALL steps, run outside any test case: dispatched
    under SUITE_PHASE_ID, where BEFORE-ALL's mocks answer (injector)."""
    return (
        [
            f'           MOVE "{SUITE_PHASE_ID}" TO UT-CURRENT-CASE',
            '           MOVE "N" TO UT-EARLY-EXIT',
        ]
        + _tally_zero_lines(suite.before_all_mocks, registry)
        + _step_lines(steps)
    )


def _build_testcase_paragraph(
    index: int,
    case: MockTestCase,
    registry: TallyRegistry,
    has_reset: bool,
    record_names: list[str] | None = None,
    suite: MockTestSuite | None = None,
    restore_state: bool = False,
    condition_names: frozenset[str] | set[str] = frozenset(),
    numeric_edited: frozenset[str] | set[str] = frozenset(),
    call_frame: bool = False,
) -> list[str]:
    case_id = f"{index:03d}"
    case_mocks = {(mock.category, mock.key) for mock in case.mocks}
    # CAPTURE target -> (tally, baseline) of the mock that fills it.
    capture_tallies = {
        target.upper(): (
            registry.name(mock.category, mock.key),
            registry.base_name(mock.category, mock.key),
        )
        for mock in case.mocks
        for _, target in mock.captures
    }
    before_each = suite.before_each_steps if suite is not None else []
    after_each = suite.after_each_steps if suite is not None else []
    lines = [f"       UT-TESTCASE-{case_id}."]

    if has_reset:
        lines.append("           PERFORM UT-RESET-WORKING-STORAGE")
    if restore_state:
        lines.append("           PERFORM UT-RESTORE-STATE")
    lines.append(f'           MOVE "{case_id}" TO UT-CURRENT-CASE')
    # Each case starts from RETURN-CODE 0, like a fresh run would: a
    # previous case's MOVE 8 TO RETURN-CODE otherwise leaked into this
    # case's EXPECT RETURN-CODE (issue #140).
    lines.append("           MOVE 0 TO RETURN-CODE")
    lines.append('           MOVE "N" TO UT-EARLY-EXIT')
    lines.extend(_case_tally_start_lines(case, registry, suite))
    lines.extend(
        _display_lines(
            "           ", f"__MOCKYMOCK__ CASE {case_id} START: {case.name}"
        )
    )

    if before_each:
        lines.extend(_step_lines(before_each))
        # VERIFY counts what the test's own PERFORM did: calls a BEFORE-EACH
        # PERFORM made are not the code under test.
        if any(step.kind == "PERFORM" for step in before_each):
            lines.extend(_tally_baseline_lines(case.mocks, registry))
            # A terminator a BEFORE-EACH PERFORM reached must not cut the
            # case's own PERFORM short.
            lines.append('           MOVE "N" TO UT-EARLY-EXIT')

    # A multi-call case's earlier calls. VERIFY counts these too: they are
    # the case's own code under test, unlike a BEFORE-EACH PERFORM's.
    for step in case.steps:
        lines.extend(_step_lines([step]))
        if step.kind == "PERFORM":
            # A terminator one call reached must not cut the next short.
            lines.append('           MOVE "N" TO UT-EARLY-EXIT')

    for value, target in case.setup_moves:
        set_line = truth_set(value, target)
        if set_line is not None:
            lines.append(f"           {set_line}")
            continue
        move = _operand_lines("           MOVE ", value, "                ")
        move[-1] += f" TO {target}"
        lines.extend(move)

    lines.append("")
    perform_line = f"           PERFORM {case.perform_target}"
    if case.perform_thru:
        perform_line += f" THRU {case.perform_thru}"
    if call_frame:
        # `call_frame_lines` runs this case's PERFORM for it.
        perform_line = f'           CALL "{CALL_FRAME_ENTRY}"'
    lines.append(perform_line)
    lines.append("")

    for expectation in case.expectations:
        asserted = _condition_name_truth(expectation)
        if asserted is not None:
            # `EXPECT <88-name> TO BE TRUE`: a condition-name is a condition,
            # not a value -- `IF FLAG-ON NOT = TRUE` does not compile and an
            # 88 cannot be DISPLAYed, so test it directly and report the
            # truth value it had instead (issue #189).
            lines.append(
                f"           IF {'NOT ' if asserted else ''}{expectation.data_name}"
            )
            got = "FALSE" if asserted else "TRUE"
            lines.extend(
                _display_lines(
                    "               ",
                    f"__MOCKYMOCK__ CASE {case_id} FAIL: expected "
                    f"{expectation.data_name} {expectation.operator} "
                    f"{expectation.expected_value}, got {got}",
                )
            )
            lines.append("               ADD 1 TO UT-FAIL-COUNT")
            lines.append("           END-IF")
            continue
        if _compares_by_value(expectation, numeric_edited):
            # `EXPECT WS-BAL TO BE 100.00` on `PIC Z,ZZZ,ZZ9.99`: a
            # numeric-edited item compares as its edited text, so the bare
            # number never matched `"      100.00"` (issue #350). A MOVE
            # to a numeric item de-edits it -- the standard de-editing
            # MOVE, CR/DB, `*` and currency included -- and the value is
            # compared as a number. A quoted string stays byte-exact.
            lines.append(f"           MOVE {expectation.data_name} TO {_DEEDIT_FIELD}")
            lines.append(
                f"           IF {_DEEDIT_FIELD} "
                f"{_expect_fail_condition(expectation.operator)} "
                f"{expectation.expected_value.strip()}"
            )
        elif _has_combined_tail(expectation.expected_value):
            # `TO BE > 0 AND < 10` / `TO BE 7 OR 8`: an abbreviated combined
            # condition. Swapping the operator would negate only its first
            # relation (`X NOT > 0 AND < 10`), so negate the whole condition
            # instead (issue #265). A negated operator (`NOT TO BE 7 OR 8`)
            # would carry its NOT onto every abbreviated relation in the
            # tail (`X NOT = 7 OR NOT = 8`, always true), so the failure
            # guard is the un-negated condition itself (issue #339).
            operator = expectation.operator
            if operator.startswith("NOT "):
                lines.append(
                    f"           IF ({expectation.data_name} "
                    f"{operator[len('NOT '):]} {expectation.expected_value})"
                )
            else:
                lines.append(
                    f"           IF NOT ({expectation.data_name} "
                    f"{operator} {expectation.expected_value})"
                )
        else:
            fail_operator = _expect_fail_condition(expectation.operator)
            lines.extend(
                _operand_lines(
                    f"           IF {expectation.data_name} {fail_operator} ",
                    expectation.expected_value,
                    "               ",
                )
            )
        if _literal_pieces(expectation.expected_value) is None:
            lines.extend(
                _display_lines(
                    "               ",
                    f"__MOCKYMOCK__ CASE {case_id} FAIL: expected "
                    f"{expectation.data_name} {expectation.operator} "
                    f"{expectation.expected_value}, got ",
                    f" {expectation.data_name}",
                )
            )
            lines.append(_VALUE_END_DISPLAY)
        else:
            lines.append(
                f'               DISPLAY "__MOCKYMOCK__ CASE {case_id} FAIL: '
                f'expected {expectation.data_name} {expectation.operator} "'
            )
            lines.extend(
                f"                   {operand}"
                for operand in _display_operands(expectation.expected_value)
            )
            lines.append(f'                   ", got " {expectation.data_name}')
            lines.append(_VALUE_END_DISPLAY)
        lines.append("               ADD 1 TO UT-FAIL-COUNT")
        lines.append("           END-IF")

    for verification in case.verifications:
        if (verification.category, verification.key) not in case_mocks:
            raise ValueError(
                f"VERIFY references {verification.category.keyword} "
                f"{verification.key!r}, which no MOCK directive in this TESTCASE "
                f"declares (should have been refused before codegen)"
            )
        tally = registry.name(verification.category, verification.key)
        base = registry.base_name(verification.category, verification.key)
        count = f"({tally} - {base})"
        condition = _verify_condition(verification.expectation, count)
        lines.append(f"           IF {condition}")
        lines.append(f"               COMPUTE UT-TALLY-EDITED = {tally} - {base}")
        lines.extend(
            _display_lines(
                "               ",
                f"__MOCKYMOCK__ CASE {case_id} FAIL: VERIFY "
                f"{verification.category.keyword} {verification.key} WAS CALLED "
                f"{verification.expectation}, got ",
                " FUNCTION TRIM(UT-TALLY-EDITED)",
            )
        )
        lines.append("               ADD 1 TO UT-FAIL-COUNT")
        lines.append("           END-IF")

    # --record-expectations only: one marker per still-open stub this case
    # covers, emitted at the exact point a real EXPECT for that field would
    # run. Mirrors the FAIL line's own proven-safe "literal DISPLAY text
    # followed by a bare identifier" shape so GnuCOBOL renders the field in
    # its native PICTURE formatting -- no new codegen primitive needed.
    # Unlike the --trace MOCK: marker (which has no case id in scope at its
    # splice site), record_names is built here with case_id already known,
    # so this marker carries one and is attributed by id, not position.
    for name in record_names or []:
        if name.partition("(")[0].strip().upper() in condition_names:
            # A level-88 condition-name cannot be DISPLAYed ("condition-name
            # not allowed here" failed the whole recording build, issue
            # #237): record its truth value instead.
            marker = f"__MOCKYMOCK__ RECORD {case_id} {name}: "
            lines.append(f"           IF {name}")
            lines.append(f'               DISPLAY "{marker}TRUE"')
            lines.append("           ELSE")
            lines.append(f'               DISPLAY "{marker}FALSE"')
            lines.append("           END-IF")
            continue
        record = [
            f'           DISPLAY "__MOCKYMOCK__ RECORD {case_id} {name}: " {name}',
            _VALUE_END_DISPLAY.replace("               ", "           ", 1),
        ]
        capture = capture_tallies.get(name.partition("(")[0].strip().upper())
        if capture is None:
            lines.extend(record)
            continue
        # A CAPTURE target holds its initial value when the mocked CALL
        # never ran in this case: say so instead of recording that value
        # as "the argument passed" (issue #384).
        lines.append(f"           IF {capture[0]} = {capture[1]}")
        lines.append(
            f'               DISPLAY "__MOCKYMOCK__ UNREACHED {case_id} {name}"'
        )
        lines.append("           ELSE")
        lines.extend(f"    {line}" for line in record)
        lines.append("           END-IF")

    if any(step.kind == "PERFORM" for step in after_each):
        # Nor may one the case's PERFORM reached cut AFTER-EACH short: a
        # hook paragraph on a terminator chain checks this flag too.
        lines.append('           MOVE "N" TO UT-EARLY-EXIT')
    lines.extend(_step_lines(after_each))
    lines.append(f'           DISPLAY "__MOCKYMOCK__ CASE {case_id} END".')
    return lines


# EXPECT asserts <name> <operator> <value>; the generated IF guards the
# *failure* branch, so each operator compiles to its own negation. The
# ">="/"<=" rows use the equivalent plain relation ("<"/">") rather than a
# NOT-prefixed compound, keeping the emitted conditions to the simplest
# COBOL-85 relational forms. Keys must cover exactly the operators
# parser.py's _expect_operator can produce (model.EXPECT_OPERATORS) --
# keep the two in sync.
_EXPECT_FAIL_CONDITIONS = {
    "=": "NOT =",
    "NOT =": "=",
    ">": "NOT >",
    "NOT >": ">",
    "<": "NOT <",
    "NOT <": "<",
    ">=": "<",
    "NOT >=": ">=",
    "<=": ">",
    "NOT <=": "<=",
}


#: The numeric item an EXPECT on a numeric-edited field de-edits into: 31
#: digits, Enterprise COBOL's ARITH(EXTEND) maximum, so `export` stays
#: compilable there too.
_DEEDIT_FIELD = "UT-DEEDIT-VALUE"
_NUMERIC_LITERAL_RE = re.compile(r"^[+-]?(?:\d+(?:[.,]\d+)?|[.,]\d+)$")


def _compares_by_value(expectation, numeric_edited: frozenset[str] | set[str]) -> bool:
    """Whether an EXPECT compares a numeric-edited field with an unquoted
    number, i.e. by de-edited value rather than as edited text (issue
    #350). A reference-modified name is alphanumeric, so it never does."""
    if not numeric_edited:
        return False
    if not _NUMERIC_LITERAL_RE.match(expectation.expected_value.strip()):
        return False
    base, paren, subscript = expectation.data_name.partition("(")
    if paren and ":" in subscript:
        return False
    words = base.split()
    return bool(words) and words[0].upper() in numeric_edited


def _condition_name_truth(expectation) -> bool | None:
    """For `EXPECT <name> [NOT] TO BE TRUE|FALSE`, whether the condition-name
    is asserted to hold; None for every other EXPECT. TRUE and FALSE are
    not values any data item can be compared with, so the form can only
    mean a level-88 condition-name. The DSL parser refuses them with an
    ordering comparison, leaving `=` and `NOT =` here."""
    value = expectation.expected_value.strip().upper()
    if value not in ("TRUE", "FALSE") or expectation.operator not in ("=", "NOT ="):
        return None
    return (value == "TRUE") != (expectation.operator == "NOT =")


_QUOTED_LITERAL_RE = re.compile(r"\"(?:[^\"]|\"\")*\"|'(?:[^']|'')*'")
_COMBINING_WORD_RE = re.compile(r"(?<![\w-])(?:AND|OR)(?![\w-])", re.IGNORECASE)


def _has_combined_tail(value: str) -> bool:
    """Whether an EXPECT value carries an unquoted AND/OR, i.e. the
    assertion is an abbreviated combined condition (`> 0 AND < 10`)."""
    return bool(_COMBINING_WORD_RE.search(_QUOTED_LITERAL_RE.sub('""', value)))


def _expect_fail_condition(operator: str) -> str:
    try:
        return _EXPECT_FAIL_CONDITIONS[operator]
    except KeyError:
        raise ValueError(f"unrecognized EXPECT operator: {operator!r}") from None


def _verify_condition(expectation: str, tally_field: str) -> str:
    expectation = expectation.strip().upper()
    if expectation == "ONCE":
        return f"{tally_field} NOT = 1"
    if expectation == "NEVER":
        return f"{tally_field} NOT = 0"
    if expectation == "AT LEAST ONCE":
        return f"{tally_field} < 1"
    m = re.match(r"^(\d+)\s+TIMES$", expectation)
    if m:
        return f"{tally_field} NOT = {m.group(1)}"
    raise ValueError(f"unrecognized VERIFY expectation: {expectation!r}")
