"""docs/2026-09-15-actionable-refusals-and-fill-design.md: suggested_fix
on lint/run's UNMOCKED_* output, and `generate --fill`."""

from mockymock.cli.main import main

_PROGRAM = (
    "       IDENTIFICATION DIVISION.\n"
    "       PROGRAM-ID. P.\n"
    "       DATA DIVISION.\n"
    "       WORKING-STORAGE SECTION.\n"
    "       01 WS-EOF PIC X VALUE 'N'.\n"
    "       PROCEDURE DIVISION.\n"
    "       0000-MAIN-PROCESS.\n"
    "           OPEN INPUT INV-FILE.\n"
    "           READ INV-FILE\n"
    "               AT END MOVE 'Y' TO WS-EOF\n"
    "           END-READ.\n"
    "           CLOSE INV-FILE.\n"
    "           STOP RUN.\n"
)

_PARTIALLY_MOCKED_CUT = (
    'TESTSUITE "s"\n'
    "\n"
    'TESTCASE "opens and closes"\n'
    "    MOCK OPEN INV-FILE\n"
    "    END-MOCK\n"
    "    MOCK CLOSE INV-FILE\n"
    "    END-MOCK\n"
    "    PERFORM 0000-MAIN-PROCESS\n"
)

_FULLY_MOCKED_CUT = (
    'TESTSUITE "s"\n'
    "\n"
    'TESTCASE "opens and closes"\n'
    "    MOCK OPEN INV-FILE\n"
    "    END-MOCK\n"
    "    MOCK CLOSE INV-FILE\n"
    "    END-MOCK\n"
    "    MOCK READ INV-FILE\n"
    "    END-MOCK\n"
    "    PERFORM 0000-MAIN-PROCESS\n"
)


def _write_pair(tmp_path, cut_text):
    cbl = tmp_path / "P.cbl"
    cbl.write_text(_PROGRAM)
    cut = tmp_path / "P.cut"
    cut.write_text(cut_text)
    return cbl, cut


def test_lint_appends_suggested_fix_for_unmocked_read(tmp_path, capsys):
    cbl, cut = _write_pair(tmp_path, _PARTIALLY_MOCKED_CUT)
    exit_code = main(["lint", str(cbl), "--cut", str(cut)])
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "UNMOCKED_FILE_OP" in out
    assert "Add to this TESTCASE:" in out
    assert "MOCK READ INV-FILE" in out
    assert "END-MOCK" in out


def test_lint_no_suggested_fix_block_when_fully_mocked(tmp_path, capsys):
    cbl, cut = _write_pair(tmp_path, _FULLY_MOCKED_CUT)
    exit_code = main(["lint", str(cbl), "--cut", str(cut)])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Add to this TESTCASE" not in out


def test_generate_fill_inserts_only_missing_mock_block(tmp_path, capsys):
    cbl, cut = _write_pair(tmp_path, _PARTIALLY_MOCKED_CUT)
    exit_code = main(["generate", str(cbl), "--fill", str(cut)])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "added 1 mock block(s) across 1 test case(s)" in out

    result = cut.read_text()
    assert "MOCK READ INV-FILE" in result
    # Everything that was already there is untouched.
    assert "MOCK OPEN INV-FILE" in result
    assert "MOCK CLOSE INV-FILE" in result
    assert result.count("END-MOCK") == 3


def test_generate_fill_is_idempotent(tmp_path, capsys):
    cbl, cut = _write_pair(tmp_path, _PARTIALLY_MOCKED_CUT)
    main(["generate", str(cbl), "--fill", str(cut)])
    capsys.readouterr()
    after_first = cut.read_text()

    exit_code = main(["generate", str(cbl), "--fill", str(cut)])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "added 0 mock block(s)" in out
    assert cut.read_text() == after_first


def test_generate_fill_leaves_fully_mocked_case_untouched(tmp_path, capsys):
    cbl, cut = _write_pair(tmp_path, _FULLY_MOCKED_CUT)
    original = cut.read_text()
    exit_code = main(["generate", str(cbl), "--fill", str(cut)])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "added 0 mock block(s) across 0 test case(s)" in out
    assert cut.read_text() == original


def test_generate_fill_rejects_with_data(tmp_path, capsys):
    cbl, cut = _write_pair(tmp_path, _PARTIALLY_MOCKED_CUT)
    exit_code = main(["generate", str(cbl), "--fill", str(cut), "--with-data"])
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "--fill is not valid together with --with-data" in out


def test_generate_fill_rejects_output_flag(tmp_path, capsys):
    cbl, cut = _write_pair(tmp_path, _PARTIALLY_MOCKED_CUT)
    exit_code = main(
        ["generate", str(cbl), "--fill", str(cut), "-o", str(tmp_path / "x.cut")]
    )
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "--fill is not valid together with -o/--output" in out


def test_generate_fill_missing_cut_file_reports_cleanly(tmp_path, capsys):
    cbl = tmp_path / "P.cbl"
    cbl.write_text(_PROGRAM)
    missing_cut = tmp_path / "MISSING.cut"
    exit_code = main(["generate", str(cbl), "--fill", str(missing_cut)])
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "no such file" in out


def test_generate_fill_preserves_line_endings_and_trailing_newline(tmp_path, capsys):
    cbl, cut = _write_pair(tmp_path, _PARTIALLY_MOCKED_CUT)
    main(["generate", str(cbl), "--fill", str(cut)])
    capsys.readouterr()
    result = cut.read_text()
    assert result.endswith("\n")
    assert "\r\n" not in result
