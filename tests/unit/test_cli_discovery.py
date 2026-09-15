"""mockymock/cli/discovery.py: sibling .cut/.cbl inference and
directory-wide .cut discovery. See
docs/2026-09-15-cli-ergonomics-design.md."""

import pytest

from mockymock.cli.discovery import (
    DiscoveryError,
    discover_cut_files,
    resolve_cut_path,
    resolve_program_path,
)


def test_resolve_program_path_explicit_value_is_returned_verbatim(tmp_path):
    cut_path = tmp_path / "P.cut"
    result = resolve_program_path("OTHER.cbl", cut_path)
    from pathlib import Path

    assert result == Path("OTHER.cbl")


def test_resolve_program_path_finds_sibling_cbl(tmp_path):
    cut_path = tmp_path / "ORDRPROC.cut"
    cbl_path = tmp_path / "ORDRPROC.cbl"
    cbl_path.write_text("")
    assert resolve_program_path(None, cut_path) == cbl_path


def test_resolve_program_path_finds_sibling_cob_when_no_cbl(tmp_path):
    cut_path = tmp_path / "ORDRPROC.cut"
    cob_path = tmp_path / "ORDRPROC.cob"
    cob_path.write_text("")
    assert resolve_program_path(None, cut_path) == cob_path


def test_resolve_program_path_prefers_cbl_over_cob(tmp_path):
    cut_path = tmp_path / "ORDRPROC.cut"
    cbl_path = tmp_path / "ORDRPROC.cbl"
    cbl_path.write_text("")
    (tmp_path / "ORDRPROC.cob").write_text("")
    assert resolve_program_path(None, cut_path) == cbl_path


def test_resolve_program_path_raises_and_names_every_candidate_tried(tmp_path):
    cut_path = tmp_path / "MISSING.cut"
    with pytest.raises(DiscoveryError) as exc_info:
        resolve_program_path(None, cut_path)
    message = str(exc_info.value)
    assert "MISSING.cbl" in message
    assert "MISSING.cob" in message
    assert "pass the program path explicitly" in message


def test_resolve_cut_path_explicit_value_is_returned_verbatim(tmp_path):
    from pathlib import Path

    program_path = tmp_path / "P.cbl"
    assert resolve_cut_path("OTHER.cut", program_path) == Path("OTHER.cut")


def test_resolve_cut_path_finds_sibling(tmp_path):
    program_path = tmp_path / "ORDRPROC.cbl"
    cut_path = tmp_path / "ORDRPROC.cut"
    cut_path.write_text("")
    assert resolve_cut_path(None, program_path) == cut_path


def test_resolve_cut_path_raises_when_no_sibling_exists(tmp_path):
    program_path = tmp_path / "ORDRPROC.cbl"
    with pytest.raises(DiscoveryError) as exc_info:
        resolve_cut_path(None, program_path)
    assert "pass --cut explicitly" in str(exc_info.value)


def test_discover_cut_files_finds_nested_cut_files_sorted(tmp_path):
    (tmp_path / "b").mkdir()
    (tmp_path / "a").mkdir()
    (tmp_path / "b" / "SECOND.cut").write_text("")
    (tmp_path / "a" / "FIRST.cut").write_text("")
    (tmp_path / "TOP.cut").write_text("")
    result = discover_cut_files(tmp_path)
    assert result == sorted(result)
    assert {p.name for p in result} == {"FIRST.cut", "SECOND.cut", "TOP.cut"}


def test_discover_cut_files_skips_excluded_directories(tmp_path):
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "VENDORED.cut").write_text("")
    (tmp_path / "REAL.cut").write_text("")
    result = discover_cut_files(tmp_path)
    assert [p.name for p in result] == ["REAL.cut"]


def test_discover_cut_files_only_excludes_directories_below_the_root(tmp_path):
    # A test root that itself lives under an excluded name (an absolute
    # test_root in a CI checkout at .../build/tests) must still be scanned.
    root = tmp_path / "build" / "tests"
    root.mkdir(parents=True)
    (root / "REAL.cut").write_text("")
    (root / "dist").mkdir()
    (root / "dist" / "VENDORED.cut").write_text("")
    result = discover_cut_files(root)
    assert [p.name for p in result] == ["REAL.cut"]


def test_discover_cut_files_returns_empty_list_for_missing_directory(tmp_path):
    assert discover_cut_files(tmp_path / "does-not-exist") == []


def test_discover_cut_files_returns_empty_list_when_none_found(tmp_path):
    assert discover_cut_files(tmp_path) == []
