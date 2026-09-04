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

       CALL-INSIDE-ON-SIZE-ERROR.
           ADD 1 TO WS-AMOUNT
               ON SIZE ERROR
                   CALL "NESTED-DISCRATE" USING WS-AMOUNT WS-RATE.

       CALL-INSIDE-NOT-ON-SIZE-ERROR.
           ADD 1 TO WS-AMOUNT
               NOT ON SIZE ERROR
                   CALL "NESTED-DISCRATE" USING WS-AMOUNT WS-RATE.
"""


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
       01  WS-TODAY           PIC 9(6).

       PROCEDURE DIVISION.
       START-THE-FILE.
           START ORDER-FILE KEY IS EQUAL TO ORDER-KEY.

       UNLOCK-THE-FILE.
           UNLOCK ORDER-FILE.

       SORT-THE-FILE.
           SORT SORT-FILE ON ASCENDING KEY WS-KEY
               USING IN-FILE GIVING OUT-FILE.

       ACCEPT-FROM-CONSOLE.
           ACCEPT WS-NAME.

       ACCEPT-FROM-SYSTEM.
           ACCEPT WS-TODAY FROM DATE.

       PURE-COMPUTE.
           MOVE WS-KEY TO WS-NAME.
"""


def _ast():
    result = parse_cobol(SOURCE, filename="sample.cbl")
    assert result.success, result.errors
    return result.ast


def _file_family_ast():
    result = parse_cobol(FILE_FAMILY_SOURCE, filename="filefam.cbl")
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


def test_detects_start_as_file_io():
    surface = analyze(_file_family_ast())
    assert "START-THE-FILE" in surface.file_io_paragraphs


def test_detects_unlock_as_file_io():
    surface = analyze(_file_family_ast())
    assert "UNLOCK-THE-FILE" in surface.file_io_paragraphs


def test_detects_sort_as_file_io():
    surface = analyze(_file_family_ast())
    assert "SORT-THE-FILE" in surface.file_io_paragraphs


def test_detects_console_accept():
    surface = analyze(_file_family_ast())
    assert "ACCEPT-FROM-CONSOLE" in surface.console_accept_paragraphs


def test_accept_from_system_source_is_not_console_input():
    surface = analyze(_file_family_ast())
    assert "ACCEPT-FROM-SYSTEM" not in surface.console_accept_paragraphs


def test_accept_from_system_source_is_recorded_as_unmockable_not_as_a_site():
    """`ACCEPT ... FROM DATE` stays out of `boundary_sites` (nothing to
    mock) but is recorded on its own list, so a MOCK ACCEPT aimed at it can
    be refused with the real reason instead of a generic "not reachable".
    """
    surface = analyze(_file_family_ast())
    assert not [
        s for s in surface.boundary_sites if s.paragraph_name == "ACCEPT-FROM-SYSTEM"
    ]
    recorded = surface.non_interactive_accepts
    assert [(a.target, a.from_source) for a in recorded] == [("WS-TODAY", "DATE")]
    assert recorded[0].paragraph_name == "ACCEPT-FROM-SYSTEM"
    assert recorded[0].line > 0


def test_console_accept_is_not_recorded_as_unmockable():
    surface = analyze(_file_family_ast())
    assert all(a.target != "WS-NAME" for a in surface.non_interactive_accepts)


def test_pure_compute_paragraph_is_not_flagged_by_file_family():
    surface = analyze(_file_family_ast())
    assert "PURE-COMPUTE" not in surface.file_io_paragraphs
    assert "PURE-COMPUTE" not in surface.console_accept_paragraphs


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


def test_detects_static_call_nested_inside_on_size_error():
    surface = analyze(_nested_ast())
    static = [
        c
        for c in surface.static_call_sites()
        if c.paragraph_name == "CALL-INSIDE-ON-SIZE-ERROR"
    ]
    assert len(static) == 1
    assert static[0].program_name == "NESTED-DISCRATE"
    assert static[0].nested is True


