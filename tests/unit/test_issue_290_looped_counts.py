"""Issue #290: `generate --with-data` must not write `VERIFY ... WAS CALLED 1
TIMES` for a site that runs more than once a pass -- inside a looping PERFORM
(UNTIL / VARYING / TIMES, out-of-line or inline) or in a paragraph PERFORMed
twice. The bundle counts such a site once. A READ in the read loop keeps its
row-derived count."""

from __future__ import annotations

from cobolparser import parse_cobol

from mockymock.analysis.exact_counts import exact_count_scope

PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. RL.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-FILE ASSIGN TO "IN.DAT"
               ORGANIZATION IS LINE SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD  IN-FILE.
       01  IN-REC.
           05 IN-ID PIC X(5).
       WORKING-STORAGE SECTION.
       01  WS-EOF PIC X VALUE "N".
       01  WS-RC  PIC 9(4) VALUE 0.
       01  WS-I   PIC 9(4) VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT IN-FILE
           PERFORM READ-ONE
           PERFORM PROCESS-ONE UNTIL WS-EOF = "Y"
           PERFORM CALL-A 3 TIMES
           PERFORM VARYING WS-I FROM 1 BY 1 UNTIL WS-I > 4
               CALL "VARYCALL" USING WS-RC
           END-PERFORM
           PERFORM 2 TIMES
               CALL "TWICE" USING WS-RC
           END-PERFORM
           PERFORM CALL-B
           PERFORM CALL-B
           PERFORM CALL-C
           CLOSE IN-FILE
           GOBACK.
       READ-ONE.
           READ IN-FILE AT END MOVE "Y" TO WS-EOF END-READ.
       PROCESS-ONE.
           CALL "AUDITLOG" USING IN-ID WS-RC
           PERFORM READ-ONE.
       CALL-A.
           CALL "CALLA" USING WS-RC.
       CALL-B.
           CALL "CALLB" USING WS-RC.
       CALL-C.
           CALL "CALLC" USING WS-RC.
"""

REACHABLE = {"MAIN-PARA", "READ-ONE", "PROCESS-ONE", "CALL-A", "CALL-B", "CALL-C"}


def _generate(tmp_path) -> str:
    from mockymock.cli.main import main

    source = tmp_path / "RL.cbl"
    source.write_text(PROGRAM)
    out = tmp_path / "RL.cut"
    assert (
        main(["generate", str(source), "--with-data", "--seed", "1", "-o", str(out)])
        == 0
    )
    return out.read_text()


def test_looping_and_repeated_performs_leave_the_scope() -> None:
    program = parse_cobol(PROGRAM, filename="rl.cbl").ast
    scope = exact_count_scope(program, "MAIN-PARA", REACHABLE)
    assert scope is not None
    assert scope[0] == {"MAIN-PARA", "CALL-C"}


def test_loops_exact_scope_keeps_the_read_loop() -> None:
    program = parse_cobol(PROGRAM, filename="rl.cbl").ast
    scope = exact_count_scope(program, "MAIN-PARA", REACHABLE, loops_exact=True)
    assert scope is not None
    assert scope[0] == REACHABLE


def test_sites_that_run_more_than_once_are_demoted(tmp_path) -> None:
    cut = _generate(tmp_path)
    for name in ("AUDITLOG", "CALLA", "VARYCALL", "TWICE", "CALLB"):
        assert f'VERIFY CALL "{name}" WAS CALLED 1 TIMES' not in cut, name
        assert (
            f'*> VERIFY CALL "{name}" WAS CALLED <count not exact by construction '
            "-- called inside a PERFORM loop"
        ) in cut, name


def test_once_only_sites_and_the_read_loop_keep_their_counts(tmp_path) -> None:
    cut = _generate(tmp_path)
    assert 'VERIFY CALL "CALLC" WAS CALLED 1 TIMES' in cut
    assert "    VERIFY OPEN IN-FILE WAS CALLED 1 TIMES" in cut
    assert "    VERIFY READ IN-FILE WAS CALLED " in cut
