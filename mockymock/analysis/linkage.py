"""Detects whether a program's LINKAGE-SECTION shape qualifies for the
neutralization transform in `mockymock.splicer.linkage` (comment out any
named ENTRY statement(s) and the LINKAGE SECTION header line, letting the
declared items fall into WORKING-STORAGE) -- see
docs/2026-07-08-ims-linkage-support-design.md and, for the no-ENTRY
generalization below,
docs/2026-08-27-cics-eib-linkage-support-design.md.

Detection here is a pure, side-effect-free query over the AST: `linkage_plan`
answers "is there anything to do" (None for an empty/absent LINKAGE SECTION
-- an ordinary CALL-only program, untouched by this feature). It does NOT
decide whether the shape is *safe* to neutralize -- that's
`refusal.check_linkage_layout`'s job, which calls `linkage_plan` and applies
the guardrails documented in the design.

`entry_statements` may be empty: originally this only fired when the
program had at least one named `ENTRY` (the IMS DL/I `ENTRY 'DLITCBL'`
idiom this was first built for). Generalized 2026-08-27 to any non-empty
LINKAGE SECTION regardless of ENTRY count -- the IMS design doc's own
empirical finding 2 already proved the storage is unbound (and crashes)
"regardless of whether anything declares USING against it", i.e. the risk
never depended on ENTRY being present, only on mockymock's PERFORM-based
driver never binding the LINKAGE SECTION either way. This covers the
idiomatic CICS `LINKAGE SECTION. 01 DFHCOMMAREA. ... PROCEDURE DIVISION.`
shape (no ENTRY at all) for free -- see the CICS design doc's Part 1.
`neutralize`'s ENTRY-commenting loop was already a no-op over an empty
list, so only this detection gate needed to change.
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
    """None when there is nothing for this feature to do: LINKAGE SECTION
    absent/empty. `entries` may legitimately be empty -- see module
    docstring's 2026-08-27 generalization note.
    """
    entries = program.get_entry_statements()
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
