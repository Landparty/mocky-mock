"""Resolving an `OF`/`IN`-qualified COBOL data-name against a map keyed by
plain and dotted qualified names, the way `report.record_rewrite.
field_pictures` builds it. Its own module so the splicer and the report
side share it without an import cycle."""

from __future__ import annotations

import re
from collections.abc import Mapping, Set

_QUALIFIER_RE = re.compile(r"\s+(?:OF|IN)\s+", re.IGNORECASE)


def qualified_lookup(data_name: str, entries: Mapping[str, str]) -> str | None:
    """The value for a (possibly `OF`/`IN`-qualified, subscripted)
    data-name: the plain key for an unqualified name, else the one value
    every dotted key whose item matches the qualification agrees on --
    `AMT OF OUT-REC` matches `OUT-REC.AMT` and `FD-SEC.OUT-REC.AMT`, never
    `IN-REC.AMT`. Falls back to the plain key (present only when every
    declaration of the name agrees); None when nothing settles it."""
    words = _words(data_name)
    if not words or not entries:
        return None
    leaf, qualifiers = words[0], words[1:]
    if qualifiers:
        found = {
            value for key, value in entries.items() if _matches(key, leaf, qualifiers)
        }
        if len(found) == 1:
            return next(iter(found))
    return entries.get(leaf)


def qualified_member(data_name: str, names: Set[str]) -> bool:
    """Whether `data_name` names an item in `names` (plain and dotted
    qualified names, like `qualified_lookup`'s keys)."""
    words = _words(data_name)
    if not words:
        return False
    leaf, qualifiers = words[0], words[1:]
    if not qualifiers:
        return leaf in names
    return any(_matches(name, leaf, qualifiers) for name in names) or leaf in names


def _words(data_name: str) -> list[str]:
    base = data_name.partition("(")[0].strip()
    return [word.upper() for word in _QUALIFIER_RE.split(base) if word]


def _matches(key: str, leaf: str, qualifiers: list[str]) -> bool:
    """Whether the dotted `key` (`OUT-REC.AMT`) is `leaf` qualified by
    `qualifiers` (innermost first, as written after OF/IN), in order,
    skipping unnamed levels the way COBOL qualification may."""
    if "." not in key:
        return False
    *ancestors, name = key.split(".")
    if name != leaf:
        return False
    remaining = list(reversed(ancestors))
    for qualifier in qualifiers:
        if qualifier not in remaining:
            return False
        remaining = remaining[remaining.index(qualifier) + 1 :]
    return True
