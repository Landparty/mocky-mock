"""Fixture row/value rendering: field values, MOVE lines, UNSTRING-delimited
records, record-length MOVEs and the single-invocation body."""

from __future__ import annotations

import re
from dataclasses import replace

from mockymock._decimal import localize_numeric
from mockymock.dsl.fixture_bundle import BoundaryFixture, FieldSpec
from mockymock.dsl.generator._context import (
    _NUMERIC_FIELD_CATEGORIES,
    ProgramContext,
    _qualified_reference,
)
from mockymock.dsl.generator.cics import (
    _cics_fixture_statements,
    _cics_output_layout,
    _cics_resp_names,
)
from mockymock.dsl.generator.sql import _sql_status_lines
from mockymock.splicer.reset import _POINTER_USAGES


def _bundle_rendered_value(
    raw_value: str, field_category: str, decimal_comma: bool = False
) -> str:
    """Bare for a numeric-family FieldSpec category (see cobol-parser's
    fixture-bundle-schema.md), quoted (with embedded `"` doubled,
    mirroring driver._display_text's escaping) otherwise. Unlike
    `report.record_rewrite.render_expect_value`, this decides from the
    FieldSpec's own resolved category -- exact, not a text-shape guess --
    since a bundle row always carries one."""
    if field_category in _NUMERIC_FIELD_CATEGORIES:
        return localize_numeric(raw_value, decimal_comma)
    if (
        raw_value
        and any(ord(ch) < 32 or ord(ch) > 126 for ch in raw_value)
        and all(ord(ch) < 256 for ch in raw_value)
    ):
        # A byte no source character spells (`IF EIBAID = X'F3'`): a hex
        # literal, so the field holds that byte rather than its UTF-8 form.
        return "X'" + raw_value.encode("latin-1").hex().upper() + "'"
    escaped = raw_value.replace('"', '""')
    return f'"{escaped}"'


def _row_target(spec: FieldSpec, source: ProgramContext | None) -> str:
    if source is None or source.is_unique_name(spec.name):
        return spec.column
    return _qualified_reference(spec.qualified_name, spec.column, spec.name)


# A mock body cannot MOVE a generated value into a POINTER-family item
# (it takes only SET, and NULL is its only data-free value) or an INDEX
# item (its content is implementation-defined). cobol-parser's bundle lays
# them out as numeric fields holding "0", and `MOVE 0 TO <pointer>` is a
# compile error ("invalid MOVE statement"). A TESTCASE's own setup lines
# (`in_mock_body=False`) take only MOVE, so there the pointer is left out:
# the per-case WORKING-STORAGE reset (splicer/reset.py) already sets it to
# NULL, and `SET ... TO NULL` there was refused by the .cut parser.
def _row_move_line(
    row: dict[str, str],
    spec: FieldSpec,
    target: str,
    decimal_comma: bool = False,
    in_mock_body: bool = True,
    source: ProgramContext | None = None,
) -> str | None:
    usage = (spec.usage or "").upper()
    if usage in _POINTER_USAGES:
        if not in_mock_body:
            return f"*> {target} ({usage}) starts NULL: the per-case reset sets it"
        return f"SET {target} TO NULL"
    if usage == "INDEX":
        return None
    raw = row.get(spec.column, "")
    if source is not None and spec.category == "alphanumeric":
        raw = _delimited_value(raw, spec, source) or raw
    value = _bundle_rendered_value(raw, spec.category, decimal_comma)
    if spec.category == "alphanumeric-edited":
        # The bundle gives the field's edited image, which is the bytes a
        # real record holds; a plain MOVE would edit it again ("N8/DF/B3"
        # into XX/XX/XX became "N8//D/F/", issue #277).
        return f"MOVE {value} TO {target}(1:)"
    return f"MOVE {value} TO {target}"


def _picture_shape(picture: str | None) -> tuple[int, bool] | None:
    """(character length, all digits) of a DISPLAY PICTURE, or None for one
    this cannot size (edited, national, ...)."""
    if not picture:
        return None
    text = re.sub(
        r"([9XA])\((\d+)\)", lambda m: m.group(1) * int(m.group(2)), picture.upper()
    )
    text = text.replace("S", "").replace("V", "")
    if not text or not re.fullmatch(r"[9XA]+", text):
        return None
    return len(text), set(text) == {"9"}


