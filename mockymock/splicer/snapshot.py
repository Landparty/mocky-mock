"""Saves and restores program state around BEFORE-ALL (suite hooks).

A `.cut` BEFORE-ALL block's steps run once, before the first test case;
every test case must then start from the state they left behind -- not
from the program's initial state (`splicer.reset`), which is what each
case would otherwise get. See docs/2026-10-10-suite-hooks-design.md.

The driver therefore runs `UT-RESET-WORKING-STORAGE`, the BEFORE-ALL
steps, then `UT-SAVE-STATE` once; each test case runs
`UT-RESET-WORKING-STORAGE` followed by `UT-RESTORE-STATE`. Resetting first
keeps everything outside this module's reach (harness fields, capture
targets, the CICS EIB) at its usual per-case value; the restore then
overwrites every item listed below with its saved copy.

Covered items are exactly the ones `splicer.reset` covers: every
top-level (01/77) WORKING-STORAGE and LOCAL-STORAGE item, each FD/SD's
longest record, and LINKAGE items neutralized into WORKING-STORAGE.
Top-level REDEFINES items are skipped (their storage is the redefined
item's, which is saved), as are top-level FILLERs (not addressable).

How each item is copied, chosen so every MOVE is one COBOL defines as
exact:

- Group item: into `01 UT-SNAP-nnn. 05 FILLER PIC X(n).`, where n is an
  upper bound of the group's size. A MOVE with a group on either side is
  a byte copy with no conversion; saving pads the copy with spaces past
  the group's end, restoring copies back exactly the group's own bytes.
  An upper bound (not an exact size) is deliberate: it only has to be big
  enough, so it can't be wrong in the dangerous direction across
  cobol-parser versions whose size arithmetic differed.
- Elementary item with an editing PICTURE (alphanumeric-, national- or
  numeric-edited): the same group byte copy. A MOVE into an edited item
  re-applies its editing mask to the sender's already-edited text, so a
  same-PICTURE copy shifted the value (`PIC XX/XX` "AB/CD" came back
  "AB///", issue #224).
- Any other elementary item with a PICTURE (or a PICTURE-less usage such
  as COMP-1): into a field declared with the same PICTURE, USAGE and SIGN
  clause. A MOVE between two identically described non-edited items
  preserves the value.
- POINTER-family and INDEX items: `SET` into a field of the same usage
  (COBOL forbids MOVE on them).

Refused (fail closed, reported by `plan_snapshot`): a group containing an
OCCURS ... DEPENDING ON table, whose size at restore time depends on a
counter the restore itself overwrites; a group with an OCCURS table whose
bound cannot be read; and an elementary item whose description this
module cannot reproduce.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from mockymock.splicer.io_copy import longest_record_per_file
from mockymock.splicer.reset import _is_filler, _is_group, _sections, _top_level_items

SNAP_PREFIX = "UT-SNAP-"

_POINTER_USAGES = frozenset(
    {"POINTER", "PROCEDURE-POINTER", "FUNCTION-POINTER", "PROGRAM-POINTER"}
)
_SET_USAGES = _POINTER_USAGES | {"INDEX"}
_REPEAT_RE = re.compile(r"(.)\((\d+)\)")
# Generous per-elementary floor: covers every binary/float/pointer/index
# width GnuCOBOL allocates (8 bytes at most) with room to spare.
_ELEMENTARY_FLOOR = 16


@dataclass
class StateSnapshot:
    working_storage_lines: list[str] = field(default_factory=list)
    save_lines: list[str] = field(default_factory=list)
    restore_lines: list[str] = field(default_factory=list)


def plan_snapshot(
    program, linkage_items: list | None = None
) -> tuple[StateSnapshot, list[str]]:
    """The snapshot fields and the save/restore statements for `program`,
    plus one problem string per item that cannot be saved exactly (empty
    when everything can). Callers must refuse when problems is non-empty:
    a partially restored state is a silently wrong test."""
    snapshot = StateSnapshot()
    problems: list[str] = []
    for item in _state_items(program, linkage_items or []):
        snap = f"{SNAP_PREFIX}{len(snapshot.save_lines) + 1:03d}"
        if _is_group(item) or _is_edited(item):
            reason = _odo_reason(item)
            size = None if reason else _max_bytes(item)
            if reason or size is None:
                problems.append(
                    f"{item.name}: "
                    + (reason or "an OCCURS table's bound could not be read")
                    + " -- its state after BEFORE-ALL cannot be saved exactly"
                )
                continue
            snapshot.working_storage_lines.extend(
                [f"01  {snap}.", f"    05 FILLER PIC X({size})."]
            )
            snapshot.save_lines.append(f"MOVE {item.name} TO {snap}")
            snapshot.restore_lines.append(f"MOVE {snap} TO {item.name}")
            continue
        usage = (getattr(item, "usage", None) or "").upper()
        if usage in _SET_USAGES and getattr(item, "picture_clause", None) is None:
            snapshot.working_storage_lines.append(f"01  {snap} USAGE {usage}.")
            snapshot.save_lines.append(f"SET {snap} TO {item.name}")
            snapshot.restore_lines.append(f"SET {item.name} TO {snap}")
            continue
        description = _elementary_description(item)
        if description is None:
            problems.append(
                f"{item.name}: its description (no PICTURE, usage "
                f"{usage or 'unknown'}) cannot be reproduced -- its state "
                f"after BEFORE-ALL cannot be saved exactly"
            )
            continue
        snapshot.working_storage_lines.append(f"01  {snap} {description}.")
        snapshot.save_lines.append(f"MOVE {item.name} TO {snap}")
        snapshot.restore_lines.append(f"MOVE {snap} TO {item.name}")
    return snapshot, problems


def _state_items(program, linkage_items: list) -> list:
    data_division = program.get_division("DATA")
    if data_division is None:
        return list(linkage_items)
    items: list = []
    for section in _sections(data_division, "FILE"):
        items.extend(longest_record_per_file(_top_level_items(section)))
    for name in ("WORKING-STORAGE", "LOCAL-STORAGE"):
        for section in _sections(data_division, name):
            items.extend(_top_level_items(section))
    items.extend(linkage_items)
    return [
        item
        for item in items
        if not _is_filler(item) and not getattr(item, "redefines", None)
    ]


def _is_edited(item) -> bool:
    """An elementary item with an editing PICTURE (XX/XX, XXXBXXXX, NNBNN,
    ZZ9.99). A MOVE into one re-applies the editing mask to the sender's
    already-edited text, insertion characters included, so the value
    shifts on every copy (issue #224); it is byte-copied like a group."""
    picture = getattr(item, "picture_clause", None)
    return bool(picture is not None and getattr(picture, "is_edited", False))


def _children(item) -> list:
    return [c for c in getattr(item, "children", []) if getattr(c, "level", None)]


def _occurs_times(item) -> int | None:
    """1 for an item without OCCURS, its maximum occurrence count with one,
    None when that count cannot be read."""
    occurs = getattr(item, "occurs_clause", None)
    if occurs is None:
        return 1
    counts = [getattr(occurs, attr, None) for attr in ("max_occurs", "times", "count")]
    known = [c for c in counts if isinstance(c, int) and c > 0]
    return max(known) if known else None


def _odo_reason(item) -> str | None:
    for child in _children(item):
        occurs = getattr(child, "occurs_clause", None)
        if occurs is not None and getattr(occurs, "depending_on", None):
            return (
                f"it holds {child.name} OCCURS ... DEPENDING ON "
                f"{occurs.depending_on}"
            )
        nested = _odo_reason(child)
        if nested:
            return nested
    return None


def _picture_symbols(pattern: str) -> int:
    expanded = _REPEAT_RE.sub(lambda m: m.group(1) * int(m.group(2)), pattern)
    return len(expanded)


def _max_bytes(item) -> int | None:
    """An upper bound of the bytes `item` occupies, every occurrence
    included. Overcounts on purpose (REDEFINES children are added rather
    than overlaid, V/S/P symbols count a byte each, every elementary item
    gets at least _ELEMENTARY_FLOOR bytes)."""
    times = _occurs_times(item)
    if times is None:
        return None
    children = _children(item)
    if children:
        total = 0
        for child in children:
            size = _max_bytes(child)
            if size is None:
                return None
            total += size
        return total * times
    picture = getattr(item, "picture_clause", None)
    symbols = _picture_symbols(picture.pattern or "") if picture is not None else 0
    usage = (getattr(item, "usage", None) or "").upper()
    pattern = (picture.pattern or "").upper() if picture is not None else ""
    wide = usage in {"NATIONAL", "UTF-8"} or "N" in pattern or "U" in pattern
    # One extra byte for SIGN ... SEPARATE; national/UTF-8 characters take
    # up to four bytes each.
    size = max(symbols * (4 if wide else 1) + 1, _ELEMENTARY_FLOOR)
    return size * times


def _elementary_description(item) -> str | None:
    picture = getattr(item, "picture_clause", None)
    usage = (getattr(item, "usage", None) or "").upper()
    parts: list[str] = []
    if picture is not None and picture.pattern:
        parts.append(f"PIC {picture.pattern}")
    elif not usage or usage == "DISPLAY":
        return None
    if usage and usage != "DISPLAY":
        parts.append(f"USAGE {usage}")
    sign = getattr(item, "sign_clause", None)
    if sign:
        parts.append(f"SIGN {sign}")
    return " ".join(parts)
