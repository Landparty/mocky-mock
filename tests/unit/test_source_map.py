from cobolparser import parse_cobol
from cobolparser.models.statements.call import CallStatement
from cobolparser.preprocess import normalize_fixed_format

from mockymock.splicer.source_map import collect_boundaries, statement_span

SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SAMPLE.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-AMOUNT          PIC 9(5)V99.
       01  WS-RATE            PIC 9V99.

       PROCEDURE DIVISION.
       FIRST-PARAGRAPH.
           CALL "DISCRATE"
               USING WS-AMOUNT
                     WS-RATE.

       SECOND-PARAGRAPH.
           DISPLAY "DONE".
"""


def _ast_and_lines():
    """Parse SOURCE and return (ast, normalized_lines).

    cobolparser's parse_cobol() runs fixed-format source through
    normalize_fixed_format() before lexing, and that step drops blank
    (and comment) lines entirely rather than preserving them as empty
    lines. AST SourceLocation.line values are therefore line numbers in
    the *normalized* text, not the raw SOURCE string above — so the
    comparison text here must be normalized the same way, or the line
    numbers won't line up.
    """
    result = parse_cobol(SOURCE, filename="sample.cbl")
    assert result.success, result.errors
    normalized = normalize_fixed_format(SOURCE.splitlines())
    return result.ast, normalized.splitlines()


def _find_call_statement(ast):
    procedure = ast.get_division("PROCEDURE")
    for paragraph in procedure.paragraphs:
        for statement in paragraph.statements:
            if isinstance(statement, CallStatement):
                return statement
    raise AssertionError("no CALL statement found")


def test_multiline_call_span_covers_all_three_lines():
    ast, lines = _ast_and_lines()
    call_stmt = _find_call_statement(ast)
    boundaries = collect_boundaries(ast)

    start, end = statement_span(
        call_stmt, boundaries, last_line=len(lines), lines=lines
    )

    assert start == call_stmt.location.line
    assert end == start + 2
    assert "CALL" in lines[start - 1]
    assert "WS-RATE" in lines[end - 1]


def test_span_ends_before_next_paragraph_header():
    ast, lines = _ast_and_lines()
    call_stmt = _find_call_statement(ast)
    boundaries = collect_boundaries(ast)

    _, end = statement_span(call_stmt, boundaries, last_line=len(lines), lines=lines)

    second_paragraph_line = next(
        i + 1 for i, line in enumerate(lines) if "SECOND-PARAGRAPH" in line
    )
    assert end < second_paragraph_line


# --- nested-site scope map + span annotation -------------------------------

from mockymock.analysis.mock_surface import analyze
from mockymock.dsl.model import MockCategory
from mockymock.splicer.source_map import annotate_nested_sites, collect_scope_map

NESTED_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. NESTSPAN.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-FLAG            PIC X.
       01  WS-AMT             PIC 9(5).

       PROCEDURE DIVISION.
       MAIN-PARA.
           IF WS-FLAG = "Y"
               CALL "IFCALL"
                   USING WS-AMT
           ELSE
               CALL "ELSECALL" USING WS-AMT
           END-IF.
           EVALUATE WS-FLAG
               WHEN "A"
                   CALL "WHENCALL" USING WS-AMT
               WHEN OTHER
                   CALL "OTHERCALL" USING WS-AMT
           END-EVALUATE.
           PERFORM UNTIL WS-FLAG = "N"
               CALL "LOOPCALL" USING WS-AMT
           END-PERFORM.
           IF WS-FLAG = "T"
               CALL "TERMCALL" USING WS-AMT
               END-CALL
           END-IF.
           STOP RUN.
"""

UNSAFE_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. NESTBAD.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-FLAG            PIC X.
       01  WS-AMT             PIC 9(5).

       PROCEDURE DIVISION.
       ONE-LINER.
           IF WS-FLAG = "Y" CALL "INLINE" USING WS-AMT END-IF.

       GLUED.
           IF WS-FLAG = "Y"
               CALL "GLUE"
                   USING WS-AMT END-IF.

       HANDLER-PARA.
           IF WS-FLAG = "Y"
               CALL "CLAUSED" USING WS-AMT
                   ON EXCEPTION
                       CALL "INHANDLER" USING WS-AMT
               END-CALL
           END-IF.
