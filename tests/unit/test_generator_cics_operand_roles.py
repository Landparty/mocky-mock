"""Issue #222: a generated CICS mock writes only the operands the command
returns (INTO, SET, RESP, RESP2, a READ's LENGTH/RIDFLD, ...), never the
ones it reads (FROM, a WRITE's RIDFLD). cobol-parser lays out every
resolved operand of a BIDIRECTIONAL EXEC CICS boundary, so the scaffold
used to overwrite the record the program had just built for `WRITE ...
FROM(rec)` and the message for `SEND TEXT FROM(msg)` with random text."""

from __future__ import annotations

from tests.unit._generate import _generate

CICS_CBL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CW.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-RESP   PIC S9(8) COMP VALUE 0.
       01  WS-KEY    PIC X(6).
       01  WS-REC.
           05  REC-ID    PIC X(6).
           05  REC-NAME  PIC X(14).
       01  WS-IN     PIC X(20).
       01  WS-RKEY   PIC X(6).
       01  WS-MSG    PIC X(40) VALUE SPACES.
       PROCEDURE DIVISION.
       0000-MAIN.
           MOVE "000042" TO WS-KEY REC-ID
           MOVE "NEW CUSTOMER" TO REC-NAME
           EXEC CICS WRITE FILE('CUSTF') FROM(WS-REC)
                RIDFLD(WS-KEY) RESP(WS-RESP) END-EXEC
           EXEC CICS READ FILE('CUSTF') INTO(WS-IN)
                RIDFLD(WS-RKEY) END-EXEC
           IF WS-RESP = DFHRESP(NORMAL)
               STRING "ADDED " REC-ID " " REC-NAME
                   DELIMITED BY SIZE INTO WS-MSG
           END-IF
           EXEC CICS SEND TEXT FROM(WS-MSG) LENGTH(40) ERASE END-EXEC
           EXEC CICS RETURN END-EXEC.
"""


def _mock(cut: str, key: str) -> str:
    start = cut.index(f'MOCK CICS "{key}"')
    return cut[start : cut.index("END-MOCK", start)]


def test_write_mock_sets_resp_but_not_its_from_record_or_ridfld(tmp_path) -> None:
    cut = _generate(tmp_path, "CW", CICS_CBL, "--seed", "1")
    write = _mock(cut, "WRITE")
    assert "TO WS-RESP" in write
    assert "REC-ID" not in write
    assert "REC-NAME" not in write
    assert "WS-KEY" not in write


def test_send_mock_leaves_the_message_alone(tmp_path) -> None:
    cut = _generate(tmp_path, "CW", CICS_CBL, "--seed", "1")
    assert "WS-MSG" not in _mock(cut, "SEND")


def test_read_mock_still_writes_into_and_its_ridfld(tmp_path) -> None:
    cut = _generate(tmp_path, "CW", CICS_CBL, "--seed", "1")
    read = _mock(cut, "READ")
    assert "TO WS-IN" in read
    assert "TO WS-RKEY" in read
