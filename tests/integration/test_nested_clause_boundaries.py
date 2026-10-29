"""End-to-end proof for boundaries nested in another boundary's clause
body: a CALL in a mocked READ's AT END (sharing the header's line), a CALL
in its NOT AT END, and a WRITE in that CALL's ON EXCEPTION -- three levels,
all mocked. Before, the READ was refused (UNLIFTABLE_CLAUSE_BODY) and the
inner sites had no span (UNSUPPORTED_NESTED_MOCK_TARGET). Now each inner
site is spliced into the lifted copy of the clause body that holds it,
compiled with GnuCOBOL and run for real."""

from pathlib import Path

from mockymock.cli.main import main
from tests.integration._docker import requires_docker

FIXTURES = Path(__file__).parent / "fixtures"
PROGRAM = FIXTURES / "nested_clause_boundaries.cbl"
CUT = FIXTURES / "nested_clause_boundaries.cut"


@requires_docker
def test_nested_clause_boundaries_run_passes():
    assert main(["run", str(PROGRAM), "--cut", str(CUT)]) == 0


@requires_docker
def test_nested_clause_boundaries_fail_when_the_inner_mock_disagrees(
    tmp_path: Path,
):
    # The second VALIDATE raises ON EXCEPTION, whose body WRITEs one
    # error record: claiming none fails, so the inner splice really runs.
    broken = tmp_path / "nested_clause_boundaries.cut"
    broken.write_text(
        CUT.read_text().replace(
            "VERIFY WRITE ERR-REC WAS CALLED ONCE",
            "VERIFY WRITE ERR-REC WAS CALLED 0 TIMES",
        )
    )
    assert main(["run", str(PROGRAM), "--cut", str(broken)]) == 1


@requires_docker
def test_generated_scaffold_runs(tmp_path: Path):
    out = tmp_path / "generated.cut"
    assert main(["generate", str(PROGRAM), "-o", str(out)]) == 0
    assert main(["run", str(PROGRAM), "--cut", str(out)]) == 0