"""

EXEC_NESTED_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. NESTEXEC.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-FLAG            PIC X.
       01  WS-AMT             PIC 9(5).

       PROCEDURE DIVISION.
       SQL-PARA.
           IF WS-FLAG = "Y"
               EXEC SQL
                   UPDATE ORDERS
                       SET STATUS = CASE WHEN 1 > 0 THEN 'Y' ELSE 'N' END
                       WHERE ID = :WS-AMT
               END-EXEC
           END-IF.

       STOP-PARA.
           STOP RUN.
"""


def _annotated_surface(source, name):
    result = parse_cobol(source, filename=name)
    assert result.success, result.errors
    surface = analyze(result.ast)
    lines = normalize_fixed_format(source.splitlines()).splitlines()
    scope_map = collect_scope_map(result.ast, lines)
    annotate_nested_sites(surface, scope_map, lines)
    return surface, lines


def _site(surface, key):
    for site in surface.boundary_sites:
        if key in site.keys:
            return site
    raise AssertionError(f"no site with key {key}")


def _line_of(lines, needle):
    return next(i + 1 for i, line in enumerate(lines) if needle in line)


def test_scope_map_locates_block_words():
    result = parse_cobol(NESTED_SOURCE, filename="nestspan.cbl")
    lines = normalize_fixed_format(NESTED_SOURCE.splitlines()).splitlines()
    scope_map = collect_scope_map(result.ast, lines)
    words = {b.word for b in scope_map.boundaries}
    assert {"ELSE", "END-IF", "WHEN", "END-EVALUATE", "END-PERFORM"} <= words


def test_if_branch_call_span_stops_before_else():
    surface, lines = _annotated_surface(NESTED_SOURCE, "nestspan.cbl")
    site = _site(surface, "IFCALL")
    assert site.unspliceable_reason is None
    start, end = site.span
    assert start == _line_of(lines, 'CALL "IFCALL"')
    assert end == start + 1  # USING continuation line
    assert "ELSE" in lines[end]  # next line is the ELSE


def test_else_when_other_and_loop_bodies_get_spans():
    surface, lines = _annotated_surface(NESTED_SOURCE, "nestspan.cbl")
    for key, stopper in (
        ("ELSECALL", "END-IF"),
        ("WHENCALL", "WHEN OTHER"),
        ("OTHERCALL", "END-EVALUATE"),
        ("LOOPCALL", "END-PERFORM"),
    ):
        site = _site(surface, key)
        assert site.unspliceable_reason is None, (key, site.unspliceable_reason)
        start, end = site.span
        assert start == _line_of(lines, f'CALL "{key}"')
        assert stopper in lines[end]  # line after span is the block word


def test_own_end_call_terminator_is_inside_span():
    surface, lines = _annotated_surface(NESTED_SOURCE, "nestspan.cbl")
    site = _site(surface, "TERMCALL")
    assert site.unspliceable_reason is None
    start, end = site.span
    assert "END-CALL" in lines[end - 1]  # last span line is the END-CALL
    assert "END-IF" in lines[end]


def test_one_liner_nested_call_is_unspliceable():
    surface, _ = _annotated_surface(UNSAFE_SOURCE, "nestbad.cbl")
    site = _site(surface, "INLINE")
    assert site.span is None
    assert site.unspliceable_reason is not None


def test_glued_trailing_end_if_is_unspliceable():
    surface, _ = _annotated_surface(UNSAFE_SOURCE, "nestbad.cbl")
    site = _site(surface, "GLUE")
    assert site.span is None
    assert "does not start its own line" in site.unspliceable_reason


def test_call_with_handler_clause_is_unspliceable():
    surface, _ = _annotated_surface(UNSAFE_SOURCE, "nestbad.cbl")
    site = _site(surface, "CLAUSED")
    assert site.span is None
    assert "clause bodies" in site.unspliceable_reason


