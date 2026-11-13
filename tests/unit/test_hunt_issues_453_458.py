"""Hunt issues #453 (SEARCH ALL detection), #454 (export column of a body on
its clause header's line), #457 (MOCK SECTION fallen into through an unnamed
leading paragraph) and #458 (real program run from BEFORE-ALL)."""

from __future__ import annotations

from cobolparser import parse_cobol

from mockymock._lines import split_source_lines
from mockymock.analysis.dialect_risk import find_dialect_risks
from mockymock.cli.main import main

HEAD = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. {name}.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
"""

# --- #453 -------------------------------------------------------------------

SEARCHES = (
    HEAD.format(name="SRCH")
    + """\
       01  WS-TBL.
           05  WS-ENT OCCURS 5 TIMES ASCENDING KEY WS-KEY
                   INDEXED BY IX.
               10  WS-KEY   PIC 9(3).
       01  WS-SMALL-K   PIC 9(3) VALUE 5.
       01  WS-N         PIC 9(3) VALUE 5.
       PROCEDURE DIVISION.
       MAIN-PARA.
           SET IX TO 1
           SEARCH WS-ENT
               AT END DISPLAY 'NONE'
               WHEN WS-KEY (IX) = WS-SMALL-K
                   DISPLAY 'FOUND'
           END-SEARCH
           SEARCH WS-ENT
               WHEN WS-KEY (IX) = WS-N
                   DISPLAY 'ALLOWED' FUNCTION CURRENT-DATE
           END-SEARCH
           SEARCH ALL WS-ENT
               WHEN WS-KEY (IX) = 3
                   DISPLAY 'X'
           END-SEARCH
           GOBACK.
"""
)


def test_only_a_real_search_all_is_a_collation_risk():
    ast = parse_cobol(SEARCHES).ast
    risks = find_dialect_risks(ast, split_source_lines(SEARCHES))
    lines = split_source_lines(SEARCHES)
    search_all_line = 1 + next(i for i, t in enumerate(lines) if "SEARCH ALL" in t)
    display_line = 1 + next(i for i, t in enumerate(lines) if "CURRENT-DATE" in t)
    search_all = [r.line for r in risks if r.code == "SEARCH_ALL_COLLATION"]
    assert search_all == [search_all_line]
    clock = [r.line for r in risks if r.code == "CLOCK_DEPENDENT"]
    # The FUNCTION inside the WHEN body is reported at its own DISPLAY only.
    assert clock == [display_line]


# --- #454 -------------------------------------------------------------------

READER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. RDONE.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-FILE ASSIGN TO "IN.DAT"
               FILE STATUS IS WS-FS.
       DATA DIVISION.
       FILE SECTION.
       FD  IN-FILE.
       01  IN-REC              PIC X(10).
       WORKING-STORAGE SECTION.
       01  WS-FS               PIC XX.
       01  WS-EOF              PIC X VALUE "N".
       01  WS-COUNT            PIC 9(3) VALUE 0.
       PROCEDURE DIVISION.
       0000-MAIN.
           PERFORM UNTIL WS-EOF = "Y"
               READ IN-FILE
                   AT END MOVE "Y" TO WS-EOF
                   NOT AT END ADD 1 TO WS-COUNT
               END-READ
           END-PERFORM
           GOBACK.
"""

READER_CUT = """\
TESTSUITE "RDONE"

TESTCASE "one record"
    MOCK READ IN-FILE ROWS
        ( IN-REC = "A" )
    END-MOCK
    PERFORM 0000-MAIN
    EXPECT WS-COUNT TO BE 1
"""


