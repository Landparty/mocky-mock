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
