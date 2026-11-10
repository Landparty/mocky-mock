"""Numeric CLI flags are range-checked up front: a NaN, infinite,
negative or out-of-range threshold, poll interval or timeout is a
usage error, not a crash after the whole run.

Regression: bug hunt of 2026-11-05 on the .cut suite language and the CLI
(executed counterpart: tests/integration/test_cut_suite_language.py).
`--coverage-fail-under nan` never failed, `mutate --fail-under nan`
crashed after the whole run, 150 was accepted; the runner took a
negative `--poll-interval` (crash on the first idle sleep) or 0."""

import pytest

from mockymock.cli.main import main

# --- 3. ambiguous / wrongly qualified names ---------------------------------

TWICE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TWICE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  CUST-REC.
           05  CUST-ID        PIC 9(5).
               88 CUST-OK     VALUE 1.
       01  OUTER.
           05  CUST-ID        PIC 9(5).
               88 CUST-OK     VALUE 1.
           05  ONLY-HERE      PIC 9.
       01  WS-B               PIC 9(5).
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 1 TO CUST-ID OF CUST-REC
           GOBACK.
"""


# --- 4. percent and seconds flags -------------------------------------------


@pytest.mark.parametrize(
    "argv",
    [
        ["run", "P.cbl", "--coverage-fail-under", "nan"],
        ["run", "P.cbl", "--coverage-fail-under", "150"],
        ["run", "P.cbl", "--coverage-fail-under", "-1"],
        ["mutate", "P.cbl", "--fail-under", "nan"],
        ["mutate", "P.cbl", "--fail-under", "inf"],
        ["runner", "--poll-interval", "-1"],
        ["runner", "--poll-interval", "0"],
        ["runner", "--suite-timeout", "nan"],
    ],
)
def test_out_of_range_numeric_flags_are_refused_up_front(argv, capsys):
    assert main(argv) == 2
    err = capsys.readouterr().err
    assert "must be" in err and argv[-1] in err


def test_a_nan_report_mutation_threshold_is_refused(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "P.cbl").write_text(TWICE)
    (tmp_path / "P.cut").write_text(
        'TESTSUITE "s"\nTESTCASE "c"\n    PERFORM MAIN-PARA\n'
    )
    assert main(["report", "P.cbl", "--mutation-threshold", "nan"]) == 1
    assert "--mutation-threshold must be between 0 and 100" in capsys.readouterr().out
