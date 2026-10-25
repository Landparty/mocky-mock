"""`mockymock report --execute --mutate` end to end: a real GnuCOBOL run and
a real mutation pass feed the report, and the recorded expectations a real
`run --record-expectations` writes come back labelled CHARACTERIZATION."""

import json
import shutil
from pathlib import Path

from mockymock.analysis.assertion_labels import scan_assertion_labels
from mockymock.cli.main import main
from tests.integration._docker import requires_docker

EXAMPLES = Path(__file__).parent.parent.parent / "examples"


@requires_docker
def test_report_executes_the_suite_and_grades_every_case(tmp_path):
    for name in ("CLAIMSEG.cbl", "CLAIMSEG.cut"):
        shutil.copy(EXAMPLES / "claimseg" / name, tmp_path / name)
    exit_code = main(
        [
            "report",
            str(tmp_path / "CLAIMSEG.cbl"),
            "--execute",
            "--mutate",
            "--json",
            str(tmp_path / "r.json"),
            "--scenarios",
            "none",
        ]
    )
    assert exit_code == 0
    report = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))
    steps = {s["id"]: s for s in report["steps"]}
    assert steps["run"]["status"] == "ok"
    assert steps["coverage"]["details"]["percentage"] == 100.0
    assert steps["mutation"]["details"]["score"] is not None
    assert report["summary"]["passed"] == len(report["cases"]) == 5
    assert all(c["level"] in ("L1", "L2", "L3") for c in report["cases"])
    assert (tmp_path / ".mockymock" / "CLAIMSEG.report.html").is_file()


@requires_docker
def test_mutate_without_mutable_statements_is_skipped_with_its_reason(tmp_path):
    for name in ("ORDRPROC.cbl", "ORDRPROC.cut"):
        shutil.copy(EXAMPLES / "ordrproc" / name, tmp_path / name)
    main(
        [
            "report",
            str(tmp_path / "ORDRPROC.cbl"),
            "--mutate",
            "--json",
            str(tmp_path / "r.json"),
            "--scenarios",
            "none",
        ]
    )
    report = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))
    mutation = next(s for s in report["steps"] if s["id"] == "mutation")
    assert mutation["status"] == "skipped"
    assert "no mutable statements" in mutation["summary"]


@requires_docker
def test_recorded_expectations_are_labelled_characterization(tmp_path):
    for name in ("ORDRPROC.cbl",):
        shutil.copy(EXAMPLES / "ordrproc" / name, tmp_path / name)
    cut = (EXAMPLES / "ordrproc" / "ORDRPROC.cut").read_text(encoding="utf-8")
    cut = cut.replace(
        "    EXPECT WS-NET-AMOUNT TO BE 50.00",
        "    *> STUB EXPECT WS-NET-AMOUNT -- zero discount",
    )
    (tmp_path / "ORDRPROC.cut").write_text(cut, encoding="utf-8")
    exit_code = main(
        [
            "run",
            str(tmp_path / "ORDRPROC.cbl"),
            "--cut",
            str(tmp_path / "ORDRPROC.cut"),
            "--record-expectations",
        ]
    )
    assert exit_code == 0
    rewritten = (tmp_path / "ORDRPROC.cut").read_text(encoding="utf-8")
    recorded = [
        a
        for a in scan_assertion_labels(rewritten)
        if a.case_name.startswith("Zero") and a.text.startswith("EXPECT WS-NET-AMOUNT")
    ]
    assert [a.label for a in recorded] == ["characterization"]
