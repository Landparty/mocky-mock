"""Synthesizes the COBOL paragraph/section call stack for the debugger.

GnuCOBOL compiles the entire PROCEDURE DIVISION into one C function; a
`PERFORM` of another paragraph is a computed-goto plus a push onto
GnuCOBOL's own `frame_stack[255]` array of return addresses, never a real
C call (confirmed empirically -- `bt`/`-stack-list-frames` always report
exactly one program frame, `SPIKE_`, regardless of PERFORM nesting depth;
see docs/2026-07-22-dap-debugger-design.md's Empirical basis, "call stack
synthesis" finding). This module walks `frame_ptr`/`frame_stack` itself
instead of trusting gdb's backtrace.

A `frame_stack[i].return_address_ptr` is a raw code address, resolved via
`GdbSession.resolve_address` (a temporary breakpoint insert/delete). That
address usually lands in the middle of the GENERATED C plumbing for a
PERFORM (e.g. the `frame_ptr--;` line right after the internal `goto`
returns), not exactly on a `#line N "<file>.cbl"` marker -- confirmed
empirically: the return address for a `PERFORM CALC-INTEREST` inside a
loop resolved to a raw `fixture.c` line, and the nearest PRECEDING
`#line ... .cbl` directive in the generated source (found by scanning the
compiled `.c` file's own `#line` directives) was exactly the `PERFORM`
statement's own line -- precisely the caller's location a DAP stack frame
should show. `build_generated_c_line_map` builds that nearest-preceding
lookup; it is a NEW mapping, distinct from line_map.py's original <->
instrumented mapping (which only ever relates two COBOL-shaped texts, never
the generated C file).
"""

from __future__ import annotations

import bisect
import re
from dataclasses import dataclass

from mockymock.debug.gdb_session import GdbSession, evaluate
from mockymock.debug.line_map import LineMap

_LINE_DIRECTIVE_RE = re.compile(r'^#line (\d+) "([^"]*\.cbl)"')

# GnuCOBOL's own bound on simultaneous PERFORM nesting (frame_stack[255]),
# see the generated .c.l.h header -- a safe iteration cap so a corrupted
# frame_ptr can never spin this loop forever.
_MAX_FRAMES = 255


@dataclass
class CallFrame:
    paragraph: str | None
    section: str | None
    original_line: int


def build_generated_c_line_map(generated_c_text: str) -> list[tuple[int, int]]:
    """Sorted (generated-C line, instrumented .cbl line) pairs, one per
    `#line N "<file>.cbl"` directive in the compiled `.c` file (the
    directives pointing at the compiler's own `fixture.c`-style
    self-references are not included -- only the ones naming the COBOL
    source). See module docstring for why the NEAREST PRECEDING entry,
    not an exact match, is the right lookup for a return address."""
    entries: list[tuple[int, int]] = []
    for line_number, line in enumerate(generated_c_text.splitlines(), start=1):
        match = _LINE_DIRECTIVE_RE.match(line)
        if match:
            entries.append((line_number, int(match.group(1))))
    entries.sort()
    return entries


def _nearest_preceding_cobol_line(
    entries: list[tuple[int, int]], generated_c_line: int
) -> int | None:
    index = bisect.bisect_right(entries, (generated_c_line, float("inf"))) - 1
    if index < 0:
        return None
    return entries[index][1]


