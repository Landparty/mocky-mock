"""`mockymock report`: CLI wiring, output files and exit codes. Docker-free
(results are passed with --run-json, as an assistant that already ran the
suite would)."""

import json
import shutil
from pathlib import Path

import pytest

from mockymock.cli.main import build_parser, main

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


@pytest.fixture
def ordrproc(tmp_path, monkeypatch):
    for name in ("ORDRPROC.cbl", "ORDRPROC.cut"):
        shutil.copy(EXAMPLES / "ordrproc" / name, tmp_path / name)
    monkeypatch.chdir(tmp_path)
    # The toolchain probe shells out to docker; keep the unit test hermetic.
    from mockymock.runtime import status

    monkeypatch.setattr(status, "probe", _fake_probe)
    return tmp_path


def _fake_probe():
    class _Status:
        def to_dict(self):
            return {"ready": False, "checks": [], "cobc_version": None}

    return _Status()


def _run_json(path, status="passed"):
    path.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "name": "10% discount reduces net amount correctly",
                        "status": status,
                        "failures": [],
                    },
                    {
                        "name": "Zero discount leaves amount unchanged",
                        "status": "passed",
                        "failures": [],
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    return path


def test_writes_html_next_to_the_program_by_default(ordrproc, capsys):
    exit_code = main(["report", "ORDRPROC.cbl", "--scenarios", "none"])
    assert exit_code == 0
    page = (ordrproc / "ORDRPROC.report.html").read_text(encoding="utf-8")
    assert "<title>ORDRPROC test report</title>" in page
    out = capsys.readouterr().out
    assert "[skipped] Run the suite under GnuCOBOL" in out
    assert "wrote ORDRPROC.report.html" in out


def test_json_and_output_paths(ordrproc):
    exit_code = main(
        [
            "report",
            "--cut",
            "ORDRPROC.cut",
            "-o",
            "out/r.html",
            "--json",
            "r.json",
            "--run-json",
            str(_run_json(ordrproc / "run.json")),
            "--scenarios",
            "none",
        ]
    )
    assert exit_code == 0
    report = json.loads((ordrproc / "r.json").read_text(encoding="utf-8"))
    assert report["summary"]["passed"] == 2
    assert (ordrproc / "out" / "r.html").is_file()


def test_exits_1_when_a_test_failed(ordrproc):
    exit_code = main(
        [
            "report",
            "ORDRPROC.cbl",
            "--run-json",
            str(_run_json(ordrproc / "run.json", status="failed")),
            "--scenarios",
            "none",
        ]
    )
    assert exit_code == 1


def test_journal_next_to_the_cut_is_picked_up(ordrproc):
    main(
        [
            "journal",
            "--cut",
            "ORDRPROC.cut",
            "--step",
            "plan",
            "--summary",
            "hello journal",
        ]
    )
    main(["report", "ORDRPROC.cbl", "--json", "r.json", "--scenarios", "none"])
    report = json.loads((ordrproc / "r.json").read_text(encoding="utf-8"))
    assert report["journal"][0]["summary"] == "hello journal"


def test_rejects_an_out_of_range_threshold(ordrproc, capsys):
    exit_code = main(["report", "ORDRPROC.cbl", "--mutation-threshold", "150"])
    assert exit_code == 1
    assert "--mutation-threshold" in capsys.readouterr().out


def test_scenarios_choices_are_validated():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["report", "X.cbl", "--scenarios", "most"])


def test_building_the_parser_does_not_import_the_report_modules():
    import subprocess
    import sys

    code = (
        "import sys; from mockymock.cli.main import build_parser; build_parser(); "
        "bad = [m for m in ('mockymock.report.test_report', "
        "'mockymock.report.html_report', 'mockymock.analysis.dialect_risk') "
        "if m in sys.modules]; print(bad); sys.exit(1 if bad else 0)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout
