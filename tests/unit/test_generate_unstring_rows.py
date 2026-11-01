"""`generate` gives a field the program UNSTRINGs the delimiters its parse
looks for: random text without them made every record take the reject
path, under a case still called "happy path" (the RECFMT field run)."""

from __future__ import annotations

import re

from mockymock.cli.main import main

RECF_CBL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. RECF.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-FILE ASSIGN TO INFILE
               ORGANIZATION IS LINE SEQUENTIAL
               FILE STATUS IS WS-FS.
       DATA DIVISION.
       FILE SECTION.
       FD  IN-FILE.
       01  IN-LINE           PIC X(32).
       WORKING-STORAGE SECTION.
       01  WS-FS             PIC XX.
       01  WS-EOF            PIC X VALUE "N".
           88 EOF            VALUE "Y".
       01  WS-ID             PIC X(6).
       01  WS-NAME           PIC X(10).
       01  WS-AMT-TXT        PIC X(8).
       01  WS-CODE           PIC X(2).
       01  WS-FIELDS         PIC 9 VALUE 0.
       01  WS-GOOD           PIC 9(5) VALUE 0.
       01  WS-BAD            PIC 9(5) VALUE 0.
       PROCEDURE DIVISION.
       0000-MAIN.
           OPEN INPUT IN-FILE
           PERFORM 1000-READ
           PERFORM 2000-PARSE UNTIL EOF
           CLOSE IN-FILE
           DISPLAY "GOOD " WS-GOOD " BAD " WS-BAD
           GOBACK.
       1000-READ.
           READ IN-FILE
               AT END SET EOF TO TRUE
           END-READ.
       2000-PARSE.
           MOVE 0 TO WS-FIELDS
           UNSTRING IN-LINE DELIMITED BY "|"
               INTO WS-ID WS-NAME WS-AMT-TXT WS-CODE
               TALLYING IN WS-FIELDS
           END-UNSTRING
           IF WS-FIELDS < 4
               ADD 1 TO WS-BAD
           ELSE
               ADD 1 TO WS-GOOD
           END-IF
           PERFORM 1000-READ.
"""


def test_generated_records_hold_one_part_per_unstring_target(tmp_path, capsys):
    program = tmp_path / "RECF.cbl"
    program.write_text(RECF_CBL, encoding="utf-8")
    out = tmp_path / "RECF.cut"
    assert main(["generate", str(program), "--seed", "7", "-o", str(out)]) == 0
    values = re.findall(r'MOVE "([^"]*)" TO IN-LINE', out.read_text())
    assert values
    for value in values:
        parts = value.split("|")
        # WS-ID X(6), WS-NAME X(10), WS-AMT-TXT X(8), WS-CODE X(2)
        assert [len(p) for p in parts] == [6, 10, 8, 2]
        assert len(value) <= 32


def test_a_field_split_two_ways_is_left_alone():
    from cobolparser import parse_cobol

    from mockymock.dsl.generator import _unstring_layouts

    twice = RECF_CBL.replace(
        "           IF WS-FIELDS < 4",
        '           UNSTRING IN-LINE DELIMITED BY ","\n'
        "               INTO WS-ID WS-NAME\n"
        "           END-UNSTRING\n"
        "           IF WS-FIELDS < 4",
    )
    assert _unstring_layouts(parse_cobol(RECF_CBL).ast) == {
        "IN-LINE": ("|", ["WS-ID", "WS-NAME", "WS-AMT-TXT", "WS-CODE"])
    }
    assert _unstring_layouts(parse_cobol(twice).ast) == {}
