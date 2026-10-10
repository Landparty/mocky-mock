"""Pins the behaviour cut-dsl.md documents under "A mock replaces the whole
statement, clauses included": mocking a READ comments out its AT END and
NOT AT END bodies too, so the program's own statements in those clauses
never run under the mock."""

from cobolparser import parse_cobol
from cobolparser.preprocess import normalize_fixed_format

from mockymock.analysis.mock_surface import analyze
from mockymock.dsl.parser import parse_cut
from mockymock.splicer.naming import TallyRegistry
from mockymock.splicer.orchestrator import splice_program
from mockymock.splicer.source_map import collect_boundaries

PURGE_CBL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PURGE.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT PURGE-PARM-FILE ASSIGN TO "PARMS".
       DATA DIVISION.
       FILE SECTION.
       FD  PURGE-PARM-FILE.
       01  PURGE-PARM-REC.
           05 PURG-CUTOFF-DATE PIC X(8).
       WORKING-STORAGE SECTION.
       01  WS-EOF          PIC X VALUE "N".
       01  WS-CUTOFF-DATE  PIC X(8).
       PROCEDURE DIVISION.
       MAIN-PARA.
           READ PURGE-PARM-FILE
               AT END
                   MOVE "Y" TO WS-EOF
               NOT AT END
                   MOVE PURG-CUTOFF-DATE TO WS-CUTOFF-DATE
           END-READ
           GOBACK.
"""

PURGE_CUT = """\
TESTSUITE "PURGE"

TESTCASE "cutoff date"
    MOCK READ PURGE-PARM-FILE
        MOVE "20260101" TO PURG-CUTOFF-DATE
    END-MOCK
    PERFORM MAIN-PARA
"""


def test_mocked_read_comments_out_its_at_end_and_not_at_end_bodies():
    result = parse_cobol(PURGE_CBL, filename="PURGE.cbl")
    assert result.success, result.errors
    surface = analyze(result.ast)
    suite = parse_cut(PURGE_CUT)
    lines = normalize_fixed_format(PURGE_CBL.splitlines()).splitlines()

    spliced = splice_program(
        lines,
        collect_boundaries(result.ast),
        surface,
        suite,
        TallyRegistry(suite),
    )

    live = [line for line in spliced if not line.lstrip().startswith("*>")]
    live_text = "\n".join(live)
    # Both clause bodies are gone from the live code, not just the READ verb.
    assert "MOVE PURG-CUTOFF-DATE TO WS-CUTOFF-DATE" not in live_text
    assert 'MOVE "Y" TO WS-EOF' not in live_text
    assert "END-READ" not in live_text
    # The mock body is what runs instead.
    assert 'MOVE "20260101" TO PURG-CUTOFF-DATE' in live_text
    assert "GOBACK" in live_text
