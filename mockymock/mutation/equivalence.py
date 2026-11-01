"""Mutants provably equivalent to the original program (issue #349).

An equivalent mutant computes exactly what the original does, so no test,
however good, can kill it; scored as a survivor it caps the mutation score
below 100% for a reason that has nothing to do with the suite. These are
recognized before the mutant is built, reported as `equivalent` with the
reason, and left out of the score -- never silently dropped.

Two shapes, both from straight-line code where the proof needs only the
two adjacent statements:

* **Dead store** (`stmt-delete`). The deleted MOVE / SET <88> TO TRUE /
  INITIALIZE writes fields the very next statement overwrites in full
  without reading them: `MOVE "N" TO WS-FLAG` followed by
  `SET WS-FLAG-YES TO TRUE`. Deleting it leaves the same state.
* **Zero, then add** (`arith-verb-swap`). An unsigned numeric field set to
  zero by the statement right before `ADD n TO f`: 0 + n and 0 - n store
  the same magnitude in an unsigned field, whatever n is. Zoned and packed
  fields only: a binary one wraps (`zero_baseline.keeps_magnitude`).

Conservative throughout: every operand must be a plain name or a literal,
each statement must sit wholly on its own line, and nothing may come
between the two lines but blank and comment lines. Anything less certain
stays an ordinary mutant -- a missed equivalent costs one survivor, a
false one would hide a real gap in the suite.
"""

from __future__ import annotations

import re

from mockymock.mutation.operators import (
    TEXT_START_COL,
    Mutant,
    _statement_ends_on_line,
)
from mockymock.mutation.zero_baseline import _items_by_name, keeps_magnitude

_NAME = r"[A-Z0-9][A-Z0-9-]*"
_PLAIN_NAME = re.compile(rf"^{_NAME}$", re.IGNORECASE)
_MOVE = re.compile(
    rf"^MOVE\s+(?P<source>.+?)\s+TO\s+(?P<targets>{_NAME}(?:\s*,?\s+{_NAME})*)"
    r"\s*\.?\s*$",
    re.IGNORECASE,
)
_SET_TRUE = re.compile(
    rf"^SET\s+(?P<names>{_NAME}(?:\s*,?\s+{_NAME})*)\s+TO\s+TRUE\s*\.?\s*$",
    re.IGNORECASE,
)
_INITIALIZE = re.compile(
    rf"^INITIALIZE\s+(?P<targets>{_NAME}(?:\s*,?\s+{_NAME})*)\s*\.?\s*$",
    re.IGNORECASE,
)
_ADD_SUB = re.compile(
    rf"^(?:ADD\s+(?P<add>{_NAME}|[+-]?\d+(?:\.\d+)?)\s+TO"
    rf"|SUBTRACT\s+(?P<sub>{_NAME}|[+-]?\d+(?:\.\d+)?)\s+FROM)"
    rf"\s+(?P<target>{_NAME})(?:\s+ROUNDED)?\s*\.?\s*$",
    re.IGNORECASE,
)
_LITERAL = re.compile(
    r"""^(?:"[^"]*"|'[^']*'|[+-]?\d+(?:\.\d+)?|ZEROS?|ZEROES|SPACES?"""
    r"|HIGH-VALUES?|LOW-VALUES?|QUOTES?)$",
    re.IGNORECASE,
)
_ZERO = re.compile(r"^(?:ZEROS?|ZEROES|[+-]?0+(?:\.0+)?)$", re.IGNORECASE)
_RESERVED = frozenset({"TO", "FROM", "TRUE", "ROUNDED", "OF", "IN", "CORRESPONDING"})
_SWAPS = frozenset({"ADD..TO -> SUBTRACT..FROM", "SUBTRACT..FROM -> ADD..TO"})


def equivalence_reason(mutant: Mutant, lines: list[str], ast: object) -> str:
    """Why `mutant` cannot change the program's behavior, or "" when it
    may. `lines` is the original source, `ast` its parse (copybooks
    expanded) for the data-item facts."""
    try:
        if mutant.operator == "stmt-delete":
            return _dead_store(mutant, lines, ast)
        if mutant.operator == "arith-verb-swap" and mutant.description in _SWAPS:
            return _zero_then_add(mutant, lines, ast)
    except Exception:  # noqa: BLE001 -- unproven means "may differ"
        return ""
    return ""


def _code(line: str) -> str:
    """Columns 8-72, without a trailing `*>` comment."""
    return line[TEXT_START_COL - 1 : 72].partition("*>")[0].strip()


def _is_comment(line: str) -> bool:
    return len(line) >= 7 and line[6] in "*/"


def _neighbor(lines: list[str], index: int, step: int) -> int | None:
    """Index of the next (step=1) or previous (step=-1) line holding code."""
    other = index + step
    while 0 <= other < len(lines):
        if not _is_comment(lines[other]) and _code(lines[other]):
            return other
        other += step
    return None


def _complete(lines: list[str], index: int) -> bool:
    code = lines[index][:72].partition("*>")[0]
    return _statement_ends_on_line(lines, index, code)


def _ends_sentence(lines: list[str], index: int) -> bool:
    return _code(lines[index]).endswith(".")


def _unconditional_sentence(lines: list[str], index: int) -> bool:
    """Whether the statement on `lines[index]`, which ends a sentence,
    also starts one: then no IF can enclose it, and the statement after
    it runs exactly when it did. A period on a line whose sentence began
    earlier may close an IF, which the next sentence is outside of."""
    before = _neighbor(lines, index, -1)
    return before is None or _ends_sentence(lines, before)


