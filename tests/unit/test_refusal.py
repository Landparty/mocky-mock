from cobolparser import parse_cobol

from mockymock.analysis.mock_surface import analyze
from mockymock.analysis.refusal import check_test_case, check_whole_program

SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SAMPLE.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-PGM-NAME        PIC X(8) VALUE "DISCRATE".
       01  WS-AMOUNT          PIC 9(5)V99.
       01  WS-RATE            PIC 9V99.

       PROCEDURE DIVISION.
       SAFE-PARAGRAPH.
           CALL "DISCRATE" USING WS-AMOUNT WS-RATE.

       DYNAMIC-PARAGRAPH.
           CALL WS-PGM-NAME USING WS-AMOUNT.

       WRAPPER-PARAGRAPH.
           PERFORM DYNAMIC-PARAGRAPH.
"""

# File I/O source: mirrors tests/unit/test_mock_surface.py's proven-parseable
# SELECT/FD shape so READ-AN-ORDER is flagged in surface.file_io_paragraphs.
FILE_IO_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. FILESAMP.

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
       01  WS-AMOUNT          PIC 9(5)V99.

       PROCEDURE DIVISION.
       READ-AN-ORDER.
           READ ORDER-FILE
               AT END DISPLAY "EOF"
           END-READ.

       CALLS-READ-AN-ORDER.
           PERFORM READ-AN-ORDER.
"""

# EXEC SQL source: mirrors tests/unit/test_mock_surface.py's EXEC_SOURCE shape
# so RUN-SQL is flagged in surface.exec_paragraphs.
EXEC_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. EXECSAMP.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-CUST-ID         PIC 9(5).

       PROCEDURE DIVISION.
       RUN-SQL.
           EXEC SQL
               SELECT CUST_ID INTO :WS-CUST-ID FROM CUSTOMERS
           END-EXEC.

       CALLS-RUN-SQL.
           PERFORM RUN-SQL.
"""

# Three-level PERFORM chain (A -> B -> C) with the dangerous construct only
# in C, to prove the BFS chains through a pass-through paragraph rather than
# only checking direct PERFORM targets.
CHAIN_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CHAINSAMP.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-PGM-NAME        PIC X(8) VALUE "DISCRATE".
       01  WS-AMOUNT          PIC 9(5)V99.

       PROCEDURE DIVISION.
       PARAGRAPH-A.
           PERFORM PARAGRAPH-B.

       PARAGRAPH-B.
           PERFORM PARAGRAPH-C.

       PARAGRAPH-C.
           CALL WS-PGM-NAME USING WS-AMOUNT.
"""

# The finding's own repro: WRAPPER-PARAGRAPH's PERFORM to DYNAMIC-PARAGRAPH
# is nested inside an IF, not top-level. A BFS that only reads
# paragraph.statements (flat) never sees this PERFORM and wrongly reports
# DYNAMIC-PARAGRAPH's dynamic CALL as unreachable.
NESTED_IF_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. NESTEDIF.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-PGM-NAME        PIC X(8) VALUE "DISCRATE".
       01  WS-AMOUNT          PIC 9(5)V99.
       01  WS-FLAG            PIC X VALUE "Y".

       PROCEDURE DIVISION.
       DYNAMIC-PARAGRAPH.
           CALL WS-PGM-NAME USING WS-AMOUNT.

       WRAPPER-PARAGRAPH.
           IF WS-FLAG = "Y"
               PERFORM DYNAMIC-PARAGRAPH
           END-IF.
"""

# PERFORM ... THRU reachable from START-HERE. No dynamic CALL/file-IO/EXEC
# anywhere, so UNSUPPORTED_PERFORM_THRU should be the only reason surfaced.
PERFORM_THRU_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. THRUSAMP.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-AMOUNT          PIC 9(5)V99.

       PROCEDURE DIVISION.
       START-HERE.
           PERFORM RANGE-START THRU RANGE-END.

       RANGE-START.
           DISPLAY "START".

       RANGE-END.
           DISPLAY "END".
"""


def _result():
    result = parse_cobol(SOURCE, filename="sample.cbl")
    assert result.success, result.errors
    return result


def _file_io_result():
    result = parse_cobol(FILE_IO_SOURCE, filename="filesamp.cbl")
    assert result.success, result.errors
    return result


def _exec_result():
    result = parse_cobol(EXEC_SOURCE, filename="execsamp.cbl")
    assert result.success, result.errors
    return result


def _chain_result():
    result = parse_cobol(CHAIN_SOURCE, filename="chainsamp.cbl")
    assert result.success, result.errors
    return result


