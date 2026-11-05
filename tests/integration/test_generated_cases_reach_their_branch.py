"""A generated branch case must run the arm it is named for.

`generate --scenarios branches` names each case for the branch arm its data
targets (`"READ-ONE: IF@39 THEN"`). Nothing in the `.cut` asserts the arm
runs, so a case whose data misses it still passes. These tests run every
such case under `--trace` and check the arm's first statement executed.
Bug hunt of 2026-11-05; each program below shows a defect of cobol-parser's
scenario planner, fixed there:

* GUARDED: a branch below `IF RC NOT = "V" ... GO TO exit` left RC to
  chance, so the case took the exit (real-world ACHPROC: six cases).
* NUMCLS: `IF IN-NAME IS NUMERIC` on a PIC X(10) got "00000000", which is
  space-padded to "00000000  " and is not numeric.
* ODOCNT: an OCCURS 1 TO 5 DEPENDING ON counter (PIC 99) got 51 or 99; the
  loop over the table then never ended and the binary timed out.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from mockymock.cli.main import main
from tests.integration._docker import requires_docker

GUARDED = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. GUARDED.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT INV-FILE ASSIGN TO "INVF"
               FILE STATUS IS WS-FS.
       DATA DIVISION.
       FILE SECTION.
       FD  INV-FILE.
       01  INV-REC.
           05  INV-RC         PIC X.
           05  INV-QTY        PIC 9(4).
           05  INV-TYPE       PIC X(2).
       WORKING-STORAGE SECTION.
       01  WS-FS              PIC XX.
       01  WS-EOF             PIC X VALUE "N".
       01  WS-TOTAL           PIC 9(6) VALUE 0.
       01  WS-ERRORS          PIC 9(4) VALUE 0.
       01  WS-BIG             PIC 9(4) VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PROCESS.
           OPEN INPUT INV-FILE
           PERFORM READ-ONE THRU READ-ONE-EXIT UNTIL WS-EOF = "Y"
           CLOSE INV-FILE
           STOP RUN.
       READ-ONE.
           READ INV-FILE
               AT END MOVE "Y" TO WS-EOF
                      GO TO READ-ONE-EXIT
           END-READ
           IF INV-RC NOT = "V"
               ADD 1 TO WS-ERRORS
               GO TO READ-ONE-EXIT
           END-IF
           EVALUATE INV-TYPE
               WHEN "AA"
                   ADD 1 TO WS-TOTAL
               WHEN OTHER
                   ADD 1 TO WS-ERRORS
                   GO TO READ-ONE-EXIT
           END-EVALUATE
           IF INV-QTY > 500
               ADD 1 TO WS-BIG
           ELSE
               ADD INV-QTY TO WS-TOTAL
           END-IF.
       READ-ONE-EXIT.
           EXIT.
"""

NUMCLS = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. NUMCLS.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-FILE ASSIGN TO "INF"
               FILE STATUS IS WS-FS.
       DATA DIVISION.
       FILE SECTION.
       FD  IN-FILE.
       01  IN-REC.
           05 IN-NAME        PIC X(10).
       WORKING-STORAGE SECTION.
       01  WS-FS             PIC XX.
       01  WS-MSG            PIC X(10).
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT IN-FILE
           READ IN-FILE
           IF IN-NAME IS NUMERIC
               MOVE "NUMNAME" TO WS-MSG
           ELSE
               MOVE "TEXTNAME" TO WS-MSG
           END-IF
           CLOSE IN-FILE
           STOP RUN.
