"""Bug hunt of 2026-10-27, after the SECTION-member terminator support
(PR #367). Each program here was reproduced on GnuCOBOL 3.2."""

from __future__ import annotations

from cobolparser import parse_cobol

from mockymock.analysis.exact_counts import exact_count_scope
from mockymock.analysis.refusal import find_terminator_plans
from mockymock.analysis.refusal._gates import union_executed_paragraphs
from mockymock.analysis.refusal._reachability import (
    _go_to_fallthrough_targets,
    _go_to_targets,
    _reachable_paragraphs,
)
from mockymock.dsl.model import MockTestCase, MockTestSuite
from tests.unit.test_terminators import _analyze

# P1 jumps to the last paragraph of S1, which falls into S2 and then S3.
# S2 is entered by nothing but that fall-through, so its end is no PERFORM
# return point: the unmocked CALL in S3 runs.
RUNAWAY = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. RUNAWAY.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-STEP    PIC X(10) VALUE SPACES.
       PROCEDURE DIVISION.
       S1 SECTION.
       P1.
           CALL 'APGM'
           GO TO P1-EXIT.
       P1-EXIT.
           EXIT.
       S2 SECTION.
       Q1.
           GO TO Q3.
       Q2.
           MOVE 'Q2' TO WS-STEP.
       Q3.
           MOVE 'Q3' TO WS-STEP.
       S3 SECTION.
       R1.
           CALL 'CPGM'.
"""


def _program(source: str):
    result = parse_cobol(source, filename="X.cbl")
    assert result.success, result.errors
    return result.ast


def _suite(*targets: str) -> MockTestSuite:
    return MockTestSuite(
        name="S",
        test_cases=[MockTestCase(name=t, perform_target=t) for t in targets],
    )


def test_fall_through_walk_continues_past_a_section_it_fell_into():
    seen, reasons = _reachable_paragraphs(_program(RUNAWAY), "P1", None)
    assert reasons == []
    assert "R1" in seen


def test_executed_union_continues_past_a_section_it_fell_into():
    executed = union_executed_paragraphs(_program(RUNAWAY), _suite("P1"))
    assert executed is not None
    assert "R1" in executed


def test_fall_through_hazards_continue_past_a_section_it_fell_into():
    program = _program(RUNAWAY)
    procedure = program.get_division("PROCEDURE")
    safe = {
        p.paragraph_name: name
        for name, section in procedure._sections.items()
        if name in ("S2", "S3")
        for p in section.paragraphs
    }
    hazards = _go_to_fallthrough_targets(program, _go_to_targets(program), safe)
    assert "R1" in hazards


EXIT_SECTION = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. EXSEC.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-RC      PIC 99 VALUE 0.
       PROCEDURE DIVISION.
       0000-MAIN SECTION.
       0000-START.
           PERFORM 1000-WORK
           GOBACK.
       1000-WORK SECTION.
       1000-A.
           CALL 'APGM' USING WS-RC
           EXIT SECTION.
       1000-B.
           CALL 'BPGM' USING WS-RC.
"""


def test_exact_counts_stop_at_the_end_of_a_section_range():
    """`PERFORM 1000-WORK` never runs 1000-B: its CALL is not counted
    (init wrote `VERIFY CALL "BPGM" WAS CALLED 1 TIMES`, got 0)."""
    program = _program(EXIT_SECTION)
    reachable = {"0000-START", "1000-A", "1000-B"}
    scope = exact_count_scope(program, "0000-START", reachable)
    assert scope is not None
    paragraphs, _ = scope
    assert "1000-A" in paragraphs
    assert "1000-B" not in paragraphs


FALL_IN = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. FALLIN.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-RC      PIC 99 VALUE 0.
       PROCEDURE DIVISION.
       0000-MAIN SECTION.
           PERFORM 1000-INIT
           CONTINUE.
       1000-INIT.
           CALL 'INITPGM' USING WS-RC.
"""


def test_a_member_run_by_perform_and_by_falling_in_is_not_counted_once():
    """`PERFORM 0000-MAIN` runs 1000-INIT twice: once PERFORMed, once by
    falling into it (init wrote `1 TIMES`, got 2)."""
    program = _program(FALL_IN)
    procedure = program.get_division("PROCEDURE")
    names = {p.paragraph_name for p in procedure._sections["0000-MAIN"].paragraphs}
    scope = exact_count_scope(program, "0000-MAIN", names)
    assert scope is not None
    paragraphs, _ = scope
    assert "1000-INIT" not in paragraphs


def _generate(tmp_path, name: str, cbl: str, *extra: str) -> str:
    from mockymock.cli.main import main

    source = tmp_path / f"{name}.cbl"
    source.write_text(cbl)
    out = tmp_path / f"{name}.cut"
    main(
        ["generate", str(source), "--with-data", "--seed", "1", "-o", str(out), *extra]
    )
    return out.read_text()


KEYED_READ = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. KEYRD.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT CUST-FILE ASSIGN TO CUSTF
               ORGANIZATION IS INDEXED
               ACCESS MODE IS RANDOM
               RECORD KEY IS CUST-ID
               FILE STATUS IS WS-FS.
       DATA DIVISION.
       FILE SECTION.
       FD  CUST-FILE.
       01  CUST-REC.
           05 CUST-ID    PIC X(6).
           05 CUST-NAME  PIC X(20).
       WORKING-STORAGE SECTION.
       01  WS-FS         PIC XX VALUE '00'.
       01  WS-FOUND      PIC X VALUE 'N'.
       PROCEDURE DIVISION.
       0000-MAIN.
           OPEN INPUT CUST-FILE
           PERFORM 1000-READ 3 TIMES
           CLOSE CUST-FILE
           GOBACK.
       1000-READ.
           MOVE 'C00001' TO CUST-ID
           READ CUST-FILE
               INVALID KEY MOVE 'N' TO WS-FOUND
               NOT INVALID KEY MOVE 'Y' TO WS-FOUND
           END-READ.
"""


