"""`mockymock run --branch-coverage`: paragraph, IF / EVALUATE outcome and
statement coverage read from the whole run's GnuCOBOL trace."""

import json
from pathlib import Path

from mockymock.cli.main import main
from tests.integration._docker import requires_docker

FIXTURE = Path(__file__).parent / "fixtures" / "branchcov"
EXAMPLES = Path(__file__).parent.parent.parent / "examples"


def _outcomes(program: dict) -> dict[tuple[int, str], int]:
    return {
        (branch["line"], outcome["label"]): outcome["hits"]
        for branch in program["branches"]["items"]
        for outcome in branch["outcomes"]
    }


@requires_docker
def test_every_case_counts_and_each_outcome_is_attributed(tmp_path: Path, capsys):
    out = tmp_path / "coverage.json"
    code = main(
        [
            "run",
            str(FIXTURE / "BRCOV.cbl"),
            "--cut",
            str(FIXTURE / "BRCOV.cut"),
            "--branch-coverage",
            str(out),
        ]
    )
    assert code == 0
    document = json.loads(out.read_text())
    assert document["version"] == 1
    assert document["casesRun"] == 2
    (program,) = document["programs"]
    assert program["programId"] == "BRCOV"
    paragraphs = {p["name"]: p["hits"] for p in program["paragraphs"]["items"]}
    assert paragraphs == {"MAIN-PARA": 2, "FLAG-PARA": 1, "NEVER-PARA": 0}
    assert _outcomes(program) == {
        (13, "true"): 1,
        (13, "false"): 1,
        (16, "true"): 1,
        (16, "false"): 1,
        (21, "WHEN 1"): 1,
        (21, "WHEN 2"): 1,
        (21, "WHEN OTHER"): 0,
        (30, 'WHEN WS-FLAG = "Y"'): 1,
        (30, "no WHEN matched"): 1,
    }
    assert program["branches"]["total"] == 9
    assert program["branches"]["covered"] == 8
    assert {"line": 38} in program["statements"]["uncovered"]
    printed = capsys.readouterr().out
    assert "paragraphs never entered: NEVER-PARA" in printed
    assert "line 21: EVALUATE never took: WHEN OTHER" in printed


@requires_docker
def test_real_subprograms_are_measured_under_their_own_id(tmp_path: Path):
    out = tmp_path / "coverage.json"
    paymod = EXAMPLES / "paymod"
    code = main(
        [
            "run",
            str(paymod / "PAYMAIN.cbl"),
            "--cut",
            str(paymod / "PAYMAIN.cut"),
            "--branch-coverage",
            str(out),
        ]
    )
    assert code == 0
    programs = {p["programId"]: p for p in json.loads(out.read_text())["programs"]}
    assert set(programs) == {"PAYMAIN", "PAYCALC"}
    assert programs["PAYCALC"]["programFile"].endswith("PAYCALC.cbl")
    assert programs["PAYCALC"]["paragraphs"]["covered"] >= 1
    assert programs["PAYCALC"]["branches"]["total"] > 0
