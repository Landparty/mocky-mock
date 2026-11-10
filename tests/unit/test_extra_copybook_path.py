"""`--extra-copybook-path`: directories added after the --copybook-path /
config file list instead of replacing it (mocky-mock-vscode#130: the
extension passes zapp.yml's directories this way, so the project's own
copybook_path list is kept)."""

import argparse

from mockymock.cli.main import _apply_config_to_args, build_parser, main
from mockymock.project.config import MockymockConfig
from mockymock.project.discovery import SYSTEM_COPYBOOK_DIR

PROGRAM = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TWOCPY.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
           COPY CPYA.
           COPY CPYB.
       PROCEDURE DIVISION.
       0000-MAIN.
           MOVE 1 TO A-FLD
           MOVE 2 TO B-FLD
           GOBACK.
"""
SUITE = """TESTSUITE "two copybooks"
TESTCASE "moves"
    PERFORM 0000-MAIN
    EXPECT A-FLD TO BE 1
"""


def _args(*argv: str) -> argparse.Namespace:
    return build_parser().parse_args(["lint", "P.cbl", *argv])


def test_extra_paths_follow_the_config_list():
    args = _args("--extra-copybook-path", "zapp")
    args._config = MockymockConfig(copybook_path=("cfg1", "cfg2"))
    _apply_config_to_args(args)
    assert args.copybook_path == ["cfg1", "cfg2", "zapp", str(SYSTEM_COPYBOOK_DIR)]


def test_extra_paths_follow_an_explicit_list_and_skip_duplicates():
    args = _args("--copybook-path", "mine", "--extra-copybook-path", "mine")
    args._config = MockymockConfig(copybook_path=("cfg",))
    _apply_config_to_args(args)
    assert args.copybook_path == ["mine", str(SYSTEM_COPYBOOK_DIR)]


def test_lint_keeps_the_config_copybooks_with_an_extra_path(
    tmp_path, monkeypatch, capsys
):
    for name, field in (("copybooks", "A-FLD"), ("shared", "B-FLD")):
        (tmp_path / name).mkdir()
        cpy = "CPYA" if name == "copybooks" else "CPYB"
        (tmp_path / name / f"{cpy}.cpy").write_text(
            f"       01  {field}  PIC 9.\n", encoding="utf-8"
        )
    (tmp_path / "zapp").mkdir()
    (tmp_path / "mockymock.toml").write_text(
        'copybook_path = ["copybooks", "shared"]\n', encoding="utf-8"
    )
    (tmp_path / "TWOCPY.cbl").write_text(PROGRAM, encoding="utf-8")
    (tmp_path / "TWOCPY.cut").write_text(SUITE, encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    lint = ["lint", "TWOCPY.cbl", "--cut", "TWOCPY.cut"]
    assert main([*lint, "--extra-copybook-path", "zapp"]) == 0
    assert "no problems found" in capsys.readouterr().out
    # --copybook-path still replaces the config's list, as documented.
    assert main([*lint, "--copybook-path", "zapp"]) == 1
    assert "CPYB" in capsys.readouterr().out
