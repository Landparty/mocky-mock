"""Issue #301: with NOHANDLE, a failed EXEC CICS RETURN/XCTL/ABEND returns
control with the condition in EIBRESP, just as with RESP(field). The
mocked terminator's early exit is now gated on EIBRESP = 0, and DFHEIBLK is
synthesized for it even when the program never names EIBRESP."""

from __future__ import annotations

from cobolparser import parse_cobol
from cobolparser.preprocess import normalize_fixed_format

from mockymock.analysis.cics_eib import cics_eib_plan
from mockymock.analysis.refusal._plans import _cics_resp_field

PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. XN2.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-MSG  PIC X(12) VALUE SPACES.
       01  WS-RESP PIC S9(8) COMP.
       PROCEDURE DIVISION.
       2000-RET.
           EXEC CICS RETURN NOHANDLE END-EXEC
           EXEC CICS XCTL PROGRAM('P') NOHANDLE RESP(WS-RESP) END-EXEC
           EXEC CICS ABEND ABCODE('X') END-EXEC
           MOVE "AFTER" TO WS-MSG.
"""


def _parsed():
    result = parse_cobol(PROGRAM, filename="xn2.cbl")
    assert result.success, result.errors
    lines = normalize_fixed_format(PROGRAM.splitlines()).splitlines()
    return result.ast, lines


def test_nohandle_uses_eibresp_and_resp_wins() -> None:
    ast, _ = _parsed()
    statements = ast.find_all_by_type("ExecCicsStatement")
    assert [_cics_resp_field(s) for s in statements] == [
        ("EIBRESP", None),
        ("WS-RESP", None),
        (None, None),
    ]


def test_eib_is_synthesized_for_a_nohandle_terminator() -> None:
    ast, lines = _parsed()
    plan = cics_eib_plan(ast, lines)
    assert plan is not None
    assert "EIBRESP" in plan.referenced_names
