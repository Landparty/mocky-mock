"""End-to-end proof that a test case whose PERFORM target reaches
STOP RUN (through a chain of plain PERFORM calls) no longer crashes the
suite, and that a later test case in the same suite still runs -- see
docs/2026-07-08-goback-stop-run-support-design.md, Finding 3 of
docs/2026-07-06-real-world-readiness-audit.md."""

from pathlib import Path

import pytest

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
def test_go_to_reachable_terminator_goes_back_to_the_test(tmp_path: Path, capsys):
    """A GO TO-reachable terminator, refused until 2026-11-03: no EXIT verb
    returns from a GO TO target, so it GOBACKs to the test out of the
    driver's call frame, and the next case still runs."""
    cbl_path = tmp_path / "GOTOTERM.cbl"
    cbl_path.write_text(
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. GOTOTERM.\n"
        "\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01  WS-STEP             PIC 9 VALUE 0.\n"
        "\n"
        "       PROCEDURE DIVISION.\n"
        "       0000-MAIN-PROCESS.\n"
        "           MOVE 1 TO WS-STEP\n"
        "           GO TO 1000-EXIT.\n"
        "\n"
        "       1000-EXIT.\n"
        "           ADD 1 TO WS-STEP\n"
        "           STOP RUN.\n"
        "\n"
        "       2000-AFTER.\n"
        "           MOVE 9 TO WS-STEP.\n"
    )
    cut_path = tmp_path / "GOTOTERM.cut"
    cut_path.write_text(
        'TESTSUITE "gototerm"\n'
        "\n"
        'TESTCASE "reaches terminator via GO TO"\n'
        "    PERFORM 0000-MAIN-PROCESS\n"
        "    EXPECT WS-STEP TO BE 2\n"
        'TESTCASE "the next case still runs"\n'
        "    PERFORM 0000-MAIN-PROCESS\n"
        "    EXPECT WS-STEP TO BE 2\n"
    )

    exit_code = main(["run", str(cbl_path), "--cut", str(cut_path)])
    out = capsys.readouterr().out

    assert exit_code == 0, out
    assert "2 run, 0 failed" in out


@requires_docker
def test_terminator_inside_a_loop_body_stops_the_loop(tmp_path: Path, capsys):
    """A STOP RUN reachable only through the target of a PERFORM ... UNTIL
    (the looping-PERFORM gap of 2026-07-09, refused since then): the
    loop's UNTIL now also tests the early-exit flag, so the test stops at
    iteration 2, where the real STOP RUN stops the program, instead of
    running iterations 3-5."""
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
        "    EXPECT WS-COUNT TO BE 2\n"
        'TESTCASE "the next case still runs"\n'
        "    PERFORM 0000-MAIN-PROCESS\n"
        "    EXPECT WS-COUNT TO BE 2\n"
    )

    exit_code = main(["run", str(cbl_path), "--cut", str(cut_path)])
    out = capsys.readouterr().out

    assert exit_code == 0, out
    assert "[PASS] reaches terminator only via a looping PERFORM" in out
    assert "[PASS] the next case still runs" in out


