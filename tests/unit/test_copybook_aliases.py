"""project/copybook_aliases.py: copybooks exported under a name the search
cannot match as written (`gttlbi0a.copy` for COPY GTTLBI0A) are staged as
`MEMBER.cpy`, automatically by case and extension or explicitly through
`copybook_aliases`."""

import pytest

from mockymock.cli.main import main
from mockymock.project import copybook_aliases
from mockymock.project.config import ConfigError, load_config
from mockymock.project.copybook_aliases import (
    DEFAULT_COPYBOOK_EXTENSIONS,
    automatic_aliases,
    stage_copybook_aliases,
)


def _write(path, text=""):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


# -- automatic matching -------------------------------------------------------


def test_lower_case_export_with_unsearched_extension_is_aliased(tmp_path):
    source = _write(tmp_path / "copylib" / "gttlbi0a.copy")
    found = automatic_aliases([str(tmp_path / "copylib")], DEFAULT_COPYBOOK_EXTENSIONS)
    assert found == {"GTTLBI0A": source}


@pytest.mark.parametrize(
    "name", ["dmtren0a.dcl", "Gttlbi0a.cpy", "member1", "MEMBER2.TXT", "abc.INC"]
)
def test_default_extensions_cover_common_exports(tmp_path, name):
    _write(tmp_path / name)
    found = automatic_aliases([str(tmp_path)], DEFAULT_COPYBOOK_EXTENSIONS)
    assert list(found) == [name.partition(".")[0].upper()]


@pytest.mark.parametrize("name", ["GREETING.cpy", "GREETING.CBL", "GREETING"])
def test_a_file_the_search_already_matches_is_not_staged(tmp_path, name):
    _write(tmp_path / name)
    assert automatic_aliases([str(tmp_path)], DEFAULT_COPYBOOK_EXTENSIONS) == {}


def test_extension_outside_the_list_is_not_aliased(tmp_path):
    _write(tmp_path / "gttlbi0a.bak")
    assert automatic_aliases([str(tmp_path)], DEFAULT_COPYBOOK_EXTENSIONS) == {}


def test_extension_list_is_compared_without_case(tmp_path):
    source = _write(tmp_path / "gttlbi0a.COPY")
    assert automatic_aliases([str(tmp_path)], (".copy",)) == {"GTTLBI0A": source}


def test_empty_extension_list_turns_matching_off(tmp_path):
    _write(tmp_path / "gttlbi0a.copy")
    assert automatic_aliases([str(tmp_path)], ()) == {}


def test_first_search_directory_wins_a_member(tmp_path):
    first = _write(tmp_path / "a" / "gttlbi0a.copy", "first")
    _write(tmp_path / "b" / "gttlbi0a.dcl", "second")
    found = automatic_aliases(
        [str(tmp_path / "a"), str(tmp_path / "b")], DEFAULT_COPYBOOK_EXTENSIONS
    )
    assert found == {"GTTLBI0A": first}


def test_subdirectories_and_missing_directories_are_skipped(tmp_path):
    (tmp_path / "lib" / "nested.copy").mkdir(parents=True)
    found = automatic_aliases(
        [str(tmp_path / "lib"), str(tmp_path / "absent")], DEFAULT_COPYBOOK_EXTENSIONS
    )
    assert found == {}


# -- staging ------------------------------------------------------------------


def test_nothing_to_stage_returns_none(tmp_path):
    _write(tmp_path / "GREETING.cpy")
    assert stage_copybook_aliases([str(tmp_path)]) is None


def test_staging_names_each_member_as_the_search_expects(tmp_path):
    _write(tmp_path / "lib" / "gttlbi0a.copy", "       01 A PIC X.\n")
    staged = stage_copybook_aliases([str(tmp_path / "lib")])
    assert staged is not None
    assert staged.parent == copybook_aliases.STAGING_ROOT
    assert [p.name for p in staged.iterdir()] == ["GTTLBI0A.cpy"]
    assert (staged / "GTTLBI0A.cpy").read_text() == "       01 A PIC X.\n"


def test_unchanged_copylib_reuses_its_staging_directory(tmp_path):
    _write(tmp_path / "lib" / "gttlbi0a.copy")
    first = stage_copybook_aliases([str(tmp_path / "lib")])
    assert stage_copybook_aliases([str(tmp_path / "lib")]) == first


def test_changed_copylib_gets_a_new_staging_directory(tmp_path):
    source = _write(tmp_path / "lib" / "gttlbi0a.copy", "old")
    first = stage_copybook_aliases([str(tmp_path / "lib")])
    source.write_text("a longer body")
    second = stage_copybook_aliases([str(tmp_path / "lib")])
    assert second != first
    assert (second / "GTTLBI0A.cpy").read_text() == "a longer body"


def test_explicit_alias_wins_over_automatic_match(tmp_path):
    _write(tmp_path / "lib" / "gttlbi0a.copy", "automatic")
    chosen = _write(tmp_path / "export" / "member-0042.txt", "explicit")
    staged = stage_copybook_aliases([str(tmp_path / "lib")], {"gttlbi0a": str(chosen)})
    assert (staged / "GTTLBI0A.cpy").read_text() == "explicit"


def test_staging_copies_when_hard_links_fail(tmp_path, monkeypatch):
    def no_links(source, target):
        raise OSError("cross-device link")

    monkeypatch.setattr(copybook_aliases.os, "link", no_links)
    _write(tmp_path / "lib" / "gttlbi0a.copy", "copied")
    staged = stage_copybook_aliases([str(tmp_path / "lib")])
    assert (staged / "GTTLBI0A.cpy").read_text() == "copied"


# -- config -------------------------------------------------------------------


