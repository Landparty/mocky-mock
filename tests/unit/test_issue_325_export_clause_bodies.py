"""Issue #325: `export` restores the 7-column sequence area before
splicing, which put the clause-body lift's AST-column offsets 7
characters early, so every mocked statement lost its AT END / NOT AT END
/ INVALID KEY / ON EXCEPTION bodies (and the UT-MOCK-STATUS bookkeeping)
in the exported source while `run` kept them."""

from mockymock.cli.main import main

PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. RDCNT.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-FILE ASSIGN TO "IN.DAT"
               FILE STATUS IS WS-FS.
       DATA DIVISION.
       FILE SECTION.
       FD  IN-FILE.
       01  IN-REC.
           05  IN-AMT          PIC 9(3).
       WORKING-STORAGE SECTION.
       01  WS-FS               PIC XX.
       01  WS-EOF              PIC X VALUE "N".
       01  WS-TOTAL            PIC 9(5) VALUE 0.
       01  WS-COUNT            PIC 9(3) VALUE 0.
       PROCEDURE DIVISION.
       0000-MAIN.
           PERFORM 1000-READ UNTIL WS-EOF = "Y"
           GOBACK.
       1000-READ.
           READ IN-FILE
               AT END
                   MOVE "Y" TO WS-EOF
               NOT AT END
                   ADD IN-AMT TO WS-TOTAL
                   ADD 1 TO WS-COUNT
           END-READ.
"""

CUT = """\
TESTSUITE "RDCNT"

TESTCASE "two records are totalled"
    MOCK READ IN-FILE ROWS
        ( IN-AMT = 10 )
        ( IN-AMT = 20 )
    END-MOCK
    PERFORM 0000-MAIN
    EXPECT WS-COUNT TO BE 2
    EXPECT WS-TOTAL TO BE 30
"""


def test_export_keeps_the_mocked_reads_clause_bodies(tmp_path, capsys):
    cbl = tmp_path / "RDCNT.cbl"
    cbl.write_text(PROGRAM)
    cut = tmp_path / "RDCNT.cut"
    cut.write_text(CUT)
    out_path = tmp_path / "RDCNT-EXPORT.cbl"

    assert main(["export", str(cbl), "--cut", str(cut), "-o", str(out_path)]) == 0
    capsys.readouterr()
    live = [
        line.strip()
        for line in out_path.read_text().splitlines()
        if not line.lstrip().startswith("*>") and line[6:7] != "*"
    ]
    at_end = live.index('WHEN UT-MOCK-STATUS(1:1) = "1"')
    assert live[at_end + 1] == 'MOVE "Y" TO WS-EOF'
    not_at_end = live.index('WHEN UT-MOCK-STATUS(1:1) = "0"')
    assert live[not_at_end + 1 : not_at_end + 3] == [
        "ADD IN-AMT TO WS-TOTAL",
        "ADD 1 TO WS-COUNT",
    ]
    assert "MOVE WS-FS TO UT-MOCK-STATUS" in live