def test_detects_static_call_nested_inside_not_on_size_error():
    surface = analyze(_nested_ast())
    static = [
        c
        for c in surface.static_call_sites()
        if c.paragraph_name == "CALL-INSIDE-NOT-ON-SIZE-ERROR"
    ]
    assert len(static) == 1
    assert static[0].program_name == "NESTED-DISCRATE"
    assert static[0].nested is True


# cobolparser's on_size_error/not_on_size_error attribute name is not
# guaranteed uniform across statement types by anything mockymock controls
# -- ADD's parser class is not SUBTRACT's or COMPUTE's. Verify each of the
# five arithmetic verbs individually rather than trusting ADD's shape
# generalizes (code-review follow-up on the 2026-08-10 audit fix).
_ARITHMETIC_SIZE_ERROR_STATEMENTS = {
    "ADD": "ADD 1 TO WS-AMOUNT",
    "SUBTRACT": "SUBTRACT 1 FROM WS-AMOUNT",
    "MULTIPLY": "MULTIPLY WS-AMOUNT BY 2",
    "DIVIDE": "DIVIDE WS-AMOUNT BY WS-RATE GIVING WS-AMOUNT",
    "COMPUTE": "COMPUTE WS-AMOUNT = WS-RATE + 1",
}


@pytest.mark.parametrize("verb, statement", _ARITHMETIC_SIZE_ERROR_STATEMENTS.items())
@pytest.mark.parametrize("clause", ["ON SIZE ERROR", "NOT ON SIZE ERROR"])
def test_detects_call_nested_inside_every_arithmetic_size_error_clause(
    verb, statement, clause
):
    source = (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. SIZEALL.\n"
        "\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01  WS-AMOUNT          PIC 9(5)V99.\n"
        "       01  WS-RATE            PIC 9V99.\n"
        "\n"
        "       PROCEDURE DIVISION.\n"
        "       MAIN-PARA.\n"
        f"           {statement}\n"
        f"               {clause}\n"
        '                   CALL "NESTED-DISCRATE" USING WS-AMOUNT WS-RATE.\n'
    )
    result = parse_cobol(source, filename="sizeall.cbl")
    assert result.success, result.errors
    surface = analyze(result.ast)
    static = surface.static_call_sites()
    assert len(static) == 1, f"{verb} {clause}: expected exactly one CALL site"
    assert static[0].program_name == "NESTED-DISCRATE"
    assert static[0].nested is True


def test_detects_call_nested_inside_read_at_end():
    # cobolparser >= 1.2.0 populates IO clause bodies (at_end_clause etc.);
    # this was a strict xfail while collect_clause_stmts() was a stub that
    # discarded them.
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
    # The CALL lives inside a boundary statement's clause body, so it must
    # be flagged unspliceable-by-ancestry for the refusal gate.
    site = next(
        s
        for s in surface.boundary_sites
        if s.keys == ("NESTED-DISCRATE",)
        and s.paragraph_name == "CALL-INSIDE-READ-AT-END"
    )
    assert site.nested is True
    assert site.nested_in_boundary is True


WRITE_EOP_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. EOPSURF.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT RPT-FILE ASSIGN TO "RPT".

       DATA DIVISION.
       FILE SECTION.
       FD  RPT-FILE
           LINAGE IS 60 LINES.
       01  RPT-REC            PIC X(80).

       WORKING-STORAGE SECTION.
       01  WS-AMOUNT          PIC 9(5)V99.
       01  WS-RATE            PIC 9V99.

       PROCEDURE DIVISION.
       CALL-INSIDE-AT-EOP.
           WRITE RPT-REC
               AT END-OF-PAGE
                   CALL "NESTED-DISCRATE" USING WS-AMOUNT WS-RATE.

       CALL-INSIDE-NOT-AT-EOP.
           WRITE RPT-REC
               NOT AT END-OF-PAGE
                   CALL "NESTED-DISCRATE" USING WS-AMOUNT WS-RATE.
