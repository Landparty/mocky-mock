"""CLI-level tests for docs/2026-09-15-cli-ergonomics-design.md: sibling
.cut/.cbl inference, directory-wide run/lint discovery, the config file,
and setup --rebuild. Docker-free -- these exercise `lint` (never touches
docker_toolchain) and argument-resolution paths that run before any
splice/compile step."""

from pathlib import Path

from mockymock.cli.main import main

_CLEAN_PROGRAM = (
    "       IDENTIFICATION DIVISION.\n"
    "       PROGRAM-ID. ORDRPROC.\n"
    "       PROCEDURE DIVISION.\n"
    "       0000-MAIN-PROCESS.\n"
    "           STOP RUN.\n"
)

_CLEAN_CUT = 'TESTSUITE "s"\n\nTESTCASE "c"\n    PERFORM 0000-MAIN-PROCESS\n'


def _write_pair(tmp_path, stem="ORDRPROC", cbl_ext=".cbl"):
    cbl = tmp_path / f"{stem}{cbl_ext}"
    cbl.write_text(_CLEAN_PROGRAM.replace("ORDRPROC", stem))
    cut = tmp_path / f"{stem}.cut"
    cut.write_text(_CLEAN_CUT)
    return cbl, cut


def test_lint_infers_program_from_cut_sibling(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _, cut = _write_pair(tmp_path)
    exit_code = main(["lint", "--cut", str(cut)])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "no problems found" in out


def test_lint_infers_cut_from_program_sibling(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cbl, _ = _write_pair(tmp_path)
    exit_code = main(["lint", str(cbl)])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "no problems found" in out


def test_lint_reports_a_clean_error_when_no_sibling_program_exists(
    tmp_path, capsys, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    cut = tmp_path / "ORPHAN.cut"
    cut.write_text(_CLEAN_CUT)
    exit_code = main(["lint", "--cut", str(cut)])
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "no COBOL source found beside" in out
    assert "pass the program path explicitly" in out


def test_lint_directory_discovery_runs_every_cut_file(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_pair(tmp_path, stem="ONE")
    _write_pair(tmp_path, stem="TWO")
    exit_code = main(["lint"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "== " in out and "ONE.cut" in out and "TWO.cut" in out
    assert "2 suite(s) checked, 0 .cut file(s) skipped" in out


def test_lint_directory_discovery_with_no_cut_files_is_a_clean_error(
    tmp_path, capsys, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    exit_code = main(["lint"])
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "no .cut files found under" in out


def test_lint_directory_discovery_skips_unpaired_cut_and_reports_it(
    tmp_path, capsys, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    _write_pair(tmp_path, stem="PAIRED")
    (tmp_path / "ORPHAN.cut").write_text(_CLEAN_CUT)
    exit_code = main(["lint"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "1 suite(s) checked, 1 .cut file(s) skipped" in out


def test_run_and_lint_explicit_flags_are_unaffected_by_inference(
    tmp_path, capsys, monkeypatch
):
    """Byte-for-byte regression guard: passing both program and --cut
    explicitly must never touch the new inference/discovery code paths."""
    monkeypatch.chdir(tmp_path)
    cbl, cut = _write_pair(tmp_path)
    exit_code = main(["lint", str(cbl), "--cut", str(cut)])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "no problems found" in out
    assert "==" not in out  # directory-mode banner never printed


def test_config_file_supplies_copybook_path(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "copybooks").mkdir()
    (tmp_path / "copybooks" / "GREETING.cpy").write_text(
        "       01 WS-GREETING PIC X(5) VALUE 'HELLO'.\n"
    )
    cbl = tmp_path / "COPYPROG.cbl"
    cbl.write_text(
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. COPYPROG.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       COPY GREETING.\n"
        "       PROCEDURE DIVISION.\n"
        "       0000-MAIN-PROCESS.\n"
        "           STOP RUN.\n"
    )
    cut = tmp_path / "COPYPROG.cut"
    cut.write_text('TESTSUITE "s"\n\nTESTCASE "c"\n    PERFORM 0000-MAIN-PROCESS\n')
    (tmp_path / "mockymock.toml").write_text('copybook_path = ["copybooks"]\n')

    exit_code = main(["lint", str(cbl), "--cut", str(cut)])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "not found in search paths" not in out


def test_explicit_copybook_path_flag_overrides_config_file(
    tmp_path, capsys, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "real-copybooks").mkdir()
    (tmp_path / "real-copybooks" / "GREETING.cpy").write_text(
        "       01 WS-GREETING PIC X(5) VALUE 'HELLO'.\n"
    )
    cbl = tmp_path / "COPYPROG.cbl"
    cbl.write_text(
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. COPYPROG.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       COPY GREETING.\n"
        "       PROCEDURE DIVISION.\n"
        "       0000-MAIN-PROCESS.\n"
        "           STOP RUN.\n"
    )
    cut = tmp_path / "COPYPROG.cut"
    cut.write_text('TESTSUITE "s"\n\nTESTCASE "c"\n    PERFORM 0000-MAIN-PROCESS\n')
    (tmp_path / "mockymock.toml").write_text('copybook_path = ["does-not-exist"]\n')

    exit_code = main(
        [
            "lint",
            str(cbl),
            "--cut",
            str(cut),
            "--copybook-path",
            str(tmp_path / "real-copybooks"),
        ]
    )
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "not found in search paths" not in out


def test_malformed_config_file_is_a_clean_error_not_a_traceback(
    tmp_path, capsys, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    cbl, cut = _write_pair(tmp_path)
    (tmp_path / "mockymock.toml").write_text("copybook_path = [\n")
    exit_code = main(["lint", str(cbl), "--cut", str(cut)])
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "could not parse" in out


def test_setup_help_documents_rebuild_flag(capsys):
    from mockymock.cli.main import build_parser

    parser = build_parser()
    setup_parser = parser._subparsers._group_actions[0].choices["setup"]
    help_text = setup_parser.format_help()
    assert "--rebuild" in help_text
    assert "Force a fresh image build" in help_text


def test_top_level_help_groups_commands(capsys):
    from mockymock.cli.main import build_parser

    help_text = build_parser().format_help()
    assert "Everyday:" in help_text
    assert "Diagnosing a failure:" in help_text
    assert "Advanced:" in help_text


def test_per_pair_report_path_keeps_same_stem_suites_apart(tmp_path):
    from mockymock.cli.main import _per_pair_report_path

    root = tmp_path / "tests"
    assert _per_pair_report_path("out/report.xml", root / "PROG.cut", root) == str(
        Path("out/report-PROG.xml")
    )
    one = _per_pair_report_path("out/report.xml", root / "svc1" / "PROG.cut", root)
    two = _per_pair_report_path("out/report.xml", root / "svc2" / "PROG.cut", root)
    assert one == str(Path("out/report-svc1-PROG.xml"))
    assert two == str(Path("out/report-svc2-PROG.xml"))


def test_malformed_config_file_does_not_break_commands_that_never_read_it(
    tmp_path, capsys, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "mockymock.toml").write_text("copybook_path = [\n")
    exit_code = main(["explain", "UNRESOLVED_COPYBOOK"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "could not parse" not in out


def test_malformed_config_file_keeps_collect_json_machine_readable(
    tmp_path, capsys, monkeypatch
):
    import json

    monkeypatch.chdir(tmp_path)
    _, cut = _write_pair(tmp_path)
    (tmp_path / "mockymock.toml").write_text("copybook_path = [\n")
    exit_code = main(["collect", "--cut", str(cut), "--json"])
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "could not parse" in json.loads(out)["error"]


def test_malformed_config_file_reported_on_stderr_for_json_only_stdout_commands(
    tmp_path, capsys, monkeypatch
):
    # `fixtures` promises stdout is exactly the JSON document (or nothing,
    # on a gate failure) -- a config error must go to stderr instead, the
    # same convention its own "no such file" gate uses.
    monkeypatch.chdir(tmp_path)
    (tmp_path / "mockymock.toml").write_text("copybook_path = [\n")
    exit_code = main(["fixtures", "MISSING.cbl"])
    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert "could not parse" in captured.err
