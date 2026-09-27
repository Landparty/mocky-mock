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
"""

from __future__ import annotations

import re

_LINE_BREAK_RE = re.compile(r"\r\n|\r|\n")


def split_source_lines(text: str) -> list[str]:
    """Split `text` on `\\n` / `\\r\\n` / `\\r` only. Otherwise mirrors
    `str.splitlines()`: no trailing empty line for a terminating line
    break, `[]` for `""`."""
    if not text:
        return []
    parts = _LINE_BREAK_RE.split(text)
    if parts[-1] == "":
        parts.pop()
    return parts