def test_a_looped_read_with_no_at_end_gets_no_row_count(tmp_path):
    """The bundle counts a READ by its rows (10); a keyed READ in `PERFORM
    1000-READ 3 TIMES` reads 3 times (NIST IX301M / RL301M)."""
    cut = _generate(tmp_path, "KEYRD", KEYED_READ)
    assert "VERIFY READ CUST-FILE WAS CALLED 10 TIMES" not in cut
    assert "*> VERIFY READ CUST-FILE WAS CALLED <count not exact" in cut
    assert "VERIFY OPEN CUST-FILE WAS CALLED 1 TIMES" in cut


EARLY_STOP = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ESTOP.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-RC      PIC 99 VALUE 0.
       PROCEDURE DIVISION.
       0000-MAIN.
           CALL 'OPENPGM' USING WS-RC
           IF WS-RC NOT = 0
               MOVE 16 TO RETURN-CODE
               STOP RUN
           END-IF
           CALL 'WORKPGM' USING WS-RC
           PERFORM 1000-TERM
           GOBACK.
       1000-TERM.
           CALL 'TERMPGM' USING WS-RC.
"""


def test_sites_after_a_conditional_stop_are_not_counted():
    """The error-status scenario takes the STOP RUN branch: WORKPGM and
    TERMPGM never run there (init's `--scenarios all` scaffold failed its
    own run, `got 0`)."""
    program = _program(EARLY_STOP)
    scope = exact_count_scope(program, "0000-MAIN", {"0000-MAIN", "1000-TERM"})
    assert scope is not None
    _, statement_ids = scope
    procedure = program.get_division("PROCEDURE")
    by_name = {p.paragraph_name: p for p in procedure.paragraphs}
    main_calls = [
        s
        for s in by_name["0000-MAIN"].statements
        if type(s).__name__ == "CallStatement"
    ]
    assert id(main_calls[0]) in statement_ids  # OPENPGM, before the IF
    assert id(main_calls[1]) not in statement_ids  # WORKPGM, after it
    term_call = by_name["1000-TERM"].statements[0]
    assert id(term_call) not in statement_ids


TRAILING_EXIT_PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. EXPGM.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-RC      PIC 99 VALUE 0.
       01  WS-STEP    PIC X(10) VALUE SPACES.
       PROCEDURE DIVISION.
       A-MAIN SECTION.
       A-START.
           PERFORM A-CHECK
           MOVE 'DONE' TO WS-STEP
           EXIT PROGRAM.
       A-CHECK.
           CALL 'CHKSUB' USING WS-RC
           IF WS-RC NOT = 0
               MOVE 'EARLY' TO WS-STEP
               GOBACK
           END-IF.
"""


def test_a_trailing_exit_program_ends_the_section_range():
    """A-CHECK is PERFORMed by name and not fallen into: EXIT PROGRAM ends
    `PERFORM A-MAIN`'s range like GOBACK does, so nothing is refused."""
    program, surface, scope_map, lines = _analyze(TRAILING_EXIT_PROGRAM)
    plans, reasons = find_terminator_plans(
        surface, program, _suite("A-MAIN"), scope_map, lines
    )
    assert reasons == []
    kinds = {p.site.paragraph_name: p.exit_kind for p in plans}
    assert kinds == {"A-START": "SECTION", "A-CHECK": "PARAGRAPH"}


NEVER_PERFORMED = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. NEVERP.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-STEP    PIC X(10) VALUE SPACES.
       PROCEDURE DIVISION.
       S1 SECTION.
       P1.
           MOVE 'P1' TO WS-STEP
           GO TO P1-EXIT.
       P1-EXIT.
           EXIT.
       S2 SECTION.
       Q1.
           MOVE 'Q1' TO WS-STEP STOP RUN.
"""


# The STOP RUN shares its line with the MOVE, so it cannot GOBACK to the test
# instead either (2026-11-03): the refusal stands.
def test_refusal_names_why_a_member_has_no_mode():
    """Q1 is never PERFORMed at all; the message used to say it was
    "entered more than one way (by its own name and as part of its
    section's range ...)"."""
    program, surface, scope_map, lines = _analyze(NEVER_PERFORMED)
    _, reasons = find_terminator_plans(surface, program, _suite("P1"), scope_map, lines)
    messages = [r.message for r in reasons if "'Q1'" in r.message]
    assert messages
    assert "never PERFORMed" in messages[0]
    assert "more than one way" not in messages[0]