def _names(text: str) -> list[str]:
    names = [n.upper() for n in re.split(r"[\s,]+", text.strip()) if n]
    if any(not _PLAIN_NAME.match(n) or n in _RESERVED for n in names):
        return []
    return names


def _items(ast: object) -> dict[str, list[object]]:
    return _items_by_name(ast)


def _condition_parent(name: str, items: dict[str, list[object]]) -> str | None:
    """The conditional variable a level-88 `name` belongs to, when `name`
    is declared exactly once program-wide (cobol-parser hangs each one off
    its variable as a ConditionNameItem child)."""
    if name in items:
        return None  # also a data item's name: which one is meant is unclear
    owners = [
        variable
        for variable, found in items.items()
        for item in found
        for child in getattr(item, "children", []) or []
        if type(child).__name__ == "ConditionNameItem"
        and str(getattr(child, "name", "")).upper() == name
    ]
    return owners[0] if len(owners) == 1 else None


def _ancestors(name: str, items: dict[str, list[object]]) -> set[str] | None:
    """`name` and every group it is declared under, when `name` is
    declared exactly once (None otherwise: which one is meant is unknown)."""
    found = items.get(name, [])
    if len(found) != 1:
        return None
    names = {name}
    parent = getattr(found[0], "parent", None)
    while parent is not None and getattr(parent, "name", None):
        names.add(str(parent.name).upper())
        parent = getattr(parent, "parent", None)
    return names


def _written(statement: str, items: dict[str, list[object]]) -> list[str] | None:
    """Fields a MOVE-literal / SET <88> TO TRUE statement overwrites in
    full without reading anything, or None for any other statement."""
    move = _MOVE.match(statement)
    if move:
        if not _LITERAL.match(move.group("source").strip()):
            return None
        return _names(move.group("targets")) or None
    set_true = _SET_TRUE.match(statement)
    if set_true:
        conditions = _names(set_true.group("names"))
        parents = [_condition_parent(name, items) for name in conditions]
        if not conditions or any(p is None for p in parents):
            return None
        return [p for p in parents if p is not None]
    return None


def _dead_store(mutant: Mutant, lines: list[str], ast: object) -> str:
    index = mutant.line - 1
    deleted = _code(lines[index]).rstrip(".").strip()
    items = _items(ast)
    initialize = _INITIALIZE.match(deleted + ".")
    if initialize:
        targets = _names(initialize.group("targets"))
    else:
        written = _written(deleted + ".", items)
        targets = written or []
    if not targets:
        return ""
    if _ends_sentence(lines, index) and not _unconditional_sentence(lines, index):
        # The period may close an IF holding the deleted statement; the
        # overwrite after it would then run on paths the deletion never
        # did. Harmless, but not provably so -- and simple beats clever.
        return ""
    follower = _neighbor(lines, index, 1)
    if follower is None or not _complete(lines, follower):
        return ""
    overwriter = _code(lines[follower])
    overwritten = _written(overwriter, items)
    if not overwritten:
        return ""
    for target in targets:
        covering = _ancestors(target, items)
        if covering is None or not covering & set(overwritten):
            return ""
    return (
        f"equivalent: line {follower + 1} ({overwriter.rstrip('.')}) overwrites "
        f"{', '.join(targets)} in full right after, so deleting this statement "
        "cannot change anything a test can observe"
    )


def _unsigned_numeric(name: str, items: dict[str, list[object]]) -> bool:
    found = items.get(name, [])
    if len(found) != 1:
        return False
    item = found[0]
    if not keeps_magnitude(item):
        return False
    picture = getattr(item, "picture_clause", None)
    if picture is None or getattr(picture, "is_edited", False):
        return False
    if getattr(picture, "is_signed", True) or getattr(item, "sign_clause", None):
        return False
    pattern = str(getattr(picture, "pattern", "") or "").upper()
    return bool(pattern) and all(c in "9VP()0123456789" for c in pattern)


def _zero_then_add(mutant: Mutant, lines: list[str], ast: object) -> str:
    index = mutant.line - 1
    statement = _code(lines[index])
    match = _ADD_SUB.match(statement)
    if match is None or not _complete(lines, index):
        return ""
    target = match.group("target").upper()
    operand = (match.group("add") or match.group("sub") or "").upper()
    if operand == target:
        return ""
    items = _items(ast)
    if not _unsigned_numeric(target, items):
        return ""
    previous = _neighbor(lines, index, -1)
    if previous is None or not _complete(lines, previous):
        return ""
    before = _code(lines[previous])
    if _ends_sentence(lines, previous) and not _unconditional_sentence(lines, previous):
        return ""  # the zeroing may sit inside an IF its period closes
    zeroed: list[str] = []
    move = _MOVE.match(before)
    if move and _ZERO.match(move.group("source").strip()):
        zeroed = _names(move.group("targets"))
    initialize = _INITIALIZE.match(before)
    if initialize:
        zeroed = _names(initialize.group("targets"))
    if target not in zeroed:
        return ""
    return (
        f"equivalent: {target} is unsigned and line {previous + 1} sets it to "
        "zero right before, where ADD and SUBTRACT store the same magnitude "
        "(0 + n and 0 - n both leave n)"
    )
