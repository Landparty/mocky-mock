"""A READ loop that ends on its FILE STATUS alone (no AT END clause) must
get an end-of-file branch from `generate --with-data`. The executed
counterpart lives in tests/integration/test_nightly_20261013b_status_read_eof.py."""

from __future__ import annotations

from tests.unit.test_bug_hunt_m1_fixes import _generate

STATUS_LOOP_CBL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. STATLOOP.
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
           05  IN-AMT      PIC 9(3).
       WORKING-STORAGE SECTION.
       01  WS-FS           PIC XX.
       01  WS-TOTAL        PIC 9(7) VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT IN-FILE
           PERFORM READ-PARA
           PERFORM UNTIL WS-FS = "10"
               ADD IN-AMT TO WS-TOTAL
               PERFORM READ-PARA
           END-PERFORM
           CLOSE IN-FILE
           DISPLAY WS-TOTAL
           GOBACK.
       READ-PARA.
           READ IN-FILE.
"""

#: The same loop over an indexed file read by key: running out of rows is
#: "23" (record not found) for it, never "10".
KEYED_CBL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. KEYED.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-FILE ASSIGN TO "IN.DAT"
               ORGANIZATION IS INDEXED
               ACCESS MODE IS RANDOM
               RECORD KEY IS IN-KEY
               FILE STATUS IS WS-FS.
       DATA DIVISION.
       FILE SECTION.
       FD  IN-FILE.
       01  IN-REC.
           05  IN-KEY      PIC 9(3).
           05  IN-AMT      PIC 9(3).
       WORKING-STORAGE SECTION.
       01  WS-FS           PIC XX.
       01  WS-TOTAL        PIC 9(7) VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT IN-FILE
           MOVE 1 TO IN-KEY
           READ IN-FILE
           ADD IN-AMT TO WS-TOTAL
           CLOSE IN-FILE
           GOBACK.
"""


def _read_mock(cut: str) -> str:
    start = cut.index("MOCK READ IN-FILE")
    return cut[start : cut.index("END-MOCK", start)]


def test_status_driven_read_loop_gets_an_end_of_file_branch(tmp_path) -> None:
    """cobol-parser gives a READ fixture a terminal only when the READ has
    an AT END clause. Without one, the body was rows and nothing else: the
    implicit MOVE "00" reported success forever and the loop never ended."""
    cut = _generate(tmp_path, "STATLOOP", STATUS_LOOP_CBL, "--seed", "3", "--rows", "3")
    body = _read_mock(cut)
    assert "WHEN OTHER" in body
    assert 'MOVE "10" TO WS-FS' in body


def test_status_driven_read_loop_counts_the_end_of_file_read(tmp_path) -> None:
    """Three rows plus the READ that finds the end of the file."""
    cut = _generate(tmp_path, "STATLOOP", STATUS_LOOP_CBL, "--seed", "3", "--rows", "3")
    assert "VERIFY READ IN-FILE WAS CALLED 4 TIMES" in cut


def test_empty_input_scenario_reports_end_of_file_on_the_first_read(
    tmp_path,
) -> None:
    cut = _generate(
        tmp_path, "STATLOOP", STATUS_LOOP_CBL, "--seed", "3", "--scenarios", "all"
    )
    start = cut.index('TESTCASE "empty input"')
    case = cut[start : cut.index("TESTCASE", start + 1)]
    assert 'MOVE "10" TO WS-FS' in _read_mock(case)
    assert "VERIFY READ IN-FILE WAS CALLED 1 TIMES" in case


def test_keyed_read_gets_no_end_of_file_status(tmp_path) -> None:
    cut = _generate(tmp_path, "KEYED", KEYED_CBL, "--seed", "3")
    assert 'MOVE "10" TO WS-FS' not in cut
