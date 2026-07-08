"""End-to-end proof for the NIST COBOL-85 CALL examples under
``examples/nist-cobol85/``.

These programs come straight from the cobol-parser project's example corpus
(the public-domain NIST COBOL-85 validation suite). Each one is spliced with
its committed ``.cut``, compiled with GnuCOBOL in the mockymock-cobc
container, and executed for real -- proving mockymock's static-CALL mocking
holds up against unmodified real-world test-suite programs, not just
hand-written fixtures.
"""

from pathlib import Path

import pytest

from mockymock.cli.main import main
from tests.integration._docker import requires_docker

EXAMPLE_DIR = Path(__file__).parent.parent.parent / "examples" / "nist-cobol85"

EXAMPLES = ["IC101A", "IC116M", "IC117M", "OBIC1A"]


@requires_docker
@pytest.mark.parametrize("name", EXAMPLES)
def test_committed_nist_example_passes(name: str):
    exit_code = main(
        [
            "run",
            str(EXAMPLE_DIR / f"{name}.CBL"),
            "--cut",
            str(EXAMPLE_DIR / f"{name}.cut"),
        ]
    )
    assert exit_code == 0


@requires_docker
def test_nist_example_fails_when_verify_count_is_wrong(tmp_path: Path):
    """A wrong VERIFY count on a passing example must turn the run red --
    guards against the examples silently degrading into no-op smoke tests."""
    cut = (EXAMPLE_DIR / "IC101A.cut").read_text()
    broken = tmp_path / "IC101A.cut"
    broken.write_text(
        cut.replace(
            'VERIFY CALL "IC102A" WAS CALLED ONCE',
            'VERIFY CALL "IC102A" WAS CALLED 3 TIMES',
        )
    )
    exit_code = main(["run", str(EXAMPLE_DIR / "IC101A.CBL"), "--cut", str(broken)])
    assert exit_code == 1