def test_export_keeps_a_same_line_clause_body_in_area_b(tmp_path, capsys):
    cbl = tmp_path / "RDONE.cbl"
    cbl.write_text(READER)
    cut = tmp_path / "RDONE.cut"
    cut.write_text(READER_CUT)
    out = tmp_path / "RDONE-EXPORT.cbl"
    assert main(["export", str(cbl), "--cut", str(cut), "--output", str(out)]) == 0
    capsys.readouterr()
    lines = out.read_text().splitlines()
    for number, line in enumerate(lines, start=1):
        if not line.strip() or line[6:7] in ("*", "/", "-", "D"):
            continue
        assert line[:7].strip() == "", f"line {number} leaves Area B: {line!r}"
    bodies = [
        line for line in lines if 'MOVE "Y" TO WS-EOF' in line and line[6:7] != "*"
    ]
    assert bodies and all(line.startswith("       ") for line in bodies)


# --- #457 -------------------------------------------------------------------

SECFALL = (
    HEAD.format(name="SECFALL")
    + """\
       01  WS-FLAG      PIC X VALUE 'N'.
       01  WS-TOTAL     PIC 9(5) VALUE 0.
       PROCEDURE DIVISION.
       MAIN SECTION.
       MAIN-PROCESS.
           IF WS-FLAG = 'Y'
               GO TO FINISH-UP
           END-IF
           PERFORM REPORTING.
       FINISH-UP.
           ADD 1 TO WS-TOTAL.
       REPORTING SECTION.
           ADD 100 TO WS-TOTAL.
       RPT-BODY.
           ADD 5 TO WS-TOTAL.
           GOBACK.
"""
)

SECFALL_CUT = """\
TESTSUITE "SECFALL"

TESTCASE "mocked section via go to path"
    MOCK SECTION REPORTING
        ADD 7 TO WS-TOTAL
    END-MOCK
    MOVE 'Y' TO WS-FLAG
    PERFORM MAIN-PROCESS
    EXPECT WS-TOTAL TO BE 8
"""


def test_mock_section_fallen_into_through_its_unnamed_paragraph_is_refused(
    tmp_path, capsys
):
    cbl = tmp_path / "SECFALL.cbl"
    cbl.write_text(SECFALL)
    cut = tmp_path / "SECFALL.cut"
    cut.write_text(SECFALL_CUT)
    rc = main(["lint", str(cbl), "--cut", str(cut)])
    out = capsys.readouterr().out
    assert rc == 1
    assert "UNSUPPORTED_FLOW_MOCK_TARGET" in out
    assert "falling through" in out


# --- #458 -------------------------------------------------------------------

SUBQ = (
    HEAD.format(name="SUBQ")
    + """\
       LINKAGE SECTION.
       01  LK-OUT       PIC X(8).
       PROCEDURE DIVISION USING LK-OUT.
       SUB-MAIN.
           CALL "LEAF" USING LK-OUT
           GOBACK.
"""
)

MAINQ = (
    HEAD.format(name="MAINQ")
    + """\
       01  WS-OUT       PIC X(8).
       PROCEDURE DIVISION.
       MAIN-PARA.
           CALL "SUBQ" USING WS-OUT
           GOBACK.
"""
)

MAINQ_CUT = """\
TESTSUITE "MAINQ"

BEFORE-ALL
    USE REAL CALL "SUBQ" FROM "SUBQ.cbl"
    PERFORM MAIN-PARA
END-BEFORE

TESTCASE "leaf mocked only here"
    MOCK CALL "LEAF"
        MOVE "LEAFED" TO LK-OUT
    END-MOCK
    PERFORM MAIN-PARA
    EXPECT WS-OUT TO BE "LEAFED"
"""


def test_real_program_run_from_before_all_is_checked_against_its_mocks(
    tmp_path, capsys, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "SUBQ.cbl").write_text(SUBQ)
    cbl = tmp_path / "MAINQ.cbl"
    cbl.write_text(MAINQ)
    cut = tmp_path / "MAINQ.cut"
    cut.write_text(MAINQ_CUT)
    rc = main(["lint", str(cbl), "--cut", str(cut)])
    out = capsys.readouterr().out
    assert rc == 1
    assert "UNMOCKED_CALL" in out
    assert "BEFORE-ALL step PERFORM MAIN-PARA" in out
