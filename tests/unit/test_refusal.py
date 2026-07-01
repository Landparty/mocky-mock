from cobolparser import parse_cobol

from mockymock.analysis.mock_surface import analyze
from mockymock.analysis.refusal import (
    check_test_case,
    check_unresolved_copybooks,
    check_whole_program,
)

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

# A CALL nested inside an IF ... END-IF, reachable from START-HERE. Mirrors
# test_mock_surface.py's NESTED_SOURCE CALL-INSIDE-IF shape. Used to prove
# refusal.py refuses a MOCK CALL whose only matching site is nested (the
# splicer cannot safely determine the nested statement's replacement span,
# since cobolparser has no location data for END-IF/END-EVALUATE).
NESTED_CALL_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. NESTEDCALL.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-FLAG            PIC X VALUE "Y".
       01  WS-AMOUNT          PIC 9(5)V99.
       01  WS-RATE            PIC 9V99.

       PROCEDURE DIVISION.
       START-HERE.
           IF WS-FLAG = "Y"
               CALL "DISCRATE" USING WS-AMOUNT WS-RATE
           END-IF.
"""

# Same shape as NESTED_CALL_SOURCE but the CALL "DISCRATE" is top-level, not
# nested inside the IF -- used as the over-refusal regression guard (Step 7):
# a top-level MOCK CALL for the same call name must NOT trigger
# UNSUPPORTED_NESTED_CALL_TARGET.
TOP_LEVEL_CALL_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TOPLEVEL.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-FLAG            PIC X VALUE "Y".
       01  WS-AMOUNT          PIC 9(5)V99.
       01  WS-RATE            PIC 9V99.

       PROCEDURE DIVISION.
       START-HERE.
           CALL "DISCRATE" USING WS-AMOUNT WS-RATE.
           IF WS-FLAG = "Y"
               DISPLAY "NOOP"
           END-IF.
"""

# Same call name ("DISCRATE") appears BOTH top-level AND nested inside an IF
# in the same reachable paragraph. Per the brief's design note: this must
# still refuse, since the splicer would attempt to splice every matching
# site for that name, including the unsafe nested one -- partial safety
# (only the top-level site being splicable) isn't good enough.
MIXED_CALL_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. MIXEDCALL.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-FLAG            PIC X VALUE "Y".
       01  WS-AMOUNT          PIC 9(5)V99.
       01  WS-RATE            PIC 9V99.

       PROCEDURE DIVISION.
       START-HERE.
           CALL "DISCRATE" USING WS-AMOUNT WS-RATE.
           IF WS-FLAG = "Y"
               CALL "DISCRATE" USING WS-AMOUNT WS-RATE
           END-IF.
"""

# One paragraph with TWO different static CALLs. Used to prove the reverse
# of UNMATCHED_MOCK: a reachable static CALL that the .cut simply never
# mocks must be refused too, since an unmocked CALL has nowhere to link
# (the called program's real source is never part of this compilation unit).
TWO_CALL_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TWOCALL.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-AMOUNT          PIC 9(5)V99.
       01  WS-RATE            PIC 9V99.

       PROCEDURE DIVISION.
       START-HERE.
           CALL "DISCRATE" USING WS-AMOUNT WS-RATE.
           CALL "TAXCALC" USING WS-AMOUNT WS-RATE.
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


def _nested_call_result():
    result = parse_cobol(NESTED_CALL_SOURCE, filename="nestedcall.cbl")
    assert result.success, result.errors
    return result


def _top_level_call_result():
    result = parse_cobol(TOP_LEVEL_CALL_SOURCE, filename="toplevel.cbl")
    assert result.success, result.errors
    return result


def _mixed_call_result():
    result = parse_cobol(MIXED_CALL_SOURCE, filename="mixedcall.cbl")
    assert result.success, result.errors
    return result


def _two_call_result():
    result = parse_cobol(TWO_CALL_SOURCE, filename="twocall.cbl")
    assert result.success, result.errors
    return result


def test_whole_program_check_passes_for_clean_parse():
    assert check_whole_program(_result()) == []


def test_whole_program_check_flags_parse_errors():
    bad = parse_cobol("NOT EVEN VALID COBOL { } [ ]", filename="bad.cbl")
    reasons = check_whole_program(bad)
    assert any(r.code == "PARSE_ERROR" for r in reasons)


# Unexpanded COPY statement -- the AST leaves zero trace of this (verified
# empirically: find_all_by_type("CopyStatement") returns [] and "COPY" never
# appears in ast.to_dict()'s JSON), so check_unresolved_copybooks must detect
# it textually via cobolparser's own lexer, not via the AST.
UNRESOLVED_COPY_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. MAINPGM.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
           COPY ORDREC.

       PROCEDURE DIVISION.
       PROCESS-ORDER.
           CALL "DISCRATE" USING ORD-AMOUNT WS-DISCOUNT-PCT.
"""

