"""Flags ADD/SUBTRACT swap survivors the suite cannot kill from the target
field's starting value.

An unsigned numeric field stores only a magnitude. Starting from zero,
`ADD n TO f` leaves `n` and the mutant `SUBTRACT n FROM f` leaves `-n`,
stored as `n`: the two programs are indistinguishable, so the mutant
survives however good the assertions are. The fix lives in the test
data, not the assertions -- start the field from a non-zero value and
the two diverge -- so a survivor of that shape gets a hint saying so
instead of reading as a missing EXPECT.

Purely static and conservative: the hint is only attached to a mutant
that already survived, every target named on the mutated line must be an
unsigned, non-edited numeric WORKING-STORAGE/LOCAL-STORAGE item whose
between-case reset value is zero (its VALUE clause, or the zero default
`splicer/reset.py` gives a numeric item without one), and no test case
may seed it. A program statement that changes the field before the
arithmetic runs is not modelled, which is why the hint says "probably".
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from mockymock.mutation.operators import Mutant

_SWAP_DESCRIPTIONS = frozenset(
    {"ADD..TO -> SUBTRACT..FROM", "SUBTRACT..FROM -> ADD..TO"}
)
_RESET_SECTIONS = frozenset({"WORKING-STORAGE", "LOCAL-STORAGE"})
_ZERO_WORDS = frozenset({"ZERO", "ZEROS", "ZEROES"})

_WORD = r"(?<![A-Z0-9-]){}(?![A-Z0-9-])"
# The receiving operands of `ADD .. TO x` / `SUBTRACT .. FROM x`: everything
# after the preposition up to the end of the statement's receiving phrase.
_TARGETS = re.compile(_WORD.format("(?:TO|FROM)") + r"(?P<targets>.*)", re.IGNORECASE)
_TARGETS_END = re.compile(
    _WORD.format("(?:ON|NOT|SIZE|END-ADD|END-SUBTRACT)") + r"|\.\s*$",
    re.IGNORECASE,
)
_GIVING = re.compile(_WORD.format("GIVING"), re.IGNORECASE)
_SUBSCRIPT = re.compile(r"\([^)]*\)")
_NAME = re.compile(r"^[A-Z0-9][A-Z0-9-]*$", re.IGNORECASE)
_QUALIFIER = frozenset({"OF", "IN"})


def zero_baseline_hint(mutant: Mutant, ast: object, suite: object) -> str:
    """The hint for one surviving mutant, or "" when it does not apply."""
    if (
        mutant.operator != "arith-verb-swap"
        or mutant.description not in _SWAP_DESCRIPTIONS
    ):
        return ""
    targets = _receiving_names(mutant.original)
    if not targets:
        return ""
    items = _items_by_name(ast)
    seeded = _seeded_names(suite)
    for name in targets:
        candidates = items.get(name.upper(), [])
        if not candidates or not all(_starts_at_zero_unsigned(i) for i in candidates):
            return ""
        if name.upper() in seeded:
            return ""
    names = ", ".join(targets)
    first = targets[0]
    return (
        f"probably untestable from {names}'s starting value: unsigned, and "
        f"every test case starts it at zero, where ADD and SUBTRACT store the "
        f"same magnitude (0 + n and 0 - n both leave n). This is a test-data "
        f"gap, not a missing assertion: seed it to a non-zero value in a test "
        f"case (e.g. MOVE 5 TO {first}) so the two results differ."
    )


def _receiving_names(line: str) -> list[str]:
    """Bare data names after TO/FROM on the mutated line. Empty when the
    statement is a GIVING form (its receiving field is not the one being
    added to) or when nothing on this line can be read as a name."""
    code = line[:72]  # columns 73-80 are the identification area
    if _GIVING.search(code):
        return []
    match = _TARGETS.search(code)
    if match is None:
        return []
    tail = match.group("targets")
    end = _TARGETS_END.search(tail)
    if end is not None:
        tail = tail[: end.start()]
    tokens = _SUBSCRIPT.sub(" ", tail).replace(",", " ").split()
    names: list[str] = []
    skip_next = False
    for token in tokens:
        if skip_next:
            skip_next = False
            continue
        upper = token.upper()
        if upper in _QUALIFIER:
            skip_next = True
            continue
        if upper == "ROUNDED":
            continue
        if not _NAME.match(token) or token[0].isdigit():
            return []
        names.append(token.rstrip("."))
    return names


def _items_by_name(ast: object) -> dict[str, list[object]]:
    find = getattr(ast, "find_all_by_type", None)
    if find is None:
        return {}
    items: dict[str, list[object]] = {}
    for item in find("CobolDataItem"):
        name = getattr(item, "name", None)
        if name:
            items.setdefault(str(name).upper(), []).append(item)
    return items


def _starts_at_zero_unsigned(item: object) -> bool:
    if getattr(item, "section_name", None) not in _RESET_SECTIONS:
        return False
    picture = getattr(item, "picture_clause", None)
    if picture is None or getattr(picture, "is_edited", False):
        return False
    if getattr(picture, "is_signed", True) or getattr(item, "sign_clause", None):
        return False
    pattern = str(getattr(picture, "pattern", "") or "").upper()
    if not pattern or any(c not in "9VP()0123456789" for c in pattern):
        return False
    if getattr(item, "occurs_clause", None) is not None:
        return False
    return _is_zero_value(getattr(item, "value_clause", None))


def _is_zero_value(value: object) -> bool:
    if value is None:
        return True  # reset.py resets a numeric item with no VALUE to ZERO
    text = str(value).strip().upper()
    if text in _ZERO_WORDS:
        return True
    try:
        return Decimal(text) == 0
    except InvalidOperation:
        return False


def _seeded_names(suite: object) -> set[str]:
    """Every data name a test case writes before or while the program runs:
    setup MOVEs, mock ROWS/TERMINAL fields, and `TO <name>` in mock bodies.
    Any write counts -- a MOVE of zero would not help, but telling the two
    apart would mean evaluating the test author's intent."""
    names: set[str] = set()
    for case in getattr(suite, "test_cases", []) or []:
        for _value, target in getattr(case, "setup_moves", []) or []:
            names.add(str(target).upper())
        for mock in getattr(case, "mocks", []) or []:
            for row in (getattr(mock, "rows", None) or []) + [
                getattr(mock, "terminal_row", None) or []
            ]:
                for field_name, _value in row:
                    names.add(str(field_name).upper())
            for body_line in getattr(mock, "body_lines", []) or []:
                for target in re.findall(
                    r"(?<![A-Z0-9-])TO\s+([A-Z0-9][A-Z0-9-]*)", body_line.upper()
                ):
                    names.add(target)
    return names
