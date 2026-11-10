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


def is_sql_declaration(text: str) -> bool:
    """A precompiler declaration other than WHENEVER -- `DECLARE ...
    CURSOR/TABLE/STATEMENT`, `INCLUDE`, `BEGIN/END DECLARE SECTION`: DB2
    generates no runtime call for it and never touches the SQLCA, so in
    the PROCEDURE DIVISION it is not a boundary (issue #267)."""
    return bool(_DECLARATIVE_RE.match(text.strip())) and not is_whenever(text)


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
    from mockymock.analysis._program_walk import (
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


def whenever_lines(program) -> dict[str, int]:
    """GO TO target -> the source line of the first `EXEC SQL WHENEVER ...
    GO TO <target>` naming it, for messages."""
    found: dict[str, int] = {}
    for statement in _procedure_sql_statements(program):
        text = _sql_text(statement)
        if not is_whenever(text):
            continue
        parsed = parse_whenever(text)
        if parsed.target and parsed.target not in found:
            location = getattr(statement, "location", None)
            found[parsed.target] = getattr(location, "line", 0) or 0
    return found


#: The SQLCA fields a WHENEVER check reads, and the SQLCA itself.
_SQLCA_WORD_RE = re.compile(
    r"(?<![A-Z0-9-])(?:SQLCODE|SQLCA|SQLWARN[0-9A-Z]?|SQLSTATE)(?![A-Z0-9-])"
)
_LITERAL_SQLCODE_MOVE_RE = re.compile(
    r"(?<![A-Z0-9-])MOVE\s+([+-]?\d+)\s+TO\s+SQLCODE(?![A-Z0-9-])(?!\s+(?:OF|IN)\b)"
)
#: Words that make a mock body's last SQLCODE value depend on control flow.
_CONDITIONAL_WORD_RE = re.compile(
    r"(?<![A-Z0-9-])(?:IF|ELSE|EVALUATE|WHEN|PERFORM|GO|SEARCH|"
    r"ON|AT|INVALID|NOT)(?![A-Z0-9-])"
)
_STRING_LITERAL_RE = re.compile(r"\"[^\"]*\"|'[^']*'")


def _fires(condition: str, sqlcode: int) -> bool:
    if condition == "SQLERROR":
        return sqlcode < 0
    if condition == "NOT FOUND":
        return sqlcode == 100
    return True  # SQLWARNING also reads SQLWARN0: never proven quiet


def whenever_can_fire(program, mocks) -> bool:
    """Whether a test case with these MOCK directives in force can make any
    emulated `EXEC SQL WHENEVER ... GO TO` jump (issue #244).

    Fail closed: False only when every SQL mock provably leaves SQLCODE at
    a value no active condition fires on -- a body with no control flow
    whose every SQLCODE reference is `MOVE <integer> TO SQLCODE`, or a ROWS
    mock (each row starts from SQLCODE 0, exhaustion sets 100) whose rows
    set no firing SQLCODE while NOT FOUND is inactive. An active
    SQLWARNING (it also reads SQLWARN0) always counts as able to fire."""
    from mockymock.dsl.model import MockCategory

    active = {
        condition
        for checks in whenever_actions(program).values()
        for condition, _ in checks
    }
    if not active:
        return False
    if "SQLWARNING" in active:
        return True
    for directive in mocks:
        if directive.category is not MockCategory.SQL:
            continue
        if directive.rows is not None:
            if "NOT FOUND" in active:
                return True
            for row in directive.rows:
                for name, value in row:
                    if not _SQLCA_WORD_RE.fullmatch(" ".join(name.upper().split())):
                        continue
                    try:
                        code = int(value.strip())
                    except ValueError:
                        return True
                    if any(_fires(c, code) for c in active):
                        return True
            continue
        body = _STRING_LITERAL_RE.sub(
            "''", " ".join(" ".join(directive.body_lines).upper().split())
        )
        if _CONDITIONAL_WORD_RE.search(body):
            return True
        moves = _LITERAL_SQLCODE_MOVE_RE.findall(body)
        if not moves or len(_SQLCA_WORD_RE.findall(body)) != len(moves):
            return True
        if any(_fires(c, int(code)) for code in moves for c in active):
            return True
    return False
