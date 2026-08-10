"""Tests for call_stack.py. Every value canned below (generated-C line
numbers, frame_stack depth, resolved addresses) is taken from a real debug
session against the spike fixture (see
docs/2026-07-22-dap-debugger-design.md's Empirical basis and the CLI
implementation plan's Task 5) -- not hand-invented."""

from mockymock.debug.call_stack import (
    ParagraphIndex,
    build_generated_c_line_map,
    synthesize_stack,
)
from mockymock.debug.line_map import LineMap

# A trimmed slice of the real generated fixture.c, including only the
# #line directives that matter for this test (the parser only looks at
# lines matching `#line N "....cbl"` -- everything else is ignored, so
# omitting unrelated lines does not change the result).
GENERATED_C_TEXT = "\n".join(
    [
        '#line 9 "/work/x/fixture.cbl"',
        "l_2:;",
        "",
        '#line 15 "/work/x/fixture.cbl"',
        "  cob_nop ();",
        "#line 153 fixture.c",  # not a .cbl directive: must be ignored
        "  frame_ptr++;",
        "  frame_ptr->return_address_ptr = &&l_6;",
        "  goto l_5;",
        "  l_6:;",  # <- resolves here: generated-C line 9
        "  frame_ptr--;",
        '#line 13 "/work/x/fixture.cbl"',
        "  cob_nop ();",
        "",
        '#line 19 "/work/x/fixture.cbl"',
        "l_5:;",
        '#line 20 "/work/x/fixture.cbl"',
        "  cob_nop ();",
        "  cob_add_int (&f_18, 1, 0);",
    ]
)


def _identity_line_map(max_line: int = 30) -> LineMap:
    identity = {i: i for i in range(1, max_line + 1)}
    return LineMap(_to_original=identity, _to_instrumented=identity)


def test_build_generated_c_line_map_only_captures_cbl_directives():
    entries = build_generated_c_line_map(GENERATED_C_TEXT)
    # Every entry's line number is a .cbl line; the "fixture.c"
    # self-referential directive on line 6 must not appear.
    assert (1, 9) in entries
    assert (4, 15) in entries
    assert (12, 13) in entries
    assert all(cobol_line != 153 for _, cobol_line in entries)


def test_nearest_preceding_finds_the_call_sites_own_line():
    """The return-address line (right after `goto l_5;`) has no .cbl
    marker of its own; the nearest PRECEDING one is the PERFORM
    statement's own line -- confirmed empirically."""
    from mockymock.debug.call_stack import _nearest_preceding_cobol_line

    entries = build_generated_c_line_map(GENERATED_C_TEXT)
    return_address_line = 9  # the "l_6:;" line, generated-C line 9 in this text
    assert _nearest_preceding_cobol_line(entries, return_address_line) == 15


class _StubProgram:
    def __init__(self, paragraph_starts):
        self._paragraph_starts = paragraph_starts

    def get_division(self, name):
        assert name == "PROCEDURE"
        return self


class _StubParagraph:
    def __init__(self, name, line):
        self.paragraph_name = name
        self.location = _Loc(line)


class _Loc:
    def __init__(self, line):
        self.line = line


def _spike_paragraph_index() -> ParagraphIndex:
    """Mirrors the spike fixture: MAIN-PARA at line 9, CALC-INTEREST at
    line 19, no SECTIONs."""
    return ParagraphIndex(
        paragraph_starts=[(9, "MAIN-PARA"), (19, "CALC-INTEREST")],
        section_starts=[],
    )


def test_paragraph_index_resolves_line_to_enclosing_paragraph():
    index = _spike_paragraph_index()
    assert index.resolve(10)[0] == "MAIN-PARA"
    assert index.resolve(20)[0] == "CALC-INTEREST"
    assert index.resolve(20)[1] is None  # no SECTIONs in the fixture


