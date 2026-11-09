"""Long COBOL literals split into `&`-concatenated pieces.

cobc compiles the instrumented copy `-free`, where a source line over 512
bytes is truncated. The driver, the injector and the refusal gate's
MOCK_LINE_TOO_LONG check all need the same answer to "how would this line
be split", so it lives here, in a leaf module with no mockymock imports:
anything may use it without joining an import cycle."""

from __future__ import annotations

import re

#: A literal longer than this is split across lines by the driver: cobc
#: compiles the instrumented copy `-free`, where a source line over 512
#: bytes is truncated -- a recorded golden like DEPTMQC's 336-byte MQMD
#: (`X"4D44..."`, 675 characters) cut the generated IF in half.
_LONG_LITERAL = 120
#: Characters of literal content per continuation piece.
_LITERAL_CHUNK = 60
_SPLITTABLE_LITERAL_RE = re.compile(
    r"^(?P<prefix>[Xx]?)(?P<quote>[\"'])(?P<body>.*)(?P=quote)$"
)


def _literal_pieces(value: str) -> list[str] | None:
    """A long alphanumeric or hexadecimal literal as concatenated pieces
    (`X"4D44..."` -> `X"4D44..."`, `& X"2020..."`, ...), one per source
    line, or None when `value` is short or not one such literal. The `&`
    concatenation of literals is a literal to cobc (verified under
    `-free -std=mvs`, GnuCOBOL 3.1.2), so the comparison is unchanged. A
    hex piece keeps whole bytes; a quoted piece never splits a doubled
    quote."""
    text = value.strip()
    if len(text) <= _LONG_LITERAL:
        return None
    m = _SPLITTABLE_LITERAL_RE.match(text)
    if m is None:
        return None
    prefix, quote, body = m.group("prefix"), m.group("quote"), m.group("body")
    units: list[str] = []
    index = 0
    while index < len(body):
        if body[index] == quote:
            if body[index : index + 2] != quote * 2:
                return None  # a lone quote: not one literal
            units.append(quote * 2)
            index += 2
        elif prefix:
            units.append(body[index : index + 2])
            index += 2
        else:
            units.append(body[index])
            index += 1
    pieces: list[str] = []
    current = ""
    for unit in units:
        if current and len(current) + len(unit) > _LITERAL_CHUNK:
            pieces.append(f"{prefix}{quote}{current}{quote}")
            current = ""
        current += unit
    pieces.append(f"{prefix}{quote}{current}{quote}")
    return [pieces[0]] + [f"& {piece}" for piece in pieces[1:]]


def _operand_lines(head: str, value: str, indent: str) -> list[str]:
    """`head + value` as one line, or -- for a long literal -- the head with
    the literal's first piece, then each further `& piece` on its own
    line under `indent`."""
    pieces = _literal_pieces(value)
    if pieces is None:
        return [f"{head}{value}"]
    return [f"{head}{pieces[0]}"] + [f"{indent}{piece}" for piece in pieces[1:]]


_MOVE_HEAD_RE = re.compile(r"MOVE\s+", re.IGNORECASE)


def split_long_move(line: str, indent: str = "     ") -> list[str]:
    """`line` -- a `MOVE <value> TO <target>` statement, with its own
    leading indentation -- as one line, or, when `<value>` is one long
    literal, as `MOVE <first piece>` plus `& <piece>` lines under it
    (`_literal_pieces`), so no driver line passes cobc -free's 512-byte
    limit (issue #322). Anything else is returned unchanged: the value is
    whatever precedes the LAST ` TO `, and must be one whole literal, so a
    ` TO ` inside a literal can never split it wrongly."""
    stripped = line.lstrip()
    head = _MOVE_HEAD_RE.match(stripped)
    if head is None:
        return [line]
    to_at = stripped.upper().rfind(" TO ")
    if to_at <= head.end():
        return [line]
    pieces = _literal_pieces(stripped[head.end() : to_at])
    if pieces is None:
        return [line]
    lead = line[: len(line) - len(stripped)]
    lines = [f"{lead}MOVE {pieces[0]}"] + [
        f"{lead}{indent}{piece}" for piece in pieces[1:]
    ]
    lines[-1] += stripped[to_at:]
    return lines
