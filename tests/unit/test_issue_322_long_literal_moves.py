"""Issue #322: cobc -free truncates a source line past 512 bytes. Long
literals in hook MOVEs, ROWS / TERMINAL values and mock body MOVEs were
written on one driver line (only TESTCASE setup MOVEs and EXPECTs were
split), so a lint-clean suite failed to compile. They are now split into
`&` pieces; a mock body line that still cannot fit is refused."""

from mockymock.analysis.refusal import (
    REFUSAL_EXPLANATIONS,
    check_mock_body_line_length,
)
from mockymock.dsl.model import HookStep
from mockymock.dsl.parser import parse_cut
from mockymock.splicer.driver import _step_lines
from mockymock.splicer.injector import build_rows_block
from mockymock.splicer.literals import split_long_move

LIT = 'X"' + "41" * 300 + '"'


def _fits(lines: list[str]) -> bool:
    return all(len(line) <= 512 for line in lines)


def _rejoined(lines: list[str]) -> str:
    return " ".join(line.strip() for line in lines)


def test_split_long_move_splits_only_a_whole_long_literal():
    lines = split_long_move(f"        MOVE {LIT} TO WS-BUF")
    assert len(lines) > 1 and _fits(lines)
    assert lines[0].startswith('        MOVE X"4141')
    assert lines[1].lstrip().startswith('& X"41')
    assert lines[-1].endswith('" TO WS-BUF')
    for line in ("MOVE 1 TO WS-N", 'MOVE "A TO B" TO WS-X', "ADD 1 TO WS-N"):
        assert split_long_move(line) == [line]


def test_hook_move_steps_are_split():
    step = HookStep(kind="MOVE", target="WS-HOLD", value=LIT, line=1)
    lines = _step_lines([step])
    assert len(lines) > 1 and _fits(lines)
    assert _rejoined(lines).startswith("MOVE X")
    assert _rejoined(lines).endswith("TO WS-HOLD")


def test_rows_and_terminal_values_are_split():
    lines = build_rows_block(
        "UT-T",
        [[("IN-REC", LIT)]],
        row_suffix_moves=[],
        exhausted_moves=[f"MOVE {LIT} TO IN-REC"],
    )
    assert _fits(lines)
    assert sum(line.lstrip().startswith("MOVE X") for line in lines) == 2


def test_a_body_line_that_cannot_be_split_is_refused():
    long_name = "WS-" + "A" * 26
    expression = " + ".join([long_name] * 20)
    suite = parse_cut(
        'TESTSUITE "S"\n'
        'TESTCASE "c"\n'
        '    MOCK CALL "SUB"\n'
        f"        COMPUTE WS-N = {expression}\n"
        f"        MOVE {LIT} TO WS-BUF\n"
        "    END-MOCK\n"
        "    PERFORM P\n"
    )
    reasons = check_mock_body_line_length(suite)
    assert [r.code for r in reasons] == ["MOCK_LINE_TOO_LONG"]
    assert 'MOCK CALL "SUB"' in reasons[0].message
    assert "COMPUTE" in reasons[0].message
    assert "MOCK_LINE_TOO_LONG" in REFUSAL_EXPLANATIONS
