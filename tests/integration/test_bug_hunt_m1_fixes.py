"""Executed regressions for the 2026-10-05 bug hunt (mocky-mock issues
#139-#150): each one compiles and runs a small program with real
GnuCOBOL, the way the issue was found. Unit-level counterparts live in
tests/unit/test_bug_hunt_m1_fixes.py."""

from __future__ import annotations

from pathlib import Path

from mockymock.cli.main import main
from tests.integration._docker import requires_docker


def _run(tmp_path: Path, name: str, cbl: str, cut: str, *extra: str) -> int:
    (tmp_path / f"{name}.cbl").write_text(cbl)
    (tmp_path / f"{name}.cut").write_text(cut)
    return main(["run", str(tmp_path / f"{name}.cbl"), *extra])


NOADV_CBL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. NOADV.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A PIC 9 VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 1 TO WS-A
           DISPLAY "PROGRESS..." WITH NO ADVANCING.
           GOBACK.
"""

NOADV_CUT = """\
TESTSUITE "noadv"
TESTCASE "one"
PERFORM MAIN-PARA
EXPECT WS-A TO BE 2
TESTCASE "two"
PERFORM MAIN-PARA
EXPECT WS-A TO BE 1
"""


@requires_docker
def test_139_no_advancing_does_not_turn_a_failure_into_a_pass(
    tmp_path: Path, capsys
) -> None:
    exit_code = _run(tmp_path, "NOADV", NOADV_CBL, NOADV_CUT)
    out = capsys.readouterr().out
    assert exit_code == 1, out
    assert "[FAIL] one" in out
    assert "[PASS] two" in out
    assert "CRASH" not in out
