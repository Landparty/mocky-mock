"""End-to-end proof for the real-world ACCTPRG (account purge, IMS DL/I
batch) example -- a named ENTRY 'DLITCBL' bound to a LINKAGE SECTION that
mockymock's PERFORM-only driver never binds. Before
docs/2026-07-08-ims-linkage-support-design.md's neutralization transform,
compiling and running a test against this program's default entry crashed
with SIGSEGV (unbound LINKAGE storage). This test proves the crash is gone
and the program is genuinely testable end-to-end, compiled and executed
with GnuCOBOL in the mockymock-cobc container -- not merely non-crashing.
"""

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