"""

ODOCNT = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ODOCNT.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-FILE ASSIGN TO "INF"
               FILE STATUS IS WS-FS.
       DATA DIVISION.
       FILE SECTION.
       FD  IN-FILE.
       01  DTL-REC.
           05 DTL-ID         PIC X(4).
           05 DTL-CNT        PIC 99.
           05 DTL-ITEM OCCURS 1 TO 5 TIMES DEPENDING ON DTL-CNT.
              10 DTL-VAL     PIC 999.
       WORKING-STORAGE SECTION.
       01  WS-FS             PIC XX.
       01  WS-I              PIC 99.
       01  WS-SUM            PIC 9(6) VALUE 0.
       01  WS-MANY           PIC 9 VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT IN-FILE
           READ IN-FILE
           PERFORM VARYING WS-I FROM 1 BY 1 UNTIL WS-I > DTL-CNT
               ADD DTL-VAL(WS-I) TO WS-SUM
           END-PERFORM
           IF DTL-CNT > 3
               MOVE 1 TO WS-MANY
           ELSE
               MOVE 2 TO WS-MANY
           END-IF
           CLOSE IN-FILE
           STOP RUN.
"""

#: `<paragraph>: IF@<line> THEN|ELSE`, a case targeting one IF arm.
_IF_CASE = re.compile(r'^TESTCASE "([^"]*: IF@(\d+) (THEN|ELSE))"$', re.M)


def _arm_first_lines(source: str, if_line: int) -> dict[str, int]:
    """The line of the first statement of the THEN and the ELSE arm of the
    IF on `if_line`: the next line, and the line after its ELSE."""
    lines = source.splitlines()
    else_line = next(
        number
        for number in range(if_line + 1, len(lines) + 1)
        if lines[number - 1].strip() == "ELSE"
    )
    return {"THEN": if_line + 1, "ELSE": else_line + 1}


def _generate(tmp_path: Path, name: str, source: str) -> tuple[Path, Path]:
    program = tmp_path / f"{name}.cbl"
    program.write_text(source)
    cut = tmp_path / f"{name}.cut"
    assert (
        main(
            [
                "generate",
                str(program),
                "--scenarios",
                "branches",
                "--seed",
                "11",
                "-o",
                str(cut),
            ]
        )
        == 0
    )
    return program, cut


@requires_docker
@pytest.mark.parametrize(
    ("name", "source", "condition"),
    [
        ("GUARDED", GUARDED, "IF INV-QTY > 500"),
        ("NUMCLS", NUMCLS, "IF IN-NAME IS NUMERIC"),
        ("ODOCNT", ODOCNT, "IF DTL-CNT > 3"),
    ],
)
def test_every_if_case_runs_its_arm(tmp_path: Path, capsys, name, source, condition):
    if_lines = {
        number
        for number, text in enumerate(source.splitlines(), start=1)
        if text.strip() == condition
    }
    program, cut = _generate(tmp_path, name, source)
    cases = _IF_CASE.findall(cut.read_text())
    targeted = {int(line) for _, line, _ in cases}
    assert if_lines <= targeted, cut.read_text()

    for case, line, arm in cases:
        if int(line) not in if_lines:
            continue
        trace = tmp_path / "trace.json"
        exit_code = main(
            [
                "run",
                str(program),
                "--cut",
                str(cut),
                "--case",
                case,
                "--trace",
                "--trace-json",
                str(trace),
            ]
        )
        out = capsys.readouterr().out
        assert exit_code == 0, out
        executed = {step["line"] for step in json.loads(trace.read_text())["path"]}
        wanted = _arm_first_lines(source, int(line))[arm]
        assert wanted in executed, f"{case}: line {wanted} never ran\n{out}"


def test_an_odo_counter_stays_inside_its_table(tmp_path: Path):
    """Every value generated for the OCCURS 1 TO 5 DEPENDING ON counter,
    including the boundary-values cases, is 1..5: 99 made the table loop
    (`WS-I PIC 99 ... UNTIL WS-I > DTL-CNT`) run forever."""
    program = tmp_path / "ODOCNT.cbl"
    program.write_text(ODOCNT)
    cut = tmp_path / "ODOCNT.cut"
    argv = ["generate", str(program), "--scenarios", "all", "--seed", "11"]
    assert main([*argv, "-o", str(cut)]) == 0
    values = [int(v) for v in re.findall(r"MOVE (\d+) TO DTL-CNT", cut.read_text())]
    assert values
    assert all(1 <= value <= 5 for value in values), sorted(set(values))
