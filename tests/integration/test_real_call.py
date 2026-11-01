"""USE REAL CALL end to end: the entry program and its real subprogram are
compiled into one binary, the subprogram's own boundaries answered by the
suite's mocks (docs/2026-11-01-real-call-integration-design.md)."""

from pathlib import Path

from mockymock.cli.main import main
from tests.integration._docker import requires_docker

EXAMPLE_DIR = Path(__file__).parent.parent.parent / "examples" / "paymod"


def _copy_example(tmp_path: Path) -> None:
    for name in ("PAYMAIN.cbl", "PAYCALC.cbl", "PAYMAIN.cut"):
        (tmp_path / name).write_text((EXAMPLE_DIR / name).read_text())


@requires_docker
def test_committed_paymod_example_passes(capsys):
    exit_code = main(
        [
            "run",
            str(EXAMPLE_DIR / "PAYMAIN.cbl"),
            "--cut",
            str(EXAMPLE_DIR / "PAYMAIN.cut"),
        ]
    )
    out = capsys.readouterr().out
    assert exit_code == 0, out
    assert "2 run, 0 failed" in out


@requires_docker
def test_a_linkage_mismatch_fails_the_suite(tmp_path: Path, capsys):
    """The class of bug a unit suite cannot see: the subprogram reads its
    LINKAGE with another layout than the caller passes."""
    _copy_example(tmp_path)
    sub = tmp_path / "PAYCALC.cbl"
    sub.write_text(
        sub.read_text().replace(
            "05  LK-HOURS        PIC 9(3).", "05  LK-HOURS        PIC 9(2)."
        )
    )
    exit_code = main(
        ["run", str(tmp_path / "PAYMAIN.cbl"), "--cut", str(tmp_path / "PAYMAIN.cut")]
    )
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "[FAIL] prices two employees through the real PAYCALC" in out


@requires_docker
def test_each_case_gets_a_fresh_subprogram(tmp_path: Path, capsys):
    (tmp_path / "MAINP.cbl").write_text(
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. MAINP.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01  WS-N                PIC 9(3) VALUE 0.\n"
        "       PROCEDURE DIVISION.\n"
        "       0000-MAIN.\n"
        '           CALL "COUNTER" USING WS-N\n'
        "           GOBACK.\n"
    )
    (tmp_path / "COUNTER.cbl").write_text(
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. COUNTER.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01  WS-CALLS            PIC 9(3) VALUE 0.\n"
        "       LINKAGE SECTION.\n"
        "       01  LK-N                PIC 9(3).\n"
        "       PROCEDURE DIVISION USING LK-N.\n"
        "       0000-COUNT.\n"
        "           ADD 1 TO WS-CALLS\n"
        "           MOVE WS-CALLS TO LK-N\n"
        "           GOBACK.\n"
    )
    (tmp_path / "MAINP.cut").write_text(
        'TESTSUITE "fresh state"\n'
        "BEFORE-EACH\n"
        '    USE REAL CALL "COUNTER" FROM "COUNTER.cbl"\n'
        "END-BEFORE\n"
        'TESTCASE "first"\n'
        "    PERFORM 0000-MAIN\n"
        "    EXPECT WS-N TO BE 1\n"
        'TESTCASE "second starts from VALUE clauses again"\n'
        "    PERFORM 0000-MAIN\n"
        "    EXPECT WS-N TO BE 1\n"
        '    VERIFY CALL "COUNTER" WAS CALLED ONCE\n'
    )
    exit_code = main(
        ["run", str(tmp_path / "MAINP.cbl"), "--cut", str(tmp_path / "MAINP.cut")]
    )
    out = capsys.readouterr().out
    assert exit_code == 0, out


@requires_docker
def test_generate_real_writes_a_suite_that_runs(tmp_path: Path, capsys):
    _copy_example(tmp_path)
    cut = tmp_path / "generated.cut"
    assert (
        main(
            [
                "generate",
                str(tmp_path / "PAYMAIN.cbl"),
                "--real",
                str(tmp_path / "PAYCALC.cbl"),
                "--seed",
                "7",
                "-o",
                str(cut),
            ]
        )
        == 0
    )
    assert 'USE REAL CALL "PAYCALC" FROM "PAYCALC.cbl"' in cut.read_text()
    capsys.readouterr()
    exit_code = main(["run", str(tmp_path / "PAYMAIN.cbl"), "--cut", str(cut)])
    assert exit_code == 0, capsys.readouterr().out
