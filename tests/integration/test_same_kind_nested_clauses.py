"""End-to-end proof for a statement nested in a clause body of its own
kind: a READ in a mocked READ's NOT AT END, and a CALL in a mocked CALL's
ON EXCEPTION, each closed by its own END-<verb>. A terminator closes the
nearest statement it has not closed yet, so the extent of both is certain;
before, both outer sites were refused ("has a statement of its own kind
inside its clause bodies")."""

from pathlib import Path

from mockymock.cli.main import main
from tests.integration._docker import requires_docker

FIXTURES = Path(__file__).parent / "fixtures"
PROGRAM = FIXTURES / "same_kind_nested_clauses.cbl"
CUT = FIXTURES / "same_kind_nested_clauses.cut"


@requires_docker
def test_same_kind_nested_clauses_run_passes():
    assert main(["run", str(PROGRAM), "--cut", str(CUT)]) == 0


@requires_docker
def test_same_kind_nested_clauses_fail_when_the_inner_mock_disagrees(
    tmp_path: Path,
):
    # The inner CALL runs only from the outer CALL's lifted ON EXCEPTION.
    broken = tmp_path / "same_kind_nested_clauses.cut"
    broken.write_text(
        CUT.read_text().replace(
            'VERIFY CALL "ERRLOG" WAS CALLED ONCE',
            'VERIFY CALL "ERRLOG" WAS CALLED 0 TIMES',
        )
    )
    assert main(["run", str(PROGRAM), "--cut", str(broken)]) == 1


@requires_docker
def test_generated_scaffold_runs(tmp_path: Path):
    out = tmp_path / "generated.cut"
    assert main(["generate", str(PROGRAM), "-o", str(out)]) == 0
    assert main(["run", str(PROGRAM), "--cut", str(out)]) == 0
