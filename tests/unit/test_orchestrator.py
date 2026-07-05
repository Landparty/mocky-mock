"""Unit tests for the generalized splice orchestrator."""

from cobolparser import parse_cobol
from cobolparser.preprocess import normalize_fixed_format

from mockymock.analysis.mock_surface import analyze
from mockymock.dsl.model import MockCategory, MockDirective, MockTestCase, MockTestSuite
from mockymock.splicer.naming import TallyRegistry
from mockymock.splicer.orchestrator import splice_program
from mockymock.splicer.source_map import collect_boundaries

SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ALLBOUND.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-FILE ASSIGN TO "IN.DAT"
               ORGANIZATION IS LINE SEQUENTIAL.

       DATA DIVISION.
       FILE SECTION.
       FD  IN-FILE.
       01  IN-REC             PIC X(20).

       WORKING-STORAGE SECTION.
       01  WS-EOF             PIC X VALUE "N".
       01  WS-CUST-ID         PIC 9(5).

       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT IN-FILE.
           READ IN-FILE
               AT END MOVE "Y" TO WS-EOF
           END-READ.
           CLOSE IN-FILE.

       SQL-PARA.
           EXEC SQL
               UPDATE ORDERS SET STATUS = 'Y' WHERE ID = :WS-CUST-ID
           END-EXEC.

       UNREACHED-SQL.
           EXEC SQL
               DELETE FROM AUDIT WHERE ID = :WS-CUST-ID
           END-EXEC.

       CALL-PARA.
           CALL "DISCRATE" USING WS-CUST-ID.
"""


def _splice(suite):
    result = parse_cobol(SOURCE, filename="allbound.cbl")
    assert result.success, result.errors
    surface = analyze(result.ast)
    normalized = normalize_fixed_format(SOURCE.splitlines())
    lines = normalized.splitlines()
    boundaries = collect_boundaries(result.ast)
    return splice_program(
        lines, boundaries, surface, suite, TallyRegistry(suite)
    )


def _file_suite():
    case = MockTestCase(
        name="file case",
        mocks=[
            MockDirective(MockCategory.OPEN, "IN-FILE"),
            MockDirective(
                MockCategory.READ, "IN-FILE", ['MOVE "Y" TO WS-EOF']
            ),
            MockDirective(MockCategory.CLOSE, "IN-FILE"),
            MockDirective(
                MockCategory.SQL, "UPDATE ORDERS", ["MOVE 0 TO SQLCODE"]
            ),
        ],
        perform_target="MAIN-PARA",
    )
    return MockTestSuite(name="S", test_cases=[case])


def test_mocked_file_statements_are_commented_and_replaced():
    lines = _splice(_file_suite())
    joined = "\n".join(lines)
    assert "      *>     OPEN INPUT IN-FILE." in joined
    assert "      *>     READ IN-FILE" in joined
    # READ's AT END clause is inside the replaced span
    assert '      *>         AT END MOVE "Y" TO WS-EOF' in joined
    assert "      *>     CLOSE IN-FILE." in joined
    assert "ADD 1 TO UT-OPEN-IN-FILE-TALLY" in joined
    assert "ADD 1 TO UT-READ-IN-FILE-TALLY" in joined


def test_mocked_sql_statement_gets_dispatch():
    lines = _splice(_file_suite())
    joined = "\n".join(lines)
    assert "ADD 1 TO UT-SQL-UPDATE-ORDERS-TALLY" in joined
    assert "MOVE 0 TO SQLCODE" in joined


def test_unmocked_exec_sql_is_trap_stubbed_program_wide():
    lines = _splice(_file_suite())
    joined = "\n".join(lines)
    # the unreached DELETE is commented out and trapped, even though no case
    # mocks or reaches it (cobc cannot compile a raw EXEC block)
    assert "      *>     EXEC SQL" in joined
    live_sql = [
        ln
        for ln in lines
        if "DELETE FROM AUDIT" in ln and not ln.strip().startswith("*>")
    ]
    assert live_sql == []
    assert "unmocked EXEC SQL reached" in joined


def test_unmocked_call_is_left_in_place():
    lines = _splice(_file_suite())
    assert any(
        'CALL "DISCRATE"' in ln and not ln.strip().startswith("*>") for ln in lines
    )


def test_sentence_terminating_period_is_preserved():
    lines = _splice(_file_suite())
    # CLOSE IN-FILE. was the last statement of MAIN-PARA -- its replacement
    # block must end with a period so the sentence terminates before SQL-PARA.
    close_idx = next(
        i for i, ln in enumerate(lines) if ln.startswith("      *>     CLOSE IN-FILE.")
    )
    block_end = next(
        i
        for i in range(close_idx + 1, len(lines))
        if lines[i].strip().startswith("END-EVALUATE")
    )
    assert lines[block_end].rstrip().endswith(".")
