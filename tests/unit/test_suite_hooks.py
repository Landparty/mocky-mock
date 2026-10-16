"""Suite hooks end to end, short of compiling: BEFORE-ALL/BEFORE-EACH/
AFTER-EACH/AFTER-ALL steps through the static checks, the snapshot plan,
the mock dispatch and the generated driver
(docs/2026-10-10-suite-hooks-design.md)."""

from pathlib import Path

import pytest
from cobolparser import parse_cobol

from mockymock.cli.checks import run_static_checks
from mockymock.dsl.model import SUITE_PHASE_ID
from mockymock.dsl.parser import parse_cut
from mockymock.splicer.driver import build_driver
from mockymock.splicer.injector import dispatch_entries
from mockymock.splicer.naming import TallyRegistry
from mockymock.splicer.snapshot import (
    SYNTHESIZED_GROUP_BYTES,
    StateSnapshot,
    plan_snapshot,
)

PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. HOOKS.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-RATE          PIC S9(3)V99 COMP-3 VALUE 0.
       01  WS-SEP           PIC S9(3) SIGN LEADING SEPARATE.
       01  WS-TOTALS.
           05 WS-COUNT      PIC 9(4).
           05 WS-AMOUNTS    OCCURS 3 TIMES PIC 9(5)V99 COMP-3.
       01  WS-TOTALS-X REDEFINES WS-TOTALS PIC X(16).
       77  WS-PTR           USAGE POINTER.
       01  WS-FLOAT         COMP-2.
       01  WS-MSG           PIC X(20).
       PROCEDURE DIVISION.
       0000-MAIN.
           PERFORM 0100-INIT
           PERFORM 1000-CALC
           GOBACK.
       0100-INIT.
           CALL "LOADRATE" USING WS-RATE.
       0200-CLEAR.
           MOVE 0 TO WS-COUNT.
       1000-CALC.
           ADD 1 TO WS-COUNT
           CALL "AUDIT" USING WS-COUNT.
       9000-CLOSE.
           MOVE "DONE" TO WS-MSG.
"""

CUT = """\
TESTSUITE "hooks"

BEFORE-ALL
    MOCK CALL "LOADRATE"
        MOVE 1.25 TO WS-RATE
    END-MOCK
    PERFORM 0100-INIT
END-BEFORE

BEFORE-EACH
    MOCK CALL "AUDIT"
    END-MOCK
    PERFORM 0200-CLEAR
END-BEFORE

AFTER-EACH
    MOVE SPACES TO WS-MSG
END-AFTER

AFTER-ALL
    PERFORM 9000-CLOSE
END-AFTER

TESTCASE "uses the rate BEFORE-ALL loaded"
    PERFORM 1000-CALC
    EXPECT WS-RATE TO BE 1.25
    EXPECT WS-COUNT TO BE 1
    VERIFY CALL "AUDIT" WAS CALLED ONCE

TESTCASE "starts from BEFORE-ALL state again"
    MOVE 5 TO WS-COUNT
    PERFORM 1000-CALC
    EXPECT WS-COUNT TO BE 6
"""


@pytest.fixture
def files(tmp_path: Path):
    def write(cut: str = CUT, program: str = PROGRAM) -> tuple[Path, Path]:
        cbl = tmp_path / "HOOKS.cbl"
        cbl.write_text(program)
        cut_path = tmp_path / "HOOKS.cut"
        cut_path.write_text(cut)
        return cbl, cut_path

    return write


def test_clean_suite_passes_and_plans_a_snapshot(files):
    result = run_static_checks(*files(), None)
    assert result.problems == []
    assert result.snapshot is not None
    assert result.snapshot.save_lines


def test_shared_mock_reached_only_by_a_hook_step_is_not_refused(files):
    # LOADRATE is reached only by BEFORE-ALL's PERFORM 0100-INIT, never by a
    # test case's own PERFORM -- that is the point of the block.
    result = run_static_checks(*files(), None)
    assert not any("LOADRATE" in p for p in result.problems)


def test_shared_mock_reached_by_nothing_is_refused_once(files):
    cut = CUT.replace(
        '    MOCK CALL "AUDIT"\n    END-MOCK\n',
        '    MOCK CALL "AUDIT"\n    END-MOCK\n    MOCK CALL "NOWHERE"\n    END-MOCK\n',
    )
    result = run_static_checks(*files(cut), None)
    unmatched = [p for p in result.problems if "NOWHERE" in p]
    assert unmatched == [
        'refused (UNMATCHED_MOCK): BEFORE-EACH MOCK CALL "NOWHERE" is not '
        "reached by any test case or hook step"
    ]


def test_unmocked_boundary_in_a_before_all_step_says_where_to_add_the_mock(files):
    cut = CUT.replace(
        '    MOCK CALL "LOADRATE"\n        MOVE 1.25 TO WS-RATE\n    END-MOCK\n', ""
    )
    result = run_static_checks(*files(cut), None)
    refusal = [p for p in result.problems if "LOADRATE" in p]
    assert refusal and refusal[0].startswith(
        "refused (UNMOCKED_CALL): BEFORE-ALL PERFORM 0100-INIT:"
    )
    assert "    Add to BEFORE-ALL:" in result.problems


def test_each_hook_problem_is_reported_once_not_per_case(files):
    cut = """\
