"""Executed regressions for READ ... INTO (and the FILE SECTION reset)
found by the 2026-10-09 nightly bug hunt: each compiles and runs with real
GnuCOBOL. Unit-level counterparts are in
tests/unit/test_nightly_20261009_read_into.py."""

from __future__ import annotations

from pathlib import Path

from tests.integration._docker import requires_docker
from tests.integration.test_bug_hunt_m1_fixes import _run

RINTO_CBL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. RINTO.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-FILE ASSIGN TO "IN.DAT"
               ORGANIZATION IS SEQUENTIAL
               FILE STATUS IS WS-FS.
       DATA DIVISION.
       FILE SECTION.
       FD  IN-FILE.
       01  IN-REC.
           05  R-ID        PIC X(3).
           05  R-AMT       PIC 9(3).
       WORKING-STORAGE SECTION.
       01  WS-FS           PIC XX.
       01  WS-REC.
           05  R-ID        PIC X(3).
           05  R-AMT       PIC 9(3).
       01  WS-TOTAL        PIC 9(5) VALUE 0.
       01  WS-EOF          PIC X VALUE "N".
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM READ-ONE
           STOP RUN.
       READ-ONE.
           READ IN-FILE INTO WS-REC
           ADD R-AMT OF WS-REC TO WS-TOTAL.
"""

RINTO_CUT = """\
TESTSUITE "rinto"
TESTCASE "qualified body"
    MOCK READ IN-FILE
        MOVE "ABC" TO R-ID OF IN-REC
        MOVE 5 TO R-AMT OF IN-REC
    END-MOCK
    PERFORM READ-ONE
    EXPECT WS-TOTAL TO BE 5
TESTCASE "record group move"
    MOCK READ IN-FILE
        MOVE "ABC007" TO IN-REC
    END-MOCK
    PERFORM READ-ONE
    EXPECT WS-TOTAL TO BE 7
"""


@requires_docker
def test_rinto(tmp_path: Path, capsys) -> None:
    """A body qualified OF the FD record still gets the INTO copy, though the INTO item shares the field names."""
    exit_code = _run(tmp_path, "RINTO", RINTO_CBL, RINTO_CUT)
    out = capsys.readouterr().out
    assert exit_code == 0, out


RNF_CBL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. RNF.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT CUST-FILE ASSIGN TO "CUST.DAT"
               ORGANIZATION IS INDEXED
               ACCESS MODE IS RANDOM
               RECORD KEY IS CUST-KEY
               FILE STATUS IS WS-FS.
       DATA DIVISION.
       FILE SECTION.
       FD  CUST-FILE.
       01  CUST-REC.
           05  CUST-KEY    PIC X(4).
           05  CUST-NAME   PIC X(10).
       WORKING-STORAGE SECTION.
       01  WS-FS           PIC XX.
       01  WS-CUST.
           05  WS-KEY      PIC X(4).
           05  WS-NAME     PIC X(10).
       PROCEDURE DIVISION.
       LOOKUP.
           MOVE "0001" TO CUST-KEY
           MOVE "UNKNOWN" TO WS-NAME
           READ CUST-FILE INTO WS-CUST
               INVALID KEY CONTINUE
           END-READ.
"""

RNF_CUT = """\
TESTSUITE "rnf"
TESTCASE "not found keeps default"
    MOCK READ CUST-FILE
        FILE-STATUS IS RECORD-NOT-FOUND
    END-MOCK
    PERFORM LOOKUP
    EXPECT WS-FS TO BE "23"
    EXPECT WS-NAME TO BE "UNKNOWN"
"""


@requires_docker
def test_rnf(tmp_path: Path, capsys) -> None:
    """A mocked READ that fails leaves the INTO item alone, as a real one does."""
    exit_code = _run(tmp_path, "RNF", RNF_CBL, RNF_CUT)
    out = capsys.readouterr().out
    assert exit_code == 0, out


MR_CBL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. MR.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-FILE ASSIGN TO "MR.DAT"
               ORGANIZATION IS LINE SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD  IN-FILE.
       01  IN-HDR          PIC X(2).
       01  IN-DTL          PIC X(10).
       WORKING-STORAGE SECTION.
       01  WS-REC          PIC X(10).
       PROCEDURE DIVISION.
       READ-ONE.
           READ IN-FILE INTO WS-REC
               AT END CONTINUE
           END-READ.
       MAIN-PARA.
           OPEN INPUT IN-FILE
           PERFORM READ-ONE
           DISPLAY "[" WS-REC "]"
           CLOSE IN-FILE
           STOP RUN.
"""

MR_CUT = """\
TESTSUITE "mr"
TESTCASE "detail record"
    MOCK READ IN-FILE
        MOVE "ABCDEFGHIJ" TO IN-DTL
    END-MOCK
    PERFORM READ-ONE
    EXPECT WS-REC TO BE "ABCDEFGHIJ"
"""


@requires_docker
def test_mr(tmp_path: Path, capsys) -> None:
    """An FD with several 01 records copies the longest one into the INTO item."""
    exit_code = _run(tmp_path, "MR", MR_CBL, MR_CUT)
    out = capsys.readouterr().out
    assert exit_code == 0, out


FDR_CBL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. FDR.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT OUT-FILE ASSIGN TO "OUT.DAT"
               ORGANIZATION IS SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD  OUT-FILE.
       01  OUT-HDR         PIC X(2).
       01  OUT-DTL         PIC X(10).
       WORKING-STORAGE SECTION.
       01  WS-X            PIC X.
       PROCEDURE DIVISION.
       FILL-PARA.
           MOVE ALL "Z" TO OUT-DTL.
       NOOP-PARA.
           CONTINUE.
"""

FDR_CUT = """\
TESTSUITE "fdr"
TESTCASE "dirty"
    PERFORM FILL-PARA
    EXPECT OUT-DTL TO BE "ZZZZZZZZZZ"
TESTCASE "clean"
    PERFORM NOOP-PARA
    EXPECT OUT-DTL TO BE SPACES
"""


@requires_docker
def test_fdr(tmp_path: Path, capsys) -> None:
    """The reset between cases clears an FD's longest record, not just its first."""
    exit_code = _run(tmp_path, "FDR", FDR_CBL, FDR_CUT)
    out = capsys.readouterr().out
    assert exit_code == 0, out
