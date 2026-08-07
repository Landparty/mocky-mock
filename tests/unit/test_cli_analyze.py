"""Tests for the `mockymock analyze` cobol-parser passthrough subcommand."""

import json

from mockymock.cli.main import main


def _dead_code_fixture(tmp_path):
    cbl = tmp_path / "DEADDEMO.cbl"
    cbl.write_text(
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. DEADDEMO.\n"
        "\n"
        "       PROCEDURE DIVISION.\n"
        "       MAIN-PARA.\n"
        "           DISPLAY 'HELLO'.\n"
        "           STOP RUN.\n"
        "\n"
        "       DEAD-PARA.\n"
        "           DISPLAY 'NEVER RUNS'.\n"
    )
    return cbl


def test_analyze_dead_code_prints_cobol_parser_json(tmp_path, capsys):
    cbl = _dead_code_fixture(tmp_path)
    exit_code = main(["analyze", "dead-code", str(cbl), "--compact"])
    out = capsys.readouterr().out
    assert exit_code == 0
    payload = json.loads(out)
    assert payload["program_id"] == "DEADDEMO"
    assert len(payload["dead_code"]) == 1
    assert payload["dead_code"][0]["name"] == "DEAD-PARA"
    assert payload["dead_code"][0]["type"] == "PARAGRAPH"
    assert payload["summary"] == {
        "total_procedures": 2,
        "referenced_procedures": 1,
        "dead_procedures": 1,
    }


def test_analyze_propagates_cobol_parser_exit_code_on_missing_file(tmp_path, capsys):
    missing = tmp_path / "NOPE.cbl"
    exit_code = main(["analyze", "dead-code", str(missing)])
    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert f"error: File not found: {missing}" in captured.err


def test_analyze_with_unrecognized_subcommand_falls_back_to_parse_and_fails(capsys):
    # cobol-parser's own main() rewrites an unrecognized first token to the
    # `parse` subcommand (legacy syntax support) rather than raising an
    # argparse "invalid choice" error -- the bogus token is then treated as
    # a filename and fails as "File not found". This test pins that
    # observed behavior so a future cobol-parser CLI change that removes
    # the legacy fallback is caught here rather than surfacing as a
    # confusing passthrough bug.
    exit_code = main(["analyze", "bogus-subcommand", "X"])
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "error: File not found: bogus-subcommand" in captured.err


def test_analyze_help_lists_the_passthrough_metavar(capsys):
    exit_code = main(["analyze", "--help"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "COBOL_PARSER_ARGS" in out