"""


@pytest.mark.parametrize("paragraph", ["CALL-INSIDE-AT-EOP", "CALL-INSIDE-NOT-AT-EOP"])
def test_detects_call_nested_inside_write_eop_clauses(paragraph):
    """2026-08-12 audit Finding 3: not_at_eop_clause was missing from
    _NESTED_STATEMENT_ATTRS (at_eop_clause was present), so a boundary
    statement inside WRITE ... NOT AT END-OF-PAGE was invisible to the
    whole analysis layer -- same bug class as the 2026-08-10 audit's
    on_size_error fix. Both halves verified here."""
    result = parse_cobol(WRITE_EOP_SOURCE, filename="eopsurf.cbl")
    assert result.success, result.errors
    surface = analyze(result.ast)
    static = [c for c in surface.static_call_sites() if c.paragraph_name == paragraph]
    assert len(static) == 1, f"{paragraph}: expected exactly one CALL site"
    assert static[0].program_name == "NESTED-DISCRATE"
    assert static[0].nested is True


STRING_OVERFLOW_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. STROVFL.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A               PIC X(5) VALUE "AAA".
       01  WS-B               PIC X(5) VALUE "BBB".
       01  WS-OUT             PIC X(6).
       01  WS-AMOUNT          PIC 9(5)V99.
       01  WS-RATE            PIC 9V99.

       PROCEDURE DIVISION.
       CALL-INSIDE-STRING-OVERFLOW.
           STRING WS-A DELIMITED BY SPACE
                  WS-B DELIMITED BY SPACE
               INTO WS-OUT
               ON OVERFLOW
                   CALL "NESTED-DISCRATE" USING WS-AMOUNT WS-RATE
           END-STRING.

       CALL-INSIDE-STRING-NOT-OVERFLOW.
           STRING WS-A DELIMITED BY SPACE
                  WS-B DELIMITED BY SPACE
               INTO WS-OUT
               NOT ON OVERFLOW
                   CALL "NESTED-DISCRATE" USING WS-AMOUNT WS-RATE
           END-STRING.

       CALL-INSIDE-UNSTRING-OVERFLOW.
           UNSTRING WS-OUT DELIMITED BY SPACE
               INTO WS-A WS-B
               ON OVERFLOW
                   CALL "NESTED-DISCRATE" USING WS-AMOUNT WS-RATE
           END-UNSTRING.

       CALL-INSIDE-UNSTRING-NOT-OVERFLOW.
           UNSTRING WS-OUT DELIMITED BY SPACE
               INTO WS-A WS-B
               NOT ON OVERFLOW
                   CALL "NESTED-DISCRATE" USING WS-AMOUNT WS-RATE
           END-UNSTRING.
"""


@pytest.mark.parametrize(
    "paragraph",
    [
        "CALL-INSIDE-STRING-OVERFLOW",
        "CALL-INSIDE-STRING-NOT-OVERFLOW",
        "CALL-INSIDE-UNSTRING-OVERFLOW",
        "CALL-INSIDE-UNSTRING-NOT-OVERFLOW",
    ],
)
def test_detects_call_nested_inside_string_unstring_overflow_clauses(paragraph):
    """2026-08-12 audit Finding 3: not_on_overflow was missing from
    _NESTED_STATEMENT_ATTRS. StringStatement/UnstringStatement expose their
    ON OVERFLOW body under the same `on_overflow` name CallStatement uses
    (already in the tuple, verified by the positive halves here), but their
    NOT ON OVERFLOW body under `not_on_overflow`, which had no entry."""
    result = parse_cobol(STRING_OVERFLOW_SOURCE, filename="strovfl.cbl")
    assert result.success, result.errors
    surface = analyze(result.ast)
    static = [c for c in surface.static_call_sites() if c.paragraph_name == paragraph]
    assert len(static) == 1, f"{paragraph}: expected exactly one CALL site"
    assert static[0].program_name == "NESTED-DISCRATE"
    assert static[0].nested is True


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


# --- SEARCH ... WHEN bodies (audit 1.3) and CANCEL (audit 1.6) ---------------

SEARCH_WHEN_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SRCHSURF.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-TAB.
           05  WS-ENT OCCURS 3 TIMES INDEXED BY WS-IDX PIC X.
       01  WS-AMT             PIC 9(5).

       PROCEDURE DIVISION.
       SEARCH-PARA.
           SEARCH WS-ENT
               AT END DISPLAY "NONE"
               WHEN WS-ENT (WS-IDX) = "A"
                   CALL "WHENPGM" USING WS-AMT
           END-SEARCH.
           STOP RUN.
