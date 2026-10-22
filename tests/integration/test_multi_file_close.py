"""Issue #348: `CLOSE CHKFILE STOPPAY CHKRPT` with one MOCK per file. Each
file's directive answers the one statement -- its own FILE-STATUS applies
and its own tally counts it -- so every file can be VERIFY'd."""

from pathlib import Path

from mockymock.cli.main import main
from tests.integration._docker import requires_docker

FIXTURES = Path(__file__).parent / "fixtures"
CBL = FIXTURES / "multi_file_close.cbl"
CUT = FIXTURES / "multi_file_close.cut"


@requires_docker
def test_every_file_of_a_multi_file_close_is_mocked_and_verified():
    assert main(["run", str(CBL), "--cut", str(CUT)]) == 0


@requires_docker
def test_a_wrong_verify_count_on_one_file_fails(tmp_path: Path, capsys):
    cut = tmp_path / "multi_file_close.cut"
    cut.write_text(
        CUT.read_text().replace(
            "VERIFY CLOSE CHKRPT WAS CALLED ONCE",
            "VERIFY CLOSE CHKRPT WAS CALLED 2 TIMES",
        )
    )
    assert main(["run", str(CBL), "--cut", str(cut)]) == 1
    assert "VERIFY CLOSE CHKRPT WAS CALLED 2 TIMES, got 1" in capsys.readouterr().out
