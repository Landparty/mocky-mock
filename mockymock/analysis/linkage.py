"""Detects whether a program's ENTRY/LINKAGE-SECTION shape qualifies for the
neutralization transform in `mockymock.splicer.linkage` (comment out the
named ENTRY statement(s) and the LINKAGE SECTION header line, letting the
declared items fall into WORKING-STORAGE) -- see
docs/2026-07-08-ims-linkage-support-design.md.

Detection here is a pure, side-effect-free query over the AST: `linkage_plan`
answers "is there anything to do" (None when the program has no ENTRY
statements or an empty/absent LINKAGE SECTION -- an ordinary CALL-only
program, untouched by this feature). It does NOT decide whether the shape is
*safe* to neutralize -- that's `refusal.check_linkage_layout`'s job, which
calls `linkage_plan` and applies the guardrails documented in the design.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class LinkagePlan:
    """Everything the guardrail checks and the splicer transform need.

    `header_line` is 1-indexed into the NORMALIZED free-form text (the same
    text `mockymock.splicer` edits) -- derived as one line before the first
    LINKAGE SECTION data item's own location, since cobolparser does not
    reliably report a DATA-DIVISION section's own header location (verified
    empirically: every section under one DATA DIVISION reports that
    DIVISION's own line, not its own header line).
    """

    entry_statements: list
    linkage_items: list
    header_line: int


def linkage_plan(program) -> LinkagePlan | None:
    """None when there is nothing for this feature to do: no ENTRY
    statement anywhere in the program, or LINKAGE SECTION absent/empty.
    """
    entries = program.get_entry_statements()
    if not entries:
        return None
    data = program.get_division("DATA")
    if data is None:
        return None
    linkage_section = data._sections.get("LINKAGE")
    if linkage_section is None or not linkage_section.data_items:
        return None
    header_line = linkage_section.data_items[0].location.line - 1
    return LinkagePlan(
        entry_statements=entries,
        linkage_items=linkage_section.data_items,
        header_line=header_line,
    )
