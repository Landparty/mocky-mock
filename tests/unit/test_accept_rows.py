"""Issue #263: a SYSIN control-card loop (`PERFORM ... UNTIL WS-IN =
"END"` around `ACCEPT WS-IN`). MOCK ACCEPT takes ROWS with a mandatory
TERMINAL group, and generate's happy path moves the loop's sentinel into
the target after the first call so the scaffold ends."""

from __future__ import annotations

import pytest

from mockymock.dsl.model import MockCategory
from mockymock.dsl.parser import CutParseError, parse_cut
from tests.unit.test_bug_hunt_m1_fixes import _generate

ACC_CBL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ACC.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-IN                PIC X(3) VALUE SPACES.
       01  WS-N                 PIC 9(3) VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM GET-ONE UNTIL WS-IN = "END".
           DISPLAY WS-N
           GOBACK.
       GET-ONE.
           ACCEPT WS-IN
           ADD 1 TO WS-N.
"""


def _cut(body: str) -> str:
    return 'TESTSUITE "ACC"\nTESTCASE "cards"\n' + body + "    PERFORM MAIN-PARA\n"


def test_accept_takes_rows_with_a_terminal_group() -> None:
    suite = parse_cut(
        _cut(
            "    MOCK ACCEPT WS-IN ROWS\n"
            '        ( WS-IN = "AAA" )\n'
            '        TERMINAL ( WS-IN = "END" )\n'
            "    END-MOCK\n"
        )
    )
    mock = suite.test_cases[0].mocks[0]
    assert mock.category is MockCategory.ACCEPT
    assert mock.rows == [[("WS-IN", '"AAA"')]]
    assert mock.terminal_row == [("WS-IN", '"END"')]


def test_accept_rows_without_terminal_is_refused() -> None:
    with pytest.raises(CutParseError, match="TERMINAL"):
        parse_cut(
            _cut(
                "    MOCK ACCEPT WS-IN ROWS\n"
                '        ( WS-IN = "AAA" )\n'
                "    END-MOCK\n"
            )
        )


def test_generate_ends_a_loop_waiting_on_the_accepted_sentinel(tmp_path) -> None:
    cut = _generate(tmp_path, "ACC", ACC_CBL, "--seed", "3")
    begin = cut.index("MOCK ACCEPT WS-IN")
    body = [
        line.strip()
        for line in cut[begin : cut.index("END-MOCK", begin)].splitlines()[1:]
        if line.strip()
    ]
    assert body[-3:] == [
        "IF UT-ACCEPT-WS-IN-TALLY > 1",
        "MOVE 'END' TO WS-IN",
        "END-IF",
    ]
    assert "VERIFY ACCEPT WS-IN WAS CALLED 2 TIMES" in cut


def test_placeholder_accept_answers_the_sentinel(tmp_path) -> None:
    cut = _generate(
        tmp_path, "ACC", ACC_CBL, "--seed", "3", "--placeholder", "ACCEPT:WS-IN"
    )
    begin = cut.index("MOCK ACCEPT WS-IN")
    assert "MOVE 'END' TO WS-IN" in cut[begin : cut.index("END-MOCK", begin)]
    assert "VERIFY ACCEPT WS-IN WAS CALLED 1 TIMES" in cut
