from cobolparser import parse_cobol

from mockymock.analysis.mock_surface import analyze
from mockymock.analysis.refusal import (
    _expand_thru_range,
    check_expansion_warnings,
    check_nested_exec,
    check_test_case,
    check_unresolved_copybooks,
    check_whole_program,
)
from mockymock.dsl.model import MockCategory, MockDirective, MockTestCase


def _case(perform_target, call_names=(), mocks=(), verifications=(), perform_thru=None):
    return MockTestCase(
        name="case",
        mocks=[MockDirective(MockCategory.CALL, n) for n in call_names]
        + list(mocks),
        perform_target=perform_target,
        perform_thru=perform_thru,
        verifications=list(verifications),
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

# PERFORM ... THRU reachable from START-HERE: the RANGE-START..RANGE-END
# range is expanded in source order, so the CALL in RANGE-MID (a range
# member never PERFORMed directly) and the CALL in HELPER-PARA (reached
# via RANGE-MID's own nested single-member THRU) are both reachable; the
# in-range GO TO RANGE-END is covered positionally. RANGE-MID's
# "PERFORM ... THRU <x>." sentence followed by another statement is the
# (verified) layout that makes cobolparser emit an empty phantom "."
# paragraph INSIDE the outer range -- expansion must tolerate phantom
# members.
PERFORM_THRU_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. THRUSAMP.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-AMOUNT          PIC 9(5)V99.

       PROCEDURE DIVISION.
       START-HERE.
           PERFORM RANGE-START THRU RANGE-END.
           STOP RUN.

       RANGE-START.
           DISPLAY "START".

       RANGE-MID.
           PERFORM HELPER-PARA THRU HELPER-PARA.
           CALL "MIDCALL" USING WS-AMOUNT.
           GO TO RANGE-END.

       RANGE-END.
           DISPLAY "END".

       HELPER-PARA.
           CALL "HELPCALL" USING WS-AMOUNT.
"""

# Degenerate ranges: endpoints reversed in source order / endpoint that
# does not exist. Both must refuse fail-closed, never best-effort.
BACKWARDS_THRU_SOURCE = PERFORM_THRU_SOURCE.replace(
    "PERFORM RANGE-START THRU RANGE-END.", "PERFORM RANGE-END THRU RANGE-START."
)
MISSING_THRU_SOURCE = PERFORM_THRU_SOURCE.replace(
    "PERFORM RANGE-START THRU RANGE-END.", "PERFORM RANGE-START THRU NO-SUCH-PARA."
)

# Duplicate endpoint name across two sections: the range is ambiguous.
DUP_THRU_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. DUPSAMP.

       PROCEDURE DIVISION.
       MAIN SECTION.
       START-HERE.
           PERFORM DUP-PARA THRU LAST-PARA.
           STOP RUN.

       WORK-A SECTION.
       DUP-PARA.
           DISPLAY "A".

       WORK-B SECTION.
       DUP-PARA.
           DISPLAY "B".

       LAST-PARA.
           DISPLAY "Z".
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


# An unsupported verb parses "clean" (success=True, errors=0) but the
# statement is dropped from the AST with only a ParseResult.warnings entry
# (cobolparser 2026-07-07 silent-drop remediation). Splicing an AST that is
# missing statements would silently drop program behavior, so each warning
# must refuse fail-closed.
UNSUPPORTED_VERB_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. INVOKER.

       PROCEDURE DIVISION.
       MAIN-PARA.
           INVOKE SOME-OBJECT "someMethod".
           DISPLAY "done".
"""


def test_whole_program_check_flags_parse_warnings():
    result = parse_cobol(UNSUPPORTED_VERB_SOURCE, filename="invoker.cbl")
    assert result.success, result.errors
    assert result.warnings  # precondition: the INVOKE drop is warned about
    reasons = check_whole_program(result)
    assert any(r.code == "PARSE_WARNING" for r in reasons)
    assert any("INVOKE" in r.message for r in reasons)


# Multi-program compilation units parse into ast.contained_programs with a
# summary warning; mockymock's splicer and reachability BFS only ever look
# at the first program's divisions, so these must refuse rather than test a
# fraction of the file.
MULTI_PROGRAM_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. FIRSTPGM.
       PROCEDURE DIVISION.
       A-PARA.
           DISPLAY "one".
       END PROGRAM FIRSTPGM.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SECONDPGM.
       PROCEDURE DIVISION.
       B-PARA.
           DISPLAY "two".
       END PROGRAM SECONDPGM.
"""


def test_whole_program_check_flags_multi_program_units():
    result = parse_cobol(MULTI_PROGRAM_SOURCE, filename="multi.cbl")
    assert result.success, result.errors
    reasons = check_whole_program(result)
    assert any(r.code == "PARSE_WARNING" for r in reasons)


COPY_PROGRAM_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. LOSSYPGM.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
           COPY BADREC.

       PROCEDURE DIVISION.
       MAIN-PARA.
           DISPLAY BAD-FIELD.
"""


def test_expansion_warnings_refuse_lossy_copybook_decode(tmp_path):
    """A copybook whose bytes cannot be decoded losslessly is expanded with
    U+FFFD replacement characters and the loss is reported only via
    `CopybookExpansion.statistics.warnings` -- the expanded source would
    still splice and compile, with corrupted PIC/VALUE content. Fail closed."""
    from cobolparser.preprocess import expand_copybooks

    (tmp_path / "BADREC.CPY").write_bytes(
        b"       01  BAD-FIELD PIC X(5) VALUE 'ab\xffcd'.\n"
    )
    expansion = expand_copybooks(
        COPY_PROGRAM_SOURCE, copybook_paths=[str(tmp_path)]
    )
    assert expansion.statistics.warnings  # precondition: the loss is warned
    reasons = check_expansion_warnings(expansion)
    assert any(r.code == "EXPANSION_WARNING" for r in reasons)


def test_expansion_warnings_pass_for_clean_expansion(tmp_path):
    from cobolparser.preprocess import expand_copybooks

    (tmp_path / "BADREC.CPY").write_text(
        "       01  BAD-FIELD PIC X(5) VALUE 'abcde'.\n"
    )
    expansion = expand_copybooks(
        COPY_PROGRAM_SOURCE, copybook_paths=[str(tmp_path)]
    )
    assert check_expansion_warnings(expansion) == []


def test_expansion_warnings_ignore_advisory_lint(tmp_path):
    """`ExpansionStatistics.warnings` also carries advisory heuristics (e.g.
    "may be missing terminating period") that false-positive on valid
    copybooks; only lossy-decode diagnostics may refuse, or working programs
    would be rejected."""

    class _FakeStats:
        warnings = [
            "Line 1 in 'X.CPY' may be missing terminating period",
            "Copybook 'Y.CPY' contains only comments",
        ]

    class _FakeExpansion:
        statistics = _FakeStats()

    assert check_expansion_warnings(_FakeExpansion()) == []


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
        surface, result.ast, _case("SAFE-PARAGRAPH", call_names={"DISCRATE"})
    )
    assert reasons == []