def test_config_aliases_resolve_relative_to_the_config_file(tmp_path):
    _write(tmp_path / "export" / "m0042.txt")
    _write(
        tmp_path / "mockymock.toml",
        '[copybook_aliases]\ngttlbi0a = "export/m0042.txt"\n',
    )
    nested = tmp_path / "src"
    nested.mkdir()
    config = load_config(nested)
    assert config.copybook_aliases == {
        "GTTLBI0A": str(tmp_path / "export" / "m0042.txt")
    }


def test_config_alias_to_a_missing_file_is_an_error(tmp_path):
    _write(tmp_path / "mockymock.toml", '[copybook_aliases]\nGTTLBI0A = "nope.txt"\n')
    with pytest.raises(ConfigError, match="not a file"):
        load_config(tmp_path)


@pytest.mark.parametrize(
    "body",
    [
        'copybook_aliases = "GTTLBI0A"\n',
        '[copybook_aliases]\n"../X" = "a.txt"\n',
        "[copybook_aliases]\nGTTLBI0A = 3\n",
    ],
)
def test_config_alias_table_shape_is_validated(tmp_path, body):
    _write(tmp_path / "a.txt")
    _write(tmp_path / "mockymock.toml", body)
    with pytest.raises(ConfigError, match="copybook_aliases"):
        load_config(tmp_path)


def test_config_extensions_gain_a_leading_dot(tmp_path):
    _write(tmp_path / "mockymock.toml", 'copybook_extensions = ["copy", ".dcl", ""]\n')
    assert load_config(tmp_path).copybook_extensions == (".copy", ".dcl", "")


@pytest.mark.parametrize(
    "body", ['copybook_extensions = ".copy"\n', 'copybook_extensions = ["a/b"]\n']
)
def test_config_extensions_shape_is_validated(tmp_path, body):
    _write(tmp_path / "mockymock.toml", body)
    with pytest.raises(ConfigError, match="copybook_extensions"):
        load_config(tmp_path)


def test_unset_extensions_mean_the_defaults(tmp_path):
    assert load_config(tmp_path).copybook_extensions is None


def test_cobol_yml_mockymock_section_carries_aliases(tmp_path):
    _write(tmp_path / "export" / "m0042.txt")
    _write(
        tmp_path / "cobol.yml",
        "mockymock:\n  copybook_aliases:\n    GTTLBI0A: export/m0042.txt\n",
    )
    config = load_config(tmp_path)
    assert config.copybook_aliases == {
        "GTTLBI0A": str(tmp_path / "export" / "m0042.txt")
    }


# -- end to end through the CLI ----------------------------------------------


_PROGRAM = (
    "       IDENTIFICATION DIVISION.\n"
    "       PROGRAM-ID. COPYPROG.\n"
    "       DATA DIVISION.\n"
    "       WORKING-STORAGE SECTION.\n"
    "       COPY GTTLBI0A.\n"
    "       PROCEDURE DIVISION.\n"
    "       0000-MAIN-PROCESS.\n"
    "           STOP RUN.\n"
)
_COPYBOOK = "       01 WS-GREETING PIC X(5) VALUE 'HELLO'.\n"


def _pair(tmp_path):
    cbl = _write(tmp_path / "src" / "COPYPROG.cbl", _PROGRAM)
    cut = _write(
        tmp_path / "src" / "COPYPROG.cut",
        'TESTSUITE "s"\n\nTESTCASE "c"\n    PERFORM 0000-MAIN-PROCESS\n',
    )
    return cbl, cut


def test_lint_finds_a_lower_case_copy_export(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cbl, cut = _pair(tmp_path)
    _write(tmp_path / "copylib" / "gttlbi0a.copy", _COPYBOOK)
    exit_code = main(["lint", str(cbl), "--cut", str(cut)])
    out = capsys.readouterr().out
    assert "not found in search paths" not in out
    assert exit_code == 0


def test_explicit_copybook_path_is_aliased_too(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cbl, cut = _pair(tmp_path)
    _write(tmp_path / "far" / "away" / "Gttlbi0a.dcl", _COPYBOOK)
    exit_code = main(
        ["lint", str(cbl), "--cut", str(cut), "--copybook-path", "far/away"]
    )
    assert "not found in search paths" not in capsys.readouterr().out
    assert exit_code == 0


def test_matching_turned_off_falls_back_to_the_hint(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cbl, cut = _pair(tmp_path)
    _write(tmp_path / "copylib" / "gttlbi0a.copy", _COPYBOOK)
    _write(tmp_path / "mockymock.toml", "copybook_extensions = []\n")
    exit_code = main(["lint", str(cbl), "--cut", str(cut)])
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "not found in search paths" in out
    assert "copybook_aliases" in out


def test_config_alias_resolves_a_file_named_nothing_like_the_member(
    tmp_path, capsys, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    cbl, cut = _pair(tmp_path)
    _write(tmp_path / "export" / "member-0042.txt", _COPYBOOK)
    _write(
        tmp_path / "mockymock.toml",
        '[copybook_aliases]\nGTTLBI0A = "export/member-0042.txt"\n',
    )
    exit_code = main(["lint", str(cbl), "--cut", str(cut)])
    assert "not found in search paths" not in capsys.readouterr().out
    assert exit_code == 0


def test_unstageable_copylib_leaves_the_search_unchanged(tmp_path, capsys, monkeypatch):
    def fail(*args, **kwargs):
        raise OSError("read-only temp folder")

    monkeypatch.setattr(copybook_aliases, "stage_copybook_aliases", fail)
    monkeypatch.chdir(tmp_path)
    cbl, cut = _pair(tmp_path)
    _write(tmp_path / "copylib" / "gttlbi0a.copy", _COPYBOOK)
    exit_code = main(["lint", str(cbl), "--cut", str(cut)])
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "could not stage copybook aliases" in captured.err
