import pytest
from cobolparser import parse_cobol

from mockymock.analysis.mock_surface import CallKind, analyze

SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SAMPLE.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT ORDER-FILE ASSIGN TO "ORDERS"
               ORGANIZATION IS LINE SEQUENTIAL.

       DATA DIVISION.
       FILE SECTION.
       FD  ORDER-FILE.
       01  ORDER-RECORD       PIC X(11).

       WORKING-STORAGE SECTION.
       01  WS-PGM-NAME        PIC X(8) VALUE "DISCRATE".
       01  WS-AMOUNT          PIC 9(5)V99.
       01  WS-RATE            PIC 9V99.

       PROCEDURE DIVISION.
       PROCESS-ORDER.
           CALL "DISCRATE" USING WS-AMOUNT WS-RATE.

       DYNAMIC-DISPATCH.
           CALL WS-PGM-NAME USING WS-AMOUNT.

       READ-AN-ORDER.
           READ ORDER-FILE
               AT END DISPLAY "EOF"
           END-READ.
"""

EXEC_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. EXECSAMP.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-CUST-ID         PIC 9(5).
       01  WS-SEGMENT         PIC X(20).

       PROCEDURE DIVISION.
       RUN-SQL.
           EXEC SQL
               SELECT CUST_ID INTO :WS-CUST-ID FROM CUSTOMERS
           END-EXEC.

       RUN-CICS.
           EXEC CICS
               RECEIVE INTO(WS-CUST-ID)
           END-EXEC.

       RUN-IMS.
           EXEC DLI
               GU SEGMENT-NAME
           END-EXEC.

       NO-EXEC-HERE.
           DISPLAY "no exec statements".
"""


NESTED_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. NESTED.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT ORDER-FILE ASSIGN TO "ORDERS"
               ORGANIZATION IS LINE SEQUENTIAL.

       DATA DIVISION.
       FILE SECTION.
       FD  ORDER-FILE.
       01  ORDER-RECORD       PIC X(11).

       WORKING-STORAGE SECTION.
       01  WS-FLAG            PIC X VALUE "Y".
       01  WS-AMOUNT          PIC 9(5)V99.
       01  WS-RATE            PIC 9V99.
       01  WS-CUST-ID         PIC 9(5).

       PROCEDURE DIVISION.
       CALL-INSIDE-IF.
           IF WS-FLAG = "Y"
               CALL "NESTED-DISCRATE" USING WS-AMOUNT WS-RATE
           END-IF.

       CALL-INSIDE-READ-AT-END.
           READ ORDER-FILE
               AT END
                   CALL "NESTED-DISCRATE" USING WS-AMOUNT WS-RATE
           END-READ.

       EXEC-INSIDE-INLINE-PERFORM.
           PERFORM 3 TIMES
               EXEC SQL
                   SELECT CUST_ID INTO :WS-CUST-ID FROM CUSTOMERS
               END-EXEC
           END-PERFORM.

       CALL-INSIDE-EVALUATE.
           EVALUATE WS-FLAG
               WHEN "Y"
                   CALL "NESTED-DISCRATE" USING WS-AMOUNT WS-RATE
               WHEN OTHER
                   DISPLAY "NO"
           END-EVALUATE.

       CALL-INSIDE-CALL-ON-EXCEPTION.
           CALL "OUTER-PGM" USING WS-AMOUNT WS-RATE
               ON EXCEPTION
                   CALL "NESTED-DISCRATE" USING WS-AMOUNT WS-RATE
           END-CALL.
