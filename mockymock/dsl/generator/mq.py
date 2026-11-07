"""MQ (MQGET/MQPUT...) CALL success replies."""

from __future__ import annotations

from mockymock.analysis.mock_surface import BoundarySite


def _mq_success_reply(
    body: list[str], site: BoundarySite, pinned: frozenset[str] = frozenset()
) -> list[str]:
    """`body` with an MQI call's CompCode and Reason -- by the MQI's fixed
    convention its last two USING arguments -- answered MQCC_OK (0) and
    MQRC_NONE (0) instead of the random numbers the fixture row generated
    (issue #205). A real CompCode is only ever 0, 1 or 2, and the standard
    `IF WS-COMPCODE NOT = MQCC-OK ... GOBACK` idiom compares it against a
    data item the constraint solver cannot see, so a random one sent every
    generated happy path down the MQCONN-failed exit and failed its own
    VERIFYs. The end-of-data reply MQGET's loop needs is added after this,
    by `_call_loop_end_lines`, and still wins on the call that ends the
    loop."""
    if not site.is_mq:
        return body
    using = list(getattr(site.statement, "using_parameters", None) or [])
    names = [str(getattr(param, "name", "") or "") for param in using]
    if len(names) < 2 or not names[-1] or not names[-2]:
        return body
    # A CompCode/Reason the scenario pinned is the point of the case (the
    # `IF WS-COMPCODE NOT = 0` arm after an MQGET): its value stays.
    keep = [name for name in names[-2:] if name.upper() not in pinned]
    if not keep:
        return body
    targets = {name.upper() for name in keep}
    kept = [
        line
        for line in body
        if not (
            line.upper().startswith("MOVE ")
            and line.upper().rsplit(" TO ", 1)[-1].strip() in targets
        )
    ]
    return kept + [f"MOVE 0 TO {name}" for name in keep]
