"""`analysis.clause_bodies` and the splice it drives (issue #209): a mocked
READ / CALL / keyed file op re-runs the program's own NOT AT END /
INVALID KEY / NOT INVALID KEY / ON EXCEPTION / NOT ON EXCEPTION bodies,
selected by the mocked outcome, instead of deleting them with the
statement."""

from cobolparser import parse_cobol
from cobolparser.preprocess import normalize_fixed_format

from mockymock.analysis.clause_bodies import (
    clause_bodies_liftable,
    lift_clause_bodies,
)
from mockymock.analysis.mock_surface import analyze, analyze_file_status_fields
from mockymock.dsl.parser import parse_cut
from mockymock.splicer.naming import TallyRegistry
from mockymock.splicer.orchestrator import splice_program
from mockymock.splicer.source_map import collect_boundaries

PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. IK.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT CUST-FILE ASSIGN TO "CUST.DAT"
               ORGANIZATION IS INDEXED
               ACCESS MODE IS RANDOM
               RECORD KEY IS CUST-ID
               FILE STATUS IS WS-FS.
       DATA DIVISION.
       FILE SECTION.
       FD  CUST-FILE.
       01  CUST-REC.
           05  CUST-ID         PIC X(5).
       WORKING-STORAGE SECTION.
       01  WS-FS               PIC XX.
       01  WS-FOUND            PIC X VALUE "?".
       01  WS-OK               PIC X VALUE "?".
       01  WS-RATE             PIC 9(3) VALUE 0.
       01  WS-N                PIC 9(3) VALUE 0.
       PROCEDURE DIVISION.
       0000-MAIN.
           READ CUST-FILE
               INVALID KEY MOVE "N" TO WS-FOUND
               NOT INVALID KEY
                   MOVE "Y" TO WS-FOUND
                   IF WS-RATE > 1
                       ADD 1 TO WS-N
                   END-IF
           END-READ
           CALL "RATESUB" USING WS-RATE
               ON EXCEPTION MOVE "N" TO WS-OK
               NOT ON EXCEPTION MOVE "Y" TO WS-OK
           END-CALL
           GOBACK.
"""

CUT = """\
TESTSUITE "IK"

TESTCASE "not found"
    MOCK READ CUST-FILE
        FILE-STATUS IS RECORD-NOT-FOUND
    END-MOCK
    MOCK CALL "RATESUB"
        MOVE "EX" TO UT-MOCK-STATUS
    END-MOCK
    PERFORM 0000-MAIN
"""


def _parse(source: str = PROGRAM):
    result = parse_cobol(source, filename="IK.cbl")
    assert result.success, result.errors
    lines = normalize_fixed_format(source.splitlines()).splitlines()
    return result.ast, lines


def _statement(ast, node_type: str):
    (statement,) = ast.find_all_by_type(node_type)
    return statement


def test_read_invalid_key_bodies_are_lifted_verbatim():
    ast, lines = _parse()
    lifted = lift_clause_bodies(_statement(ast, "IOReadStatement"), lines)
    assert lifted is not None
    by_attr = {clause.attr: clause for clause in lifted}
    assert by_attr["invalid_key_clause"].lines == ('MOVE "N" TO WS-FOUND',)
    assert by_attr["invalid_key_clause"].guard == 'UT-MOCK-STATUS(1:1) = "2"'
    assert by_attr["not_invalid_key_clause"].lines == (
        'MOVE "Y" TO WS-FOUND',
        "IF WS-RATE > 1",
        "ADD 1 TO WS-N",
        "END-IF",
    )
    assert by_attr["not_invalid_key_clause"].guard == 'UT-MOCK-STATUS(1:1) = "0"'


def test_call_exception_bodies_are_lifted():
    ast, lines = _parse()
    lifted = lift_clause_bodies(_statement(ast, "CallStatement"), lines)
    assert lifted is not None
    by_attr = {clause.attr: clause for clause in lifted}
    assert by_attr["on_exception"].guard == 'UT-MOCK-STATUS = "EX"'
    assert by_attr["not_on_exception"].lines == ('MOVE "Y" TO WS-OK',)


def test_a_body_with_another_boundary_is_not_liftable():
    source = PROGRAM.replace(
        '               ON EXCEPTION MOVE "N" TO WS-OK\n',
        '               ON EXCEPTION CALL "OTHER"\n',
    )
    ast, lines = _parse(source)
    call = [
        c
        for c in ast.find_all_by_type("CallStatement")
        if getattr(c, "on_exception", None)
    ][0]
    assert not clause_bodies_liftable(call)
    assert lift_clause_bodies(call, lines) is None


def test_a_nested_conditional_phrase_or_unbalanced_if_is_not_lifted():
    source = PROGRAM.replace(
        "                   IF WS-RATE > 1\n"
        "                       ADD 1 TO WS-N\n"
        "                   END-IF\n",
        "                   ADD 1 TO WS-N ON SIZE ERROR MOVE 0 TO WS-N END-ADD\n",
    )
    ast, lines = _parse(source)
    assert lift_clause_bodies(_statement(ast, "IOReadStatement"), lines) is None


def test_a_statement_without_clauses_is_not_lifted():
    source = PROGRAM.replace(
        "           READ CUST-FILE\n"
        '               INVALID KEY MOVE "N" TO WS-FOUND\n'
        "               NOT INVALID KEY\n"
        '                   MOVE "Y" TO WS-FOUND\n'
        "                   IF WS-RATE > 1\n"
        "                       ADD 1 TO WS-N\n"
        "                   END-IF\n"
        "           END-READ\n",
        "           READ CUST-FILE\n",
    )
    ast, lines = _parse(source)
    assert lift_clause_bodies(_statement(ast, "IOReadStatement"), lines) is None


def test_splice_selects_each_clause_from_the_mocked_outcome():
    ast, lines = _parse()
    surface = analyze(ast)
    suite = parse_cut(CUT)
    spliced = splice_program(
        lines,
        collect_boundaries(ast),
        surface,
        suite,
        TallyRegistry(suite),
        file_status_fields=analyze_file_status_fields(ast),
    )
    live = [line.strip() for line in spliced if not line.lstrip().startswith("*>")]
    # FILE-STATUS IS moves "23" into WS-FS; the branch then reports WS-FS
    # as the outcome, which selects INVALID KEY.
    status_at = live.index('MOVE "23" TO WS-FS')
    assert live[status_at + 1] == "MOVE WS-FS TO UT-MOCK-STATUS"
    invalid = live.index('WHEN UT-MOCK-STATUS(1:1) = "2"')
    assert live[invalid + 1] == 'MOVE "N" TO WS-FOUND'
    # The CALL mock opts into ON EXCEPTION by its own MOVE.
    exception = live.index('WHEN UT-MOCK-STATUS = "EX"')
    assert live[exception + 1] == 'MOVE "N" TO WS-OK'