TESTSUITE "dedupe"
BEFORE-EACH
    PERFORM 1000-CALC
END-BEFORE
TESTCASE "a"
    PERFORM 9000-CLOSE
TESTCASE "b"
    PERFORM 9000-CLOSE
"""
    result = run_static_checks(*files(cut), None)
    hook = [p for p in result.problems if p.startswith("refused (UNMOCKED_CALL)")]
    assert len(hook) == 1
    assert hook[0].startswith(
        "refused (UNMOCKED_CALL): BEFORE-EACH (TESTCASE 'a') PERFORM 1000-CALC:"
    )
    assert "    Add to BEFORE-EACH:" in result.problems


def test_each_hook_perform_does_not_refuse_a_test_cases_own_mock(files):
    # AUDIT is the case's own mock, reached by its own PERFORM 1000-CALC;
    # BEFORE-EACH's PERFORM 0200-CLEAR never reaches it, and must not have to.
    cut = """\
TESTSUITE "own mock"
BEFORE-EACH
    PERFORM 0200-CLEAR
END-BEFORE
AFTER-EACH
    PERFORM 9000-CLOSE
END-AFTER
TESTCASE "own mock"
    MOCK CALL "AUDIT"
    END-MOCK
    PERFORM 1000-CALC
    EXPECT WS-COUNT TO BE 1
"""
    result = run_static_checks(*files(cut), None)
    assert result.problems == []


def test_case_own_mock_its_perform_never_reaches_is_still_refused(files):
    cut = """\
TESTSUITE "own mock"
BEFORE-EACH
    PERFORM 1000-CALC
END-BEFORE
TESTCASE "unreached"
    MOCK CALL "AUDIT"
    END-MOCK
    PERFORM 0200-CLEAR