"""


def _ast():
    result = parse_cobol(SOURCE, filename="sample.cbl")
    assert result.success, result.errors
    return result.ast


def _exec_ast():
    result = parse_cobol(EXEC_SOURCE, filename="execsamp.cbl")
    assert result.success, result.errors
    return result.ast


def _nested_ast():
    result = parse_cobol(NESTED_SOURCE, filename="nested.cbl")
    assert result.success, result.errors
    return result.ast


def test_classifies_static_call_site():
    surface = analyze(_ast())
    static = surface.static_call_sites()
    assert len(static) == 1
    assert static[0].program_name == "DISCRATE"
    assert static[0].paragraph_name == "PROCESS-ORDER"
    assert static[0].kind is CallKind.STATIC


def test_classifies_dynamic_call_site():
    surface = analyze(_ast())
    dynamic = surface.dynamic_call_sites()
    assert len(dynamic) == 1
    assert dynamic[0].paragraph_name == "DYNAMIC-DISPATCH"
    assert dynamic[0].kind is CallKind.DYNAMIC


def test_detects_file_io_paragraph():
    surface = analyze(_ast())
    assert "READ-AN-ORDER" in surface.file_io_paragraphs


def test_paragraph_without_file_io_is_not_flagged():
    surface = analyze(_ast())
    assert "PROCESS-ORDER" not in surface.file_io_paragraphs


def test_detects_exec_sql_paragraph():
    surface = analyze(_exec_ast())
    assert "RUN-SQL" in surface.exec_paragraphs


def test_detects_exec_cics_paragraph():
    surface = analyze(_exec_ast())
    assert "RUN-CICS" in surface.exec_paragraphs


def test_detects_exec_dli_paragraph():
    surface = analyze(_exec_ast())
    assert "RUN-IMS" in surface.exec_paragraphs


def test_paragraph_without_exec_is_not_flagged():
    surface = analyze(_exec_ast())
    assert "NO-EXEC-HERE" not in surface.exec_paragraphs


def test_detects_static_call_nested_inside_if():
    surface = analyze(_nested_ast())
    static = [
        c for c in surface.static_call_sites() if c.paragraph_name == "CALL-INSIDE-IF"
    ]
    assert len(static) == 1
    assert static[0].program_name == "NESTED-DISCRATE"
    assert static[0].kind is CallKind.STATIC


def test_call_nested_inside_if_is_marked_nested():
    surface = analyze(_nested_ast())
    static = [
        c for c in surface.static_call_sites() if c.paragraph_name == "CALL-INSIDE-IF"
    ]
    assert len(static) == 1
    assert static[0].nested is True


def test_top_level_call_is_not_marked_nested():
    surface = analyze(_ast())
    static = surface.static_call_sites()
    assert len(static) == 1
    assert static[0].paragraph_name == "PROCESS-ORDER"
    assert static[0].nested is False


@pytest.mark.xfail(
    strict=True,
    reason=(
        "cobolparser's READ AT END / NOT AT END clause parsing is a documented "
        "stub: collect_clause_stmts() (cobolparser/parsers/statements/_utils.py:262) "
        "always discards its tokens and returns [], so IOReadStatement.at_end_clause "
        "is never populated with real nested statements regardless of source. Our "
        "recursive walk is ready to pick this up (at_end_clause is in "
        "_NESTED_STATEMENT_ATTRS) the moment cobolparser implements real clause "
        "parsing; until then this is a verified upstream limitation, not a bug in "
        "mock_surface.py. SAFETY NOTE: a CALL/EXEC/file-op hidden in a READ AT END "
        "or an INVALID KEY body (DELETE/REWRITE/START share the same stub) is "
        "invisible to the AST today, so Task 6's refusal gate cannot catch it via "
        "this path."
    ),
)
def test_detects_call_nested_inside_read_at_end():
    surface = analyze(_nested_ast())
    static = [
        c
        for c in surface.static_call_sites()
        if c.paragraph_name == "CALL-INSIDE-READ-AT-END"
    ]
    assert len(static) == 1
    assert static[0].program_name == "NESTED-DISCRATE"
    # The paragraph also has a top-level READ, so file I/O is still flagged.
    assert "CALL-INSIDE-READ-AT-END" in surface.file_io_paragraphs


def test_detects_exec_sql_nested_inside_inline_perform():
    surface = analyze(_nested_ast())
    assert "EXEC-INSIDE-INLINE-PERFORM" in surface.exec_paragraphs


def test_detects_static_call_nested_inside_evaluate():
    surface = analyze(_nested_ast())
    static = [
        c
        for c in surface.static_call_sites()
        if c.paragraph_name == "CALL-INSIDE-EVALUATE"
    ]
    assert len(static) == 1
    assert static[0].program_name == "NESTED-DISCRATE"


def test_detects_static_call_nested_inside_call_on_exception():
    surface = analyze(_nested_ast())
    static = [
        c
        for c in surface.static_call_sites()
        if c.paragraph_name == "CALL-INSIDE-CALL-ON-EXCEPTION"
    ]
    # Two static CALLs in this paragraph: the outer CALL "OUTER-PGM" and the
    # nested CALL "NESTED-DISCRATE" inside its ON EXCEPTION clause.
    assert len(static) == 2
    assert {c.program_name for c in static} == {"OUTER-PGM", "NESTED-DISCRATE"}
