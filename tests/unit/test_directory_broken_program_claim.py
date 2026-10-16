"""Issue #303, option (b): in directory mode a `.cut` whose explicit
PROGRAM "..." line names a missing file fails the run/lint (exit 1); a
`.cut` whose program was only guessed is still just skipped. Every
skipped suite gets a failing --junit-xml / --json-report entry."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from mockymock.cli.main import main

_ORDRPROC = Path(__file__).resolve().parents[2] / "examples" / "ordrproc"

BROKEN_CLAIM = """\
TESTSUITE "pay"
PROGRAM "src/PAYROLL.cbl"
TESTCASE "a"
    PERFORM X
    EXPECT WS-A TO BE 1
"""

GUESSED = BROKEN_CLAIM.replace('PROGRAM "src/PAYROLL.cbl"\n', "")


def _project(tmp_path, monkeypatch, extra: dict[str, str]) -> None:
    shutil.copy(_ORDRPROC / "ORDRPROC.cbl", tmp_path / "ORDRPROC.cbl")
    shutil.copy(_ORDRPROC / "ORDRPROC.cut", tmp_path / "ORDRPROC.cut")
    for name, text in extra.items():
        (tmp_path / name).write_text(text, encoding="utf-8")
    monkeypatch.chdir(tmp_path)


def test_lint_fails_on_a_broken_program_line(tmp_path, monkeypatch, capsys) -> None:
    _project(tmp_path, monkeypatch, {"PAYROLL.cut": BROKEN_CLAIM})
    assert main(["lint"]) == 1
    assert "name a PROGRAM that does not exist" in capsys.readouterr().out


def test_lint_still_skips_a_guessed_program(tmp_path, monkeypatch, capsys) -> None:
    _project(tmp_path, monkeypatch, {"PAYROLL.cut": GUESSED})
    assert main(["lint"]) == 0
    assert "1 .cut file(s) skipped" in capsys.readouterr().out


def test_run_writes_a_failing_report_for_a_skipped_suite(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "PAYROLL.cut").write_text(BROKEN_CLAIM, encoding="utf-8")
    assert main(["run", "--junit-xml", "junit.xml", "--json-report", "r.json"]) == 1
    junit = (tmp_path / "junit-PAYROLL.xml").read_text(encoding="utf-8")
    assert 'failures="1"' in junit or 'errors="1"' in junit
    assert "does not exist" in junit
    report = json.loads((tmp_path / "r-PAYROLL.json").read_text(encoding="utf-8"))
    assert report["suite"]["name"] == "pay"
    assert any(case["status"] != "passed" for case in report["cases"])
