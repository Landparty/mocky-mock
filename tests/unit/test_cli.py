"""CLI behavior tests (non-Docker-specific)."""

import json

from mockymock.cli.main import main


def test_generate_reports_terminators_separately_from_unmockable(tmp_path, capsys):
    cbl = tmp_path / "TERMDEMO.cbl"
    cbl.write_text(
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. TERMDEMO.\n"
        "\n"
        "       PROCEDURE DIVISION.\n"
        "       0000-MAIN-PROCESS.\n"
        "           STOP RUN.\n"
    )
    exit_code = main(["generate", str(cbl)])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "STOP RUN/GOBACK site(s) detected" in out
    assert "will be refused" not in out


# --- mockymock lint -------------------------------------------------------

from pathlib import Path

_EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


def test_lint_clean_example_reports_no_problems(capsys):
    exit_code = main(
        [
            "lint",
            str(_EXAMPLES / "ordrproc" / "ORDRPROC.cbl"),
            "--cut",
            str(_EXAMPLES / "ordrproc" / "ORDRPROC.cut"),
        ]
    )
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "mockymock lint: no problems found." in out


def test_lint_reports_problems_and_count(tmp_path, capsys):
    cbl = tmp_path / "BAD.cbl"
    cbl.write_text("this is not cobol\n")
    cut = tmp_path / "BAD.cut"
    cut.write_text('TESTSUITE "s"\n')
    exit_code = main(["lint", str(cbl), "--cut", str(cut)])
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "mockymock lint: refused (" in out
    assert "problem(s) found." in out


def test_lint_reports_invalid_cut_file(tmp_path, capsys):
    cut = tmp_path / "X.cut"
    cut.write_text("NOT A DIRECTIVE\n")
    exit_code = main(
        ["lint", str(_EXAMPLES / "ordrproc" / "ORDRPROC.cbl"), "--cut", str(cut)]
    )
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "invalid .cut file" in out


def test_lint_missing_inputs_fail_cleanly(tmp_path, capsys):
    exit_code = main(
        ["lint", str(tmp_path / "NOPE.cbl"), "--cut", str(tmp_path / "NOPE.cut")]
    )
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "mockymock lint: no such file" in out


# --- mockymock collect ----------------------------------------------------


def test_collect_json_lists_cases_with_lines_and_tags(tmp_path, capsys):
    cut = tmp_path / "PROG.cut"
    cut.write_text(
        'TESTSUITE "demo suite"\n'
        "\n"
        'TESTCASE "first" TAGS "fast"\n'
        "    PERFORM MAIN\n"
        "\n"
        'TESTCASE "second"\n'
        "    PERFORM MAIN\n"
    )
    exit_code = main(["collect", "--cut", str(cut), "--json"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["version"] == 1
    assert payload["suite"] == {"name": "demo suite", "line": 1}
    assert payload["cases"] == [
        {"name": "first", "line": 3, "tags": ["fast"]},
        {"name": "second", "line": 6, "tags": []},
    ]


def test_collect_human_listing(tmp_path, capsys):
    cut = tmp_path / "PROG.cut"
    cut.write_text('TESTSUITE "s"\nTESTCASE "only"\n    PERFORM MAIN\n')
    exit_code = main(["collect", "--cut", str(cut)])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "TESTSUITE 's' (line 1)" in out
    assert "TESTCASE 'only' (line 2)" in out
    assert "1 test case(s)" in out


def test_collect_invalid_cut_reports_error_in_json(tmp_path, capsys):
    cut = tmp_path / "PROG.cut"
    cut.write_text("junk\n")
    exit_code = main(["collect", "--cut", str(cut), "--json"])
    assert exit_code == 1
    payload = json.loads(capsys.readouterr().out)
    assert "error" in payload


def test_collect_lists_expanded_provider_cases(tmp_path, capsys):
    cut = tmp_path / "PROG.cut"
    cut.write_text(
        'TESTSUITE "s"\n'
        "PROVIDER Nums\n"
        "    HEADER N\n"
        "    ROW 1\n"
        "    ROW 2\n"
        'TESTCASE "c" USING PROVIDER Nums\n'
        "    MOVE {N} TO WS-N\n"
        "    PERFORM MAIN\n"
    )
    exit_code = main(["collect", "--cut", str(cut), "--json"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert [c["name"] for c in payload["cases"]] == [
        "c [row 1: 1]",
        "c [row 2: 2]",
    ]


# --- mockymock run --trace ------------------------------------------------
# The refusal below must fire before Docker is touched, so these tests need
# no daemon and no valid .cbl/.cut -- reaching the toolchain at all would
# itself be the failure.


def _trace_files(tmp_path):
    cbl = tmp_path / "P.cbl"
    cbl.write_text(
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. P.\n"
        "       PROCEDURE DIVISION.\n"
        "       0000-MAIN.\n"
        "           DISPLAY 'HI'.\n"
    )
    cut = tmp_path / "P.cut"
    cut.write_text('TESTSUITE "P"\n\nTESTCASE "a"\n    PERFORM 0000-MAIN\nEND\n')
    return cbl, cut


def test_trace_without_any_case_is_refused(tmp_path, capsys):
    cbl, cut = _trace_files(tmp_path)
    exit_code = main(["run", str(cbl), "--cut", str(cut), "--trace"])
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "--trace requires exactly one --case" in out


def test_trace_with_two_cases_is_refused(tmp_path, capsys):
    cbl, cut = _trace_files(tmp_path)
    exit_code = main(
        ["run", str(cbl), "--cut", str(cut), "--trace", "--case", "a", "--case", "b"]
    )
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "--trace requires exactly one --case" in out


def test_trace_with_a_tag_selection_is_refused(tmp_path, capsys):
    cbl, cut = _trace_files(tmp_path)
    exit_code = main(
        [
            "run",
            str(cbl),
            "--cut",
            str(cut),
            "--trace",
            "--case",
            "a",
            "--tag",
            "smoke",
        ]
    )
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "--trace requires exactly one --case" in out


def test_trace_json_implies_trace_and_inherits_the_same_refusal(tmp_path, capsys):
    """--trace-json alone (no --case) must hit the trace refusal, which only
    happens if it turned --trace on first."""
    cbl, cut = _trace_files(tmp_path)
    exit_code = main(
        ["run", str(cbl), "--cut", str(cut), "--trace-json", str(tmp_path / "t.json")]
    )
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "--trace requires exactly one --case" in out
