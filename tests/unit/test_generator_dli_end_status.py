"""A looped DL/I get-next ends on the status its loop waits for
(2026-11-03, samples IMSORDER and IMSPATIE): a qualified GN reports GE at
the end of its range, not GB, so answering the default GB never satisfied
`PERFORM UNTIL PCB-STATUS = 'GE'` and the run spun until the timeout."""

from __future__ import annotations

from tests.unit._generate import _generate

PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. DLIGE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  DLI-GN          PIC X(4) VALUE 'GN  '.
       01  WS-EOF          PIC X VALUE 'N'.
           88  AT-END      VALUE 'Y'.
       01  SEG-IO          PIC X(20).
       01  SSA-QUAL        PIC X(20).
       LINKAGE SECTION.
       01  DB-PCB.
           05  PCB-DBD     PIC X(8).
           05  PCB-LEVEL   PIC XX.
           05  PCB-STATUS  PIC XX.
       PROCEDURE DIVISION USING DB-PCB.
       MAIN-PARA.
           CALL 'CBLTDLI' USING DLI-GN DB-PCB SEG-IO SSA-QUAL
           LOOP
           GOBACK.
"""

UNTIL_STATUS = """\
           PERFORM UNTIL PCB-STATUS = 'GE'
               DISPLAY SEG-IO
               CALL 'CBLTDLI' USING DLI-GN DB-PCB SEG-IO SSA-QUAL
           END-PERFORM"""

UNTIL_FLAG = """\
           PERFORM UNTIL AT-END
               IF PCB-STATUS = 'GE'
                   MOVE 'Y' TO WS-EOF
               ELSE
                   CALL 'CBLTDLI' USING DLI-GN DB-PCB SEG-IO SSA-QUAL
               END-IF
           END-PERFORM"""


def test_a_loop_on_the_status_gets_that_status(tmp_path) -> None:
    cut = _generate(tmp_path, "DLIGE", PROGRAM.replace("           LOOP", UNTIL_STATUS))
    assert 'MOVE "GE" TO DB-PCB(11:2)' in cut
    assert 'MOVE "GB" TO DB-PCB(11:2)' not in cut


def test_a_loop_on_a_flag_set_from_the_status_gets_that_status(tmp_path) -> None:
    cut = _generate(tmp_path, "DLIGE", PROGRAM.replace("           LOOP", UNTIL_FLAG))
    assert 'MOVE "GE" TO DB-PCB(11:2)' in cut
    assert 'MOVE "GB" TO DB-PCB(11:2)' not in cut


def test_a_loop_on_gb_keeps_gb(tmp_path) -> None:
    program = PROGRAM.replace("           LOOP", UNTIL_STATUS.replace("'GE'", "'GB'"))
    cut = _generate(tmp_path, "DLIGE", program)
    assert 'MOVE "GB" TO DB-PCB(11:2)' in cut


# Regression: executed bug hunt of 2026-10-05 (issues #139-#150); the executed
# counterparts live in tests/integration/test_bug_hunt_m1_fixes.py.
import pytest

SCAN_CBL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SCAN.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-SEG    PIC X(20).
       01  WS-COUNT  PIC 9(3) VALUE 0.
       01  WS-DONE   PIC X VALUE "N".
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM UNTIL WS-DONE = "Y"
               EXEC DLI GNP SEGMENT(ACCT) INTO(WS-SEG) END-EXEC
               IF DIBSTAT = SPACES
                   ADD 1 TO WS-COUNT
               ELSE
                   MOVE "Y" TO WS-DONE
               END-IF
           END-PERFORM
           GOBACK.
"""


def test_145_looped_get_next_dli_mock_reports_end_of_segments(tmp_path) -> None:
    cut = _generate(tmp_path, "SCAN", SCAN_CBL, "--seed", "1")
    assert 'MOVE "GE" TO DIBSTAT' in cut
    assert "-TALLY > 1" in cut


