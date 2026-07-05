"""Deterministic (category, key) -> UT-...-TALLY field naming.

CALL keeps v1's UT-<NAME>-TALLY shape so existing .cut files whose mock
bodies reference tally fields keep working; every other category prefixes
the category word (UT-READ-INFILE-TALLY, UT-SQL-UPDATE-ORDERS-TALLY).

Sanitized keys can collide (two SQL prefixes that differ only in
punctuation, or only beyond the length cap), so names are assigned through
a suite-scoped registry that suffixes -2, -3, ... on collision in
first-appearance order — deterministic for a given .cut file.
"""

from __future__ import annotations

import re

from mockymock.dsl.model import MockCategory, MockTestSuite

_NON_COBOL_NAME_CHAR_RE = re.compile(r"[^A-Z0-9-]")

# "UT-" + body + "-TALLY" must stay a valid COBOL word everywhere (30-char
# conservative limit, well under GnuCOBOL's 63): cap the body at 21.
_MAX_BODY = 21


def _sanitize(text: str) -> str:
    sanitized = _NON_COBOL_NAME_CHAR_RE.sub("-", text.upper())
    sanitized = re.sub(r"-{2,}", "-", sanitized).strip("-")
    return sanitized


class TallyRegistry:
    """Assigns and remembers the tally field name for every (category, key)
    mocked anywhere in a suite."""

    def __init__(self, suite: MockTestSuite) -> None:
        self._names: dict[tuple[MockCategory, str], str] = {}
        taken: set[str] = set()
        for category, key in suite.all_mock_keys():
            body = (
                _sanitize(key)
                if category is MockCategory.CALL
                else _sanitize(f"{category.value} {key}")
            )
            body = body[:_MAX_BODY].rstrip("-") or "MOCK"
            name = f"UT-{body}-TALLY"
            suffix = 2
            while name in taken:
                trimmed = body[: _MAX_BODY - len(str(suffix)) - 1].rstrip("-")
                name = f"UT-{trimmed}-{suffix}-TALLY"
                suffix += 1
            taken.add(name)
            self._names[(category, key)] = name

    def name(self, category: MockCategory, key: str) -> str:
        return self._names[(category, key)]

    def known(self, category: MockCategory, key: str) -> bool:
        return (category, key) in self._names

    def items(self) -> list[tuple[tuple[MockCategory, str], str]]:
        return list(self._names.items())
