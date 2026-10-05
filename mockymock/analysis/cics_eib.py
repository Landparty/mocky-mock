"""Detects whether a program references the CICS Execute Interface Block
(`DFHEIBLK`) or any of its named fields (`EIBCALEN`, `EIBAID`, ...) without
declaring them anywhere itself -- see
docs/2026-08-27-cics-eib-linkage-support-design.md.

A real CICS translator inserts `DFHEIBLK`'s LINKAGE SECTION layout ahead of
`cobc`/the native compiler ever seeing the source; mockymock never runs a
CICS translator (`splicer.injector.build_exec_trap` already avoids needing
one for `EXEC CICS` command syntax itself, see the design doc's problem
statement), so a program referencing an EIB field from ordinary COBOL
outside any `EXEC CICS` block would otherwise fail `cobc` compilation with
an undeclared-data-name error.

Detection here is a pure, side-effect-free query, mirroring
`analysis.linkage.linkage_plan`'s split from its own guardrail check:
`cics_eib_plan` answers "is there anything to do" (`None` when the program
never references any EIB name, or when it already declares its own copy --
an ordinary non-CICS program, or a program that hand-declares/COPYs
`DFHEIBLK` itself, either way untouched by this feature). It does not decide
whether OTHER CICS constructs in the program are safe (`DFHRESP`/`DFHVALUE`
macro calls, an undeclared `DFHCOMMAREA`) -- that is
`refusal.check_cics_eib_layout`'s job.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from cobolparser.analysis.unused_variables import collect_declared_items

DFHEIBLK_NAME = "DFHEIBLK"

# The standard IBM CICS Execute Interface Block field names, unchanged
# across CICS TS releases. See the design doc's "The DFHEIBLK layout"
# section for the full PICTURE clauses -- this module only needs the names,
# for reference detection.
EIB_FIELD_NAMES: frozenset[str] = frozenset(
    {
        "EIBTIME",
        "EIBDATE",
        "EIBTRNID",
        "EIBTASKN",
        "EIBTRMID",
        "EIBCPOSN",
        "EIBCALEN",
        "EIBAID",
        "EIBFN",
        "EIBRCODE",
        "EIBDS",
        "EIBREQID",
        "EIBRSRCE",
        "EIBSYNC",
        "EIBFREE",
        "EIBRECV",
        "EIBATT",
        "EIBEOC",
        "EIBFMH",
        "EIBCOMPL",
        "EIBSIG",
        "EIBCONF",
        "EIBERR",
        "EIBERRCD",
        "EIBSYNRB",
        "EIBNODAT",
        "EIBRESP",
        "EIBRESP2",
        "EIBRLDBK",
    }
)

_EIB_NAMES = EIB_FIELD_NAMES | {DFHEIBLK_NAME}
# Plain `\b...\b` is wrong here: COBOL identifiers may contain hyphens,
# which are not `\w` characters, so `\bEIBCALEN\b` would false-match inside
# an unrelated hyphenated name like `WS-EIBCALEN-SAVED` (a `\b` boundary
# exists at the transition between the non-word `-` and the word-char `E`).
# Use an explicit lookaround against the full COBOL identifier character
# class (letters/digits/hyphen) instead, and match case-insensitively --
# COBOL identifiers are themselves case-insensitive, so a lowercase or
# mixed-case source reference is exactly as real a reference as an
# uppercase one.
# One combined alternation rather than 29 separate patterns: each pattern
# starts with a lookbehind, which defeats `re`'s literal-prefix scan
# optimization, so every name cost a full pass over the program text --
# measured at 0.73s of a 2.5s static-check pass on a 29k-line program, ~15x
# `refusal.check_cics_eib_layout`'s two-pattern equivalent. Longest name
# first so a prefix never shadows a longer sibling (EIBRESP vs EIBRESP2);
# occurrences cannot overlap, since the lookarounds delimit every match
# with a non-identifier character on both sides.
_EIB_NAME_RE = re.compile(
    "(?<![A-Za-z0-9-])(?:"
    + "|".join(sorted((re.escape(n) for n in _EIB_NAMES), key=len, reverse=True))
    + ")(?![A-Za-z0-9-])",
    re.IGNORECASE,
)


# The EXEC DLI interface block (DIB). Like the EIB, the DL/I translator
# normally supplies it, so a program testing DIBSTAT after an EXEC DLI call
# did not compile under mockymock -- behind a clean lint (issue #145).
DLIDIB_NAME = "DLIDIB"
DIB_FIELD_NAMES: frozenset[str] = frozenset(
    {
        "DIBVER",
        "DIBSTAT",
        "DIBSEGM",
        "DIBSEGLV",
        "DIBKFBL",
        "DIBDBDNM",
        "DIBDBORG",
    }
)
_DIB_NAMES = DIB_FIELD_NAMES | {DLIDIB_NAME}
_DIB_NAME_RE = re.compile(
    "(?<![A-Za-z0-9-])(?:"
    + "|".join(sorted((re.escape(n) for n in _DIB_NAMES), key=len, reverse=True))
    + ")(?![A-Za-z0-9-])",
    re.IGNORECASE,
)


@dataclass
class CicsEibPlan:
    """Everything `splicer.cics_eib`'s synthesis functions need.

    `referenced_names` is sorted, transparency-message-only: synthesis
    always emits the full fixed `DFHEIBLK` layout regardless of which
    specific fields matched (see module docstring on the design doc's
    reasoning -- a real translator always inserts the whole block).
    """

    referenced_names: list[str]
    #: DL/I interface block names referenced and undeclared (issue #145);
    #: empty when the program needs no DIB. Synthesized the same way, as a
    #: `01 DLIDIB.` group.
    dib_names: list[str] = field(default_factory=list)


def cics_eib_plan(program, lines: list[str]) -> CicsEibPlan | None:
    """`None` when there is nothing for this feature to do: no EIB name
    referenced anywhere in `lines`, or every referenced name is already
    declared somewhere in the program's own DATA DIVISION (a hand-declared
    or `COPY DFHEIBLK`-expanded copy -- synthesizing a second one would be a
    duplicate-data-name compile error, and the program already has real
    storage for it).
    """
    text = "\n".join(lines)
    referenced = sorted({m.group(0).upper() for m in _EIB_NAME_RE.finditer(text)})
    dib = sorted({m.group(0).upper() for m in _DIB_NAME_RE.finditer(text)})
    if not referenced and not dib:
        return None

    declared = {item.name.upper() for item in collect_declared_items(program)}
    if declared & set(referenced):
        referenced = []
    if declared & _DIB_NAMES:
        dib = []
    if not referenced and not dib:
        return None

    return CicsEibPlan(referenced_names=referenced, dib_names=dib)
