"""USE AFTER EXCEPTION procedures under mocks (2026-11-03, NIST CCVS85).

A mocked file statement whose outcome is an exception runs the USE
procedure that applies, as the runtime runs it after a real one: a READ
with AT END handles its own end and a bare one runs the procedure, a
failed OPEN INPUT runs the INPUT procedure, an OUTPUT file with none runs
nothing, and a USE naming the file wins over one naming its mode."""

from pathlib import Path

from mockymock.cli.main import main
from tests.integration._docker import requires_docker

FIXTURES = Path(__file__).parent.parent / "fixtures" / "declaratives"


@requires_docker
def test_mocked_exceptions_run_the_use_procedure(tmp_path: Path, capsys):
    for name in ("DECL.cbl", "DECL.cut"):
        (tmp_path / name).write_text((FIXTURES / name).read_text())
    rc = main(["run", str(tmp_path / "DECL.cbl"), "--cut", str(tmp_path / "DECL.cut")])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "4 run, 0 failed" in out


@requires_docker
def test_a_bare_read_at_end_does_run_the_procedure(tmp_path: Path, capsys):
    """The suite above would also pass if no USE procedure ever ran in its
    first case's place: this one says it did."""
    (tmp_path / "DECL.cbl").write_text((FIXTURES / "DECL.cbl").read_text())
    cut = (FIXTURES / "DECL.cut").read_text()
    (tmp_path / "DECL.cut").write_text(
        cut.replace("EXPECT INPUT-ERRORS TO BE 1", "EXPECT INPUT-ERRORS TO BE 0", 1)
    )
    assert (
        main(["run", str(tmp_path / "DECL.cbl"), "--cut", str(tmp_path / "DECL.cut")])
        == 1
    )
    assert "expected INPUT-ERRORS = 0, got 1" in capsys.readouterr().out
