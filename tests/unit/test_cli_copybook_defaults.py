"""docs/2026-09-15-copybook-discovery-defaults-design.md: default
copybook search directories and the actionable did-you-mean hint on a
CopybookNotFoundError."""

from mockymock.cli.discovery import copybook_not_found_hint, effective_copybook_paths
from mockymock.cli.main import main


def test_effective_copybook_paths_appends_copybooks_subdirectory(tmp_path):
    program = tmp_path / "PROG.cbl"
    program.write_text("")
    (tmp_path / "copybooks").mkdir()
    assert effective_copybook_paths(program, []) == [str(tmp_path / "copybooks")]


def test_effective_copybook_paths_no_default_when_subdirectory_absent(tmp_path):
    program = tmp_path / "PROG.cbl"
    program.write_text("")
    assert effective_copybook_paths(program, []) == []


def test_effective_copybook_paths_does_not_default_to_programs_own_directory(
    tmp_path,
):
    """The program's own directory always exists trivially -- including
    it as a default would turn every COPY-bearing program into an
    implicit copybook search even when none was ever configured. See
    the docstring on effective_copybook_paths for the regression this
    guards."""
    program = tmp_path / "PROG.cbl"
    program.write_text("")
    result = effective_copybook_paths(program, [])
    assert str(tmp_path) not in result


def test_effective_copybook_paths_preserves_explicit_entries_and_order(tmp_path):
    program = tmp_path / "PROG.cbl"
    program.write_text("")
    (tmp_path / "copybooks").mkdir()
    result = effective_copybook_paths(program, ["explicit-dir"])
    assert result == ["explicit-dir", str(tmp_path / "copybooks")]


def test_effective_copybook_paths_does_not_duplicate_an_already_present_default(
    tmp_path,
):
    program = tmp_path / "PROG.cbl"
    program.write_text("")
    copybooks_dir = tmp_path / "copybooks"
    copybooks_dir.mkdir()
    result = effective_copybook_paths(program, [str(copybooks_dir)])
    assert result == [str(copybooks_dir)]


def test_copybook_not_found_hint_names_both_remedies():
    hint = copybook_not_found_hint()
    assert "--copybook-path" in hint
    assert "[tool.mockymock]" in hint
    # The universal file every tool in the family reads (config.py).
    assert "cobol.yml" in hint
    assert hint.startswith("    ")  # continuation-line convention


def _copy_bearing_pair(tmp_path, *, with_copybook: bool):
    if with_copybook:
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
    return cbl, cut


def test_lint_resolves_copybook_from_default_subdirectory_with_no_flag(
    tmp_path, capsys, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    cbl, cut = _copy_bearing_pair(tmp_path, with_copybook=True)
    exit_code = main(["lint", str(cbl), "--cut", str(cut)])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "not found in search paths" not in out


def test_lint_missing_copybook_gets_actionable_hint(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cbl, cut = _copy_bearing_pair(tmp_path, with_copybook=False)
    (tmp_path / "copybooks").mkdir()  # exists, but GREETING.cpy is missing from it
    exit_code = main(["lint", str(cbl), "--cut", str(cut)])
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "not found in search paths" in out
    assert "--copybook-path" in out
    assert "[tool.mockymock]" in out


def test_generate_with_data_missing_copybook_gets_actionable_hint(
    tmp_path, capsys, monkeypatch
):
    """`--with-data` resolves the program's layout before the expansion
    gate runs, and cobol-parser wraps the not-found error -- the hint
    must still be appended there."""
    monkeypatch.chdir(tmp_path)
    cbl, cut = _copy_bearing_pair(tmp_path, with_copybook=False)
    (tmp_path / "copybooks").mkdir()
    exit_code = main(["generate", str(cbl), "--with-data", "-o", str(cut), "--force"])
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "not found in search paths" in out
    assert "--copybook-path" in out


def test_dclgen_and_include_folders_are_searched_by_default(tmp_path):
    """`EXEC SQL INCLUDE` members usually ship in a DCLGEN folder beside
    the copylib (sweep 2026-10-29: DMTREN0A)."""
    (tmp_path / "src").mkdir()
    program = tmp_path / "src" / "PROG.cbl"
    program.write_text("")
    (tmp_path / "dclgen").mkdir()
    (tmp_path / "src" / "include").mkdir()
    assert effective_copybook_paths(program, []) == [
        str(tmp_path / "src" / "include"),
        str(tmp_path / "dclgen"),
    ]


def test_hint_names_a_file_the_search_cannot_match(tmp_path):
    """A mainframe export spelled `gttlbi0a.copy`: wrong case and an
    extension cobol-parser never tries, so no search path finds it."""
    from cobolparser.preprocess import CopybookNotFoundError

    (tmp_path / "copylib").mkdir()
    (tmp_path / "copylib" / "gttlbi0a.copy").write_text("")
    (tmp_path / "dclgen").mkdir()
    (tmp_path / "dclgen" / "GTTLBI0A.dcl").write_text("")
    (tmp_path / "copylib" / "OTHER.cpy").write_text("")
    error = CopybookNotFoundError("GTTLBI0A", [str(tmp_path / "copylib")])
    hint = copybook_not_found_hint(error)
    assert "gttlbi0a.copy" in hint
    assert "GTTLBI0A.dcl" in hint
    assert "OTHER" not in hint
    assert "GTTLBI0A.cpy" in hint


def test_hint_follows_a_wrapped_not_found_error(tmp_path):
    from cobolparser.preprocess import CopybookNotFoundError

    (tmp_path / "copybooks").mkdir()
    (tmp_path / "copybooks" / "Greeting.CPY").write_text("")
    cause = CopybookNotFoundError("GREETING", [str(tmp_path / "copybooks")])
    wrapper = RuntimeError("unresolved copybook dependency")
    wrapper.__cause__ = cause
    assert "Greeting.CPY" in copybook_not_found_hint(wrapper)


def test_hint_stays_one_line_when_nothing_looks_like_the_member(tmp_path):
    from cobolparser.preprocess import CopybookNotFoundError

    (tmp_path / "copybooks").mkdir()
    error = CopybookNotFoundError("GREETING", [str(tmp_path / "copybooks")])
    assert copybook_not_found_hint(error) == copybook_not_found_hint()
