"""Issue #336: `--name` went into `<program>.<NAME>.cut` unchecked, so
`--name a/b` wrote an orphaned suite into a new folder and `--name ../x`
wrote outside the tests folder. It must now be one plain word."""

import pytest

from mockymock.cli.main import main

PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. NM.
       PROCEDURE DIVISION.
       MAIN-PARA.
           GOBACK.
"""


@pytest.mark.parametrize("command", ["generate", "init", "suites"])
@pytest.mark.parametrize("name", ["a/b", "../../escaped", "a\\b", "", "x.y"])
def test_bad_suite_names_are_refused(tmp_path, monkeypatch, capsys, command, name):
    monkeypatch.chdir(tmp_path)
    cbl = tmp_path / "NM.cbl"
    cbl.write_text(PROGRAM)
    assert main([command, str(cbl), "--name", name]) == 2
    assert "<program>.<NAME>.cut" in capsys.readouterr().err
    assert sorted(p.name for p in tmp_path.rglob("*")) == ["NM.cbl"]


def test_a_plain_name_still_works(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    cbl = tmp_path / "NM.cbl"
    cbl.write_text(PROGRAM)
    assert main(["generate", str(cbl), "--name", "edge_cases-2"]) == 0
    assert [p.name for p in tmp_path.rglob("*.cut")] == ["NM.edge_cases-2.cut"]
