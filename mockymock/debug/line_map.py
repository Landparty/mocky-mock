"""Bidirectional original <-> instrumented line mapping for the debugger.

`report.coverage.build_original_line_map` already solves "instrumented line
-> original line, dropping splicer-inserted lines" one-directional, for
after-the-fact reports (coverage, trace). A debug session needs the same
mapping live and in the reverse direction too: DAP gives an original `.cbl`
line when setting a breakpoint, which must resolve to the instrumented line
before gdb can use it -- gdb only ever knows about the spliced/instrumented
file cobc actually compiled (confirmed empirically, see
docs/2026-07-22-dap-debugger-design.md's Empirical basis, question 2).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from mockymock.report.coverage import build_original_line_map


@dataclass
class LineMap:
    """Built once per debug session from the same three line lists
    `_cmd_run` already assembles for trace/coverage: instrumented,
    normalized (pre-splice), and original (raw .cbl)."""

    _to_original: dict[int, int] = field(default_factory=dict)
    _to_instrumented: dict[int, int] = field(default_factory=dict)

    @classmethod
    def build(
        cls,
        instrumented_lines: list[str],
        normalized_lines: list[str],
        original_lines: list[str],
    ) -> LineMap:
        to_original = build_original_line_map(
            instrumented_lines, normalized_lines, original_lines
        )
        # Invert once at construction. The forward map is built from a
        # difflib alignment over disjoint matching blocks, so it is 1:1 in
        # practice; if two instrumented lines ever mapped to the same
        # original line, the first one built wins (arbitrary but stable).
        to_instrumented: dict[int, int] = {}
        for instrumented, original in to_original.items():
            to_instrumented.setdefault(original, instrumented)
        return cls(_to_original=to_original, _to_instrumented=to_instrumented)

    def to_original(self, instrumented_line: int) -> int | None:
        return self._to_original.get(instrumented_line)

    def to_instrumented(self, original_line: int) -> int | None:
        return self._to_instrumented.get(original_line)

    def reject_reason(self, original_line: int) -> str | None:
        """None if `original_line` has an instrumented counterpart (a
        breakpoint can be set there); otherwise a message explaining why
        not. v1 does not relocate to the nearest valid statement -- it
        rejects and lets the caller pick another line. See design doc's
        Line mapping section for why a relocation feature (reusing
        splicer/source_map.py's span/boundary data) is a reasonable v2,
        not required here."""
        if original_line in self._to_instrumented:
            return None
        return (
            f"line {original_line} has no corresponding executable location "
            f"in the compiled program (it may be a comment, a blank line, a "
            f"declaration, or a line the splicer replaced)"
        )
