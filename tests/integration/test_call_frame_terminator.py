"""A STOP RUN deep in the program's own PERFORMs, under a case (2026-11-03).

DEEP's READ-ONE is PERFORMed by MAIN-LINE; at a premature end its AT END
GO TO NO-DATA falls into FINISH and its STOP RUN. No EXIT verb returns from
there to the test, so the driver runs each case's PERFORM inside a CALL of
its own entry, and the STOP RUN becomes a GOBACK out of that CALL
(`TerminatorPlan.exit_kind` "RETURN"): the case ends where the program
would, and the next case starts clean."""

from pathlib import Path

from mockymock.cli.main import main
from tests.integration._docker import requires_docker

FIXTURES = Path(__file__).parent.parent / "fixtures" / "terminators"


def _copy(tmp_path: Path, cut: str | None = None) -> list[str]:
    (tmp_path / "DEEP.cbl").write_text((FIXTURES / "DEEP.cbl").read_text())
    (tmp_path / "DEEP.cut").write_text(cut or (FIXTURES / "DEEP.cut").read_text())
    return ["run", str(tmp_path / "DEEP.cbl"), "--cut", str(tmp_path / "DEEP.cut")]


@requires_docker
def test_a_deep_stop_run_ends_its_case_and_the_next_one_runs(tmp_path: Path, capsys):
    rc = main(_copy(tmp_path))
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "2 run, 0 failed" in out


@requires_docker
def test_the_case_really_stops_at_the_stop_run(tmp_path: Path, capsys):
    """The suite above checks what it claims: the first case ends with
    AFTER-READ 9 (NO-DATA ran, nothing after the first PERFORM READ-ONE)."""
    cut = (FIXTURES / "DEEP.cut").read_text()
    cut = cut.replace("EXPECT AFTER-READ TO BE 9", "EXPECT AFTER-READ TO BE 2", 1)
    assert main(_copy(tmp_path, cut)) == 1
    assert "expected AFTER-READ = 2, got 9" in capsys.readouterr().out
