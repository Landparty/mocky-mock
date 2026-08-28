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


def replace_columns(
    lines: list[str],
    line_number: int,
    start_column: int,
    end_column: int,
    replacement: str,
) -> list[str]:
    """Return a NEW list with columns [start_column, end_column) (0-based,
    half-open) of `lines[line_number - 1]` overwritten by `replacement`,
    space-padded to the original width.

    Padding rather than substituting is the whole point: every downstream
    step indexes the source by `SourceLocation` line AND column, so an
    edit that shortened a line would silently move every statement after
    it on that line.

    The span is validated rather than trusted -- `0 <= start_column <=
    end_column <= len(line)`, and `replacement` no wider than the span.
    Python slicing tolerates out-of-range indices, so an unchecked span
    past either end of the line would quietly rewrite it to a different
    length: exactly the guarantee this function exists to make, broken
    silently. Raises `ValueError` instead."""
    if not 0 <= line_number - 1 < len(lines):
        raise ValueError(f"line {line_number} is outside the source")
    text = lines[line_number - 1]
    width = end_column - start_column
    if not 0 <= start_column <= end_column <= len(text):
        raise ValueError(
            f"columns [{start_column}, {end_column}) are outside line "
            f"{line_number} (length {len(text)})"
        )
    if len(replacement) > width:
        raise ValueError(
            f"cannot fit {replacement!r} into columns "
            f"[{start_column}, {end_column}) of line {line_number}"
        )
    result = list(lines)
    result[line_number - 1] = (
        text[:start_column] + replacement.ljust(width) + text[end_column:]
    )
    return result


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
