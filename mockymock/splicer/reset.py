"""Generates MOVE statements that reset WORKING-STORAGE between test cases.

Necessary because mockymock compiles one binary per TESTSUITE (see Global
Constraints): without an explicit reset, case N's leftover state leaks
into case N+1. Resets to the item's declared VALUE clause if present,
otherwise to COBOL's conventional type default (ZERO for numeric --
including numeric-edited PICs like ZZZ9, which reject MOVE SPACES --
SPACES for alphanumeric) -- a deliberate divergence from "truly undefined"
COBOL memory, in exchange for deterministic, order-independent tests.

PICTURE-less usage-typed items get usage-appropriate resets instead of an
illegal `MOVE SPACES`: COMP-1/COMP-2 floats take `MOVE 0`, POINTER-family
items take `SET ... TO NULL`. Items this module cannot reset legally are
SKIPPED rather than given illegal COBOL (documented fidelity limits, see
.okf/splicer.md): USAGE INDEX items, PICTURE-less items of unrecognized
usage, and OCCURS children with VALUE clauses (restoring those needs
subscripted MOVEs).
"""

from __future__ import annotations

import re

_REPEAT_GROUP_RE = re.compile(r"\(\d+\)")

# PIC symbols that make an item numeric or numeric-edited -- either way the
# only legal reset literal is a number, never SPACES (cobc rejects
# `MOVE SPACES TO <PIC ZZZ item>`). Z/*/$/+/- only ever appear in
# numeric-edited pictures; X/A/B pictures never contain them.
_NUMERIC_PIC_CHARS = frozenset("9VPZ*$+-")

# usage strings as cobolparser stores them (verified empirically).
_FLOAT_USAGES = frozenset({"COMP-1", "COMP-2", "COMPUTATIONAL-1", "COMPUTATIONAL-2"})
_POINTER_USAGES = frozenset(
    {"POINTER", "PROCEDURE-POINTER", "FUNCTION-POINTER", "PROGRAM-POINTER"}
)


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

    return reset_lines_for_items(_top_level_items(section))


def reset_lines_for_items(items) -> list[str]:
    """The reset-line generation loop `reset_move_lines` runs over
    WORKING-STORAGE's top-level items, factored out so other WORKING-STORAGE-
    shaped item lists (e.g. a LINKAGE SECTION neutralized into WORKING-STORAGE
    by `mockymock.splicer.linkage`) get the identical VALUE-restoring
    treatment without duplicating this logic."""
    lines: list[str] = []
    for item in items:
        if _is_filler(item):
            continue  # a top-level FILLER cannot be a valid MOVE/INITIALIZE target
        if _is_group(item) and not item.value_clause:
            lines.append(f"INITIALIZE {item.name}")
            lines.extend(_child_value_restores(item))
        else:
            reset = _elementary_reset(item)
            if reset is not None:
                lines.append(reset)
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
    declared its own VALUE clause (INITIALIZE does not honor those).

    Children carrying an OCCURS clause are skipped entirely (subtree
    included): an unsubscripted `MOVE 7 TO WS-CELL` against an OCCURS item
    is illegal COBOL and cobc rejects it, and a subscripted expansion would
    need the table bounds -- a documented fidelity limit (such children are
    left at INITIALIZE's type defaults, not their declared VALUE)."""
    out: list[str] = []
    for child in getattr(group, "children", []):
        if getattr(child, "level", None) is None:
            continue  # clause node, not a data item
        if _is_filler(child):
            continue  # FILLER is unaddressable; its VALUE already survives INITIALIZE
        if getattr(child, "occurs_clause", None) is not None:
            continue  # OCCURS needs subscripted MOVEs -- skip, fidelity limit
        if _is_group(child):
            out.extend(_child_value_restores(child))
        elif getattr(child, "value_clause", None):
            restore = _elementary_reset(child)
            if restore is not None:
                out.append(restore)
    return out


def _is_numeric(item) -> bool:
    """True for numeric AND numeric-edited pictures: Z, *, $, + and - only
    ever appear in numeric-edited PICs (e.g. ZZZ9, $$9, ***9), whose only
    legal literal reset is a number -- `MOVE SPACES TO <PIC ZZZ>` is
    rejected by cobc."""
    if item.picture_clause is None:
        return False
    stripped = _REPEAT_GROUP_RE.sub("", item.picture_clause.pattern or "")
    return any(c in _NUMERIC_PIC_CHARS for c in stripped.upper())


def _elementary_reset(item) -> str | None:
    """The reset line for one elementary (or VALUE-carrying group) item, or
    None when no legal reset exists (skip rather than emit illegal COBOL).

    POINTER-family items can only be assigned with SET, and NULL is their
    only legal VALUE, so `SET ... TO NULL` both resets and restores. USAGE
    INDEX items are skipped: their content is implementation-defined and a
    reset adds nothing a fresh SEARCH/SET in the test flow doesn't. A
    PICTURE-less item of unrecognized usage is skipped fail-safe."""
    usage = (getattr(item, "usage", None) or "").upper()
    if usage in _POINTER_USAGES:
        return f"SET {item.name} TO NULL"
    if usage == "INDEX":
        return None  # no legal MOVE; fidelity limit
    if item.value_clause:
        return f"MOVE {item.value_clause} TO {item.name}"
    if item.picture_clause is None:
        if usage in _FLOAT_USAGES:
            return f"MOVE 0 TO {item.name}"
        return None  # PIC-less, unrecognized usage: skip fail-safe
    return f"MOVE {'0' if _is_numeric(item) else 'SPACES'} TO {item.name}"
