"""Pins the behaviour cut-dsl.md documents under "A mock replaces the
statement, not its clauses" (issue #209): mocking a READ comments out the
READ itself, and the program's own AT END / NOT AT END bodies are re-run
after the mock, selected by the mocked outcome (`UT-MOCK-STATUS`). Before
#209 both bodies were deleted with the statement, so a mocked READ fed
records that the program's own NOT AT END logic never processed."""

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


def _splice(cbl: str, cut: str) -> list[str]:
    result = parse_cobol(cbl, filename="PURGE.cbl")
    assert result.success, result.errors
    surface = analyze(result.ast)
    suite = parse_cut(cut)
    lines = normalize_fixed_format(cbl.splitlines()).splitlines()
    spliced = splice_program(
        lines,
        collect_boundaries(result.ast),
        surface,
        suite,
        TallyRegistry(suite),
    )
    return [line for line in spliced if not line.lstrip().startswith("*>")]


def test_mocked_read_reruns_its_own_clause_bodies_by_outcome():
    live = _splice(PURGE_CBL, PURGE_CUT)
    live_text = "\n".join(live)
    # The READ verb itself is gone; the mock body runs instead.
    assert "END-READ" not in live_text
    assert 'MOVE "20260101" TO PURG-CUTOFF-DATE' in live_text
    assert "GOBACK" in live_text
    # Both clause bodies come back, after the mock, each under its outcome.
    stripped = [line.strip() for line in live]
    mock_at = stripped.index('MOVE "20260101" TO PURG-CUTOFF-DATE')
    at_end = stripped.index('WHEN UT-MOCK-STATUS(1:1) = "1"')
    not_at_end = stripped.index('WHEN UT-MOCK-STATUS(1:1) = "0"')
    assert mock_at < at_end < not_at_end
    assert stripped[at_end + 1] == 'MOVE "Y" TO WS-EOF'
    assert stripped[not_at_end + 1] == "MOVE PURG-CUTOFF-DATE TO WS-CUTOFF-DATE"
    # Every mocked branch starts from success; an unmocked case selects none.
    assert 'MOVE "00" TO UT-MOCK-STATUS' in stripped
    assert stripped.index("MOVE SPACES TO UT-MOCK-STATUS") < mock_at


def test_a_clause_body_holding_a_terminator_is_not_lifted():
    """A body that would end the run (STOP RUN) or run another boundary
    unmocked is not lifted; the refusal gate refuses such a mocked site
    (UNLIFTABLE_CLAUSE_BODY, issue #319), and the splicer on its own keeps
    the whole-statement replacement. A GO TO body is lifted since #319."""
    cbl = PURGE_CBL.replace(
        '                   MOVE "Y" TO WS-EOF\n',
        "                   STOP RUN\n",
    )
    live_text = "\n".join(_splice(cbl, PURGE_CUT))
    assert "UT-MOCK-STATUS" not in live_text
    assert "MOVE PURG-CUTOFF-DATE TO WS-CUTOFF-DATE" not in live_text


def test_a_clause_body_holding_a_go_to_is_lifted():
    cbl = PURGE_CBL.replace(
        '                   MOVE "Y" TO WS-EOF\n',
        "                   GO TO MAIN-EXIT\n",
    ).replace(
        "           GOBACK.\n",
        "           GOBACK.\n       MAIN-EXIT.\n           EXIT.\n",
    )
    stripped = [line.strip() for line in _splice(cbl, PURGE_CUT)]
    at_end = stripped.index('WHEN UT-MOCK-STATUS(1:1) = "1"')
    assert stripped[at_end + 1] == "GO TO MAIN-EXIT"
    assert "MOVE PURG-CUTOFF-DATE TO WS-CUTOFF-DATE" in stripped
