"""`EXEC SQL WHENEVER` emulation (issue #195).

WHENEVER is a precompiler declaration, not a runtime statement: DB2's
precompiler rewrites every *later* executable SQL statement, in physical
source order (not execution order), into the statement followed by

    IF SQLCODE < 0 GO TO <label>                      (SQLERROR)
    IF SQLWARN0 = 'W' OR SQLCODE > 0 AND NOT = 100 .. (SQLWARNING)
    IF SQLCODE = 100 GO TO <label>                    (NOT FOUND)

until another WHENEVER for the same condition replaces it (`CONTINUE`
switches the check off). Mocking WHENEVER as an ordinary SQL boundary lost
that control flow, so a mocked SQL error never reached the handler.

This module is the one place that reads WHENEVER: `mock_surface` keeps
WHENEVER statements out of the mockable boundary sites, the splicer
replaces each with CONTINUE and appends the checks after every mocked
SQL dispatch, and the reachability walk follows each check's GO TO like
a real one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from cobolparser.models.sql_statements import ExecSQLStatement

#: Condition keyword (normalized) in the order DB2's generated checks run.
CONDITIONS = ("SQLERROR", "SQLWARNING", "NOT FOUND")

_WHENEVER_RE = re.compile(
    r"^WHENEVER\s+(?P<cond>SQLERROR|SQLWARNING|NOT\s+FOUND|NOTFOUND)\s+"
    r"(?:(?P<cont>CONTINUE)|(?:GO\s*TO)\s+:?(?P<label>[A-Z0-9][A-Z0-9-]*))\s*$",
    re.IGNORECASE,
)

#: SQL verbs the precompiler never follows with a WHENEVER check: they are
#: declarations, not statements that run and set SQLCODE.
_DECLARATIVE_RE = re.compile(
    r"^(?:WHENEVER|INCLUDE|DECLARE|BEGIN\s+DECLARE|END\s+DECLARE)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Whenever:
    """One parsed `WHENEVER <condition> <action>`: `target` is the GO TO
    paragraph/section (uppercased), None for CONTINUE; `problem` says why
    the text could not be read (the other fields are then empty)."""

    condition: str = ""
    target: str | None = None
    problem: str | None = None


def is_whenever(text: str) -> bool:
    return " ".join(text.upper().split()).startswith("WHENEVER ")


def parse_whenever(text: str) -> Whenever:
    normalized = " ".join(text.split())
    match = _WHENEVER_RE.match(normalized)
    if match is None:
        return Whenever(
            problem=(
                f"'EXEC SQL {normalized}' is not a WHENEVER SQLERROR/"
                f"SQLWARNING/NOT FOUND with CONTINUE or GO TO <paragraph>"
            )
        )
    condition = " ".join(match.group("cond").upper().split())
    if condition == "NOTFOUND":
        condition = "NOT FOUND"
    if match.group("cont"):
        return Whenever(condition=condition)
    return Whenever(condition=condition, target=match.group("label").upper())


def _sql_text(statement) -> str:
    return str(getattr(statement, "sql_text", "") or "")


def _executable(statement) -> bool:
    return not _DECLARATIVE_RE.match(_sql_text(statement).strip())


def _procedure_sql_statements(program) -> list:
    """Every EXEC SQL statement in the PROCEDURE DIVISION, nested bodies
    included, in physical source order."""
    # Imported here: mock_surface imports this module.
    from mockymock.analysis.mock_surface import (
        _all_paragraphs,
        _nested_statement_lists,
    )

    procedure = program.get_division("PROCEDURE") if program is not None else None
    if procedure is None:
        return []
    found: list = []

    def walk(statements: list) -> None:
        for statement in statements:
            if isinstance(statement, ExecSQLStatement):
                found.append(statement)
            for nested in _nested_statement_lists(statement):
                walk(nested)

    for paragraph in _all_paragraphs(procedure):
        walk(paragraph.statements)

    def position(statement) -> tuple[int, int]:
        location = getattr(statement, "location", None)
        return (
            getattr(location, "line", 0) or 0,
            getattr(location, "column", 0) or 0,
        )

    return sorted(found, key=position)


def whenever_actions(program) -> dict[int, tuple[tuple[str, str], ...]]:
    """id(executable EXEC SQL statement) -> the (condition, GO TO target)
    checks DB2 would run after it, in `CONDITIONS` order. Statements with
    no active GO TO are absent. Cached on the program object: the
    reachability walk asks once per test case."""
    cached = getattr(program, "_mockymock_sql_whenever", None)
    if cached is not None:
        return cached
    active: dict[str, str | None] = {}
    actions: dict[int, tuple[tuple[str, str], ...]] = {}
    for statement in _procedure_sql_statements(program):
        text = _sql_text(statement)
        if is_whenever(text):
            parsed = parse_whenever(text)
            if parsed.problem is None:
                active[parsed.condition] = parsed.target
            continue
        if not _executable(statement):
            continue
        checks = tuple(
            (condition, target)
            for condition in CONDITIONS
            if (target := active.get(condition))
        )
        if checks:
            actions[id(statement)] = checks
    try:
        program._mockymock_sql_whenever = actions
    except AttributeError:  # pragma: no cover - a slotted/frozen node
        pass
    return actions


def whenever_targets(program) -> set[str]:
    """Every paragraph/section a WHENEVER check can GO TO."""
    return {
        target for checks in whenever_actions(program).values() for _, target in checks
    }


_CHECK_CONDITIONS = {
    "SQLERROR": "SQLCODE < 0",
    "SQLWARNING": 'SQLWARN0 = "W" OR (SQLCODE > 0 AND SQLCODE NOT = 100)',
    "NOT FOUND": "SQLCODE = 100",
}


def whenever_check_lines(checks: tuple[tuple[str, str], ...]) -> list[str]:
    """The COBOL the precompiler would append after one SQL statement."""
    lines: list[str] = []
    for condition, target in checks:
        lines.append(f"IF {_CHECK_CONDITIONS[condition]}")
        lines.append(f"    GO TO {target}")
        lines.append("END-IF")
    return lines
