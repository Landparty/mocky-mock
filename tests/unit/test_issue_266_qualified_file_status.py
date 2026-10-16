"""Issue #266: a qualified FILE STATUS IS FS-CODE OF CUST-STAT keeps its
qualifier, so the generated status MOVEs are not ambiguous."""

from cobolparser import parse_cobol

from mockymock.analysis.mock_surface import analyze_file_status_fields

PROGRAM = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. QFS.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT CUST-FILE ASSIGN TO CUSTF
               FILE STATUS IS FS-CODE OF CUST-STAT.
           SELECT ORD-FILE ASSIGN TO ORDF
               FILE STATUS IS FS-CODE OF ORD-STAT.
       DATA DIVISION.
       FILE SECTION.
       FD  CUST-FILE.
       01  CUST-REC          PIC X(10).
       FD  ORD-FILE.
       01  ORD-REC           PIC X(10).
       WORKING-STORAGE SECTION.
       01  CUST-STAT.
           05  FS-CODE     PIC XX.
       01  ORD-STAT.
           05  FS-CODE     PIC XX.
       01  WS-COUNT        PIC 9(3) VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT CUST-FILE
           PERFORM UNTIL FS-CODE OF CUST-STAT NOT = "00"
               READ CUST-FILE
               IF FS-CODE OF CUST-STAT = "00"
                   ADD 1 TO WS-COUNT
               END-IF
           END-PERFORM
           CLOSE CUST-FILE
           GOBACK.
"""


def test_status_field_keeps_its_qualifier_for_file_and_record():
    fields = analyze_file_status_fields(parse_cobol(PROGRAM).ast)
    assert fields["CUST-FILE"] == "FS-CODE OF CUST-STAT"
    assert fields["ORD-FILE"] == "FS-CODE OF ORD-STAT"
    assert fields["CUST-REC"] == "FS-CODE OF CUST-STAT"


def test_unqualified_status_field_is_unchanged():
    source = PROGRAM.replace(" OF CUST-STAT.", ".", 1)
    fields = analyze_file_status_fields(parse_cobol(source).ast)
    assert fields["CUST-FILE"] == "FS-CODE"
