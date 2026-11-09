"""`generate --real`: cases that take a real subprogram's "found" path.

A subprogram that looks up what its caller asks for reads a file until a
record matches a LINKAGE item (`IF RATE-PART = LK-PART`). The placeholder
mock `generate --real` writes for that READ returns end-of-file at once, so
no generated case ever runs the "found" branch, and a change there is never
compared (docs/2026-11-02-real-dynamic-call-design.md, "lookup records").

For every such comparison this module adds one TESTCASE: a copy of the
suite's first case whose own `MOCK READ <file>` returns, on the first READ,
a record holding the caller's value (`MOVE LK-PART TO RATE-PART`, the other
fields generated from their PICTUREs) and end-of-file on the next one. The
mock body runs inside the real program, so it can name its LINKAGE items.
"""

from __future__ import annotations

import random
import re
import zlib
from dataclasses import dataclass

from mockymock.analysis.real_programs import PreparedReal
from mockymock.dsl.model import MockCategory

_EQUAL_RE = re.compile(
    r"^\s*IF\s+(?P<left>[A-Z0-9][A-Z0-9-]*)\s*(?:=|EQUALS?(?:\s+TO)?)\s*"
    r"(?P<right>[A-Z0-9][A-Z0-9-]*)\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class KeyMatch:
    """`IF <record field> = <linkage item>` in a real program."""

    program: str
    file: str
    record_field: str
    linkage_item: str
    line: int


def key_matches(prepared: PreparedReal) -> list[KeyMatch]:
    """Every IF in `prepared` comparing a field of a record it READs with
    one of its LINKAGE items, once per (file, field, item)."""
    from cobolparser.generators.data import ProgramLayoutIndex

    index = ProgramLayoutIndex.build(prepared.ast)
    read_files = {
        key.upper()
        for site in prepared.surface.boundary_sites
        if site.category is MockCategory.READ
        for key in site.keys
    }
    found: list[KeyMatch] = []
    seen: set[tuple[str, str, str]] = set()
    for statement in _if_statements(prepared.ast):
        then = list(getattr(statement, "then_statements", None) or [])
        start = statement.location.line
        end = max(start, then[0].location.line - 1) if then else start
        condition = " ".join(prepared.lines[start - 1 : end]).split("*>", 1)[0]
        match = _EQUAL_RE.match(condition)
        if match is None:
            continue
        sides = [
            index.resolve(match.group("left")),
            index.resolve(match.group("right")),
        ]
        if any(side is None for side in sides):
            continue
        record = next((s for s in sides if s and s.section == "file"), None)
        linkage = next((s for s in sides if s and s.section == "linkage"), None)
        if record is None or linkage is None:
            continue
        file_name = str(record.record.get_metadata("fd_file_name") or "").upper()
        if file_name not in read_files:
            continue
        identity = (file_name, record.spec.name.upper(), linkage.spec.name.upper())
        if identity in seen:
            continue
        seen.add(identity)
        found.append(
            KeyMatch(
                program=prepared.program_id.upper(),
                file=file_name,
                record_field=record.spec.name.upper(),
                linkage_item=linkage.spec.name.upper(),
                line=start,
            )
        )
    return found


def _if_statements(ast: object):
    from mockymock.analysis.mock_surface import (
        _all_paragraphs,
        _nested_statement_lists,
    )

    procedure = ast.get_division("PROCEDURE")  # type: ignore[attr-defined]
    if procedure is None:
        return

    def walk(statements):
        for statement in statements:
            if type(statement).__name__ == "IfStatement":
                yield statement
            for nested in _nested_statement_lists(statement):
                yield from walk(nested)

    for paragraph in _all_paragraphs(procedure):
        yield from walk(paragraph.statements)


def found_record_mock(
    prepared: PreparedReal, match: KeyMatch, end_of_file_body: list[str]
) -> list[str]:
    """`MOCK READ <file>` returning the matching record once, then the
    placeholder's own end-of-file body."""
    from cobolparser.generators.data import (
        DataGeneratorOptions,
        ProgramLayoutIndex,
        ValueFactory,
        flatten_record,
    )

    from mockymock.dsl.generator import _bundle_rendered_value

    index = ProgramLayoutIndex.build(prepared.ast)
    record = index.resolve(match.record_field)
    assert record is not None
    seed = zlib.crc32(f"{match.program}:{match.file}:{match.record_field}".encode())
    factory = ValueFactory(random.Random(seed), DataGeneratorOptions())
    moves = []
    for spec in flatten_record(record.record, DataGeneratorOptions()):
        if spec.name.upper() in ("FILLER", match.record_field):
            continue
        value = _bundle_rendered_value(factory.value_for(spec, 0), spec.category)
        moves.append(f"MOVE {value} TO {spec.name}")
    moves.append(f"MOVE {match.linkage_item} TO {match.record_field}")
    lines = [
        f"    *> {match.program} line {match.line}: a record matching "
        f"{match.linkage_item}, then end of file",
        f"    MOCK READ {match.file}",
        f"        IF {match.record_field} = {match.linkage_item}",
        *(f"            {line}" for line in end_of_file_body),
        "        ELSE",
        *(f"            {line}" for line in moves),
        "        END-IF",
        "    END-MOCK",
    ]
    return lines


def add_found_cases(
    lines: list[str], links: list[PreparedReal], placeholders: dict[str, list[str]]
) -> tuple[list[str], int]:
    """`lines` (the `.cut`) with one case per key match, copied from its
    first TESTCASE. `placeholders` maps a READ key to its placeholder mock's
    body (the end-of-file answer). Returns the new lines and the count."""
    start = next(
        (i for i, line in enumerate(lines) if line.strip().startswith("TESTCASE ")),
        None,
    )
    if start is None:
        return lines, 0
    end = next(
        (
            i
            for i in range(start + 1, len(lines))
            if lines[i].strip().startswith("TESTCASE ")
        ),
        len(lines),
    )
    template = lines[start:end]
    while template and not template[-1].strip():
        template.pop()
    added: list[str] = []
    count = 0
    for prepared in links:
        for match in key_matches(prepared):
            body = placeholders.get(match.file)
            if body is None:
                continue
            name = (
                f"{match.program}: {match.file} has a record matching "
                f"{match.linkage_item}"
            )
            added += ["", f'TESTCASE "{name}"']
            added += found_record_mock(prepared, match, body)
            added += template[1:]
            count += 1
    if not added:
        return lines, 0
    out = list(lines)
    while out and not out[-1].strip():
        out.pop()
    return [*out, *added, ""], count