PRIMED_SCAN_CBL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. EDL.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-SEG  PIC X(20).
       01 WS-CNT  PIC 9(4) VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           EXEC DLI GN USING PCB(1) SEGMENT(CUSTSEG) INTO(WS-SEG)
           END-EXEC
           PERFORM UNTIL DIBSTAT NOT = SPACES
               ADD 1 TO WS-CNT
               EXEC DLI GN USING PCB(1) SEGMENT(CUSTSEG) INTO(WS-SEG)
               END-EXEC
           END-PERFORM
           GOBACK.
"""


@pytest.mark.parametrize("mode", ["--with-data", "--per-paragraph"])
def test_315_primed_get_next_loop_reports_end_of_segments(tmp_path, mode) -> None:
    """Issue #315: the priming GN before the loop is the first site seen
    for the key and is not itself looped; the GN inside the loop is."""
    from mockymock.cli.main import main

    source = tmp_path / "EDL.cbl"
    source.write_text(PRIMED_SCAN_CBL)
    out = tmp_path / "EDL.cut"
    assert main(["generate", str(source), mode, "-o", str(out)]) == 0
    assert 'MOVE "GB" TO DIBSTAT' in out.read_text()


# Regression: bug hunt of 2026-11-05 (round 2), test generation: a DL/I program
# that primes its loop with the same GHN on the same PCB the loop repeats. The
# one `MOCK CALL "CBLTDLI"` answered both calls with the first site's row,
# pinned to the loop's status, so the loop never ran (ACCTPRG, LNRECOV). Rows
# are now dispatched on the calling paragraph (`UT-CALLING-PARAGRAPH`), the
# status is pinned only at the call in the branch's own paragraph, and the
# end-of-data reply counts each site's own calls (`UT-SITE-TALLY`). Executed
# counterpart: tests/integration/test_bug_hunt_20261105_generation_round2.py.
from tests.unit.test_issue_156_loop_end_reply import _mock

PRIMED = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PRIMED.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  DLI-GHN              PIC X(4) VALUE 'GHN '.
       01  SSA-CUST             PIC X(9) VALUE 'CUSTSEG  '.
       01  WS-SEG.
           05  SG-ID            PIC X(8).
       01  WS-EOF               PIC X VALUE 'N'.
           88  END-OF-DB        VALUE 'Y'.
       LINKAGE SECTION.
       01  DB-PCB.
           05  DB-NAME          PIC X(8).
           05  DB-LEVEL         PIC XX.
           05  DB-STATUS        PIC XX.
           05  FILLER           PIC X(20).
       PROCEDURE DIVISION.
       0000-MAIN.
           ENTRY 'DLITCBL' USING DB-PCB.
           PERFORM 1000-PRIME
           PERFORM 2000-SCAN UNTIL END-OF-DB
           GOBACK.
       1000-PRIME.
           CALL 'CBLTDLI' USING DLI-GHN DB-PCB WS-SEG SSA-CUST
           EVALUATE DB-STATUS
               WHEN SPACES
                   CONTINUE
               WHEN 'GB'
                   SET END-OF-DB TO TRUE
           END-EVALUATE.
       2000-SCAN.
           CALL 'CBLTDLI' USING DLI-GHN DB-PCB WS-SEG SSA-CUST
           EVALUATE DB-STATUS
               WHEN SPACES
                   DISPLAY 'NEXT ' SG-ID
               WHEN 'GB'
                   SET END-OF-DB TO TRUE
               WHEN OTHER
                   SET END-OF-DB TO TRUE
           END-EVALUATE.
"""


def _case(cut: str, name: str) -> str:
    start = cut.index(f'TESTCASE "{name}"')
    end = cut.find("\nTESTCASE ", start + 1)
    return cut[start : end if end != -1 else len(cut)]


def test_priming_and_loop_calls_get_their_own_rows(tmp_path):
    cut = _generate(tmp_path, "PRIMED", PRIMED, "--seed", "1", "--scenarios", "all")
    # WHEN GB, not WHEN OTHER: the published cobol-parser plans no WHEN OTHER
    # case here (fixed by the cobol-parser PR of this round).
    case = _case(cut, "2000-SCAN: EVALUATE@33 WHEN GB")
    body = _mock(case, 'MOCK CALL "CBLTDLI"')
    prime = body.index('UT-CALLING-PARAGRAPH = "1000-PRIME"')
    scan = body.index('UT-CALLING-PARAGRAPH = "2000-SCAN"')
    prime_row = body[prime:scan] if prime < scan else body[prime:]
    scan_row = body[scan:prime] if scan < prime else body[scan:]
    # The loop's status is given at the loop's call only; the priming call
    # finds its segment, so the loop runs.
    assert "MOVE SPACES TO DB-PCB(11:2)" in prime_row
    assert "MOVE SPACES TO DB-PCB(11:2)" not in scan_row.split("END-EVALUATE")[0]
    # The end-of-data reply waits for the loop call's own second call.
    assert "IF UT-SITE-TALLY > 1" in body
    assert "UT-CBLTDLI-TALLY > 1" not in body


