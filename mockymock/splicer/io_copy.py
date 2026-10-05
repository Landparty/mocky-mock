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
    #: Uppercased FD/SD file name -> its first record's name.
    file_records: dict[str, str] = field(default_factory=dict)
    #: Uppercased data-name -> the names of it and everything under it.
    subtrees: dict[str, frozenset[str]] = field(default_factory=dict)


def data_layout(program) -> DataLayout:
    layout = DataLayout()
    data = program.get_division("DATA") if program is not None else None
    if data is None:
        return layout
    for section in getattr(data, "sections", data.children):
        for item in getattr(section, "children", []):
            if getattr(item, "level", None) not in (1, 77):
                continue
            metadata = getattr(item, "_metadata", None) or {}
            file_name = str(metadata.get("fd_file_name") or "").upper()
            name = str(getattr(item, "name", "") or "").upper()
            if file_name and name and file_name not in layout.file_records:
                layout.file_records[file_name] = name
            _collect_subtree(item, layout.subtrees)
    return layout


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
    statement, layout: DataLayout | None, mentioned_text: list[str]
) -> str | None:
    """`MOVE <record> TO <into>` for a READ/RETURN ... INTO, or None when
    there is nothing to copy -- including when the mock already writes the
    INTO item itself (`mentioned_text`: its body lines and ROWS fields)."""
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
        if {word.upper() for word in _WORD_RE.findall(text)} & inside:
            return None
    return f"MOVE {record} TO {target}"