"""
    result = run_static_checks(*files(cut), None)
    assert any(
        p.startswith("refused (UNMATCHED_MOCK)") and "AUDIT" in p
        for p in result.problems
    )


def test_odo_group_refuses_before_all_but_not_a_suite_without_it(files):
    program = PROGRAM.replace(
        "           05 WS-AMOUNTS    OCCURS 3 TIMES PIC 9(5)V99 COMP-3.\n",
        "           05 WS-AMOUNTS    OCCURS 1 TO 3 TIMES DEPENDING ON WS-COUNT\n"
        "                            PIC 9(5)V99 COMP-3.\n",
    )
    result = run_static_checks(*files(program=program), None)
    assert any(
        p.startswith("refused (UNSAVABLE_BEFORE_ALL_STATE): WS-TOTALS:")
        and "DEPENDING ON WS-COUNT" in p
        for p in result.problems
    )
    no_before_all = CUT.split("BEFORE-EACH")[0].split("BEFORE-ALL")[0] + (
        "BEFORE-EACH" + CUT.split("BEFORE-EACH", 1)[1]
    )
    no_before_all = no_before_all.replace("    EXPECT WS-RATE TO BE 1.25\n", "")
    result = run_static_checks(*files(no_before_all, program), None)
    assert not any("UNSAVABLE" in p for p in result.problems)
    assert result.snapshot is None


def test_snapshot_copies_each_item_the_exact_way():
    ast = parse_cobol(PROGRAM).ast
    snapshot, problems = plan_snapshot(ast)
    assert problems == []
    ws = snapshot.working_storage_lines
    assert "01  UT-SNAP-001 PIC S9(3)V99 USAGE COMP-3." in ws
    assert "01  UT-SNAP-002 PIC S9(3) SIGN LEADING SEPARATE." in ws
    # Group: a byte copy into an upper-bound buffer.
    group = ws.index("01  UT-SNAP-003.")
    size = int(ws[group + 1].split("X(")[1].rstrip(")."))
    assert size >= 4 + 3 * 4
    assert "01  UT-SNAP-004 USAGE POINTER." in ws
    assert "01  UT-SNAP-005 USAGE COMP-2." in ws
    assert snapshot.save_lines == [
        "MOVE WS-RATE TO UT-SNAP-001",
        "MOVE WS-SEP TO UT-SNAP-002",
        "MOVE WS-TOTALS TO UT-SNAP-003",
        "SET UT-SNAP-004 TO WS-PTR",
        "MOVE WS-FLOAT TO UT-SNAP-005",
        "MOVE WS-MSG TO UT-SNAP-006",
    ]
    # The top-level REDEFINES shares WS-TOTALS's storage: not copied twice.
    assert not any("WS-TOTALS-X" in line for line in snapshot.save_lines)
    assert snapshot.restore_lines[3] == "SET WS-PTR TO UT-SNAP-004"
    assert snapshot.restore_lines[0] == "MOVE UT-SNAP-001 TO WS-RATE"


EDITED_PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SN3.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-PH                 PIC XXXBXXXX VALUE SPACES.
       01  WS-D                  PIC XX/XX.
       01  WS-AMT                PIC ZZ9.99.
       01  WS-CNT                PIC 9(3) VALUE 0.
       PROCEDURE DIVISION.
       0000-MAIN.
           GOBACK.
"""


def test_snapshot_byte_copies_edited_items():
    """Issue #224: a MOVE into an edited item re-applies its editing mask to
    the already-edited sender, so a same-PICTURE snapshot shifted the value
    on every restore ("AB/CD" came back "AB///"). Edited items are copied
    as bytes, like groups; plain items keep the same-PICTURE copy."""
    snapshot, problems = plan_snapshot(parse_cobol(EDITED_PROGRAM).ast)
    assert problems == []
    ws = snapshot.working_storage_lines
    for n in (1, 2, 3):
        group = ws.index(f"01  UT-SNAP-00{n}.")
        assert ws[group + 1].startswith("    05 FILLER PIC X(")
    assert "01  UT-SNAP-004 PIC 9(3)." in ws
    assert snapshot.save_lines[:2] == [
        "MOVE WS-PH TO UT-SNAP-001",
        "MOVE WS-D TO UT-SNAP-002",
    ]
    assert snapshot.restore_lines[1] == "MOVE UT-SNAP-002 TO WS-D"


CICS_EIB_PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. EB.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-MODE               PIC X(5).
       01  WS-CA                 PIC X(10).
       LINKAGE SECTION.
       01  DFHCOMMAREA           PIC X(10).
       PROCEDURE DIVISION.
       0000-MAIN.
           IF EIBCALEN = 0
               MOVE "FIRST" TO WS-MODE
           ELSE
               MOVE "NEXT" TO WS-MODE
               MOVE DFHCOMMAREA TO WS-CA
           END-IF
           EXEC CICS RETURN END-EXEC.
"""

CICS_EIB_CUT = """\
TESTSUITE "eb"
BEFORE-ALL
    MOVE 10 TO EIBCALEN
    MOVE "STATE1" TO DFHCOMMAREA
END-BEFORE
TESTCASE "continuation"
    MOCK CICS "RETURN"
        CONTINUE
    END-MOCK
    PERFORM 0000-MAIN
    EXPECT WS-MODE TO BE "NEXT"
    EXPECT WS-CA TO BE "STATE1"
"""

SQLCA_PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SQ.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
           EXEC SQL INCLUDE SQLCA END-EXEC.
       01  WS-R                  PIC X(3).
       PROCEDURE DIVISION.
       0000-MAIN.
           IF SQLCODE NOT = 0
               MOVE "ERR" TO WS-R
           ELSE
               MOVE "OK" TO WS-R
           END-IF
           GOBACK.
"""

SQLCA_CUT = """\
TESTSUITE "sq"
BEFORE-ALL
    MOVE -911 TO SQLCODE
END-BEFORE
TESTCASE "err"
    PERFORM 0000-MAIN
    EXPECT WS-R TO BE "ERR"
"""