# Regression: stress test of the integrated testing stack (backend test packs +
# oracle over a synthetic corpus of every program type), 2026-11-02. One row
# per DL/I call.


# --- one row per DL/I call --------------------------------------------------

IMS_MPP = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. IMSORD.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  DLI-GU               PIC X(4) VALUE 'GU  '.
       01  DLI-ISRT             PIC X(4) VALUE 'ISRT'.
       01  WS-IN-MSG.
           05  IM-LL            PIC S9(4) COMP.
           05  IM-ZZ            PIC S9(4) COMP.
           05  IM-PART          PIC X(8).
       01  WS-OUT-MSG.
           05  OM-LL            PIC S9(4) COMP VALUE 30.
           05  OM-ZZ            PIC S9(4) COMP VALUE 0.
           05  OM-CODE          PIC X(3).
       01  WS-SEG.
           05  SG-PART          PIC X(8).
       LINKAGE SECTION.
       01  IO-PCB.
           05  IO-LTERM         PIC X(8).
           05  FILLER           PIC XX.
           05  IO-STATUS        PIC XX.
           05  FILLER           PIC X(20).
       01  DB-PCB.
           05  DB-NAME          PIC X(8).
           05  DB-LEVEL         PIC XX.
           05  DB-STATUS        PIC XX.
           05  FILLER           PIC X(20).
       PROCEDURE DIVISION.
       0000-MAIN.
           ENTRY 'DLITCBL' USING IO-PCB DB-PCB.
           CALL 'CBLTDLI' USING DLI-GU IO-PCB WS-IN-MSG
           PERFORM UNTIL IO-STATUS NOT = SPACES
               CALL 'CBLTDLI' USING DLI-GU DB-PCB WS-SEG
               EVALUATE DB-STATUS
                   WHEN SPACES
                       CALL 'IMSCHK' USING WS-SEG OM-CODE
                   WHEN 'GE'
                       MOVE 'NF ' TO OM-CODE
               END-EVALUATE
               CALL 'CBLTDLI' USING DLI-ISRT IO-PCB WS-OUT-MSG
               CALL 'CBLTDLI' USING DLI-GU IO-PCB WS-IN-MSG
           END-PERFORM
           GOBACK.
"""


def test_each_dli_call_gets_its_own_row(tmp_path):
    """IMSORD: one MOCK answered the message GU, the DB GU and the ISRT
    with the first fixture's row, so the DB PCB status a branch needed
    was lost and the found path (and IMSCHK) never ran."""
    cut = _generate(tmp_path, "IMSORD", IMS_MPP, "--seed", "1", "--scenarios", "all")
    body = _mock(cut, 'MOCK CALL "CBLTDLI"')
    assert 'WHEN UT-CAP-CBLTDLI-1 = "GU" AND UT-PASSED-ARG-2 = "IO-PCB"' in body
    assert 'WHEN UT-CAP-CBLTDLI-1 = "GU" AND UT-PASSED-ARG-2 = "DB-PCB"' in body
    assert 'WHEN UT-CAP-CBLTDLI-1 = "ISRT"' in body
    # Only the message GU ends the loop; the DB GU keeps its row's status
    # (the priming GU shares function and PCB, so the tally tells them
    # apart).
    assert "IF UT-CBLTDLI-TALLY > 1" in body
    assert 'MOVE "QC" TO IO-PCB(11:2)' in body
    assert 'MOVE "GE" TO DB-PCB(11:2)' not in body
    assert 'MOVE "GE" TO DB-STATUS' in cut  # the not-found case's own row