@requires_docker
def test_terminator_via_out_of_line_perform_varying_goes_back_to_the_test(
    tmp_path: Path, capsys
):
    """Regression pin for a gap the 2026-07-09 final branch review
    surfaced, now resolved upstream: cobolparser's out-of-line PERFORM path
    (`PERFORM paragraph-name VARYING var FROM x BY y UNTIL cond`, as
    opposed to the inline `PERFORM VARYING ... END-PERFORM` block form)
    used to silently drop the trailing VARYING clause, mistagging
    `perform_type` as "SIMPLE" -- indistinguishable from a genuine plain
    PERFORM to `_plain_perform_edges_from`. What protected this shape at
    the time was a wholly unrelated mechanism: cobolparser also emitted a
    parse warning for the dropped clause, and check_whole_program refused
    on PARSE_WARNING before the terminator logic ever ran -- not the
    perform_type guard the mistagging should have defeated. cobolparser
    now parses this clause correctly (confirmed in
    tests/unit/test_refusal.py::test_out_of_line_perform_varying_parses_correctly),
    so this end-to-end test now proves the *intended* mechanism -- the
    perform_type guard in `_plain_perform_edges_from`, pinned at the unit
    level in
    tests/unit/test_terminators.py::test_terminator_reached_only_through_a_varying_loop_body_refuses
    (UNTIL loops are extended with the early-exit flag since 2026-10-29;
    VARYING is not, its counter would step once more) -- independently refuses this shape via `UNSUPPORTED_TERMINATOR_LAYOUT`
    against the real GnuCOBOL/Docker toolchain, rather than relying on the
    old parser bug's accidental PARSE_WARNING safety net. (Since 2026-11-03
    the shape no longer refuses: see the end of the test.)"""
    cbl_path = tmp_path / "VARYOUT.cbl"
    cbl_path.write_text(
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. VARYOUT.\n"
        "\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01  WS-I                PIC 9(2) VALUE 0.\n"
        "\n"
        "       PROCEDURE DIVISION.\n"
        "       0000-MAIN-PROCESS.\n"
        "           PERFORM 1000-LOOP-BODY\n"
        "               VARYING WS-I FROM 1 BY 1 UNTIL WS-I > 5.\n"
        "\n"
        "       1000-LOOP-BODY.\n"
        "           STOP RUN.\n"
    )
    cut_path = tmp_path / "VARYOUT.cut"
    cut_path.write_text(
        'TESTSUITE "varyout"\n'
        "\n"
        'TESTCASE "reaches terminator via out-of-line PERFORM VARYING"\n'
        "    PERFORM 0000-MAIN-PROCESS\n"
        "    EXPECT WS-I TO BE 1\n"
        'TESTCASE "the next case still runs"\n'
        "    PERFORM 0000-MAIN-PROCESS\n"
        "    EXPECT WS-I TO BE 1\n"
    )

    exit_code = main(["run", str(cbl_path), "--cut", str(cut_path)])
    out = capsys.readouterr().out

    # Since 2026-11-03 the STOP RUN GOBACKs to the test from the driver's
    # call frame: the loop stops at its first iteration, as the program does.
    assert exit_code == 0, out
    assert "2 run, 0 failed" in out
    assert "PARSE_WARNING" not in out


CHAIN_PERFORM_SOLE_STATEMENT_CBL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SOLESTMT.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-RESULT           PIC 9(4) VALUE 0.

       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           PERFORM 1000-WRAPPER.

       1000-WRAPPER.
           PERFORM 2000-INNER.

       2000-INNER.
           MOVE 1 TO WS-RESULT
           STOP RUN.
"""

CHAIN_PERFORM_SOLE_STATEMENT_CUT = """\
TESTSUITE "SOLESTMT smoke"

TESTCASE "chain PERFORM as sole statement of its paragraph compiles and runs"
    PERFORM 0000-MAIN-PROCESS
    EXPECT WS-RESULT TO BE 1
"""


@requires_docker
def test_chain_check_after_sole_period_terminated_perform_compiles(
    tmp_path: Path, capsys
):
    """Permanent regression fixture for a real, pre-existing splicer bug
    (not SECTION-specific -- discovered while building SECTION-scoped
    terminator support, but affects the already-shipped GOBACK/STOP RUN
    feature too): when an intermediate PERFORM in a safe chain is the
    sole, period-terminated statement of its own paragraph, the inserted
    chain-check block previously had no closing period, so the following
    paragraph header ran into an unterminated sentence and cobc rejected
    the compile. See the fix in mockymock/splicer/orchestrator.py's
    chain-check insertion loop."""
    cbl_path = tmp_path / "SOLESTMT.cbl"
    cbl_path.write_text(CHAIN_PERFORM_SOLE_STATEMENT_CBL)
    cut_path = tmp_path / "SOLESTMT.cut"
    cut_path.write_text(CHAIN_PERFORM_SOLE_STATEMENT_CUT)

    exit_code = main(["run", str(cbl_path), "--cut", str(cut_path)])
    out = capsys.readouterr().out

    assert exit_code == 0, out
    assert (
        "[PASS] chain PERFORM as sole statement of its paragraph compiles and runs"
        in out
    )


SECTION_CBL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SECTTERM.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-RESULT           PIC 9(4) VALUE 0.

       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           PERFORM 1000-TERM-SECTION.

       1000-TERM-SECTION SECTION.
       1000-TERM-FIRST.
           MOVE 1 TO WS-RESULT
           STOP RUN.
       1000-TERM-SECOND.
           MOVE 999 TO WS-RESULT.
"""

