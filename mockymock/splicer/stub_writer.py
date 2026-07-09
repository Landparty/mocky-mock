"""Comments out a statement's source span and splices replacement lines in."""

from __future__ import annotations


def comment_and_replace(
    lines: list[str], start_line: int, end_line: int, replacement: list[str]
) -> list[str]:
    """Return a NEW list: lines [start_line, end_line] (1-indexed, inclusive)
    commented out in place, with `replacement` inserted immediately after
    the (now-commented) span.
    """
    result = list(lines)
    for line_no in range(start_line, end_line + 1):
        idx = line_no - 1
        if 0 <= idx < len(result) and result[idx].strip():
            result[idx] = "      *> " + result[idx]
    insert_at = end_line  # 0-indexed position right after the span
    return result[:insert_at] + replacement + result[insert_at:]


def insert_lines_after(
    lines: list[str], line_number: int, new_lines: list[str]
) -> list[str]:
    """Return a NEW list with `new_lines` inserted immediately after
    `line_number` (1-indexed). Unlike comment_and_replace, this NEVER
    touches the original line(s) -- used when an existing statement must
    stay exactly as written and something new just needs to run right
    after it (see docs/2026-07-08-goback-stop-run-support-design.md, the
    intermediate-PERFORM early-exit flag-check instrumentation)."""
    return lines[:line_number] + new_lines + lines[line_number:]