class ParagraphIndex:
    """Line -> enclosing paragraph/section name, built once per debug
    session from the parsed AST (not from splicer/source_map.py's
    ScopeMap, which tracks statement-nesting boundaries for a different
    purpose -- splice-safety -- and carries scope WORDS, not paragraph
    NAMES; see the CLI implementation plan's Task 5 note to verify reuse
    candidates before assuming their shape)."""

    def __init__(
        self,
        paragraph_starts: list[tuple[int, str]],
        section_starts: list[tuple[int, str]],
    ) -> None:
        self._paragraph_starts = sorted(paragraph_starts)
        self._section_starts = sorted(section_starts)

    @classmethod
    def build(cls, program) -> "ParagraphIndex":
        procedure = program.get_division("PROCEDURE")
        paragraph_starts: list[tuple[int, str]] = []
        section_starts: list[tuple[int, str]] = []
        if procedure is None:
            return cls([], [])
        for paragraph in procedure.paragraphs:
            if paragraph.paragraph_name.strip("."):
                paragraph_starts.append(
                    (paragraph.location.line, paragraph.paragraph_name)
                )
        for section in procedure._sections.values():
            if (section.section_name or "").strip("."):
                section_starts.append((section.location.line, section.section_name))
            for paragraph in section.paragraphs:
                if paragraph.paragraph_name.strip("."):
                    paragraph_starts.append(
                        (paragraph.location.line, paragraph.paragraph_name)
                    )
        return cls(paragraph_starts, section_starts)

    def resolve(self, original_line: int) -> tuple[str | None, str | None]:
        paragraph = self._nearest(self._paragraph_starts, original_line)
        section = self._nearest(self._section_starts, original_line)
        return paragraph, section

    @staticmethod
    def _nearest(starts: list[tuple[int, str]], line: int) -> str | None:
        index = bisect.bisect_right(starts, (line, chr(0x10FFFF))) - 1
        if index < 0:
            return None
        return starts[index][1]


def _resolve_frame(
    file: str,
    generated_line: int,
    line_map: LineMap,
    generated_c_lines: list[tuple[int, int]],
    paragraph_index: ParagraphIndex,
) -> CallFrame | None:
    """Resolves a (file, line) pair -- from either the current stopped
    frame or a walked return address -- to a CallFrame. `file` may be the
    `.cbl` (instrumented) source directly, or the generated `.c` file."""
    if file.endswith(".cbl"):
        instrumented_line = generated_line
    else:
        instrumented_line = _nearest_preceding_cobol_line(
            generated_c_lines, generated_line
        )
        if instrumented_line is None:
            return None
    original_line = line_map.to_original(instrumented_line)
    if original_line is None:
        return None
    paragraph, section = paragraph_index.resolve(original_line)
    return CallFrame(paragraph=paragraph, section=section, original_line=original_line)


def synthesize_stack(
    session: GdbSession,
    line_map: LineMap,
    generated_c_lines: list[tuple[int, int]],
    paragraph_index: ParagraphIndex,
    current_file: str,
    current_line: int,
) -> list[CallFrame]:
    """Frame 0 is the current stopped position (from the ordinary
    line-mapped breakpoint/step position -- NOT from `frame_stack`, which
    only holds RETURN addresses of callers, per the design doc). Frames
    1..N are the enclosing PERFORM callers, innermost first, walked from
    `frame_stack` in reverse (most-recently-pushed first)."""
    frames: list[CallFrame] = []
    current = _resolve_frame(
        current_file, current_line, line_map, generated_c_lines, paragraph_index
    )
    if current is not None:
        frames.append(current)

    depth_text = evaluate(session, "frame_ptr-frame_stack")
    depth = int(depth_text)
    depth = max(0, min(depth, _MAX_FRAMES))

    # frame_stack[0] is a sentinel, never a real caller: GnuCOBOL
    # initializes it to {perform_through: 0, return_address_ptr: &&P_cgerror}
    # at function entry, before any PERFORM runs, and increments frame_ptr
    # BEFORE writing the real return address for each new PERFORM level
    # (confirmed empirically -- resolving frame_stack[0] here landed on the
    # P_cgerror error label, not any real call site). The real, populated
    # caller frames are frame_stack[1..depth], innermost first.
    for i in range(depth, 0, -1):
        address = int(evaluate(session, f"(long)frame_stack[{i}].return_address_ptr"))
        location = session.resolve_address(address)
        frame = _resolve_frame(
            location.get("file", ""),
            int(location["line"]),
            line_map,
            generated_c_lines,
            paragraph_index,
        )
        if frame is not None:
            frames.append(frame)

    return frames