@pytest.mark.parametrize(
    ("program", "cut", "group"),
    [
        (CICS_EIB_PROGRAM, CICS_EIB_CUT, "DFHEIBLK"),
        (SQLCA_PROGRAM, SQLCA_CUT, "SQLCA"),
    ],
)
def test_snapshot_covers_the_synthesized_blocks(files, program, cut, group):
    """Issue #225: DFHEIBLK, DLIDIB and the generated SQLCA are spliced in
    after parsing, so the snapshot never saved them while the per-case
    reset still cleared them: a BEFORE-ALL that set EIBCALEN or SQLCODE was
    wiped before the first case. Each is now saved as a group byte copy."""
    result = run_static_checks(*files(cut, program), None)
    assert result.problems == []
    assert result.snapshot is not None
    assert f"MOVE {group} TO UT-SNAP-001" in result.snapshot.save_lines
    assert f"MOVE UT-SNAP-001 TO {group}" in result.snapshot.restore_lines
    assert result.snapshot.working_storage_lines[:2] == [
        "01  UT-SNAP-001.",
        f"    05 FILLER PIC X({SYNTHESIZED_GROUP_BYTES[group]}).",
    ]


def _driver(cut: str = CUT, snapshot: StateSnapshot | None = None):
    suite = parse_cut(cut)
    registry = TallyRegistry(suite)
    snapshot = snapshot or StateSnapshot(
        working_storage_lines=["01  UT-SNAP-001 PIC X(20)."],
        save_lines=["MOVE WS-MSG TO UT-SNAP-001"],
        restore_lines=["MOVE UT-SNAP-001 TO WS-MSG"],
    )
    artifact = build_driver(
        suite, ["MOVE SPACES TO WS-MSG"], registry, snapshot=snapshot
    )
    return suite, registry, artifact


def _stripped(lines: list[str]) -> list[str]:
    return [line.strip() for line in lines if line.strip()]


def test_driver_runs_before_all_once_saves_and_after_all_last():
    _, registry, artifact = _driver()
    proc = _stripped(artifact.procedure_lines)
    suite_start = proc.index('DISPLAY "__MOCKYMOCK__ TESTSUITE: hooks"')
    m = parse_cut(CUT).before_all_mocks[0]
    loadrate = registry.name(m.category, m.key)
    assert proc[suite_start + 1 : suite_start + 9] == [
        "PERFORM UT-RESET-WORKING-STORAGE",
        f'MOVE "{SUITE_PHASE_ID}" TO UT-CURRENT-CASE',
        'MOVE "N" TO UT-EARLY-EXIT',
        f"MOVE 0 TO {loadrate}",
        "PERFORM 0100-INIT",
        # The ROWS cursor each case resumes from (issue #223).
        f"MOVE {loadrate} TO {registry.start_name(m.category, m.key)}",
        "PERFORM UT-SAVE-STATE",
        "PERFORM UT-TESTCASE-001",
    ]
    after = proc.index("PERFORM UT-TESTCASE-002") + 1
    assert proc[after : after + 4] == [
        f'MOVE "{SUITE_PHASE_ID}" TO UT-CURRENT-CASE',
        'MOVE "N" TO UT-EARLY-EXIT',
        f"MOVE 0 TO {loadrate}",
        "PERFORM 9000-CLOSE",
    ]
    assert proc[after + 4].startswith('DISPLAY "__MOCKYMOCK__ SUMMARY')
    assert "01  UT-SNAP-001 PIC X(20)." in artifact.working_storage_lines
    assert "UT-SAVE-STATE." in proc and "UT-RESTORE-STATE." in proc


