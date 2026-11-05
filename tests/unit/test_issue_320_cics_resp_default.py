"""Issue #320 (option 1, default success): a mocked EXEC CICS command
starts by moving 0 (DFHRESP(NORMAL)) to its own RESP / RESP2 items and to
EIBRESP / EIBRESP2 when the program has them, as real CICS sets them on
every command. An empty mock used to leave the previous command's
condition there, so the next success check took its error branch."""

from cobolparser import parse_cobol
from cobolparser.preprocess import normalize_fixed_format

from mockymock.analysis.mock_surface import analyze
from mockymock.dsl.parser import parse_cut
from mockymock.splicer.cics_resp import resp_operands
from mockymock.splicer.naming import TallyRegistry
from mockymock.splicer.orchestrator import splice_program
from mockymock.splicer.source_map import collect_boundaries

PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CICSR.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-REC              PIC X(20).
       01  WS-KEY              PIC X(5).
       01  WS-RESP             PIC S9(8) COMP.
       01  WS-RESP2            PIC S9(8) COMP.
       01  WS-MSG              PIC X(20).
       01  WS-LAST             PIC S9(8) COMP.
       PROCEDURE DIVISION.
       1000-LOOKUP.
           EXEC CICS READ FILE('CUSTF') INTO(WS-REC) RIDFLD(WS-KEY)
                RESP(WS-RESP) END-EXEC
           EXEC CICS WRITEQ TS QUEUE('AUDITQ') FROM(WS-REC)
                RESP(WS-RESP) RESP2(WS-RESP2) END-EXEC
{eib}           IF WS-RESP NOT = 0
               MOVE "AUDIT FAILED" TO WS-MSG
           END-IF.
"""

CUT = """\
TESTSUITE "CICSR"

TESTCASE "notfnd then ok"
    MOCK CICS "READ"
        MOVE 13 TO WS-RESP
    END-MOCK
    MOCK CICS "WRITEQ"
    END-MOCK
    PERFORM 1000-LOOKUP
"""


def _splice(eib: str = "") -> list[str]:
    source = PROGRAM.format(eib=eib)
    result = parse_cobol(source, filename="CICSR.cbl")
    assert result.success, result.errors
    suite = parse_cut(CUT)
    lines = normalize_fixed_format(source.splitlines()).splitlines()
    spliced = splice_program(
        lines,
        collect_boundaries(result.ast),
        analyze(result.ast),
        suite,
        TallyRegistry(suite),
    )
    return [line.strip() for line in spliced if not line.lstrip().startswith("*>")]


def _branch(live: list[str], tally_fragment: str) -> list[str]:
    start = next(
        i
        for i, line in enumerate(live)
        if line.startswith("ADD 1 TO") and tally_fragment in line
    )
    end = live.index("WHEN OTHER", start)
    return live[start + 1 : end]


def test_resp_and_resp2_default_to_normal_before_the_body():
    live = _splice()
    assert _branch(live, "READ") == ["MOVE 0 TO WS-RESP", "MOVE 13 TO WS-RESP"]
    assert _branch(live, "WRITEQ") == [
        "MOVE 0 TO WS-RESP",
        "MOVE 0 TO WS-RESP2",
    ]


def test_eibresp_is_reset_when_the_program_has_it():
    live = _splice(eib="           MOVE EIBRESP TO WS-LAST\n")
    assert _branch(live, "WRITEQ") == [
        "MOVE 0 TO WS-RESP",
        "MOVE 0 TO WS-RESP2",
        "MOVE 0 TO EIBRESP",
        # RESP and EIBRESP end equal, whichever one the body set.
        "IF WS-RESP NOT = 0",
        "MOVE WS-RESP TO EIBRESP",
        "ELSE",
        "MOVE EIBRESP TO WS-RESP",
        "END-IF",
    ]


class _Statement:
    def __init__(self, text: str) -> None:
        self.cics_text = text


def test_resp_operands_reads_single_data_names_only():
    assert resp_operands(_Statement("READ FILE('F') RESP(A-1) RESP2(B)")) == [
        "A-1",
        "B",
    ]
    assert resp_operands(_Statement("READ FILE('F') RESP(TBL (2))")) == []
    assert resp_operands(_Statement("READ FILE('F')")) == []
