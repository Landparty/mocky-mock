from pathlib import Path

from mockymock.cli.main import main
from tests.integration._docker import requires_docker

EXAMPLE_DIR = Path(__file__).parent.parent.parent / "examples" / "ordrproc"


@requires_docker
def test_committed_ordrproc_example_passes():
    exit_code = main(
        [
            "run",
            str(EXAMPLE_DIR / "ORDRPROC.cbl"),
            "--cut",
            str(EXAMPLE_DIR / "ORDRPROC.cut"),
        ]
    )
    assert exit_code == 0
