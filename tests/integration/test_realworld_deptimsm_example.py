"""End-to-end proof for the new DEPTIMSM (IMS MPP deposit transaction)
example, and the first real-world proof of the --coverage feature
(docs/2026-07-17-coverage-reporting-design.md). Like ACCTPRG, this
program uses a named ENTRY 'DLITCBL' bound to a LINKAGE SECTION mockymock's
PERFORM-only driver neutralizes into WORKING-STORAGE.

The coverage percentage/line counts below were verified empirically
against real GnuCOBOL in Docker while writing this test's own suite (not
guessed): 20/20 cases pass, and gcov reports exactly 692/907 executable
lines covered (76.30%). See the design doc's addendum for why this
number is expected to be well below 100% even though every real branch in
the program is exercised (driver harness dead-fail branches, and the
splicer's per-boundary-site mock dispatch emitting one WHEN clause per
test case that shares a mock key, most of which are structurally
unreachable from any single case's own PERFORM target)."""

from pathlib import Path

from mockymock.cli.main import main
from tests.integration._docker import requires_docker

EXAMPLE_DIR = (
    Path(__file__).parent.parent.parent / "examples" / "real-world" / "DEPTIMSM"
)


@requires_docker
def test_committed_deptimsm_example_passes():
    exit_code = main(
        [
            "run",
            str(EXAMPLE_DIR / "DEPTIMSM.cbl"),
            "--cut",
            str(EXAMPLE_DIR / "DEPTIMSM.cut"),
            "--copybook-path",
            str(EXAMPLE_DIR / "copybooks"),
        ]
    )
    assert exit_code == 0


@requires_docker
def test_committed_deptimsm_example_reports_coverage(capsys):
    exit_code = main(
        [
            "run",
            str(EXAMPLE_DIR / "DEPTIMSM.cbl"),
            "--cut",
            str(EXAMPLE_DIR / "DEPTIMSM.cut"),
            "--copybook-path",
            str(EXAMPLE_DIR / "copybooks"),
            "--coverage",
        ]
    )
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "coverage: 76.30% lines executed (692/907)" in out
