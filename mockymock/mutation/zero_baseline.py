"""Flags ADD/SUBTRACT swap survivors the suite cannot kill from the target
field's starting value.

An unsigned numeric field stores only a magnitude. Starting from zero,
`ADD n TO f` leaves `n` and the mutant `SUBTRACT n FROM f` leaves `-n`,
stored as `n`: the two programs are indistinguishable, so the mutant
survives however good the assertions are. The fix lives in the test
data, not the assertions -- start the field from a non-zero value and
the two diverge -- so a survivor of that shape gets a hint saying so
instead of reading as a missing EXPECT.

Purely static and conservative: the hint is only attached to a mutant
that already survived, every target named on the mutated line must be an
unsigned, non-edited numeric WORKING-STORAGE/LOCAL-STORAGE item whose
between-case reset value is zero (its VALUE clause, or the zero default
`splicer/reset.py` gives a numeric item without one), and no test case
may seed it. A program statement that changes the field before the
arithmetic runs is not modelled, which is why the hint says "probably".

The premise also needs the statement to run once per case. Inside a
looping PERFORM (a looped paragraph or an inline PERFORM body) a counter's
`ADD 1` runs n times and ends at n while the mutant alternates 1, 0, 1,
..., so an ordinary EXPECT kills it -- that survivor is a missing
assertion and gets no hint (issue #203).

Seeding only helps if something the suite can see depends on the field:
an EXPECT on it (or on a group holding it), or a program statement that
reads it -- a MOVE, a condition, a CALL argument -- other than its own
ADD/SUBTRACT updates and DISPLAY, which no assertion observes. When no
target is observed that way the survivor is a missing assertion first,
and gets no hint: seeding alone would leave it alive.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from mockymock.mutation.operators import Mutant

_SWAP_DESCRIPTIONS = frozenset(
    {"ADD..TO -> SUBTRACT..FROM", "SUBTRACT..FROM -> ADD..TO"}
)
_RESET_SECTIONS = frozenset({"WORKING-STORAGE", "LOCAL-STORAGE"})
_ZERO_WORDS = frozenset({"ZERO", "ZEROS", "ZEROES"})

_WORD = r"(?<![A-Z0-9-]){}(?![A-Z0-9-])"
# The receiving operands of `ADD .. TO x` / `SUBTRACT .. FROM x`: everything
# after the preposition up to the end of the statement's receiving phrase.
_TARGETS = re.compile(_WORD.format("(?:TO|FROM)") + r"(?P<targets>.*)", re.IGNORECASE)
_TARGETS_END = re.compile(
    _WORD.format("(?:ON|NOT|SIZE|END-ADD|END-SUBTRACT)") + r"|\.\s*$",
    re.IGNORECASE,
)
_GIVING = re.compile(_WORD.format("GIVING"), re.IGNORECASE)
_SUBSCRIPT = re.compile(r"\([^)]*\)")
_NAME = re.compile(r"^[A-Z0-9][A-Z0-9-]*$", re.IGNORECASE)
_QUALIFIER = frozenset({"OF", "IN"})


def zero_baseline_hint(
    mutant: Mutant,
    ast: object,
    suite: object,
    source_location_map: dict[int, tuple[str, int]] | None = None,
) -> str:
    """The hint for one surviving mutant, or "" when it does not apply.

    `source_location_map` is `StaticCheckResult.source_location_map`: the
    AST's lines are copybook-expanded, `mutant.line` is a line of the
    program itself, and every COPY above it shifts the two apart (issue
    #342). Empty or None when nothing was expanded."""
    if (
        mutant.operator != "arith-verb-swap"
        or mutant.description not in _SWAP_DESCRIPTIONS
    ):
        return ""
    targets = _receiving_names(mutant.original)
    if not targets:
        return ""
    items = _items_by_name(ast)
    seeded = _seeded_names(suite)
    for name in targets:
        candidates = items.get(name.upper(), [])
        if not candidates or not all(_starts_at_zero_unsigned(i) for i in candidates):
            return ""
        if name.upper() in seeded:
            return ""
    if not any(_is_observed(name, items, ast, suite) for name in targets):
        return ""
    if _may_run_more_than_once(_ast_lines(mutant.line, source_location_map), ast):
        return ""
    names = ", ".join(targets)
    first = targets[0]
    return (
        f"probably untestable from {names}'s starting value: unsigned, and "
        f"every test case starts it at zero, where ADD and SUBTRACT store the "
        f"same magnitude (0 + n and 0 - n both leave n). This is a test-data "
        f"gap, not a missing assertion: seed it to a non-zero value in a test "
        f"case (e.g. MOVE 5 TO {first}) so the two results differ."
    )


def _ast_lines(
    line: int, source_location_map: dict[int, tuple[str, int]] | None
) -> frozenset[int]:
    """The AST (copybook-expanded) line numbers of the program's own source
    line `line`: itself without an expansion, else every expanded line the
    source map pairs with `("<main>", line)`."""
    if not source_location_map:
        return frozenset({line})
    return frozenset(
        expanded
        for expanded, (origin_file, origin_line) in source_location_map.items()
        if origin_file == "<main>" and origin_line == line
    )


def _may_run_more_than_once(lines: frozenset[int], ast: object) -> bool:
    """Whether the ADD/SUBTRACT on AST line(s) `lines` sits in a paragraph a
    looping PERFORM reaches, or in a looping inline PERFORM's body. When
    the loop analysis cannot run, False: the hint stays, as before."""
    try:
        from mockymock.analysis.loops import (
            _walk,
            looped_paragraphs_and_statements,
        )
        from mockymock.analysis.mock_surface import _all_paragraphs

        looped_paragraphs, looped_ids = looped_paragraphs_and_statements(ast)
        if not looped_paragraphs and not looped_ids:
            return False
        procedure = ast.get_division("PROCEDURE")  # type: ignore[attr-defined]
        for paragraph in _all_paragraphs(procedure):
            for statement in _walk(paragraph.statements):
                location = getattr(statement, "location", None)
                if getattr(location, "line", None) not in lines:
                    continue
                if type(statement).__name__ not in _ARITHMETIC_STATEMENTS:
                    continue
                if (
                    paragraph.paragraph_name in looped_paragraphs
                    or id(statement) in looped_ids
                ):
                    return True
    except Exception:  # noqa: BLE001 -- hints are advisory
        return False
    return False


_ARITHMETIC_STATEMENTS = frozenset({"AddStatement", "SubtractStatement"})


def _receiving_names(line: str) -> list[str]:
    """Bare data names after TO/FROM on the mutated line. Empty when the
    statement is a GIVING form (its receiving field is not the one being
    added to) or when nothing on this line can be read as a name."""
    code = line[:72]  # columns 73-80 are the identification area
    if _GIVING.search(code):
        return []
    match = _TARGETS.search(code)
    if match is None:
        return []
    tail = match.group("targets")
    end = _TARGETS_END.search(tail)
    if end is not None:
        tail = tail[: end.start()]
    tokens = _SUBSCRIPT.sub(" ", tail).replace(",", " ").split()
    names: list[str] = []
    skip_next = False
    for token in tokens:
        if skip_next:
            skip_next = False
            continue
        upper = token.upper()
        if upper in _QUALIFIER:
            skip_next = True
            continue
        if upper == "ROUNDED":
            continue
        if not _NAME.match(token) or token[0].isdigit():
            return []
        names.append(token.rstrip("."))
    return names


def _items_by_name(ast: object) -> dict[str, list[object]]:
    find = getattr(ast, "find_all_by_type", None)
    if find is None:
        return {}
    items: dict[str, list[object]] = {}
    for item in find("CobolDataItem"):
        name = getattr(item, "name", None)
        if name:
            items.setdefault(str(name).upper(), []).append(item)
    return items


#: Usages where storing a negative result in an unsigned item keeps its
#: magnitude. A binary one does not under GnuCOBOL -std=mvs: 0 - 5 in a
#: `PIC 9(4) COMP` (or BINARY, COMP-4, COMP-5) leaves 65531, not 5, so a
#: test asserting the field tells the ADD/SUBTRACT swap apart.
_MAGNITUDE_USAGES = frozenset(
    {"DISPLAY", "COMP-3", "COMPUTATIONAL-3", "PACKED-DECIMAL"}
)


def keeps_magnitude(item: object) -> bool:
    """Whether `item`'s usage (inherited from its group, as cobol-parser
    records it) stores |n| when a negative n lands in it unsigned."""
    usage = str(getattr(item, "usage", None) or "DISPLAY").upper()
    return usage in _MAGNITUDE_USAGES


def _starts_at_zero_unsigned(item: object) -> bool:
    if getattr(item, "section_name", None) not in _RESET_SECTIONS:
        return False
    if not keeps_magnitude(item):
        return False
    picture = getattr(item, "picture_clause", None)
    if picture is None or getattr(picture, "is_edited", False):
        return False
    if getattr(picture, "is_signed", True) or getattr(item, "sign_clause", None):
        return False
    pattern = str(getattr(picture, "pattern", "") or "").upper()
    if not pattern or any(c not in "9VP()0123456789" for c in pattern):
        return False
    if getattr(item, "occurs_clause", None) is not None:
        return False
    return _is_zero_value(getattr(item, "value_clause", None))


def _is_zero_value(value: object) -> bool:
    if value is None:
        return True  # reset.py resets a numeric item with no VALUE to ZERO
    text = str(value).strip().upper()
    if text in _ZERO_WORDS:
        return True
    try:
        return Decimal(text) == 0
    except InvalidOperation:
        return False


# Statements that only print a field: nothing an EXPECT or VERIFY
# can see depends on them.
_UNOBSERVED_STATEMENTS = frozenset({"DisplayStatement"})


def _is_observed(
    name: str, items: dict[str, list[object]], ast: object, suite: object
) -> bool:
    """Whether a test could notice `name`'s value once it is seeded: an
    EXPECT names it or a group holding it, or the program reads it (or a
    group holding it) somewhere other than its own `ADD .. TO` /
    `SUBTRACT .. FROM` updates and a DISPLAY. Anything the cross-reference
    cannot settle counts as observed -- the hint stays, as before."""
    names = {name.upper()}
    for item in items.get(name.upper(), []):
        parent = getattr(item, "parent", None)
        while parent is not None and getattr(parent, "name", None):
            names.add(str(parent.name).upper())
            parent = getattr(parent, "parent", None)
    if names & _expected_names(suite):
        return True
    try:
        return _read_by_program(names, ast)
    except Exception:  # noqa: BLE001 -- no cross-reference: assume observed
        return True


def _read_by_program(names: set[str], ast: object) -> bool:
    """Whether any of `names` is referenced by a statement other than its
    own update or a DISPLAY. `cobolparser.analysis.xref` is new in
    cobol-parser 1.10 (the floor is older); without it the ImportError
    reaches `_is_observed`, which then keeps the hint."""
    from cobolparser.analysis.xref import XrefAnalyzer

    report = XrefAnalyzer().analyze(ast)
    for wanted in names:
        entry = report.entry_for(wanted)
        if entry is None:
            continue
        updates = {
            (ref.location.line, ref.statement)
            for ref in entry.references
            if ref.role == "write"
        }
        for ref in entry.references:
            if ref.role == "write" or ref.statement in _UNOBSERVED_STATEMENTS:
                continue
            if ref.role == "read" and (ref.location.line, ref.statement) in updates:
                continue  # the target of its own ADD/SUBTRACT
            return True
    return False


def _expected_names(suite: object) -> set[str]:
    """Every data name an EXPECT asserts, bare: subscripts and OF/IN
    qualifiers dropped."""
    names: set[str] = set()
    for case in getattr(suite, "test_cases", []) or []:
        for expect in getattr(case, "expectations", []) or []:
            text = _SUBSCRIPT.sub(" ", str(getattr(expect, "data_name", "")))
            words = text.split()
            if words:
                names.add(words[0].upper())
    return names


def _seeded_names(suite: object) -> set[str]:
    """Every data name a test case writes before or while the program runs:
    setup MOVEs, mock ROWS/TERMINAL fields, and `TO <name>` in mock bodies.
    Any write counts -- a MOVE of zero would not help, but telling the two
    apart would mean evaluating the test author's intent."""
    names: set[str] = set()
    # BEFORE-ALL/BEFORE-EACH MOVEs run before every case's own PERFORM, so
    # they seed exactly like a case's MOVE (AFTER-* steps run too late).
    for attr in ("before_all_steps", "before_each_steps"):
        for step in getattr(suite, attr, []) or []:
            if step.kind == "MOVE":
                names.add(str(step.target).upper())
    for case in getattr(suite, "test_cases", []) or []:
        for _value, target in getattr(case, "setup_moves", []) or []:
            names.add(str(target).upper())
        for step in getattr(case, "steps", []) or []:
            if step.kind == "MOVE":
                names.add(str(step.target).upper())
        for mock in getattr(case, "mocks", []) or []:
            for row in (getattr(mock, "rows", None) or []) + [
                getattr(mock, "terminal_row", None) or []
            ]:
                for field_name, _value in row:
                    names.add(str(field_name).upper())
            for body_line in getattr(mock, "body_lines", []) or []:
                for target in re.findall(
                    r"(?<![A-Z0-9-])TO\s+([A-Z0-9][A-Z0-9-]*)", body_line.upper()
                ):
                    names.add(target)
    return names
