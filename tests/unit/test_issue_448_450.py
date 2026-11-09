"""#448: `GO TO.` falls into a following section header; #450: a GO TO loop
counts as a loop for SQL / IMS / CICS sites."""

from __future__ import annotations

from cobolparser import parse_cobol

from mockymock.analysis.alter import alter_problem, alter_reset_lines
from mockymock.analysis.loops import goto_loop_paragraphs

ALTER_SRC = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. P.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-MSG PIC X(4).
       PROCEDURE DIVISION.
       MAIN-SEC SECTION.
       MAIN-PARA.
           ALTER SW-PARA TO PROCEED TO B-PARA
           PERFORM SW-PARA THRU EXIT-PARA
           GOBACK.
       SW-PARA.
           GO TO.
       NEXT-SEC SECTION.
           MOVE "FALL" TO WS-MSG.
       A-PARA.
           MOVE "A" TO WS-MSG.
       B-PARA.
           MOVE "B" TO WS-MSG.
       EXIT-PARA.
           EXIT.
"""


def test_go_to_dot_resets_to_the_following_section():
    ast = parse_cobol(ALTER_SRC).ast
    assert alter_problem(ast) is None
    assert alter_reset_lines(ast) == ["ALTER SW-PARA TO PROCEED TO NEXT-SEC"]


def test_go_to_dot_before_a_paragraph_still_resets_to_it():
    source = ALTER_SRC.replace("       NEXT-SEC SECTION.\n           MOVE \"FALL\" TO WS-MSG.\n", "")
    ast = parse_cobol(source).ast
    assert alter_reset_lines(ast) == ["ALTER SW-PARA TO PROCEED TO A-PARA"]


def test_go_to_dot_followed_only_by_a_section_is_accepted():
    source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. P.
       PROCEDURE DIVISION.
       MAIN-SEC SECTION.
       MAIN-PARA.
           ALTER SW-PARA TO PROCEED TO MAIN-PARA
           PERFORM SW-PARA
           GOBACK.
       SW-PARA.
           GO TO.
       LAST-SEC SECTION.
           DISPLAY "LAST".
"""
    ast = parse_cobol(source).ast
    assert alter_problem(ast) is None
    assert alter_reset_lines(ast) == ["ALTER SW-PARA TO PROCEED TO LAST-SEC"]


GOLOOP = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. GOLOOP.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-NAME   PIC X(20).
       01  WS-COUNT  PIC 9(4) VALUE 0.
           EXEC SQL INCLUDE SQLCA END-EXEC.
       PROCEDURE DIVISION.
       MAIN-PARA.
           EXEC SQL OPEN C1 END-EXEC.
       FETCH-LOOP.
           EXEC SQL FETCH C1 INTO :WS-NAME END-EXEC.
           IF SQLCODE = 100
               GO TO END-PARA
           END-IF.
           ADD 1 TO WS-COUNT.
           GO TO FETCH-LOOP.
       END-PARA.
           EXEC SQL CLOSE C1 END-EXEC.
           GOBACK.
"""


def test_go_to_back_makes_a_loop_body():
    ast = parse_cobol(GOLOOP).ast
    # GO TO END-PARA goes forward; GO TO FETCH-LOOP closes the loop.
    assert goto_loop_paragraphs(ast) == {"FETCH-LOOP"}


def test_goto_loop_fetch_gets_rows(tmp_path):
    from mockymock.cli.main import main

    source = tmp_path / "GOLOOP.cbl"
    source.write_text(GOLOOP)
    out = tmp_path / "GOLOOP.cut"
    main(["generate", str(source), "--with-data", "-o", str(out), "--force"])
    text = out.read_text()
    assert 'MOCK SQL "FETCH" ROWS' in text
