"""`mockymock run PROG.cut` takes the suite in the program's place and
infers the program (b96e91a). The other program + suite commands said
"no .cut file found for PROG.cut" instead; they share the same
resolution now."""

import pytest

from mockymock.cli.main import main

PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-X PIC 9 VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 1 TO WS-X.
"""

SUITE = """\
TESTSUITE "prog"

TESTCASE "sets x"
    PERFORM MAIN-PARA
    EXPECT WS-X TO BE 1
"""


@pytest.fixture
def pair(tmp_path, monkeypatch):
    (tmp_path / "PROG.cbl").write_text(PROGRAM, encoding="utf-8")
    (tmp_path / "PROG.cut").write_text(SUITE, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_lint_takes_a_cut_as_its_program_argument(pair, capsys):
    assert main(["lint", "PROG.cut"]) == 0
    assert "no problems found" in capsys.readouterr().out


@pytest.mark.parametrize("command", ["mutate", "report", "export"])
def test_other_commands_infer_the_program_from_the_cut(pair, capsys, command):
    from mockymock.cli.main import _resolve_program_and_cut, build_parser

    args = build_parser().parse_args([command, "PROG.cut"])
    resolved = _resolve_program_and_cut(f"mockymock {command}", args)
    assert resolved is not None, capsys.readouterr().out
    source, cut = resolved
    assert (source.name, cut.name) == ("PROG.cbl", "PROG.cut")
