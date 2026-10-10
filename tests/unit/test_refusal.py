import pytest
from cobolparser import parse_cobol

from mockymock.analysis.mock_surface import _all_paragraphs, analyze
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
        mocks=[MockDirective(MockCategory.CALL, n) for n in call_names] + list(mocks),
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

       SIZE-ERROR-PARAGRAPH.
           ADD 1 TO WS-AMOUNT
               ON SIZE ERROR
                   CALL "DISCRATE" USING WS-AMOUNT WS-RATE.
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


# SAFE-PARAGRAPH's static CALL "DISCRATE" in isolation: no other paragraph
# anywhere in the program shares its key. Contrast with SOURCE above, where
# the SAME literal key also matches the unspliceable nested CALL inside
# SIZE-ERROR-PARAGRAPH's ON SIZE ERROR clause -- a paragraph SAFE-PARAGRAPH
# itself never reaches, exercised by
# test_per_case_check_refuses_nested_mock_target_matched_program_wide below.
ISOLATED_CALL_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ISOLATED.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-AMOUNT          PIC 9(5)V99.
       01  WS-RATE            PIC 9V99.

       PROCEDURE DIVISION.
       SAFE-PARAGRAPH.
           CALL "DISCRATE" USING WS-AMOUNT WS-RATE.
"""


def _isolated_call_result():
    result = parse_cobol(ISOLATED_CALL_SOURCE, filename="isolated.cbl")
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
#
# Originally used INVOKE as the unsupported verb, then EXHIBIT once
# cobolparser registered a real parser for INVOKE. cobol-parser's
# 2026-09-02 statement-coverage work gave EVERY real COBOL verb a parser
# (EXHIBIT, TRANSFORM, CHAIN, SEND/RECEIVE, ... included), so the
# warn-and-discard path now only covers the three verb-shaped reserved
# words no dialect defines as a statement: EXECUTE, GOTO, RECOVER
# (procedure_recovery.py's UNSUPPORTED_VERBS). RECOVER is used here to
# keep this test's fail-closed-on-any-warning behavior under real coverage
# rather than silently degrading to a no-op precondition failure -- and
# it warns identically on every cobol-parser release this project
# supports, so the test is version-independent.
UNSUPPORTED_VERB_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. INVOKER.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-FIELD PIC X(5).

       PROCEDURE DIVISION.
       MAIN-PARA.
           RECOVER WS-FIELD.
           DISPLAY "done".
"""


def test_whole_program_check_flags_parse_warnings():
    result = parse_cobol(UNSUPPORTED_VERB_SOURCE, filename="invoker.cbl")
    assert result.success, result.errors
    assert result.warnings  # precondition: the RECOVER drop is warned about
    reasons = check_whole_program(result)
    assert any(r.code == "PARSE_WARNING" for r in reasons)
    assert any("RECOVER" in r.message for r in reasons)


# Regression pin for a gap the 2026-07-09 final branch review surfaced,
# now resolved upstream: cobolparser's out-of-line PERFORM path (`PERFORM
# paragraph-name VARYING ...`, as opposed to the inline `PERFORM VARYING
# ... END-PERFORM` block form) used to silently drop the trailing VARYING
# clause, leaving `PerformStatement.perform_type` mistagged as "SIMPLE"
# (indistinguishable from a genuine plain PERFORM to
# refusal._plain_perform_edges_from). What actually protected this shape
# at the time was a wholly unrelated mechanism -- cobolparser also emitted
# an "Unparsed tokens starting at 'VARYING' ... dropped from the AST"
# warning, which check_whole_program refused via PARSE_WARNING before
# find_terminator_plans ever ran -- not the perform_type guard the
# mistagging should have defeated. cobolparser now parses this clause
# correctly (perform_type == "VARYING", no warnings), confirmed directly
# below. The terminator-safety regression test for this shape now lives in
# tests/unit/test_terminators.py::test_terminator_reached_only_through_a_varying_loop_body_refuses,
# proving the *intended* perform_type guard excludes it on its own now
# that the accidental PARSE_WARNING safety net this test used to pin no
# longer fires for this shape.
OUT_OF_LINE_PERFORM_VARYING_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. VARYOUT.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-I                PIC 9(2) VALUE 0.

       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           PERFORM 1000-LOOP-BODY
               VARYING WS-I FROM 1 BY 1 UNTIL WS-I > 5.

       1000-LOOP-BODY.
           STOP RUN.
