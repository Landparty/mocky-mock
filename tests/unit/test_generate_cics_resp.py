"""CICS RESP handling in the data-driven scaffold: issue #253 (RESP/RESP2
answer DFHRESP(NORMAL) on the happy path) and issue #316 (a browse loop
guarded on its own RESP gets an end-of-file reply)."""

from __future__ import annotations

from tests.unit.test_bug_hunt_m1_fixes import _generate

READ_CBL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CRD.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-RESP  PIC 9(8).
       01 WS-RESP2 PIC 9(8).
       01 WS-KEY   PIC X(6) VALUE "000001".
       01 WS-NAME  PIC X(30).
       01 WS-MSG   PIC X(10).
       PROCEDURE DIVISION.
       MAIN-PARA.
           EXEC CICS READ FILE('CUST') INTO(WS-NAME)
                RIDFLD(WS-KEY) RESP(WS-RESP) RESP2(WS-RESP2)
           END-EXEC
           EVALUATE WS-RESP
             WHEN DFHRESP(NORMAL)
               MOVE "FOUND" TO WS-MSG
             WHEN OTHER
               MOVE "ERR" TO WS-MSG
           END-EVALUATE
           DISPLAY WS-MSG
           EXEC CICS RETURN END-EXEC.
"""


def _mock(cut: str, header: str, start: int = 0) -> list[str]:
    begin = cut.index(header, start)
    return [
        line.strip() for line in cut[begin : cut.index("END-MOCK", begin)].splitlines()
    ]


def test_happy_path_answers_resp_and_resp2_normal(tmp_path) -> None:
    for seed in ("1", "2", "3"):
        body = _mock(
            _generate(tmp_path, "CRD", READ_CBL, "--seed", seed, "--force"),
            'MOCK CICS "READ"',
        )
        assert "MOVE 0 TO WS-RESP" in body
        assert "MOVE 0 TO WS-RESP2" in body
        assert not [
            line
            for line in body
            if line.endswith((" TO WS-RESP", " TO WS-RESP2"))
            and not line.startswith("MOVE 0 ")
        ]


def test_a_branch_scenario_keeps_the_resp_it_pinned(tmp_path) -> None:
    cut = _generate(tmp_path, "CRD", READ_CBL, "--seed", "1", "--scenarios", "branches")
    branch = cut.index("WHEN OTHER")
    body = _mock(cut, 'MOCK CICS "READ"', branch)
    pinned = [line for line in body if line.endswith(" TO WS-RESP")]
    assert pinned and pinned != ["MOVE 0 TO WS-RESP"]


BROWSE_CBL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CBR.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-RESP  PIC S9(8) COMP VALUE 0.
       01 WS-KEY   PIC X(6) VALUE "000001".
       01 WS-REC   PIC X(30).
       01 WS-CNT   PIC 9(4) VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           EXEC CICS STARTBR FILE('CUSTF') RIDFLD(WS-KEY)
                RESP(WS-RESP) END-EXEC
           EXEC CICS READNEXT FILE('CUSTF') INTO(WS-REC)
                RIDFLD(WS-KEY) RESP(WS-RESP) END-EXEC
           PERFORM UNTIL WS-RESP NOT = DFHRESP(NORMAL)
               ADD 1 TO WS-CNT
               EXEC CICS READNEXT FILE('CUSTF') INTO(WS-REC)
                    RIDFLD(WS-KEY) RESP(WS-RESP) END-EXEC
           END-PERFORM
           EXEC CICS ENDBR FILE('CUSTF') END-EXEC
           EXEC CICS RETURN END-EXEC.
"""


def test_browse_loop_gets_endfile_after_its_row(tmp_path) -> None:
    """Issue #316: READNEXT answered NORMAL on every call, so the browse
    loop guarded on its RESP never ended."""
    cut = _generate(tmp_path, "CBR", BROWSE_CBL, "--seed", "1")
    body = _mock(cut, 'MOCK CICS "READNEXT')
    tally = next(line for line in body if line.startswith("IF UT-CICS-READNEXT"))
    assert body[body.index(tally) + 1] == "MOVE 20 TO WS-RESP"
    assert tally.endswith("-TALLY > 1")
    assert "WAS CALLED 2 TIMES" in next(
        line for line in cut.splitlines() if 'VERIFY CICS "READNEXT' in line
    )


def test_per_paragraph_browse_ends_on_the_first_call(tmp_path) -> None:
    from mockymock.cli.main import main

    source = tmp_path / "CBR.cbl"
    source.write_text(BROWSE_CBL)
    out = tmp_path / "CBR.cut"
    assert main(["generate", str(source), "--per-paragraph", "-o", str(out)]) == 0
    body = _mock(out.read_text(), 'MOCK CICS "READNEXT')
    assert "MOVE 20 TO WS-RESP" in body
    assert not any("TALLY" in line for line in body)


def test_readq_ts_loop_reports_itemerr(tmp_path) -> None:
    cbl = BROWSE_CBL.replace(
        "READNEXT FILE('CUSTF') INTO(WS-REC)\n                RIDFLD(WS-KEY)",
        "READQ TS QUEUE('Q1') INTO(WS-REC)\n               ",
    ).replace(
        "READNEXT FILE('CUSTF') INTO(WS-REC)\n                    RIDFLD(WS-KEY)",
        "READQ TS QUEUE('Q1') INTO(WS-REC)\n                   ",
    )
    cut = _generate(tmp_path, "CRQ", cbl, "--seed", "1")
    assert "MOVE 26 TO WS-RESP" in _mock(cut, 'MOCK CICS "READQ')


def test_readnext_outside_any_loop_is_left_alone(tmp_path) -> None:
    cbl = BROWSE_CBL.replace(
        "PERFORM UNTIL WS-RESP NOT = DFHRESP(NORMAL)", "IF WS-RESP = 0"
    ).replace("END-PERFORM", "END-IF")
    cut = _generate(tmp_path, "CRN", cbl, "--seed", "1")
    assert "MOVE 20 TO WS-RESP" not in cut
