"""Generates MOVE statements that reset WORKING-STORAGE between test cases.

Necessary because mockymock compiles one binary per TESTSUITE (see Global
Constraints): without an explicit reset, case N's leftover state leaks
into case N+1. Resets to the item's declared VALUE clause if present,
otherwise to COBOL's conventional type default (ZERO for numeric, SPACES
for alphanumeric) -- a deliberate divergence from "truly undefined" COBOL
memory, in exchange for deterministic, order-independent tests.
"""

from __future__ import annotations

import re

_REPEAT_GROUP_RE = re.compile(r"\(\d+\)")


def reset_move_lines(program) -> list[str]:
    """One `MOVE <value> TO <name>` line per top-level WORKING-STORAGE item."""
    working_storage = program.get_division("DATA")
    if working_storage is None:
        return []

    section = _find_working_storage_section(working_storage)
    if section is None:
        return []

    lines: list[str] = []
    for item in _top_level_items(section):
        value = _default_value_literal(item)
        lines.append(f"MOVE {value} TO {item.name}")
    return lines


def _find_working_storage_section(data_division):
    for section in getattr(data_division, "sections", data_division.children):
        name = getattr(section, "_own_section_name", None) or getattr(
            section, "section_name", None
        )
        if name and "WORKING-STORAGE" in name.upper():
            return section
    return None


def _top_level_items(section):
    return [item for item in section.children if getattr(item, "level", None) == 1]


def _is_numeric(item) -> bool:
    if item.picture_clause is None:
        return False
    stripped = _REPEAT_GROUP_RE.sub("", item.picture_clause.pattern)
    return any(c in stripped for c in ("9", "V", "P"))


def _default_value_literal(item) -> str:
    if item.value_clause:
        return item.value_clause
    return "0" if _is_numeric(item) else "SPACES"
