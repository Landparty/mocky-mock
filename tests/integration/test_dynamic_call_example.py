"""End-to-end proof for dynamic CALL mocks: three `CALL WS-PGM-NAME`
statements (one nested in an IF) are matched by a single bare-key
`MOCK CALL WS-PGM-NAME` directive whose body branches on the identifier's
runtime value, spliced, compiled with GnuCOBOL in the mockymock-cobc
container, and executed for real -- the layout that was blanket-refused
(DYNAMIC_CALL) before docs/2026-07-06-dynamic-call-mocks-design.md."""

from pathlib import Path

from mockymock.cli.main import main
from tests.integration._docker import requires_docker

FIXTURES = Path(__file__).parent / "fixtures"


@requires_docker
def test_dynamic_call_run_passes():
    exit_code = main(
        [
            "run",
            str(FIXTURES / "dynamic_call.cbl"),
            "--cut",
            str(FIXTURES / "dynamic_call.cut"),
        ]
    )
    assert exit_code == 0


@requires_docker
def test_dynamic_call_fails_when_expectation_is_wrong(tmp_path: Path):
    cut = (FIXTURES / "dynamic_call.cut").read_text()
    broken = tmp_path / "dynamic_call.cut"
    broken.write_text(cut.replace("EXPECT WS-TOTAL TO BE 5", "EXPECT WS-TOTAL TO BE 6"))
    exit_code = main(
        ["run", str(FIXTURES / "dynamic_call.cbl"), "--cut", str(broken)]
    )
    assert exit_code == 1


@requires_docker
def test_dynamic_call_fails_when_verify_count_is_wrong(tmp_path: Path):
    cut = (FIXTURES / "dynamic_call.cut").read_text()
    broken = tmp_path / "dynamic_call.cut"
    broken.write_text(
        cut.replace("WAS CALLED 3 TIMES", "WAS CALLED 2 TIMES")
    )
    exit_code = main(
        ["run", str(FIXTURES / "dynamic_call.cbl"), "--cut", str(broken)]
    )
    assert exit_code == 1
