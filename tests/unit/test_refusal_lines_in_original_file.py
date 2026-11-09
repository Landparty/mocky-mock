"""Issue #241: refusals and STOP RUN/GOBACK warnings name lines of the
`.cbl` the user has open (or `line N of COPYBOOK`), not of the
copybook-expanded source."""

from __future__ import annotations

from mockymock.cli.main import main
from mockymock.engine.checks import source_line_relabeler

COPYBOOK = "".join(
    f"           05 CUST-F{n}            PIC X(2).\n" for n in range(1, 7)
)

PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROG8.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  CUST-REC.
           COPY CUSTWS.
       01  WS-RC                PIC 9(2) VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           CALL "GETCUST" USING CUST-REC WS-RC
           CALL "LOGIT" USING CUST-REC
           GOBACK.
"""

CUT = """\
TESTSUITE "p8"
TESTCASE "a"
    MOCK CALL "GETCUST"
        MOVE 0 TO WS-RC
    END-MOCK
    PERFORM MAIN-PARA
    EXPECT WS-RC TO BE 0
"""


def _project(tmp_path):
    (tmp_path / "copybooks").mkdir()
    (tmp_path / "copybooks" / "CUSTWS.cpy").write_text(COPYBOOK)
    (tmp_path / "PROG8.cbl").write_text(PROGRAM)
    (tmp_path / "PROG8.cut").write_text(CUT)
    return tmp_path / "PROG8.cbl", tmp_path / "PROG8.cut"


def test_lint_refusal_names_the_original_line(tmp_path, capsys) -> None:
    program, cut = _project(tmp_path)
    main(["lint", str(program), "--cut", str(cut)])
    out = capsys.readouterr().out
    assert "UNMOCKED_CALL" in out
    assert "CALL boundary at line 11 " in out  # CALL "LOGIT", not line 16


def test_generate_goback_warning_names_the_original_line(tmp_path, capsys) -> None:
    program, _ = _project(tmp_path)
    assert main(["generate", str(program), "-o", str(tmp_path / "g.cut")]) == 0
    assert "GOBACK in paragraph 'MAIN-PARA' (line 12)" in capsys.readouterr().out


def test_relabeler_names_copybook_lines_and_skips_cut_lines() -> None:
    relabel = source_line_relabeler({3: ("<main>", 2), 4: ("/x/CALC.CPY", 1)})
    assert relabel("at line 3 and line 4") == "at line 2 and line 1 of CALC.CPY"
    assert relabel(".cut line 3: no") == ".cut line 3: no"
