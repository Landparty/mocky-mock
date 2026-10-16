"""Issue #205: a generated MQ mock answers MQCC_OK / MQRC_NONE in its
CompCode and Reason (by the MQI's convention, the last two USING
arguments) instead of random numbers. A random CompCode sent the
`IF WS-COMPCODE NOT = MQCC-OK ... GOBACK` idiom down the failure exit on
the first call, so the generated happy path never ran and its own VERIFYs
failed. A looped MQGET then reports MQRC_NO_MSG_AVAILABLE after its row,
or the drain loop -- which now sees success -- would never end."""

from __future__ import annotations

from pathlib import Path

from tests.unit.test_bug_hunt_m1_fixes import _generate

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
    assert 'VERIFY CALL "MQGET" WAS CALLED 2 TIMES' in cut