def test_per_case_check_refuses_unmocked_dynamic_call():
    """Identifier-carrying dynamic CALLs are mockable since the 2026-07-06
    dynamic-call design; reachable-but-unmocked ones refuse UNMOCKED_CALL
    like any other unmocked call."""
    result = _result()
    surface = analyze(result.ast)
    reasons = check_test_case(
        surface, result.ast, _case("DYNAMIC-PARAGRAPH", call_names=())
    )
    assert any(r.code == "UNMOCKED_CALL" for r in reasons)


def test_per_case_check_follows_perform_to_find_dynamic_call():
    result = _result()
    surface = analyze(result.ast)
    reasons = check_test_case(
        surface, result.ast, _case("WRAPPER-PARAGRAPH", call_names=())
    )
    assert any(r.code == "UNMOCKED_CALL" for r in reasons)


def test_per_case_check_refuses_unmatched_mock_call():
    result = _result()
    surface = analyze(result.ast)
    reasons = check_test_case(
        surface, result.ast, _case("SAFE-PARAGRAPH", call_names={"SOME-OTHER-PROGRAM"})
    )
    assert any(r.code == "UNMATCHED_MOCK" for r in reasons)


def test_per_case_check_refuses_reachable_file_io():
    result = _file_io_result()
    surface = analyze(result.ast)
    reasons = check_test_case(
        surface, result.ast, _case("CALLS-READ-AN-ORDER", call_names=())
    )
    assert any(r.code == "UNMOCKED_FILE_OP" for r in reasons)


def test_per_case_check_refuses_reachable_exec_sql():
    result = _exec_result()
    surface = analyze(result.ast)
    reasons = check_test_case(
        surface, result.ast, _case("CALLS-RUN-SQL", call_names=())
    )
    assert any(r.code == "UNMOCKED_SQL" for r in reasons)


def test_per_case_check_follows_multi_hop_perform_chain_to_dynamic_call():
    """A performs B performs C, with the dynamic CALL only in C. The BFS
    must chain through the pass-through paragraph B, not just check A's
    direct PERFORM targets."""
    result = _chain_result()
    surface = analyze(result.ast)
    reasons = check_test_case(
        surface, result.ast, _case("PARAGRAPH-A", call_names=())
    )
    assert any(r.code == "UNMOCKED_CALL" for r in reasons)


