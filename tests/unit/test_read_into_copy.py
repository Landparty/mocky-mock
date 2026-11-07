"""READ ... INTO: when the spliced mock copies the FD record into the
INTO item, and which FD record is copied and reset.

Regression: nightly bug hunt of 2026-10-09. Executed counterparts:
tests/integration/test_nightly_20261009_read_into.py."""

from cobolparser import parse_cobol

from mockymock.splicer.io_copy import data_layout, into_move
from mockymock.splicer.reset import reset_move_lines
from tests.integration.test_nightly_20261009_read_into import (
    FDR_CBL,
    MR_CBL,
    RINTO_CBL,
    RNF_CBL,
)


def _read(cbl: str):
    program = parse_cobol(cbl).ast
    reads = [
        s for s in program.get_all_statements() if type(s).__name__ == "IOReadStatement"
    ]
    return program, reads[0]


def test_a_body_qualified_by_the_record_still_copies() -> None:
    program, read = _read(RINTO_CBL)
    move = into_move(read, data_layout(program), ["MOVE 5 TO R-AMT OF IN-REC"])
    assert move == "MOVE IN-REC TO WS-REC"


def test_a_body_naming_the_into_item_suppresses_the_copy() -> None:
    program, read = _read(RINTO_CBL)
    layout = data_layout(program)
    assert into_move(read, layout, ["MOVE 5 TO R-AMT OF WS-REC"]) is None
    assert into_move(read, layout, ["MOVE 5 TO R-AMT"]) is None


def test_the_copy_is_guarded_by_a_success_status() -> None:
    program, read = _read(RNF_CBL)
    move = into_move(read, data_layout(program), [], "WS-FS")
    assert move == 'IF WS-FS(1:1) = "0" MOVE CUST-REC TO WS-CUST END-IF'


def test_the_longest_fd_record_is_copied() -> None:
    program, read = _read(MR_CBL)
    assert into_move(read, data_layout(program), []) == "MOVE IN-DTL TO WS-REC"


def test_the_longest_fd_record_is_reset() -> None:
    program = parse_cobol(FDR_CBL).ast
    text = " ".join(reset_move_lines(program))
    assert "OUT-DTL" in text
    assert "OUT-HDR" not in text
