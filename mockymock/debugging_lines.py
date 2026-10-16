"""Fixed-format debugging lines (`D` in column 7) under `SOURCE-COMPUTER
... WITH DEBUGGING MODE` (issue #274).

The compiler compiles a D line as ordinary code when the program declares
WITH DEBUGGING MODE, and as a comment otherwise. cobolparser and
`normalize_fixed_format` treat every D line as a comment by default, so
such a program lost its D lines twice: the AST (and its boundary sites)
never saw them, and neither did the text the splicer hands to cobc.
`activate_debugging_lines` makes the source say what the compiler reads:
the D indicator becomes a space, so the parser, the reachability gate and
the compiled sandbox all agree. Line numbers and columns do not move.
"""

from __future__ import annotations

import re

_DEBUGGING_MODE_RE = re.compile(r"\bWITH\s+DEBUGGING\s+MODE\b", re.IGNORECASE)
_DEBUG_INDICATOR_RE = re.compile(r"(?m)^([^\r\n]{6})[dD]")
_LINE_RE = re.compile(r"[^\r\n]+")


def declares_debugging_mode(source: str) -> bool:
    """Whether a non-comment line of fixed-format `source` says WITH
    DEBUGGING MODE."""
    for match in _LINE_RE.finditer(source):
        line = match.group()
        if len(line) > 6 and line[6] in "*/":
            continue
        if _DEBUGGING_MODE_RE.search(line[7:] if len(line) > 6 else line):
            return True
    return False


def activate_debugging_lines(source: str) -> str:
    """`source` with every D line turned into a code line when it declares
    WITH DEBUGGING MODE; unchanged otherwise."""
    if not declares_debugging_mode(source):
        return source
    return _DEBUG_INDICATOR_RE.sub(r"\1 ", source)
