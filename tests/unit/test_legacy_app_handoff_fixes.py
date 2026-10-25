"""Regression tests for copybook discovery from the legacy-application
testing handoff: a `cobol/` program with its copybooks in a sibling
`copybook/` folder must be found without an explicit --copybook-path.
"""

from __future__ import annotations

from pathlib import Path

from mockymock.cli.discovery import effective_copybook_paths


def test_sibling_copybook_folder_one_level_up_is_found(tmp_path: Path) -> None:
    """The legacy-application layout: cobol/PROG.cbl with copybook/*.cpy
    next to cobol/."""
    project = tmp_path / "project"
    cobol = project / "cobol"
    copybook = project / "copybook"
    cobol.mkdir(parents=True)
    copybook.mkdir()
    (copybook / "ACCTMAST.cpy").write_text("       01 X PIC X.\n")

    assert effective_copybook_paths(cobol / "PROG.cbl", []) == [str(copybook)]


def test_explicit_copybook_path_is_not_duplicated(tmp_path: Path) -> None:
    project = tmp_path / "project"
    cobol = project / "cobol"
    copybook = project / "copybook"
    cobol.mkdir(parents=True)
    copybook.mkdir()
    (copybook / "A.cpy").write_text("       01 X PIC X.\n")

    result = effective_copybook_paths(cobol / "PROG.cbl", [str(copybook)])

    assert result == [str(copybook)]
