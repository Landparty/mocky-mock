"""Generates MOVE statements that reset WORKING-STORAGE between test cases.

Necessary because mockymock compiles one binary per TESTSUITE (see Global
Constraints): without an explicit reset, case N's leftover state leaks
into case N+1. Resets to the item's declared VALUE clause if present,
otherwise to COBOL's conventional type default (ZERO for numeric --
including numeric-edited PICs like ZZZ9, which reject MOVE SPACES --
SPACES for alphanumeric) -- a deliberate divergence from "truly undefined"
COBOL memory, in exchange for deterministic, order-independent tests.

PICTURE-less usage-typed items get usage-appropriate resets instead of an
illegal `MOVE SPACES`: COMP-1/COMP-2 floats take `MOVE 0`, POINTER-family
items take `SET ... TO NULL`. Items this module cannot reset legally are
SKIPPED rather than given illegal COBOL (documented fidelity limits, see
.okf/splicer.md): USAGE INDEX items, PICTURE-less items of unrecognized
usage. A group with a VALUE clause inside a table (an OCCURS item) is
reset with `INITIALIZE <group> ALL TO VALUE THEN TO DEFAULT`, which
restores every occurrence's VALUE without subscripted MOVEs. Top-level REDEFINES items are skipped on purpose: their
storage is the redefined item's, which is reset (and its VALUE restored)
by its own line -- a second reset through the redefining view would
overwrite it.
"""

from __future__ import annotations

import re

from mockymock.splicer.io_copy import longest_record_per_file

_REPEAT_GROUP_RE = re.compile(r"\(\d+\)")

# A cobolparser `value_clause` for an alphanumeric literal, with the optional
# `ALL ` repetition prefix split off: `ALL "="` -> ("ALL ", '"="').
_ALL_PREFIX_RE = re.compile(r"^(ALL\s+)(.*)$", re.IGNORECASE | re.DOTALL)
QUOTE = chr(34)
_QUOTE_RUN_RE = re.compile(QUOTE + "+")

# PIC symbols that make an item numeric or numeric-edited -- either way the
# only legal reset literal is a number, never SPACES (cobc rejects
# `MOVE SPACES TO <PIC ZZZ item>`). Z/*/$/+/- only ever appear in
# numeric-edited pictures; X/A/B pictures never contain them.
_NUMERIC_PIC_CHARS = frozenset("9VPZ*$+-")

# usage strings as cobolparser stores them (verified empirically).
_FLOAT_USAGES = frozenset({"COMP-1", "COMP-2", "COMPUTATIONAL-1", "COMPUTATIONAL-2"})
_POINTER_USAGES = frozenset(
    {"POINTER", "PROCEDURE-POINTER", "FUNCTION-POINTER", "PROGRAM-POINTER"}
)


def reset_move_lines(program) -> list[str]:
    """One reset line per top-level (01 or 77) WORKING-STORAGE and
    LOCAL-STORAGE item, plus each FILE SECTION FD/SD's first record.

    Elementary items get `MOVE <value> TO <name>` (declared VALUE clause, or
    the type default). Group items without a VALUE clause get
    `INITIALIZE <name>` instead: a MOVE SPACES over a group would write
    spaces across its numeric children, corrupting them for the next test
    case's arithmetic, while INITIALIZE resets numeric children to zero and
    alphanumeric ones to spaces. INITIALIZE does not restore children's own
    VALUE clauses, so after the INITIALIZE we additionally emit a MOVE for
    every (recursively nested) child that declared its own VALUE clause --
    see `_child_value_restores`.
    """
    data_division = program.get_division("DATA")
    if data_division is None:
        return []

    # LOCAL-STORAGE and FILE SECTION records leak between cases exactly
    # like WORKING-STORAGE does -- one binary runs every case -- so a case
    # passed alone and failed in the suite (issue #147). LOCAL-STORAGE
    # gets the same VALUE-restoring treatment; a FILE SECTION record has
    # no VALUE clauses, and only an FD's longest record is reset: every
    # other 01 under the same FD is an implicit redefinition of it, and
    # resetting a shorter one left the rest of the area dirty.
    lines: list[str] = []
    for section in _sections(data_division, "FILE"):
        lines.extend(
            reset_lines_for_items(longest_record_per_file(_top_level_items(section)))
        )
    for section_name in ("WORKING-STORAGE", "LOCAL-STORAGE"):
        for section in _sections(data_division, section_name):
            lines.extend(reset_lines_for_items(_top_level_items(section)))
    return lines


