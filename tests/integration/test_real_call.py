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


ORDMOD_DIR = Path(__file__).parent.parent.parent / "examples" / "ordmod"


def _run_ordmod(directory: Path, capsys) -> tuple[int, str]:
    exit_code = main(
        [
            "run",
            str(directory / "ORDMAIN.cbl"),
            "--cut",
            str(directory / "ORDMAIN.cut"),
            "--copybook-path",
            str(directory),
        ]
    )
    return exit_code, capsys.readouterr().out


@requires_docker
def test_committed_ordmod_example_passes(capsys):
    """Three real subprograms, two of them with DB2, MQ and a file of their
    own, one CALLed by another real subprogram."""
    exit_code, out = _run_ordmod(ORDMOD_DIR, capsys)
    assert exit_code == 0, out
    assert "3 run, 0 failed" in out


@requires_docker
def test_ordmod_catches_a_logic_change_in_a_nested_subprogram(tmp_path: Path, capsys):
    for source in ORDMOD_DIR.iterdir():
        if source.is_file():
            (tmp_path / source.name).write_text(source.read_text())
    validate = tmp_path / "ORDVAL.cbl"
    validate.write_text(
        validate.read_text().replace(
            "WHEN LK-AMOUNT > WS-LIMIT", "WHEN LK-AMOUNT < WS-LIMIT"
        )
    )
    exit_code, out = _run_ordmod(tmp_path, capsys)
    assert exit_code == 1
    assert "expected WS-ACCEPTED = 2, got 1" in out


IMSMOD_DIR = Path(__file__).parent.parent.parent / "examples" / "imsmod"


def _imsmod_args(directory: Path, cut: Path) -> list[str]:
    return [
        "run",
        str(directory / "PRTINQ.cbl"),
        "--cut",
        str(cut),
        "--copybook-path",
        str(directory),
        "--timeout",
        "30",
    ]


@requires_docker
def test_committed_imsmod_example_passes(capsys):
    """An IMS MPP whose real subprograms read DB2 and a file."""
    exit_code = main(_imsmod_args(IMSMOD_DIR, IMSMOD_DIR / "PRTINQ.cut"))
    out = capsys.readouterr().out
    assert exit_code == 0, out
    assert "3 run, 0 failed" in out


@requires_docker
def test_imsmod_catches_a_linkage_mismatch_in_a_subprogram(tmp_path: Path, capsys):
    for source in IMSMOD_DIR.iterdir():
        if source.is_file():
            (tmp_path / source.name).write_text(source.read_text())
    stock = tmp_path / "PRTSTK.cbl"
    text = stock.read_text()
    assert "LK-ONHAND               PIC 9(7)." in text
    stock.write_text(
        text.replace(
            "LK-ONHAND               PIC 9(7).", "LK-ONHAND               PIC 9(5)."
        )
    )
    exit_code = main(_imsmod_args(tmp_path, tmp_path / "PRTINQ.cut"))
    assert exit_code == 1, capsys.readouterr().out


@requires_docker
def test_generated_imsmod_suite_ends_its_gu_loop(tmp_path: Path, capsys):
    """One MOCK CALL "CBLTDLI" answers the GU and the ISRT: the scaffold
    used to leave it a TODO and hang until --timeout; it now answers QC to
    the GU alone."""
    for source in IMSMOD_DIR.iterdir():
        if source.is_file():
            (tmp_path / source.name).write_text(source.read_text())
    cut = tmp_path / "generated.cut"
    assert (
        main(
            [
                "generate",
                str(tmp_path / "PRTINQ.cbl"),
                "--real",
                str(tmp_path / "PRTSTK.cbl"),
                "--real",
                str(tmp_path / "PRTRATE.cbl"),
                "--copybook-path",
                str(tmp_path),
                "-o",
                str(cut),
            ]
        )
        == 0
    )
    assert 'MOVE "QC" TO IOPCB(11:2)' in cut.read_text()
    capsys.readouterr()
    exit_code = main(_imsmod_args(tmp_path, cut))
    assert exit_code == 0, capsys.readouterr().out
