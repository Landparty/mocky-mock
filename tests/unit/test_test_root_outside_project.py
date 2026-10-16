"""Issue #294: with `test_root` outside the project folder, the suite
`generate` writes there is found by `suites` and by every command that
infers `--cut` from a program."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from mockymock.cli.main import main

_ORDRPROC = Path(__file__).resolve().parents[2] / "examples" / "ordrproc"


def _project(tmp_path, monkeypatch) -> Path:
    project = tmp_path / "proj"
    (project / "src").mkdir(parents=True)
    (tmp_path / "qa-tests").mkdir()
    (project / "mockymock.toml").write_text(
        'test_root = "../qa-tests"\nsource_root = "src"\n'
    )
    shutil.copy(_ORDRPROC / "ORDRPROC.cbl", project / "src" / "ORDRPROC.cbl")
    shutil.copy(_ORDRPROC / "ORDRPROC.cut", tmp_path / "qa-tests" / "ORDRPROC.cut")
    monkeypatch.chdir(project)
    return project


def test_suites_lists_a_suite_in_an_outside_tests_folder(
    tmp_path, monkeypatch, capsys
) -> None:
    _project(tmp_path, monkeypatch)
    assert main(["suites", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert [Path(row["cut"]).name for row in payload["suites"]] == ["ORDRPROC.cut"]


def test_lint_program_finds_its_suite_in_an_outside_tests_folder(
    tmp_path, monkeypatch, capsys
) -> None:
    _project(tmp_path, monkeypatch)
    assert main(["lint", "src/ORDRPROC.cbl"]) == 0
    assert "no .cut file found" not in capsys.readouterr().out
