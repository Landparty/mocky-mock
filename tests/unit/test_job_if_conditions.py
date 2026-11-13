"""`mockymock job` IF conditions: the 2026-11-11 bug hunt (ABENDCC after an
abend, `= TRUE` / `= FALSE` on ABEND and RUN) and the fail-closed guard for
a step that codes `COND=` inside an IF/THEN/ELSE, whose IF cobol-parser
drops (upstream issue, still present in cobol-parser 3.6.0)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import cobolparser.jcl as cj
import pytest

from mockymock.jobstream.conditions import (
    ConditionError,
    if_blocks,
    inside,
    step_runs,
)
from mockymock.jobstream.runner import JobOptions, run_job_stream

# -- ABENDCC (regression: 2026-11-11 bug hunt, finding 1) --------------------


@pytest.mark.parametrize("condition", ["(S1.ABENDCC = S0C4)", "(ABENDCC = U0100)"])
def test_abendcc_after_an_abend_is_a_gap_not_a_silent_skip(condition):
    with pytest.raises(ConditionError, match="abend codes"):
        step_runs(condition, {"S1": None}, True)


def test_abendcc_of_a_step_that_did_not_abend_is_false():
    assert step_runs("(S1.ABENDCC = S0C4)", {"S1": 0}, False) is False
    assert step_runs("(ABENDCC = S0C4)", {"S1": 0}, False) is False


def test_abendcc_of_the_step_that_abended_is_a_gap_even_if_another_ran():
    with pytest.raises(ConditionError, match="abend codes"):
        step_runs("(S2.ABENDCC = S0C4)", {"S1": 0, "S2": None}, True)


def test_abendcc_ne_is_not_guessed():
    with pytest.raises(ConditionError):
        step_runs("(S1.ABENDCC NE S0C4)", {"S1": 0}, False)


# -- = TRUE / = FALSE (regression: 2026-11-11 bug hunt, finding 2) ------------


@pytest.mark.parametrize(
    ("condition", "rcs", "abended", "expected"),
    [
        ("(S1.ABEND = TRUE)", {"S1": None}, True, True),
        ("(S1.ABEND = FALSE)", {"S1": None}, True, False),
        ("(S1.ABEND EQ FALSE)", {"S1": 0}, False, True),
        ("(ABEND = TRUE)", {"S1": None}, True, True),
        ("(ABEND = FALSE)", {"S1": 0}, False, True),
        ("(S1.RUN = TRUE)", {"S1": 0}, False, True),
        ("(S1.RUN = FALSE)", {"S1": 0}, False, False),
        ("(S1.RUN = FALSE AND S1.RC = 0)", {"S1": 0}, False, False),
    ],
)
def test_true_false_comparisons(condition, rcs, abended, expected):
    assert step_runs(condition, rcs, abended) is expected


def test_run_false_of_a_bypassed_step():
    assert step_runs("(S1.RUN = FALSE)", {}, False, bypassed={"S1"}) is True


def test_true_false_with_another_operator_says_so():
    with pytest.raises(ConditionError, match="= TRUE or = FALSE"):
        step_runs("(S1.ABEND > TRUE)", {"S1": 0}, False)


def test_run_on_an_ambiguous_name_is_not_false():
    with pytest.raises(ConditionError, match="ambiguous"):
        step_runs("(PS1.RUN)", {"A.PS1": 0, "B.PS1": 0}, False)


# -- COND= inside IF/THEN/ELSE ------------------------------------------------


def test_if_blocks_nest_and_skip_comments():
    text = "\n".join(
        [
            "//J JOB",
            "//  IF (S1.RC = 0) THEN",  # 2
            "//*  IF (X) THEN",
            "//I2 IF (S2.RC = 0) THEN",  # 4
            "//S3 EXEC PGM=IEFBR14",
            "//  ENDIF",  # 6
            "//  ELSE",
            "//  ENDIF",  # 8
            "//S9 EXEC PGM=IEFBR14",
        ]
    )
    assert sorted(if_blocks(text)) == [(2, 8), (4, 6)]
    assert inside(if_blocks(text), 5)
    assert not inside(if_blocks(text), 9)


_DECK = """\
//JOB1  JOB (ACCT),'X'
//MYP   PROC
//PS1   EXEC PGM=IEFBR14
//      IF (PS1.RC = 0) THEN
//PS2   EXEC PGM=IEFBR14,COND=(8,LT)
//      ENDIF
//      PEND
//S1    EXEC PGM=IEFBR14
//      IF (S1.RC = 0) THEN
//S2    EXEC PGM=IEFBR14,COND=(8,LT)
//      ELSE
//S3    EXEC PGM=IEFBR14,COND=(8,LT)
//      ENDIF
//A     EXEC MYP
//      IF (S1.RC = 0) THEN
//B     EXEC LIBP
//      ENDIF
//C     EXEC LIBP
"""

_LIBP = """\
//LIBP  PROC
//L1    EXEC PGM=IEFBR14
//L2    EXEC PGM=IEFBR14,COND=(4,LT)
//      IF (L1.RC = 0) THEN
//L3    EXEC PGM=IEFBR14,COND=(4,LT)
//      ENDIF
"""

# What cobol-parser 3.6.0's parse_jcl gives for _DECK (checked against the
# real parser with jcl-parser 2.3.1): COND= replaces the IF on S2, S3,
# A.PS2, B.L2, B.L3 and C.L3.
_STEPS = [
    ("S1", "IEFBR14", None, 8, None),
    ("S2", "IEFBR14", None, 10, "(8,LT)"),
    ("S3", "IEFBR14", None, 12, "(8,LT)"),
    ("A", None, "MYP", 14, None),
    ("A.PS1", "IEFBR14", "MYP", 3, None),
    ("A.PS2", "IEFBR14", "MYP", 5, "(8,LT)"),
    ("B", None, "LIBP", 16, "(S1.RC = 0)"),
    ("B.L1", "IEFBR14", "LIBP", 2, "(S1.RC = 0)"),
    ("B.L2", "IEFBR14", "LIBP", 3, "(4,LT)"),
    ("B.L3", "IEFBR14", "LIBP", 5, "(4,LT)"),
    ("C", None, "LIBP", 18, None),
    ("C.L1", "IEFBR14", "LIBP", 2, None),
    ("C.L2", "IEFBR14", "LIBP", 3, "(4,LT)"),
    ("C.L3", "IEFBR14", "LIBP", 5, "(4,LT)"),
]


def _check(tmp_path: Path, monkeypatch, only: list[str]):
    """Run the job with just the named steps (plus the PROC invocations)."""
    procs = tmp_path / "procs"
    procs.mkdir()
    (procs / "LIBP.prc").write_text(_LIBP)
    (tmp_path / "j.jcl").write_text(_DECK)
    data = tmp_path / "data"
    data.mkdir()
    steps = [
        SimpleNamespace(
            name=name,
            program=program,
            procedure=procedure,
            line=line,
            condition=condition,
            dd_statements=[],
        )
        for name, program, procedure, line, condition in _STEPS
        if program is None or name in only
    ]
    monkeypatch.setattr(
        cj,
        "parse_jcl",
        lambda *a, **k: SimpleNamespace(
            errors=[], jobs=[SimpleNamespace(name="JOB1", steps=steps)], unresolved=[]
        ),
    )
    return run_job_stream(
        JobOptions(
            jcl=tmp_path / "j.jcl",
            sources=[],
            data=data,
            proc_paths=[procs],
            work_dir=tmp_path,
        )
    )


@pytest.mark.parametrize("step", ["S2", "S3", "A.PS2", "B.L2", "B.L3", "C.L3"])
def test_cond_inside_an_if_is_a_gap(tmp_path, monkeypatch, step):
    report = _check(tmp_path, monkeypatch, ["S1", step])
    assert report["verdict"] == "incomplete"
    result = report["steps"][-1]
    assert (result["name"], result["status"]) == (step, "gap")
    assert "inside an IF" in result["detail"]


def test_cond_outside_any_if_still_runs(tmp_path, monkeypatch):
    report = _check(tmp_path, monkeypatch, ["S1", "A.PS1", "B.L1", "C.L1", "C.L2"])
    assert [s["status"] for s in report["steps"]] == ["ran"] * 5
    assert report["verdict"] == "passed"


def test_fake_steps_match_the_real_parser(tmp_path):
    pytest.importorskip("jclparser")
    procs = tmp_path / "procs"
    procs.mkdir()
    (procs / "LIBP.prc").write_text(_LIBP)
    parsed = cj.parse_jcl(_DECK, filename="j.jcl", proc_paths=[str(procs)])
    assert [
        (s.name, s.program, s.procedure, s.line, s.condition)
        for s in parsed.jobs[0].steps
    ] == _STEPS
