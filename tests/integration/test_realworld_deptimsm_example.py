"""End-to-end proof for the new DEPTIMSM (IMS MPP deposit transaction)
example, and the first real-world proof of the --coverage feature
(docs/2026-07-17-coverage-reporting-design.md). Like ACCTPRG, this
program uses a named ENTRY 'DLITCBL' bound to a LINKAGE SECTION mockymock's
PERFORM-only driver neutralizes into WORKING-STORAGE.

The coverage percentage/line counts below were verified empirically
against real GnuCOBOL in Docker while writing this test's own suite (not
guessed): 20/20 cases pass, and gcov originally reported exactly 692/907
executable lines covered (76.30%); re-pinned to 693/913 when the
driver's FAIL lines gained actual values (5 uncovered
MOVE-to-UT-TALLY-EDITED lines, one per VERIFY, plus the field's covered
initialization). See the design doc's addendum for why this
number is expected to be well below 100% even though every real branch in
the program is exercised (driver harness dead-fail branches, and the
splicer's per-boundary-site mock dispatch emitting one WHEN clause per
test case that shares a mock key, most of which are structurally
unreachable from any single case's own PERFORM target)."""

import re
from pathlib import Path

from mockymock.cli.main import main
from tests.integration._docker import pinned_coverage_toolchain, requires_docker

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
    # Extract-then-compare (rather than a bare substring check) so a
    # mismatch's failure message shows the actual coverage line instead
    # of a page of unrelated captured stdout.
    match = re.search(r"coverage: \d+\.\d+% of \S+ own lines executed \(\d+/\d+\)", out)
    assert match is not None, "no coverage line in output"
    if pinned_coverage_toolchain():
        assert match.group(0) == (
            "coverage: 100.00% of DEPTIMSM.cbl's own lines executed (108/108)"
        )
