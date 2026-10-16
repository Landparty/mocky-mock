"""`SPECIAL-NAMES. DECIMAL-POINT IS COMMA.` (issue #230).

Under that clause a COBOL numeric literal is written `1,25`, and `1.25` is
the literal `1` followed by a sentence period. Every numeric literal
mockymock writes into COBOL or a `.cut` file -- the reset paragraph's
VALUE restores, a scaffold's mock-body MOVEs, a recorded EXPECT golden --
goes through `localize_numeric` so the program keeps compiling.
cobol-parser normalizes `VALUE 1,25` to `1.25`, so the literals arrive in
period form whatever the program wrote.
"""

from __future__ import annotations

import re

_PERIOD_DECIMAL_RE = re.compile(r"^([+-]?\d*)\.(\d+)$")
_MOVE_NUMERIC_RE = re.compile(r"^(\s*MOVE\s+[+-]?\d*)\.(\d+\s+TO\s)", re.IGNORECASE)


def decimal_point_is_comma(program) -> bool:
    """True when the program's CONFIGURATION SECTION declares
    `DECIMAL-POINT IS COMMA` (cobol-parser records it as the section's
    `special_names.decimal_point_is_comma` metadata)."""
    if program is None:
        return False
    find = getattr(program, "find_all_by_type", None)
    if find is None:
        return False
    for section in find("CobolSection"):
        metadata = getattr(section, "_metadata", None) or {}
        special_names = metadata.get("special_names") or {}
        if special_names.get("decimal_point_is_comma"):
            return True
    return False


def localize_numeric(literal: str, decimal_comma: bool) -> str:
    """`literal` with its decimal point written as a comma when
    `decimal_comma` and it is a plain numeric literal (`-3.50` -> `-3,50`);
    anything else is returned unchanged."""
    if not decimal_comma:
        return literal
    return _PERIOD_DECIMAL_RE.sub(r"\1,\2", literal)


def localize_move_line(line: str, decimal_comma: bool) -> str:
    """A `MOVE <numeric literal> TO ...` line with its literal localized."""
    if not decimal_comma:
        return line
    return _MOVE_NUMERIC_RE.sub(r"\1,\2", line)


def delocalize_numeric(text: str, decimal_comma: bool) -> str:
    """The inverse for text read back from the program: a DISPLAYed
    `00125,00` under `DECIMAL-POINT IS COMMA` -> `00125.00`."""
    if not decimal_comma:
        return text
    return re.sub(r"^([+-]?\d*),(\d+[+-]?)$", r"\1.\2", text)