# Same shape, but with "COPY" appearing only inside a string literal and as
# a substring of an identifier -- neither should be detected as an
# unresolved COPY statement (false-positive probe for the lexer-based
# detector, not a naive substring search).
NO_COPY_STATEMENT_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. NOCOPY.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-MSG        PIC X(20) VALUE "THIS IS A COPY TEST".
       01  WS-COPYRIGHT  PIC X(5) VALUE "COPY!".

       PROCEDURE DIVISION.
       MAIN-PARA.
           DISPLAY WS-MSG.
"""


def test_check_unresolved_copybooks_flags_unexpanded_copy_statement():
    reasons = check_unresolved_copybooks(UNRESOLVED_COPY_SOURCE)
    assert any(r.code == "UNRESOLVED_COPYBOOK" for r in reasons)


def test_check_unresolved_copybooks_passes_clean_source():
    assert check_unresolved_copybooks(SOURCE) == []


def test_check_unresolved_copybooks_does_not_false_positive_on_copy_substring():
    """'COPY' appearing inside a string literal or as part of another
    identifier (WS-COPYRIGHT) must not be mistaken for a COPY statement --
    this is the concrete proof the detector is lexer-based, not a naive
    substring search."""
    reasons = check_unresolved_copybooks(NO_COPY_STATEMENT_SOURCE)
    assert reasons == []


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


def test_per_case_check_refuses_mock_call_targeting_nested_call_site():
    """A MOCK CALL "DISCRATE" whose only matching CALL site is nested inside
    an IF must be refused: the splicer cannot safely determine the nested
    statement's replacement span, since cobolparser has no location data for
    block terminators like END-IF (see the corrected Task 14 Step 6 design
    -- recursing the splicer into nested bodies was tried and found unsafe,
    so refusal.py refuses instead)."""
    result = _nested_call_result()
    surface = analyze(result.ast)
    reasons = check_test_case(
        surface, result.ast, "START-HERE", mocked_call_names={"DISCRATE"}
    )
    assert any(r.code == "UNSUPPORTED_NESTED_CALL_TARGET" for r in reasons)


def test_per_case_check_allows_mock_call_targeting_top_level_call_site():
    """Regression guard against over-refusing: a MOCK CALL for a call name
    that only has a top-level (non-nested) matching site must NOT trigger
    UNSUPPORTED_NESTED_CALL_TARGET, even though the same paragraph also
    contains an unrelated IF block."""
    result = _top_level_call_result()
    surface = analyze(result.ast)
    reasons = check_test_case(
        surface, result.ast, "START-HERE", mocked_call_names={"DISCRATE"}
    )
    assert not any(r.code == "UNSUPPORTED_NESTED_CALL_TARGET" for r in reasons)


def test_per_case_check_refuses_mock_call_with_both_top_level_and_nested_site():
    """A call name with BOTH a top-level occurrence and a nested occurrence
    (both reachable) must still refuse: the splicer would attempt to splice
    every matching site for that name, including the unsafe nested one, so
    partial safety (only the top-level site being splicable) isn't good
    enough. Guards against a naive `all(nested)` implementation that would
    wrongly allow this mixed case."""
    result = _mixed_call_result()
    surface = analyze(result.ast)
    reasons = check_test_case(
        surface, result.ast, "START-HERE", mocked_call_names={"DISCRATE"}
    )
    assert any(r.code == "UNSUPPORTED_NESTED_CALL_TARGET" for r in reasons)


def test_per_case_check_refuses_reachable_static_call_left_unmocked():
    """A paragraph with two static CALLs, mocking only one: the other CALL
    is reachable but has nowhere to link if left unmocked (the called
    program's real source is never part of this compilation unit), so it
    must be refused with UNMOCKED_CALL rather than crashing at compile/link
    time."""
    result = _two_call_result()
    surface = analyze(result.ast)
    reasons = check_test_case(
        surface, result.ast, "START-HERE", mocked_call_names={"DISCRATE"}
    )
    unmocked = [r for r in reasons if r.code == "UNMOCKED_CALL"]
    assert len(unmocked) == 1
    assert "TAXCALC" in unmocked[0].message


def test_per_case_check_allows_when_every_reachable_static_call_is_mocked():
    """Regression guard against over-refusing: when every reachable static
    CALL site is mocked, UNMOCKED_CALL must not fire."""
    result = _two_call_result()
    surface = analyze(result.ast)
    reasons = check_test_case(
        surface,
        result.ast,
        "START-HERE",
        mocked_call_names={"DISCRATE", "TAXCALC"},
    )
    assert not any(r.code == "UNMOCKED_CALL" for r in reasons)


def test_per_case_check_unmocked_nested_call_gets_only_unmocked_call_code():
    """A reachable static call that's both nested AND unmocked should get
    only UNMOCKED_CALL, not UNSUPPORTED_NESTED_CALL_TARGET -- that check
    only fires when the name IS in mocked_call_names (catches 'tried to mock
    a nested site'); this catches the separate case of 'didn't even try'."""
    result = _nested_call_result()
    surface = analyze(result.ast)
    reasons = check_test_case(
        surface, result.ast, "START-HERE", mocked_call_names=set()
    )
    assert any(r.code == "UNMOCKED_CALL" for r in reasons)
    assert not any(r.code == "UNSUPPORTED_NESTED_CALL_TARGET" for r in reasons)
