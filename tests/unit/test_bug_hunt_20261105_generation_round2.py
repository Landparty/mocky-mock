"""Bug hunt of 2026-11-05 (round 2), test generation: a DL/I program that
primes its loop with the same GHN on the same PCB the loop repeats.

The one `MOCK CALL "CBLTDLI"` answered both calls with the first site's
row, pinned to the loop's status: the priming call already returned it, so
the loop never ran (ACCTPRG, LNRECOV: the 2500-GET-NEXT cases were
reported verified). Rows are now dispatched on the calling paragraph
(`UT-CALLING-PARAGRAPH`), the status is pinned only at the call in the
branch's own paragraph, and the end-of-data reply counts each site's own
calls (`UT-SITE-TALLY`)."""

from types import SimpleNamespace

from mockymock.splicer.injector import passed_argument_names, site_tally_lines
from tests.unit.test_bug_hunt_m1_fixes import _generate
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


def _site(paragraph: str, line: int = 40):
    statement = SimpleNamespace(using_parameters=[])
    return SimpleNamespace(statement=statement, paragraph_name=paragraph, line=line)


class _Registry:
    def site_tally(self, line):
        return f"UT-SITE-{line}-TALLY"

    @staticmethod
    def site_case(line):
        return f"UT-SITE-{line}-CASE"


def test_calling_paragraph_and_site_tally_name_the_sites_own():
    body = 'IF UT-CALLING-PARAGRAPH = "2000-SCAN" AND UT-SITE-TALLY > 1'
    assert (
        passed_argument_names(body, _site("2000-scan"), _Registry())
        == 'IF "2000-SCAN" = "2000-SCAN" AND UT-SITE-40-TALLY > 1'
    )
    # The site counter restarts for each case.
    assert site_tally_lines(_site("P"), _Registry()) == [
        "IF UT-SITE-40-CASE NOT = UT-CURRENT-CASE",
        "    MOVE UT-CURRENT-CASE TO UT-SITE-40-CASE",
        "    MOVE 0 TO UT-SITE-40-TALLY",
        "END-IF",
        "ADD 1 TO UT-SITE-40-TALLY",
    ]


def _case(cut: str, name: str) -> str:
    start = cut.index(f'TESTCASE "{name}"')
    end = cut.find("\nTESTCASE ", start + 1)
    return cut[start : end if end != -1 else len(cut)]


def test_priming_and_loop_calls_get_their_own_rows(tmp_path):
    cut = _generate(tmp_path, "PRIMED", PRIMED, "--seed", "1", "--scenarios", "all")
    case = _case(cut, "2000-SCAN: EVALUATE@33 WHEN OTHER")
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