def _nested_if_result():
    result = parse_cobol(NESTED_IF_SOURCE, filename="nestedif.cbl")
    assert result.success, result.errors
    return result


def _perform_thru_result():
    result = parse_cobol(PERFORM_THRU_SOURCE, filename="thrusamp.cbl")
    assert result.success, result.errors
    return result


def test_whole_program_check_passes_for_clean_parse():
    assert check_whole_program(_result()) == []


def test_whole_program_check_flags_parse_errors():
    bad = parse_cobol("NOT EVEN VALID COBOL { } [ ]", filename="bad.cbl")
    reasons = check_whole_program(bad)
    assert any(r.code == "PARSE_ERROR" for r in reasons)


def test_per_case_check_allows_static_call_only_paragraph():
    result = _result()
    surface = analyze(result.ast)
    reasons = check_test_case(
        surface, result.ast, "SAFE-PARAGRAPH", mocked_call_names={"DISCRATE"}
    )
    assert reasons == []


def test_per_case_check_refuses_unreachable_dynamic_call_target():
    result = _result()
    surface = analyze(result.ast)
    reasons = check_test_case(
        surface, result.ast, "DYNAMIC-PARAGRAPH", mocked_call_names=set()
    )
    assert any(r.code == "DYNAMIC_CALL" for r in reasons)


def test_per_case_check_follows_perform_to_find_dynamic_call():
    result = _result()
    surface = analyze(result.ast)
    reasons = check_test_case(
        surface, result.ast, "WRAPPER-PARAGRAPH", mocked_call_names=set()
    )
    assert any(r.code == "DYNAMIC_CALL" for r in reasons)


def test_per_case_check_refuses_unmatched_mock_call():
    result = _result()
    surface = analyze(result.ast)
    reasons = check_test_case(
        surface,
        result.ast,
        "SAFE-PARAGRAPH",
        mocked_call_names={"SOME-OTHER-PROGRAM"},
    )
    assert any(r.code == "UNMATCHED_MOCK" for r in reasons)


def test_per_case_check_refuses_reachable_file_io():
    result = _file_io_result()
    surface = analyze(result.ast)
    reasons = check_test_case(
        surface, result.ast, "CALLS-READ-AN-ORDER", mocked_call_names=set()
    )
    assert any(r.code == "UNMOCKED_FILE_IO" for r in reasons)


def test_per_case_check_refuses_reachable_exec_sql():
    result = _exec_result()
    surface = analyze(result.ast)
    reasons = check_test_case(
        surface, result.ast, "CALLS-RUN-SQL", mocked_call_names=set()
    )
    assert any(r.code == "UNSUPPORTED_EXEC" for r in reasons)


def test_per_case_check_follows_multi_hop_perform_chain_to_dynamic_call():
    """A performs B performs C, with the dynamic CALL only in C. The BFS
    must chain through the pass-through paragraph B, not just check A's
    direct PERFORM targets."""
    result = _chain_result()
    surface = analyze(result.ast)
    reasons = check_test_case(
        surface, result.ast, "PARAGRAPH-A", mocked_call_names=set()
    )
    assert any(r.code == "DYNAMIC_CALL" for r in reasons)


def test_per_case_check_finds_perform_nested_inside_if_to_dynamic_call():
    """Regression for the Task 6 Critical finding: WRAPPER-PARAGRAPH's
    PERFORM DYNAMIC-PARAGRAPH is nested inside an IF, not a top-level
    statement. A BFS that only reads paragraph.statements flatly would miss
    this PERFORM entirely and wrongly report zero refusal reasons even
    though the dynamic CALL is genuinely reachable."""
    result = _nested_if_result()
    surface = analyze(result.ast)
    reasons = check_test_case(
        surface, result.ast, "WRAPPER-PARAGRAPH", mocked_call_names=set()
    )
    assert any(r.code == "DYNAMIC_CALL" for r in reasons)


def test_per_case_check_refuses_reachable_perform_thru():
    """PERFORM ... THRU is never range-expanded by the BFS (source-order
    guarantees aren't verified); a reachable PERFORM...THRU must instead
    surface its own fail-closed UNSUPPORTED_PERFORM_THRU refusal."""
    result = _perform_thru_result()
    surface = analyze(result.ast)
    reasons = check_test_case(
        surface, result.ast, "START-HERE", mocked_call_names=set()
    )
    assert any(r.code == "UNSUPPORTED_PERFORM_THRU" for r in reasons)
