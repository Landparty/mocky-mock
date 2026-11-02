"""Fixes from the 2026-11-02 stress test of the integrated testing stack
(backend test packs + oracle over a synthetic corpus of every program
type): a fixed test clock, mock bodies naming the argument a call passed,
identical case branches merged, one row per DL/I call, pinned MQ codes."""

from types import SimpleNamespace

from mockymock.runtime.executor import (
    CURRENT_DATE_ENV,
    DEFAULT_CURRENT_DATE,
    fixed_clock_env,
)
from mockymock.splicer.injector import (
    _case_selectors,
    merge_identical_branches,
    passed_argument_names,
)
from tests.unit.test_bug_hunt_m1_fixes import _generate
from tests.unit.test_issue_156_loop_end_reply import _mock

# --- fixed clock -----------------------------------------------------------


def test_test_binaries_run_on_a_fixed_clock(monkeypatch):
    """BNDET01 DISPLAYed FUNCTION CURRENT-DATE: every oracle compare of it
    reported a behaviour change although nothing changed."""
    monkeypatch.delenv("COB_CURRENT_DATE", raising=False)
    monkeypatch.delenv(CURRENT_DATE_ENV, raising=False)
    assert fixed_clock_env() == {"COB_CURRENT_DATE": DEFAULT_CURRENT_DATE}


def test_fixed_clock_can_be_moved_or_turned_off(monkeypatch):
    monkeypatch.delenv("COB_CURRENT_DATE", raising=False)
    monkeypatch.setenv(CURRENT_DATE_ENV, "2030/12/31 23:59:59.00")
    assert fixed_clock_env() == {"COB_CURRENT_DATE": "2030/12/31 23:59:59.00"}
    monkeypatch.setenv(CURRENT_DATE_ENV, "real")
    assert fixed_clock_env() == {}


def test_a_clock_the_user_set_is_kept(monkeypatch):
    monkeypatch.setenv("COB_CURRENT_DATE", "2001/01/01 00:00:00.00")
    assert fixed_clock_env() == {}


def test_native_run_passes_the_clock(monkeypatch, tmp_path):
    from mockymock.runtime import native_toolchain

    seen = {}

    def fake_run(cmd, **kwargs):
        seen.update(kwargs.get("env") or {})
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.delenv("COB_CURRENT_DATE", raising=False)
    monkeypatch.delenv(CURRENT_DATE_ENV, raising=False)
    monkeypatch.setattr(native_toolchain, "_run", fake_run)
    monkeypatch.setattr(native_toolchain, "_require_home", lambda: tmp_path)
    binary = tmp_path / "PROG"
    binary.write_text("")
    native_toolchain.run_binary(binary, timeout_seconds=5)
    assert seen.get("COB_CURRENT_DATE") == DEFAULT_CURRENT_DATE


# --- UT-PASSED-ARG-n --------------------------------------------------------


def _site(*names):
    statement = SimpleNamespace(
        using_parameters=[SimpleNamespace(name=name) for name in names]
    )
    return SimpleNamespace(statement=statement)


def test_passed_argument_names_quote_the_sites_own_argument():
    site = _site("DLI-GU", "db-pcb", "WS-SEG")
    body = 'IF UT-PASSED-ARG-2 = "DB-PCB" AND UT-PASSED-ARG-9 = " "'
    assert passed_argument_names(body, site) == 'IF "DB-PCB" = "DB-PCB" AND " " = " "'
    assert passed_argument_names("MOVE 1 TO X", site) == "MOVE 1 TO X"


# --- merged case branches ---------------------------------------------------

BODY = ["                   ADD 1 TO UT-WRITE-OUT-TALLY"]
OTHER = [
    "               WHEN OTHER",
    '                   DISPLAY "trap"',
    "           END-EVALUATE",
]


def _dispatch(bodies):
    lines = ["           EVALUATE UT-CURRENT-CASE"]
    for case_id, body in bodies:
        lines.append(f'               WHEN "{case_id}"')
        lines.extend(body)
    return lines + OTHER


