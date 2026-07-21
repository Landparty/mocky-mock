"""End-to-end proof for PROVIDER parameterized test cases: a single
`USING PROVIDER` TESTCASE expands into N independently compiled/run
cases -- see
docs/2026-07-20-provider-parameterized-test-cases-design.md."""

import json
from pathlib import Path

from mockymock.cli.main import main
from tests.integration._docker import requires_docker

EXAMPLE_DIR = Path(__file__).parent.parent.parent / "examples" / "statelkup"


@requires_docker
def test_committed_statelkup_example_passes():
    exit_code = main(
        [
            "run",
            str(EXAMPLE_DIR / "STATELKUP.cbl"),
            "--cut",
            str(EXAMPLE_DIR / "STATELKUP.cut"),
        ]
    )
    assert exit_code == 0


@requires_docker
def test_statelkup_fails_when_one_rows_expectation_is_wrong(tmp_path: Path):
    cut = (EXAMPLE_DIR / "STATELKUP.cut").read_text()
    broken = tmp_path / "STATELKUP.cut"
    broken.write_text(
        cut.replace(
            'EXPECT WS-STATE-NAME TO BE {Name}',
            'EXPECT WS-STATE-NAME TO BE "WRONG"',
            1,
        )
    )
    exit_code = main(
        ["run", str(EXAMPLE_DIR / "STATELKUP.cbl"), "--cut", str(broken)]
    )
    assert exit_code == 1


def test_statelkup_collect_lists_three_expanded_cases(capsys):
    """No Docker needed -- collect is pure parse (mockymock/cli/main.py)."""
    exit_code = main(
        ["collect", "--cut", str(EXAMPLE_DIR / "STATELKUP.cut"), "--json"]
    )
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert [c["name"] for c in payload["cases"]] == [
        "1000-LOOKUP-STATE resolves a state name [row 1: AZ]",
        "1000-LOOKUP-STATE resolves a state name [row 2: KY]",
        "1000-LOOKUP-STATE resolves a state name [row 3: XX]",
    ]
