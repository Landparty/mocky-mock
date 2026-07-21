"""Unit tests for analyze_file_status_fields: FD/SELECT FILE STATUS
extraction feeding the FILE-STATUS DSL sugar."""

from cobolparser import parse_cobol

from mockymock.analysis.mock_surface import analyze_file_status_fields

SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. STATFILE.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT WITH-STATUS ASSIGN TO "A.DAT"
               ORGANIZATION IS LINE SEQUENTIAL
               FILE STATUS IS WS-WITH-STATUS.
           SELECT NO-STATUS ASSIGN TO "B.DAT"
               ORGANIZATION IS LINE SEQUENTIAL.

       DATA DIVISION.
       FILE SECTION.
       FD  WITH-STATUS.
       01  WITH-STATUS-REC    PIC X(10).
       FD  NO-STATUS.
       01  NO-STATUS-REC      PIC X(10).

       WORKING-STORAGE SECTION.
       01  WS-WITH-STATUS     PIC X(2).

       PROCEDURE DIVISION.
       MAIN-PROCESS.
           OPEN INPUT WITH-STATUS NO-STATUS.
"""


def _program():
    result = parse_cobol(SOURCE, filename="statfile.cbl")
    assert result.success, result.errors
    return result.ast


def test_file_with_file_status_clause_is_captured():
    fields = analyze_file_status_fields(_program())
    assert fields["WITH-STATUS"] == "WS-WITH-STATUS"


def test_file_without_file_status_clause_has_no_entry():
    fields = analyze_file_status_fields(_program())
    assert "NO-STATUS" not in fields


def test_program_with_no_environment_division_returns_empty():
    source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. NOENV.
       PROCEDURE DIVISION.
       MAIN-PROCESS.
           DISPLAY "HI".
"""
    result = parse_cobol(source, filename="noenv.cbl")
    assert result.success, result.errors
    assert analyze_file_status_fields(result.ast) == {}
