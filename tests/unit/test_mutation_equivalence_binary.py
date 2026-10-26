"""Zero-then-add is only equivalent where an unsigned item keeps the
magnitude of a negative result. A binary item does not under GnuCOBOL:
`MOVE 0 TO X` then `SUBTRACT 5 FROM X` on `PIC 9(4) COMP` leaves 65531,
so a test asserting X kills the swap and it must not be called
equivalent."""

from __future__ import annotations

import pytest

from mockymock.mutation.equivalence import equivalence_reason
from mockymock.mutation.operators import generate_mutants

PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. EQBIN.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-COMP   PIC 9(4) COMP.
       01  WS-BIN    PIC 9(4) BINARY.
       01  WS-COMP5  PIC 9(4) COMP-5.
       01  WS-GROUP  USAGE COMP.
           05  WS-INHERITS PIC 9(4).
       01  WS-PACKED PIC 9(4) COMP-3.
       01  WS-ZONED  PIC 9(4).
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 0 TO WS-COMP
           ADD 5 TO WS-COMP
           MOVE 0 TO WS-BIN
           ADD 5 TO WS-BIN
           MOVE 0 TO WS-COMP5
           ADD 5 TO WS-COMP5
           MOVE 0 TO WS-INHERITS
           ADD 5 TO WS-INHERITS
           MOVE 0 TO WS-PACKED
           ADD 5 TO WS-PACKED
           MOVE 0 TO WS-ZONED
           ADD 5 TO WS-ZONED
           STOP RUN.
"""


def _swap_reason(line: int) -> str:
    from cobolparser import parse_cobol

    lines = PROGRAM.splitlines()
    ast = parse_cobol(PROGRAM, filename="EQBIN.cbl").ast
    (mutant,) = [
        m
        for m in generate_mutants(lines)
        if m.line == line and m.operator == "arith-verb-swap"
    ]
    return equivalence_reason(mutant, lines, ast)


@pytest.mark.parametrize("line", [15, 17, 19, 21])
def test_zero_then_add_on_a_binary_field_is_not_equivalent(line):
    assert _swap_reason(line) == ""


@pytest.mark.parametrize("line", [23, 25])
def test_zero_then_add_on_a_packed_or_zoned_field_still_is(line):
    assert "unsigned" in _swap_reason(line)
