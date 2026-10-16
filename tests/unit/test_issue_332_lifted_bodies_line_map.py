"""Issue #332: a mocked READ's lifted AT END / NOT AT END bodies were
re-emitted stripped and re-indented, so the text-equality line map
(`build_original_line_map`, behind --trace, --coverage and the debugger)
never paired them with their source lines. They are now emitted verbatim."""

from cobolparser import parse_cobol
from cobolparser.preprocess import normalize_fixed_format

from mockymock.analysis.mock_surface import analyze, analyze_file_status_fields
from mockymock.dsl.parser import parse_cut
from mockymock.report.coverage import build_original_line_map
from mockymock.splicer.naming import TallyRegistry
from mockymock.splicer.orchestrator import splice_program
from mockymock.splicer.source_map import (
    annotate_nested_sites,
    collect_boundaries,
    collect_scope_map,
)

PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. RDLOOP.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-FILE ASSIGN TO "IN.DAT"
               FILE STATUS IS WS-FS.
       DATA DIVISION.
       FILE SECTION.
       FD  IN-FILE.
       01  IN-REC.
           05  IN-AMT          PIC 9(3).
       WORKING-STORAGE SECTION.
       01  WS-FS               PIC XX.
       01  WS-EOF              PIC X VALUE "N".
       01  WS-TOTAL            PIC 9(5) VALUE 0.
       01  WS-COUNT            PIC 9(3) VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM UNTIL WS-EOF = "Y"
               READ IN-FILE
                   AT END
                       MOVE "Y" TO WS-EOF
                   NOT AT END
                       ADD IN-AMT TO WS-TOTAL
                       ADD 1 TO WS-COUNT
               END-READ
           END-PERFORM
           GOBACK.
"""

CUT = """\
TESTSUITE "RDLOOP"

TESTCASE "two rows"
    MOCK READ IN-FILE ROWS
        ( IN-AMT = 10 )
        ( IN-AMT = 20 )
    END-MOCK
    PERFORM MAIN-PARA
"""


def test_lifted_body_lines_map_back_to_their_source_lines():
    result = parse_cobol(PROGRAM, filename="RDLOOP.cbl")
    assert result.success, result.errors
    suite = parse_cut(CUT)
    original = PROGRAM.splitlines()
    lines = normalize_fixed_format(original).splitlines()
    surface = analyze(result.ast)
    annotate_nested_sites(surface, collect_scope_map(result.ast, lines), lines)
    spliced = splice_program(
        lines,
        collect_boundaries(result.ast),
        surface,
        suite,
        TallyRegistry(suite),
        file_status_fields=analyze_file_status_fields(result.ast),
    )
    mapping = build_original_line_map(spliced, lines, original)
    mapped_back = {orig: spliced[inst - 1] for inst, orig in mapping.items()}

    def line_of(text: str) -> int:
        return next(i for i, line in enumerate(original, 1) if text in line)

    for text in ('MOVE "Y" TO WS-EOF', "ADD IN-AMT TO WS-TOTAL", "ADD 1 TO WS-COUNT"):
        source_line = line_of(text)
        assert source_line in mapped_back, text
        instrumented = mapped_back[source_line]
        assert text in instrumented and "*>" not in instrumented
