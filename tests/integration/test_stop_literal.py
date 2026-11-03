"""STOP <literal> under a test (2026-11-03, NIST NC302M/OBNC1M): the
operator answers at once, and the program goes on. The fixture's SECURITY
comment entry holds division headers, as OBNC1M's does."""

from pathlib import Path

from mockymock.cli.main import main
from tests.integration._docker import requires_docker

FIXTURES = Path(__file__).parent.parent / "fixtures" / "stop_literal"


@requires_docker
def test_a_case_runs_through_a_stop_literal(tmp_path: Path, capsys):
    for name in ("STOPLIT.cbl", "STOPLIT.cut"):
        (tmp_path / name).write_text((FIXTURES / name).read_text())
    rc = main(
        ["run", str(tmp_path / "STOPLIT.cbl"), "--cut", str(tmp_path / "STOPLIT.cut")]
    )
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "1 run, 0 failed" in out
