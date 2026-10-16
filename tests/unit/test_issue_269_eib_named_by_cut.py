"""Issue #269: an EIB field named only by the .cut (setup MOVE, EXPECT, a
mock body) still gets the synthesized DFHEIBLK it needs to compile."""

from mockymock.cli.checks import run_static_checks

PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CEIB.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-REC   PIC X(10).
       01  WS-KEY   PIC X(5) VALUE "K1".
       PROCEDURE DIVISION.
       MAIN-PARA.
           EXEC CICS READ FILE('CUST') INTO(WS-REC) RIDFLD(WS-KEY)
           END-EXEC
           GOBACK.
"""

CUT = """\
TESTSUITE "eib"
TESTCASE "found"
    MOCK CICS "READ"
        MOVE "SMITH" TO WS-REC
    END-MOCK
    MOVE 0 TO EIBCALEN
    PERFORM MAIN-PARA
    EXPECT EIBRESP TO BE 0
"""


def test_eib_fields_named_only_in_the_cut_are_synthesized(tmp_path) -> None:
    program = tmp_path / "CEIB.cbl"
    program.write_text(PROGRAM)
    cut = tmp_path / "CEIB.cut"
    cut.write_text(CUT)
    checked = run_static_checks(program, cut, None)
    assert checked.problems == []
    assert checked.cics_eib is not None
    assert checked.cics_eib.referenced_names == ["EIBCALEN", "EIBRESP"]


def test_no_eib_anywhere_synthesizes_nothing(tmp_path) -> None:
    program = tmp_path / "CEIB.cbl"
    program.write_text(PROGRAM)
    cut = tmp_path / "CEIB.cut"
    cut.write_text(
        CUT.replace("    MOVE 0 TO EIBCALEN\n", "").replace(
            "    EXPECT EIBRESP TO BE 0\n", '    EXPECT WS-REC TO BE "SMITH"\n'
        )
    )
    assert run_static_checks(program, cut, None).cics_eib is None
