"""End-to-end proof for the GO-TO-to-EXIT-PARAGRAPH simplification (see
docs/2026-08-17-goto-exit-paragraph-simplification-design.md).

STATUS: this fixture was written but NOT executed in the session that
authored it -- no Docker daemon was reachable there. It follows
test_terminator_support.py's precedent exactly (a real `mockymock run`
against real GnuCOBOL, not a mocked subprocess) and is meant to be the
permanent regression fixture once someone with Docker runs it and
confirms it passes. Until that happens, do not cite this file as proof
the feature works at runtime -- see the design doc's Status note.

GOTOEXIT.cbl implements the textbook early-exit idiom:

    0000-MAIN-PROCESS.
        PERFORM 1000-DO-WORK
        IF WS-COND = "Y"
            GO TO 0000-MAIN-EXIT
        END-IF
        MOVE 99 TO WS-RESULT.
    0000-MAIN-EXIT.
        EXIT.
    1000-DO-WORK.
        CALL "CALCPGM" USING WS-RESULT.

Both branches are driven by a plain `PERFORM 0000-MAIN-PROCESS` (no
THRU) in every test case below -- the THRU-elision claim this feature
makes (see the design doc's "THRU elision" section): the mocked CALL
runs first (inside 1000-DO-WORK) and sets WS-COND, so one mock body
selects which branch the rest of the paragraph takes.
"""

from pathlib import Path

from mockymock.cli.main import main
from tests.integration._docker import requires_docker

CBL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. GOTOEXIT.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-COND             PIC X VALUE "N".
       01  WS-RESULT           PIC 9(4) VALUE 0.

       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           PERFORM 1000-DO-WORK
           IF WS-COND = "Y"
               GO TO 0000-MAIN-EXIT
           END-IF
           MOVE 99 TO WS-RESULT.

       0000-MAIN-EXIT.
           EXIT.

       1000-DO-WORK.
           CALL "CALCPGM" USING WS-RESULT.
"""

CUT = """\
TESTSUITE "GOTOEXIT early-exit idiom, no PERFORM THRU declared"

TESTCASE "normal path -- early exit not taken, falls through to MOVE 99"
    MOCK CALL "CALCPGM"
        MOVE "N" TO WS-COND
        MOVE 42 TO WS-RESULT
    END-MOCK
    PERFORM 0000-MAIN-PROCESS
    EXPECT WS-RESULT TO BE 99

TESTCASE "early-exit path -- GO TO fires, MOVE 99 must NOT run"
    MOCK CALL "CALCPGM"
        MOVE "Y" TO WS-COND
        MOVE 42 TO WS-RESULT
    END-MOCK
    PERFORM 0000-MAIN-PROCESS
    EXPECT WS-RESULT TO BE 42

TESTCASE "third case still runs after the early-exit case"
    MOCK CALL "CALCPGM"
        MOVE "N" TO WS-COND
        MOVE 7 TO WS-RESULT
    END-MOCK
    PERFORM 0000-MAIN-PROCESS
    EXPECT WS-RESULT TO BE 99
"""


@requires_docker
def test_early_exit_branch_returns_correctly_with_no_perform_thru(
    tmp_path: Path, capsys
):
    """The critical claim: with the GO TO spliced into EXIT PARAGRAPH,
    the early-exit branch returns to the test driver correctly -- no
    crash, no silent stop, no hang -- using a plain PERFORM with no THRU
    declared. Before this feature, this exact shape would either refuse
    UNSUPPORTED_TERMINATOR_LAYOUT (if a terminator were downstream) or,
    for this terminator-free variant, risk the latent "adjacent gap" the
    design doc names: a GO TO landing outside a plain PERFORM's single-
    paragraph scope could silently fall through into unrelated code
    instead of returning. This test's second case is the one that would
    have caught that silently, if it existed."""
    cbl_path = tmp_path / "GOTOEXIT.cbl"
    cbl_path.write_text(CBL)
    cut_path = tmp_path / "GOTOEXIT.cut"
    cut_path.write_text(CUT)

    exit_code = main(["run", str(cbl_path), "--cut", str(cut_path)])
    out = capsys.readouterr().out

    assert exit_code == 0, out
    assert "[PASS] normal path -- early exit not taken, falls through to MOVE 99" in out
    assert "[PASS] early-exit path -- GO TO fires, MOVE 99 must NOT run" in out
    assert "[PASS] third case still runs after the early-exit case" in out
    assert "CRASH" not in out
    assert "FAIL" not in out


def test_goto_is_actually_spliced_out_of_the_compiled_source(tmp_path: Path):
    """`export` is Docker-free (identical pre-splice pipeline to `run`,
    stopping before compile/run) so this one runs even without a Docker
    daemon -- real end-to-end verification of the splice mechanics
    through the full CLI pipeline, just not of GnuCOBOL's own runtime
    behavior. The instrumented source must no longer contain a live
    `GO TO 0000-MAIN-EXIT` -- it should be commented out and replaced
    with EXIT PARAGRAPH, per GotoExitPlan/build_goto_exit_replacement."""
    cbl_path = tmp_path / "GOTOEXIT.cbl"
    cbl_path.write_text(CBL)
    cut_path = tmp_path / "GOTOEXIT.cut"
    cut_path.write_text(CUT)
    out_path = tmp_path / "GOTOEXIT.exported.cbl"

    exit_code = main(
        [
            "export",
            str(cbl_path),
            "--cut",
            str(cut_path),
            "--output",
            str(out_path),
        ]
    )
    assert exit_code == 0
    exported = out_path.read_text()
    assert "EXIT PARAGRAPH" in exported
    live_goto_lines = [
        line
        for line in exported.splitlines()
        if "GO TO 0000-MAIN-EXIT" in line and "*>" not in line
    ]
    assert live_goto_lines == []
