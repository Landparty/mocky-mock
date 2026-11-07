"""Issue #205: a generated MQ mock answers MQCC_OK / MQRC_NONE in its
CompCode and Reason (by the MQI's convention, the last two USING
arguments) instead of random numbers. A random CompCode sent the
`IF WS-COMPCODE NOT = MQCC-OK ... GOBACK` idiom down the failure exit on
the first call, so the generated happy path never ran and its own VERIFYs
failed. A looped MQGET then reports MQRC_NO_MSG_AVAILABLE after its row,
or the drain loop -- which now sees success -- would never end."""

from __future__ import annotations

from pathlib import Path

from tests.unit._generate import _generate

MQBATCH = (
    Path(__file__).resolve().parents[1] / "fixtures" / "enterprise" / "MQBATCH.cbl"
).read_text()


def _mock(cut: str, key: str) -> list[str]:
    start = cut.index(f'MOCK MQ "{key}"')
    return [
        line.strip() for line in cut[start : cut.index("END-MOCK", start)].splitlines()
    ]


def test_every_mq_call_answers_mqcc_ok_and_mqrc_none(tmp_path) -> None:
    cut = _generate(tmp_path, "MQBATCH", MQBATCH, "--seed", "1")
    for key in ("MQCONN", "MQOPEN", "MQCLOSE", "MQDISC", "MQPUT1"):
        body = _mock(cut, key)
        assert "MOVE 0 TO WS-COMPCODE" in body, key
        assert "MOVE 0 TO WS-REASON" in body, key
        assert [line for line in body if line.endswith("TO WS-COMPCODE")] == [
            "MOVE 0 TO WS-COMPCODE"
        ], key


def test_the_looped_mqget_ends_its_drain_loop(tmp_path) -> None:
    cut = _generate(tmp_path, "MQBATCH", MQBATCH, "--seed", "1")
    body = _mock(cut, "MQGET")
    assert "MOVE 0 TO WS-COMPCODE" in body
    first = body.index("IF UT-MQGET-TALLY > 1")
    assert body[first + 1 : first + 3] == [
        "MOVE 2 TO WS-COMPCODE",
        "MOVE 2033 TO WS-REASON",
    ]
    # The drain loop runs only past MQCONN's and MQOPEN's `IF ... GOBACK`:
    # the cases taking either branch never reach it (2026-11-03, it was
    # VERIFY ... 2 TIMES in every case, failing in those two), so no count
    # is exact by construction.
    assert 'VERIFY CALL "MQGET" WAS CALLED 2 TIMES' not in cut
    assert (
        '*> VERIFY CALL "MQGET" WAS CALLED <count not exact by construction -- '
        "called after a branch that may end the run"
    ) in cut


def test_the_bundle_less_placeholder_answers_compcode_and_reason_too() -> None:
    """The placeholder `directive_snippet` renders (lint's fix text,
    `generate --fill`, and `generate --real`'s mocks for a real
    subprogram's MQ calls) answers the same two arguments: RETURN-CODE
    alone left `IF WS-COMPCODE = 0` reading whatever the field held."""
    from cobolparser import parse_cobol

    from mockymock.analysis.mock_surface import analyze
    from mockymock.dsl.generator import directive_snippet

    program = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. MQPUB.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-HCONN    PIC S9(9) BINARY.
       01 WS-HOBJ     PIC S9(9) BINARY.
       01 WS-OD       PIC X(100).
       01 WS-OPTIONS  PIC S9(9) BINARY.
       01 WS-COMPCODE PIC S9(9) BINARY.
       01 WS-REASON   PIC S9(9) BINARY.
       PROCEDURE DIVISION.
       MAIN-PARA.
           CALL "MQOPEN" USING WS-HCONN WS-OD WS-OPTIONS WS-HOBJ
                               WS-COMPCODE WS-REASON
           GOBACK.
"""
    result = parse_cobol(program)
    surface = analyze(result.ast)
    (site,) = [s for s in surface.boundary_sites if s.keys and s.keys[0] == "MQOPEN"]

    snippet = directive_snippet(site, surface)

    assert snippet is not None
    body = [line.strip() for line in snippet.splitlines()]
    assert body[0] == 'MOCK MQ "MQOPEN"'
    assert "MOVE 0 TO WS-COMPCODE" in body
    assert "MOVE 0 TO WS-REASON" in body


# Regression: stress test of the integrated testing stack (backend test packs +
# oracle over a synthetic corpus of every program type), 2026-11-02. Pinned MQ
# codes.


# --- pinned MQ reply --------------------------------------------------------

MQ_PROG = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. MQPROC.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-HCONN             PIC S9(9) BINARY VALUE 0.
       01  WS-HOBJ              PIC S9(9) BINARY.
       01  WS-COMPCODE          PIC S9(9) BINARY.
       01  WS-REASON            PIC S9(9) BINARY.
       01  WS-BUFLEN            PIC S9(9) BINARY VALUE 20.
       01  WS-DATALEN           PIC S9(9) BINARY.
       01  WS-MD                PIC X(324).
       01  WS-GMO               PIC X(112).
       01  WS-MSG               PIC X(20).
       PROCEDURE DIVISION.
       0000-MAIN.
           CALL 'MQGET' USING WS-HCONN WS-HOBJ WS-MD WS-GMO
                              WS-BUFLEN WS-MSG WS-DATALEN
                              WS-COMPCODE WS-REASON
           IF WS-COMPCODE NOT = 0
               DISPLAY 'NO MESSAGE ' WS-REASON
           ELSE
               DISPLAY 'GOT ' WS-MSG
           END-IF
           GOBACK.
"""


def test_mq_failure_case_keeps_its_completion_code(tmp_path):
    """MQPROC: the scenario for `IF WS-COMPCODE NOT = 0` pinned a non-zero
    CompCode, and the success default (`MOVE 0`, #205) overwrote it: the
    no-message branch was never run."""
    cut = _generate(tmp_path, "MQPROC", MQ_PROG, "--seed", "1", "--scenarios", "all")
    bodies = []
    start = 0
    while (start := cut.find('MOCK MQ "MQGET"', start)) != -1:
        bodies.append(cut[start : cut.index("END-MOCK", start)])
        start += 1
    assert any("MOVE 0 TO WS-COMPCODE" in body for body in bodies)
    assert any(
        "TO WS-COMPCODE" in body and "MOVE 0 TO WS-COMPCODE" not in body
        for body in bodies
    )