def test_per_case_check_finds_perform_nested_inside_if_to_dynamic_call():
    """Regression for the Task 6 Critical finding: WRAPPER-PARAGRAPH's
    PERFORM DYNAMIC-PARAGRAPH is nested inside an IF, not a top-level
    statement. A BFS that only reads paragraph.statements flatly would miss
    this PERFORM entirely and wrongly report zero refusal reasons even
    though the dynamic CALL is genuinely reachable."""
    result = _nested_if_result()
    surface = analyze(result.ast)
    reasons = check_test_case(
        surface, result.ast, _case("WRAPPER-PARAGRAPH", call_names=())
    )
    assert any(r.code == "UNMOCKED_CALL" for r in reasons)


def test_per_case_check_expands_perform_thru_range():
    """The THRU range is expanded in source order: both the CALL in a
    mid-range paragraph and the CALL reached transitively from it are
    reachable -- unmocked they surface UNMOCKED_CALL, mocked the case is
    clean. UNSUPPORTED_PERFORM_THRU no longer fires for a well-formed
    range."""
    result = _perform_thru_result()
    surface = analyze(result.ast)
    reasons = check_test_case(
        surface, result.ast, _case("START-HERE", call_names=())
    )
    codes = [r.code for r in reasons]
    assert "UNSUPPORTED_PERFORM_THRU" not in codes
    assert codes.count("UNMOCKED_CALL") == 2

    reasons = check_test_case(
        surface,
        result.ast,
        _case("START-HERE", call_names=("MIDCALL", "HELPCALL")),
    )
    assert reasons == []


def test_per_case_check_refuses_backwards_thru_range():
    result = parse_cobol(BACKWARDS_THRU_SOURCE, filename="backthru.cbl")
    assert result.success, result.errors
    surface = analyze(result.ast)
    reasons = check_test_case(
        surface, result.ast, _case("START-HERE", call_names=())
    )
    thru = [r for r in reasons if r.code == "UNSUPPORTED_PERFORM_THRU"]
    assert len(thru) == 1
    assert "backwards" in thru[0].message


def test_per_case_check_refuses_missing_thru_endpoint():
    result = parse_cobol(MISSING_THRU_SOURCE, filename="missthru.cbl")
    assert result.success, result.errors
    surface = analyze(result.ast)
    reasons = check_test_case(
        surface, result.ast, _case("START-HERE", call_names=())
    )
    thru = [r for r in reasons if r.code == "UNSUPPORTED_PERFORM_THRU"]
    assert len(thru) == 1
    assert "NO-SUCH-PARA" in thru[0].message


def test_per_case_check_refuses_ambiguous_thru_endpoint():
    result = parse_cobol(DUP_THRU_SOURCE, filename="dupthru.cbl")
    assert result.success, result.errors
    surface = analyze(result.ast)
    reasons = check_test_case(
        surface, result.ast, _case("START-HERE", call_names=())
    )
    thru = [r for r in reasons if r.code == "UNSUPPORTED_PERFORM_THRU"]
    assert len(thru) == 1
    assert "DUP-PARA" in thru[0].message


def test_per_case_check_seeds_driver_side_thru_range():
    """A .cut `PERFORM RANGE-START THRU RANGE-END` seeds reachability with
    the whole range even though no in-program PERFORM points at it."""
    result = _perform_thru_result()
    surface = analyze(result.ast)
    case = _case(
        "RANGE-START", call_names=("MIDCALL", "HELPCALL"), perform_thru="RANGE-END"
    )
    assert check_test_case(surface, result.ast, case) == []

    unmocked = _case("RANGE-START", call_names=(), perform_thru="RANGE-END")
    codes = [r.code for r in check_test_case(surface, result.ast, unmocked)]
    assert codes.count("UNMOCKED_CALL") == 2


def test_per_case_check_unknown_driver_side_thru_endpoint():
    result = _perform_thru_result()
    surface = analyze(result.ast)
    case = _case("RANGE-START", call_names=(), perform_thru="NO-SUCH-PARA")
    reasons = check_test_case(surface, result.ast, case)
    assert any(r.code == "UNKNOWN_PARAGRAPH" for r in reasons)


def test_expand_thru_range_refuses_unverifiable_order():
    """The runtime source-order guarantee: when ordering could not be
    verified (`ordered is None`, a parser-regression guard no real program
    triggers), expansion refuses instead of guessing."""
    members, problem = _expand_thru_range(None, "A", "B", "paragraph 'X'")
    assert members == []
    assert problem.code == "UNSUPPORTED_PERFORM_THRU"
    assert "source order" in problem.message


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
        surface, result.ast, _case("START-HERE", call_names={"DISCRATE"})
    )
    assert any(r.code == "UNSUPPORTED_NESTED_MOCK_TARGET" for r in reasons)


