"""Issue #326: a lifted clause body was refused for holding the bare word
SIZE / OVERFLOW / EXCEPTION / END, so `STRING ... DELIMITED BY SIZE` (and
a correctly terminated `COMPUTE ... ON SIZE ERROR ... END-COMPUTE`) cost a
mocked READ both of its AT END / NOT AT END bodies. Only a conditional
phrase whose owner is not closed by its own END-<verb> is refused now."""

import pytest
from cobolparser import parse_cobol
from cobolparser.preprocess import normalize_fixed_format

from mockymock.analysis.clause_bodies import lift_clause_bodies

TEMPLATE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. STRRD.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-FILE ASSIGN TO "IN.DAT"
               FILE STATUS IS WS-FS.
       DATA DIVISION.
       FILE SECTION.
       FD  IN-FILE.
       01  IN-REC.
           05  IN-NAME         PIC X(10).
       WORKING-STORAGE SECTION.
       01  WS-FS               PIC XX.
       01  WS-EOF              PIC X VALUE "N".
       01  WS-COUNT            PIC 9(3) VALUE 0.
       01  WS-LINE             PIC X(20).
       01  WS-TAB.
           05  WS-ENT          PIC X OCCURS 3 INDEXED BY WS-I.
       PROCEDURE DIVISION.
       0000-MAIN.
           READ IN-FILE
               AT END
                   MOVE "Y" TO WS-EOF
               NOT AT END
                   ADD 1 TO WS-COUNT
{body}
           END-READ
           GOBACK.
"""

LIFTED = {
    "delimited by size": (
        '                   STRING "NAME=" IN-NAME DELIMITED BY SIZE\n'
        "                       INTO WS-LINE\n"
        "                   END-STRING"
    ),
    "terminated size error": (
        "                   COMPUTE WS-COUNT = WS-COUNT * 2\n"
        "                       ON SIZE ERROR MOVE 0 TO WS-COUNT\n"
        "                   END-COMPUTE"
    ),
    "terminated overflow": (
        "                   STRING IN-NAME DELIMITED BY SIZE INTO WS-LINE\n"
        '                       ON OVERFLOW MOVE "X" TO WS-EOF\n'
        "                   END-STRING"
    ),
    "terminated search at end": (
        "                   SEARCH WS-ENT\n"
        '                       AT END MOVE "Y" TO WS-EOF\n'
        '                       WHEN WS-ENT(WS-I) = "A" CONTINUE\n'
        "                   END-SEARCH"
    ),
}

REFUSED = {
    "unterminated size error": (
        "                   COMPUTE WS-COUNT = WS-COUNT * 2\n"
        "                       ON SIZE ERROR MOVE 0 TO WS-COUNT"
    ),
    "unterminated overflow": (
        "                   STRING IN-NAME DELIMITED BY SIZE INTO WS-LINE\n"
        '                       ON OVERFLOW MOVE "X" TO WS-EOF'
    ),
    "phrase of an inner verb closed only by an outer terminator": (
        "                   STRING IN-NAME DELIMITED BY SIZE INTO WS-LINE\n"
        "                       ON OVERFLOW\n"
        "                           COMPUTE WS-COUNT = 1\n"
        "                               ON SIZE ERROR CONTINUE\n"
        "                   END-STRING"
    ),
}


def _lift(body: str):
    source = TEMPLATE.format(body=body)
    result = parse_cobol(source, filename="STRRD.cbl")
    assert result.success, result.errors
    lines = normalize_fixed_format(source.splitlines()).splitlines()
    (read,) = result.ast.find_all_by_type("IOReadStatement")
    return lift_clause_bodies(read, lines)


@pytest.mark.parametrize("body", LIFTED.values(), ids=LIFTED.keys())
def test_a_terminated_or_non_phrase_use_is_lifted(body):
    lifted = _lift(body)
    assert lifted is not None
    by_attr = {clause.attr: clause for clause in lifted}
    assert by_attr["at_end_clause"].lines == ('MOVE "Y" TO WS-EOF',)
    not_at_end = by_attr["not_at_end_clause"].lines
    assert not_at_end[0] == "ADD 1 TO WS-COUNT"
    assert not_at_end[1:] == tuple(line.strip() for line in body.splitlines())


@pytest.mark.parametrize("body", REFUSED.values(), ids=REFUSED.keys())
def test_an_unterminated_phrase_is_still_refused(body):
    assert _lift(body) is None