def test_site_inside_handler_clause_gets_its_own_span():
    # The enclosing CALL cannot be spliced (a CALL of its own kind in its
    # clause body), but the handler's CALL can be, in place: the enclosing
    # CALL then runs for real, and a case reaching it is refused unmocked.
    surface, _ = _annotated_surface(UNSAFE_SOURCE, "nestbad.cbl")
    site = _site(surface, "INHANDLER")
    assert site.nested_in_boundary
    assert site.span == (22, 23), site.unspliceable_reason


def test_nested_exec_sql_span_includes_end_exec():
    surface, lines = _annotated_surface(EXEC_NESTED_SOURCE, "nestexec.cbl")
    site = next(s for s in surface.boundary_sites if s.category is MockCategory.SQL)
    assert site.unspliceable_reason is None, site.unspliceable_reason
    start, end = site.span
    assert start == _line_of(lines, "EXEC SQL")
    assert "END-EXEC" in lines[end - 1]  # last span line
    assert "END-IF" in lines[end]  # CASE WHEN/ELSE in SQL text didn't truncate


# --- SECTION headers are boundaries (audit 2.2) ------------------------------

SECTION_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SECSPAN.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-AMT             PIC 9(5).

       PROCEDURE DIVISION.
       MAIN-SEC SECTION.
       MAIN-PARA.
           CALL "LASTCALL" USING WS-AMT.

       NEXT-SEC SECTION.
       NEXT-PARA.
           DISPLAY "NEXT".
"""


def test_span_of_sections_last_statement_ends_before_section_header():
    """Audit finding 2.2: SECTION header lines were not boundaries, so the
    span of a paragraph's last statement swallowed (and commented out) the
    following `NEXT-SEC SECTION.` header."""
    result = parse_cobol(SECTION_SOURCE, filename="secspan.cbl")
    assert result.success, result.errors
    lines = normalize_fixed_format(SECTION_SOURCE.splitlines()).splitlines()
    call_stmt = next(
        statement
        for paragraph in _all_section_paragraphs(result.ast)
        for statement in paragraph.statements
        if isinstance(statement, CallStatement)
    )
    boundaries = collect_boundaries(result.ast)
    section_header_line = next(
        i + 1 for i, line in enumerate(lines) if "NEXT-SEC SECTION" in line
    )
    assert section_header_line in boundaries
    _, end = statement_span(call_stmt, boundaries, last_line=len(lines), lines=lines)
    assert end < section_header_line


def _all_section_paragraphs(ast):
    procedure = ast.get_division("PROCEDURE")
    paragraphs = list(procedure.paragraphs)
    for section in procedure._sections.values():
        paragraphs.extend(section.paragraphs)
    return paragraphs


# --- top-level "owns its line" annotation (audit 2.1) -------------------------

TOP_LEVEL_LAYOUT_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TOPLAYOUT.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A               PIC 9(3).

       PROCEDURE DIVISION.
       SIBLING-PARA.
           MOVE 1 TO WS-A CALL "AFTERSIB" USING WS-A.

       ONE-LINER. CALL "ONHEADER" USING WS-A.

       TWO-CALLS.
           CALL "FIRSTONE" CALL "SECONDONE".

       CLEAN-PARA.
           CALL "CLEANONE" USING WS-A.
"""


def _annotated_top_level(source=TOP_LEVEL_LAYOUT_SOURCE, name="toplayout.cbl"):
    result = parse_cobol(source, filename=name)
    assert result.success, result.errors
    surface = analyze(result.ast)
    lines = normalize_fixed_format(source.splitlines()).splitlines()
    annotate_nested_sites(surface, collect_scope_map(result.ast, lines), lines)
    return surface


def test_top_level_call_after_sibling_code_is_annotated_unspliceable():
    """Audit finding 2.1: `MOVE 1 TO WS-A CALL "X" USING WS-A.` -- the
    whole-line splice used to silently delete the MOVE."""
    surface = _annotated_top_level()
    site = _site(surface, "AFTERSIB")
    assert site.unspliceable_reason is not None
    assert "does not start its own line" in site.unspliceable_reason


def test_one_line_paragraph_call_is_annotated_unspliceable():
    """`P1. CALL "X".` -- the splice used to comment out the paragraph
    header along with the statement."""
    surface = _annotated_top_level()
    site = _site(surface, "ONHEADER")
    assert site.unspliceable_reason is not None
    assert "does not start its own line" in site.unspliceable_reason


