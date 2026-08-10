"""UNRESOLVED_FILE_STATUS_TARGET: a MOCK using FILE-STATUS IS must target
a file whose SELECT entry declares a FILE STATUS field."""

from cobolparser import parse_cobol

from mockymock.analysis.mock_surface import analyze, analyze_file_status_fields
from mockymock.analysis.refusal import check_test_case
from mockymock.dsl.parser import parse_cut

SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. STATCHK.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT WITH-STATUS ASSIGN TO "A.DAT"
               ORGANIZATION IS LINE SEQUENTIAL
               FILE STATUS IS WS-STATUS.
           SELECT NO-STATUS ASSIGN TO "B.DAT"
               ORGANIZATION IS LINE SEQUENTIAL.

       DATA DIVISION.
       FILE SECTION.
       FD  WITH-STATUS.
       01  WITH-STATUS-REC    PIC X(10).
       FD  NO-STATUS.
       01  NO-STATUS-REC      PIC X(10).

       WORKING-STORAGE SECTION.
       01  WS-STATUS          PIC X(2).

       PROCEDURE DIVISION.
       MAIN-PROCESS.
           OPEN INPUT WITH-STATUS.
           OPEN INPUT NO-STATUS.
"""


def _check(cut_text: str):
    result = parse_cobol(SOURCE, filename="statchk.cbl")
    assert result.success, result.errors
    surface = analyze(result.ast)
    file_status_fields = analyze_file_status_fields(result.ast)
    suite = parse_cut(cut_text)
    case = suite.test_cases[0]
    return check_test_case(surface, result.ast, case, file_status_fields)


def test_file_status_on_a_file_with_a_declared_field_does_not_refuse():
    cut = """\
TESTSUITE "s"
TESTCASE "c"
    MOCK OPEN WITH-STATUS
        FILE-STATUS IS FILE-NOT-FOUND
    END-MOCK
    MOCK OPEN NO-STATUS
    END-MOCK
    PERFORM MAIN-PROCESS
"""
    reasons = _check(cut)
    assert not any(r.code == "UNRESOLVED_FILE_STATUS_TARGET" for r in reasons)


def test_file_status_on_a_file_with_no_declared_field_refuses():
    cut = """\
TESTSUITE "s"
TESTCASE "c"
    MOCK OPEN WITH-STATUS
    END-MOCK
    MOCK OPEN NO-STATUS
        FILE-STATUS IS SUCCESS
    END-MOCK
    PERFORM MAIN-PROCESS
"""
    reasons = _check(cut)
    matches = [r for r in reasons if r.code == "UNRESOLVED_FILE_STATUS_TARGET"]
    assert len(matches) == 1
    assert "NO-STATUS" in matches[0].message


# READ ROWS source: no FILE STATUS clause on the SELECT (mirrors
# test_refusal.py's proven-parseable FILE_IO_SOURCE shape), so a MOCK READ
# ... ROWS block has no status field to fall back on for end-of-data --
# only its own TERMINAL group can supply one.
PROGRAM_NO_STATUS_FIELD = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. RRSAMP.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT ORDER-FILE ASSIGN TO "ORDERS"
               ORGANIZATION IS LINE SEQUENTIAL.

       DATA DIVISION.
       FILE SECTION.
       FD  ORDER-FILE.
       01  ORDER-RECORD.
           05  ORDER-QTY      PIC 9(5).

       PROCEDURE DIVISION.
       READ-AN-ORDER.
           READ ORDER-FILE
               AT END DISPLAY "EOF"
           END-READ.
"""

CUT_READ_ROWS_NO_TERMINAL = """\
TESTSUITE "s"
TESTCASE "c"
    MOCK READ ORDER-FILE ROWS
        ( ORDER-QTY = 50 )
    END-MOCK
    PERFORM READ-AN-ORDER
"""

CUT_READ_ROWS_WITH_TERMINAL = """\
TESTSUITE "s"
TESTCASE "c"
    MOCK READ ORDER-FILE ROWS
        ( ORDER-QTY = 50 )
        TERMINAL ( ORDER-QTY = 0 )
    END-MOCK
    PERFORM READ-AN-ORDER
"""


def _reasons_for(source: str, cut_text: str):
    result = parse_cobol(source, filename="rrsamp.cbl")
    assert result.success, result.errors
    surface = analyze(result.ast)
    file_status_fields = analyze_file_status_fields(result.ast)
    suite = parse_cut(cut_text)
    case = suite.test_cases[0]
    return check_test_case(surface, result.ast, case, file_status_fields)


def test_read_rows_without_status_field_or_terminal_refuses():
    # program whose SELECT has no FILE STATUS clause; .cut mocks its READ
    # with ROWS and no TERMINAL group
    reasons = _reasons_for(PROGRAM_NO_STATUS_FIELD, CUT_READ_ROWS_NO_TERMINAL)
    assert any(r.code == "UNRESOLVED_FILE_STATUS_TARGET" for r in reasons)
    assert any("TERMINAL" in r.message for r in reasons)


def test_read_rows_with_terminal_but_no_status_field_is_accepted():
    reasons = _reasons_for(PROGRAM_NO_STATUS_FIELD, CUT_READ_ROWS_WITH_TERMINAL)
    assert not [r for r in reasons if r.code == "UNRESOLVED_FILE_STATUS_TARGET"]


CUT_READ_ROWS_SUGAR_NO_TERMINAL = """\
TESTSUITE "s"
TESTCASE "c"
    MOCK READ ORDER-FILE ROWS
        ( ORDER-QTY = 50 )
        FILE-STATUS IS SUCCESS
    END-MOCK
    PERFORM READ-AN-ORDER
"""


def test_file_status_sugar_and_missing_terminal_refuse_only_once():
    """Audit finding F27: when a MOCK READ ... ROWS directive both uses
    FILE-STATUS IS sugar AND is missing a TERMINAL on a file absent from
    file_status_fields, two independent checks used to both fire
    UNRESOLVED_FILE_STATUS_TARGET for the same directive -- still fails
    closed, just redundant and confusing."""
    reasons = _reasons_for(PROGRAM_NO_STATUS_FIELD, CUT_READ_ROWS_SUGAR_NO_TERMINAL)
    matches = [r for r in reasons if r.code == "UNRESOLVED_FILE_STATUS_TARGET"]
    assert len(matches) == 1


def test_check_test_case_defaults_file_status_fields_to_empty():
    """The new parameter is optional -- every existing caller that omits
    it must keep working exactly as before."""
    result = parse_cobol(SOURCE, filename="statchk.cbl")
    surface = analyze(result.ast)
    suite = parse_cut("""\
TESTSUITE "s"
TESTCASE "c"
    MOCK OPEN WITH-STATUS
    END-MOCK
    MOCK OPEN NO-STATUS
    END-MOCK
    PERFORM MAIN-PROCESS
""")
    reasons = check_test_case(surface, result.ast, suite.test_cases[0])
    assert reasons == []
