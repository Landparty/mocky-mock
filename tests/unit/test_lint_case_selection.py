"""`mockymock lint --case/--tag`: per-case refusals are scoped to the
selection, as `debug --case` scopes them (the extension's debug preflight
runs lint, so a refusal in one TESTCASE used to block debugging another --
mocky-mock-vscode#95)."""

import shutil
from pathlib import Path

import pytest

from mockymock.cli.main import main

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"
CLEAN = "fetches two customers then exhausts"
WIP = "work in progress"


@pytest.fixture
def custprog(tmp_path, monkeypatch):
    shutil.copytree(EXAMPLES / "custprog", tmp_path, dirs_exist_ok=True)
    cut = tmp_path / "CUSTPROG.cut"
    cut.write_text(
        cut.read_text(encoding="utf-8")
        + f'\nTESTCASE "{WIP}" TAGS "wip"\n    PERFORM MAIN-PROCESS\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _lint(*extra):
    return main(
        ["lint", "CUSTPROG.cbl", "--cut", "CUSTPROG.cut", "--copybook-path"]
        + ["copybooks", *extra]
    )


def test_whole_file_still_reports_every_case(custprog, capsys):
    assert _lint() == 1
    assert "UNMOCKED_SQL" in capsys.readouterr().out


def test_case_ignores_another_cases_refusals(custprog, capsys):
    assert _lint("--case", CLEAN) == 0
    out = capsys.readouterr().out
    assert "UNMOCKED_SQL" not in out
    assert "no problems found" in out


def test_case_still_reports_its_own_refusals(custprog, capsys):
    assert _lint("--case", WIP) == 1
    assert "UNMOCKED_SQL" in capsys.readouterr().out


def test_tag_selects_cases(custprog, capsys):
    assert _lint("--tag", "wip") == 1
    assert "UNMOCKED_SQL" in capsys.readouterr().out


def test_unknown_case_is_a_problem(custprog, capsys):
    assert _lint("--case", "nope") == 1
    assert "no TESTCASE named 'nope'" in capsys.readouterr().out


def test_directory_mode_skips_suites_without_the_case(custprog, capsys):
    other = custprog / "CUSTPROG.extra.cut"
    other.write_text(
        'TESTSUITE "extra"\nTESTCASE "unrelated"\n    PERFORM MAIN-PROCESS\n',
        encoding="utf-8",
    )
    assert main(["lint", "--copybook-path", "copybooks", "--case", CLEAN]) == 0
    out = capsys.readouterr().out
    assert "1 suite(s) without a selected TESTCASE skipped" in out
    assert main(["lint", "--copybook-path", "copybooks", "--case", "nope"]) == 1
    assert "no TESTCASE named 'nope' in any suite" in capsys.readouterr().out
