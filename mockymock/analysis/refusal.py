"""Refusal gate: whole-program (parse errors) and per-TESTCASE
(dynamic CALL / file I/O / EXEC reachable from PERFORM target, or an
unmatched MOCK CALL directive) checks.

Reachability is computed with a self-contained BFS over PerformStatement
targets within the same program -- not cobolparser's ProgramFlowAnalyzer --
because that keeps this module's correctness checkable against the same
small set of verified attributes (CobolParagraph.statements,
PerformStatement.target_paragraph) the rest of mockymock already depends
on, rather than additionally depending on ProgramFlowAnalyzer's full edge
taxonomy. A CALL is a leaf: it is never traversed into, since the called
program's source isn't part of this compilation unit.
"""

from __future__ import annotations

from dataclasses import dataclass

from cobolparser.models.statements.control import PerformStatement

from mockymock.analysis.mock_surface import MockSurface, _all_paragraphs


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
    reachable = _reachable_paragraphs(program, perform_target)

    if perform_target not in reachable:
        reasons.append(
            RefusalReason(
                code="UNKNOWN_PARAGRAPH",
                message=f"PERFORM target '{perform_target}' not found in PROCEDURE DIVISION",
            )
        )
        return reasons

    reachable_call_names: set[str] = set()
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


def _reachable_paragraphs(program, start: str) -> set[str]:
    procedure = program.get_division("PROCEDURE")
    if procedure is None:
        return set()
    by_name = {p.paragraph_name: p for p in _all_paragraphs(procedure)}
    if start not in by_name:
        return set()

    seen: set[str] = set()
    stack = [start]
    while stack:
        name = stack.pop()
        if name in seen or name not in by_name:
            continue
        seen.add(name)
        for statement in by_name[name].statements:
            if isinstance(statement, PerformStatement) and statement.target_paragraph:
                stack.append(statement.target_paragraph)
    return seen
