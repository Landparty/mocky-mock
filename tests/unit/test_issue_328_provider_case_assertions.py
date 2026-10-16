"""Issue #328: `report` joined the raw-text assertion scan (which records a
PROVIDER-bound template's EXPECTs under the template's name) to the parsed
suite (which only has the expanded rows) by name, so every row read as
"asserts nothing" and its INTENT labels counted for nobody."""

import json
import shutil
from pathlib import Path

from mockymock.dsl.parser import parse_cut
from mockymock.report.test_report import ReportOptions, build_report

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"

CUT = """\
TESTSUITE "ORDRPROC provider"

PROVIDER P
    HEADER AMT, NET
    ROW 100.00, 90.00
    ROW 50.00, 45.00

TESTCASE "discount" USING PROVIDER P
    MOCK CALL "DISCRATE"
        MOVE 0.10 TO WS-DISCOUNT-PCT
    END-MOCK
    MOVE {AMT} TO ORD-AMOUNT
    PERFORM PROCESS-ORDER
    *> INTENT: BR-001 net = amount - amount * discount
    EXPECT WS-NET-AMOUNT TO BE {NET}

TESTCASE "plain"
    MOCK CALL "DISCRATE"
        MOVE 0.00 TO WS-DISCOUNT-PCT
    END-MOCK
    MOVE 50.00 TO ORD-AMOUNT
    PERFORM PROCESS-ORDER
    *> INTENT: BR-001 no discount
    EXPECT WS-NET-AMOUNT TO BE 50.00
"""


def test_expanded_rows_carry_their_template_name():
    names = [(c.name, c.template_name) for c in parse_cut(CUT).test_cases]
    assert names[0][1] == names[1][1] == "discount"
    assert names[0][0].startswith("discount [row 1")
    assert names[2] == ("plain", None)


def test_each_provider_row_inherits_the_templates_assertions(tmp_path):
    shutil.copy(EXAMPLES / "ordrproc" / "ORDRPROC.cbl", tmp_path / "ORDRPROC.cbl")
    (tmp_path / "ORDRPROC.cut").write_text(CUT, encoding="utf-8")
    suite = parse_cut(CUT)
    run_json = tmp_path / "run.json"
    run_json.write_text(
        json.dumps(
            {
                "version": 1,
                "cases": [
                    {
                        "name": c.name,
                        "line": c.line,
                        "status": "passed",
                        "failures": [],
                    }
                    for c in suite.test_cases
                ],
                "summary": {"testsRun": len(suite.test_cases)},
            }
        ),
        encoding="utf-8",
    )
    report = build_report(
        ReportOptions(
            program=tmp_path / "ORDRPROC.cbl",
            cut=tmp_path / "ORDRPROC.cut",
            run_json=run_json,
            probe_toolchain=False,
            scenarios="none",
        )
    )
    by_name = {case["name"]: case for case in report["cases"]}
    for case in suite.test_cases:
        assert by_name[case.name]["assertions"]["total"] == 1
        assert by_name[case.name]["assertions"]["intent"] == 1
    assert not [f for f in report["findings"] if f["category"] == "no-assertion"]
    (rule,) = [r for r in report["rules"] if r["id"] == "BR-001"]
    assert rule["citedBy"] == [c.name for c in suite.test_cases]
