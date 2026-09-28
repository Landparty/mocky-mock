"""Record-boundary line splitting for COBOL source text.

`str.splitlines()` breaks on every Unicode line boundary: not only `\\n`,
`\\r\\n` and `\\r` but also form feed (`\\x0c`, a page eject that legacy
sources carry inside comment lines), vertical tab, the `\\x1c`-`\\x1e`
separators, NEL (`\\x85`) and U+2028/2029. cobolparser splits a source's
records on `\\n` / `\\r\\n` / `\\r` only (its own `_lines.split_source_lines`),
so every `SourceLocation.line` it hands back counts records that way. A
mockymock stage that split the same text with `splitlines()` saw one more
line per such character, and every splice span after it landed one line
early -- the mock replaced the statement BEFORE the boundary and the real
CALL / file I/O still ran. Every split of COBOL source text (raw or
normalized) that is later indexed by an AST line number goes through here.

The rule that matters is *agreement with the installed cobolparser*, not
any one splitting rule: cobolparser releases before `cobolparser._lines`
existed (1.8.x and earlier, still allowed by the `>=1.7.7` floor) number
records the `str.splitlines()` way themselves. Splitting on record
delimiters only against one of those would shift every splice the other
way. So record-delimiter splitting is used exactly when the parser does
it, and `str.splitlines()` otherwise.
"""

from __future__ import annotations

import re
from importlib.util import find_spec

_LINE_BREAK_RE = re.compile(r"\r\n|\r|\n")

#: True when the installed cobolparser numbers records on `\\n` / `\\r\\n` /
#: `\\r` only (it ships `cobolparser._lines`); False for older releases,
#: which number them the `str.splitlines()` way.
PARSER_SPLITS_ON_RECORD_DELIMITERS = find_spec("cobolparser._lines") is not None


def split_source_lines(text: str) -> list[str]:
    """Split `text` into lines the way the installed cobolparser numbers
    them: on `\\n` / `\\r\\n` / `\\r` only when it does
    (`PARSER_SPLITS_ON_RECORD_DELIMITERS`), otherwise `str.splitlines()`.
    Either way: no trailing empty line for a terminating line break, `[]`
    for `""`."""
    if not PARSER_SPLITS_ON_RECORD_DELIMITERS:
        return text.splitlines()
    if not text:
        return []
    parts = _LINE_BREAK_RE.split(text)
    if parts[-1] == "":
        parts.pop()
    return parts
