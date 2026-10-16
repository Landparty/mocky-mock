"""docs/2026-09-15-cut-editor-intelligence-design.md: `mockymock collect
--boundaries` and `mockymock explain`."""

import json
from pathlib import Path

from mockymock.cli.main import main

_EXAMPLE_DIR = Path(__file__).resolve().parents[2] / "examples" / "ordrproc"
_ORDRPROC_CBL = _EXAMPLE_DIR / "ORDRPROC.cbl"
_ORDRPROC_CUT = _EXAMPLE_DIR / "ORDRPROC.cut"


def test_collect_boundaries_requires_json(capsys):
    exit_code = main(
        ["collect", str(_ORDRPROC_CBL), "--cut", str(_ORDRPROC_CUT), "--boundaries"]
    )
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "requires --json" in out


def test_collect_boundaries_requires_program(capsys):
    exit_code = main(["collect", "--cut", str(_ORDRPROC_CUT), "--boundaries", "--json"])
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "requires a program argument" in out


def test_collect_boundaries_reports_the_call_site(capsys):
    exit_code = main(
        [
            "collect",
            str(_ORDRPROC_CBL),
            "--cut",
            str(_ORDRPROC_CUT),
            "--json",
            "--boundaries",
        ]
    )
    out = capsys.readouterr().out
    assert exit_code == 0
    payload = json.loads(out)
    assert "boundaries" in payload
    assert len(payload["boundaries"]) == 1
    site = payload["boundaries"][0]
    assert site["category"] == "CALL"
    assert site["key"] == "DISCRATE"
    # The exact header the scaffold would write: a quoted CALL key.
    assert site["directive"] == 'MOCK CALL "DISCRATE"'
    assert site["paragraph"] == "PROCESS-ORDER"
    assert site["line"] > 0


def test_collect_without_boundaries_flag_is_unaffected(capsys):
    """Byte-for-byte regression guard: the plain collect payload shape
    is unchanged when --boundaries isn't passed."""
    exit_code = main(["collect", "--cut", str(_ORDRPROC_CUT), "--json"])
    out = capsys.readouterr().out
    assert exit_code == 0
    payload = json.loads(out)
    assert "boundaries" not in payload
    assert set(payload) == {"version", "cutFile", "suite", "cases"}


def test_collect_boundaries_missing_program_file_reports_cleanly(tmp_path, capsys):
    exit_code = main(
        [
            "collect",
            str(tmp_path / "MISSING.cbl"),
            "--cut",
            str(_ORDRPROC_CUT),
            "--json",
            "--boundaries",
        ]
    )
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "no such file" in out


def test_explain_known_code(capsys):
    exit_code = main(["explain", "UNSUPPORTED_DECLARATIVES"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "UNSUPPORTED_DECLARATIVES" in out
    assert "DECLARATIVES" in out


def test_explain_is_case_insensitive(capsys):
    exit_code = main(["explain", "unsupported_declaratives"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "UNSUPPORTED_DECLARATIVES" in out


def test_explain_unknown_code_exits_1_and_lists_known_codes_in_json(capsys):
    exit_code = main(["explain", "NOT_A_REAL_CODE", "--json"])
    out = capsys.readouterr().out
    assert exit_code == 1
    payload = json.loads(out)
    assert payload["error"] == "not catalogued"
    assert "UNSUPPORTED_DECLARATIVES" in payload["knownCodes"]


def test_explain_list_shows_every_code(capsys):
    exit_code = main(["explain", "--list", "--json"])
    out = capsys.readouterr().out
    assert exit_code == 0
    payload = json.loads(out)
    assert "UNMOCKED_CALL" in payload["codes"]
    assert payload["codes"] == sorted(payload["codes"])


def test_explain_no_code_and_no_list_shows_every_code(capsys):
    """Bare `mockymock explain` (no code, no --list) is treated the same
    as --list -- there's nothing else useful it could do."""
    exit_code = main(["explain"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "UNMOCKED_CALL" in out


_COPY_PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A PIC X(4).
       PROCEDURE DIVISION.
       MAIN-PARA.
           COPY CALLS.
           GOBACK.
"""
_COPY_CUT = """\
TESTSUITE "S"
TESTCASE "T"
    MOCK CALL "SUBPROG"
    END-MOCK
    PERFORM MAIN-PARA
"""


def _copy_project(root: Path, copybook_dir: str) -> tuple[Path, Path]:
    (root / copybook_dir).mkdir()
    (root / copybook_dir / "CALLS.cpy").write_text(
        '           CALL "SUBPROG" USING WS-A.\n', encoding="utf-8"
    )
    program = root / "PROG.cbl"
    program.write_text(_COPY_PROGRAM, encoding="utf-8")
    cut = root / "PROG.cut"
    cut.write_text(_COPY_CUT, encoding="utf-8")
    return program, cut


def _collected_keys(program: Path, cut: Path, capsys) -> list[str]:
    exit_code = main(
        ["collect", str(program), "--cut", str(cut), "--json", "--boundaries"]
    )
    out = capsys.readouterr().out
    assert exit_code == 0, out
    return [site["key"] for site in json.loads(out)["boundaries"]]


def test_collect_boundaries_finds_a_site_in_the_default_copybooks_folder(
    tmp_path, capsys, monkeypatch
):
    """Issue #200: collect skipped the copybook lookup lint/run use, so a
    CALL inside copybooks/CALLS.cpy vanished (exit 0, empty list)."""
    monkeypatch.chdir(tmp_path)
    program, cut = _copy_project(tmp_path, "copybooks")
    assert _collected_keys(program, cut, capsys) == ["SUBPROG"]


def test_collect_boundaries_honours_the_config_copybook_path(
    tmp_path, capsys, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    program, cut = _copy_project(tmp_path, "lib")
    (tmp_path / "mockymock.toml").write_text(
        'copybook_path = ["lib"]\n', encoding="utf-8"
    )
    assert _collected_keys(program, cut, capsys) == ["SUBPROG"]
