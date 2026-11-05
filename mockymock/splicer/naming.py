"""Deterministic (category, key) -> UT-...-TALLY field naming.

CALL keeps v1's UT-<NAME>-TALLY shape so existing .cut files whose mock
bodies reference tally fields keep working; every other category prefixes
the category word (UT-READ-INFILE-TALLY, UT-SQL-UPDATE-ORDERS-TALLY).
DYNCALL prefixes its .cut keyword CALL, not the internal category name
(UT-CALL-WS-PGM-NAME-TALLY): that is what a .cut author would guess from
writing MOCK CALL WS-PGM-NAME, and it can never collide with a static
CALL's un-prefixed shape for the same spelling.

A name is a pure function of (category, key) -- never of which other keys
the suite (or the --case/--tag selection) happens to hold -- because
generate writes these names into mock bodies (issue #314: an order-based
-2 suffix moved to the other file's tally when a case was added above, and
the happy path hung). When sanitizing the key would lose information (the
body is cut at the length cap, or punctuation is folded to `-`), the body
is cut shorter and a 4-hex-digit hash of the full (category, key) is
appended: UT-READ-CUSTOMER-MA-7F3A-TALLY. Two keys can then still meet
only by a hash collision or by differing in nothing but letter case or a
space vs. a hyphen; the registry suffixes -2, -3, ... on such a residual
collision, in first-appearance order, as a last resort.
"""

from __future__ import annotations

import hashlib
import re

from mockymock.dsl.model import MockCategory, MockTestSuite

_NON_COBOL_NAME_CHAR_RE = re.compile(r"[^A-Z0-9-]")

# "UT-" + body + "-TALLY" must stay a valid COBOL word everywhere (30-char
# conservative limit, well under GnuCOBOL's 63): cap the body at 21.
_MAX_BODY = 21
# Room left for the body before "-" + the 4-digit hash.
_HASH_DIGITS = 4
_HASHED_BODY = _MAX_BODY - _HASH_DIGITS - 1


def _sanitize(text: str) -> str:
    sanitized = _NON_COBOL_NAME_CHAR_RE.sub("-", text.upper())
    sanitized = re.sub(r"-{2,}", "-", sanitized).strip("-")
    return sanitized


def tally_name(category: MockCategory, key: str) -> str:
    """The tally field for (category, key), independent of any other key."""
    raw = key if category is MockCategory.CALL else f"{category.keyword} {key}"
    body = _sanitize(raw)
    lossless = body == raw.upper().replace(" ", "-")
    if lossless and body and len(body) <= _MAX_BODY:
        return f"UT-{body}-TALLY"
    digest = hashlib.sha1(f"{category.value}:{key}".encode()).hexdigest()
    stem = body[:_HASHED_BODY].rstrip("-") or "MOCK"
    return f"UT-{stem}-{digest[:_HASH_DIGITS].upper()}-TALLY"


class TallyRegistry:
    """Assigns and remembers the tally field name for every (category, key)
    mocked anywhere in a suite."""

    def __init__(self, suite: MockTestSuite) -> None:
        self._names: dict[tuple[MockCategory, str], str] = {}
        taken: set[str] = set()
        for category, key in suite.all_mock_keys():
            name = tally_name(category, key)
            body = name.removeprefix("UT-").removesuffix("-TALLY")
            suffix = 2
            while name in taken:
                trimmed = body[: _MAX_BODY - len(str(suffix)) - 1].rstrip("-")
                name = f"UT-{trimmed}-{suffix}-TALLY"
                suffix += 1
            taken.add(name)
            self._names[(category, key)] = name
        # Per-site call counters (`UT-SITE-TALLY` in a mock body), filled
        # in by the injector as it splices each site that uses one and
        # declared by the driver, which is built after the injection.
        self._site_tallies: dict[int, str] = {}

    def name(self, category: MockCategory, key: str) -> str:
        return self._names[(category, key)]

    def base_name(self, category: MockCategory, key: str) -> str:
        """The field holding the tally's value when the case's own PERFORM
        began, so VERIFY counts only that PERFORM's calls while the tally
        itself keeps counting as the ROWS cursor (issue #223). A tally
        always ends in -TALLY, so the -BASE twin can never collide with
        another tally."""
        return self.name(category, key).removesuffix("-TALLY") + "-BASE"

    def start_name(self, category: MockCategory, key: str) -> str:
        """The field holding a BEFORE-ALL mock's tally as BEFORE-ALL left it:
        each case inheriting the mock resumes its ROWS cursor there."""
        return self.name(category, key).removesuffix("-TALLY") + "-START"

    def known(self, category: MockCategory, key: str) -> bool:
        return (category, key) in self._names

    def items(self) -> list[tuple[tuple[MockCategory, str], str]]:
        return list(self._names.items())

    def site_tally(self, line: int) -> str:
        """The counter of the calls the site at `line` answered in the
        running case (`UT-SITE-TALLY` in a mock body). Its twin
        `site_case` holds the case it counts for, so the site resets it
        itself when another case reaches it."""
        name = f"UT-SITE-{line}-TALLY"
        self._site_tallies[line] = name
        return name

    @staticmethod
    def site_case(line: int) -> str:
        return f"UT-SITE-{line}-CASE"

    def site_tallies(self) -> list[tuple[int, str]]:
        return sorted(self._site_tallies.items())


def truth_set(value: str, target: str) -> str | None:
    """`SET <target> TO TRUE|FALSE` for a `.cut` MOVE / ROWS / TERMINAL
    assignment whose value is TRUE or FALSE, None for any other value.
    TRUE and FALSE are not values COBOL can MOVE: the form can only mean a
    level-88 condition-name, which only SET can change -- the same reading
    EXPECT <88> TO BE TRUE gets (issue #251). Lint refuses the form on a
    target that is not an 88 (analysis.cut_names)."""
    word = value.strip().upper()
    if word not in ("TRUE", "FALSE"):
        return None
    return f"SET {target.strip()} TO {word}"


def assign(value: str, target: str) -> str:
    """The one statement a `.cut` `value -> target` assignment splices as:
    a SET for TRUE/FALSE (see truth_set), a MOVE otherwise."""
    return truth_set(value, target) or f"MOVE {value} TO {target}"
