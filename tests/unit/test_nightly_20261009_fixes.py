"""Regression tests for the 2026-10-09 nightly bug hunt. The executed
counterpart lives in tests/integration/test_nightly_20261009_fixes.py."""

from __future__ import annotations

from tests.unit.test_bug_hunt_m1_fixes import _generate

PRIME_CBL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PRIME.
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
       01  WS-EOF          PIC X VALUE "N".
           88  EOF-YES     VALUE "Y".
       01  WS-TOTAL        PIC 9(7) VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT IN-FILE
           READ IN-FILE
               AT END SET EOF-YES TO TRUE
           END-READ
           PERFORM PROCESS-REC UNTIL EOF-YES
           CLOSE IN-FILE
           DISPLAY WS-TOTAL
           GOBACK.
       PROCESS-REC.
           ADD IN-AMT TO WS-TOTAL
           READ IN-FILE
               AT END SET EOF-YES TO TRUE
           END-READ.
"""


def _read_mock(cut: str) -> str:
    start = cut.index("MOCK READ IN-FILE")
    return cut[start : cut.index("END-MOCK", start)]


def test_priming_read_loop_gets_a_body_that_ends_the_loop(tmp_path) -> None:
    """A priming READ plus a READ inside the loop are two cobol-parser
    fixtures for one mockymock site. They used to be merged as if they were
    a multi-file OPEN's status-only group, which left the READ mock empty
    and the PERFORM UNTIL EOF-YES loop spinning forever."""
    cut = _generate(tmp_path, "PRIME", PRIME_CBL, "--seed", "3", "--rows", "3")
    body = _read_mock(cut)
    assert "WHEN OTHER" in body
    # The exhaustion branch reports end of file; the splice then runs the
    # program's own `AT END SET EOF-YES TO TRUE` (issue #209).
    assert 'MOVE "10" TO' in body
    assert "the splice runs this READ's own AT END clause" in body


def test_priming_read_loop_verify_counts_one_stream_not_each_site(
    tmp_path,
) -> None:
    """Both READ sites consume the same sequential file: 3 rows plus the
    end-of-file READ is 4 calls in total, not the sum of each site's own
    per-site count."""
    cut = _generate(tmp_path, "PRIME", PRIME_CBL, "--seed", "3", "--rows", "3")
    assert cut.count("VERIFY READ IN-FILE") == 1
    assert "VERIFY READ IN-FILE WAS CALLED 4 TIMES" in cut
