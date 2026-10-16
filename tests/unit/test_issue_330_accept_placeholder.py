"""Issue #330: the placeholder body for `MOCK ACCEPT <target>` (lint's
suggested fix, `generate --fill`, `--per-paragraph`) was always
`MOVE SPACES TO <target>`, which cobc rejects for a numeric or
numeric-edited target. It is now `INITIALIZE <target>`, legal for all."""

from mockymock.cli.main import main

PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ACC.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-NUM              PIC 9(4) VALUE 0.
       01  WS-ED               PIC ZZ9.
       01  WS-DBL              PIC 9(5) VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           ACCEPT WS-NUM
           ACCEPT WS-ED
           COMPUTE WS-DBL = WS-NUM * 2
           GOBACK.
"""

CUT = """\
TESTSUITE "f"
TESTCASE "a"
    PERFORM MAIN-PARA
    EXPECT WS-DBL TO BE 0
"""


def test_suggested_fix_and_fill_use_initialize(tmp_path, capsys):
    cbl = tmp_path / "ACC.cbl"
    cbl.write_text(PROGRAM)
    cut = tmp_path / "F.cut"
    cut.write_text(CUT)

    assert main(["lint", str(cbl), "--cut", str(cut)]) == 1
    printed = capsys.readouterr().out
    assert "INITIALIZE WS-NUM" in printed
    assert "MOVE SPACES" not in printed

    assert main(["generate", str(cbl), "--fill", str(cut)]) == 0
    capsys.readouterr()
    text = cut.read_text()
    assert "INITIALIZE WS-NUM" in text and "INITIALIZE WS-ED" in text
    assert "MOVE SPACES" not in text
    assert main(["lint", str(cbl), "--cut", str(cut)]) == 0
