"""Issue #350: `EXPECT <numeric-edited field> TO BE <unquoted number>`
compares the de-edited value; a quoted string stays byte-exact."""

from pathlib import Path

from mockymock.cli.main import main
from tests.integration._docker import requires_docker

FIXTURES = Path(__file__).parent / "fixtures"
CBL = FIXTURES / "numeric_edited.cbl"
CUT = FIXTURES / "numeric_edited.cut"


@requires_docker
def test_numeric_edited_fields_compare_by_value_or_by_bytes():
    assert main(["run", str(CBL), "--cut", str(CUT)]) == 0


@requires_docker
def test_a_wrong_value_fails_and_shows_the_edited_text(tmp_path: Path, capsys):
    cut = tmp_path / "numeric_edited.cut"
    cut.write_text(CUT.read_text().replace("TO BE 100.00", "TO BE 100.01"))
    assert main(["run", str(CBL), "--cut", str(cut)]) == 1
    out = capsys.readouterr().out
    assert "expected WS-DET-BAL = 100.01" in out
    assert "100.00" in out
