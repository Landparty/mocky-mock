"""Synthesized WORKING-STORAGE for `CAPTURE ARG <n> INTO <target>`.

`CAPTURE ARG` (docs/2026-08-11-argument-capture-design.md) moves a real
`CALL`'s USING parameter into a `.cut`-named target so an `EXPECT` can
assert on what the program actually passed -- usually the most interesting
assertion in a test. Its one ergonomic problem was that the target had to
already exist: the author had to find (or add) a spare WORKING-STORAGE item
of a compatible type before writing a single capture, which is why
`generate` never scaffolded one and every capture stayed hand-written.

This module removes that step. A capture target whose name starts with
`CAPTURE_TARGET_PREFIX` is understood as "declare this for me": mockymock
synthesizes a WORKING-STORAGE item mirroring the captured argument's own
PICTURE/USAGE, and a reset line so one case's capture never leaks into the
next. The reserved prefix is what keeps this from being a footgun -- a
mistyped real data name can never accidentally become a new field, because
it will not start with `UT-CAP-`.

Fails closed: an argument whose layout cannot be mirrored exactly (a table,
a PICTURE-less COMP-1/POINTER item, a group holding non-DISPLAY data whose
bytes an alphanumeric copy would render unreadable) is reported as an
unresolved reason, and `cli.checks` turns that into an
`UNRESOLVED_CAPTURE_TARGET` refusal rather than emitting a declaration that
would not compile or would compare against raw binary.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from mockymock.dsl.model import CAPTURE_CATEGORIES, MockCategory, MockTestSuite

#: Names starting with this are mockymock's to declare. Deliberately shares
#: the `UT-` namespace every other generated field uses, so a program of its
#: own with a colliding name was already broken.
CAPTURE_TARGET_PREFIX = "UT-CAP-"

_NON_COBOL_NAME_CHAR_RE = re.compile(r"[^A-Z0-9-]")

#: "UT-CAP-" + body + "-<n>" must stay a valid COBOL word (30-char
#: conservative limit, well under GnuCOBOL's 63): cap the body at 16.
_MAX_BODY = 16

#: A group item is captured as one alphanumeric field only when every byte
#: under it is DISPLAY-encoded. A group holding COMP/COMP-3 children copies
#: correctly byte-for-byte but the result is binary, so an `EXPECT` against
#: it would compare unreadable bytes -- worse than refusing.
_DISPLAY_USAGES = frozenset({"DISPLAY", "", "NATIONAL"})


def capture_target_name(category: MockCategory, key: str, index: int) -> str:
    """The deterministic synthesized target for argument `index` (1-based)
    of the boundary `(category, key)`. `generate` writes this name into the
    `.cut`; this module recognizes it by its prefix, not by re-deriving it,
    so a hand-edited `.cut` that renames one keeps working."""
    body = _NON_COBOL_NAME_CHAR_RE.sub("-", key.upper())
    body = re.sub(r"-{2,}", "-", body).strip("-")
    body = body[:_MAX_BODY].rstrip("-") or "ARG"
    return f"{CAPTURE_TARGET_PREFIX}{body}-{index}"


@dataclass(frozen=True)
class CapturePlan:
    """One synthesized capture target."""

    target: str
    source_name: str
    declaration: str
    reset_line: str


#: Key stamped onto every group item by `_data_item_index`: whether every
#: byte under it is DISPLAY-encoded. cobol-parser reports a GROUP's own
#: `usage` as DISPLAY regardless of its children (verified against
#: `compute_program_data_items`), so the group's own field cannot answer
#: this and the subtree has to be walked.
_SUBTREE_DISPLAY_KEY = "_mockymock_subtree_all_display"


def _data_item_index(program) -> dict[str, dict]:
    """Name (uppercased, unqualified) -> layout facts, from cobol-parser's
    own `compute_program_data_items`, with each group additionally stamped
    with whether its whole subtree is DISPLAY-encoded.

    A name declared more than once under different parents is omitted
    rather than guessed at -- an ambiguous capture source is exactly the
    case this module must refuse on."""
    from cobolparser.generators.data.layout_offsets import compute_program_data_items

    items = compute_program_data_items(program).get("items", [])
    non_display_prefixes = [
        str(item.get("qualified_name") or "")
        for item in items
        if not item.get("is_group")
        and str(item.get("usage") or "DISPLAY").upper() not in _DISPLAY_USAGES
    ]
    for item in items:
        if not item.get("is_group"):
            continue
        qualified = str(item.get("qualified_name") or "")
        item[_SUBTREE_DISPLAY_KEY] = not any(
            child == qualified or child.startswith(qualified + ".")
            for child in non_display_prefixes
        )

    seen: dict[str, dict | None] = {}
    for item in items:
        name = str(item.get("name") or "").upper()
        if not name:
            continue
        seen[name] = None if name in seen else item
    return {name: item for name, item in seen.items() if item is not None}


def _declaration_for(target: str, item: dict) -> tuple[str, str] | None:
    """`(declaration, reset_line)` mirroring `item`, or None when this
    module will not synthesize storage for that shape."""
    if item.get("occurs"):
        return None  # a table argument: MOVE semantics differ per element
    picture = item.get("picture")
    usage = str(item.get("usage") or "DISPLAY").upper()
    if item.get("is_group"):
        length = item.get("byte_length")
        if not length or not item.get(_SUBTREE_DISPLAY_KEY, False):
            return None
        return (
            f"01  {target}  PIC X({length}).",
            f"MOVE SPACES TO {target}",
        )
    if not picture:
        return None  # COMP-1/COMP-2/POINTER/INDEX: nothing to mirror
    suffix = "" if usage in _DISPLAY_USAGES else f" USAGE {usage}"
    declaration = f"01  {target}  PIC {picture}{suffix}."
    numeric = any(char in picture.upper() for char in "9VPZ*$+-")
    reset = f"MOVE {'ZERO' if numeric else 'SPACES'} TO {target}"
    return declaration, reset


def plan_captures(
    program, suite: MockTestSuite, surface
) -> tuple[list[CapturePlan], list[str]]:
    """Every synthesized capture target the suite asks for, plus a reason
    for each one that could not be synthesized.

    Resolution is per (directive, argument index): the argument's real
    data name comes from the matching CALL site's own
    `CallStatement.using_parameters`, exactly as `injector.build_site_
    dispatch` resolves it at splice time, so the declared type always
    mirrors the item the generated MOVE will read.

    A directive matching several physical CALL sites whose argument `n`
    names DIFFERENT items is unresolved, not guessed: one synthesized field
    cannot mirror two layouts, and picking either silently would make the
    capture wrong at one of the sites.
    """
    from mockymock.analysis.refusal import directive_matches_site

    plans: dict[str, CapturePlan] = {}
    unresolved: list[str] = []
    index = _data_item_index(program)

    for case in suite.test_cases:
        for directive in case.mocks:
            if directive.category not in CAPTURE_CATEGORIES:
                continue
            for arg_index, target in directive.captures:
                if not target.upper().startswith(CAPTURE_TARGET_PREFIX):
                    continue  # an author-declared target: not ours to make
                target = target.upper()
                # `.name` is a `str` by the CallStatement contract and the
                # parser substitutes "OMITTED" rather than emitting an empty
                # one -- but this set comprehension is the only place a
                # violation of that would surface, and it would surface as
                # an AttributeError out of the static-check pass rather
                # than as the UNRESOLVED_CAPTURE_TARGET refusal this
                # function exists to produce. Filter instead: a nameless
                # argument then falls through to the "names no resolvable
                # data item" branch below, which is what it is.
                source_names = {
                    site.statement.using_parameters[arg_index - 1].name.upper()
                    for site in surface.boundary_sites
                    if directive_matches_site(directive, site)
                    and getattr(site.statement, "using_parameters", None)
                    and len(site.statement.using_parameters) >= arg_index
                    and site.statement.using_parameters[arg_index - 1].name
                }
                if len(source_names) != 1:
                    unresolved.append(
                        f"CAPTURE ARG {arg_index} INTO {target} in MOCK "
                        f"{directive.describe()}: argument {arg_index} "
                        + (
                            "names no resolvable data item at any matching " "CALL site"
                            if not source_names
                            else f"names different items at different call "
                            f"sites ({', '.join(sorted(source_names))}), so "
                            f"one synthesized field cannot mirror them all"
                        )
                    )
                    continue
                source_name = next(iter(source_names))
                if target in index:
                    unresolved.append(
                        f"CAPTURE ARG {arg_index} INTO {target} in MOCK "
                        f"{directive.describe()}: {target} is already "
                        f"declared by the program itself, so mockymock "
                        f"cannot synthesize it -- rename the target, or "
                        f"drop the {CAPTURE_TARGET_PREFIX} prefix to "
                        f"capture into the program's own field deliberately"
                    )
                    continue
                item = index.get(source_name)
                if item is None:
                    unresolved.append(
                        f"CAPTURE ARG {arg_index} INTO {target} in MOCK "
                        f"{directive.describe()}: {source_name} is not a "
                        f"uniquely-named data item in this program, so its "
                        f"layout cannot be mirrored"
                    )
                    continue
                built = _declaration_for(target, item)
                if built is None:
                    unresolved.append(
                        f"CAPTURE ARG {arg_index} INTO {target} in MOCK "
                        f"{directive.describe()}: {source_name}'s layout "
                        f"cannot be mirrored by a synthesized field (a "
                        f"table, a PICTURE-less item, or a group holding "
                        f"non-DISPLAY data) -- declare a target of your own "
                        f"in the program and CAPTURE into that instead"
                    )
                    continue
                declaration, reset_line = built
                existing = plans.get(target)
                if existing is not None:
                    if existing.declaration != declaration:
                        unresolved.append(
                            f"{target} is captured from both "
                            f"{existing.source_name} and {source_name}, "
                            f"whose layouts differ"
                        )
                    continue
                plans[target] = CapturePlan(
                    target=target,
                    source_name=source_name,
                    declaration=declaration,
                    reset_line=reset_line,
                )
    return list(plans.values()), unresolved


def capture_working_storage_lines(plans: list[CapturePlan]) -> list[str]:
    return [plan.declaration for plan in plans]


def capture_reset_lines(plans: list[CapturePlan]) -> list[str]:
    """Reset between test cases, for the same reason every other generated
    field is reset: the suite compiles to ONE binary, so without this a
    case that never reached its CALL would `EXPECT` against the previous
    case's captured value."""
    return [plan.reset_line for plan in plans]
