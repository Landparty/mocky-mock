"""Walking a parsed COBOL program: every paragraph, every nested
statement list, every SELECT and FD record.

These are leaf helpers with no mockymock imports. `mock_surface` and the
scanners it runs (`cics_handle`, `sql_whenever`, `declaratives`) all need
them, so they live here rather than in `mock_surface`, which the scanners
would otherwise import back (tests/unit/test_layering.py)."""

from __future__ import annotations

from dataclasses import dataclass

from cobolparser.models.program import (
    CobolDivision,
    CobolParagraph,
    CobolProgram,
    CobolSection,
)
from cobolparser.models.statements.control import EvaluateStatement, SearchStatement
from cobolparser.models.statements.misc import SelectStatement

_NESTED_STATEMENT_ATTRS = (
    "then_statements",
    "else_statements",
    "inline_statements",
    "at_end_clause",
    "not_at_end_clause",
    "invalid_key_clause",
    "not_invalid_key_clause",
    "at_eop_clause",
    "not_at_eop_clause",
    "on_exception",
    "not_on_exception",
    "on_overflow",
    "not_on_overflow",
    "on_size_error",
    "not_on_size_error",
    # RECEIVE ... NO DATA / WITH DATA (Communication Module, cobol-parser
    # 2026-09-02). XML/JSON GENERATE/PARSE's ON EXCEPTION / NOT ON
    # EXCEPTION bodies arrive under the CALL-shaped names already listed.
    "no_data_clause",
    "with_data_clause",
)


def _nested_statement_lists(statement) -> list[list]:
    """Return every nested `list[CobolStatement]` body attached to `statement`.

    Covers IF/ELSE branches, inline PERFORM bodies, IO clause bodies
    (AT END, INVALID KEY, AT END-OF-PAGE), CALL exception handlers, and
    (via the EvaluateStatement/SearchStatement special cases) every
    EVALUATE WHEN/WHEN OTHER branch and every SEARCH WHEN body.
    """
    lists = [
        value
        for attr in _NESTED_STATEMENT_ATTRS
        if (value := getattr(statement, attr, None))
    ]
    if isinstance(statement, EvaluateStatement):
        for when in statement.when_clauses:
            if when.statements:
                lists.append(when.statements)
        if statement.default_when is not None and statement.default_when.statements:
            lists.append(statement.default_when.statements)
    if isinstance(statement, SearchStatement):
        # SearchStatement.when_clauses is a list[dict] with a "statements"
        # key (verified against cobolparser's control.py), unlike
        # EvaluateStatement's WhenClause nodes. SEARCH's AT END body is
        # already covered by "at_end_clause" in _NESTED_STATEMENT_ATTRS.
        for search_when in statement.when_clauses:
            if search_when.get("statements"):
                lists.append(search_when["statements"])
    return lists


def _all_paragraphs(procedure_division: CobolDivision) -> list[CobolParagraph]:
    """Mirrors CoverageAnalyzer._analyze_paragraphs's traversal pattern."""
    paragraphs = list(procedure_division.paragraphs)
    for section in procedure_division._sections.values():
        paragraphs.extend(section.paragraphs)
    return paragraphs


@dataclass(frozen=True)
class FileSelect:
    """What a SELECT says about how a file is read: organization, access
    mode and its keys (uppercased; None/empty when not given)."""

    organization: str | None
    access_mode: str | None
    record_key: str | None
    alternate_keys: tuple[str, ...]
    relative_key: str | None

    @property
    def keyed(self) -> bool:
        """An indexed (KSDS) or relative (RRDS) file a READ without NEXT or
        PREVIOUS reads by key: its access is RANDOM or DYNAMIC."""
        return self.organization in ("INDEXED", "RELATIVE") and (
            self.access_mode in ("RANDOM", "DYNAMIC")
        )


def file_selects(program: CobolProgram) -> dict[str, FileSelect]:
    """Every SELECT of the program, by uppercased file name."""
    selects: dict[str, FileSelect] = {}
    environment = program.get_division("ENVIRONMENT")
    if environment is None:
        return selects
    io_section = environment.get_section_by_name("INPUT-OUTPUT")
    if not isinstance(io_section, CobolSection):
        return selects
    file_control = io_section.get_paragraph_by_name("FILE-CONTROL")
    if file_control is None:
        return selects

    def upper(value: object) -> str | None:
        return str(value).upper() if value else None

    for statement in file_control.statements:
        if not isinstance(statement, SelectStatement) or not statement.file_name:
            continue
        alternates = tuple(
            str(entry.get("key")).upper()
            for entry in getattr(statement, "alternate_keys", None) or []
            if isinstance(entry, dict) and entry.get("key")
        )
        selects[statement.file_name.upper()] = FileSelect(
            organization=upper(getattr(statement, "organization", None)),
            access_mode=upper(getattr(statement, "access_mode", None)),
            record_key=upper(getattr(statement, "record_key", None)),
            alternate_keys=alternates,
            relative_key=upper(getattr(statement, "relative_key", None)),
        )
    return selects


def _fd_records(program: CobolProgram) -> list[tuple[str, str]]:
    """(uppercased record name, uppercased FD file name) for every 01
    declared under an FD/SD."""
    data = program.get_division("DATA")
    if data is None:
        return []
    records: list[tuple[str, str]] = []
    for section in getattr(data, "sections", data.children):
        for item in getattr(section, "children", []):
            if getattr(item, "level", None) != 1:
                continue
            metadata = getattr(item, "_metadata", None) or {}
            file_name = str(metadata.get("fd_file_name") or "").upper()
            name = str(getattr(item, "name", "") or "").upper()
            if file_name and name and name != "FILLER":
                records.append((name, file_name))
    return records
