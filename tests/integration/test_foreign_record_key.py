"""A SELECT whose RECORD KEY (and ALTERNATE RECORD KEY) is declared in
WORKING-STORAGE, outside the file's FD record, like CardDemo's CBEXPORT
and CBIMPORT: GnuCOBOL refused the spliced program ("'EXP-SEQ-NUM' is not
defined") before any test case ran. The file is mocked, so its keys are
never used; `splicer.file_keys` makes the SELECT compile."""

from pathlib import Path

from mockymock.cli.main import main
from tests.integration._docker import requires_docker

FIXTURES = Path(__file__).parent / "fixtures"
CBL = FIXTURES / "foreign_record_key.cbl"
CUT = FIXTURES / "foreign_record_key.cut"


@requires_docker
def test_a_file_keyed_outside_its_fd_compiles_and_runs(capsys):
    assert main(["run", str(CBL), "--cut", str(CUT)]) == 0
    out = capsys.readouterr().out
    assert "2 run, 0 failed" in out
    assert "is not defined" not in out
