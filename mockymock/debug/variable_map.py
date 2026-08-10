"""COBOL data item <-> gdb-visible expression mapping for the debugger.

gdb does not expose COBOL names as symbols (`print WS-BALANCE`-style
expressions fail -- confirmed empirically). But `cobc -g` always emits a
sibling `<compiled-name>.c.l.h` header (included into the generated
function body) declaring every working-storage/linkage item as its own
named C local -- `b_NN` for a raw buffer, `f_NN` for a `cob_field`
wrapping one -- with the ORIGINAL COBOL NAME AS A TRAILING COMMENT on the
same declaration line:

    static cob_u8_t b_18[4] __attribute__((aligned));  /* WS-BALANCE */
    static cob_field f_18 = {4, b_18, &a_2};             /* WS-BALANCE */

That comment is a free, mechanical symbol table (see
docs/2026-07-22-dap-debugger-design.md's Empirical basis, question 3).

Decoding: for a `cob_field` (`f_NN`) expression, gdb can read its own
`attr->type`/`attr->digits`/`attr->scale` directly -- GnuCOBOL's authoritative
type constants (from the container's own /usr/include/libcob/common.h, not
guessed) are COB_TYPE_NUMERIC_DISPLAY=0x10, COB_TYPE_NUMERIC_BINARY=0x11
(COMP), COB_TYPE_NUMERIC_PACKED=0x12 (COMP-3), COB_TYPE_ALPHANUMERIC family
=0x20-0x23. Raw bytes are read via MI `-data-read-memory-bytes` (NOT gdb's
default char-array print, which stops at the first embedded NUL byte and
silently truncates/misrepresents binary numeric data -- confirmed
empirically: a `PIC 9(5)V99 COMP-3` field's buffer printed as `""` via
`-data-evaluate-expression` but decoded correctly once read as raw memory).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from mockymock.debug.gdb_session import (
    GdbCommandError,
    GdbSession,
    ResultRecord,
    decode_c_escape,
    evaluate,
)

# GnuCOBOL's authoritative field-type constants
# (/usr/include/libcob/common.h in the toolchain image), not guessed.
_COB_TYPE_NUMERIC_DISPLAY = 0x10
_COB_TYPE_NUMERIC_BINARY = 0x11
_COB_TYPE_NUMERIC_PACKED = 0x12
_COB_TYPE_ALPHANUMERIC_FAMILY = {0x20, 0x21, 0x22, 0x23}
_COB_FLAG_HAVE_SIGN = 0x0001

# Matches a `.c.l.h` declaration line for either a raw buffer (`b_NN`) or a
# cob_field wrapper (`f_NN`), capturing the generated name and its trailing
# `/* COBOL-NAME */` comment. Not a general C parser -- only ever needs to
# match this compiler's own generated declaration shape.
_DECL_RE = re.compile(
    r"\b(?P<expr>[bf]_\d+)\b[^/\n]*/\*\s*(?P<name>[A-Za-z0-9-]+)\s*\*/"
)


def parse_local_header(text: str) -> dict[str, str]:
    """COBOL name -> gdb expression, from a `<compiled-name>.c.l.h` file's
    text. `f_NN` (cob_field wrapper) is preferred over `b_NN` (raw buffer)
    when both exist for the same name -- the field wrapper always appears
    after its buffer in the generated file (see module docstring's
    example), so scanning in file order and letting a later match
    overwrite an earlier one for the same name gets this for free."""
    table: dict[str, str] = {}
    for match in _DECL_RE.finditer(text):
        table[match.group("name")] = match.group("expr")
    return table


@dataclass
class VariableValue:
    name: str
    kind: Literal[
        "alphanumeric", "numeric-display", "binary", "packed-decimal", "opaque"
    ]
    raw_repr: str
    """The MI expression's own printed value, verbatim."""
    decoded: str | None = None
    """Human-facing decimal string for numeric kinds; None otherwise (the
    alphanumeric/opaque cases' raw_repr already IS the display value)."""


def _decode_packed_decimal(raw: bytes, digits: int, scale: int) -> str:
    """COMP-3: two BCD digit nibbles per byte, with a sign nibble
    (0xC/0xF positive, 0xD negative) after the last digit nibble.
    Confirmed empirically: 123.45 (PIC 9(5)V99 COMP-3, digits=7, scale=2)
    after three ADD 1s reads back as raw bytes 00 12 64 5F -> digit
    nibbles 0012645, sign nibble F (positive) -> "126.45"."""
    nibbles: list[int] = []
    for byte in raw:
        nibbles.append(byte >> 4)
        nibbles.append(byte & 0x0F)
    digit_str = "".join(str(n) for n in nibbles[:digits])
    sign_nibble = nibbles[digits] if len(nibbles) > digits else 0xF
    if scale > 0:
        int_part = digit_str[:-scale] or "0"
        frac_part = digit_str[-scale:]
        value = f"{int_part}.{frac_part}"
    else:
        value = digit_str or "0"
    return f"-{value}" if sign_nibble == 0xD else value


