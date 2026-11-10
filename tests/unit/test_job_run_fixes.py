"""`mockymock job` fixes from the 2026-11-10 bug hunt: OPEN EXTEND staging and
DISP=MOD, unqualified step names inside a PROC, the temporary-dataset default
disposition, and PROVIDER values in multi-call step MOVEs."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from mockymock.dsl.parser import CutParseError, parse_cut
from mockymock.jobstream.conditions import ConditionError, step_runs
from mockymock.jobstream.runner import JobOptions, JobRun, _disposition

_APPENDER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. APPENDR.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT LOGF ASSIGN TO LOGDD
               ORGANIZATION IS SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD  LOGF.
       01  LOG-REC PIC X(20).
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN EXTEND LOGF
           MOVE "NEW ENTRY" TO LOG-REC
           WRITE LOG-REC
           CLOSE LOGF
           GOBACK.
"""


def _dd(name: str, dataset: str | None, disposition: str | None = None):
    dd = SimpleNamespace(
        name=name,
        dataset=dataset,
        disposition=disposition,
        is_dummy=False,
        is_instream=False,
        instream_lines=None,
        sysout=None,
        record_length=None,
    )
    dd.flatten = lambda: [dd]
    return dd


def _job(tmp_path: Path, inputs: dict[str, bytes]) -> JobRun:
    data = tmp_path / "data"
    data.mkdir()
    for name, content in inputs.items():
        (data / name).write_bytes(content)
    run = JobRun(
        JobOptions(jcl=tmp_path / "j.jcl", sources=[], data=data, work_dir=tmp_path)
    )
    run._load_inputs()
    return run


def test_open_extend_marks_the_plan(tmp_path: Path):
    from cobolparser import parse_cobol

    from mockymock.analysis.mock_surface import analyze
    from mockymock.dsl.real_file_suite import plan_real_files

    ast = parse_cobol(_APPENDER, filename="a.cbl").ast
    (plan,), _ = plan_real_files(ast, analyze(ast))
    assert (plan.reads, plan.writes, plan.opens_existing) == (False, True, True)


@pytest.mark.parametrize("disposition", ["OLD", "SHR", "MOD"])
def test_extend_file_is_staged_with_its_existing_records(tmp_path, disposition):
    source = tmp_path / "APPENDR.cbl"
    source.write_text(_APPENDER, encoding="utf-8")
    run = _job(tmp_path, {"LOG.DATA": b"OLD ENTRY           "})
    bindings = {"LOGDD": [_dd("LOGDD", "LOG.DATA", disposition)]}
    files, problem = run._step_files("S1", source, bindings)
    assert problem is None
    (spec,) = files
    assert spec.opens_existing
    assert spec.source is not None
    assert spec.source.read_bytes() == b"OLD ENTRY           "


def test_disp_mod_does_not_prepend_records_the_step_already_holds(tmp_path):
    run = _job(tmp_path, {"LOG.DATA": b"OLD "})
    cards = [_dd("LOGDD", "LOG.DATA", "MOD")]
    run._write_output("S1", "LOGDD", cards, b"OLD NEW ", holds_existing=True)
    assert run.datasets["LOG.DATA"].read_bytes() == b"OLD NEW "
    # OPEN OUTPUT on DISP=MOD still appends to what was there.
    run._write_output("S2", "LOGDD", cards, b"MORE")
    assert run.datasets["LOG.DATA"].read_bytes() == b"OLD NEW MORE"


@pytest.mark.parametrize(
    "condition, rcs, step, runs",
    [
        # A job-level step shares the PROC step's name: the PROC's own wins.
        ("(4,LT,PS1)", {"PS1": 8, "A.PS1": 0}, "A.PS2", True),
        ("(PS1.RC = 0)", {"PS1": 8, "A.PS1": 0}, "A.PS2", True),
        # The PROC called twice: each call reads its own PS1.
        ("(4,LT,PS1)", {"A.PS1": 0, "B.PS1": 8}, "B.PS2", False),
        ("(4,LT,PS1)", {"A.PS1": 8, "B.PS1": 0}, "B.PS2", True),
        # A job-level step outside any PROC still finds a job-level name.
        ("(4,LT,S1)", {"S1": 8}, "S2", False),
        # A qualified name is taken as written.
        ("(4,LT,A.PS1)", {"A.PS1": 8, "B.PS1": 0}, "B.PS2", False),
    ],
)
def test_unqualified_names_resolve_inside_the_procedure(condition, rcs, step, runs):
    assert step_runs(condition, rcs, False, step=step) is runs


def test_an_ambiguous_step_name_says_so():
    with pytest.raises(ConditionError, match="ambiguous"):
        step_runs("(4,LT,PS1)", {"A.PS1": 0, "B.PS1": 0}, False, step="S9")


def test_own_bypassed_procedure_step_is_ignored():
    assert step_runs(
        "(4,LT,PS1)", {"A.PS1": 8}, False, bypassed={"B.PS1"}, step="B.PS2"
    )


@pytest.mark.parametrize(
    "disposition, normal",
    [
        ("SHR", "PASS"),
        ("OLD", "PASS"),
        ("(NEW,PASS)", "PASS"),
        ("NEW", "DELETE"),
        (None, "DELETE"),
        ("(OLD,DELETE)", "DELETE"),
    ],
)
def test_temporary_default_dispositions(disposition, normal):
    assert (
        _disposition(SimpleNamespace(disposition=disposition, dataset="&&T"))[1]
        == normal
    )


def test_passed_temporary_survives_a_bare_shr_reader(tmp_path):
    run = _job(tmp_path, {})
    run._write_output("S1", "OUT", [_dd("OUT", "&&T", "(NEW,PASS)")], b"X\n")
    reader = SimpleNamespace(dd_statements=[_dd("IN", "&&T", "SHR")])
    run._apply_dispositions(reader, True)
    staged, why = run._input_file("S3", "IN", [_dd("IN", "&&T", "SHR")], True)
    assert why is None and staged is not None


def test_provider_period_in_a_step_move_is_refused():
    text = """TESTSUITE "S"
PROVIDER D
    HEADER V
    ROW 5.
TESTCASE "c" USING PROVIDER D
    MOVE {V} TO WS-A
    PERFORM P1
    PERFORM P2
    EXPECT WS-A TO BE 1
"""
    with pytest.raises(CutParseError, match="line 4: MOVE value '5.'"):
        parse_cut(text)
