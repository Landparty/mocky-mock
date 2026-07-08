"""Neutralizes an ENTRY-bound LINKAGE SECTION so a program's default entry
gets real, addressable storage instead of unbound LINKAGE memory -- see
docs/2026-07-08-ims-linkage-support-design.md.

mockymock's driver only ever `PERFORM`s a program's default entry directly,
in the same compilation unit; it never `CALL`s the program through a named
`ENTRY` statement. A LINKAGE SECTION bound only through such an ENTRY's
`USING` clause is therefore never allocated, and any reference to it from
code reachable off the default entry dereferences unbound memory (verified
against the real GnuCOBOL toolchain: SIGSEGV, exit 139).

The fix, also verified against the real toolchain: comment out the ENTRY
statement(s) and the `LINKAGE SECTION.` header line, leaving the LINKAGE
data items physically in place. With no section header separating them from
whatever precedes them, GnuCOBOL folds them into the preceding
`WORKING-STORAGE SECTION` -- real, statically-allocated, zero/space/VALUE-
defaulted storage, no data relocation needed.

`refusal.check_linkage_layout` gates this: it must return `[]` for a program
before `neutralize` is applied. Both `neutralize` and `extra_reset_lines`
assume that gate already passed -- they do not re-run the guardrails, only
the caller-independent line-location work.
"""

from __future__ import annotations

from mockymock.analysis.linkage import LinkagePlan
from mockymock.splicer.reset import reset_lines_for_items
from mockymock.splicer.source_map import collect_boundaries, statement_span
from mockymock.splicer.stub_writer import comment_and_replace


def neutralize(lines: list[str], program, plan: LinkagePlan) -> list[str]:
    """Comment out every ENTRY statement's line span and the LINKAGE
    SECTION header line. Pure text edit: `comment_and_replace` is always
    called with an empty replacement, so no line is inserted or removed --
    every other line's number is unaffected, which is why this can safely
    run before or after any other line-based splice in the pipeline."""
    last_line = len(lines)
    entry_lines = {e.location.line for e in plan.entry_statements}
    boundaries = sorted(set(collect_boundaries(program)) | entry_lines)

    for entry in plan.entry_statements:
        start, end = statement_span(entry, boundaries, last_line)
        lines = comment_and_replace(lines, start, end, [])

    lines = comment_and_replace(lines, plan.header_line, plan.header_line, [])
    return lines


def extra_reset_lines(plan: LinkagePlan) -> list[str]:
    """Reset lines for the LINKAGE items `neutralize` folded into
    WORKING-STORAGE -- `reset_move_lines` walks the AST's WORKING-STORAGE
    section directly and would never see them (the transform above edits
    text only, not the AST each item still belongs to)."""
    return reset_lines_for_items(plan.linkage_items)
