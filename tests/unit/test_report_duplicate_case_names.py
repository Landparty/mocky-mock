"""Issue #304: `report --run-json` matches run results to its cases by
.cut line (then by name, in order), so two TESTCASEs sharing a name each
keep their own status instead of one being left "not run"."""

from __future__ import annotations

import json
import shutil

import pytest

from mockymock.report.test_report import ReportOptions, build_report
from tests.unit.test_test_report import EXAMPLES

DUP_CUT = """\
TESTSUITE "dups"

TESTCASE "dup"
    MOVE 0.00 TO WS-DISCOUNT-PCT
    MOVE 50.00 TO ORD-AMOUNT
    PERFORM PROCESS-ORDER
    EXPECT WS-NET-AMOUNT TO BE 50.00

TESTCASE "dup"
    MOVE 0.00 TO WS-DISCOUNT-PCT
    MOVE 60.00 TO ORD-AMOUNT
    PERFORM PROCESS-ORDER
    EXPECT WS-NET-AMOUNT TO BE 61.00
"""


@pytest.mark.parametrize("with_lines", [True, False])
def test_same_named_cases_keep_their_own_status(tmp_path, with_lines) -> None:
    shutil.copy(EXAMPLES / "ordrproc" / "ORDRPROC.cbl", tmp_path / "ORDRPROC.cbl")
    (tmp_path / "ORDRPROC.cut").write_text(DUP_CUT, encoding="utf-8")
    entries = [
        {"name": "dup", "line": 3, "status": "passed", "failures": []},
        {"name": "dup", "line": 9, "status": "failed", "failures": []},
    ]
    if not with_lines:
        for entry in entries:
            entry["line"] = None
    run_json = tmp_path / "run.json"
    run_json.write_text(
        json.dumps({"version": 1, "cases": entries, "summary": {"testsRun": 2}}),
        encoding="utf-8",
    )
    report = build_report(
        ReportOptions(
            program=tmp_path / "ORDRPROC.cbl",
            cut=tmp_path / "ORDRPROC.cut",
            probe_toolchain=False,
            scenarios="none",
            run_json=run_json,
        )
    )
    assert [(c["line"], c["status"]) for c in report["cases"]] == [
        (3, "passed"),
        (9, "failed"),
    ]