"""


def test_detects_static_call_nested_inside_search_when():
    """Audit finding 1.3: _nested_statement_lists never opened
    SearchStatement.when_clauses (a list[dict] with a "statements" key,
    unlike EVALUATE's WhenClause nodes), so a CALL inside SEARCH ... WHEN
    produced no boundary site at all -- no site, no refusal, no splice."""
    result = parse_cobol(SEARCH_WHEN_SOURCE, filename="srchsurf.cbl")
    assert result.success, result.errors
    surface = analyze(result.ast)
    sites = [s for s in surface.boundary_sites if "WHENPGM" in s.keys]
    assert len(sites) == 1
    assert sites[0].nested is True
    assert sites[0].paragraph_name == "SEARCH-PARA"


CANCEL_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CANSURF.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-AMT             PIC 9(5).

       PROCEDURE DIVISION.
       CANCEL-PARA.
           CANCEL "SUBPGM".
"""


def test_detects_cancel_as_unmockable_site_with_program_names():
    """CANCEL is detected (category None -- never spliced, never matched by
    a directive) with its program names as keys, so the refusal gate can
    decide covered-by-CALL-mock vs UNMOCKED_CANCEL."""
    result = parse_cobol(CANCEL_SOURCE, filename="cansurf.cbl")
    assert result.success, result.errors
    surface = analyze(result.ast)
    sites = [s for s in surface.boundary_sites if s.label == "CANCEL"]
    assert len(sites) == 1
    assert sites[0].category is None
    assert sites[0].keys == ("SUBPGM",)


from mockymock.analysis.mock_surface import _TERMINATOR_LABELS
from mockymock.analysis.refusal import check_test_case
from mockymock.dsl.model import MockTestCase

TERMINATOR_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TERMSAMP.

       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM SUB-PARA
           STOP RUN.

       SUB-PARA.
           GOBACK.

       MESSAGE-PARA.
           STOP "OPERATOR MESSAGE".
"""


def _terminator_surface():
    result = parse_cobol(TERMINATOR_SOURCE, filename="termsamp.cbl")
    assert result.success, result.errors
    return analyze(result.ast)


def test_stop_run_is_detected_as_unmockable_terminator_site():
    surface = _terminator_surface()
    sites = [s for s in surface.boundary_sites if s.label == "STOP RUN"]
    assert len(sites) == 1
    assert sites[0].category is None
    assert sites[0].paragraph_name == "MAIN-PARA"


def test_goback_is_detected_as_unmockable_terminator_site():
    surface = _terminator_surface()
    sites = [s for s in surface.boundary_sites if s.label == "GOBACK"]
    assert len(sites) == 1
    assert sites[0].category is None
    assert sites[0].paragraph_name == "SUB-PARA"


def test_stop_literal_is_not_a_terminator_site():
    """STOP "message" (stop_type == "literal") displays and continues --
    it is not STOP RUN and must not be classified as a terminator."""
    surface = _terminator_surface()
    assert not any(
        s.paragraph_name == "MESSAGE-PARA" and s.label in ("STOP RUN", "GOBACK")
        for s in surface.boundary_sites
    )


def test_terminator_labels_constant_matches_classified_labels():
    assert _TERMINATOR_LABELS == frozenset({"STOP RUN", "GOBACK"})


def test_reachable_terminator_is_not_misreported_as_sort_merge():
    """check_test_case's category=None catch-all must not fire on the new
    STOP RUN/GOBACK labels -- they are handled separately by
    check_terminator_layout (Task 3), not here."""
    result = parse_cobol(TERMINATOR_SOURCE, filename="termsamp.cbl")
    surface = analyze(result.ast)
    case = MockTestCase(name="c", perform_target="MAIN-PARA")
    reasons = check_test_case(surface, result.ast, case)
    assert not any(r.code == "UNSUPPORTED_SORT_MERGE" for r in reasons)
