"""Nested and stacked programs (2026-11-03, NIST IC2xx): the outermost
unit is tested, a CALL to the program nested in it is mocked like any
CALL, and the nested program still compiles after the driver's trap."""

from pathlib import Path

from mockymock.cli.main import main
from tests.integration._docker import requires_docker

FIXTURES = Path(__file__).parent.parent / "fixtures" / "nested"


def _args(tmp_path: Path, cut: str | None = None) -> list[str]:
    (tmp_path / "NESTCALL.cbl").write_text((FIXTURES / "NESTCALL.cbl").read_text())
    (tmp_path / "NESTCALL.cut").write_text(
        cut or (FIXTURES / "NESTCALL.cut").read_text()
    )
    return [
        "run",
        str(tmp_path / "NESTCALL.cbl"),
        "--cut",
        str(tmp_path / "NESTCALL.cut"),
    ]


@requires_docker
def test_the_outer_program_runs_with_its_nested_call_mocked(tmp_path: Path, capsys):
    rc = main(_args(tmp_path))
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "3 run, 0 failed" in out


@requires_docker
def test_the_mock_answers_the_call_not_the_nested_program(tmp_path: Path, capsys):
    """The nested INNER would set WS-RC to 8: the first case's mock sets 0."""
    cut = (FIXTURES / "NESTCALL.cut").read_text()
    cut = cut.replace('EXPECT WS-STEP TO BE "DONE"', 'EXPECT WS-STEP TO BE "FAIL"', 1)
    assert main(_args(tmp_path, cut)) == 1
    assert 'expected WS-STEP = "FAIL"' in capsys.readouterr().out
