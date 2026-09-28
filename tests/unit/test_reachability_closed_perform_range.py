"""Unit tests for the closed PERFORM-range stop in the GO TO fall-through
closure (2026-09-28, `_closed_perform_ranges`).

The CCVS / "PERFORM X THRU X-EXIT" idiom -- `PERFORM BAIL-OUT THRU
BAIL-OUT-EX` whose body does `GO TO BAIL-OUT-WRITE`, a member that falls
through into BAIL-OUT-EX -- used to make the fall-through walk from
BAIL-OUT-WRITE cascade past BAIL-OUT-EX into the rest of the program, even
though GnuCOBOL's return marker for that PERFORM fires at BAIL-OUT-EX's end.
That is why the committed NIST IC101A example refused (unmocked CLOSE,
SECTION-scoped STOP RUN) for a case that only PERFORMs one CALL test.
"""

from cobolparser import parse_cobol

from mockymock.analysis.refusal._reachability import _reachable_paragraphs

HEADER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. RNGTEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A                PIC X VALUE SPACE.
       PROCEDURE DIVISION.
"""

# PERFORM BAIL-OUT THRU BAIL-OUT-EX, with an internal GO TO to a member
# that falls through into the range end; DOWNSTREAM physically follows.
CLOSED = HEADER + """\
       MAIN-PARA.
           PERFORM BAIL-OUT THRU BAIL-OUT-EX.
           GOBACK.
       BAIL-OUT.
           IF WS-A NOT = SPACE GO TO BAIL-OUT-WRITE.
           GO TO BAIL-OUT-EX.
       BAIL-OUT-WRITE.
           DISPLAY WS-A.
       BAIL-OUT-EX.
           EXIT.
       DOWNSTREAM.
           CALL "DOWNSTRM".
           STOP RUN.
"""


def _reach(source, start, thru=None):
    result = parse_cobol(source, filename="RNGTEST.cbl")
    assert result.success, result.errors
    reachable, reasons = _reachable_paragraphs(result.ast, start, thru)
    assert reasons == []
    return reachable


def test_walk_stops_at_the_end_of_a_closed_perform_thru_range():
    reachable = _reach(CLOSED, "MAIN-PARA")
    assert {"BAIL-OUT", "BAIL-OUT-WRITE", "BAIL-OUT-EX"} <= reachable
    assert "DOWNSTREAM" not in reachable


def test_go_to_into_the_range_from_outside_disqualifies_it():
    """A GO TO BAIL-OUT-WRITE from outside the range enters it with no
    marker for it active: falling off BAIL-OUT-EX then really continues."""
    source = CLOSED.replace(
        "           GOBACK.\n",
        "           IF WS-A = 'X' GO TO BAIL-OUT-WRITE.\n           GOBACK.\n",
    )
    assert "DOWNSTREAM" in _reach(source, "MAIN-PARA")


def test_plain_perform_of_a_member_disqualifies_the_range():
    source = CLOSED.replace(
        "           GOBACK.\n",
        "           PERFORM BAIL-OUT-WRITE.\n           GOBACK.\n",
    )
    assert "DOWNSTREAM" in _reach(source, "MAIN-PARA")


def test_fall_through_into_the_range_from_outside_drops_it():
    """P0 is a GO TO target whose fall-through lands in BAIL-OUT with no
    PERFORM of the range active. BAIL-OUT itself ends in an unconditional
    GO TO, so P0's own walk stops there -- only the dynamic exposure check
    stops BAIL-OUT-WRITE's walk from wrongly ending at BAIL-OUT-EX."""
    source = HEADER + """\
       MAIN-PARA.
           PERFORM BAIL-OUT THRU BAIL-OUT-EX.
           GO TO P0.
       P0.
           DISPLAY "P0".
       BAIL-OUT.
           GO TO BAIL-OUT-WRITE.
       BAIL-OUT-WRITE.
           DISPLAY WS-A.
       BAIL-OUT-EX.
           EXIT.
       DOWNSTREAM.
           CALL "DOWNSTRM".
           STOP RUN.
"""
    assert "DOWNSTREAM" in _reach(source, "MAIN-PARA")


def test_the_test_cases_own_thru_range_is_a_closed_range():
    """The driver's own PERFORM CALL-TEST-1 THRU CALL-WRITE-1 returns at
    CALL-WRITE-1's end, so the internal GO TO CALL-WRITE-1 must not cascade
    into the next test's paragraphs (IC101A's shape)."""
    source = HEADER + """\
       CALL-TEST-1.
           IF WS-A = SPACE GO TO CALL-WRITE-1.
           DISPLAY "FAIL".
       CALL-WRITE-1.
           DISPLAY "WRITE".
       CALL-TEST-2.
           CALL "OTHER".
           STOP RUN.
"""
    assert "CALL-TEST-2" not in _reach(source, "CALL-TEST-1", "CALL-WRITE-1")
    # ...but a plain PERFORM CALL-TEST-1 returns at CALL-TEST-1's end, so
    # its GO TO CALL-WRITE-1 leaves the performed range and really does
    # fall through into CALL-TEST-2.
    assert "CALL-TEST-2" in _reach(source, "CALL-TEST-1")


def test_a_driver_seed_naming_a_member_disqualifies_a_program_range():
    """The .cut entry point is invisible to the whole-program scan: a case
    that PERFORMs BAIL-OUT-WRITE directly returns at ITS end, but the
    program range must not be trusted for that case either."""
    source = CLOSED.replace(
        "       BAIL-OUT-WRITE.\n           DISPLAY WS-A.\n",
        "       BAIL-OUT-WRITE.\n           DISPLAY WS-A.\n"
        "           IF WS-A = 'Z' GO TO BAIL-OUT.\n",
    )
    assert "DOWNSTREAM" in _reach(source, "BAIL-OUT-WRITE")


# Two EXEC blocks ending in "END-EXEC." give the AST two phantom "."
# paragraphs -- which used to read as a duplicated paragraph name and
# switch the closed-range stop off for the whole program (the committed
# ACCTMNT example refused its 2000-PROCESS-PARM-CARDS cases for it).
WITH_EXEC_PHANTOMS = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PHANTOM.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
           EXEC SQL INCLUDE SQLCA END-EXEC.
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM FEE-POST THRU FEE-DONE.
       RATE-CHANGE.
           EXEC SQL COMMIT END-EXEC.
       FEE-POST.
           EXEC SQL OPEN C1 END-EXEC.
           IF SQLCODE NOT = 0
               GO TO FEE-DONE
           END-IF.
       FEE-DONE.
           EXEC SQL CLOSE C1 END-EXEC.
       FINALIZE.
           CALL "REALPGM".
"""


def test_phantom_exec_paragraphs_do_not_disable_the_range_stop():
    result = parse_cobol(WITH_EXEC_PHANTOMS, filename="PHANTOM.cbl")
    assert result.success, result.errors
    reachable, reasons = _reachable_paragraphs(result.ast, "MAIN-PARA")
    assert reasons == []
    assert {"FEE-POST", "FEE-DONE"} <= reachable
    assert "FINALIZE" not in reachable
