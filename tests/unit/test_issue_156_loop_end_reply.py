"""Issue #156 item 1: a looped MQGET or CBLTDLI get call whose loop waits on
the call's own reply used to replay its row forever. The executed
counterpart lives in tests/integration/test_issue_156_loop_end_reply.py."""

from __future__ import annotations

from tests.unit.test_bug_hunt_m1_fixes import _generate

MQ_LOOP_CBL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. MQLOOP.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-HCONN        PIC S9(9) BINARY.
       01  WS-HOBJ         PIC S9(9) BINARY.
       01  WS-MD           PIC X(364).
       01  WS-GMO          PIC X(112).
       01  WS-BUFLEN       PIC S9(9) BINARY VALUE 80.
       01  WS-BUFFER       PIC X(80).
       01  WS-DATALEN      PIC S9(9) BINARY.
       01  WS-COMPCODE     PIC S9(9) BINARY.
       01  WS-REASON       PIC S9(9) BINARY.
       01  WS-COUNT        PIC 9(4) VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM UNTIL WS-REASON = 2033
               CALL 'MQGET' USING WS-HCONN WS-HOBJ WS-MD WS-GMO
                    WS-BUFLEN WS-BUFFER WS-DATALEN WS-COMPCODE
                    WS-REASON
               IF WS-COMPCODE = 0
                   ADD 1 TO WS-COUNT
               END-IF
           END-PERFORM
           DISPLAY WS-COUNT
           STOP RUN.
"""

IMS_LOOP_CBL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. IMSLOOP.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  DLI-GN          PIC X(4) VALUE 'GN  '.
       01  DLI-ISRT        PIC X(4) VALUE 'ISRT'.
       01  WS-IO-AREA      PIC X(40).
       01  WS-COUNT        PIC 9(4) VALUE 0.
       LINKAGE SECTION.
       01  DB-PCB.
           05  PCB-DBD     PIC X(8).
           05  PCB-LEVEL   PIC XX.
           05  PCB-STATUS  PIC XX.
               88  PCB-END-OF-DB VALUE 'GB'.
           05  PCB-REST    PIC X(24).
       PROCEDURE DIVISION.
           ENTRY 'DLITCBL' USING DB-PCB.
       MAIN-PARA.
           PERFORM UNTIL PCB-END-OF-DB
               CALL 'CBLTDLI' USING DLI-GN DB-PCB WS-IO-AREA
               IF NOT PCB-END-OF-DB
                   ADD 1 TO WS-COUNT
               END-IF
           END-PERFORM
           DISPLAY WS-COUNT
           GOBACK.
"""


def _scaffold(tmp_path, name: str, cbl: str) -> str:
    from mockymock.cli.main import main

    source = tmp_path / f"{name}.cbl"
    source.write_text(cbl)
    out = tmp_path / f"{name}.cut"
    assert main(["generate", str(source), "--per-paragraph", "-o", str(out)]) == 0
    return out.read_text()


def _mock(cut: str, header: str) -> str:
    start = cut.index(header)
    return cut[start : cut.index("END-MOCK", start)]


def test_looped_mqget_reports_no_message_after_its_row(tmp_path) -> None:
    cut = _generate(tmp_path, "MQLOOP", MQ_LOOP_CBL, "--seed", "1")
    body = _mock(cut, 'MOCK MQ "MQGET"')
    assert "IF UT-MQGET-TALLY > 1" in body
    assert "MOVE 2 TO WS-COMPCODE" in body
    assert "MOVE 2033 TO WS-REASON" in body
    # One call returns the row, the next one ends the loop.
    assert 'VERIFY CALL "MQGET" WAS CALLED 2 TIMES' in cut


def test_scaffolded_looped_mqget_ends_the_loop_on_the_first_call(tmp_path) -> None:
    body = _mock(_scaffold(tmp_path, "MQLOOP", MQ_LOOP_CBL), 'MOCK MQ "MQGET"')
    assert "MOVE 2033 TO WS-REASON" in body
    assert "TALLY" not in body


def test_mqget_in_a_loop_that_does_not_wait_on_it_is_left_alone(tmp_path) -> None:
    cbl = MQ_LOOP_CBL.replace("PERFORM UNTIL WS-REASON = 2033", "PERFORM 3 TIMES")
    cut = _scaffold(tmp_path, "MQTIMES", cbl)
    assert "2033" not in cut


def test_looped_cbltdli_get_next_reports_gb_through_the_pcb(tmp_path) -> None:
    """The guard reads an 88 under the PCB; the reply goes to the PCB's
    status bytes whatever the program named that field."""
    body = _mock(_scaffold(tmp_path, "IMSLOOP", IMS_LOOP_CBL), 'MOCK CALL "CBLTDLI"')
    assert 'MOVE "GB" TO DB-PCB(11:2)' in body


def test_cbltdli_sites_needing_different_replies_get_a_todo(tmp_path) -> None:
    """One MOCK CALL "CBLTDLI" answers every CBLTDLI site, so an ISRT next
    to the looped GN cannot share a synthesized GB."""
    cbl = IMS_LOOP_CBL.replace(
        "           DISPLAY WS-COUNT\n",
        "           CALL 'CBLTDLI' USING DLI-ISRT DB-PCB WS-IO-AREA\n"
        "           DISPLAY WS-COUNT\n",
    )
    body = _mock(_scaffold(tmp_path, "IMSMIX", cbl), 'MOCK CALL "CBLTDLI"')
    assert "*> TODO: a loop waits on this CALL's reply" in body
    assert '"GB" TO DB-PCB(11:2)' not in body
    # Both calls succeed on a blank status (issue #317).
    assert "MOVE SPACES TO DB-PCB(11:2)" in body


DLC_PRIMED_CBL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. DLC.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-GN   PIC X(4) VALUE "GN  ".
       01 WS-SEG  PIC X(20).
       01 WS-CNT  PIC 9(4) VALUE 0.
       LINKAGE SECTION.
       01 DB-PCB.
          05 PCB-DBD     PIC X(8).
          05 PCB-LEVEL   PIC XX.
          05 PCB-STATUS  PIC XX.
          05 PCB-REST    PIC X(20).
       PROCEDURE DIVISION.
       MAIN-PARA.
           ENTRY "DLITCBL" USING DB-PCB.
           CALL "CBLTDLI" USING WS-GN DB-PCB WS-SEG
           PERFORM UNTIL PCB-STATUS NOT = SPACES
               ADD 1 TO WS-CNT
               CALL "CBLTDLI" USING WS-GN DB-PCB WS-SEG
           END-PERFORM
           GOBACK.
"""


def test_cbltdli_row_reports_a_blank_status_before_the_end_reply(tmp_path) -> None:
    """Issue #317: the random fixture row put a status such as "PO" into
    PCB-STATUS, so the get loop never ran and VERIFY ... 2 TIMES failed.
    Every row now reports a blank status; the end reply still follows."""
    cut = _generate(tmp_path, "DLC", DLC_PRIMED_CBL, "--seed", "1")
    body = [line.strip() for line in _mock(cut, 'MOCK CALL "CBLTDLI"').splitlines()]
    blank = body.index("MOVE SPACES TO DB-PCB(11:2)")
    assert body[blank + 1 : blank + 3] == [
        "IF UT-CBLTDLI-TALLY > 1",
        'MOVE "GB" TO DB-PCB(11:2)',
    ]
    assert 'VERIFY CALL "CBLTDLI" WAS CALLED 2 TIMES' in cut