def _delimited_value(raw: str, spec: FieldSpec, source: ProgramContext) -> str | None:
    """The generated value for a field the program UNSTRINGs, rebuilt as
    one part per INTO target joined by the delimiter: a random string
    without the delimiter made every record take the program's reject path,
    under a case still called "happy path" (the RECFMT field run). Each
    part is sized to its target (digits for a numeric one) and drawn from
    the generated value's own characters, so it stays seeded. None when
    the field is not split, or a target cannot be sized."""
    layout = source.unstring_layouts.get(spec.name.upper())
    if layout is None:
        return None
    delimiter, targets = layout
    shapes = [_picture_shape(source.pictures.get(target)) for target in targets]
    if any(shape is None for shape in shapes):
        return None
    lengths = [shape[0] for shape in shapes if shape is not None]
    budget = spec.size - len(delimiter) * (len(targets) - 1)
    if budget < len(targets):
        return None
    while sum(lengths) > budget:
        widest = lengths.index(max(lengths))
        lengths[widest] -= 1
    pool = [c for c in raw if c.isalnum() and c not in delimiter] or ["A"]
    parts: list[str] = []
    cursor = 0
    for length, shape in zip(lengths, shapes, strict=True):
        chars = [pool[(cursor + i) % len(pool)] for i in range(length)]
        cursor += length
        if shape is not None and shape[1]:
            chars = [c if c.isdigit() else str(ord(c) % 10) for c in chars]
        parts.append("".join(chars))
    return delimiter.join(parts)


def _record_length_move(
    fixture: BoundaryFixture, source: ProgramContext | None
) -> str | None:
    """`MOVE <length> TO <item>` for a READ of a file whose FD says `RECORD
    VARYING FROM n TO m DEPENDING ON item` (issue #214): a real READ stores
    the length of the record it just read there, and a mock that never
    sets it left every generated record at the item's VALUE (usually 0),
    below the FD's own minimum, so a program checking the length took its
    short-record path for all the happy-path data. The bundle carries no
    per-row length yet (cobol-parser's `declared_lengths` is not surfaced),
    so every row reports the full length the record layout describes,
    clamped into the FD's range. None for any other file."""
    if fixture.category != "READ" or source is None or source.program is None:
        return None
    key = fixture.key.upper()
    if key not in source.record_length_moves:
        source.record_length_moves[key] = _compute_record_length_move(
            key, source.program
        )
    return source.record_length_moves[key]


def _compute_record_length_move(key: str, program) -> str | None:
    from cobolparser.generators.data import ProgramLayoutIndex, VaryingLength

    try:
        records = ProgramLayoutIndex.build(program).records_for_file(key)
    except Exception:  # noqa: BLE001 -- a layout the index cannot read: no MOVE
        return None
    for record in records or []:
        size = int(record.calculate_size() or 0)
        varying = VaryingLength.from_fd_clauses(
            record.get_metadata("fd_clauses"), record_size=size
        )
        if varying is not None and varying.depending_on:
            return f"MOVE {varying.maximum} TO {varying.depending_on}"
    return None


def _row_move_lines(
    row: dict[str, str],
    fixture: BoundaryFixture,
    source: ProgramContext | None = None,
    in_mock_body: bool = True,
) -> list[str]:
    lines = [
        line
        for line in (
            _row_move_line(
                row,
                spec,
                _row_target(spec, source),
                source is not None and source.decimal_comma,
                in_mock_body,
                source,
            )
            for spec in fixture.layout
        )
        if line is not None
    ]
    length_move = _record_length_move(fixture, source)
    if length_move is not None:
        lines.append(length_move)
    return lines


def _single_row_body(
    fixture: BoundaryFixture,
    source: ProgramContext | None = None,
    pinned: frozenset[str] = frozenset(),
) -> list[str]:
    """ACCEPT / CALL / DYNCALL / CICS / DLI (always single-invocation), and
    SQL's own single-row/status-override fallback (see `_sql_wants_rows`).
    MOVEs every field the fixture generated, then -- SQL only -- an
    explicit status MOVE (SQL has no implicit default the way file-op
    categories do: every existing hand-written SQL mock in this codebase
    sets SQLCODE itself, always)."""
    body: list[str] = []
    normal_resp: list[str] = []
    if fixture.category == "CICS":
        layout = _cics_output_layout(fixture, source)
        # RESP/RESP2 answer DFHRESP(NORMAL) and 0 unless the scenario pins
        # them: a random number sent every happy path down the error
        # branch, and --record-expectations recorded it (issue #253).
        normal_resp = [
            name
            for name in _cics_resp_names(
                _cics_fixture_statements(fixture, source) or []
            )
            if name not in pinned
        ]
        layout = [
            spec
            for spec in layout
            if not set(spec.qualified_name.upper().split(".")) & set(normal_resp)
        ]
        fixture = replace(fixture, layout=layout)
    if fixture.sequence:
        body.extend(_row_move_lines(fixture.sequence[0], fixture, source))
    body.extend(f"MOVE 0 TO {name}" for name in normal_resp)
    if fixture.category == "SQL":
        body.extend(_sql_status_lines(fixture))
        return body
    for field_name, code in fixture.status.items():
        body.append(f'MOVE "{code}" TO {field_name}')
    return body
