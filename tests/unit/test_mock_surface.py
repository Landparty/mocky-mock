from cobolparser import parse_cobol

from mockymock.analysis.mock_surface import CallKind, analyze

SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SAMPLE.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT ORDER-FILE ASSIGN TO "ORDERS"
               ORGANIZATION IS LINE SEQUENTIAL.

       DATA DIVISION.
       FILE SECTION.
       FD  ORDER-FILE.
       01  ORDER-RECORD       PIC X(11).

       WORKING-STORAGE SECTION.
       01  WS-PGM-NAME        PIC X(8) VALUE "DISCRATE".
       01  WS-AMOUNT          PIC 9(5)V99.
       01  WS-RATE            PIC 9V99.

       PROCEDURE DIVISION.
       PROCESS-ORDER.
           CALL "DISCRATE" USING WS-AMOUNT WS-RATE.

       DYNAMIC-DISPATCH.
           CALL WS-PGM-NAME USING WS-AMOUNT.

       READ-AN-ORDER.
           READ ORDER-FILE
               AT END DISPLAY "EOF"
           END-READ.
"""

EXEC_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. EXECSAMP.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-CUST-ID         PIC 9(5).
       01  WS-SEGMENT         PIC X(20).

       PROCEDURE DIVISION.
       RUN-SQL.
           EXEC SQL
               SELECT CUST_ID INTO :WS-CUST-ID FROM CUSTOMERS
           END-EXEC.

       RUN-CICS.
           EXEC CICS
               RECEIVE INTO(WS-CUST-ID)
           END-EXEC.

       RUN-IMS.
           EXEC DLI
               GU SEGMENT-NAME
           END-EXEC.

       NO-EXEC-HERE.
           DISPLAY "no exec statements".
"""


def _ast():
    result = parse_cobol(SOURCE, filename="sample.cbl")
    assert result.success, result.errors
    return result.ast


def _exec_ast():
    result = parse_cobol(EXEC_SOURCE, filename="execsamp.cbl")
    assert result.success, result.errors
    return result.ast


def test_classifies_static_call_site():
    surface = analyze(_ast())
    static = surface.static_call_sites()
    assert len(static) == 1
    assert static[0].program_name == "DISCRATE"
    assert static[0].paragraph_name == "PROCESS-ORDER"
    assert static[0].kind is CallKind.STATIC


def test_classifies_dynamic_call_site():
    surface = analyze(_ast())
    dynamic = surface.dynamic_call_sites()
    assert len(dynamic) == 1
    assert dynamic[0].paragraph_name == "DYNAMIC-DISPATCH"
    assert dynamic[0].kind is CallKind.DYNAMIC


def test_detects_file_io_paragraph():
    surface = analyze(_ast())
    assert "READ-AN-ORDER" in surface.file_io_paragraphs


def test_paragraph_without_file_io_is_not_flagged():
    surface = analyze(_ast())
    assert "PROCESS-ORDER" not in surface.file_io_paragraphs


def test_detects_exec_sql_paragraph():
    surface = analyze(_exec_ast())
    assert "RUN-SQL" in surface.exec_paragraphs


def test_detects_exec_cics_paragraph():
    surface = analyze(_exec_ast())
    assert "RUN-CICS" in surface.exec_paragraphs


def test_detects_exec_dli_paragraph():
    surface = analyze(_exec_ast())
    assert "RUN-IMS" in surface.exec_paragraphs


def test_paragraph_without_exec_is_not_flagged():
    surface = analyze(_exec_ast())
    assert "NO-EXEC-HERE" not in surface.exec_paragraphs