SECTION_CUT = """\
TESTSUITE "SECTTERM smoke"

TESTCASE "terminator in section's first paragraph is neutralized"
    PERFORM 0000-MAIN-PROCESS
    EXPECT WS-RESULT TO BE 1

TESTCASE "second case still runs after the first hits the section terminator"
    PERFORM 0000-MAIN-PROCESS
    EXPECT WS-RESULT TO BE 1
"""


@requires_docker
def test_section_scoped_terminator_neutralized_and_second_paragraph_does_not_run(
    tmp_path: Path, capsys
):
    """Permanent regression fixture for spike #5 of
    docs/2026-07-08-goback-stop-run-support-design.md, finally committed
    now that docs/2026-07-10-section-scoped-terminator-support-design.md
    implements it: STOP RUN in a SECTION's first paragraph, entered only
    via PERFORM <section-name>, is replaced with EXIT SECTION. Proves two
    things a unit test cannot: 1000-TERM-SECOND never runs (real GnuCOBOL
    EXIT SECTION semantics, not just the splice shape), and control
    correctly returns to the test driver (the case's own EXPECT runs, and
    a second test case in the suite still runs afterward).

    Verification mechanism: if 1000-TERM-SECOND incorrectly ran (EXIT
    SECTION failing to stop before it -- the exact failure mode this test
    exists to catch), it would overwrite WS-RESULT to 999, and
    `EXPECT WS-RESULT TO BE 1` would fail loudly with a [FAIL] line and a
    non-zero exit code -- a real, CLI-visible signal, unlike a DISPLAY
    statement's output, which mockymock's CLI never surfaces (it only
    prints structured __MOCKYMOCK__ TESTSUITE/CASE/SUMMARY lines parsed
    from the binary's stdout, per report/results.py's parse_stdout --
    verified by reading that function directly)."""
    cbl_path = tmp_path / "SECTTERM.cbl"
    cbl_path.write_text(SECTION_CBL)
    cut_path = tmp_path / "SECTTERM.cut"
    cut_path.write_text(SECTION_CUT)

    exit_code = main(["run", str(cbl_path), "--cut", str(cut_path)])
    out = capsys.readouterr().out

    assert exit_code == 0, out
    assert "[PASS] terminator in section's first paragraph is neutralized" in out
    assert (
        "[PASS] second case still runs after the first hits the section terminator"
        in out
    )
    assert "FAIL" not in out
    assert "CRASH" not in out


# Whole program in one SECTION, members PERFORMed by name; an abort
# paragraph in a second section, PERFORMed conditionally (2026-10-27,
# docs/2026-10-27-section-member-terminators-design.md).
SECTIONED_CBL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SECPGM.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-RC      PIC 99 VALUE 0.
       01  WS-STEP    PIC X(10) VALUE SPACES.
       01  WS-AFTER   PIC X VALUE 'N'.
       PROCEDURE DIVISION.
       A000-MAIN SECTION.
       A000-START.
           PERFORM A100-INIT
           PERFORM A200-WORK
           MOVE 'DONE' TO WS-STEP
           GOBACK.
       A100-INIT.
           MOVE 'INIT' TO WS-STEP.
       A200-WORK.
           CALL 'CHKSUB' USING WS-RC
           IF WS-RC NOT = 0
               PERFORM Z900-ABORT
           END-IF
           MOVE 'WORKED' TO WS-STEP.
       Z000-ERRORS SECTION.
       Z900-ABORT.
           MOVE 'ABORT' TO WS-STEP
           STOP RUN.
       Z910-NEVER.
           MOVE 'Y' TO WS-AFTER.
