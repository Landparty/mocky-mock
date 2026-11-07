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
restores every occurrence's VALUE without subscripted MOVEs; a group with
a FILLER VALUE adds WITH FILLER, since a FILLER cannot be named in a MOVE,
and so does the plain INITIALIZE of a group with any FILLER (issue #278).
A FILLER group is transparent (its named children are reset in its
place, issue #247). Top-level REDEFINES items are skipped on purpose: their
storage is the redefined item's, which is reset (and its VALUE restored)
by its own line -- a second reset through the redefining view would
overwrite it.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from mockymock._decimal import decimal_point_is_comma, localize_move_line
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

# A VALUE clause a plain MOVE can store into a numeric(-edited) item: a
# numeric literal or the figurative ZERO. Anything else (SPACES, an
# alphanumeric literal, HIGH-VALUES, ALL "*") needs reference modification.
_NUMERIC_VALUE_RE = re.compile(
    r"^(?:[+-]?(?:\d+(?:[.,]\d*)?|[.,]\d+)|ZERO|ZEROS|ZEROES)$", re.IGNORECASE
)

# usage strings as cobolparser stores them (verified empirically).
_FLOAT_USAGES = frozenset({"COMP-1", "COMP-2", "COMPUTATIONAL-1", "COMPUTATIONAL-2"})
#: PICTURE-less numeric usages a `MOVE 0` resets: the floats above plus
#: the COBOL 2002 binary / float types GnuCOBOL accepts under -std=mvs
#: (issue #333 -- they used to be skipped and leaked between cases).
_PICLESS_NUMERIC_USAGES = _FLOAT_USAGES | frozenset(
    {
        "BINARY-CHAR",
        "BINARY-SHORT",
        "BINARY-LONG",
        "BINARY-DOUBLE",
        "BINARY-C-LONG",
        "FLOAT-SHORT",
        "FLOAT-LONG",
        "FLOAT-EXTENDED",
    }
)
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
    # cobol-parser hands `VALUE 1,25` back as `1.25`; under DECIMAL-POINT IS
    # COMMA that is the literal 1 and a period, and cobc rejects the
    # reset paragraph (issue #230).
    comma = decimal_point_is_comma(program)
    return [localize_move_line(line, comma) for line in lines]


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
    for item, ref in reset_targets(items):
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
            odo_max, odo_restore = _odo_counter_lines(item)
            lines.extend(odo_max)
            filler = " WITH FILLER" if _has_filler_value(item) else ""
            if filler or _has_occurs_value(item):
                # A table element's VALUE needs a subscripted MOVE per
                # occurrence; INITIALIZE's ALL TO VALUE phrase restores
                # every occurrence (and every other child's VALUE) in one
                # statement, then zero/space-fills the rest (issue #156).
                # A FILLER's VALUE cannot be restored by name at all, and a
                # case that overwrote the whole group (MOVE SPACES TO
                # a report line) changed it: WITH FILLER restores it too
                # (issue #196).
                if odo_max:
                    # ALL TO VALUE THEN TO DEFAULT works item by item, so an
                    # ODO counter inside the group drops to 0 before its
                    # table is reached. Default-fill the whole group first,
                    # then restore VALUEs alone, which leaves a VALUE-less
                    # counter at its maximum (checked on GnuCOBOL 3.1).
                    lines.append(f"INITIALIZE {ref}{filler}")
                    lines.extend(odo_max)
                    lines.append(f"INITIALIZE {ref}{filler} ALL TO VALUE")
                else:
                    lines.append(
                        f"INITIALIZE {ref}{filler} ALL TO VALUE THEN TO DEFAULT"
                    )
            else:
                # INITIALIZE skips FILLERs unless told WITH FILLER, so a
                # VALUE-less padding FILLER kept whatever bytes a group MOVE
                # or READ INTO left in it, in every later case (issue #278).
                filler = " WITH FILLER" if _has_filler(item) else ""
                lines.append(f"INITIALIZE {ref}{filler}")
                lines.extend(_child_value_restores(item, ref))
            lines.extend(odo_restore)
        else:
            reset = _elementary_reset(item, ref)
            if reset is not None:
                lines.append(reset)
    return lines


def reset_targets(items) -> list[tuple[Any, str]]:
    """Each item of `items` the reset (and the BEFORE-ALL snapshot) can
    name, paired with the reference that names it unambiguously.

    * A FILLER cannot be the target of a MOVE or INITIALIZE, but a FILLER
      *group* (`01 FILLER.` holding flags and counters) can still hold
      named items, and skipping its subtree let their values leak from
      one case to the next (issue #247). Such a group is transparent: its
      named children stand in for it, recursively.
    * A top-level item whose name is also declared elsewhere (a stray 01
      sharing a copybook field's name) cannot be named at all -- a level-01
      item cannot be qualified -- and its bare name made cobc reject the
      whole reset paragraph (issue #281). A group is reset through its
      children, each qualified by it (`X OF CUST-ID`) when that is unique;
      an elementary item, or a child whose qualified name is still not
      unique, is left out: no statement of the program can reference it
      either.

    A child with an OCCURS clause is left out (an unsubscripted reference
    is illegal), as is an elementary FILLER."""
    items = list(items)
    if not items:
        return []
    index = _name_index(items[0])
    out: list[tuple[Any, str]] = []

    def visit(item, qualifiers: list[str], nested: bool) -> None:
        if nested and getattr(item, "occurs_clause", None) is not None:
            return
        if _is_filler(item):
            for child in _data_children(item):
                visit(child, qualifiers, True)
            return
        chain = [item.name, *qualifiers]
        if _unique_reference(index, chain):
            out.append((item, " OF ".join(chain)))
        elif _is_group(item) and not getattr(item, "redefines", None):
            for child in _data_children(item):
                visit(child, chain, True)

    for item in items:
        visit(item, [], False)
    return out


def _name_index(anchor) -> dict[str, list[list[str]]]:
    """Uppercased name -> the named ancestry (innermost first, uppercased)
    of every data item and condition name so called, in the whole program
    `anchor` belongs to."""
    root = anchor
    while getattr(root, "parent", None) is not None:
        root = root.parent
    index: dict[str, list[list[str]]] = {}

    def walk(node) -> None:
        for child in getattr(node, "children", []):
            named = getattr(child, "level", None) is not None or (
                type(child).__name__ == "ConditionNameItem"
            )
            if named and not _is_filler(child):
                ancestry = [n.upper() for n in _named_ancestry(child)]
                index.setdefault(child.name.upper(), []).append(ancestry)
            walk(child)

    walk(root)
    return index


def _unique_reference(index: dict[str, list[list[str]]], chain: list[str]) -> bool:
    """True when exactly one declared item matches `NAME OF Q1 OF Q2 ...`:
    the qualifiers appear, in order, among its enclosing named groups."""
    qualifiers = [q.upper() for q in chain[1:]]

    def matches(ancestry: list[str]) -> bool:
        position = 0
        for name in ancestry:
            if position < len(qualifiers) and name == qualifiers[position]:
                position += 1
        return position == len(qualifiers)

    candidates = index.get(chain[0].upper(), [])
    # An item the walk could not see (a synthesized block) is not in the
    # index at all: nothing else declares its name either.
    return not candidates or sum(matches(a) for a in candidates) == 1


def _odo_counter_lines(group) -> tuple[list[str], list[str]]:
    """The lines that bracket a group's reset so every `OCCURS ...
    DEPENDING ON` table in it is cleared at its full size (issue #216).

    INITIALIZE of a variable-length group only covers the occurrences its
    ODO object currently names. The counter's own reset line usually ran
    first (declaration order) and left it at 0, so no entry was cleared and
    the previous case's table data leaked into the next; declared after the
    table, the INITIALIZE used whatever count the previous case left. A
    fresh program starts with the whole maximum-size area initialized, so
    each counter is set to its table's maximum first and reset to its own
    VALUE (or type default) afterwards: returns (set-to-maximum lines,
    counter-restore lines). A counter that cannot be found (or sits inside
    a table), or an unbounded table, leaves the reset as it was."""
    before: list[str] = []
    after: list[str] = []
    for clause in _odo_clauses(group):
        counter = _find_data_item(
            group, clause.depending_on, clause.depending_on_qualifiers
        )
        if counter is None or getattr(clause, "is_unbounded", False):
            continue
        if _inside_table(counter):
            continue  # an unsubscripted MOVE to it would be illegal
        if not getattr(clause, "max_times", None):
            continue
        target = _qualified_name(counter)
        restore = _elementary_reset(counter, target)
        if restore is None:
            continue
        before.append(f"MOVE {clause.max_times} TO {target}")
        after.append(restore)
    return before, after


def _inside_table(item) -> bool:
    node = item
    while node is not None and getattr(node, "level", None) is not None:
        if getattr(node, "occurs_clause", None) is not None:
            return True
        node = getattr(node, "parent", None)
    return False


def _data_children(item) -> list:
    return [
        child
        for child in getattr(item, "children", [])
        if getattr(child, "level", None) is not None
    ]


def _odo_clauses(group) -> list:
    """Every OCCURS clause with a DEPENDING ON phrase under `group`."""
    out = []
    for child in _data_children(group):
        clause = getattr(child, "occurs_clause", None)
        if clause is not None and getattr(clause, "depending_on", None):
            out.append(clause)
        out.extend(_odo_clauses(child))
    return out


def _qualified_name(item) -> str:
    """`item`'s name qualified by every enclosing named group: `CNT OF HDR
    OF REC`. FILLER and nameless groups are left out of the chain -- `CNT
    OF FILLER` is not COBOL and cobc rejected the whole driver (issue
    #246); a qualifier may skip levels."""
    return " OF ".join([item.name, *_named_ancestry(item)])


def _find_data_item(anchor, name: str, qualifiers) -> object | None:
    """The data item named `name` (whose enclosing groups include every name
    in `qualifiers`) anywhere in the program `anchor` belongs to, or None
    when there is no single match."""
    root = anchor
    while getattr(root, "parent", None) is not None:
        root = root.parent
    wanted = name.upper()
    quals = {q.upper() for q in qualifiers or []}
    matches = []

    def walk(node) -> None:
        for child in getattr(node, "children", []):
            if getattr(child, "level", None) is not None and (
                (getattr(child, "name", None) or "").upper() == wanted
            ):
                chain = {n.upper() for n in _qualified_name(child).split(" OF ")[1:]}
                if quals <= chain:
                    matches.append(child)
            walk(child)

    walk(root)
    return matches[0] if len(matches) == 1 else None


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

    Fixed upstream (cobol-parser, `_literals.quote_literal`); normalizing
    here is kept as defence in depth, and is idempotent against the fixed
    parser: a run of quotes is only ever grown to the next even length, so
    an already-doubled pair is left alone. The one shape this cannot
    recover is a literal whose real content is two adjacent quotes coming
    from an unfixed parser -- indistinguishable from one correctly-escaped
    quote, and resolved in favour of the well-formed reading.

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
    them by name, so reset generation must never emit a line for one. An
    entry written without a data-name (`10 PIC X(20) VALUE 'A'.`, CardDemo's
    COPAUS1C) is FILLER too: cobol-parser flags it `is_filler` and names it
    `ANONYMOUS-<level>-<line>`, a name the compiler never saw."""
    if getattr(item, "is_filler", False) is True:
        return True
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


def _has_filler(group) -> bool:
    """True when any FILLER, with a VALUE or not, sits somewhere under
    `group`."""
    return any(
        _is_filler(child) or _has_filler(child) for child in _data_children(group)
    )


def _has_filler_value(group) -> bool:
    """True when a FILLER somewhere under `group` declares a VALUE clause."""
    return any(
        (_is_filler(child) and getattr(child, "value_clause", None))
        or _has_filler_value(child)
        for child in _data_children(group)
    )


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
        if getattr(child, "occurs_clause", None) is not None:
            continue  # unsubscripted MOVE is illegal; see _has_occurs_value
        if _is_filler(child):
            # Unaddressable itself, but a FILLER group's named children
            # are not: restore them through the named ancestors alone
            # (issue #247). A group with a FILLER VALUE never gets here: it
            # is reset WITH FILLER ALL TO VALUE (see _has_filler_value).
            out.extend(_child_value_restores(child, qualifier))
            continue
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
    if any(c in _NUMERIC_PIC_CHARS for c in stripped.upper()):
        return True
    # Any symbol an alphanumeric(-edited) picture cannot hold is a
    # CURRENCY SIGN the program chose (NIST NC107A's `PIC WWWWW` under
    # `CURRENCY SIGN IS "W"`): numeric-edited.
    return any(c not in _ALPHANUMERIC_PIC_CHARS for c in stripped.upper())


#: The symbols of an alphanumeric or alphanumeric-edited (or national) PIC.
_ALPHANUMERIC_PIC_CHARS = frozenset("AXBNGU0/")


def _value_restore(item, name: str) -> str:
    """`MOVE <VALUE literal> TO <name>`, adjusted where a plain MOVE would
    not rebuild the bytes the VALUE clause put there (issue #218):

    * a numeric or numeric-edited DISPLAY item whose VALUE is not a number
      (`PIC ZZ,ZZ9.99 VALUE SPACES`, the report-line idiom) is moved through
      reference modification, `MOVE SPACES TO <name>(1:)` -- cobc rejects a
      figurative SPACE or an alphanumeric literal moved to a numeric item,
      and the byte-wise move reproduces what VALUE stored;
    * a JUSTIFIED item's literal is padded to the item's full length, since
      VALUE ignores JUSTIFIED (`PIC X(6) JUST RIGHT VALUE "AB"` starts as
      "AB    ") while a MOVE right-justifies. Reference modification does
      not help there: GnuCOBOL still justified `WS-J(1:)`."""
    literal = cobol_literal(item.value_clause)
    picture = item.picture_clause
    if picture is None:
        return f"MOVE {literal} TO {name}"
    if is_text_edited(item):
        # VALUE stores the literal's bytes as they are; a MOVE re-applies
        # the editing mask to them ("12/31/99" into XX/XX/XX became
        # "12//3/1/", issue #277). Reference modification is a byte copy.
        return f"MOVE {literal} TO {name}(1:)"
    usage = (getattr(item, "usage", None) or "DISPLAY").upper()
    if (
        _is_numeric(item)
        and usage == "DISPLAY"
        and not _NUMERIC_VALUE_RE.match(literal)
    ):
        return f"MOVE {literal} TO {name}(1:)"
    if getattr(item, "justified", False):
        literal = _pad_literal(literal, getattr(picture, "size", None))
    return f"MOVE {literal} TO {name}"


def is_text_edited(item) -> bool:
    """An alphanumeric- or national-edited item (`PIC XX/XX/XX`,
    `XXXBXXXX`, `NNBNN`): a MOVE into one edits the sending text again, so
    a value that is already the item's bytes must be copied by reference
    modification instead (issue #277)."""
    picture = getattr(item, "picture_clause", None)
    if picture is None:
        return False
    if getattr(picture, "is_alphanumeric_edited", False) or getattr(
        picture, "is_national_edited", False
    ):
        return True
    return is_alphanumeric_edited_picture(getattr(picture, "pattern", "") or "")


def is_alphanumeric_edited_picture(pattern: str) -> bool:
    """A PICTURE string holding an X or A plus a B, 0 or / insertion
    symbol -- the definition of alphanumeric-edited."""
    symbols = _REPEAT_GROUP_RE.sub("", pattern.upper())
    return any(c in symbols for c in "XA") and any(c in symbols for c in "B0/")


def _pad_literal(literal: str, size: int | None) -> str:
    """Pad a plain quoted literal with trailing spaces to `size` characters
    (an embedded doubled quote counts as one). Figurative constants, `ALL`
    literals and anything else already fill the item and are returned as is."""
    if not size or len(literal) < 2 or literal[0] != QUOTE or literal[-1] != QUOTE:
        return literal
    inner = literal[1:-1]
    length = len(inner.replace(QUOTE * 2, QUOTE))
    if length >= size:
        return literal
    return f"{QUOTE}{inner}{' ' * (size - length)}{QUOTE}"


def _elementary_reset(item, target: str | None = None) -> str | None:
    """The reset line for one elementary (or VALUE-carrying group) item, or
    None when no legal reset exists (skip rather than emit illegal COBOL).

    POINTER-family items can only be assigned with SET, and NULL is their
    only legal VALUE, so `SET ... TO NULL` both resets and restores. USAGE
    INDEX items get no line here: no MOVE is legal for them, so
    `index_names` hands each one to the saved-start-up-value SET reset
    (`index_reset_lines`, issue #333). A PICTURE-less item of unrecognized
    usage is skipped fail-safe (`unreset_items` reports it).

    `target` is the reference the line writes to (a qualified name for a
    group child); it defaults to the item's own name."""
    name = target or item.name
    usage = (getattr(item, "usage", None) or "").upper()
    if usage in _POINTER_USAGES:
        return f"SET {name} TO NULL"
    if usage == "INDEX":
        return None  # no legal MOVE; fidelity limit
    if item.value_clause:
        return _value_restore(item, name)
    if item.picture_clause is None:
        if usage in _PICLESS_NUMERIC_USAGES:
            return f"MOVE 0 TO {name}"
        return None  # PIC-less, unrecognized usage: skip fail-safe
    return f"MOVE {'0' if _is_numeric(item) else 'SPACES'} TO {name}"


# Driver fields that hold each INDEXED BY index's start-up value (issue #189).
INDEX_SAVED_FLAG = "UT-IDX-SAVED"
INDEX_SAVE_PREFIX = "UT-IDX-SAVE-"


def index_names(program) -> list[str]:
    """A reference to every `INDEXED BY` index the program's DATA DIVISION
    declares, one per declaration, in declaration order, followed by every
    WORKING-STORAGE / LOCAL-STORAGE `USAGE INDEX` data item the reset can
    SET by its bare name (issue #333: one outside any table, with a name
    declared once). Both get the same save-at-start / restore-every-case
    treatment.

    An INDEXED BY name declared once is returned bare. One declared by
    several tables (one record copybook included under two 01s) is
    qualified through its table's named ancestors, `IX OF ENT OF IN-REC`:
    a bare `SET ... TO IX` is ambiguous and cobc rejected the whole driver
    (issue #249). FILLER ancestors are left out of the chain (COBOL lets a
    qualifier skip levels); a declaration still not told apart from
    another by its qualified chain is left out, since nothing can name
    it."""
    data_division = program.get_division("DATA")
    if data_division is None:
        return []
    found: list[tuple[str, str]] = []  # (bare name, qualified reference)
    counts: dict[str, int] = {}
    index_items: list[str] = []

    def walk(node, in_table: bool, storage: bool) -> None:
        for child in _data_children(node):
            clause = getattr(child, "occurs_clause", None)
            for name in getattr(clause, "index_names", None) or []:
                if name:
                    ancestry = _named_ancestry(child, include_self=True)
                    chain = [name.upper(), *(n.upper() for n in ancestry)]
                    found.append((name.upper(), " OF ".join(chain)))
            item_name = (getattr(child, "name", None) or "").upper()
            if item_name:
                counts[item_name] = counts.get(item_name, 0) + 1
            child_in_table = in_table or clause is not None
            usage = (getattr(child, "usage", None) or "").upper()
            if (
                storage
                and usage == "INDEX"
                and not child_in_table
                and not _is_group(child)
                and not _is_filler(child)
                and item_name
            ):
                index_items.append(item_name)
            walk(child, child_in_table, storage)

    for section in getattr(data_division, "sections", data_division.children):
        section_name = (
            getattr(section, "_own_section_name", None)
            or getattr(section, "section_name", None)
            or ""
        )
        storage = section_name.upper().replace(" SECTION", "").strip() in (
            "WORKING-STORAGE",
            "LOCAL-STORAGE",
        )
        walk(section, False, storage)
    bare_counts = Counter(bare for bare, _ in found)
    qualified_counts = Counter(qualified for _, qualified in found)
    names: list[str] = []
    for bare, qualified in found:
        if bare_counts[bare] == 1:
            names.append(bare)
        elif qualified_counts[qualified] == 1:
            names.append(qualified)
    names.extend(
        name
        for name in dict.fromkeys(index_items)
        if counts.get(name) == 1 and name not in names
    )
    return names


def _named_ancestry(item, include_self: bool = False) -> list[str]:
    """The names of `item`'s enclosing data items, innermost first, FILLER
    and nameless ones left out (a qualifier may skip levels)."""
    names: list[str] = []
    node = item if include_self else getattr(item, "parent", None)
    while node is not None and getattr(node, "level", None) is not None:
        if not _is_filler(node):
            names.append(node.name)
        node = getattr(node, "parent", None)
    return names


def unreset_items(program) -> list[str]:
    """WORKING-STORAGE / LOCAL-STORAGE elementary items the between-case
    reset cannot put back (issue #333): a `USAGE INDEX` item inside a
    table or with a duplicated name, or a PICTURE-less item of a usage
    `_elementary_reset` does not know. Their values carry from one case
    into the next, so the caller reports them."""
    data_division = program.get_division("DATA")
    if data_division is None:
        return []
    saved = set(index_names(program))
    skipped: list[str] = []

    def walk(node) -> None:
        for child in _data_children(node):
            if getattr(child, "level", None) in (66, 88):
                continue  # a RENAMES / condition name has no storage of its own
            if _is_group(child):
                walk(child)
                continue
            name = (getattr(child, "name", None) or "").upper()
            if not name or _is_filler(child) or getattr(child, "redefines", None):
                continue
            usage = (getattr(child, "usage", None) or "").upper()
            if usage == "INDEX":
                if name not in saved:
                    skipped.append(name)
                continue
            if (
                child.picture_clause is None
                and not child.value_clause
                and usage not in _POINTER_USAGES
                and usage not in _PICLESS_NUMERIC_USAGES
                and not getattr(child, "occurs_clause", None)
            ):
                skipped.append(name)

    for section_name in ("WORKING-STORAGE", "LOCAL-STORAGE"):
        for section in _sections(data_division, section_name):
            walk(section)
    return list(dict.fromkeys(skipped))


def index_working_storage_lines(names: list[str]) -> list[str]:
    """Declarations for the saved start-up value of each index name."""
    if not names:
        return []
    lines = [f'01  {INDEX_SAVED_FLAG}  PIC X VALUE "N".']
    lines.extend(
        f"01  {INDEX_SAVE_PREFIX}{n:03d}  USAGE INDEX."
        for n in range(1, len(names) + 1)
    )
    return lines


def index_reset_lines(names: list[str]) -> list[str]:
    """Put every `INDEXED BY` index back to the value the program started
    with (issue #189): an index name is not a data item, so the
    WORKING-STORAGE reset never saw it, and a case that did `SET IX UP BY
    1` left the next case subscripting from 2. A fresh index's value is
    compiler-defined (GnuCOBOL 3.1 starts it at 1; 3.2 under -std=mvs was
    seen at 0), so rather than pick a constant, the first reset -- which
    runs before any program code -- saves each index, and every reset
    restores it."""
    if not names:
        return []
    saves = [
        f"SET {INDEX_SAVE_PREFIX}{n:03d} TO {name}"
        for n, name in enumerate(names, start=1)
    ]
    restores = [
        f"SET {name} TO {INDEX_SAVE_PREFIX}{n:03d}"
        for n, name in enumerate(names, start=1)
    ]
    return [
        f'IF {INDEX_SAVED_FLAG} = "N"',
        *(f"    {line}" for line in saves),
        f'    MOVE "Y" TO {INDEX_SAVED_FLAG}',
        "END-IF",
        *restores,
    ]