def test_identical_case_branches_are_emitted_once():
    """HUGE01: 300 WRITE sites x 305 generated cases spliced 490k lines,
    and gcc ran out of time (and 9 GB of memory) compiling them."""
    special = ["                   MOVE 1 TO X"]
    cases = [(f"{n:03d}", BODY) for n in range(1, 306)]
    cases[4] = ("005", special)
    merged = merge_identical_branches(_dispatch(cases))
    assert merged == [
        "           EVALUATE UT-CURRENT-CASE",
        '               WHEN "001" THRU "004"',
        '               WHEN "006" THRU "305"',
        *BODY,
        '               WHEN "005"',
        *special,
        *OTHER,
    ]


def test_dispatch_with_no_shared_branch_is_unchanged():
    lines = _dispatch([("001", BODY), ("002", ["                   CONTINUE"])])
    assert merge_identical_branches(lines) == lines


def test_case_selectors_keep_short_runs_and_odd_ids_apart():
    assert _case_selectors(["001", "002", "004", "005", "006", "SUITE"]) == [
        '"001"',
        '"002"',
        '"004" THRU "006"',
        '"SUITE"',
    ]
    # Ids of different widths never share a range.
    assert _case_selectors(["998", "999", "1000"]) == ['"998"', '"999"', '"1000"']


# --- one row per DL/I call --------------------------------------------------

IMS_MPP = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. IMSORD.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  DLI-GU               PIC X(4) VALUE 'GU  '.
       01  DLI-ISRT             PIC X(4) VALUE 'ISRT'.
       01  WS-IN-MSG.
           05  IM-LL            PIC S9(4) COMP.
           05  IM-ZZ            PIC S9(4) COMP.
           05  IM-PART          PIC X(8).
       01  WS-OUT-MSG.
           05  OM-LL            PIC S9(4) COMP VALUE 30.
           05  OM-ZZ            PIC S9(4) COMP VALUE 0.
           05  OM-CODE          PIC X(3).
       01  WS-SEG.
           05  SG-PART          PIC X(8).
       LINKAGE SECTION.
       01  IO-PCB.
           05  IO-LTERM         PIC X(8).
           05  FILLER           PIC XX.
           05  IO-STATUS        PIC XX.
           05  FILLER           PIC X(20).
       01  DB-PCB.
           05  DB-NAME          PIC X(8).
           05  DB-LEVEL         PIC XX.
           05  DB-STATUS        PIC XX.
           05  FILLER           PIC X(20).
       PROCEDURE DIVISION.
       0000-MAIN.
           ENTRY 'DLITCBL' USING IO-PCB DB-PCB.
           CALL 'CBLTDLI' USING DLI-GU IO-PCB WS-IN-MSG
           PERFORM UNTIL IO-STATUS NOT = SPACES
               CALL 'CBLTDLI' USING DLI-GU DB-PCB WS-SEG
               EVALUATE DB-STATUS
                   WHEN SPACES
                       CALL 'IMSCHK' USING WS-SEG OM-CODE
                   WHEN 'GE'
                       MOVE 'NF ' TO OM-CODE
               END-EVALUATE
               CALL 'CBLTDLI' USING DLI-ISRT IO-PCB WS-OUT-MSG
               CALL 'CBLTDLI' USING DLI-GU IO-PCB WS-IN-MSG
           END-PERFORM
           GOBACK.