"""


def _sectioned_cut(target: str) -> str:
    return f"""\
TESTSUITE "SECPGM"

TESTCASE "abort"
    MOCK CALL "CHKSUB"
        MOVE 8 TO WS-RC
    END-MOCK
    PERFORM {target}
    EXPECT WS-STEP TO BE "ABORT"
    EXPECT WS-AFTER TO BE "N"

TESTCASE "happy"
    MOCK CALL "CHKSUB"
        MOVE 0 TO WS-RC
    END-MOCK
    PERFORM {target}
    EXPECT WS-STEP TO BE "DONE"
"""


@requires_docker
@pytest.mark.parametrize("target", ["A000-START", "A000-MAIN"])
def test_terminators_in_section_members_return_to_the_driver(
    tmp_path: Path, capsys, target: str
):
    """By name (A000-START: EXIT PARAGRAPH everywhere) or as the section's
    range (A000-MAIN: EXIT SECTION in A000-START and after its PERFORMs),
    both terminators return to the case: the abort stops before 'WORKED'
    and 'DONE' and never falls into Z910-NEVER, and the next case runs."""
    cbl_path = tmp_path / "SECPGM.cbl"
    cbl_path.write_text(SECTIONED_CBL)
    cut_path = tmp_path / "SECPGM.cut"
    cut_path.write_text(_sectioned_cut(target))

    exit_code = main(["run", str(cbl_path), "--cut", str(cut_path)])
    out = capsys.readouterr().out

    assert exit_code == 0, out
    assert "[PASS] abort" in out
    assert "[PASS] happy" in out


FALL_THROUGH_CBL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SECEX.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-RC      PIC 99 VALUE 0.
       01  WS-STEP    PIC X(10) VALUE SPACES.
       01  WS-AFTER   PIC X VALUE 'N'.
       PROCEDURE DIVISION.
       0000-MAIN SECTION.
       0000-START.
           CALL 'CHKSUB' USING WS-RC
           IF WS-RC NOT = 0
               MOVE 'EARLY' TO WS-STEP
               GOBACK
           END-IF
           MOVE 'MAIN' TO WS-STEP.
       0000-EXIT.
           GOBACK.
       0000-TAIL.
           MOVE 'Y' TO WS-AFTER.
"""

FALL_THROUGH_CUT = """\
TESTSUITE "SECEX"

TESTCASE "early"
    MOCK CALL "CHKSUB"
        MOVE 8 TO WS-RC
    END-MOCK
    PERFORM 0000-MAIN
    EXPECT WS-STEP TO BE "EARLY"
    EXPECT WS-AFTER TO BE "N"

TESTCASE "normal"
    MOCK CALL "CHKSUB"
        MOVE 0 TO WS-RC
    END-MOCK
    PERFORM 0000-MAIN
    EXPECT WS-STEP TO BE "MAIN"
    EXPECT WS-AFTER TO BE "N"
"""


@requires_docker
def test_terminator_in_an_exit_paragraph_reached_by_fall_through(
    tmp_path: Path, capsys
):
    """The `0000-EXIT. GOBACK.` idiom: the exit paragraph runs inside the
    `PERFORM 0000-MAIN` section range by falling through, and its EXIT
    SECTION stops before 0000-TAIL."""
    cbl_path = tmp_path / "SECEX.cbl"
    cbl_path.write_text(FALL_THROUGH_CBL)
    cut_path = tmp_path / "SECEX.cut"
    cut_path.write_text(FALL_THROUGH_CUT)

    exit_code = main(["run", str(cbl_path), "--cut", str(cut_path)])
    out = capsys.readouterr().out

    assert exit_code == 0, out
    assert "[PASS] early" in out
    assert "[PASS] normal" in out
