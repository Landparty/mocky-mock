"""Issue #300: a CALL whose USING arguments the program sets itself has no
fixture or call_count expectation in the bundle (nothing to generate);
that is not a "boundary key mismatch"."""

from __future__ import annotations

from tests.unit._generate import _generate

STA1_CBL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. STA1.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-KEY               PIC X(6).
       01  WS-OUT               PIC X(6).
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE "K00001" TO WS-KEY
           CALL "CUSTRD" USING WS-KEY
           MOVE "OUT001" TO WS-OUT
           CALL "CUSTWR" USING WS-OUT
           GOBACK.
"""


def test_program_supplied_calls_are_not_a_key_mismatch(tmp_path, capsys) -> None:
    cut = _generate(tmp_path, "STA1", STA1_CBL, "--seed", "1")
    assert "boundary key mismatch" not in capsys.readouterr().err
    assert 'MOCK CALL "CUSTRD"' in cut
    assert 'MOCK CALL "CUSTWR"' in cut
