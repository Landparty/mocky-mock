"""End-to-end proof that a test case whose PERFORM target reaches
STOP RUN (through a chain of plain PERFORM calls) no longer crashes the
suite, and that a later test case in the same suite still runs -- see
docs/2026-07-08-goback-stop-run-support-design.md, Finding 3 of
docs/2026-07-06-real-world-readiness-audit.md."""

from pathlib import Path

from mockymock.cli.main import main
from tests.integration._docker import requires_docker

CBL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TERMDEMO.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-RESULT           PIC 9(4) VALUE 0.

       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           PERFORM 1000-DO-WORK
           STOP RUN.

       1000-DO-WORK.
           CALL "CALCPGM" USING WS-RESULT.
"""

CUT = """\
TESTSUITE "TERMDEMO smoke"

TESTCASE "main process computes result"
    MOCK CALL "CALCPGM"
        MOVE 42 TO WS-RESULT
    END-MOCK
    PERFORM 0000-MAIN-PROCESS
    EXPECT WS-RESULT TO BE 42
    VERIFY "CALCPGM" WAS CALLED ONCE

TESTCASE "second case still runs after the first hits STOP RUN"
    MOCK CALL "CALCPGM"
        MOVE 7 TO WS-RESULT
    END-MOCK
    PERFORM 0000-MAIN-PROCESS
    EXPECT WS-RESULT TO BE 7
"""


@requires_docker
def test_case_reaching_stop_run_passes_and_later_case_still_runs(
    tmp_path: Path, capsys
):
    cbl_path = tmp_path / "TERMDEMO.cbl"
    cbl_path.write_text(CBL)
    cut_path = tmp_path / "TERMDEMO.cut"
    cut_path.write_text(CUT)

    exit_code = main(["run", str(cbl_path), "--cut", str(cut_path)])
    out = capsys.readouterr().out

    assert exit_code == 0, out
    assert "[PASS] main process computes result" in out
    assert "[PASS] second case still runs after the first hits STOP RUN" in out
    assert "CRASH" not in out
    assert "FAIL" not in out


@requires_docker
def test_expectation_mismatch_after_terminator_still_fails_loudly(
    tmp_path: Path, capsys
):
    """Regression guard: neutralizing the terminator must not accidentally
    make a genuinely wrong EXPECT pass."""
    cbl_path = tmp_path / "TERMDEMO.cbl"
    cbl_path.write_text(CBL)
    broken_cut = CUT.replace("EXPECT WS-RESULT TO BE 42", "EXPECT WS-RESULT TO BE 99")
    cut_path = tmp_path / "TERMDEMO.cut"
    cut_path.write_text(broken_cut)

    exit_code = main(["run", str(cbl_path), "--cut", str(cut_path)])
    out = capsys.readouterr().out

    assert exit_code == 1
    assert "[FAIL] main process computes result" in out
    assert "expected WS-RESULT = 99" in out


@requires_docker
def test_go_to_reachable_terminator_refuses_before_compiling(tmp_path: Path, capsys):
    """The one deferred-scope shape this integration tier should verify
    end-to-end: a GO TO-reachable terminator refuses cleanly instead of
    reaching the (unsafe) splicer."""
    cbl_path = tmp_path / "GOTOTERM.cbl"
    cbl_path.write_text(
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. GOTOTERM.\n"
        "\n"
        "       PROCEDURE DIVISION.\n"
        "       0000-MAIN-PROCESS.\n"
        "           GO TO 1000-EXIT.\n"
        "\n"
        "       1000-EXIT.\n"
        "           STOP RUN.\n"
    )
    cut_path = tmp_path / "GOTOTERM.cut"
    cut_path.write_text(
        'TESTSUITE "gototerm"\n'
        "\n"
        'TESTCASE "reaches terminator via GO TO"\n'
        "    PERFORM 0000-MAIN-PROCESS\n"
    )

    exit_code = main(["run", str(cbl_path), "--cut", str(cut_path)])
    out = capsys.readouterr().out

    assert exit_code == 1
    assert "UNSUPPORTED_TERMINATOR_LAYOUT" in out


@requires_docker
def test_terminator_inside_a_loop_body_refuses_before_compiling(tmp_path: Path, capsys):
    """Permanent regression fixture for the looping-PERFORM safety gap
    fixed 2026-07-09 (see .okf/log.md): a STOP RUN reachable only through
    the target of a PERFORM ... UNTIL must refuse, not be silently
    neutralized. Before the fix, a synthetic spike with this exact shape
    was accepted as safe and the compiled/spliced binary ran 3 extra
    unwanted loop iterations past the point the real STOP RUN would have
    stopped it (iterations 3-5, when the real program would have stopped
    at iteration 2) -- a silent correctness bug, not a crash, so this test
    checks for the refusal itself rather than trying to observe the
    absence of extra output."""
    cbl_path = tmp_path / "LOOPTERM.cbl"
    cbl_path.write_text(
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. LOOPTERM.\n"
        "\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01  WS-COUNT            PIC 9(2) VALUE 0.\n"
        '       01  WS-DONE             PIC X VALUE "N".\n'
        "\n"
        "       PROCEDURE DIVISION.\n"
        "       0000-MAIN-PROCESS.\n"
        '           PERFORM 1000-LOOP-BODY UNTIL WS-DONE = "Y".\n'
        "\n"
        "       1000-LOOP-BODY.\n"
        "           ADD 1 TO WS-COUNT\n"
        "           IF WS-COUNT = 2\n"
        "               STOP RUN\n"
        "           END-IF\n"
        "           IF WS-COUNT >= 5\n"
        '               MOVE "Y" TO WS-DONE\n'
        "           END-IF.\n"
    )
    cut_path = tmp_path / "LOOPTERM.cut"
    cut_path.write_text(
        'TESTSUITE "loopterm"\n'
        "\n"
        'TESTCASE "reaches terminator only via a looping PERFORM"\n'
        "    PERFORM 0000-MAIN-PROCESS\n"
    )

    exit_code = main(["run", str(cbl_path), "--cut", str(cut_path)])
    out = capsys.readouterr().out

    assert exit_code == 1
    assert "UNSUPPORTED_TERMINATOR_LAYOUT" in out
