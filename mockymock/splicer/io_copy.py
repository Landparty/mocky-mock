"""The implicit MOVE a mocked `READ ... INTO` / `WRITE ... FROM` must keep.

A real `READ f INTO x` reads into the file's record area and then moves
that record to `x`; `WRITE r FROM y` (and REWRITE, RELEASE ... FROM, RETURN
... INTO) moves `y` into the record first. A mocked boundary replaces the
whole statement with its dispatch block, so without these lines a mock
that fills the record left the INTO item untouched and a FROM item never
reached the record (issue #149).

Mock bodies written before this fix set the INTO item's own fields
directly (`MOCK READ PARMFILE  MOVE 7 TO WS-PARM-DAYS`); copying the empty
record over them afterwards would undo that. So the INTO copy is emitted
only when the mock never names the INTO item or anything inside it.

A READ that fails moves nothing (the INTO item keeps its value), so when
the file has a FILE STATUS field the copy only runs on a successful status.
Every 01 under one FD shares one record area, so the copy (and the reset
in `splicer.reset`) uses the FD's longest record, not its first one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from cobolparser.models.statements.io import (
    IOReadStatement,
    IORewriteStatement,
    IOWriteStatement,
)
from cobolparser.models.statements.misc import ReleaseStatement, ReturnStatement

_WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]*")


@dataclass
class DataLayout:
    #: Uppercased FD/SD file name -> its longest record's name.
    file_records: dict[str, str] = field(default_factory=dict)
    #: Uppercased data-name -> the names of it and everything under it.
    subtrees: dict[str, frozenset[str]] = field(default_factory=dict)
    #: Uppercased FD/SD file name -> every data-name declared under any of
    #: its records (`splicer.file_keys`: a RECORD KEY must be one of them).
    file_names: dict[str, frozenset[str]] = field(default_factory=dict)


def data_layout(program) -> DataLayout:
    layout = DataLayout()
    data = program.get_division("DATA") if program is not None else None
    if data is None:
        return layout
    for section in getattr(data, "sections", data.children):
        items = [
            item
            for item in getattr(section, "children", [])
            if getattr(item, "level", None) in (1, 77)
        ]
        for item in longest_record_per_file(items):
            metadata = getattr(item, "_metadata", None) or {}
            file_name = str(metadata.get("fd_file_name") or "").upper()
            name = str(getattr(item, "name", "") or "").upper()
            if name and file_name not in layout.file_records:
                layout.file_records[file_name] = name
        for item in items:
            names = _collect_subtree(item, layout.subtrees)
            metadata = getattr(item, "_metadata", None) or {}
            file_name = str(metadata.get("fd_file_name") or "").upper()
            if file_name:
                known = layout.file_names.get(file_name, frozenset())
                layout.file_names[file_name] = known | names
    return layout


def record_length(item) -> int:
    """Bytes the 01 record *item* occupies, 0 when it cannot be laid out."""
    from mockymock._cobol_layout import compute_record_layout

    try:
        return compute_record_layout(item)[0].byte_length
    except Exception:  # noqa: BLE001 -- an unlayable record never wins
        return 0


def longest_record_per_file(items) -> list:
    """The longest FD/SD record of each file among *items* (01-level items),
    in the order their files first appear; ties keep the first record."""
    best: dict[str, tuple[int, object]] = {}
    for item in items:
        metadata = getattr(item, "_metadata", None) or {}
        file_name = str(metadata.get("fd_file_name") or "").upper()
        if not file_name:
            continue
        length = record_length(item)
        if file_name not in best or length > best[file_name][0]:
            best[file_name] = (length, item)
    return [item for _, item in best.values()]


def _collect_subtree(item, subtrees: dict[str, frozenset[str]]) -> frozenset[str]:
    name = str(getattr(item, "name", "") or "").upper()
    names = {name} if name and name != "FILLER" else set()
    for child in getattr(item, "children", []):
        if getattr(child, "level", None) is not None:
            names |= _collect_subtree(child, subtrees)
    frozen = frozenset(names)
    if name and name != "FILLER":
        # A name declared twice keeps the union: either may be meant.
        subtrees[name] = subtrees.get(name, frozenset()) | frozen
    return frozen


def _base_name(reference: str) -> str:
    match = _WORD_RE.match(reference.strip())
    return match.group(0).upper() if match else ""


def from_move(statement) -> str | None:
    """`MOVE <from> TO <record>` for a WRITE/REWRITE/RELEASE ... FROM."""
    if isinstance(statement, (IOWriteStatement, IORewriteStatement)):
        source = getattr(statement, "from_clause", None)
    elif isinstance(statement, ReleaseStatement):
        source = getattr(statement, "from_source", None)
    else:
        return None
    record = getattr(statement, "record_name", None)
    if not source or not record:
        return None
    return f"MOVE {source} TO {record}"


def into_move(
    statement,
    layout: DataLayout | None,
    mentioned_text: list[str],
    status_field: str | None = None,
) -> str | None:
    """`MOVE <record> TO <into>` for a READ/RETURN ... INTO, or None when
    there is nothing to copy -- including when the mock already writes the
    INTO item itself (`mentioned_text`: its body lines and ROWS fields).
    With a `status_field`, the MOVE only runs when the status is a success
    ("0x"), as a failed READ leaves the INTO item alone."""
    if layout is None or not isinstance(statement, (IOReadStatement, ReturnStatement)):
        return None
    target = getattr(statement, "into_target", None)
    file_name = str(getattr(statement, "file_name", "") or "").upper()
    record = layout.file_records.get(file_name)
    if not target or not record:
        return None
    base = _base_name(target)
    inside = layout.subtrees.get(base, frozenset({base}))
    for text in mentioned_text:
        if _names_any(text, inside):
            return None
    move = f"MOVE {record} TO {target}"
    if status_field:
        return f'IF {status_field}(1:1) = "0" {move} END-IF'
    return move


def _names_any(text: str, names: frozenset[str]) -> bool:
    """Whether *text* refers to one of *names*. A word qualified by a name
    outside them (`R-AMT OF IN-REC` when the INTO item is WS-REC, sharing
    the copybook's field names) refers to something else."""
    words = [word.upper() for word in _WORD_RE.findall(text)]
    for i, word in enumerate(words):
        if word not in names:
            continue
        if (
            i + 2 < len(words)
            and words[i + 1] in ("OF", "IN")
            and words[i + 2] not in names
        ):
            continue
        return True
    return False
