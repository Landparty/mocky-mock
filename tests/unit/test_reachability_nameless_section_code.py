"""Code before a SECTION's first paragraph header (2026-11-13 benchmark).

cobol-parser names the paragraph holding it "" in every section, so the
reachability walk keyed by name treated them as one paragraph: only the
first section's leading code was walked, everything later sections'
leading code PERFORMs counted as unreachable, `generate` dropped its MOCK
SQL blocks, and the unmocked FETCH loop never ended (PDSTI16A, FRTFRA6A)."""

from __future__ import annotations

from cobolparser import parse_cobol

from mockymock.analysis.refusal._reachability import _reachable_bfs
from tests.unit._generate import _generate

PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SECTLEAD.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-ID               PIC 9(5) VALUE 0.
       01  WS-NAME             PIC X(20).
           EXEC SQL INCLUDE SQLCA END-EXEC.
       PROCEDURE DIVISION.
       MAIN SECTION.
           PERFORM INIT-SEC
           PERFORM WORK-SEC
           GOBACK.
       INIT-SEC SECTION.
           MOVE 1 TO WS-ID.
       INIT-EXIT.
           EXIT.
       WORK-SEC SECTION.
           PERFORM READ-SEC.
       WORK-EXIT.
           EXIT.
       READ-SEC SECTION.
       READ-PARA.
           EXEC SQL
               SELECT NAME INTO :WS-NAME FROM T WHERE ID = :WS-ID
           END-EXEC.
       READ-EXIT.
           EXIT.
"""


def test_every_sections_leading_code_is_walked() -> None:
    result = parse_cobol(PROGRAM, filename="sectlead.cbl")
    assert result.success, result.errors
    reached, reasons = _reachable_bfs(result.ast, "MAIN")
    assert reasons == []
    assert {"WORK-SEC", "READ-SEC", "READ-PARA", "READ-EXIT"} <= reached
    # Callers still see the nameless paragraphs as "".
    assert "" in reached
    assert not any(name.startswith("\x00") for name in reached)


def test_generate_keeps_the_sql_mock_a_later_section_performs(tmp_path) -> None:
    cut = _generate(tmp_path, "SECTLEAD", PROGRAM)
    assert 'MOCK SQL "SELECT"' in cut
