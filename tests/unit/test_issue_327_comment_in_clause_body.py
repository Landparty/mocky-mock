"""Issue #327: an inline `*>` comment inside a lifted clause body must not
be scanned as code. A period in the comment read as a sentence end (so the
body was cut short or refused), and an apostrophe opened a literal that
swallowed the rest of the statement."""

import pytest
from cobolparser import parse_cobol
from cobolparser.preprocess import normalize_fixed_format

from mockymock.analysis.clause_bodies import lift_clause_bodies, scan_words

TEMPLATE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CMT.
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
       01  WS-OUT              PIC X(20).
       PROCEDURE DIVISION.
       0000-MAIN.
           READ IN-FILE
               AT END
                   MOVE "Y" TO WS-EOF {at_end}
               NOT AT END
                   ADD 1 TO WS-COUNT {not_at_end}
                   STRING IN-REC DELIMITED BY SPACE
                       INTO WS-OUT
                   END-STRING
           END-READ
           GOBACK.
"""


def _lift(at_end: str, not_at_end: str):
    source = TEMPLATE.format(at_end=at_end, not_at_end=not_at_end)
    result = parse_cobol(source, filename="CMT.cbl")
    assert result.success, result.errors
    lines = normalize_fixed_format(source.splitlines()).splitlines()
    (read,) = result.ast.find_all_by_type("IOReadStatement")
    return lift_clause_bodies(read, lines)


@pytest.mark.parametrize(
    "comment",
    ["*> one more name.", "*> don't skip"],
    ids=["period", "apostrophe"],
)
@pytest.mark.parametrize("where", ["at_end", "not_at_end"])
def test_a_comment_in_a_clause_body_does_not_break_the_lift(comment, where):
    lifted = _lift(
        at_end=comment if where == "at_end" else "",
        not_at_end=comment if where == "not_at_end" else "",
    )
    assert lifted is not None
    by_attr = {clause.attr: clause for clause in lifted}
    assert by_attr["at_end_clause"].lines[0].startswith('MOVE "Y" TO WS-EOF')
    body = by_attr["not_at_end_clause"].lines
    assert body[0].startswith("ADD 1 TO WS-COUNT")
    assert body[-1] == "END-STRING"
    assert any(line.startswith("STRING IN-REC") for line in body)


def test_scan_words_skips_an_inline_comment_but_not_a_literal():
    words = [w for _, _, w in scan_words("MOVE '*>' TO X *> it's done.\nEXIT")]
    assert words == ["MOVE", "TO", "X", "EXIT"]
