"""Composes cobolparser analyzers into a single mock-surface report.

v1 only mocks STATIC CALL sites. Dynamic CALL sites, file I/O, and EXEC
SQL/CICS/DLI are *detected* here (for the refusal gate in Task 6) but not
mockable — that's the modularity seam for later categories.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from cobolparser.models.program import CobolDivision, CobolParagraph, CobolProgram
from cobolparser.models.sql_statements import ExecSQLStatement
from cobolparser.models.statements.call import CallStatement
from cobolparser.models.statements.io import (
    IOCloseStatement,
    IODeleteStatement,
    IOOpenStatement,
    IOReadStatement,
    IORewriteStatement,
    IOWriteStatement,
)
from cobolparser.parsers.statements.ibm_exec_statements import (
    ExecCicsStatement,
    ExecImsStatement,
)


class CallKind(Enum):
    STATIC = "static"
    DYNAMIC = "dynamic"


@dataclass
class CallSite:
    program_name: str | None  # literal name if STATIC, None if DYNAMIC
    kind: CallKind
    paragraph_name: str
    line: int


@dataclass
class MockSurface:
    call_sites: list[CallSite] = field(default_factory=list)
    file_io_paragraphs: set[str] = field(default_factory=set)
    exec_paragraphs: set[str] = field(default_factory=set)

    def static_call_sites(self) -> list[CallSite]:
        return [c for c in self.call_sites if c.kind is CallKind.STATIC]

    def dynamic_call_sites(self) -> list[CallSite]:
        return [c for c in self.call_sites if c.kind is CallKind.DYNAMIC]


_FILE_IO_TYPES = (
    IOOpenStatement,
    IOCloseStatement,
    IOReadStatement,
    IOWriteStatement,
    IORewriteStatement,
    IODeleteStatement,
)

# NOTE: The plan's reference code guessed `statement.node_type in
# ("EXEC_SQL", "EXEC_CICS", "EXEC_DLI")`. Verified against cobolparser
# source (not guessed):
#   - EXEC SQL   -> ExecSQLStatement (cobolparser/models/sql_statements.py),
#                   node_type == "EXEC-SQL" (hyphen, not underscore)
#   - EXEC CICS  -> ExecCicsStatement (cobolparser/parsers/statements/
#                   ibm_exec_statements.py), node_type == "EXEC_CICS"
#   - EXEC DLI   -> ExecImsStatement (same file), node_type == "EXEC_IMS"
#                   (NOT "EXEC_DLI" as guessed)
# isinstance is used instead of node_type string matching so that
# ExecSQLStatement subclasses (DeclareCursorStatement, FetchStatement,
# DynamicSQLStatement, etc. — all of which keep node_type == "EXEC-SQL")
# are caught without hardcoding every subclass's node_type string.
_EXEC_TYPES = (ExecSQLStatement, ExecCicsStatement, ExecImsStatement)


def analyze(program: CobolProgram) -> MockSurface:
    """Walk PROCEDURE DIVISION and classify every CALL/file-IO/EXEC statement."""
    surface = MockSurface()
    procedure = program.get_division("PROCEDURE")
    if procedure is None:
        return surface

    for paragraph in _all_paragraphs(procedure):
        for statement in paragraph.statements:
            if isinstance(statement, CallStatement):
                kind = CallKind.DYNAMIC if statement.is_dynamic else CallKind.STATIC
                surface.call_sites.append(
                    CallSite(
                        program_name=None if statement.is_dynamic else statement.called_program,
                        kind=kind,
                        paragraph_name=paragraph.paragraph_name,
                        line=statement.location.line,
                    )
                )
            elif isinstance(statement, _FILE_IO_TYPES):
                surface.file_io_paragraphs.add(paragraph.paragraph_name)
            elif isinstance(statement, _EXEC_TYPES):
                surface.exec_paragraphs.add(paragraph.paragraph_name)

    return surface


def _all_paragraphs(procedure_division: CobolDivision) -> list[CobolParagraph]:
    """Mirrors CoverageAnalyzer._analyze_paragraphs's traversal pattern."""
    paragraphs = list(procedure_division.paragraphs)
    for section in procedure_division._sections.values():
        paragraphs.extend(section.paragraphs)
    return paragraphs
