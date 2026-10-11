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

from mockymock.analysis.linkage import (
    AddressOfSite,
    LinkagePlan,
    procedure_header_clause_spans,
)
from mockymock.splicer.reset import reset_lines_for_items
from mockymock.splicer.source_map import collect_boundaries, statement_span
from mockymock.splicer.stub_writer import comment_and_replace, replace_columns


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
        start, end = statement_span(entry, boundaries, last_line, lines)
        lines = comment_and_replace(lines, start, end, [])

    lines = comment_and_replace(lines, plan.header_line, plan.header_line, [])
    # The default entry's USING/RETURNING clause names items that now live
    # in WORKING-STORAGE, which cobc rejects ("not in LINKAGE SECTION"):
    # blank it, width-preserving like every edit here. The gate already
    # refused a header whose clause cannot be delimited.
    spans = procedure_header_clause_spans(lines, program) or []
    for index, (line_number, start, end) in enumerate(spans):
        # The closing period moves to where the clause began, so the header
        # is complete on its first line (see procedure_header_clause_spans).
        lines = replace_columns(
            lines, line_number, start, end, "." if index == 0 else ""
        )
    return lines


def extra_reset_lines(plan: LinkagePlan) -> list[str]:
    """Reset lines for the LINKAGE items `neutralize` folded into
    WORKING-STORAGE -- `reset_move_lines` walks the AST's WORKING-STORAGE
    section directly and would never see them (the transform above edits
    text only, not the AST each item still belongs to)."""
    return reset_lines_for_items(plan.linkage_items)


# Where a folded item's `SET ADDRESS OF` target is redirected to. Chosen to be
# no wider than the narrowest span it ever replaces: `ADDRESS OF X` is 12
# characters for a one-character data name, and so is this, so the rewrite
# always fits without shortening the line (see `redirect_address_of`).
DISCARD_POINTER = "UT-ADDR-SINK"


def redirect_address_of(lines: list[str], sites: list[AddressOfSite]) -> list[str]:
    """Rewrite every receiving-side `ADDRESS OF <folded item>` to
    `DISCARD_POINTER`, space-padded to the identical width.

    `neutralize` above gives the LINKAGE items real WORKING-STORAGE storage,
    which is exactly what makes `SET ADDRESS OF` on them illegal afterwards:
    GnuCOBOL rejects rebinding an item that is "not BASED or a LINKAGE item".
    Marking them BASED instead would restore the statement's legality by
    taking the storage away again -- the precise crash this whole transform
    exists to prevent -- so the statement, not the storage, is what gives.
    Redirecting the rebind into a scratch pointer discards it while leaving
    the SET itself executing: no control flow changes, no sentence structure
    changes, and (unlike commenting the statement out) a sibling statement
    sharing the line is untouched.

    Column-scoped and width-preserving via `replace_columns`, so like
    `neutralize` this shifts no line and no column that any later
    `SourceLocation`-driven step depends on -- both the receiving item's own
    references and the pointer being read stay exactly where they were.

    Applied right-to-left within a line so that two sites on one line cannot
    invalidate each other's columns.
    """
    for site in sorted(sites, key=lambda s: (s.line, s.start_column), reverse=True):
        lines = replace_columns(
            lines, site.line, site.start_column, site.end_column, DISCARD_POINTER
        )
    return lines


def extra_working_storage_lines(sites: list[AddressOfSite]) -> list[str]:
    """The `DISCARD_POINTER` declaration, or nothing when no site needed it.

    Reaches the instrumented source through `driver.build_driver`'s
    `extra_working_storage_lines` -- the one insertion point already proven
    safe, same route `splicer.cics_eib`'s synthesized EIB block takes. It
    needs no reset line between test cases: nothing ever reads it.
    """
    if not sites:
        return []
    return [f"01  {DISCARD_POINTER}           USAGE POINTER."]