def test_two_top_level_statements_on_one_line_both_annotate_unspliceable():
    """Two mocked statements on one line must not be able to corrupt each
    other: the first shares its line with the second, the second does not
    start its own line -- both refuse."""
    surface = _annotated_top_level()
    first = _site(surface, "FIRSTONE")
    second = _site(surface, "SECONDONE")
    assert first.unspliceable_reason is not None
    assert "shares its line" in first.unspliceable_reason
    assert second.unspliceable_reason is not None
    assert "does not start its own line" in second.unspliceable_reason


def test_top_level_call_owning_its_line_is_annotated_clean():
    surface = _annotated_top_level()
    site = _site(surface, "CLEANONE")
    assert site.unspliceable_reason is None
    assert site.span is None  # top-level spans still come from statement_span


def test_top_level_call_with_own_clause_body_is_not_over_refused():
    """A top-level CALL whose ON EXCEPTION handler starts on the CALL's own
    line is still spliceable: the nested handler statements are part of the
    statement being replaced, not sibling code."""
    source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. HANDLERTOP.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A               PIC 9(3).

       PROCEDURE DIVISION.
       HANDLER-PARA.
           CALL "HANDLED" USING WS-A ON EXCEPTION
               MOVE 9 TO WS-A
           END-CALL.
"""
    surface = _annotated_top_level(source, "handlertop.cbl")
    site = _site(surface, "HANDLED")
    assert site.unspliceable_reason is None


# --- terminator (STOP RUN/GOBACK) site validation (Task 2) -------------------

TERMINATOR_OWN_LINE_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TERMOWNLINE.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-RESULT           PIC 9(4) VALUE 0.

       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           PERFORM 1000-DO-WORK
           STOP RUN.

       1000-DO-WORK.
           CALL "CALCPGM" USING WS-RESULT.
"""

TERMINATOR_SHARED_LINE_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TERMSHARELINE.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-RESULT           PIC 9(4) VALUE 0.

       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           MOVE 1 TO WS-RESULT STOP RUN.
"""

CANCEL_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CANCELSAMP.

       PROCEDURE DIVISION.
       MAIN-PARA.
           CALL "SUBPGM".
           CANCEL "SUBPGM".
"""


def _analyze_and_annotate(source, name="X.cbl"):
    result = parse_cobol(source, filename=name)
    assert result.success, result.errors
    lines = normalize_fixed_format(source.splitlines()).splitlines()
    surface = analyze(result.ast)
    annotate_nested_sites(surface, collect_scope_map(result.ast, lines), lines)
    return surface


def test_terminator_on_its_own_line_gets_no_unspliceable_reason():
    surface = _analyze_and_annotate(TERMINATOR_OWN_LINE_SOURCE)
    site = next(s for s in surface.boundary_sites if s.label == "STOP RUN")
    assert site.unspliceable_reason is None


def test_terminator_sharing_its_line_is_flagged_unspliceable():
    surface = _analyze_and_annotate(TERMINATOR_SHARED_LINE_SOURCE)
    site = next(s for s in surface.boundary_sites if s.label == "STOP RUN")
    assert site.unspliceable_reason == "does not start its own line"


def test_cancel_site_is_still_unannotated_after_terminator_change():
    """Regression guard: broadening the category-None skip must not start
    annotating CANCEL (or any other category=None label) -- only STOP
    RUN/GOBACK."""
    surface = _analyze_and_annotate(CANCEL_SOURCE)
    site = next(s for s in surface.boundary_sites if s.label == "CANCEL")
    assert site.span is None
    assert site.unspliceable_reason is None


# --- statement_top_level_problem (Task 2 factoring) ---------------------------

from cobolparser.models.statements.control import PerformStatement

from mockymock.splicer.source_map import statement_top_level_problem

PERFORM_OWN_LINE_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PERFORMOWNLINE.

       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM SUB-PARA.
           DISPLAY "AFTER".

       SUB-PARA.
           DISPLAY "SUB".
