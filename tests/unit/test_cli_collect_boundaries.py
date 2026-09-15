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
