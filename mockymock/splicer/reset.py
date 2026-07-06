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
    """One reset line per top-level (01 or 77) WORKING-STORAGE item.

    Elementary items get `MOVE <value> TO <name>` (declared VALUE clause, or
    the type default). Group items without a VALUE clause get
    `INITIALIZE <name>` instead: a MOVE SPACES over a group would write
    spaces across its numeric children, corrupting them for the next test
    case's arithmetic, while INITIALIZE resets numeric children to zero and
    alphanumeric ones to spaces. INITIALIZE does not restore children's own
    VALUE clauses, so after the INITIALIZE we additionally emit a MOVE for
    every (recursively nested) child that declared its own VALUE clause --
    see `_child_value_restores`.
    """
    working_storage = program.get_division("DATA")
    if working_storage is None:
        return []

    section = _find_working_storage_section(working_storage)
    if section is None:
        return []

    lines: list[str] = []
    for item in _top_level_items(section):
        if _is_filler(item):
            continue  # a top-level FILLER cannot be a valid MOVE/INITIALIZE target
        if _is_group(item) and not item.value_clause:
            lines.append(f"INITIALIZE {item.name}")
            lines.extend(_child_value_restores(item))
        else:
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
    # Level 77 items are standalone top-level items just like 01s; leaving
    # them out would let their state leak between test cases.
    return [
        item for item in section.children if getattr(item, "level", None) in (1, 77)
    ]


def _is_filler(item) -> bool:
    """FILLER items are unaddressable in COBOL: MOVE/INITIALIZE cannot target
    them by name, so reset generation must never emit a line for one."""
    name = getattr(item, "name", None)
    return not name or name.upper() == "FILLER"


def _is_group(item) -> bool:
    """A group item has subordinate data items. cobolparser's `children` list
    mixes in clause nodes (e.g. PictureClause), so only children that carry a
    data-item `level` count."""
    return any(
        getattr(child, "level", None) is not None
        for child in getattr(item, "children", [])
    )


def _child_value_restores(group) -> list[str]:
    """After INITIALIZE zeroes/space-fills a group, restore any child that
    declared its own VALUE clause (INITIALIZE does not honor those)."""
    out: list[str] = []
    for child in getattr(group, "children", []):
        if getattr(child, "level", None) is None:
            continue  # clause node, not a data item
        if _is_filler(child):
            continue  # FILLER is unaddressable; its VALUE already survives INITIALIZE
        if _is_group(child):
            out.extend(_child_value_restores(child))
        elif getattr(child, "value_clause", None):
            out.append(f"MOVE {child.value_clause} TO {child.name}")
    return out


def _is_numeric(item) -> bool:
    if item.picture_clause is None:
        return False
    stripped = _REPEAT_GROUP_RE.sub("", item.picture_clause.pattern)
    return any(c in stripped for c in ("9", "V", "P"))


def _default_value_literal(item) -> str:
    if item.value_clause:
        return item.value_clause
    return "0" if _is_numeric(item) else "SPACES"