def test_per_case_check_allows_mock_call_targeting_top_level_call_site():
    """Regression guard against over-refusing: a MOCK CALL for a call name
    that only has a top-level (non-nested) matching site must NOT trigger
    UNSUPPORTED_NESTED_CALL_TARGET, even though the same paragraph also
    contains an unrelated IF block."""
    result = _top_level_call_result()
    surface = analyze(result.ast)
    reasons = check_test_case(
        surface, result.ast, _case("START-HERE", call_names={"DISCRATE"})
    )
    assert not any(r.code == "UNSUPPORTED_NESTED_MOCK_TARGET" for r in reasons)


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
        surface, result.ast, _case("START-HERE", call_names={"DISCRATE"})
    )
    assert any(r.code == "UNSUPPORTED_NESTED_MOCK_TARGET" for r in reasons)


def test_per_case_check_refuses_reachable_static_call_left_unmocked():
    """A paragraph with two static CALLs, mocking only one: the other CALL
    is reachable but has nowhere to link if left unmocked (the called
    program's real source is never part of this compilation unit), so it
    must be refused with UNMOCKED_CALL rather than crashing at compile/link
    time."""
    result = _two_call_result()
    surface = analyze(result.ast)
    reasons = check_test_case(
        surface, result.ast, _case("START-HERE", call_names={"DISCRATE"})
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
        surface, result.ast, _case("START-HERE", call_names={"DISCRATE", "TAXCALC"})
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
        surface, result.ast, _case("START-HERE", call_names=())
    )
    assert any(r.code == "UNMOCKED_CALL" for r in reasons)
    assert not any(r.code == "UNSUPPORTED_NESTED_MOCK_TARGET" for r in reasons)


# START/UNLOCK/SORT are file I/O just like OPEN/READ/WRITE; console ACCEPT
# reads stdin at runtime. All must hit the per-case refusal gate when
# reachable, and must NOT when the test only reaches pure-compute paragraphs.
FILE_FAMILY_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. FILEFAM.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT ORDER-FILE ASSIGN TO "ORDERS"
               ORGANIZATION IS INDEXED
               RECORD KEY IS ORDER-KEY.

       DATA DIVISION.
       FILE SECTION.
       FD  ORDER-FILE.
       01  ORDER-RECORD.
           05  ORDER-KEY      PIC X(5).
           05  ORDER-BODY     PIC X(6).

       WORKING-STORAGE SECTION.
       01  WS-KEY             PIC X(5).
       01  WS-NAME            PIC X(10).

       PROCEDURE DIVISION.
       STARTS-THE-FILE.
           START ORDER-FILE KEY IS EQUAL TO ORDER-KEY.

       SORTS-THE-FILE.
           SORT SORT-FILE ON ASCENDING KEY WS-KEY
               USING IN-FILE GIVING OUT-FILE.

       READS-THE-CONSOLE.
           ACCEPT WS-NAME.

       CALLS-STARTS-THE-FILE.
           PERFORM STARTS-THE-FILE.

       PURE-COMPUTE.
           MOVE WS-KEY TO WS-NAME.
"""


def _file_family_result():
    result = parse_cobol(FILE_FAMILY_SOURCE, filename="filefam.cbl")
    assert result.success, result.errors
    return result


def test_per_case_check_refuses_reachable_start_statement():
    result = _file_family_result()
    surface = analyze(result.ast)
    reasons = check_test_case(
        surface, result.ast, _case("CALLS-STARTS-THE-FILE", call_names=())
    )
    assert any(r.code == "UNMOCKED_FILE_OP" for r in reasons)


def test_per_case_check_refuses_reachable_sort_statement():
    result = _file_family_result()
    surface = analyze(result.ast)
    reasons = check_test_case(
        surface, result.ast, _case("SORTS-THE-FILE", call_names=())
    )
    assert any(r.code == "UNSUPPORTED_SORT_MERGE" for r in reasons)


def test_per_case_check_refuses_reachable_console_accept():
    result = _file_family_result()
    surface = analyze(result.ast)
    reasons = check_test_case(
        surface, result.ast, _case("READS-THE-CONSOLE", call_names=())
    )
    assert any(r.code == "UNMOCKED_CONSOLE_ACCEPT" for r in reasons)


def test_per_case_check_allows_pure_compute_next_to_file_family():
    result = _file_family_result()
    surface = analyze(result.ast)
    reasons = check_test_case(
        surface, result.ast, _case("PURE-COMPUTE", call_names=())
    )
    assert reasons == []
