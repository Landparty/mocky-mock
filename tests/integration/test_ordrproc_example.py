import shutil
from pathlib import Path

import pytest

from mockymock.cli.main import main

requires_gnucobol = pytest.mark.skipif(
    shutil.which("cobc") is None, reason="GnuCOBOL (cobc) not installed"
)

EXAMPLE_DIR = Path(__file__).parent.parent.parent / "examples" / "ordrproc"


@requires_gnucobol
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
