"""Issue #302 / #262: a placeholder READ or RETURN mock (lint's suggested
fix, `generate --fill`, `--per-paragraph`, and the bundle scaffold's
fallback) answered every call with a record, so a `PERFORM ... UNTIL
<eof-flag>` loop around `READ ... AT END MOVE "Y" TO <eof-flag>` never
ended."""

from __future__ import annotations

from cobolparser import parse_cobol

from mockymock.analysis.mock_surface import analyze, analyze_file_status_fields
from mockymock.dsl.generator import directive_snippet

PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. RD2.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-FILE ASSIGN TO "IN.DAT"
               ORGANIZATION IS LINE SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD IN-FILE.
       01 IN-REC PIC X(10).
       WORKING-STORAGE SECTION.
       01 WS-REC PIC X(10).
       01 WS-EOF PIC X VALUE "N".
       01 WS-CNT PIC 9(4) VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT IN-FILE
           PERFORM 1000-READ UNTIL WS-EOF = "Y"
           CLOSE IN-FILE
           GOBACK.
       1000-READ.
           READ IN-FILE INTO WS-REC
               AT END MOVE "Y" TO WS-EOF
           END-READ
           IF WS-EOF NOT = "Y"
               ADD 1 TO WS-CNT
           END-IF.
"""

WITH_STATUS = PROGRAM.replace(
    "ORGANIZATION IS LINE SEQUENTIAL.",
    "ORGANIZATION IS LINE SEQUENTIAL\n               FILE STATUS IS WS-FS.",
).replace("01 WS-REC PIC X(10).", "01 WS-REC PIC X(10).\n       01 WS-FS PIC XX.")


def _snippet(cbl: str, label: str) -> str | None:
    result = parse_cobol(cbl, filename="RD2.cbl")
    assert result.success, result.errors
    surface = analyze(result.ast)
    site = next(s for s in surface.boundary_sites if s.label == label)
    return directive_snippet(site, surface, analyze_file_status_fields(result.ast))


def test_lint_suggestion_reports_end_of_file_through_the_outcome() -> None:
    assert _snippet(PROGRAM, "READ") == (
        "    MOCK READ IN-FILE\n"
        '        MOVE "10" TO UT-MOCK-STATUS\n'
        '        MOVE "Y" TO WS-EOF\n'
        "    END-MOCK"
    )


def test_lint_suggestion_reports_end_of_file_through_file_status() -> None:
    snippet = _snippet(WITH_STATUS, "READ")
    assert snippet is not None
    assert '        MOVE "10" TO WS-FS' in snippet.splitlines()


def test_read_without_at_end_keeps_the_empty_placeholder() -> None:
    cbl = PROGRAM.replace(
        '               AT END MOVE "Y" TO WS-EOF\n           END-READ\n', ""
    ).replace("READ IN-FILE INTO WS-REC", "READ IN-FILE INTO WS-REC.")
    cbl = cbl.replace(
        '           IF WS-EOF NOT = "Y"\n               ADD 1 TO WS-CNT\n'
        "           END-IF.\n",
        "",
    )
    assert _snippet(cbl, "READ") == "    MOCK READ IN-FILE\n    END-MOCK"


def test_per_paragraph_scaffold_ends_the_read_loop(tmp_path) -> None:
    from mockymock.cli.main import main

    source = tmp_path / "RD2.cbl"
    source.write_text(PROGRAM)
    out = tmp_path / "RD2.cut"
    assert main(["generate", str(source), "--per-paragraph", "-o", str(out)]) == 0
    text = out.read_text()
    block = text[
        text.index("MOCK READ IN-FILE") : text.index(
            "END-MOCK", text.index("MOCK READ IN-FILE")
        )
    ]
    assert 'MOVE "10" TO UT-MOCK-STATUS' in block
