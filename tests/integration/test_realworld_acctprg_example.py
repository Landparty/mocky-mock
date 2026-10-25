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
from tests.integration._docker import pinned_coverage_toolchain, requires_docker

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
    suites, not only purpose-built ones. Pins the original program's
    own-line figure (see the comment on the assertion below)."""
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
    match = re.search(r"coverage: \d+\.\d+% of \S+ own lines executed \(\d+/\d+\)", out)
    assert match is not None, "no coverage line in output"
    # Re-pinned against real Docker/GnuCOBOL 2026-09-28 to the ORIGINAL
    # program's own-line figure, which `run --coverage` has led with since
    # 073d4f7 (the instrumented sandbox number, which moves with every
    # codegen change to injected dispatch lines, is now only a subordinate
    # line). This figure moves only when ACCTPRG.cbl or its suite changes.
    # Re-pinned 2026-10-05 (GnuCOBOL 3.2.0): 84/97 -> 86/97 when the suite
    # gained its two MOCK CALL ... ROWS whole-program cases, which drive
    # real 0000-MAIN-PROCESS loop iterations instead of only the
    # empty-database path.
    if pinned_coverage_toolchain():
        assert match.group(0) == (
            "coverage: 88.66% of ACCTPRG.cbl's own lines executed (86/97)"
        )
