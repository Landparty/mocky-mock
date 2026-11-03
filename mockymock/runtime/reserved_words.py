"""Two GnuCOBOL quirks a program that compiles on z/OS must get past.

Reserved words: `-std=mvs` reserves CHAR (as GnuCOBOL's ibm.words says,
"Is this an error and was in for FUNCTION CHAR"), so a program declaring
`02 CHAR PIC X` fails to compile with "'CHAR' is a reserved word, but isn't
supported" (NIST ST115A, ST137A, ...). `-fnot-reserved=CHAR` frees the
word, but also takes FUNCTION CHAR away, so it is passed only for a program
that declares the word as a data name and never calls the function.

Column 7: GnuCOBOL 3.1/3.2 read a dollar sign in column 7 as a directive
indicator even in free format, inside a literal too (NIST ST137A's
`    " <dollar><dollar>()*+..."` failed with "spurious '<dollar>' detected"
and a syntax error). `prepare_free_source` shifts such a line right by a
blank: leading blanks mean nothing in free format, so the program and its
line numbers stay the same.
"""

from __future__ import annotations

import re
from pathlib import Path

# Words `-std=mvs` reserves that Enterprise COBOL lets a program use as a
# data name.
IBM_UNRESERVED: tuple[str, ...] = ("CHAR",)

_DOLLAR = chr(36)


def _code(text: str) -> str:
    """`text` without `*>` comments and quoted literals."""
    lines = []
    for line in text.splitlines():
        code = line.split("*>", 1)[0]
        lines.append(re.sub(r'"[^"]*"|\'[^\']*\'', '""', code))
    return "\n".join(lines)


def not_reserved_flags(source_text: str) -> list[str]:
    """`-fnot-reserved=WORD` for each IBM_UNRESERVED word `source_text`
    declares as a data name (`<level> WORD`) without calling it as a
    function (`FUNCTION WORD`)."""
    code = _code(source_text)
    flags = []
    for word in IBM_UNRESERVED:
        declared = re.search(
            rf"(?im)^\s*\d{{1,2}}\s+{re.escape(word)}(?=[\s.]|$)", code
        )
        called = re.search(rf"(?i)\bFUNCTION\s+{re.escape(word)}\b", code)
        if declared and not called:
            flags.append(f"-fnot-reserved={word}")
    return flags


def shield_column_7(text: str) -> str:
    """`text` with each line whose column 7 holds a dollar sign shifted
    right by blanks until it does not (see the module docstring)."""
    lines = text.split("\n")
    changed = False
    for index, line in enumerate(lines):
        if len(line) > 6 and line[6] == _DOLLAR:
            while len(line) > 6 and line[6] == _DOLLAR:
                line = " " + line
            lines[index] = line
            changed = True
    return "\n".join(lines) if changed else text


def prepare_free_source(path: Path) -> str:
    """Apply `shield_column_7` to the free-form source at `path` in place;
    its text afterwards ("" when it cannot be read: cobc reports that)."""
    try:
        text = path.read_text(encoding="utf-8", errors="surrogateescape")
    except OSError:
        return ""
    shielded = shield_column_7(text)
    if shielded != text:
        path.write_text(
            shielded, encoding="utf-8", errors="surrogateescape", newline=""
        )
    return shielded
