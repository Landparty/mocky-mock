"""Issue #160: `generate --with-data` must not write a VERIFY call count for
a boundary the case may never reach -- a single site under an IF (LOANPMT's
ROLLBACK), or one in a paragraph PERFORMed only from inside an IF
(DEPTMQP's MQPUT, ACCTINQ's CICS READ)."""

from __future__ import annotations

from mockymock.analysis.exact_counts import exact_count_scope

PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. COND.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-N  PIC 9 VALUE 0.
       01  WS-OK PIC X VALUE "Y".
           88  RECORD-OK VALUE "Y".
       PROCEDURE DIVISION.
       MAIN-PARA.
           CALL "ALWAYS" USING WS-N
           IF WS-N > 5
               CALL "GUARDED" USING WS-N
           END-IF
           IF RECORD-OK
               PERFORM PUT-PARA
           END-IF
           PERFORM DONE-PARA
           GOBACK.
       PUT-PARA.
           CALL "MQPUT" USING WS-N.
       DONE-PARA.
           CALL "FINISH" USING WS-N.
"""


def _generate(tmp_path, cbl: str) -> str:
    from mockymock.cli.main import main

    source = tmp_path / "COND.cbl"
    source.write_text(cbl)
    out = tmp_path / "COND.cut"
    assert (
        main(["generate", str(source), "--with-data", "--seed", "1", "-o", str(out)])
        == 0
    )
    return out.read_text()


def test_a_single_site_under_an_if_is_not_counted(tmp_path) -> None:
    cut = _generate(tmp_path, PROGRAM)
    assert 'VERIFY CALL "GUARDED" WAS CALLED 1 TIMES' not in cut
    assert '*> VERIFY CALL "GUARDED" WAS CALLED <count not exact' in cut


def test_a_top_level_site_in_a_conditionally_performed_paragraph_is_not_counted(
    tmp_path,
) -> None:
    cut = _generate(tmp_path, PROGRAM)
    assert 'VERIFY CALL "MQPUT" WAS CALLED 1 TIMES' not in cut
    assert '*> VERIFY CALL "MQPUT" WAS CALLED <count not exact' in cut


def test_sites_on_the_straight_path_keep_their_counts(tmp_path) -> None:
    cut = _generate(tmp_path, PROGRAM)
    assert 'VERIFY CALL "ALWAYS" WAS CALLED 1 TIMES' in cut
    assert 'VERIFY CALL "FINISH" WAS CALLED 1 TIMES' in cut


def test_a_paragraph_also_performed_in_a_branch_that_stops_the_run_keeps_its_count(
    tmp_path,
) -> None:
    # DEPTMQP's `IF NOT MQ-CONNECTED PERFORM 3000-FINALIZE STOP RUN`: the
    # finalize paragraph runs once on either path.
    cbl = PROGRAM.replace(
        '           CALL "ALWAYS" USING WS-N\n',
        '           CALL "ALWAYS" USING WS-N\n'
        "           IF WS-N > 8\n"
        "               PERFORM DONE-PARA\n"
        "               STOP RUN\n"
        "           END-IF\n",
    )
    cut = _generate(tmp_path, cbl)
    assert 'VERIFY CALL "FINISH" WAS CALLED 1 TIMES' in cut


def test_a_paragraph_also_performed_conditionally_loses_its_count(tmp_path) -> None:
    cbl = PROGRAM.replace(
        "               PERFORM PUT-PARA\n",
        "               PERFORM PUT-PARA\n               PERFORM DONE-PARA\n",
    )
    cut = _generate(tmp_path, cbl)
    assert 'VERIFY CALL "FINISH" WAS CALLED 1 TIMES' not in cut


def test_scope_follows_top_level_performs_only() -> None:
    from cobolparser import parse_cobol

    program = parse_cobol(PROGRAM, filename="cond.cbl").ast
    reachable = {"MAIN-PARA", "PUT-PARA", "DONE-PARA"}
    scope = exact_count_scope(program, "MAIN-PARA", reachable)
    assert scope is not None
    paragraphs, _ = scope
    assert paragraphs == {"MAIN-PARA", "DONE-PARA"}


def test_a_key_also_called_from_a_paragraph_the_entry_never_reaches_is_not_counted(
    tmp_path,
) -> None:
    # The bundle counts every site of the key, ORPHAN-PARA's included, and
    # the counts were summed into "2 TIMES" while the case calls FINISH
    # once (ACCTINQ: its CICS RETURN is also in the HANDLE CONDITION NOTFND
    # paragraph, and the scaffold `init` wrote failed its own first run).
    cbl = PROGRAM + ("       ORPHAN-PARA.\n" '           CALL "FINISH" USING WS-N.\n')
    cut = _generate(tmp_path, cbl)
    assert 'VERIFY CALL "FINISH" WAS CALLED 2 TIMES' not in cut
    assert 'VERIFY CALL "FINISH" WAS CALLED 1 TIMES' not in cut
    assert (
        '*> VERIFY CALL "FINISH" WAS CALLED <count not exact by construction '
        "-- also called from a paragraph this case's PERFORM never reaches"
    ) in cut
    assert 'VERIFY CALL "ALWAYS" WAS CALLED 1 TIMES' in cut


def test_a_cics_handle_condition_target_does_not_inflate_the_count(tmp_path) -> None:
    cbl = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. INQ.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-AREA PIC X(10).
       PROCEDURE DIVISION.
       MAIN-PARA.
           EXEC CICS HANDLE CONDITION
               NOTFND(NOTFND-PARA)
           END-EXEC
           MOVE "X" TO WS-AREA
           EXEC CICS RETURN
               COMMAREA(WS-AREA)
           END-EXEC.
       NOTFND-PARA.
           MOVE SPACES TO WS-AREA
           EXEC CICS RETURN
               COMMAREA(WS-AREA)
           END-EXEC.
"""
    from mockymock.cli.main import main

    source = tmp_path / "INQ.cbl"
    source.write_text(cbl)
    out = tmp_path / "INQ.cut"
    assert (
        main(["generate", str(source), "--with-data", "--seed", "1", "-o", str(out)])
        == 0
    )
    cut = out.read_text()
    assert "WAS CALLED 2 TIMES" not in cut
    assert '*> VERIFY CICS "RETURN' in cut
