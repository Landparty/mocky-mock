"""End-to-end proof for the real-world ACCTPRG (account purge, IMS DL/I
batch) example -- a named ENTRY 'DLITCBL' bound to a LINKAGE SECTION that
mockymock's PERFORM-only driver never binds. Before
docs/2026-07-08-ims-linkage-support-design.md's neutralization transform,
compiling and running a test against this program's default entry crashed
with SIGSEGV (unbound LINKAGE storage). This test proves the crash is gone
and the program is genuinely testable end-to-end, compiled and executed
with GnuCOBOL in the mockymock-cobc container -- not merely non-crashing.
"""

import re
from pathlib import Path

from mockymock.cli.main import main
from tests.integration._docker import requires_docker

EXAMPLE_DIR = (
    Path(__file__).parent.parent.parent / "examples" / "real-world" / "ACCTPRG"
)


@requires_docker
def test_committed_acctprg_example_passes():
    exit_code = main(
        [
            "run",
            str(EXAMPLE_DIR / "ACCTPRG.cbl"),
            "--cut",
            str(EXAMPLE_DIR / "ACCTPRG.cut"),
            "--copybook-path",
            str(EXAMPLE_DIR / "copybooks"),
        ]
    )
    assert exit_code == 0


# Exercises the intended wrong-expectation path: ACCTPRG compiles and runs
# cleanly (see test_committed_acctprg_example_passes above), so this exit 1
# comes from the deliberately broken EXPECT assertion, not from a whole-file
# parse/mock refusal or a crash.
@requires_docker
def test_acctprg_fails_when_expectation_is_wrong(tmp_path: Path):
    cut = (EXAMPLE_DIR / "ACCTPRG.cut").read_text()
    broken = tmp_path / "ACCTPRG.cut"
    broken.write_text(
        cut.replace("EXPECT WS-SEGS-PURGED TO BE 1", "EXPECT WS-SEGS-PURGED TO BE 2")
    )
    exit_code = main(
        [
            "run",
            str(EXAMPLE_DIR / "ACCTPRG.cbl"),
            "--cut",
            str(broken),
            "--copybook-path",
            str(EXAMPLE_DIR / "copybooks"),
        ]
    )
    assert exit_code == 1


@requires_docker
def test_committed_acctprg_example_reports_coverage(capsys):
    """--coverage composing with a suite nobody wrote with coverage in
    mind (ACCTPRG's suite predates this feature entirely) -- not a suite
    change, a sanity check that the tool works against pre-existing
    suites, not only purpose-built ones. Verified empirically while
    writing this test: gcov originally reported exactly 459/561
    executable lines covered (81.82%); re-pinned to 460/567 when the
    driver's FAIL lines gained actual values (5 uncovered
    MOVE-to-UT-TALLY-EDITED lines, one per VERIFY, plus the field's
    covered initialization)."""
    exit_code = main(
        [
            "run",
            str(EXAMPLE_DIR / "ACCTPRG.cbl"),
            "--cut",
            str(EXAMPLE_DIR / "ACCTPRG.cut"),
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
    match = re.search(r"coverage: \d+\.\d+% lines executed \(\d+/\d+\)", out)
    assert match is not None, "no coverage line in output"
    # Pinned against real Docker/GnuCOBOL 2026-07-21. Includes the 8
    # implicit `MOVE "00" TO WS-PURGEIN-STATUS` lines that
    # build_site_dispatch (mockymock/splicer/injector.py) injects into the
    # OPEN/READ/CLOSE dispatch branches for PURGEIN, whose FILE STATUS IS
    # WS-PURGEIN-STATUS is mocked via plain MOCK OPEN/READ/CLOSE PURGEIN
    # (no override) in ACCTPRG.cut -- see
    # docs/2026-07-20-before-blocks-and-file-status-design.md. Any codegen
    # change that adds/removes injected executable lines will legitimately
    # shift this number.
    assert match.group(0) == "coverage: 81.39% lines executed (468/575)"
