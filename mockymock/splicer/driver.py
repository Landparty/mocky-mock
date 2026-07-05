"""Generates the UT-TESTSUITE-*/UT-TESTCASE-*/UT-RESET-WORKING-STORAGE
driver paragraphs, plus the WORKING-STORAGE bookkeeping fields they need.

These become the new PROCEDURE DIVISION entry point: prepended before the
program's own paragraphs, so the original first paragraph never runs
automatically (PROCEDURE DIVISION execution starts at the first paragraph
after the header, and the driver paragraphs come first).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from mockymock.dsl.model import MockTestCase, MockTestSuite
from mockymock.splicer.naming import TallyRegistry

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
    suite: MockTestSuite, reset_lines: list[str], registry: TallyRegistry
) -> DriverArtifact:
    # Collapse each run of non-COBOL-word characters to a single hyphen and
    # strip hyphens at the ends: a title like "X (via copybook)" must not
    # yield "X--VIA-COPYBOOK-" -- a COBOL word cannot end with a hyphen and
    # cobc rejects the paragraph header outright. Capped well under
    # GnuCOBOL's 63-character word limit.
    sanitized = _SUITE_PARAGRAPH_NAME_RE.sub("-", suite.name.upper())
    sanitized = re.sub(r"-{2,}", "-", sanitized).strip("-")
    suite_paragraph = ("UT-TESTSUITE-" + sanitized)[:60].rstrip("-")

    working_storage = [
        "01  UT-CURRENT-CASE        PIC X(3).",
        "01  UT-FAIL-COUNT          PIC 9(4) VALUE 0.",
    ]
    for _, tally in registry.items():
        working_storage.append(f"01  {tally}      PIC 9(4) VALUE 0.")

    procedure: list[str] = []
    procedure.append(f"       {suite_paragraph}.")
    procedure.append(f'           DISPLAY "__MOCKYMOCK__ TESTSUITE: {suite.name}"')
    for index in range(1, len(suite.test_cases) + 1):
        procedure.append(f"           PERFORM UT-TESTCASE-{index:03d}")
    procedure.append(
        f'           DISPLAY "__MOCKYMOCK__ SUMMARY: RUN={len(suite.test_cases)} '
        f'FAILURES=" UT-FAIL-COUNT'
    )
    procedure.append("           STOP RUN.")
    procedure.append("")

    if reset_lines:
        procedure.append("       UT-RESET-WORKING-STORAGE.")
        for line in reset_lines[:-1]:
            procedure.append(f"           {line}")
        procedure.append(f"           {reset_lines[-1]}.")
        procedure.append("")

    for index, case in enumerate(suite.test_cases, start=1):
        procedure.extend(
            _build_testcase_paragraph(index, case, registry, bool(reset_lines))
        )
        procedure.append("")

    return DriverArtifact(
        working_storage_lines=working_storage, procedure_lines=procedure
    )


def _build_testcase_paragraph(
    index: int, case: MockTestCase, registry: TallyRegistry, has_reset: bool
) -> list[str]:
    case_id = f"{index:03d}"
    case_mocks = {(mock.category, mock.key) for mock in case.mocks}
    lines = [f"       UT-TESTCASE-{case_id}."]

    if has_reset:
        lines.append("           PERFORM UT-RESET-WORKING-STORAGE")
    lines.append(f'           MOVE "{case_id}" TO UT-CURRENT-CASE')
    for category, key in dict.fromkeys((m.category, m.key) for m in case.mocks):
        lines.append(f"           MOVE 0 TO {registry.name(category, key)}")
    lines.append(
        f'           DISPLAY "__MOCKYMOCK__ CASE {case_id} START: '
        f'{_display_text(case.name)}"'
    )

    for value, target in case.setup_moves:
        lines.append(f"           MOVE {value} TO {target}")

    lines.append("")
    lines.append(f"           PERFORM {case.perform_target}")
    lines.append("")

    for expectation in case.expectations:
        lines.append(
            f"           IF {expectation.data_name} NOT = {expectation.expected_value}"
        )
        lines.append(
            f'               DISPLAY "__MOCKYMOCK__ CASE {case_id} FAIL: expected '
            f'{expectation.data_name} = {_display_text(expectation.expected_value)}"'
        )
        lines.append("               ADD 1 TO UT-FAIL-COUNT")
        lines.append("           END-IF")

    for verification in case.verifications:
        if (verification.category, verification.key) not in case_mocks:
            raise ValueError(
                f"VERIFY references {verification.category.value} "
                f"{verification.key!r}, which no MOCK directive in this TESTCASE "
                f"declares (should have been refused before codegen)"
            )
        tally = registry.name(verification.category, verification.key)
        condition = _verify_condition(verification.expectation, tally)
        lines.append(f"           IF {condition}")
        lines.append(
            f'               DISPLAY "__MOCKYMOCK__ CASE {case_id} FAIL: VERIFY '
            f'{verification.category.value} {_display_text(verification.key)} WAS CALLED '
            f'{verification.expectation}"'
        )
        lines.append("               ADD 1 TO UT-FAIL-COUNT")
        lines.append("           END-IF")

    lines.append(f'           DISPLAY "__MOCKYMOCK__ CASE {case_id} END".')
    return lines


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
