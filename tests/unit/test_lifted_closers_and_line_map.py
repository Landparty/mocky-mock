"""#319 + #332 together: a mocked READ whose last clause body ends at the
sentence period gets the END-IF that period closed appended (#319), while
its body lines are still emitted verbatim so the line map behind --trace
pairs them with their source lines (#332)."""

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
       PROGRAM-ID. RDCLOSE.
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
       01  WS-BIG              PIC 9(3) VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM READ-ONE UNTIL WS-EOF = "Y"
           GOBACK.
       READ-ONE.
           READ IN-FILE
               AT END
                   MOVE "Y" TO WS-EOF
               NOT AT END
                   IF IN-AMT > 15
                       ADD 1 TO WS-BIG.
"""

CUT = """\
TESTSUITE "RDCLOSE"

TESTCASE "two rows"
    MOCK READ IN-FILE ROWS
        ( IN-AMT = 10 )
        ( IN-AMT = 20 )
    END-MOCK
    PERFORM MAIN-PARA
    EXPECT WS-BIG TO BE 1
"""


def test_closer_is_emitted_and_lifted_lines_stay_mapped():
    result = parse_cobol(PROGRAM, filename="RDCLOSE.cbl")
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
    live = [line for line in spliced if not line.lstrip().startswith("*>")]
    # The last EVALUATE TRUE is the clause guard (the first is the ROWS one).
    guard_start = max(
        i for i, line in enumerate(live) if line.strip() == "EVALUATE TRUE"
    )
    guard = live[guard_start:]
    guard_end = next(i for i, line in enumerate(guard) if "END-EVALUATE" in line)
    body = [line.strip() for line in guard[:guard_end]]
    # The END-IF the period closed comes after the verbatim IF body (#319).
    assert body.index("END-IF") > body.index("ADD 1 TO WS-BIG")

    mapping = build_original_line_map(spliced, lines, original)
    mapped_back = {orig: spliced[inst - 1] for inst, orig in mapping.items()}
    for text in ('MOVE "Y" TO WS-EOF', "IF IN-AMT > 15"):
        source_line = next(i for i, line in enumerate(original, 1) if text in line)
        assert source_line in mapped_back, text
        assert "*>" not in mapped_back[source_line], text