"""


def test_each_dli_call_gets_its_own_row(tmp_path):
    """IMSORD: one MOCK answered the message GU, the DB GU and the ISRT
    with the first fixture's row, so the DB PCB status a branch needed
    was lost and the found path (and IMSCHK) never ran."""
    cut = _generate(tmp_path, "IMSORD", IMS_MPP, "--seed", "1", "--scenarios", "all")
    body = _mock(cut, 'MOCK CALL "CBLTDLI"')
    assert 'WHEN UT-CAP-CBLTDLI-1 = "GU" AND UT-PASSED-ARG-2 = "IO-PCB"' in body
    assert 'WHEN UT-CAP-CBLTDLI-1 = "GU" AND UT-PASSED-ARG-2 = "DB-PCB"' in body
    assert 'WHEN UT-CAP-CBLTDLI-1 = "ISRT"' in body
    # Only the message GU ends the loop; the DB GU keeps its row's status
    # (the priming GU shares function and PCB, so the tally tells them
    # apart).
    assert "IF UT-CBLTDLI-TALLY > 1" in body
    assert 'MOVE "QC" TO IO-PCB(11:2)' in body
    assert 'MOVE "GE" TO DB-PCB(11:2)' not in body
    assert 'MOVE "GE" TO DB-STATUS' in cut  # the not-found case's own row


# --- pinned MQ reply --------------------------------------------------------

MQ_PROG = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. MQPROC.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-HCONN             PIC S9(9) BINARY VALUE 0.
       01  WS-HOBJ              PIC S9(9) BINARY.
       01  WS-COMPCODE          PIC S9(9) BINARY.
       01  WS-REASON            PIC S9(9) BINARY.
       01  WS-BUFLEN            PIC S9(9) BINARY VALUE 20.
       01  WS-DATALEN           PIC S9(9) BINARY.
       01  WS-MD                PIC X(324).
       01  WS-GMO               PIC X(112).
       01  WS-MSG               PIC X(20).
       PROCEDURE DIVISION.
       0000-MAIN.
           CALL 'MQGET' USING WS-HCONN WS-HOBJ WS-MD WS-GMO
                              WS-BUFLEN WS-MSG WS-DATALEN
                              WS-COMPCODE WS-REASON
           IF WS-COMPCODE NOT = 0
               DISPLAY 'NO MESSAGE ' WS-REASON
           ELSE
               DISPLAY 'GOT ' WS-MSG
           END-IF
           GOBACK.
"""


def test_mq_failure_case_keeps_its_completion_code(tmp_path):
    """MQPROC: the scenario for `IF WS-COMPCODE NOT = 0` pinned a non-zero
    CompCode, and the success default (`MOVE 0`, #205) overwrote it: the
    no-message branch was never run."""
    cut = _generate(tmp_path, "MQPROC", MQ_PROG, "--seed", "1", "--scenarios", "all")
    bodies = []
    start = 0
    while (start := cut.find('MOCK MQ "MQGET"', start)) != -1:
        bodies.append(cut[start : cut.index("END-MOCK", start)])
        start += 1
    assert any("MOVE 0 TO WS-COMPCODE" in body for body in bodies)
    assert any(
        "TO WS-COMPCODE" in body and "MOVE 0 TO WS-COMPCODE" not in body
        for body in bodies
    )


# --- suite timeout leaves nothing running -----------------------------------

FAKE_MOCKYMOCK = """\
import sys, time
from pathlib import Path
from mockymock.runtime import native_toolchain as nt

nt.install_termination_handler()
child = Path(sys.argv[1])
try:
    nt._run(
        [sys.executable, "-c",
         f"import os, time; open({str(child)!r}, 'w').write(str(os.getpid())); "
         "time.sleep(120)"],
        cwd=Path("."), env=None, timeout=300, text=True,
    )
except SystemExit:
    raise
"""


def test_runner_timeout_kills_the_compiler_mockymock_started(tmp_path):
    """A child mockymock starts in its own session (as cobc and the test
    binary do) must die with the suite that timed out."""
    import os
    import sys
    import time

    from mockymock.runner import jobs

    script = tmp_path / "fake.py"
    script.write_text(FAKE_MOCKYMOCK)
    pid_file = tmp_path / "child.pid"
    step = jobs._run_step_timed(
        [sys.executable, str(script)], [str(pid_file)], tmp_path, timeout=3
    )
    assert step.timed_out
    pid = int(pid_file.read_text())
    for _ in range(50):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.1)
    else:
        os.kill(pid, 9)
        raise AssertionError("the grandchild outlived the suite timeout")