"""


def test_out_of_line_perform_varying_parses_correctly():
    """Documents the AST-level fact test_terminators.py's sibling
    regression test depends on: this shape now parses clean, with
    perform_type correctly tagged "VARYING" rather than mistagged
    "SIMPLE"."""
    result = parse_cobol(OUT_OF_LINE_PERFORM_VARYING_SOURCE, filename="varyout.cbl")
    assert result.success, result.errors
    assert result.warnings == []  # the VARYING clause is no longer dropped
    procedure = result.ast.get_division("PROCEDURE")
    main_para = next(
        p for p in procedure.paragraphs if p.paragraph_name == "0000-MAIN-PROCESS"
    )
    perform = main_para.statements[0]
    assert perform.target_paragraph == "1000-LOOP-BODY"
    assert perform.thru_paragraph is None
    assert perform.perform_type == "VARYING"  # correctly tagged now


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
    """A multi-unit compilation unit (nested/stacked PROGRAM-IDs, an OO
    class) is refused under its own code: cobol-parser parses every unit
    (the AST is complete), it is mockymock that only splices and gates the
    outermost one -- so the reason names *that*, not dropped content."""
    result = parse_cobol(MULTI_PROGRAM_SOURCE, filename="multi.cbl")
    assert result.success, result.errors
    reasons = check_whole_program(result)
    assert [r.code for r in reasons] == ["UNSUPPORTED_NESTED_PROGRAM"]
    assert "outermost unit" in reasons[0].message
    assert not any(r.code == "PARSE_WARNING" for r in reasons)


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


# > 64 KiB of plain-ASCII comment lines: pushes a following bad byte past
# cobol-parser's encoding-detection sample (`_DETECT_PREFIX_BYTES`).
LOSSY_COPYBOOK_PADDING = b"".join(
    b"      * PADDING %05d" % i + b" " * 50 + b"\n" for i in range(1200)
)


def test_expansion_warnings_refuse_lossy_copybook_decode(tmp_path):
    """A copybook whose bytes cannot be decoded losslessly is expanded with
    U+FFFD replacement characters and the loss is reported only via
    `CopybookExpansion.statistics.warnings` -- the expanded source would
    still splice and compile, with corrupted PIC/VALUE content. Fail closed."""
    from cobolparser.preprocess import expand_copybooks

    # cobol-parser detects a copybook's encoding from its first 64 KiB, and
    # now decodes non-UTF-8 ASCII-shaped text as cp1252/latin-1 (lossless),
    # so a lone \xff near the top is no longer a lossy decode at all. The
    # loss still happens when the sampled prefix is valid UTF-8 and the bad
    # byte lies past it: the whole file is then decoded as UTF-8 with
    # replacement -- exactly the silent corruption this gate exists for.
    (tmp_path / "BADREC.CPY").write_bytes(
        LOSSY_COPYBOOK_PADDING + b"       01  BAD-FIELD PIC X(5) VALUE 'ab\xffcd'.\n"
    )
    expansion = expand_copybooks(COPY_PROGRAM_SOURCE, copybook_paths=[str(tmp_path)])
    assert expansion.statistics.warnings  # precondition: the loss is warned
    reasons = check_expansion_warnings(expansion)
    assert any(r.code == "EXPANSION_WARNING" for r in reasons)


def test_expansion_warnings_pass_for_clean_expansion(tmp_path):
    from cobolparser.preprocess import expand_copybooks

    (tmp_path / "BADREC.CPY").write_text(
        "       01  BAD-FIELD PIC X(5) VALUE 'abcde'.\n"
    )
    expansion = expand_copybooks(COPY_PROGRAM_SOURCE, copybook_paths=[str(tmp_path)])
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
    result = _isolated_call_result()
    surface = analyze(result.ast)
    reasons = check_test_case(
        surface, result.ast, _case("SAFE-PARAGRAPH", call_names={"DISCRATE"})
    )
    assert reasons == []


def test_per_case_check_refuses_nested_mock_target_matched_program_wide():
    """Whole-program mismatch, same bug class as AMBIGUOUS_MOCK's CLI-level
    regression in test_cli.py: SAFE-PARAGRAPH's own reachable CALL
    "DISCRATE" is a clean top-level site, but the same key also matches the
    unspliceable CALL "DISCRATE" nested inside SIZE-ERROR-PARAGRAPH's ON
    SIZE ERROR clause elsewhere in the program -- a paragraph this case's
    own PERFORM target never reaches. orchestrator.splice_program matches
    directives to sites by category+key alone, with no reachability filter
    (see splice_program's `mocked = any(...)` check), so that nested site
    would still get spliced -- and orchestrator's own defensive "the
    refusal gate should have refused it" check would raise -- if
    check_test_case did not also check sites program-wide."""
    result = _result()
    surface = analyze(result.ast)
    reasons = check_test_case(
        surface, result.ast, _case("SAFE-PARAGRAPH", call_names={"DISCRATE"})
    )
    assert any(r.code == "UNSUPPORTED_NESTED_MOCK_TARGET" for r in reasons)


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


def test_per_case_check_refuses_unmocked_call_nested_in_on_size_error():
    """A CALL nested inside an arithmetic statement's ON SIZE ERROR clause
    must refuse UNMOCKED_CALL exactly like one nested inside an IF -- this
    is the confirmed fix for the 2026-08-10 audit's Finding 1: before
    "on_size_error"/"not_on_size_error" were added to mock_surface.py's
    _NESTED_STATEMENT_ATTRS, this call was invisible to the analysis layer
    entirely and the test case passed silently with an unmocked boundary."""
    result = _result()
    surface = analyze(result.ast)
    reasons = check_test_case(
        surface, result.ast, _case("SIZE-ERROR-PARAGRAPH", call_names=())
    )
    assert any(r.code == "UNMOCKED_CALL" for r in reasons)


def test_per_case_check_refuses_mocking_call_nested_in_on_size_error():
    """Mirrors test_per_case_check_refuses_mock_call_targeting_nested_call_site:
    now that the CALL is visible to the analysis layer at all (this fix),
    mockymock correctly falls back to the same fail-closed treatment as any
    other unsplicable nested clause body (IF/EVALUATE/...) rather than
    silently allowing a splice cobolparser gives no location data for."""
    result = _result()
    surface = analyze(result.ast)
    reasons = check_test_case(
        surface, result.ast, _case("SIZE-ERROR-PARAGRAPH", call_names={"DISCRATE"})
    )
    assert any(r.code == "UNSUPPORTED_NESTED_MOCK_TARGET" for r in reasons)


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
    reasons = check_test_case(surface, result.ast, _case("PARAGRAPH-A", call_names=()))
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
    reasons = check_test_case(surface, result.ast, _case("START-HERE", call_names=()))
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
    reasons = check_test_case(surface, result.ast, _case("START-HERE", call_names=()))
    thru = [r for r in reasons if r.code == "UNSUPPORTED_PERFORM_THRU"]
    assert len(thru) == 1
    assert "backwards" in thru[0].message


def test_per_case_check_refuses_missing_thru_endpoint():
    result = parse_cobol(MISSING_THRU_SOURCE, filename="missthru.cbl")
    assert result.success, result.errors
    surface = analyze(result.ast)
    reasons = check_test_case(surface, result.ast, _case("START-HERE", call_names=()))
    thru = [r for r in reasons if r.code == "UNSUPPORTED_PERFORM_THRU"]
    assert len(thru) == 1
    assert "NO-SUCH-PARA" in thru[0].message


def test_per_case_check_refuses_ambiguous_thru_endpoint():
    result = parse_cobol(DUP_THRU_SOURCE, filename="dupthru.cbl")
    assert result.success, result.errors
    surface = analyze(result.ast)
    reasons = check_test_case(surface, result.ast, _case("START-HERE", call_names=()))
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


# Three sections in source order; the middle one holds an unmocked CALL.
# A .cut `PERFORM ENTRY-SEC THRU CLEANUP-SEC` really executes all three by
# fall-through under GnuCOBOL (the spliced driver emits the literal
# PERFORM ... THRU), so the refusal gate must never model less than that.
SECTION_THRU_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SECTHRU.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-RESULT          PIC X(10).

       PROCEDURE DIVISION.
       ENTRY-SEC SECTION.
       ENTRY-PARA.
           MOVE "START" TO WS-RESULT.

       MIDDLE-SEC SECTION.
       MIDDLE-PARA.
           CALL "AUDITPGM" USING WS-RESULT.

       CLEANUP-SEC SECTION.
       CLEANUP-PARA.
           MOVE "DONE" TO WS-RESULT.
"""


def test_per_case_check_refuses_section_seeded_driver_side_thru():
    """2026-08-12 audit Finding 2: the driver-side THRU seed was guarded by
    `start in by_name` -- built from paragraphs only -- so a test case's
    own PERFORM naming a SECTION as its start silently skipped both the
    range expansion and its fail-closed refusal, dropping `thru` entirely.
    MIDDLE-SEC's unmocked CALL (really executed by the compiled driver's
    fall-through) then produced a clean pass. The gate must refuse loudly
    whenever either driver-side THRU endpoint names a section."""
    result = parse_cobol(SECTION_THRU_SOURCE, filename="secthru.cbl")
    assert result.success, result.errors
    surface = analyze(result.ast)
    case = _case("ENTRY-SEC", call_names=(), perform_thru="CLEANUP-SEC")
    reasons = check_test_case(surface, result.ast, case)
    thru = [r for r in reasons if r.code == "UNSUPPORTED_PERFORM_THRU"]
    assert len(thru) == 1
    assert "SECTION" in thru[0].message


def test_per_case_check_refuses_section_named_driver_side_thru_endpoint():
    """Companion to the seed-side check: a paragraph-named start whose THRU
    endpoint names a SECTION must also refuse with the section-specific
    message, not the misleading 'not found in PROCEDURE DIVISION' one
    (the section exists -- it is just not a paragraph)."""
    result = parse_cobol(SECTION_THRU_SOURCE, filename="secthru.cbl")
    assert result.success, result.errors
    surface = analyze(result.ast)
    case = _case("ENTRY-PARA", call_names=(), perform_thru="CLEANUP-SEC")
    reasons = check_test_case(surface, result.ast, case)
    thru = [r for r in reasons if r.code == "UNSUPPORTED_PERFORM_THRU"]
    assert len(thru) == 1
    assert "SECTION" in thru[0].message


def test_per_case_check_section_target_without_thru_still_allowed():
    """Guard against over-refusing: PERFORMing a section with no THRU is
    long-supported (the BFS expands its members) and must stay allowed --
    the new refusal is scoped to THRU ranges only. MIDDLE-SEC is not
    reached from ENTRY-SEC without the THRU, so no mock is needed."""
    result = parse_cobol(SECTION_THRU_SOURCE, filename="secthru.cbl")
    assert result.success, result.errors
    surface = analyze(result.ast)
    case = _case("ENTRY-SEC", call_names=())
    assert check_test_case(surface, result.ast, case) == []


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
    reasons = check_test_case(surface, result.ast, _case("START-HERE", call_names=()))
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
    # SORTS-THE-FILE's `SORT ... USING ... GIVING ...` is the plain
    # file-to-file form -- no INPUT/OUTPUT PROCEDURE -- so it is mockable
    # (MockCategory.SORT) since the SORT/MERGE USING/GIVING mocking
    # feature landed; an unmocked reachable site refuses UNMOCKED_FILE_OP
    # like any other file-op boundary, not UNSUPPORTED_SORT_MERGE (that
    # code is now reserved for the INPUT/OUTPUT PROCEDURE form -- see
    # test_sort_merge_mocking.py for both).
    result = _file_family_result()
    surface = analyze(result.ast)
    reasons = check_test_case(
        surface, result.ast, _case("SORTS-THE-FILE", call_names=())
    )
    assert any(r.code == "UNMOCKED_FILE_OP" for r in reasons)


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
    reasons = check_test_case(surface, result.ast, _case("PURE-COMPUTE", call_names=()))
    assert reasons == []


# --- GO TO edges (audit 1.1) -------------------------------------------------

# The audit's own repro: MAIN-PARA reaches HIDDEN-PARA only via GO TO. A BFS
# that traverses only PerformStatement edges never sees HIDDEN-PARA and lets
# its CALL stay live (fail-open). GO TO EXIT-PARA is idiomatic COBOL, so
# refusing GO TO outright is not an option -- the edge must be modeled.
GOTO_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. GOTOSAMP.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-AMOUNT          PIC 9(5)V99.

       PROCEDURE DIVISION.
       MAIN-PARA.
           GO TO HIDDEN-PARA.

       HIDDEN-PARA.
           CALL "REALPGM" USING WS-AMOUNT.
"""

# Computed GO TO: every target of GO TO ... DEPENDING ON is a real edge.
DEPENDING_GOTO_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. DEPSAMP.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-X               PIC 9.
       01  WS-AMOUNT          PIC 9(5)V99.

       PROCEDURE DIVISION.
       MAIN-PARA.
           GO TO P-ONE P-TWO P-THREE DEPENDING ON WS-X.

       P-ONE.
           DISPLAY "1".

       P-TWO.
           DISPLAY "2".

       P-THREE.
           CALL "THIRDPGM" USING WS-AMOUNT.
"""

BAD_GOTO_SOURCE = GOTO_SOURCE.replace("GO TO HIDDEN-PARA.", "GO TO NO-SUCH-PARA.")


def test_per_case_check_follows_go_to_edge_to_hidden_call():
    """Audit finding 1.1: `MAIN-PARA. GO TO HIDDEN-PARA.` with a CALL in
    HIDDEN-PARA used to produce zero refusals while the CALL stayed live."""
    result = parse_cobol(GOTO_SOURCE, filename="gotosamp.cbl")
    assert result.success, result.errors
    surface = analyze(result.ast)
    reasons = check_test_case(surface, result.ast, _case("MAIN-PARA", call_names=()))
    assert any(r.code == "UNMOCKED_CALL" for r in reasons)

    mocked = check_test_case(
        surface, result.ast, _case("MAIN-PARA", call_names={"REALPGM"})
    )
    assert mocked == []


def test_per_case_check_follows_every_depending_on_target():
    result = parse_cobol(DEPENDING_GOTO_SOURCE, filename="depsamp.cbl")
    assert result.success, result.errors
    surface = analyze(result.ast)
    reasons = check_test_case(surface, result.ast, _case("MAIN-PARA", call_names=()))
    unmocked = [r for r in reasons if r.code == "UNMOCKED_CALL"]
    assert len(unmocked) == 1
    assert "THIRDPGM" in unmocked[0].message


def test_per_case_check_refuses_unresolvable_go_to_target():
    """Fail closed: a GO TO target the model cannot resolve refuses instead
    of being silently skipped."""
    result = parse_cobol(BAD_GOTO_SOURCE, filename="badgoto.cbl")
    assert result.success, result.errors
    surface = analyze(result.ast)
    reasons = check_test_case(surface, result.ast, _case("MAIN-PARA", call_names=()))
    flow = [r for r in reasons if r.code == "UNRESOLVED_FLOW_TARGET"]
    assert len(flow) == 1
    assert "NO-SUCH-PARA" in flow[0].message
    assert "GO TO" in flow[0].message


# --- PERFORM <section-name> (audit 1.2) -------------------------------------

# PERFORM WORK-SECTION: the section's paragraphs (including the phantom ""
# paragraph cobolparser emits for statements before the first paragraph
# header) must all become reachable. Before the fix the target resolved to
# nothing and was silently dropped mid-BFS.
SECTION_PERFORM_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SECSAMP.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-AMOUNT          PIC 9(5)V99.

       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM WORK-SECTION.
           STOP RUN.

       WORK-SECTION SECTION.
       WORK-PARA.
           CALL "SUBPGM" USING WS-AMOUNT.

       TAIL-SECTION SECTION.
       TAIL-PARA.
           CALL "TAILPGM" USING WS-AMOUNT.
"""

BAD_PERFORM_SOURCE = SECTION_PERFORM_SOURCE.replace(
    "PERFORM WORK-SECTION.", "PERFORM GHOST-SECTION."
)


def test_per_case_check_follows_perform_of_a_section():
    """Audit finding 1.2: PERFORM WORK-SECTION whose section body contains a
    CALL used to produce no refusal and no mock requirement."""
    result = parse_cobol(SECTION_PERFORM_SOURCE, filename="secsamp.cbl")
    assert result.success, result.errors
    surface = analyze(result.ast)
    reasons = check_test_case(surface, result.ast, _case("MAIN-PARA", call_names=()))
    unmocked = [r for r in reasons if r.code == "UNMOCKED_CALL"]
    assert len(unmocked) == 1
    assert "SUBPGM" in unmocked[0].message  # TAIL-SECTION stays unreachable

    mocked = check_test_case(
        surface, result.ast, _case("MAIN-PARA", call_names={"SUBPGM"})
    )
    assert mocked == []


def test_per_case_check_accepts_section_name_as_driver_target():
    """A .cut whose PERFORM target is a SECTION name must not be rejected as
    UNKNOWN_PARAGRAPH -- performing a section is legal COBOL."""
    result = parse_cobol(SECTION_PERFORM_SOURCE, filename="secsamp.cbl")
    assert result.success, result.errors
    surface = analyze(result.ast)
    reasons = check_test_case(
        surface, result.ast, _case("WORK-SECTION", call_names={"SUBPGM"})
    )
    assert reasons == []


def test_per_case_check_refuses_unresolvable_perform_target():
    """Fail closed: before the fix an unresolvable PERFORM target was
    `continue`d mid-BFS with no refusal at all."""
    result = parse_cobol(BAD_PERFORM_SOURCE, filename="badperf.cbl")
    assert result.success, result.errors
    surface = analyze(result.ast)
    reasons = check_test_case(surface, result.ast, _case("MAIN-PARA", call_names=()))
    flow = [r for r in reasons if r.code == "UNRESOLVED_FLOW_TARGET"]
    assert len(flow) == 1
    assert "GHOST-SECTION" in flow[0].message
    assert "PERFORM" in flow[0].message


# --- SEARCH ... WHEN bodies (audit 1.3) --------------------------------------

SEARCH_WHEN_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SRCHSAMP.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-TAB.
           05  WS-ENT OCCURS 3 TIMES INDEXED BY WS-IDX PIC X.
       01  WS-AMOUNT          PIC 9(5)V99.

       PROCEDURE DIVISION.
       MAIN-PARA.
           SEARCH WS-ENT
               AT END DISPLAY "NONE"
               WHEN WS-ENT (WS-IDX) = "A"
                   CALL "HIDDENPGM" USING WS-AMOUNT
           END-SEARCH.
           STOP RUN.
"""


def test_per_case_check_sees_call_inside_search_when_body():
    """Audit finding 1.3: a CALL inside SEARCH ... WHEN used to be invisible
    (`boundary_sites == []`) -- no site, no refusal, no splice."""
    result = parse_cobol(SEARCH_WHEN_SOURCE, filename="srchsamp.cbl")
    assert result.success, result.errors
    surface = analyze(result.ast)
    reasons = check_test_case(surface, result.ast, _case("MAIN-PARA", call_names=()))
    unmocked = [r for r in reasons if r.code == "UNMOCKED_CALL"]
    assert len(unmocked) == 1
    assert "HIDDENPGM" in unmocked[0].message


# --- DECLARATIVES and ALTER (audit 1.4, 1.5) ---------------------------------

DECLARATIVES_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. DECLSAMP.

       PROCEDURE DIVISION.
       DECLARATIVES.
       ERR-SEC SECTION.
           USE AFTER ERROR PROCEDURE ON INPUT.
       ERR-PARA.
           CALL "ERRPGM".
       END DECLARATIVES.

       MAIN-SEC SECTION.
       MAIN-PARA.
           DISPLAY "HI".
           STOP RUN.
"""

ALTER_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ALTSAMP.

       PROCEDURE DIVISION.
       MAIN-PARA.
           ALTER SWITCH-PARA TO PROCEED TO P-TWO.
           GO TO SWITCH-PARA.

       SWITCH-PARA.
           GO TO P-ONE.

       P-ONE.
           DISPLAY "1".

       P-TWO.
           DISPLAY "2".
"""


def test_whole_program_check_refuses_declaratives():
    """Audit finding 1.4: DECLARATIVES parse warning-free, but their USE
    procedures run on I/O conditions outside any PERFORM/GO TO edge, so the
    reachability gate structurally cannot check them -- unconditional
    whole-program refusal, like SORT/MERGE."""
    result = parse_cobol(DECLARATIVES_SOURCE, filename="declsamp.cbl")
    assert result.success, result.errors
    assert not result.warnings  # precondition: nothing else would catch it
    reasons = check_whole_program(result)
    assert any(r.code == "UNSUPPORTED_DECLARATIVES" for r in reasons)


def test_whole_program_check_refuses_declaratives_via_use_statement_fallback():
    """GH issue Landparty/mocky-mock#106: the primary DECLARATIVES signal
    (a stray paragraph literally named DECLARATIVES -- see
    _check_unsupported_control_flow's docstring) is a coincidental
    cobolparser parsing artifact, not a modeled flag. If that artifact is
    ever lost -- resynchronization after unrelated dropped content
    elsewhere in the program, or a future parser change -- the refusal
    must not silently disappear with it: a USE statement is legal nowhere
    outside a DECLARATIVES section, so its mere presence is an independent,
    structural signal that the same refusal fires on. Simulates the loss
    directly (renaming the AST paragraph) since the pinned cobolparser
    reliably leaves the artifact behind for every DECLARATIVES shape tried
    -- the whole point is that mockymock must not depend on that holding
    forever."""
    result = parse_cobol(DECLARATIVES_SOURCE, filename="declsamp.cbl")
    assert result.success, result.errors
    procedure = result.ast.get_division("PROCEDURE")
    # Remove every primary signal: the modelled ``declarative`` section flag
    # (cobol-parser 2026-09-15+) and, on an older parser, the stray
    # DECLARATIVES paragraph artifact. Only the USE statement remains.
    removed = False
    for section in procedure._sections.values():
        if section.get_metadata("declarative"):
            section.set_metadata("declarative", False)
            removed = True
    for paragraph in _all_paragraphs(procedure):
        if paragraph.paragraph_name.upper() == "DECLARATIVES":
            paragraph.paragraph_name = "NOT-DECLARATIVES-ANYMORE"
            removed = True
    assert removed  # precondition: a primary signal was there to remove
    reasons = check_whole_program(result)
    declaratives = [r for r in reasons if r.code == "UNSUPPORTED_DECLARATIVES"]
    assert len(declaratives) == 1
    assert "USE statement" in declaratives[0].message


def test_whole_program_check_refuses_alter():
    """Audit finding 1.5: ALTER rewrites GO TO targets at runtime, so no
    static reachability analysis is sound -- unconditional refusal."""
    result = parse_cobol(ALTER_SOURCE, filename="altsamp.cbl")
    assert result.success, result.errors
    assert not result.warnings  # precondition: ALTER parses warning-free
    reasons = check_whole_program(result)
    alter = [r for r in reasons if r.code == "UNSUPPORTED_ALTER"]
    assert len(alter) == 1
    assert "SWITCH-PARA" in alter[0].message or "MAIN-PARA" in alter[0].message


def test_whole_program_check_does_not_flag_clean_programs_for_control_flow():
    assert check_whole_program(_result()) == []


# --- phantom arithmetic-terminator paragraphs (2026-08-10 audit Finding 2) ---

PHANTOM_PARAGRAPH_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PHANTOMSAMP.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-X               PIC 9(4) VALUE 1.
       01  WS-RESULT          PIC X(10) VALUE "UNSET".

       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE "START" TO WS-RESULT.
           ADD 1 TO WS-X
           END-ADD.
           MOVE "DONE" TO WS-RESULT.
"""

# Negative control: a paragraph legitimately named after job-completion
# convention, not one of the five reserved arithmetic scope terminators --
# a guard matching the broad `^END-[A-Z]+\\.$` pattern instead of the exact
# five names would wrongly refuse this valid program.
LEGITIMATE_END_PARAGRAPH_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ENDRUNSAMP.

       PROCEDURE DIVISION.
       MAIN-PARA.
           DISPLAY "WORKING".
           PERFORM END-OF-JOB.

       END-OF-JOB.
           DISPLAY "DONE".
           STOP RUN.
"""


def _assert_phantom_terminator_handled(result, terminator: str) -> None:
    """The guard's contract is version-dependent on purpose. cobol-parser
    releases before its 2026-09-02 statement-coverage work parse a
    standalone `END-ADD.` (and the four siblings) as a PARAGRAPH named
    END-ADD, silently reparenting everything after it -- the refusal gate
    must catch that. Releases at or after that work consume the terminator
    as the arithmetic statement's own scope terminator, so no phantom
    paragraph exists and the guard must stay dormant (refusing a correctly
    parsed program would be an over-refusal). Either outcome is asserted
    exactly; the one thing that must never happen is a phantom paragraph
    the gate lets through."""
    assert result.success, result.errors
    assert not result.warnings  # precondition: nothing else would catch it
    paragraph_names = {
        p.paragraph_name for p in result.ast.procedure_division.paragraphs
    }
    reasons = check_whole_program(result)
    phantom = [r for r in reasons if r.code == "UNSUPPORTED_PHANTOM_PARAGRAPH"]
    if terminator in paragraph_names:
        # older cobol-parser: the upstream bug reproduces, the guard fires
        assert len(phantom) == 1
        assert terminator in phantom[0].message
    else:
        # fixed cobol-parser: the terminator was consumed, every statement
        # stayed in MAIN-PARA, and the guard has nothing to refuse
        assert paragraph_names == {"MAIN-PARA"}
        assert phantom == []


def test_whole_program_check_refuses_phantom_arithmetic_terminator_paragraph():
    """2026-08-10 audit Finding 2: cobolparser parsed a standalone
    `END-ADD.` (and the SUBTRACT/MULTIPLY/DIVIDE/COMPUTE siblings) as a
    paragraph name rather than consuming it as ADD's scope terminator,
    silently reparenting every following statement -- warning-free, so
    nothing else catches it. Fail closed like DECLARATIVES/ALTER. Fixed
    upstream in cobol-parser's 2026-09-02 statement-coverage work; see
    `_assert_phantom_terminator_handled` for the two accepted outcomes."""
    result = parse_cobol(PHANTOM_PARAGRAPH_SOURCE, filename="phantomsamp.cbl")
    _assert_phantom_terminator_handled(result, "END-ADD")


# A paragraph really named END-ADD -- not an ADD's terminator at all, since
# no ADD precedes it -- parses as a paragraph on every cobol-parser
# release, so the guard itself stays under direct coverage even once the
# upstream terminator fix means the fixtures above no longer trip it.
REAL_PHANTOM_NAMED_PARAGRAPH_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PHANTOMNAME.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-RESULT           PIC X(5).

       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE "START" TO WS-RESULT.
       END-ADD.
           MOVE "DONE" TO WS-RESULT.
"""


def test_whole_program_check_refuses_paragraph_literally_named_after_terminator():
    result = parse_cobol(REAL_PHANTOM_NAMED_PARAGRAPH_SOURCE, filename="phn.cbl")
    assert result.success, result.errors
    paragraph_names = {
        p.paragraph_name for p in result.ast.procedure_division.paragraphs
    }
    assert "END-ADD" in paragraph_names  # precondition: the guard's trigger
    reasons = check_whole_program(result)
    phantom = [r for r in reasons if r.code == "UNSUPPORTED_PHANTOM_PARAGRAPH"]
    assert len(phantom) == 1
    assert "END-ADD" in phantom[0].message


# The other four reserved terminators, each with its own minimal fixture
# (SUBTRACT/MULTIPLY/DIVIDE/COMPUTE have different parser classes than ADD
# in cobolparser -- code-review follow-up on the 2026-08-10 audit fix, not
# safe to assume from ADD's shape alone).
_OTHER_PHANTOM_TERMINATOR_STATEMENTS = {
    "SUBTRACT": ("SUBTRACT 1 FROM WS-X", "END-SUBTRACT"),
    "MULTIPLY": ("MULTIPLY WS-X BY 2", "END-MULTIPLY"),
    "DIVIDE": ("DIVIDE WS-X BY WS-Y GIVING WS-X", "END-DIVIDE"),
    "COMPUTE": ("COMPUTE WS-X = WS-Y + 1", "END-COMPUTE"),
}


@pytest.mark.parametrize(
    "verb, statement_and_terminator",
    _OTHER_PHANTOM_TERMINATOR_STATEMENTS.items(),
)
def test_whole_program_check_refuses_every_phantom_arithmetic_terminator(
    verb, statement_and_terminator
):
    statement, terminator = statement_and_terminator
    source = (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. PHANTOMALL.\n"
        "\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01  WS-X               PIC 9(4) VALUE 1.\n"
        "       01  WS-Y               PIC 9(4) VALUE 2.\n"
        "\n"
        "       PROCEDURE DIVISION.\n"
        "       MAIN-PARA.\n"
        f"           {statement}\n"
        f"           {terminator}.\n"
    )
    result = parse_cobol(source, filename="phantomall.cbl")
    _assert_phantom_terminator_handled(result, terminator)


def test_whole_program_check_allows_legitimate_end_prefixed_paragraph():
    """Regression guard against over-refusing: a paragraph name that merely
    starts with END- (END-OF-JOB) but isn't one of the five reserved
    arithmetic terminators must not be flagged."""
    result = parse_cobol(LEGITIMATE_END_PARAGRAPH_SOURCE, filename="endrunsamp.cbl")
    assert result.success, result.errors
    assert not result.warnings
    reasons = check_whole_program(result)
    assert not any(r.code == "UNSUPPORTED_PHANTOM_PARAGRAPH" for r in reasons)


# --- REDEFINES data items -----------------------------------------------------

# Two REDEFINES of the same nested (level 05) item, back-to-back: one
# elementary with an explicit PICTURE, one a PICTURE-less group (its shape
# comes from its own children). Column widths are kept well inside the
# fixed-format code area (columns 8-72) -- REDEFINES itself parses cleanly;
# see cobol-parser's test_data_division_branches.py for the AST-level checks.
REDEFINES_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. REDEFSAMP.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-RECORD.
           05  VARIABLE           PIC X(08).
           05  VARIABLE-NAME REDEFINES VARIABLE PIC 9(08).
           05  BARIABLE REDEFINES VARIABLE.
               10  BARIABLE-B1  PIC X(04).
               10  BARIABLE-B2  PIC X(04).

       PROCEDURE DIVISION.
       MAIN-PARA.
           STOP RUN.
"""


def test_redefines_data_items_parse_clean_with_no_warnings():
    """Precondition for the no-refusal check below: a program declaring both
    REDEFINES shapes must parse warning-free, or PARSE_WARNING would refuse
    it regardless of what this test is actually checking."""
    result = parse_cobol(REDEFINES_SOURCE, filename="redefsamp.cbl")
    assert result.success, result.errors
    assert result.warnings == []


def test_whole_program_check_does_not_flag_redefines_data_items():
    result = parse_cobol(REDEFINES_SOURCE, filename="redefsamp.cbl")
    assert check_whole_program(result) == []


# --- CANCEL coverage (audit 1.6) ----------------------------------------------

CANCEL_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CANSAMP.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-AMOUNT          PIC 9(5)V99.

       PROCEDURE DIVISION.
       MAIN-PARA.
           CALL "SUBPGM" USING WS-AMOUNT.
           CANCEL "SUBPGM".

       CANCEL-ONLY-PARA.
           CANCEL "SUBPGM".
"""


def test_reachable_cancel_is_covered_by_matching_call_mock():
    """CANCEL of a program whose CALLs the case mocks is a guaranteed
    GnuCOBOL no-op (the mocked CALL never loads the module), so it counts
    as covered -- left in place, never spliced."""
    result = parse_cobol(CANCEL_SOURCE, filename="cansamp.cbl")
    assert result.success, result.errors
    surface = analyze(result.ast)
    reasons = check_test_case(
        surface, result.ast, _case("MAIN-PARA", call_names={"SUBPGM"})
    )
    assert reasons == []


def test_reachable_cancel_without_call_mock_refuses():
    result = parse_cobol(CANCEL_SOURCE, filename="cansamp.cbl")
    assert result.success, result.errors
    surface = analyze(result.ast)
    reasons = check_test_case(surface, result.ast, _case("MAIN-PARA", call_names=()))
    codes = [r.code for r in reasons]
    assert "UNMOCKED_CALL" in codes  # the CALL itself still refuses
    assert "UNMOCKED_CANCEL" in codes


def test_call_mock_covering_only_a_cancel_is_not_unmatched():
    """A MOCK CALL "SUBPGM" whose only reachable use is covering a CANCEL
    must not be flagged UNMATCHED_MOCK -- covering the CANCEL is its job."""
    result = parse_cobol(CANCEL_SOURCE, filename="cansamp.cbl")
    assert result.success, result.errors
    surface = analyze(result.ast)
    reasons = check_test_case(
        surface, result.ast, _case("CANCEL-ONLY-PARA", call_names={"SUBPGM"})
    )
    assert reasons == []


# --- top-level "owns its line" guard (audit 2.1) ------------------------------

from cobolparser.preprocess import normalize_fixed_format as _normalize

from mockymock.splicer.source_map import (
    annotate_nested_sites as _annotate,
)
from mockymock.splicer.source_map import (
    collect_scope_map as _scope_map,
)

SHARED_LINE_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SHARESAMP.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A               PIC 9(3).

       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 1 TO WS-A CALL "SHAREPGM" USING WS-A.

       ONE-LINER-PARA. CALL "LINERPGM" USING WS-A.

       CLEAN-PARA.
           CALL "CLEANPGM" USING WS-A.
"""


def _annotated_shared_surface():
    result = parse_cobol(SHARED_LINE_SOURCE, filename="sharesamp.cbl")
    assert result.success, result.errors
    surface = analyze(result.ast)
    lines = _normalize(SHARED_LINE_SOURCE.splitlines()).splitlines()
    _annotate(surface, _scope_map(result.ast, lines), lines)
    return result, surface


def test_mocked_top_level_call_sharing_its_line_refuses():
    """Audit finding 2.1: `MOVE 1 TO WS-A CALL "X" USING WS-A.` on one line
    used to be spliced whole-line, silently deleting the MOVE."""
    result, surface = _annotated_shared_surface()
    reasons = check_test_case(
        surface, result.ast, _case("MAIN-PARA", call_names={"SHAREPGM"})
    )
    layout = [r for r in reasons if r.code == "UNSUPPORTED_MOCK_TARGET_LAYOUT"]
    assert len(layout) == 1
    assert "does not start its own line" in layout[0].message


def test_mocked_call_in_one_line_paragraph_refuses():
    """`P1. CALL "X".` -- splicing would comment out the paragraph header."""
    result, surface = _annotated_shared_surface()
    reasons = check_test_case(
        surface, result.ast, _case("ONE-LINER-PARA", call_names={"LINERPGM"})
    )
    assert any(r.code == "UNSUPPORTED_MOCK_TARGET_LAYOUT" for r in reasons)


def test_mocked_top_level_call_owning_its_line_still_passes():
    result, surface = _annotated_shared_surface()
    reasons = check_test_case(
        surface, result.ast, _case("CLEAN-PARA", call_names={"CLEANPGM"})
    )
    assert reasons == []


def test_unmocked_top_level_exec_sharing_its_line_refuses_program_wide():
    """An unmocked EXEC gets a trap splice regardless of reachability, so a
    layout problem on a top-level EXEC refuses the whole program."""
    source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. EXECSHARE.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-ID              PIC 9(5).

       PROCEDURE DIVISION.
       SQL-PARA. EXEC SQL DELETE FROM T WHERE ID = :WS-ID END-EXEC.

       OTHER-PARA.
           DISPLAY "HI".
"""
    result = parse_cobol(source, filename="execshare.cbl")
    assert result.success, result.errors
    surface = analyze(result.ast)
    lines = _normalize(source.splitlines()).splitlines()
    _annotate(surface, _scope_map(result.ast, lines), lines)
    reasons = check_nested_exec(surface)
    unspliceable = [r for r in reasons if r.code == "UNSPLICEABLE_EXEC"]
    assert len(unspliceable) == 1
    assert "does not start its own line" in unspliceable[0].message
