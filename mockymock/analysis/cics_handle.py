"""`EXEC CICS HANDLE CONDITION` / `IGNORE CONDITION` emulation (issue #268).

HANDLE CONDITION registers a label: when a later command raises the named
condition, CICS transfers control there, like a GO TO. IGNORE CONDITION
makes a condition do nothing. Mocking the two as ordinary CICS boundaries
lost that control flow, so a program written in the HANDLE style (no RESP)
could never reach its NOTFND/ERROR handler in a test.

mockymock emulates them the way it emulates `EXEC SQL WHENEVER` (#195):

* `mock_surface` keeps HANDLE/IGNORE CONDITION out of the mockable
  boundary sites (into `whenever_sites`); the splicer replaces each one
  with CONTINUE.
* The condition -> label map in force at every other CICS command is
  tracked in *physical source order* (`handle_states`), the approximation
  the issue's option 1 settles on: HANDLE is a runtime registration, so a
  program that re-registers inside a loop or across PERFORMed paragraphs
  may differ.
* A `MOCK CICS` body may say `CONDITION IS <name>`: the mocked command
  then raises that condition -- the dispatch ends with `GO TO <label in
  force>` (`resolve_condition`), or does nothing under IGNORE. A condition
  with no handler (the real command would abend), a command written with
  RESP/NOHANDLE (HANDLE does not apply to it), or a program using PUSH/POP
  HANDLE is refused (`UNSUPPORTED_CICS_CONDITION`), never guessed.
* The reachability walk follows the handler labels a case's mocks can
  raise, so a handler's own boundaries must be mocked like any other.
"""

from __future__ import annotations

import re

from cobolparser.parsers.statements.ibm_exec_statements import ExecCicsStatement

#: The value a condition maps to under IGNORE CONDITION.
IGNORED = "(IGNORE)"

_CONDITION_ENTRY_RE = re.compile(
    r"\s*(?P<cond>[A-Z][A-Z0-9]*)(?:\s*\(\s*(?P<label>[A-Z0-9][A-Z0-9-]*)\s*\))?",
    re.IGNORECASE,
)
_RESP_OPTION_RE = re.compile(r"(?<![A-Z0-9-])(?:RESP|NOHANDLE)(?![A-Z0-9-])", re.I)


def _command(statement) -> str:
    return str(getattr(statement, "cics_command", "") or "").strip().upper()


def _text(statement) -> str:
    return " ".join(str(getattr(statement, "cics_text", "") or "").split())


def is_handle_declaration(statement) -> bool:
    """HANDLE CONDITION or IGNORE CONDITION."""
    return _command(statement) in ("HANDLE", "IGNORE") and _text(
        statement
    ).upper().startswith("CONDITION")


def parse_handle(statement) -> tuple[dict[str, str | None], str | None]:
    """(condition -> label / None for "system default" / IGNORED, problem)
    for one HANDLE or IGNORE CONDITION statement."""
    text = _text(statement)[len("CONDITION") :]
    ignore = _command(statement) == "IGNORE"
    entries: dict[str, str | None] = {}
    position = 0
    while position < len(text):
        if not text[position:].strip():
            break
        m = _CONDITION_ENTRY_RE.match(text, position)
        if m is None or m.end() == position:
            return {}, f"cannot read {text[position:].strip()!r}"
        condition = m.group("cond").upper()
        label = m.group("label")
        if ignore and label:
            return {}, f"IGNORE CONDITION {condition} names a label"
        entries[condition] = IGNORED if ignore else (label.upper() if label else None)
        position = m.end()
    if not entries:
        return {}, "it names no condition"
    return entries, None


def _procedure_cics_statements(program) -> list:
    """Every EXEC CICS statement in the PROCEDURE DIVISION, nested bodies
    included, in physical source order."""
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
            if isinstance(statement, ExecCicsStatement):
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


def handle_states(program) -> dict[int, dict[str, str | None]]:
    """id(CICS command) -> the condition map in force at it (physical
    source order). Commands with nothing registered are absent. Cached on
    the program object."""
    cached = getattr(program, "_mockymock_cics_handle", None)
    if cached is not None:
        return cached
    active: dict[str, str | None] = {}
    states: dict[int, dict[str, str | None]] = {}
    for statement in _procedure_cics_statements(program):
        if is_handle_declaration(statement):
            entries, problem = parse_handle(statement)
            if problem is None:
                active.update(entries)
            continue
        if active:
            states[id(statement)] = dict(active)
    try:
        program._mockymock_cics_handle = states
    except AttributeError:  # pragma: no cover - a slotted/frozen node
        pass
    return states


def uses_push_pop(program) -> bool:
    return any(
        _command(statement) in ("PUSH", "POP")
        for statement in _procedure_cics_statements(program)
    )


def label_in_state(
    state: dict[str, str | None], condition: str
) -> tuple[str | None, bool]:
    """(label to GO TO, or None when the condition is IGNOREd; whether a
    handler covers `condition` at all) under one condition map. A condition
    with no entry of its own falls to ERROR's, as in CICS."""
    condition = condition.upper()
    if condition in state:
        value = state[condition]
    elif condition != "ERROR" and "ERROR" in state:
        value = state["ERROR"]
    else:
        return None, False
    if value == IGNORED:
        return None, True
    if value is None:
        return None, False
    return value, True


def resolve_condition(
    program, statement, condition: str
) -> tuple[str | None, str | None]:
    """(GO TO label or None for "nothing happens", problem) for `statement`
    raising `condition`."""
    condition = condition.upper()
    if _RESP_OPTION_RE.search(_text(statement)):
        return None, (
            "the command is written with RESP/NOHANDLE, so HANDLE CONDITION "
            "does not apply to it -- set its RESP field in the mock body "
            "instead"
        )
    if uses_push_pop(program):
        return None, (
            "the program uses PUSH/POP HANDLE, whose runtime handler stack "
            "mockymock does not model"
        )
    label, handled = label_in_state(
        handle_states(program).get(id(statement), {}), condition
    )
    if handled:
        return label, None
    return None, (
        f"no HANDLE CONDITION label is in force for {condition} at this "
        f"command, so the real command would take the system default "
        f"action (usually an abend)"
    )


def handler_labels(program, statement, conditions: frozenset[str] | None) -> set[str]:
    """The labels `statement` can jump to when a mock raises one of
    `conditions` (None: any condition -- every label in force)."""
    state = handle_states(program).get(id(statement))
    if not state:
        return set()
    if conditions is None:
        return {v for v in state.values() if v is not None and v != IGNORED}
    labels: set[str] = set()
    for condition in conditions:
        label, problem = resolve_condition(program, statement, condition)
        if label and problem is None:
            labels.add(label)
    return labels


def all_handler_labels(program, conditions: frozenset[str] | None = None) -> set[str]:
    """Every label any CICS command can jump to for `conditions`."""
    labels: set[str] = set()
    for statement in _procedure_cics_statements(program):
        if not is_handle_declaration(statement):
            labels |= handler_labels(program, statement, conditions)
    return labels


def raised_conditions(mocks) -> frozenset[str]:
    """The conditions these MOCK directives raise (`CONDITION IS`)."""
    return frozenset(
        str(directive.cics_condition).upper()
        for directive in mocks
        if getattr(directive, "cics_condition", None)
    )