def _sections(data_division, wanted: str) -> list:
    out = []
    for section in getattr(data_division, "sections", data_division.children):
        name = getattr(section, "_own_section_name", None) or getattr(
            section, "section_name", None
        )
        if name and name.upper().replace(" SECTION", "").strip() == wanted:
            out.append(section)
    return out


def reset_lines_for_items(items) -> list[str]:
    """The reset-line generation loop `reset_move_lines` runs over
    WORKING-STORAGE's top-level items, factored out so other WORKING-STORAGE-
    shaped item lists (e.g. a LINKAGE SECTION neutralized into WORKING-STORAGE
    by `mockymock.splicer.linkage`) get the identical VALUE-restoring
    treatment without duplicating this logic."""
    lines: list[str] = []
    for item in items:
        if _is_filler(item):
            continue  # a top-level FILLER cannot be a valid MOVE/INITIALIZE target
        if getattr(item, "redefines", None):
            # A REDEFINES item shares the storage of the item it redefines,
            # which already got its own reset line just above. Resetting it
            # too overwrote that line's work -- `01 A PIC X(4) VALUE "AB12".
            # 01 B REDEFINES A PIC 9(4).` left A holding "0000" in every
            # test case, the first one included. Skipping it leaves the
            # shared bytes exactly as the program starts with them: GnuCOBOL
            # initializes storage from the first (redefined) description.
            continue
        if _is_group(item) and not item.value_clause:
            if _has_occurs_value(item):
                # A table element's VALUE needs a subscripted MOVE per
                # occurrence; INITIALIZE's ALL TO VALUE phrase restores
                # every occurrence (and every other child's VALUE) in one
                # statement, then zero/space-fills the rest (issue #156).
                lines.append(f"INITIALIZE {item.name} ALL TO VALUE THEN TO DEFAULT")
                continue
            lines.append(f"INITIALIZE {item.name}")
            lines.extend(_child_value_restores(item, item.name))
        else:
            reset = _elementary_reset(item)
            if reset is not None:
                lines.append(reset)
    return lines


def cobol_literal(value_clause: str) -> str:
    """Re-render a cobolparser `value_clause` as a well-formed COBOL operand.

    cobolparser hands alphanumeric VALUE clauses back double-quote-delimited
    around the literal's DECODED content, and versions through 1.8.0 did not
    re-double an embedded quote when doing so. A copybook that legitimately
    declares a one-character literal holding a double quote (CICS's own
    DFHAID does, for DFHTRIG) therefore arrived here as three quote
    characters -- an unterminated literal. Emitted verbatim into
    UT-RESET-WORKING-STORAGE it desynchronized cobc's tokenizer for the rest
    of the program, surfacing as a bogus `invalid symbol` error lines away
    from the real cause.

    Fixed upstream (cobol-parser, `_literals.quote_literal`), but this
    project's floor is `cobol-parser>=1.7.7`, so the malformed shape still
    reaches us from every currently published wheel. Normalizing here is also
    idempotent against the fixed parser: a run of quotes is only ever grown
    to the next even length, so an already-doubled pair is left alone. The
    one shape this cannot recover is a literal whose real content is two
    adjacent quotes coming from an unfixed parser -- indistinguishable from
    one correctly-escaped quote, and resolved in favour of the well-formed
    reading.

    Non-literal clauses (numerics, figurative constants, identifiers) carry
    no delimiters and are returned untouched.
    """
    prefix = ""
    body = value_clause
    match = _ALL_PREFIX_RE.match(body)
    if match:
        prefix, body = match.group(1), match.group(2)
    if len(body) < 2 or not body.startswith(QUOTE) or not body.endswith(QUOTE):
        return value_clause  # not a quoted literal -- numeric, figurative, ...
    inner = _QUOTE_RUN_RE.sub(_double_quote_run, body[1:-1])
    return f"{prefix}{QUOTE}{inner}{QUOTE}"


def _double_quote_run(match: re.Match[str]) -> str:
    """Grow a run of quote characters to the next even length: COBOL escapes
    a delimiter inside a literal by repeating it, so every embedded quote must
    appear in a pair. Already-paired runs are returned unchanged, which is
    what makes `cobol_literal` idempotent."""
    run = len(match.group(0))
    return QUOTE * (run + run % 2)


def _top_level_items(section):
    # Level 77 items are standalone top-level items just like 01s; leaving
    # them out would let their state leak between test cases.
    return [
        item for item in section.children if getattr(item, "level", None) in (1, 77)
    ]


