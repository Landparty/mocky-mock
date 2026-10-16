"""Issue #256: the debugger's ParagraphIndex is built from AST lines (the
copybook-expanded text) but queried with original `.cbl` lines; mapping
each paragraph start to the original file keeps the CALL STACK names
right in a program with a WORKING-STORAGE COPY."""

from __future__ import annotations

from mockymock._lines import read_utf8_source, split_source_lines
from mockymock.cli.checks import run_static_checks
from mockymock.debug.call_stack import ParagraphIndex
from mockymock.report.coverage import build_original_line_map

COPYBOOK = "".join(
    f"       01  WS-{name}                 PIC X(4).\n" for name in "ABCD"
)

PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CPY.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       COPY WSREC.
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE "X" TO WS-B
           PERFORM SUB-PARA
           GOBACK.
       SUB-PARA.
           MOVE "ZZZZ" TO WS-A.
"""

CUT = 'TESTSUITE "c"\nTESTCASE "a"\n    PERFORM MAIN-PARA\n    EXPECT WS-B TO BE "X"\n'


def test_paragraph_names_resolve_in_original_lines(tmp_path) -> None:
    (tmp_path / "copybooks").mkdir()
    (tmp_path / "copybooks" / "WSREC.cpy").write_text(COPYBOOK)
    (tmp_path / "CPY.cbl").write_text(PROGRAM)
    (tmp_path / "CPY.cut").write_text(CUT)
    checked = run_static_checks(
        tmp_path / "CPY.cbl", tmp_path / "CPY.cut", [str(tmp_path / "copybooks")]
    )
    assert not checked.problems
    lines = list(checked.lines)
    original = split_source_lines(read_utf8_source(tmp_path / "CPY.cbl"))
    index = ParagraphIndex.build(
        checked.parse_result.ast, build_original_line_map(lines, lines, original)
    )
    assert index.resolve(8) == ("MAIN-PARA", None)  # MOVE "X" TO WS-B
    assert index.resolve(12) == ("SUB-PARA", None)  # MOVE "ZZZZ" TO WS-A
