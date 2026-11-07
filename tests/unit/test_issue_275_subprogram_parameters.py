"""Issue #275: a CALLed subprogram's PROCEDURE DIVISION USING items are its
whole interface. The scaffold sets them and stubs what the program hands
back, and a suite that asserts nothing is no longer reported as done."""

import pytest

import mockymock.cli.commands.init as init_mod
import mockymock.cli.doctor as doctor_mod
from mockymock.cli.checks import cases_asserting_nothing
from mockymock.cli.main import main
from mockymock.dsl.entry_parameters import add_entry_parameters
from mockymock.runtime import status

CALCSUB = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CALCSUB.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-RATE  PIC V999 VALUE .050.
       LINKAGE SECTION.
       01  LK-PARMS.
           05  LK-AMOUNT  PIC 9(7)V99.
           05  LK-TAX     PIC 9(7)V99.
           05  LK-RC      PIC 99.
       PROCEDURE DIVISION USING LK-PARMS.
       0000-MAIN.
           IF LK-AMOUNT = 0
               MOVE 8 TO LK-RC
           ELSE
               COMPUTE LK-TAX = LK-AMOUNT * WS-RATE
               MOVE 0 TO LK-RC
           END-IF
           GOBACK.
"""


@pytest.fixture
def calcsub(tmp_path, monkeypatch):
    (tmp_path / "CALCSUB.cbl").write_text(CALCSUB, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_generate_sets_the_parameters_and_stubs_the_outputs(calcsub, capsys):
    assert main(["generate", "CALCSUB.cbl", "-o", "CALCSUB.cut"]) == 0
    text = (calcsub / "CALCSUB.cut").read_text(encoding="utf-8")
    assert "*> what the caller of CALCSUB passes (USING)" in text
    for field in ("LK-AMOUNT", "LK-TAX", "LK-RC"):
        assert f" TO {field}\n" in text
    assert text.index("MOVE ") < text.index("PERFORM 0000-MAIN")
    # LK-AMOUNT is only read: an input, not something to assert on.
    assert "*> STUB EXPECT LK-TAX" in text
    assert "*> STUB EXPECT LK-RC" in text
    assert "STUB EXPECT LK-AMOUNT" not in text
    assert "assert nothing" not in capsys.readouterr().out
    assert main(["lint", "CALCSUB.cbl", "--cut", "CALCSUB.cut"]) == 0


def test_fallback_fills_every_scenario_once(calcsub):
    bundle = {
        "seed": 3,
        "scenarios": [
            {"name": "happy path", "entry": "0000-MAIN", "expectations": []},
            {"name": "other", "entry": "0000-MAIN", "expectations": []},
        ],
    }
    out = add_entry_parameters(bundle, str(calcsub / "CALCSUB.cbl"), None)
    for scenario in out["scenarios"]:
        params = scenario["entry_parameters"]
        assert (params["category"], params["key"]) == ("ENTRY", "CALCSUB")
        assert set(params["sequence"][0]) == {"LK-AMOUNT", "LK-TAX", "LK-RC"}
        assert [e["ref"] for e in scenario["expectations"]] == [
            "LK-PARMS.LK-TAX",
            "LK-PARMS.LK-RC",
        ]
    # Already filled (a newer cobol-parser does it itself): left alone.
    again = add_entry_parameters(out, str(calcsub / "CALCSUB.cbl"), None)
    assert len(again["scenarios"][0]["expectations"]) == 2


def test_cases_asserting_nothing_counts_stubs_only_when_asked():
    text = (
        'TESTSUITE "s"\n'
        'TESTCASE "stubbed"\n    PERFORM P\n    *> STUB EXPECT X\n\n'
        'TESTCASE "bare"\n    PERFORM P\n\n'
        'TESTCASE "asserted"\n    PERFORM P\n    EXPECT X TO BE 1\n'
    )
    assert cases_asserting_nothing(text, stubs_count=True) == [
        '.cut line 6: TESTCASE "bare"'
    ]
    assert cases_asserting_nothing(text, stubs_count=False) == [
        '.cut line 2: TESTCASE "stubbed"',
        '.cut line 6: TESTCASE "bare"',
    ]


def _docker_up():
    return doctor_mod.DoctorReport(
        toolchain=status.ToolchainStatus(
            ready=True,
            checked_at="2026-10-21T00:00:00+00:00",
            image="img",
            container="ctr",
            cobc_version="cobc 3.2.0",
            checks=(status.Check("daemon", "Docker daemon", status.OK, "ok"),),
        ),
        extra_checks=(),
        ready=True,
    )


def test_init_fails_when_recording_left_nothing_asserted(calcsub, capsys, monkeypatch):
    # A recording run that filled no STUB EXPECT (simulated: _cmd_run does
    # nothing) leaves a suite that passes whatever the program does.
    monkeypatch.setattr(doctor_mod, "gather_full_status", _docker_up)
    monkeypatch.setattr(init_mod, "_cmd_run", lambda args: 0)
    assert main(["init", "CALCSUB.cbl", "-o", "CALCSUB.cut"]) == 1
    out = capsys.readouterr().out
    assert "none of its test cases asserts anything" in out
    assert "next, run" not in out


def test_init_succeeds_once_recording_filled_the_stubs(calcsub, capsys, monkeypatch):
    def fake_record(args):
        cut = calcsub / "CALCSUB.cut"
        text = cut.read_text(encoding="utf-8")
        cut.write_text(
            text.replace("*> STUB EXPECT LK-RC", "EXPECT LK-RC TO BE 0"),
            encoding="utf-8",
        )
        return 0

    monkeypatch.setattr(doctor_mod, "gather_full_status", _docker_up)
    monkeypatch.setattr(init_mod, "_cmd_run", fake_record)
    assert main(["init", "CALCSUB.cbl", "-o", "CALCSUB.cut"]) == 0
    assert "next, run" in capsys.readouterr().out


def test_lint_and_run_say_why_a_suite_without_testcases_fails(calcsub, capsys):
    (calcsub / "CALCSUB.cut").write_text('TESTSUITE "empty"\n', encoding="utf-8")
    assert main(["lint", "CALCSUB.cbl", "--cut", "CALCSUB.cut"]) == 1
    assert "has no TESTCASE" in capsys.readouterr().out
    assert main(["run", "CALCSUB.cbl", "--cut", "CALCSUB.cut"]) == 1
    assert "has no TESTCASE" in capsys.readouterr().out


PTRSUB = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PTRSUB.
       DATA DIVISION.
       LINKAGE SECTION.
       01  LK-PARMS.
           05  LK-ADDR    USAGE POINTER.
           05  LK-RC      PIC 99.
       PROCEDURE DIVISION USING LK-PARMS.
       0000-MAIN.
           IF LK-ADDR = NULL
               MOVE 8 TO LK-RC
           ELSE
               MOVE 0 TO LK-RC
           END-IF
           GOBACK.
"""


def test_pointer_parameter_is_not_set_in_case_setup(tmp_path, monkeypatch):
    """TPMSA000: a POINTER USING item was scaffolded as `SET ... TO NULL`
    among the case's setup lines, which take only MOVE, so the .cut file
    `generate` wrote was refused by its own parser."""
    (tmp_path / "PTRSUB.cbl").write_text(PTRSUB, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert main(["generate", "PTRSUB.cbl", "-o", "PTRSUB.cut"]) == 0
    text = (tmp_path / "PTRSUB.cut").read_text(encoding="utf-8")
    assert "SET LK-ADDR" not in text
    assert "*> LK-ADDR (POINTER) starts NULL" in text
    assert " TO LK-RC\n" in text
    assert main(["lint", "PTRSUB.cbl", "--cut", "PTRSUB.cut"]) == 0