def _decode_binary(raw: bytes, scale: int, signed: bool) -> str:
    """COMP: a big-endian integer (confirmed empirically: WS-COUNTER, PIC
    S9(4) COMP, read back as raw bytes 00 04 -> 4, big-endian). COMP-5
    (native-endian) is a documented GnuCOBOL distinction not exercised by
    the spike fixture -- not handled here; see Task 10 of the CLI
    implementation plan."""
    value = int.from_bytes(raw, byteorder="big", signed=signed)
    if scale > 0:
        text = str(abs(value)).rjust(scale + 1, "0")
        sign = "-" if value < 0 else ""
        return f"{sign}{text[:-scale]}.{text[-scale:]}"
    return str(value)


def read_variable(session: GdbSession, name: str, expr: str) -> VariableValue:
    """Reads one COBOL data item's current value. `expr` is whatever
    `parse_local_header` mapped `name` to (an `f_NN` or `b_NN`
    expression)."""
    try:
        type_code = int(evaluate(session, f"(int)({expr}).attr->type"))
    except GdbCommandError:
        # Not a cob_field wrapper -- confirmed empirically: a plain PIC X
        # item with no runtime PICTURE decoding needs (no COMP/COMP-3)
        # only ever gets the raw `b_NN` buffer declared, never an `f_NN`
        # wrapper. gdb already prints a `cob_u8_t[N]` buffer as a quoted,
        # correctly-decoded display string, so unquote it directly rather
        # than reporting it as opaque.
        raw_repr = evaluate(session, expr)
        decoded = _unquote_c_string(raw_repr)
        if decoded is not None:
            return VariableValue(
                name=name, kind="alphanumeric", raw_repr=raw_repr, decoded=decoded
            )
        return VariableValue(name=name, kind="opaque", raw_repr=raw_repr)

    digits = int(evaluate(session, f"(int)({expr}).attr->digits"))
    scale = int(evaluate(session, f"(int)({expr}).attr->scale"))
    flags = int(evaluate(session, f"(int)({expr}).attr->flags"))
    size = int(evaluate(session, f"({expr}).size"))
    address = int(evaluate(session, f"(long)({expr}).data"))
    raw_repr = evaluate(session, expr)
    raw_bytes = _read_raw_memory(session, address, size)

    if type_code in _COB_TYPE_ALPHANUMERIC_FAMILY:
        # Read as raw memory rather than gdb's own char-array printing of
        # `.data`, which renders as "<pointer> <string>" for a field's
        # data member (unlike a bare buffer expression) and would need
        # its own fragile parsing to extract just the string.
        return VariableValue(
            name=name,
            kind="alphanumeric",
            raw_repr=raw_repr,
            decoded=raw_bytes.decode("ascii", errors="replace"),
        )

    if type_code == _COB_TYPE_NUMERIC_PACKED:
        return VariableValue(
            name=name,
            kind="packed-decimal",
            raw_repr=raw_repr,
            decoded=_decode_packed_decimal(raw_bytes, digits, scale),
        )
    if type_code == _COB_TYPE_NUMERIC_BINARY:
        signed = bool(flags & _COB_FLAG_HAVE_SIGN)
        return VariableValue(
            name=name,
            kind="binary",
            raw_repr=raw_repr,
            decoded=_decode_binary(raw_bytes, scale, signed),
        )
    if type_code == _COB_TYPE_NUMERIC_DISPLAY:
        # Numeric-display: each byte an ASCII digit. Sign overpunch
        # encoding (SIGN LEADING/SEPARATE clauses) was not in the spike
        # fixture -- unsigned/simple case only, flagged for Task 10.
        digit_str = "".join(chr(b) for b in raw_bytes if 0x30 <= b <= 0x39)
        decoded = (
            f"{digit_str[:-scale] or '0'}.{digit_str[-scale:]}"
            if scale > 0
            else digit_str
        )
        return VariableValue(
            name=name, kind="numeric-display", raw_repr=raw_repr, decoded=decoded
        )

    # An unrecognized/unhandled type code (COMP-5, floating point, edited
    # pictures, ...): report the raw gdb representation rather than guess
    # a decode.
    return VariableValue(name=name, kind="opaque", raw_repr=raw_repr)


def _unquote_c_string(text: str) -> str | None:
    """If `text` is gdb's own quoted-and-escaped C-string printing (e.g.
    `"CUST00001 "`), return the unescaped content; otherwise None (it's
    some other kind of gdb value printing this module doesn't decode)."""
    if len(text) < 2 or text[0] != '"' or text[-1] != '"':
        return None
    body = text[1:-1]
    out: list[str] = []
    i = 0
    while i < len(body):
        if body[i] == "\\" and i + 1 < len(body):
            decoded, i = decode_c_escape(body, i + 1)
            out.append(decoded)
        else:
            out.append(body[i])
            i += 1
    return "".join(out)


def _read_raw_memory(session: GdbSession, address: int, size: int) -> bytes:
    """`-data-read-memory-bytes` -- NOT gdb's default value printing,
    which stops at the first embedded NUL and misrepresents binary
    numeric data (see module docstring)."""
    records = session.send(f"-data-read-memory-bytes {address} {size}")
    for record in records:
        if isinstance(record, ResultRecord) and record.kind == "done":
            memory = record.payload.get("memory")
            if memory:
                return bytes.fromhex(memory[0]["contents"])
    raise GdbCommandError(
        f"-data-read-memory-bytes {address} {size} produced no memory"
    )
