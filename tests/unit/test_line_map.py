"""Tests for the debugger's bidirectional line mapping. Pure string
parsing, mirroring report/coverage.py's own test fixtures (build_original_
line_map is reused as-is; this only adds the reverse direction and the
breakpoint-rejection helper)."""

from mockymock.debug.line_map import LineMap

ORIGINAL = [
    "      *comment",
    "       MOVE 1 TO WS-A",
    "       ADD 1 TO WS-A",
]
NORMALIZED = ["MOVE 1 TO WS-A", "ADD 1 TO WS-A"]
INSTRUMENTED = ["MOVE 1 TO WS-A", "ADD 1 TO UT-TALLY-1", "ADD 1 TO WS-A"]


def _line_map() -> LineMap:
    return LineMap.build(INSTRUMENTED, NORMALIZED, ORIGINAL)


def test_to_original_matches_build_original_line_map():
    line_map = _line_map()
    assert line_map.to_original(1) == 2
    assert line_map.to_original(3) == 3
    assert line_map.to_original(2) is None  # splicer-inserted tally line


def test_to_instrumented_is_the_inverse():
    line_map = _line_map()
    assert line_map.to_instrumented(2) == 1
    assert line_map.to_instrumented(3) == 3
    assert line_map.to_instrumented(1) is None  # the comment line: never instrumented


def test_round_trip_through_both_directions():
    line_map = _line_map()
    for original_line in (2, 3):
        instrumented = line_map.to_instrumented(original_line)
        assert instrumented is not None
        assert line_map.to_original(instrumented) == original_line


def test_reject_reason_is_none_for_a_settable_line():
    line_map = _line_map()
    assert line_map.reject_reason(2) is None
    assert line_map.reject_reason(3) is None


def test_reject_reason_explains_an_unmappable_line():
    line_map = _line_map()
    reason = line_map.reject_reason(1)  # the comment line
    assert reason is not None
    assert "line 1" in reason
