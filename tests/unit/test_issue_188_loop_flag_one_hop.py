"""Issue #188 (a variant of #156): the looped MQGET's guard is an 88 flag
set one PERFORM away, in a branch on the call's reply -- DEPTMQC's
`PERFORM 2000-CONSUME-MESSAGES UNTIL NO-MORE-MSGS`, with `SET NO-MORE-MSGS
TO TRUE` under `WHEN MQ-REASON-CODE = MQRC-NO-MSG-AVAIL` in the paragraph
holding the CALL. The mock must still report end of data."""

from __future__ import annotations

from tests.unit.test_issue_156_loop_end_reply import _mock, _scaffold

FLAG_LOOP_CBL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. MQFLAG.
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
       01  MQRC-NO-MSG-AVAIL PIC S9(9) BINARY VALUE 2033.
       01  WS-FLAGS.
           05  WS-NO-MORE  PIC X VALUE 'N'.
               88  NO-MORE-MSGS VALUE 'Y'.
       01  WS-COUNT        PIC 9(4) VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM 2000-CONSUME UNTIL NO-MORE-MSGS
           DISPLAY WS-COUNT
           STOP RUN.
       2000-CONSUME.
           PERFORM 2100-GET
           IF NOT NO-MORE-MSGS
               ADD 1 TO WS-COUNT
           END-IF.
       2100-GET.
           CALL 'MQGET' USING WS-HCONN WS-HOBJ WS-MD WS-GMO
                WS-BUFLEN WS-BUFFER WS-DATALEN WS-COMPCODE
                WS-REASON
           EVALUATE TRUE
               WHEN WS-COMPCODE = 0
                   CONTINUE
               WHEN WS-REASON = MQRC-NO-MSG-AVAIL
                   SET NO-MORE-MSGS TO TRUE
               WHEN OTHER
                   SET NO-MORE-MSGS TO TRUE
           END-EVALUATE.
"""


def test_flag_set_on_the_reply_one_perform_away_ends_the_loop(tmp_path) -> None:
    body = _mock(_scaffold(tmp_path, "MQFLAG", FLAG_LOOP_CBL), 'MOCK MQ "MQGET"')
    assert "MOVE 2 TO WS-COMPCODE" in body
    assert "MOVE 2033 TO WS-REASON" in body


def test_guard_on_the_flag_field_itself_also_matches(tmp_path) -> None:
    """`UNTIL WS-NO-MORE = 'Y'` reads the 88's own field."""
    cbl = FLAG_LOOP_CBL.replace("UNTIL NO-MORE-MSGS\n", "UNTIL WS-NO-MORE = 'Y'\n")
    body = _mock(_scaffold(tmp_path, "MQFIELD", cbl), 'MOCK MQ "MQGET"')
    assert "MOVE 2033 TO WS-REASON" in body


def test_flag_set_unconditionally_is_not_a_reply_flag(tmp_path) -> None:
    """A flag the paragraph sets whatever the reply says does not follow
    the reply: nothing is synthesized (the hop needs a branch on it)."""
    cbl = FLAG_LOOP_CBL.replace(
        "           EVALUATE TRUE\n"
        "               WHEN WS-COMPCODE = 0\n"
        "                   CONTINUE\n"
        "               WHEN WS-REASON = MQRC-NO-MSG-AVAIL\n"
        "                   SET NO-MORE-MSGS TO TRUE\n"
        "               WHEN OTHER\n"
        "                   SET NO-MORE-MSGS TO TRUE\n"
        "           END-EVALUATE.\n",
        "           SET NO-MORE-MSGS TO TRUE.\n",
    )
    assert "2033" not in _scaffold(tmp_path, "MQUNCOND", cbl)


def test_flag_set_under_an_if_on_the_reply_ends_the_loop(tmp_path) -> None:
    cbl = FLAG_LOOP_CBL.replace(
        "           EVALUATE TRUE\n"
        "               WHEN WS-COMPCODE = 0\n"
        "                   CONTINUE\n"
        "               WHEN WS-REASON = MQRC-NO-MSG-AVAIL\n"
        "                   SET NO-MORE-MSGS TO TRUE\n"
        "               WHEN OTHER\n"
        "                   SET NO-MORE-MSGS TO TRUE\n"
        "           END-EVALUATE.\n",
        "           IF WS-COMPCODE NOT = 0\n"
        "               MOVE 'Y' TO WS-NO-MORE\n"
        "           END-IF.\n",
    )
    body = _mock(_scaffold(tmp_path, "MQIF", cbl), 'MOCK MQ "MQGET"')
    assert "MOVE 2033 TO WS-REASON" in body
