"""Synthesizes a `01 DFHEIBLK.` WORKING-STORAGE group for a program that
references CICS EIB fields without declaring them -- see
docs/2026-08-27-cics-eib-linkage-support-design.md.

Unlike `splicer.linkage.neutralize` (comment-only, so line-count-preserving
and safe to run early in the pipeline), this module's output *inserts* new
physical lines. Every `SourceLocation`-driven step downstream of
`normalize_fixed_format` (`mock_surface.analyze`, `collect_scope_map`,
`splice_program`'s boundary spans, ...) would silently misalign if this ran
before them -- so its output is never spliced into `lines` directly. Instead
`working_storage_lines`'s output is merged into `DriverArtifact.working_
storage_lines` (via `build_driver`'s `extra_working_storage_lines` param)
right before `_insert_driver`, the one point already proven safe for adding
new WORKING-STORAGE: the driver's own bookkeeping fields (`UT-CURRENT-CASE`
etc.) are inserted exactly the same way, at the same point, today.

`refusal.check_cics_eib_layout` guards the two situations this module
cannot safely handle (`DFHRESP`/`DFHVALUE` macro calls, an undeclared
`DFHCOMMAREA`) -- unlike `linkage.py`/`check_linkage_layout`, there is no
gate this module's *own* transform needs: `analysis.cics_eib.cics_eib_plan`
already only returns a plan when synthesis is unambiguously safe (no name
collision with an existing declaration), so there is nothing left to refuse
before applying it.
"""

from __future__ import annotations

from mockymock.analysis.cics_eib import CicsEibPlan

# The standard IBM CICS Execute Interface Block layout, unchanged across
# CICS TS releases. The two reserved slots exist for byte-alignment (real
# EIB byte layout) but are never referenced by application code and their
# exact internal names are not asserted here -- declared FILLER, which is
# both honest about that and, being unaddressable by definition,
# behaviorally identical either way. See the design doc's "The DFHEIBLK
# layout" section.
_DFHEIBLK_LINES = [
    "01  DFHEIBLK.",
    "    05  EIBTIME      PIC S9(7) COMP-3.",
    "    05  EIBDATE      PIC S9(7) COMP-3.",
    "    05  EIBTRNID     PIC X(4).",
    "    05  EIBTASKN     PIC S9(7) COMP-3.",
    "    05  EIBTRMID     PIC X(4).",
    "    05  FILLER       PIC S9(4) COMP.",
    "    05  EIBCPOSN     PIC S9(4) COMP.",
    "    05  EIBCALEN     PIC S9(4) COMP.",
    "    05  EIBAID       PIC X(1).",
    "    05  EIBFN        PIC X(2).",
    "    05  EIBRCODE     PIC X(6).",
    "    05  EIBDS        PIC X(8).",
    "    05  EIBREQID     PIC X(8).",
    "    05  EIBRSRCE     PIC X(8).",
    "    05  EIBSYNC      PIC X(1).",
    "    05  EIBFREE      PIC X(1).",
    "    05  EIBRECV      PIC X(1).",
    "    05  FILLER       PIC X(1).",
    "    05  EIBATT       PIC X(1).",
    "    05  EIBEOC       PIC X(1).",
    "    05  EIBFMH       PIC X(1).",
    "    05  EIBCOMPL     PIC X(1).",
    "    05  EIBSIG       PIC X(1).",
    "    05  EIBCONF      PIC X(1).",
    "    05  EIBERR       PIC X(1).",
    "    05  EIBERRCD     PIC X(4).",
    "    05  EIBSYNRB     PIC X(1).",
    "    05  EIBNODAT     PIC X(1).",
    "    05  EIBRESP      PIC S9(8) COMP.",
    "    05  EIBRESP2     PIC S9(8) COMP.",
    "    05  EIBRLDBK     PIC X(1).",
]


def working_storage_lines(plan: CicsEibPlan) -> list[str]:
    """The `01 DFHEIBLK.` group's WORKING-STORAGE text, unindented (callers
    add whatever column-position prefix their own insertion point needs --
    matching how `driver.build_driver`'s own bookkeeping fields are
    generated and later prefixed by `cli.main._insert_driver`).

    `plan` is accepted, not just a bare no-arg call, so a future revision
    that emits a narrower subset based on `plan.referenced_names` stays a
    signature-compatible change -- today's synthesis is always the full
    fixed layout regardless of which fields were referenced (see module
    docstring).
    """
    del plan  # unused today; see docstring
    return list(_DFHEIBLK_LINES)


def reset_lines(plan: CicsEibPlan) -> list[str]:
    """Reset line for the synthesized `DFHEIBLK` group -- appended to
    `reset.reset_move_lines`'s output the same way `splicer.linkage.
    extra_reset_lines` already is. A single `INITIALIZE` is correct and
    sufficient: `DFHEIBLK` carries no `VALUE` clauses, so `reset.py`'s own
    rule for a VALUE-less group applies (zero COMP/COMP-3 fields, space-fill
    alphanumeric ones) -- which happens to already be the realistic
    "no COMMAREA passed, first invocation" default (`EIBCALEN = 0`)."""
    del plan  # unused today; see docstring
    return ["INITIALIZE DFHEIBLK"]
