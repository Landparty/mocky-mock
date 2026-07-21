"""End-to-end proof for BEFORE-EACH/BEFORE-ALL scoping and FILE-STATUS
sugar: the committed taxfile example compiles and runs for real in the
mockymock-cobc container."""

from pathlib import Path

from mockymock.cli.main import main
from tests.integration._docker import requires_docker

EXAMPLE_DIR = Path(__file__).parent.parent.parent / "examples" / "taxfile"


@requires_docker
def test_committed_taxfile_example_passes():
    exit_code = main(
        [
            "run",
            str(EXAMPLE_DIR / "TAXFILE.cbl"),
            "--cut",
            str(EXAMPLE_DIR / "TAXFILE.cut"),
        ]
    )
    assert exit_code == 0


@requires_docker
def test_taxfile_fails_when_expectation_is_wrong(tmp_path: Path):
    cut = (EXAMPLE_DIR / "TAXFILE.cut").read_text()
    broken = tmp_path / "TAXFILE.cut"
    broken.write_text(
        cut.replace(
            'EXPECT WS-ERROR-CODE TO BE "TUFNOTFND"',
            'EXPECT WS-ERROR-CODE TO BE "WRONGCODE"',
            1,
        )
    )
    exit_code = main(["run", str(EXAMPLE_DIR / "TAXFILE.cbl"), "--cut", str(broken)])
    assert exit_code == 1
