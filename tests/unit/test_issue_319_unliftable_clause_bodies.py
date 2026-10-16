"""Issue #319: a mocked READ / CALL whose clause bodies could not be lifted
silently lost every body (the liftable ones too), with lint clean. Now a
GO TO body and a body whose IF the sentence period closes are lifted, and
anything still unliftable is refused (UNLIFTABLE_CLAUSE_BODY)."""

from cobolparser import parse_cobol
from cobolparser.preprocess import normalize_fixed_format

from mockymock.analysis.clause_bodies import clause_lift_problem, lift_clause_bodies
from mockymock.analysis.mock_surface import analyze
from mockymock.analysis.refusal import REFUSAL_EXPLANATIONS, check_clause_bodies
from mockymock.dsl.parser import parse_cut

PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. GOREAD.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-FILE ASSIGN TO "IN.DAT"
               FILE STATUS IS WS-FS.
       DATA DIVISION.
       FILE SECTION.
       FD  IN-FILE.
       01  IN-REC.
           05  IN-TYPE         PIC X.
       WORKING-STORAGE SECTION.
       01  WS-FS               PIC XX.
       01  WS-EOF              PIC X VALUE "N".
       01  WS-COUNT            PIC 9(3) VALUE 0.
       01  WS-COUNT-A          PIC 9(3) VALUE 0.
       01  WS-OK               PIC X VALUE "?".
       PROCEDURE DIVISION.
       1000-READ.
           READ IN-FILE
               AT END
                   MOVE "Y" TO WS-EOF
                   GO TO 1000-EXIT
           END-READ
           ADD 1 TO WS-COUNT.
       1000-EXIT.
           EXIT.
       2000-READ.
           READ IN-FILE
               AT END
                   MOVE "Y" TO WS-EOF
               NOT AT END
                   ADD 1 TO WS-COUNT
                   IF IN-TYPE = "A"
                       ADD 1 TO WS-COUNT-A.
       3000-CALL.
           CALL "RATESUB"
               ON EXCEPTION
                   MOVE "N" TO WS-OK
                   {exception_exit}
               NOT ON EXCEPTION
                   MOVE "Y" TO WS-OK
           END-CALL
           ADD 1 TO WS-COUNT.
       3000-EXIT.
           EXIT.
"""

CUT = """\
TESTSUITE "GOREAD"

TESTCASE "read"
    MOCK READ IN-FILE
        FILE-STATUS IS END-OF-FILE
    END-MOCK
    MOCK CALL "RATESUB"
    END-MOCK
    PERFORM 1000-READ THRU 1000-EXIT
"""


def _parse(exception_exit: str = "GO TO 3000-EXIT"):
    source = PROGRAM.format(exception_exit=exception_exit)
    result = parse_cobol(source, filename="GOREAD.cbl")
    assert result.success, result.errors
    lines = normalize_fixed_format(source.splitlines()).splitlines()
    return result.ast, lines


def _bodies(statement, lines):
    lifted = lift_clause_bodies(statement, lines)
    assert lifted is not None, clause_lift_problem(statement, lines)
    return {clause.attr: clause.lines for clause in lifted}


def test_a_go_to_body_is_lifted():
    ast, lines = _parse()
    reads = ast.find_all_by_type("IOReadStatement")
    assert _bodies(reads[0], lines) == {
        "at_end_clause": ('MOVE "Y" TO WS-EOF', "GO TO 1000-EXIT"),
    }
    (call,) = ast.find_all_by_type("CallStatement")
    assert _bodies(call, lines) == {
        "on_exception": ('MOVE "N" TO WS-OK', "GO TO 3000-EXIT"),
        "not_on_exception": ('MOVE "Y" TO WS-OK',),
    }


def test_an_if_closed_by_the_sentence_period_gets_its_end_if():
    ast, lines = _parse()
    reads = ast.find_all_by_type("IOReadStatement")
    assert _bodies(reads[1], lines) == {
        "at_end_clause": ('MOVE "Y" TO WS-EOF',),
        "not_at_end_clause": (
            "ADD 1 TO WS-COUNT",
            'IF IN-TYPE = "A"',
            "ADD 1 TO WS-COUNT-A",
            "END-IF",
        ),
    }


def test_an_if_left_open_before_the_next_clause_is_still_unliftable():
    source = PROGRAM.format(exception_exit="GO TO 3000-EXIT").replace(
        '                   MOVE "N" TO WS-OK\n',
        '                   IF WS-OK = "?"\n'
        '                       MOVE "N" TO WS-OK\n',
    )
    result = parse_cobol(source, filename="GOREAD.cbl")
    assert result.success, result.errors
    lines = normalize_fixed_format(source.splitlines()).splitlines()
    (call,) = result.ast.find_all_by_type("CallStatement")
    assert lift_clause_bodies(call, lines) is None
    assert "ON EXCEPTION" in clause_lift_problem(call, lines)


def test_a_mocked_site_with_an_unliftable_body_is_refused():
    ast, lines = _parse(exception_exit="GOBACK")
    reasons = check_clause_bodies(analyze(ast), parse_cut(CUT), lines)
    assert [r.code for r in reasons] == ["UNLIFTABLE_CLAUSE_BODY"]
    message = reasons[0].message
    assert 'MOCK CALL "RATESUB"' in message
    assert "ON EXCEPTION body holds a GOBACK" in message
    assert "UNLIFTABLE_CLAUSE_BODY" in REFUSAL_EXPLANATIONS


def test_liftable_mocked_sites_are_not_refused():
    ast, lines = _parse()
    assert check_clause_bodies(analyze(ast), parse_cut(CUT), lines) == []
