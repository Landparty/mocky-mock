"""Issue #291: the USING re-scan that tells a quoted literal from a
data-name gave up on any parenthesis, so `CAPTURE ARG` of a literal next to
a subscripted operand emitted `MOVE LIT1 TO ...` (a compile error, or the
wrong item captured when LIT1 exists)."""

from __future__ import annotations

from mockymock.splicer.injector import _call_using_literals


def test_literal_is_recognized_next_to_subscripts_and_refmods() -> None:
    text = (
        'CALL "SUBX" USING BY CONTENT "LIT1" WS-ENT(WS-I)\n'
        "    WS-ENT (WS-I + 1) WS-I(1:1) 'Q'."
    )
    names = [
        "LIT1",
        "WS-ENT ( WS-I )",
        "WS-ENT ( WS-I + 1 )",
        "WS-I ( 1 : 1 )",
        "Q",
    ]
    assert _call_using_literals(text, names) == ['"LIT1"', None, None, None, "'Q'"]


def test_multi_subscript_and_qualified_operand() -> None:
    text = 'CALL "X" USING T OF TAB (I, J) "Q"'
    assert _call_using_literals(text, ["T OF TAB ( I J )", "Q"]) == [None, '"Q"']


def test_unbalanced_parenthesis_still_falls_back() -> None:
    text = 'CALL "X" USING T(I "Q"'
    assert _call_using_literals(text, ["T ( I", "Q"]) == [None, None]
