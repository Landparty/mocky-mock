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

import re
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


# `SET ADDRESS OF <item> TO <pointer>` -- the one statement that stops being
# legal once `splicer.linkage.neutralize` has folded <item> out of LINKAGE and
# into WORKING-STORAGE (GnuCOBOL: "cannot change address of 'X', which is not
# BASED or a LINKAGE item"). Detected textually rather than off the AST because
# cobolparser's `SetStatement` drops the target-side ADDRESS OF entirely --
# `SET ADDRESS OF X TO Y` and `SET X TO Y` both arrive as `targets=["X"]`, so
# the AST cannot tell the two apart. Verified against cobolparser 1.8.0.
#
# Not a plain `\b`: COBOL identifiers may contain hyphens, which are not `\w`
# characters, so `\bLK-DIB\b` would false-match inside `WS-LK-DIB-SAVE` (same
# reasoning as `analysis.cics_eib`'s name matching).
_NAME_CHARS = r"A-Za-z0-9$@#-"
_ADDRESS_OF_RE = re.compile(
    rf"(?<![{_NAME_CHARS}])ADDRESS\s+OF\s+([{_NAME_CHARS}]+)", re.IGNORECASE
)
# An `ADDRESS OF` whose operand is not on the same line: the span this feature
# rewrites would cross a line boundary, which `stub_writer.replace_columns`
# cannot express. Fail closed rather than leave an illegal statement behind.
_DANGLING_ADDRESS_OF_RE = re.compile(
    rf"(?<![{_NAME_CHARS}])ADDRESS(\s+OF)?\s*$", re.IGNORECASE
)
_SET_RE = re.compile(rf"(?<![{_NAME_CHARS}])SET(?![{_NAME_CHARS}])", re.IGNORECASE)
_TO_RE = re.compile(rf"(?<![{_NAME_CHARS}])TO(?![{_NAME_CHARS}])", re.IGNORECASE)


@dataclass(frozen=True)
class AddressOfSite:
    """One `ADDRESS OF <folded item>` occurrence on the RECEIVING side of a
    SET, with the exact half-open column span to overwrite.

    `line` is 1-indexed into the same normalized free-form text
    `splicer.linkage.neutralize` edits; `start_column`/`end_column` are
    0-based and half-open, the convention `stub_writer.replace_columns` takes.
    """

    line: int
    start_column: int
    end_column: int
    item_name: str


def address_of_sites(
    lines: list[str], plan: LinkagePlan
) -> tuple[list[AddressOfSite], list[str]]:
    """Every `SET ADDRESS OF <folded item>` receiving-side occurrence, plus a
    list of human-readable reasons for any occurrence this cannot classify.

    Value-side occurrences (`SET <ptr> TO ADDRESS OF <folded item>`) are
    deliberately NOT returned: taking the address of a WORKING-STORAGE item is
    legal COBOL and stays correct after the fold. Only the receiving side --
    which asks the runtime to *rebind* the item's storage -- becomes illegal.

    Classification is per line: for each match, the nearest preceding `SET`
    keyword on that line wins, and an intervening `TO` means the occurrence is
    on the value side. An occurrence with no `SET` before it on its own line
    (a continued target list) is reported as a problem rather than guessed at.
    """
    folded = {
        item.name.upper() for item in plan.linkage_items if getattr(item, "name", None)
    }
    sites: list[AddressOfSite] = []
    problems: list[str] = []
    for index, text in enumerate(lines, start=1):
        for match in _ADDRESS_OF_RE.finditer(text):
            name = match.group(1)
            if name.upper() not in folded:
                continue
            prefix = text[: match.start()]
            set_positions = [m.start() for m in _SET_RE.finditer(prefix)]
            if not set_positions:
                problems.append(
                    f"line {index}: `ADDRESS OF {name}` has no SET keyword on "
                    f"its own line ({text.strip()!r}), so it cannot be "
                    "classified as a receiving or a value operand"
                )
                continue
            to_positions = [m.start() for m in _TO_RE.finditer(prefix)]
            if to_positions and to_positions[-1] > set_positions[-1]:
                continue  # value side: `SET <ptr> TO ADDRESS OF <item>`, legal
            sites.append(
                AddressOfSite(
                    line=index,
                    start_column=match.start(),
                    end_column=match.end(),
                    item_name=name,
                )
            )
        if _DANGLING_ADDRESS_OF_RE.search(text):
            problems.append(
                f"line {index}: `ADDRESS OF` is continued onto the next line "
                f"({text.strip()!r}) -- its operand cannot be rewritten "
                "within one line"
            )
    return sites, problems