"""

PERFORM_SHARED_LINE_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PERFORMSHARE.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A                PIC 9.

       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 1 TO WS-A PERFORM SUB-PARA.

       SUB-PARA.
           DISPLAY "SUB".
"""


def _find_perform(program, paragraph_name):
    procedure = program.get_division("PROCEDURE")
    paragraph = next(
        p for p in procedure.paragraphs if p.paragraph_name == paragraph_name
    )
    # Not `.statements[0]`: PERFORM_SHARED_LINE_SOURCE's MAIN-PARA holds a
    # MoveStatement *then* the PerformStatement on the same line, so index 0
    # would silently test the wrong statement (verified empirically against
    # cobolparser's parse: statements[0] is the MOVE, statements[1] the
    # PERFORM).
    return next(s for s in paragraph.statements if isinstance(s, PerformStatement))


def test_statement_top_level_problem_none_when_perform_owns_its_line():
    result = parse_cobol(PERFORM_OWN_LINE_SOURCE, filename="x.cbl")
    assert result.success, result.errors
    lines = normalize_fixed_format(PERFORM_OWN_LINE_SOURCE.splitlines()).splitlines()
    scope_map = collect_scope_map(result.ast, lines)
    perform = _find_perform(result.ast, "MAIN-PARA")
    assert statement_top_level_problem(perform, scope_map, lines) is None


def test_statement_top_level_problem_set_when_perform_shares_its_line():
    result = parse_cobol(PERFORM_SHARED_LINE_SOURCE, filename="x.cbl")
    assert result.success, result.errors
    lines = normalize_fixed_format(PERFORM_SHARED_LINE_SOURCE.splitlines()).splitlines()
    scope_map = collect_scope_map(result.ast, lines)
    perform = _find_perform(result.ast, "MAIN-PARA")
    assert (
        statement_top_level_problem(perform, scope_map, lines)
        == "does not start its own line"
    )


# --- #310: a compiler-directing line never belongs to a statement's span ---

REPLACE_OFF_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. RP.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-X PIC X(4) VALUE SPACES.
       01 WS-Y PIC X(4) VALUE SPACES.
       PROCEDURE DIVISION.
       MAIN-PARA.
           REPLACE ==WS-Y== BY ==WS-X==.
           CALL "SUBPGM" USING WS-Y
           REPLACE OFF.
           MOVE "YYYY" TO WS-Y
           GOBACK.
"""

COND_COMPILE_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CC.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-X PIC X(4) VALUE SPACES.
       PROCEDURE DIVISION.
       MAIN-PARA.
       >>IF TESTMODE DEFINED
           CALL "TESTPGM" USING WS-X
       >>ELSE
           CALL "REALPGM" USING WS-X
       >>END-IF
           GOBACK.
       OTHER-PARA.
       >>IF TESTMODE DEFINED
           DISPLAY "T"
       >>ELSE
           GOBACK
       >>END-IF
           .
"""


def _span_of(source, predicate):
    result = parse_cobol(source, filename="d.cbl")
    assert result.success, result.errors
    lines = normalize_fixed_format(source.splitlines()).splitlines()
    procedure = result.ast.get_division("PROCEDURE")
    statement = next(
        s for p in procedure.paragraphs for s in p.statements if predicate(s)
    )
    start, end = statement_span(
        statement, collect_boundaries(result.ast), len(lines), lines
    )
    return lines[start - 1 : end]


def test_span_stops_before_replace_off():
    text = _span_of(REPLACE_OFF_SOURCE, lambda s: isinstance(s, CallStatement))
    assert any("CALL" in line for line in text)
    assert not any("REPLACE" in line for line in text)


def test_span_stops_before_end_if_directive():
    text = _span_of(
        COND_COMPILE_SOURCE,
        lambda s: isinstance(s, CallStatement) and "REALPGM" in str(s.to_dict()),
    )
    assert any("REALPGM" in line for line in text)
    assert not any(">>" in line for line in text)


def test_goback_span_stops_before_end_if_directive():
    text = _span_of(
        COND_COMPILE_SOURCE,
        lambda s: type(s).__name__ == "GobackStatement" and s.location.line > 13,
    )
    assert any("GOBACK" in line for line in text)
    assert not any(">>" in line for line in text)
