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

    start, end = statement_span(call_stmt, boundaries, last_line=len(lines))

    assert start == call_stmt.location.line
    assert end == start + 2
    assert "CALL" in lines[start - 1]
    assert "WS-RATE" in lines[end - 1]


def test_span_ends_before_next_paragraph_header():
    ast, lines = _ast_and_lines()
    call_stmt = _find_call_statement(ast)
    boundaries = collect_boundaries(ast)

    _, end = statement_span(call_stmt, boundaries, last_line=len(lines))

    second_paragraph_line = next(
        i + 1 for i, line in enumerate(lines) if "SECOND-PARAGRAPH" in line
    )
    assert end < second_paragraph_line