class _FakeGdbSession:
    """Canned responses for the exact evaluate/resolve_address calls
    synthesize_stack issues, taken from the real spike-fixture session
    stopped inside CALC-INTEREST (frame_ptr-frame_stack == 1)."""

    def __init__(self):
        self.sent: list[str] = []

    def send(self, command: str):
        self.sent.append(command)
        if command == "-data-evaluate-expression frame_ptr-frame_stack":
            return [_done("1")]
        if (
            command
            == "-data-evaluate-expression (long)frame_stack[1].return_address_ptr"
        ):
            return [_done("94317603726646")]
        raise AssertionError(f"unexpected command: {command!r}")

    def resolve_address(self, address: int) -> dict:
        assert address == 94317603726646
        return {"file": "fixture.c", "fullname": "/work/x/fixture.c", "line": "9"}


def _done(value):
    from mockymock.debug.gdb_session import ResultRecord

    return ResultRecord("done", {"value": value})


def test_synthesize_stack_matches_the_verified_spike_scenario():
    """Stopped inside CALC-INTEREST (line 20), performed from MAIN-PARA's
    loop body (line 15) -- the exact scenario verified against the real
    container."""
    session = _FakeGdbSession()
    line_map = _identity_line_map()
    generated_c_lines = build_generated_c_line_map(GENERATED_C_TEXT)
    paragraph_index = _spike_paragraph_index()

    stack = synthesize_stack(
        session,
        line_map,
        generated_c_lines,
        paragraph_index,
        current_file="/work/x/fixture.cbl",
        current_line=20,
    )

    assert len(stack) == 2
    assert stack[0].paragraph == "CALC-INTEREST"
    assert stack[0].original_line == 20
    assert stack[1].paragraph == "MAIN-PARA"
    assert stack[1].original_line == 15


def test_synthesize_stack_skips_an_unresolvable_frame_without_failing_the_rest():
    """Audit finding F14: one bad frame (a GdbCommandError resolving a
    corrupted slot or unresolvable address) must not fail the whole
    stackTrace request -- frame 0 and every other resolvable caller
    frame are still returned."""
    from mockymock.debug.gdb_session import GdbCommandError

    class _OneBadFrameSession:
        def __init__(self):
            self.sent: list[str] = []

        def send(self, command: str):
            self.sent.append(command)
            if command == "-data-evaluate-expression frame_ptr-frame_stack":
                return [_done("2")]
            if (
                command == "-data-evaluate-expression (long)frame_stack[2]"
                ".return_address_ptr"
            ):
                raise GdbCommandError("corrupted slot")
            if (
                command == "-data-evaluate-expression (long)frame_stack[1]"
                ".return_address_ptr"
            ):
                return [_done("94317603726646")]
            raise AssertionError(f"unexpected command: {command!r}")

        def resolve_address(self, address: int) -> dict:
            assert address == 94317603726646
            return {"file": "fixture.c", "fullname": "/work/x/fixture.c", "line": "9"}

    stack = synthesize_stack(
        _OneBadFrameSession(),
        _identity_line_map(),
        build_generated_c_line_map(GENERATED_C_TEXT),
        _spike_paragraph_index(),
        current_file="/work/x/fixture.cbl",
        current_line=20,
    )

    # Frame 0 (current) + the resolvable frame_stack[1] caller; the
    # unresolvable frame_stack[2] slot is skipped, not fatal.
    assert len(stack) == 2
    assert stack[0].paragraph == "CALC-INTEREST"
    assert stack[1].paragraph == "MAIN-PARA"


def test_synthesize_stack_stops_at_zero_depth_with_only_the_current_frame():
    class _NoCallerSession(_FakeGdbSession):
        def send(self, command: str):
            self.sent.append(command)
            if command == "-data-evaluate-expression frame_ptr-frame_stack":
                return [_done("0")]
            raise AssertionError(f"unexpected command: {command!r}")

    stack = synthesize_stack(
        _NoCallerSession(),
        _identity_line_map(),
        build_generated_c_line_map(GENERATED_C_TEXT),
        _spike_paragraph_index(),
        current_file="/work/x/fixture.cbl",
        current_line=9,
    )

    assert len(stack) == 1
    assert stack[0].paragraph == "MAIN-PARA"