def _is_filler(item) -> bool:
    """FILLER items are unaddressable in COBOL: MOVE/INITIALIZE cannot target
    them by name, so reset generation must never emit a line for one."""
    name = getattr(item, "name", None)
    return not name or name.upper() == "FILLER"


def _is_group(item) -> bool:
    """A group item has subordinate data items. cobolparser's `children` list
    mixes in clause nodes (e.g. PictureClause), so only children that carry a
    data-item `level` count."""
    return any(
        getattr(child, "level", None) is not None
        for child in getattr(item, "children", [])
    )


def _has_occurs_value(group) -> bool:
    """True when some OCCURS item under `group` (or a child of one) declares
    a VALUE clause -- the case `_child_value_restores` cannot restore."""

    def walk(item, in_table: bool) -> bool:
        for child in getattr(item, "children", []):
            if getattr(child, "level", None) is None:
                continue
            table = in_table or getattr(child, "occurs_clause", None) is not None
            if table and getattr(child, "value_clause", None):
                return True
            if walk(child, table):
                return True
        return False

    return walk(group, False)


def _child_value_restores(group, qualifier: str) -> list[str]:
    """After INITIALIZE zeroes/space-fills a group, restore any child that
    declared its own VALUE clause (INITIALIZE does not honor those).

    Every restore targets the child fully qualified through its enclosing
    groups (`REC-FLAG OF HDR OF OUT-REC`; `qualifier` is the `OF ...` chain
    for `group` itself). COBOL lets one child name repeat under different
    groups -- IN-REC/OUT-REC built from one copybook -- and an unqualified
    MOVE to such a name is ambiguous, which cobc rejects for the whole
    driver (issue #220). Full qualification is always legal, so there is no
    need to detect the ambiguity first.

    Children carrying an OCCURS clause are skipped entirely (subtree
    included): an unsubscripted `MOVE 7 TO WS-CELL` against an OCCURS item
    is illegal COBOL and cobc rejects it. A group with a VALUE somewhere
    inside a table never gets here: `reset_lines_for_items` resets it with
    `INITIALIZE ... ALL TO VALUE` instead (see `_has_occurs_value`)."""
    out: list[str] = []
    for child in getattr(group, "children", []):
        if getattr(child, "level", None) is None:
            continue  # clause node, not a data item
        if _is_filler(child):
            continue  # FILLER is unaddressable; its VALUE already survives INITIALIZE
        if getattr(child, "occurs_clause", None) is not None:
            continue  # unsubscripted MOVE is illegal; see _has_occurs_value
        target = f"{child.name} OF {qualifier}"
        if _is_group(child):
            out.extend(_child_value_restores(child, target))
        elif getattr(child, "value_clause", None):
            restore = _elementary_reset(child, target)
            if restore is not None:
                out.append(restore)
    return out


def _is_numeric(item) -> bool:
    """True for numeric AND numeric-edited pictures: Z, *, $, + and - only
    ever appear in numeric-edited PICs (e.g. ZZZ9, $$9, ***9), whose only
    legal literal reset is a number -- `MOVE SPACES TO <PIC ZZZ>` is
    rejected by cobc."""
    if item.picture_clause is None:
        return False
    stripped = _REPEAT_GROUP_RE.sub("", item.picture_clause.pattern or "")
    return any(c in _NUMERIC_PIC_CHARS for c in stripped.upper())


def _elementary_reset(item, target: str | None = None) -> str | None:
    """The reset line for one elementary (or VALUE-carrying group) item, or
    None when no legal reset exists (skip rather than emit illegal COBOL).

    POINTER-family items can only be assigned with SET, and NULL is their
    only legal VALUE, so `SET ... TO NULL` both resets and restores. USAGE
    INDEX items are skipped: their content is implementation-defined and a
    reset adds nothing a fresh SEARCH/SET in the test flow doesn't. A
    PICTURE-less item of unrecognized usage is skipped fail-safe.

    `target` is the reference the line writes to (a qualified name for a
    group child); it defaults to the item's own name."""
    name = target or item.name
    usage = (getattr(item, "usage", None) or "").upper()
    if usage in _POINTER_USAGES:
        return f"SET {name} TO NULL"
    if usage == "INDEX":
        return None  # no legal MOVE; fidelity limit
    if item.value_clause:
        return f"MOVE {cobol_literal(item.value_clause)} TO {name}"
    if item.picture_clause is None:
        if usage in _FLOAT_USAGES:
            return f"MOVE 0 TO {name}"
        return None  # PIC-less, unrecognized usage: skip fail-safe
    return f"MOVE {'0' if _is_numeric(item) else 'SPACES'} TO {name}"