def test_driver_case_order_restore_before_each_case_body_after_each():
    suite, registry, artifact = _driver()
    proc = _stripped(artifact.procedure_lines)
    start = proc.index("UT-TESTCASE-001.")
    end = proc.index('DISPLAY "__MOCKYMOCK__ CASE 001 END".')
    body = proc[start:end]
    assert body[1:3] == ["PERFORM UT-RESET-WORKING-STORAGE", "PERFORM UT-RESTORE-STATE"]
    audit = registry.name(
        suite.before_each_mocks[0].category, suite.before_each_mocks[0].key
    )
    clear = body.index("PERFORM 0200-CLEAR")
    # A BEFORE-EACH PERFORM's own calls don't count toward the case's VERIFY,
    # but the tally (the ROWS cursor) keeps them (issue #223).
    audit_base = registry.base_name(
        suite.before_each_mocks[0].category, suite.before_each_mocks[0].key
    )
    assert f"MOVE {audit} TO {audit_base}" in body[clear + 1 :]
    assert f"MOVE 0 TO {audit}" not in body[clear + 1 :]
    assert body.index("PERFORM 1000-CALC") > clear
    assert body[-1] == "MOVE SPACES TO WS-MSG"
    # Second case: its own MOVE runs after BEFORE-EACH, so it wins.
    second = proc[proc.index("UT-TESTCASE-002.") :]
    assert second.index("MOVE 5 TO WS-COUNT") > second.index("PERFORM 0200-CLEAR")


def test_driver_clears_the_early_exit_flag_around_each_hook_performs():
    _, _, artifact = _driver(
        CUT.replace("    MOVE SPACES TO WS-MSG\n", "    PERFORM 9000-CLOSE\n")
    )
    proc = _stripped(artifact.procedure_lines)
    body = proc[proc.index("UT-TESTCASE-001.") :]
    body = body[: body.index('DISPLAY "__MOCKYMOCK__ CASE 001 END".')]
    reset = 'MOVE "N" TO UT-EARLY-EXIT'
    clear = body.index("PERFORM 0200-CLEAR")
    # A terminator BEFORE-EACH reached must not cut the case's PERFORM short.
    assert reset in body[clear : body.index("PERFORM 1000-CALC")]
    # Nor may one the case reached cut AFTER-EACH short.
    assert body[-2:] == [reset, "PERFORM 9000-CLOSE"]


def test_driver_leaves_move_only_each_hooks_untouched():
    _, _, artifact = _driver()
    proc = _stripped(artifact.procedure_lines)
    body = proc[proc.index("UT-TESTCASE-001.") :]
    body = body[: body.index('DISPLAY "__MOCKYMOCK__ CASE 001 END".')]
    # AFTER-EACH is MOVE-only here: no flag reset ahead of it.
    assert body[-2] != 'MOVE "N" TO UT-EARLY-EXIT'


def test_driver_without_before_all_never_saves_or_restores():
    cut = CUT.split("BEFORE-ALL")[0] + "BEFORE-EACH" + CUT.split("BEFORE-EACH", 1)[1]
    _, _, artifact = _driver(cut)
    proc = _stripped(artifact.procedure_lines)
    assert not any("SAVE-STATE" in line or "RESTORE-STATE" in line for line in proc)
    assert not any("UT-SNAP" in line for line in artifact.working_storage_lines)
    # AFTER-ALL still runs in the suite phase.
    assert f'MOVE "{SUITE_PHASE_ID}" TO UT-CURRENT-CASE' in proc


def test_dispatch_gives_the_suite_phase_before_all_mocks():
    suite = parse_cut(CUT)
    entries = dispatch_entries(suite)
    assert [case_id for case_id, _ in entries] == ["001", "002", SUITE_PHASE_ID]
    assert entries[-1][1] == suite.before_all_mocks


def test_dispatch_has_no_suite_phase_without_all_hooks():
    suite = parse_cut('TESTSUITE "s"\nTESTCASE "a"\n    PERFORM P\n')
    assert [case_id for case_id, _ in dispatch_entries(suite)] == ["001"]


SUBPROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SUBPGM.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-CALLS         PIC 9(4) VALUE 0.
       LINKAGE SECTION.
       01  LS-REQUEST.
           05 LS-CUST-ID    PIC X(8).
           05 LS-AMOUNTS    OCCURS 3 TIMES PIC S9(5)V99 COMP-3.
           05 LS-RC         PIC 9(2).
       01  LS-LIMIT         PIC S9(7)V99 COMP-3.
       PROCEDURE DIVISION USING LS-REQUEST LS-LIMIT.
       0000-MAIN.
           PERFORM 1000-CHECK
           GOBACK.
       0100-INIT.
           MOVE "CUST0001" TO LS-CUST-ID
           MOVE 500.00 TO LS-LIMIT.
       1000-CHECK.
           ADD 1 TO WS-CALLS
           IF LS-AMOUNTS(1) > LS-LIMIT
               MOVE 8 TO LS-RC
           ELSE
               MOVE 0 TO LS-RC
           END-IF.
