"""Refusal gate: whole-program (parse errors) and per-TESTCASE
(dynamic CALL / file I/O / EXEC reachable from PERFORM target, an unmatched
MOCK CALL directive, or a MOCK CALL targeting a nested call site) checks.

Reachability is computed with a self-contained BFS over PerformStatement
targets within the same program -- not cobolparser's ProgramFlowAnalyzer --
because that keeps this module's correctness checkable against the same
small set of verified attributes (CobolParagraph.statements,
PerformStatement.target_paragraph) the rest of mockymock already depends
on, rather than additionally depending on ProgramFlowAnalyzer's full edge
taxonomy. A CALL is a leaf: it is never traversed into, since the called
program's source isn't part of this compilation unit.

PerformStatements are discovered at any nesting depth -- including inside
IF/EVALUATE branches, inline PERFORM bodies, and IO clause bodies (AT END,
INVALID KEY, etc.) -- by reusing mock_surface.py's `_nested_statement_lists`
helper (see `_find_performs`), not a flat `paragraph.statements` scan.
PERFORM ... THRU targets are deliberately NOT range-expanded (that needs
paragraph source-order guarantees this module doesn't verify); instead, any
reachable paragraph containing a PERFORM ... THRU triggers its own
fail-closed refusal (UNSUPPORTED_PERFORM_THRU).

A MOCK CALL directive whose target call name has a *nested* reachable call
site (inside an IF/EVALUATE branch, inline PERFORM body, or similar) is
refused with UNSUPPORTED_NESTED_CALL_TARGET rather than spliced: the
splicer's replacement span depends on `source_map.py`'s boundary-list
approach, and cobolparser's AST has no location data for block terminators
(END-IF, END-EVALUATE, etc.), so a spliced nested CALL could swallow its
enclosing block's terminator and silently corrupt control flow. This is the
same fail-closed philosophy as UNSUPPORTED_PERFORM_THRU above -- refuse
rather than risk a wrong result. (An earlier fix attempt tried recursing the
splicer into nested bodies instead and discovered it corrupts control flow;
see task-14-report.md's "BLOCKED" section for the full analysis.)
"""

from __future__ import annotations

from dataclasses import dataclass

from cobolparser.models.statements.control import PerformStatement

from mockymock.analysis.mock_surface import (
    MockSurface,
    _all_paragraphs,
    _nested_statement_lists,
)


@dataclass
class RefusalReason:
    code: str
    message: str


def check_whole_program(parse_result) -> list[RefusalReason]:
    if parse_result.success:
        return []
    return [
        RefusalReason(
            code="PARSE_ERROR",
            message=f"cobolparser reported {len(parse_result.errors)} parse error(s)",
        )
    ]


def check_test_case(
    surface: MockSurface,
    program,
    perform_target: str,
    mocked_call_names: set[str],
) -> list[RefusalReason]:
    reasons: list[RefusalReason] = []
    reachable, thru_paragraphs = _reachable_paragraphs(program, perform_target)

    if perform_target not in reachable:
        reasons.append(
            RefusalReason(
                code="UNKNOWN_PARAGRAPH",
                message=f"PERFORM target '{perform_target}' not found in PROCEDURE DIVISION",
            )
        )
        return reasons

    for paragraph_name in sorted(thru_paragraphs):
        reasons.append(
            RefusalReason(
                code="UNSUPPORTED_PERFORM_THRU",
                message=(
                    f"paragraph '{paragraph_name}' uses PERFORM ... THRU, "
                    f"not supported in v1 (range expansion needs source-order "
                    f"guarantees not yet verified)"
                ),
            )
        )

    reachable_call_names: set[str] = set()
    nested_call_names: set[str] = set()
    for site in surface.call_sites:
        if site.paragraph_name not in reachable:
            continue
        if site.kind.value == "dynamic":
            reasons.append(
                RefusalReason(
                    code="DYNAMIC_CALL",
                    message=(
                        f"paragraph '{site.paragraph_name}' (line {site.line}) "
                        f"contains a dynamic CALL, not supported in v1"
                    ),
                )
            )
        else:
            reachable_call_names.add(site.program_name)
            if site.nested:
                nested_call_names.add(site.program_name)

    if reachable & surface.file_io_paragraphs:
        hit = sorted(reachable & surface.file_io_paragraphs)[0]
        reasons.append(
            RefusalReason(
                code="UNMOCKED_FILE_IO",
                message=f"paragraph '{hit}' performs file I/O, not mocked in v1",
            )
        )

    if reachable & surface.exec_paragraphs:
        hit = sorted(reachable & surface.exec_paragraphs)[0]
        reasons.append(
            RefusalReason(
                code="UNSUPPORTED_EXEC",
                message=f"paragraph '{hit}' contains EXEC SQL/CICS/DLI, not supported in v1",
            )
        )

    for name in sorted(mocked_call_names & nested_call_names):
        reasons.append(
            RefusalReason(
                code="UNSUPPORTED_NESTED_CALL_TARGET",
                message=(
                    f'MOCK CALL "{name}" matches a CALL statement nested inside '
                    f"a conditional/loop body (IF/EVALUATE/inline PERFORM), which "
                    f"cannot be safely spliced in v1 (cobolparser has no location "
                    f"data for block terminators like END-IF, so the splicer "
                    f"cannot determine where the nested statement's replacement "
                    f"span should end)"
                ),
            )
        )

    for name in mocked_call_names - reachable_call_names:
        reasons.append(
            RefusalReason(
                code="UNMATCHED_MOCK",
                message=(
                    f"MOCK CALL \"{name}\" does not match any static CALL "
                    f"site reachable from '{perform_target}'"
                ),
            )
        )

    return reasons


def _find_performs(statements: list) -> list[PerformStatement]:
    """Recursively collect every PerformStatement in `statements`, including
    ones nested inside IF/EVALUATE branches, inline PERFORM bodies, and IO
    clause bodies (AT END, INVALID KEY, etc.) -- reusing mock_surface.py's
    `_nested_statement_lists` rather than reimplementing nested-statement
    detection.
    """
    found = []
    for statement in statements:
        if isinstance(statement, PerformStatement):
            found.append(statement)
        for nested in _nested_statement_lists(statement):
            found.extend(_find_performs(nested))
    return found


def _reachable_paragraphs(program, start: str) -> tuple[set[str], set[str]]:
    """Return (reachable paragraph names, paragraph names containing a
    reachable PERFORM ... THRU), both computed in a single BFS pass over
    PerformStatement.target_paragraph edges. PERFORM ... THRU targets
    themselves are not followed -- see module docstring / check_test_case's
    UNSUPPORTED_PERFORM_THRU refusal for why range expansion is out of
    scope.
    """
    procedure = program.get_division("PROCEDURE")
    if procedure is None:
        return set(), set()
    by_name = {p.paragraph_name: p for p in _all_paragraphs(procedure)}
    if start not in by_name:
        return set(), set()

    seen: set[str] = set()
    thru_paragraphs: set[str] = set()
    stack = [start]
    while stack:
        name = stack.pop()
        if name in seen or name not in by_name:
            continue
        seen.add(name)
        for statement in _find_performs(by_name[name].statements):
            if statement.thru_paragraph:
                thru_paragraphs.add(name)
            if statement.target_paragraph:
                stack.append(statement.target_paragraph)
    return seen, thru_paragraphs
