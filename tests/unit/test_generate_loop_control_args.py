"""Issue #286: a CALL that passes its enclosing loop's own control item
(VARYING counter or UNTIL word) must not have that item written by the
generated mock body, or every call resets the loop and the scaffold's
happy path runs until --timeout."""

from __future__ import annotations

import pytest

from tests.unit.test_bug_hunt_m1_fixes import _generate

INLINE_CBL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. EC2.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-IX               PIC 9(2) VALUE 0.
       01  WS-COUNT            PIC 9(2) VALUE 5.
       01  WS-LINE             PIC X(20) VALUE SPACES.
       PROCEDURE DIVISION.
       0000-MAIN.
           PERFORM 1000-PRINT
           GOBACK.
       1000-PRINT.
           PERFORM VARYING WS-IX FROM 1 BY 1 UNTIL WS-IX > WS-COUNT
               CALL "FMTLINE" USING WS-IX WS-LINE
               DISPLAY WS-LINE
           END-PERFORM.
"""

OUT_OF_LINE_CBL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. EC3.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-I                PIC 9(2) VALUE 0.
       PROCEDURE DIVISION.
       0000-MAIN.
           PERFORM 2000-B VARYING WS-I FROM 1 BY 1 UNTIL WS-I > 4
           GOBACK.
       2000-B.
           CALL "BBB" USING WS-I.
"""


def _call_body(cut: str, header: str) -> list[str]:
    begin = cut.index(header)
    return [
        line.strip() for line in cut[begin : cut.index("END-MOCK", begin)].splitlines()
    ]


@pytest.mark.parametrize(
    ("name", "source", "header", "counter", "kept"),
    [
        ("EC2", INLINE_CBL, 'MOCK CALL "FMTLINE"', "WS-IX", " TO WS-LINE"),
        ("EC3", OUT_OF_LINE_CBL, 'MOCK CALL "BBB"', "WS-I", None),
    ],
)
def test_call_mock_leaves_the_loop_counter_alone(
    tmp_path, name, source, header, counter, kept
) -> None:
    for seed in ("1", "7"):
        body = _call_body(
            _generate(tmp_path, name, source, "--seed", seed, "--force"), header
        )
        assert not [line for line in body if line.endswith(f" TO {counter}")]
        assert any(line.startswith("*> TODO") and counter in line for line in body)
        if kept:
            assert any(line.endswith(kept) for line in body)