"""

SUBPROGRAM_CUT = """\
TESTSUITE "entry parameters"
BEFORE-ALL
    PERFORM 0100-INIT
END-BEFORE
BEFORE-EACH
    MOVE 0 TO LS-RC
END-BEFORE
TESTCASE "over the limit BEFORE-ALL set"
    MOVE 600.00 TO LS-AMOUNTS(1)
    PERFORM 1000-CHECK
    EXPECT LS-RC TO BE 8
TESTCASE "the previous case's amount is gone"
    PERFORM 1000-CHECK
    EXPECT LS-LIMIT TO BE 500.00
"""


def test_entry_parameters_are_reset_and_saved_like_working_storage(files):
    """PROCEDURE DIVISION USING parameters: folded into WORKING-STORAGE (the
    USING clause blanked), reset before every case, and part of the state
    BEFORE-ALL hands to every case."""
    from mockymock.splicer.linkage import extra_reset_lines

    result = run_static_checks(*files(SUBPROGRAM_CUT, SUBPROGRAM), None)
    assert result.problems == []
    header = next(line for line in result.lines if "PROCEDURE DIVISION" in line)
    assert header.split() == ["PROCEDURE", "DIVISION", "."]
    assert result.linkage is not None
    assert extra_reset_lines(result.linkage) == [
        "INITIALIZE LS-REQUEST",
        "MOVE 0 TO LS-LIMIT",
    ]
    assert result.snapshot is not None
    assert "MOVE LS-REQUEST TO UT-SNAP-002" in result.snapshot.save_lines
    assert "MOVE UT-SNAP-003 TO LS-LIMIT" in result.snapshot.restore_lines


ROWS_HOOK_CUT = """\
TESTSUITE "rows"
BEFORE-ALL
    MOCK READ IN-FILE ROWS
        (IN-REC = "A")
        (IN-REC = "B")
    END-MOCK
    PERFORM 1000-INIT
END-BEFORE
BEFORE-EACH
    MOCK CALL "AUDIT"
    END-MOCK
    PERFORM 0200-CLEAR
END-BEFORE
TESTCASE "inherits the cursor"
    PERFORM 3000-LOOP
    VERIFY READ IN-FILE WAS CALLED 2 TIMES
TESTCASE "own rows"
    MOCK READ IN-FILE ROWS
        (IN-REC = "Z")
    END-MOCK
    PERFORM 3000-LOOP
"""


def test_rows_cursor_survives_hook_steps_while_verify_counts_the_case():
    """Issue #223: the tally is both the VERIFY count and the ROWS cursor.
    Zeroing it after a BEFORE-EACH PERFORM, or at the start of a case that
    inherits a BEFORE-ALL mock, handed out rows the hook's priming READ had
    already consumed. The cursor now resumes (from 0, or from where
    BEFORE-ALL left it); VERIFY counts against a per-key baseline."""
    suite = parse_cut(ROWS_HOOK_CUT)
    registry = TallyRegistry(suite)
    artifact = build_driver(suite, ["MOVE SPACES TO WS-MSG"], registry)
    proc = _stripped(artifact.procedure_lines)
    read = (suite.before_all_mocks[0].category, suite.before_all_mocks[0].key)
    audit = (suite.before_each_mocks[0].category, suite.before_each_mocks[0].key)
    tally, base = registry.name(*read), registry.base_name(*read)
    start = registry.start_name(*read)
    assert f"01  {start}      PIC 9(9) VALUE 0." in artifact.working_storage_lines
    assert f"MOVE {tally} TO {start}" in proc

    first = proc[proc.index("UT-TESTCASE-001.") : proc.index("UT-TESTCASE-002.")]
    assert f"MOVE {start} TO {tally}" in first
    assert f"MOVE {tally} TO {base}" in first
    assert f"MOVE 0 TO {registry.name(*audit)}" in first
    clear = first.index("PERFORM 0200-CLEAR")
    assert f"MOVE {registry.name(*audit)} TO {registry.base_name(*audit)}" in (
        first[clear + 1 :]
    )
    assert f"IF ({tally} - {base}) NOT = 2" in first

    # A case with its own MOCK for the key starts its own rows at 1.
    second = proc[proc.index("UT-TESTCASE-002.") :]
    assert f"MOVE 0 TO {tally}" in second
    assert f"MOVE {start} TO {tally}" not in second
