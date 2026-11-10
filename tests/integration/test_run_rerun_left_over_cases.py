"""Executed regressions for the 2026-11-05 bug hunt in running suites:
each compiles and runs with real GnuCOBOL. Unit-level counterparts live
in the unit feature files (each block marked `# Regression:`)."""

from __future__ import annotations

import json
from pathlib import Path

from mockymock.cli.main import main
from tests.integration._docker import requires_docker

LOOPER_CBL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. LOOPER.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-FLAG    PIC X VALUE "N".
       01 WS-COUNT   PIC 9(4) VALUE 0.
       PROCEDURE DIVISION.
       0000-MAIN.
           STOP RUN.
       1000-LOOP.
           PERFORM UNTIL WS-FLAG = "Y"
               ADD 1 TO WS-COUNT
               DISPLAY "STILL LOOPING"
           END-PERFORM.
       2000-SET.
           MOVE 5 TO WS-COUNT.
"""

# The first case loops until the timeout; the case left over shares its
# name, so a rerun picked by name ran the looping case again, and the two
# cases after it were never run.
LOOPER_CUT = """\
TESTSUITE "looper"

TESTCASE "same"
    PERFORM 1000-LOOP
    EXPECT WS-COUNT TO BE 1

TESTCASE "same"
    PERFORM 2000-SET
    EXPECT WS-COUNT TO BE 5

TESTCASE "other"
    PERFORM 2000-SET
    EXPECT WS-COUNT TO BE 6
"""


def _statuses(path: Path) -> list[tuple[str, str]]:
    report = json.loads(path.read_text(encoding="utf-8"))
    return [(case["name"], case["status"]) for case in report["cases"]]


@requires_docker
def test_left_over_cases_rerun_by_position_and_reach_the_saved_result(
    tmp_path: Path, capsys
) -> None:
    (tmp_path / "LOOPER.cbl").write_text(LOOPER_CBL)
    (tmp_path / "LOOPER.cut").write_text(LOOPER_CUT)
    report = tmp_path / "report.json"
    exit_code = main(
        [
            "run",
            str(tmp_path / "LOOPER.cbl"),
            "--timeout",
            "2",
            "--json-report",
            str(report),
        ]
    )
    out = capsys.readouterr().out
    assert exit_code == 1, out
    expected = [("same", "crashed"), ("same", "passed"), ("other", "failed")]
    assert _statuses(report) == expected
    # `mockymock report` reuses the saved result: it used to keep the
    # cases the rerun ran as not run.
    assert _statuses(tmp_path / ".mockymock" / "LOOPER.run.json") == expected
