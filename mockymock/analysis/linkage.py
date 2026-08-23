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
    text `mockymock.splicer` edits) -- taken directly from the LINKAGE
    SECTION's own `CobolSection.location`. cobolparser used to report every
    DATA DIVISION section at its parent division's location rather than its
    own header token; that was fixed upstream (cobolparser 2026-07-09,
    "Section/Paragraph Location Tracking"), so `location.line` is now
    reliable. Do NOT go back to deriving this from the first data item's
    location minus one -- that assumption silently breaks whenever anything
    (a comment block, blank lines) separates the LINKAGE SECTION header from
    its first 01-level item, which is common in real IMS PCB-mask linkage
    sections and was measured to drift 12-14 lines on real-world programs.
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
    if linkage_section.location is None:
        return None
    header_line = linkage_section.location.line
    return LinkagePlan(
        entry_statements=entries,
        linkage_items=linkage_section.data_items,
        header_line=header_line,
    )
