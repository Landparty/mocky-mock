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
from dataclasses import dataclass

from mockymock.dsl.model import SUITE_PHASE_ID, HookStep, MockTestCase, MockTestSuite
from mockymock.splicer.naming import TallyRegistry
from mockymock.splicer.snapshot import StateSnapshot

_SUITE_PARAGRAPH_NAME_RE = re.compile(r"[^A-Z0-9-]")


def _display_text(text: str) -> str:
    """Escape a value for embedding inside a COBOL "..." DISPLAY literal:
    a quote inside a quoted literal is written as two quotes. Without this,
    EXPECT values like "OK" split the generated DISPLAY literal and cobc
    reads the remainder as undefined identifiers."""
    return text.replace('"', '""')


@dataclass
class DriverArtifact:
    working_storage_lines: list[str]
    procedure_lines: list[str]


def build_driver(
    suite: MockTestSuite,
    reset_lines: list[str],
    registry: TallyRegistry,
    record_targets: dict[int, list[str]] | None = None,
    extra_working_storage_lines: list[str] | None = None,
    snapshot: StateSnapshot | None = None,
) -> DriverArtifact:
    # Collapse each run of non-COBOL-word characters to a single hyphen and
    # strip hyphens at the ends: a title like "X (via copybook)" must not
    # yield "X--VIA-COPYBOOK-" -- a COBOL word cannot end with a hyphen and
    # cobc rejects the paragraph header outright. Capped well under
    # GnuCOBOL's 63-character word limit.
    sanitized = _SUITE_PARAGRAPH_NAME_RE.sub("-", suite.name.upper())
    sanitized = re.sub(r"-{2,}", "-", sanitized).strip("-")
    suite_paragraph = ("UT-TESTSUITE-" + sanitized)[:60].rstrip("-")

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
    for _, tally in registry.items():
        working_storage.append(f"01  {tally}      PIC 9(9) VALUE 0.")
    if extra_working_storage_lines:
        working_storage.extend(extra_working_storage_lines)

    # BEFORE-ALL hands its state to every case through a snapshot taken
    # right after it (splicer.snapshot); without BEFORE-ALL steps there is
    # nothing to hand over, and each case starts from the reset as always.
    restore_state = bool(suite.before_all_steps and snapshot and snapshot.save_lines)

    procedure: list[str] = []
    procedure.append(f"       {suite_paragraph}.")
    procedure.append(
        f'           DISPLAY "__MOCKYMOCK__ TESTSUITE: {_display_text(suite.name)}"'
    )
    if suite.before_all_steps:
        if reset_lines:
            procedure.append("           PERFORM UT-RESET-WORKING-STORAGE")
        procedure.extend(_suite_phase_lines(suite, registry, suite.before_all_steps))
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
        for line in reset_lines[:-1]:
            procedure.append(f"           {line}")
        procedure.append(f"           {reset_lines[-1]}.")
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
            )
        )
        procedure.append("")

    return DriverArtifact(
        working_storage_lines=working_storage, procedure_lines=procedure
    )


def _step_lines(steps: list[HookStep]) -> list[str]:
    lines: list[str] = []
    for step in steps:
        if step.kind == "MOVE":
            lines.append(f"           MOVE {step.value} TO {step.target}")
        else:
            thru = f" THRU {step.thru}" if step.thru else ""
            lines.append(f"           PERFORM {step.target}{thru}")
    return lines


def _tally_zero_lines(mocks, registry: TallyRegistry) -> list[str]:
    return [
        f"           MOVE 0 TO {registry.name(category, key)}"
        for category, key in dict.fromkeys((m.category, m.key) for m in mocks)
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
) -> list[str]:
    case_id = f"{index:03d}"
    case_mocks = {(mock.category, mock.key) for mock in case.mocks}
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
    for category, key in dict.fromkeys((m.category, m.key) for m in case.mocks):
        lines.append(f"           MOVE 0 TO {registry.name(category, key)}")
    lines.append(
        f'           DISPLAY "__MOCKYMOCK__ CASE {case_id} START: '
        f'{_display_text(case.name)}"'
    )

    if before_each:
        lines.extend(_step_lines(before_each))
        # VERIFY counts what the test's own PERFORM did: calls a BEFORE-EACH
        # PERFORM made are not the code under test.
        if any(step.kind == "PERFORM" for step in before_each):
            lines.extend(_tally_zero_lines(case.mocks, registry))
            # A terminator a BEFORE-EACH PERFORM reached must not cut the
            # case's own PERFORM short.
            lines.append('           MOVE "N" TO UT-EARLY-EXIT')

    for value, target in case.setup_moves:
        lines.append(f"           MOVE {value} TO {target}")

    lines.append("")
    perform_line = f"           PERFORM {case.perform_target}"
    if case.perform_thru:
        perform_line += f" THRU {case.perform_thru}"
    lines.append(perform_line)
    lines.append("")

    for expectation in case.expectations:
        fail_operator = _expect_fail_condition(expectation.operator)
        lines.append(
            f"           IF {expectation.data_name} {fail_operator} "
            f"{expectation.expected_value}"
        )
        lines.append(
            f'               DISPLAY "__MOCKYMOCK__ CASE {case_id} FAIL: expected '
            f"{expectation.data_name} {expectation.operator} "
            f"{_display_text(expectation.expected_value)}, "
            f'got " {expectation.data_name}'
        )
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
        condition = _verify_condition(verification.expectation, tally)
        lines.append(f"           IF {condition}")
        lines.append(f"               MOVE {tally} TO UT-TALLY-EDITED")
        lines.append(
            f'               DISPLAY "__MOCKYMOCK__ CASE {case_id} FAIL: VERIFY '
            f"{verification.category.keyword} {_display_text(verification.key)} WAS CALLED "
            f'{verification.expectation}, got " FUNCTION TRIM(UT-TALLY-EDITED)'
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
        lines.append(
            f'           DISPLAY "__MOCKYMOCK__ RECORD {case_id} {name}: " {name}'
        )

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
