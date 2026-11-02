"""SELECT keys that name an item outside the file's own FD record.

`SELECT F ... RECORD KEY IS K` requires K to be declared under one of F's
FD records. Some real programs break that rule: CardDemo's CBEXPORT and
CBIMPORT declare their export file's record as `PIC X(500)` and key it on
`EXPORT-SEQUENCE-NUM`, a field of a WORKING-STORAGE copybook they `WRITE
... FROM` / `READ ... INTO`. GnuCOBOL refuses to compile that
("'EXPORT-SEQUENCE-NUM' is not defined"), so the whole suite failed before
any test case ran.

Every file statement a test case reaches is mocked (the refusal gate
refuses an unmocked reachable one), so the compiled test program never
opens the real file and its key is never used. The SELECT only has to
compile: a RECORD KEY outside the FD is pointed at the FD's own (longest)
record, which GnuCOBOL accepts as a key, and an ALTERNATE RECORD KEY
outside it is dropped (it cannot reuse the record the primary key now
names). The file keeps its organization and access mode, so every other
statement that names it still compiles as written.

Edits stay on the lines they started on, so every span the splicer
computed from the original line numbers stays valid.
"""

from __future__ import annotations

import re

from mockymock.analysis.mock_surface import MockSurface

_WORD = r"[A-Za-z0-9][A-Za-z0-9-]*"
_QUALIFIERS = rf"(?:\s+(?:OF|IN)\s+{_WORD})*"
#: A key the GnuCOBOL split-key form defines (`RECORD KEY IS K = A B`,
#: `SOURCE IS A B`) is not a data item: such a SELECT is left alone.
_NOT_SPLIT = r"(?!\s*(?:=|SOURCE\b))"
_FILE_CONTROL_RE = re.compile(r"(?<![\w-])FILE-CONTROL(?![\w-])", re.IGNORECASE)
_END_RE = re.compile(
    r"(?<![\w-])(?:I-O-CONTROL|DATA\s+DIVISION)(?![\w-])", re.IGNORECASE
)
_SELECT_RE = re.compile(
    rf"(?<![\w-])SELECT\s+(?:OPTIONAL\s+)?({_WORD})(?![\w-])", re.IGNORECASE
)


def rewrite_foreign_record_keys(lines: list[str], surface: MockSurface) -> list[str]:
    """`lines` with every SELECT key declared outside its file's FD records
    pointed at the FD record (RECORD KEY) or dropped (ALTERNATE RECORD
    KEY). Unchanged when every key is in its FD, or the file has none."""
    layout = surface.data_layout
    if layout is None:
        return lines
    fixes: dict[str, tuple[str | None, list[str], str]] = {}
    for file_name, select in surface.file_selects.items():
        names = layout.file_names.get(file_name)
        record = layout.file_records.get(file_name)
        if not names or not record:
            continue
        primary = select.record_key
        foreign_primary = primary if primary and primary not in names else None
        foreign_alternates = [key for key in select.alternate_keys if key not in names]
        if foreign_primary or foreign_alternates:
            fixes[file_name] = (foreign_primary, foreign_alternates, record)
    if not fixes:
        return lines
    result = list(lines)
    for file_name, start, end in _select_spans(result):
        fix = fixes.get(file_name)
        if fix is None:
            continue
        primary, alternates, record = fix
        text = "\n".join(result[start:end])
        for key in alternates:
            text = _drop_alternate(text, key)
        if primary:
            text = _repoint_primary(text, primary, record)
        rewritten = text.split("\n")
        if len(rewritten) == end - start:  # always: no edit adds a line
            result[start:end] = rewritten
    return result


def _select_spans(lines: list[str]) -> list[tuple[str, int, int]]:
    """(uppercased file name, first line index, end index) of every SELECT
    entry written in the FILE-CONTROL paragraph of `lines`."""
    begin = next(
        (i for i, line in enumerate(lines) if _FILE_CONTROL_RE.search(line)), None
    )
    if begin is None:
        return []
    stop = next(
        (i for i in range(begin, len(lines)) if _END_RE.search(lines[i])),
        len(lines),
    )
    starts: list[tuple[str, int]] = []
    for index in range(begin, stop):
        for match in _SELECT_RE.finditer(lines[index]):
            starts.append((match.group(1).upper(), index))
    spans: list[tuple[str, int, int]] = []
    for position, (name, index) in enumerate(starts):
        end = starts[position + 1][1] if position + 1 < len(starts) else stop
        # Two SELECTs on one line share it: neither can be edited alone.
        if end == index:
            continue
        if position > 0 and starts[position - 1][1] == index:
            continue
        spans.append((name, index, end))
    return spans


def _keep_newlines(matched: str, replacement: str) -> str:
    """`replacement` followed by the line breaks `matched` spanned, so the
    edit never changes which line later text sits on."""
    return replacement + "\n" * matched.count("\n")


def _repoint_primary(text: str, key: str, record: str) -> str:
    pattern = re.compile(
        rf"(?<![\w-])(RECORD\s+(?:KEY\s+)?(?:IS\s+)?)"
        rf"({re.escape(key)}{_QUALIFIERS})(?![\w-]){_NOT_SPLIT}",
        re.IGNORECASE,
    )

    def repoint(match: re.Match[str]) -> str:
        before = text[: match.start()].rstrip()
        if re.search(r"(?<![\w-])ALTERNATE$", before, re.IGNORECASE):
            return match.group(0)
        return match.group(1) + _keep_newlines(match.group(2), record)

    return pattern.sub(repoint, text)


def _drop_alternate(text: str, key: str) -> str:
    pattern = re.compile(
        rf"(?<![\w-])ALTERNATE\s+(?:RECORD\s+)?(?:KEY\s+)?(?:IS\s+)?"
        rf"{re.escape(key)}{_QUALIFIERS}(?![\w-]){_NOT_SPLIT}"
        rf"(?:\s+(?:WITH\s+)?DUPLICATES(?![\w-]))?",
        re.IGNORECASE,
    )
    return pattern.sub(lambda match: _keep_newlines(match.group(0), ""), text)
