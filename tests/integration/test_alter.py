"""ALTER under mocks (2026-11-03, NIST NC/SG/DB): the ALTER runs real,
and each case starts with the GO TOs as written."""

from pathlib import Path

from mockymock.cli.main import main
from tests.integration._docker import requires_docker

FIXTURES = Path(__file__).parent.parent / "fixtures" / "alter"


def _args(tmp_path: Path, cut: str | None = None) -> list[str]:
    (tmp_path / "ALT.cbl").write_text((FIXTURES / "ALT.cbl").read_text())
    (tmp_path / "ALT.cut").write_text(cut or (FIXTURES / "ALT.cut").read_text())
    return ["run", str(tmp_path / "ALT.cbl"), "--cut", str(tmp_path / "ALT.cut")]


@requires_docker
def test_an_alter_holds_for_its_case_only(tmp_path: Path, capsys):
    rc = main(_args(tmp_path))
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "2 run, 0 failed" in out


@requires_docker
def test_the_alter_really_changes_the_go_to(tmp_path: Path, capsys):
    cut = (FIXTURES / "ALT.cut").read_text()
    cut = cut.replace('EXPECT WS-PATH TO BE "B"', 'EXPECT WS-PATH TO BE "A"', 1)
    assert main(_args(tmp_path, cut)) == 1
    assert 'expected WS-PATH = "A"' in capsys.readouterr().out
