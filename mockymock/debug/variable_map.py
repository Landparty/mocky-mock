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
(COMP), COB_TYPE_NUMERIC_PACKED=0x12 (COMP-3), COB_TYPE_NUMERIC_FLOAT/DOUBLE
=0x13/0x14 (COMP-1/COMP-2), COB_TYPE_ALPHANUMERIC family=0x20-0x23 and
COB_TYPE_NUMERIC_EDITED=0x24 (both read as their text). Any other code is
shown as `<unsupported type 0xNN>`, never as gdb's `cob_field` struct. Raw bytes are read via MI `-data-read-memory-bytes` (NOT gdb's
default char-array print, which stops at the first embedded NUL byte and
silently truncates/misrepresents binary numeric data -- confirmed
empirically: a `PIC 9(5)V99 COMP-3` field's buffer printed as `""` via
`-data-evaluate-expression` but decoded correctly once read as raw memory).
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from typing import Literal

from mockymock.debug.gdb_session import (
    GdbCommandError,
    GdbSession,
    MalformedMIRecordError,
    ResultRecord,
    decode_gdb_bytes,
    evaluate,
    unescape_c_bytes,
)

# GnuCOBOL's authoritative field-type constants
# (/usr/include/libcob/common.h in the toolchain image), not guessed.
_COB_TYPE_NUMERIC_DISPLAY = 0x10
_COB_TYPE_NUMERIC_BINARY = 0x11
_COB_TYPE_NUMERIC_PACKED = 0x12
_COB_TYPE_NUMERIC_FLOAT = 0x13  # COMP-1: a host-order IEEE 754 single
_COB_TYPE_NUMERIC_DOUBLE = 0x14  # COMP-2: a host-order IEEE 754 double
# Numeric-edited: the storage IS the edited display text (`-  5.50`).
_COB_TYPE_NUMERIC_EDITED = 0x24
# 0x20 ALNUM, 0x21 ALPHANUMERIC, 0x22 ALPHANUMERIC_ALL, 0x23
# ALPHANUMERIC_EDITED.
_COB_TYPE_ALPHANUMERIC_FAMILY = {0x20, 0x21, 0x22, 0x23}
_COB_FLAG_HAVE_SIGN = 0x0001
_COB_FLAG_SIGN_SEPARATE = 0x0002
_COB_FLAG_SIGN_LEADING = 0x0004
# Set on a binary field stored big-endian on a little-endian host (COMP/
# COMP-4/BINARY under -std=mvs's binary-byteorder: big-endian). COMP-5
# (flags 0x0041, REAL_BINARY) lacks it: stored in host order.
_COB_FLAG_BINARY_SWAP = 0x0020
_COB_FLAG_NO_SIGN_NIBBLE = 0x0100

# Matches a `.c.l.h` declaration line for either a raw buffer (`b_NN`) or a
# cob_field wrapper (`f_NN`), capturing the generated name and its trailing
# `/* COBOL-NAME */` comment. Not a general C parser -- only ever needs to
# match this compiler's own generated declaration shape.
# The name class is GnuCOBOL's own word pattern (cobc/scanner.l:
# `[A-Z0-9\x80-\xFF]([_A-Z0-9\x80-\xFF-]*...)`): `WS_TOTAL` and non-ASCII
# names are valid COBOL words there, and were silently left out.
_DECL_RE = re.compile(
    r"\b(?P<expr>(?P<kind>[bf])_(?P<id>\d+))\b[^/\n]*/\*\s*(?P<name>[\w-]+)\s*\*/"
)


def parse_local_header(text: str) -> dict[str, str]:
    """COBOL name -> gdb expression, from a `<compiled-name>.c.l.h` file's
    text. `f_NN` (cob_field wrapper) is preferred over `b_NN` (raw buffer)
    of the SAME item -- cobc numbers both from the item's own field id
    (`static cob_field f_18 = {4, b_18, ...}`, cobc/codegen.c).

    The comment is cobc's bare `f->name`, never qualified, so two items
    that share a name (`WS-NAME OF GRP-A` / `WS-NAME OF GRP-B`) arrive as
    two different ids under one name. Keying on the name alone let the
    later one silently replace the earlier (the Variables pane showed one
    item's value under the other's declaration and hid the second). The
    first item keeps the bare name; each further one is listed as
    `NAME (2)`, `NAME (3)`, ... in declaration order."""
    by_name: dict[str, dict[str, str]] = {}
    for match in _DECL_RE.finditer(text):
        items = by_name.setdefault(match.group("name"), {})
        item_id = match.group("id")
        if match.group("kind") == "f" or item_id not in items:
            items[item_id] = match.group("expr")
    table: dict[str, str] = {}
    for name, items in by_name.items():
        for index, expr in enumerate(items.values(), start=1):
            table[name if index == 1 else f"{name} ({index})"] = expr
    return table


#: What the Variables view shows for a declared item cobc gave no C local
#: (issue #156): an absent row read as "this program has no such item".
UNAVAILABLE_VALUE = "<unavailable: not materialized by cobc>"

#: What the Variables view shows for an item gdb could not read at this
#: stop -- a LOCAL-STORAGE item whose storage cobc has not bound yet (its
#: `.data` is NULL until the program's first use of it), issue #318.
UNREADABLE_VALUE = "<unavailable: storage not bound at this point>"

#: gdb's printing of a `cob_u8_t *` (an EXTERNAL item's `b_NN`): the
#: pointer, then the text it points at.
_POINTER_REPR_RE = re.compile(r'^0x[0-9a-fA-F]+\s+(?P<text>".*")$', re.DOTALL)


def declared_data_names(program) -> list[str]:
    """Every addressable data item the program declares, in declaration
    order: FILLER, condition names (88) and RENAMES (66) have no storage
    of their own to show."""
    from mockymock._cobol_layout import compute_program_data_items

    try:
        items = compute_program_data_items(program).get("items", [])
    except Exception:  # a layout walk must never break a debug session
        return []
    return [
        str(item["name"])
        for item in items
        if item.get("name")
        and str(item["name"]).upper() != "FILLER"
        and item.get("level") not in (66, 88)
    ]


def unavailable_names(declared: list[str], table: dict[str, str]) -> list[str]:
    """The declared data names (in order, first spelling kept) that the
    variable table has no entry for. cobc only declares a C local for an
    item it generates code against, so an item no statement references --
    or one it optimized away -- has none, and gdb cannot read it."""
    known = {name.upper() for name in table}
    missing: list[str] = []
    for name in declared:
        upper = name.upper()
        if upper in known:
            continue
        known.add(upper)
        missing.append(name)
    return missing


@dataclass(frozen=True)
class BufferLayout:
    """What cobc would have put in a `cob_field`'s attr for an item it
    only declared as a raw `b_NN` buffer, rebuilt from the program's own
    PICTURE and USAGE.

    cobc skips the `f_NN` wrapper for an item nothing needs a field for --
    a counter only ever touched by ADD/SUBTRACT, a signed DISPLAY item the
    procedure never names -- so `.attr` is unreadable and the buffer was
    printed as text: PIC S9(8) COMP holding -70000 showed as
    `"\\377\\376", <incomplete sequence \\356\\220>`, a signed DISPLAY -1.05
    as `0010u` (issue #168). `type_code` None marks a numeric item this
    module cannot decode (a PICTURE with P scaling, ...),
    shown as unavailable rather than as garbage."""

    type_code: int | None
    digits: int = 0
    scale: int = 0
    flags: int = 0


_UNDECODABLE = BufferLayout(type_code=None)

_BINARY_SWAPPED_USAGES = {
    "BINARY",
    "COMP",
    "COMPUTATIONAL",
    "COMP-4",
    "COMPUTATIONAL-4",
}
_BINARY_NATIVE_USAGES = {"COMP-5", "COMPUTATIONAL-5"}
_PACKED_USAGES = {"COMP-3", "COMPUTATIONAL-3", "PACKED-DECIMAL"}
_COMP6_USAGES = {"COMP-6", "COMPUTATIONAL-6"}
_FLOAT_USAGES = {"COMP-1", "COMPUTATIONAL-1", "FLOAT-SHORT"}
_DOUBLE_USAGES = {"COMP-2", "COMPUTATIONAL-2", "FLOAT-LONG"}


def _item_layout(item) -> BufferLayout | None:
    """None for an item whose buffer IS its display text (alphanumeric,
    numeric-edited, group): the existing unquoted-buffer path is right
    for those."""
    usage = (getattr(item, "usage", None) or "DISPLAY").upper()
    picture = getattr(item, "picture_clause", None)
    if usage in _FLOAT_USAGES:
        return BufferLayout(_COB_TYPE_NUMERIC_FLOAT)
    if usage in _DOUBLE_USAGES:
        return BufferLayout(_COB_TYPE_NUMERIC_DOUBLE)
    if picture is None:
        return None if usage == "DISPLAY" else _UNDECODABLE
    digits = getattr(picture, "total_digits", None)
    if digits is None or getattr(picture, "is_edited", False):
        return None if usage == "DISPLAY" else _UNDECODABLE
    if getattr(picture, "has_scaling_factor", False):
        return _UNDECODABLE
    scale = getattr(picture, "decimal_digits", None) or 0
    flags = _COB_FLAG_HAVE_SIGN if getattr(picture, "is_signed", False) else 0
    if usage == "DISPLAY":
        sign = (getattr(item, "sign_clause", None) or "").upper()
        if flags and "LEADING" in sign:
            flags |= _COB_FLAG_SIGN_LEADING
        if flags and "SEPARATE" in sign:
            flags |= _COB_FLAG_SIGN_SEPARATE
        return BufferLayout(_COB_TYPE_NUMERIC_DISPLAY, digits, scale, flags)
    if usage in _BINARY_SWAPPED_USAGES:
        flags |= _COB_FLAG_BINARY_SWAP
        return BufferLayout(_COB_TYPE_NUMERIC_BINARY, digits, scale, flags)
    if usage in _BINARY_NATIVE_USAGES:
        return BufferLayout(_COB_TYPE_NUMERIC_BINARY, digits, scale, flags)
    if usage in _PACKED_USAGES:
        return BufferLayout(_COB_TYPE_NUMERIC_PACKED, digits, scale, flags)
    if usage in _COMP6_USAGES:
        flags = _COB_FLAG_NO_SIGN_NIBBLE
        return BufferLayout(_COB_TYPE_NUMERIC_PACKED, digits, scale, flags)
    return _UNDECODABLE


def buffer_layouts(program) -> dict[str, BufferLayout]:
    """Upper-cased COBOL name -> `BufferLayout`, for every 01/77 item of
    the program's DATA DIVISION that needs decoding. Only 01/77 items get
    a `b_NN` buffer of their own (a subordinate item is an offset into its
    group's, and always gets an `f_NN`), so nothing else is collected.
    Two 01s sharing a name with different layouts are marked undecodable:
    which buffer is which cannot be told from the header."""
    data_division = program.get_division("DATA") if program is not None else None
    if data_division is None:
        return {}
    layouts: dict[str, BufferLayout] = {}
    sections = getattr(data_division, "sections", None) or data_division.children
    for section in sections:
        for item in getattr(section, "children", []):
            if getattr(item, "level", None) not in (1, 77):
                continue
            name = (getattr(item, "name", None) or "").upper()
            if not name or name == "FILLER":
                continue
            if any(
                getattr(child, "level", None) is not None
                for child in getattr(item, "children", [])
            ):
                continue  # group: its buffer is alphanumeric
            layout = _item_layout(item)
            if layout is None:
                continue
            if name in layouts and layouts[name] != layout:
                layout = _UNDECODABLE
            layouts[name] = layout
    return layouts


def _expected_buffer_size(layout: BufferLayout) -> set[int] | None:
    if layout.type_code == _COB_TYPE_NUMERIC_DISPLAY:
        return {layout.digits + bool(layout.flags & _COB_FLAG_SIGN_SEPARATE)}
    if layout.type_code == _COB_TYPE_NUMERIC_PACKED:
        if layout.flags & _COB_FLAG_NO_SIGN_NIBBLE:
            return {(layout.digits + 1) // 2}
        return {layout.digits // 2 + 1}
    if layout.type_code == _COB_TYPE_NUMERIC_BINARY:
        return {1, 2, 4, 8}
    if layout.type_code == _COB_TYPE_NUMERIC_FLOAT:
        return {4}
    if layout.type_code == _COB_TYPE_NUMERIC_DOUBLE:
        return {8}
    return None


@dataclass
class VariableValue:
    name: str
    kind: Literal[
        "alphanumeric",
        "numeric-display",
        "binary",
        "packed-decimal",
        "numeric-edited",
        "float",
        "opaque",
        "unavailable",
    ]
    raw_repr: str
    """The MI expression's own printed value, verbatim."""
    decoded: str | None = None
    """Human-facing decimal string for numeric kinds; None otherwise (the
    alphanumeric/opaque cases' raw_repr already IS the display value)."""


def _decode_packed_decimal(raw: bytes, digits: int, scale: int, flags: int = 0) -> str:
    """COMP-3: two BCD digit nibbles per byte, with a sign nibble
    (0xC/0xF positive, 0xD/0xB negative) after the last digit nibble.
    Confirmed empirically: 123.45 (PIC 9(5)V99 COMP-3, digits=7, scale=2)
    after three ADD 1s reads back as raw bytes 00 12 64 5F -> digit
    nibbles 0012645, sign nibble F (positive) -> "126.45".

    An EVEN digit count leaves a pad nibble at the FRONT, not the back:
    PIC S9(4) COMP-3 VALUE 1234 is 01 23 4C (GnuCOBOL 3.2, -std=mvs).
    The digits are therefore the LAST `digits` nibbles before the sign --
    reading the first `digits` showed that field as 0123, taking the
    final digit for the sign. COMP-6 (NO_SIGN_NIBBLE) has no sign nibble
    at all."""
    nibbles: list[int] = []
    for byte in raw:
        nibbles.append(byte >> 4)
        nibbles.append(byte & 0x0F)
    if flags & _COB_FLAG_NO_SIGN_NIBBLE or not nibbles:
        digit_nibbles, sign_nibble = nibbles, 0xF
    else:
        digit_nibbles, sign_nibble = nibbles[:-1], nibbles[-1]
    if digits > 0:
        digit_nibbles = digit_nibbles[-digits:]
    digit_str = "".join(str(n) for n in digit_nibbles)
    value = _place_point(digit_str, scale) or "0"
    return f"-{value}" if sign_nibble in (0xB, 0xD) else value


def _place_point(digit_str: str, scale: int) -> str:
    """`digit_str` (the stored digits) as the value cobc's `scale` says
    it holds. A PICTURE with P positions gives a negative scale (`9(3)PPP`:
    scale -3, the stored 637 is 637000) or one larger than the stored
    digit count (`VPP99`: scale 4, the stored 12 is 0.0012); reading
    either as an ordinary scale showed another number (issue #295)."""
    if scale < 0:
        return str(int(digit_str or "0") * 10 ** (-scale))
    if scale > 0:
        digit_str = digit_str.rjust(scale, "0")
        return f"{digit_str[:-scale] or '0'}.{digit_str[-scale:]}"
    return digit_str


def _decode_numeric_display(raw: bytes, scale: int, flags: int) -> str:
    """Zoned decimal: one ASCII digit per byte, plus -- for a signed
    field -- a sign that is either a separate `+`/`-` byte
    (SIGN ... SEPARATE) or overpunched into the leading/trailing digit.

    GnuCOBOL 3.2 under -std=mvs overpunches a negative digit as
    digit + 0x40 (`p`..`y`): PIC S9(3) VALUE -123 is stored `12s`, and a
    positive one as the plain digit. The EBCDIC-style convention
    (`{`/`A`..`I` positive, `}`/`J`..`R` negative) some configurations
    use is recognized too. Keeping only the 0-9 bytes, as this used to,
    dropped the overpunched digit and the sign with it (-123 read "12",
    -12.3 read "01.2")."""
    data = bytearray(raw)
    negative = False
    if flags & _COB_FLAG_HAVE_SIGN and data:
        leading = bool(flags & _COB_FLAG_SIGN_LEADING)
        index = 0 if leading else len(data) - 1
        if flags & _COB_FLAG_SIGN_SEPARATE:
            negative = data[index] == ord("-")
            del data[index]
        else:
            byte = data[index]
            if 0x70 <= byte <= 0x79:
                negative, data[index] = True, byte - 0x40
            elif byte == 0x7D:  # '}'
                negative, data[index] = True, 0x30
            elif 0x4A <= byte <= 0x52:  # 'J'..'R'
                negative, data[index] = True, byte - 0x4A + 0x31
            elif byte == 0x7B:  # '{'
                data[index] = 0x30
            elif 0x41 <= byte <= 0x49:  # 'A'..'I'
                data[index] = byte - 0x41 + 0x31
    digit_str = "".join(chr(b) for b in data if 0x30 <= b <= 0x39)
    value = _place_point(digit_str, scale)
    return f"-{value}" if negative else value


def _decode_binary(
    raw: bytes, scale: int, signed: bool, big_endian: bool = True
) -> str:
    """COMP: a big-endian integer (confirmed empirically: WS-COUNTER, PIC
    S9(4) COMP, read back as raw bytes 00 04 -> 4, big-endian). COMP-5 is
    stored in the container's native order -- little-endian on every
    architecture the toolchain image runs on (x86_64, aarch64): PIC S9(4)
    COMP-5 VALUE -2 is FE FF, which big-endian decoding read as -257.
    `read_variable` tells the two apart by COB_FLAG_BINARY_SWAP."""
    value = int.from_bytes(
        raw, byteorder="big" if big_endian else "little", signed=signed
    )
    if scale < 0:  # P scaling: 9(3)PPP COMP stores 12 for 12000 (#295)
        return str(value * 10 ** (-scale))
    if scale > 0:
        text = str(abs(value)).rjust(scale + 1, "0")
        sign = "-" if value < 0 else ""
        return f"{sign}{text[:-scale]}.{text[-scale:]}"
    return str(value)


def read_variable(
    session: GdbSession,
    name: str,
    expr: str,
    layout: BufferLayout | None = None,
) -> VariableValue:
    """Reads one COBOL data item's current value. `expr` is whatever
    `parse_local_header` mapped `name` to (an `f_NN` or `b_NN`
    expression). `layout` is the item's `buffer_layouts` entry, used only
    when `expr` turns out to be a bare buffer (see `BufferLayout`)."""
    try:
        type_code = int(evaluate(session, f"(int)({expr}).attr->type"))
    except GdbCommandError:
        if layout is not None:
            return _read_buffer_with_layout(session, name, expr, layout)
        # Not a cob_field wrapper -- confirmed empirically: a plain PIC X
        # item with no runtime PICTURE decoding needs (no COMP/COMP-3)
        # only ever gets the raw `b_NN` buffer declared, never an `f_NN`
        # wrapper. gdb already prints a `cob_u8_t[N]` buffer as a quoted,
        # correctly-decoded display string, so unquote it directly rather
        # than reporting it as opaque.
        raw_repr = evaluate(session, expr)
        decoded = _unquote_c_string(raw_repr)
        if decoded is None and (pointer := _POINTER_REPR_RE.match(raw_repr)):
            # An EXTERNAL item: `b_NN` is a pointer to its storage, and gdb
            # prints the address before the text (issue #318).
            decoded = _unquote_c_string(pointer.group("text"))
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
    if address == 0:
        # A LOCAL-STORAGE field before cobc binds its storage (issue #318).
        return VariableValue(
            name=name, kind="unavailable", raw_repr=raw_repr, decoded=UNREADABLE_VALUE
        )
    raw_bytes = _read_raw_memory(session, address, size)
    return _decode_field(name, type_code, digits, scale, flags, raw_repr, raw_bytes)


def _read_buffer_with_layout(
    session: GdbSession, name: str, expr: str, layout: BufferLayout
) -> VariableValue:
    raw_repr = evaluate(session, expr)
    expected = _expected_buffer_size(layout)
    if expected is None:
        return _unavailable(name, raw_repr)
    try:
        size = int(evaluate(session, f"sizeof({expr})"))
        address = int(evaluate(session, f"(long)({expr})"))
    except (GdbCommandError, ValueError):
        return _unavailable(name, raw_repr)
    if size not in expected:
        # Not the buffer the PICTURE describes (a pointer, a differently
        # sized item of the same name): decoding it would invent a value.
        return _unavailable(name, raw_repr)
    raw_bytes = _read_raw_memory(session, address, size)
    assert layout.type_code is not None  # implied by `expected`
    return _decode_field(
        name,
        layout.type_code,
        layout.digits,
        layout.scale,
        layout.flags,
        raw_repr,
        raw_bytes,
    )


def _unavailable(name: str, raw_repr: str) -> VariableValue:
    return VariableValue(
        name=name,
        kind="unavailable",
        raw_repr=raw_repr,
        decoded="<unavailable: not materialized by cobc>",
    )


def _decode_field(
    name: str,
    type_code: int,
    digits: int,
    scale: int,
    flags: int,
    raw_repr: str,
    raw_bytes: bytes,
) -> VariableValue:
    if type_code in _COB_TYPE_ALPHANUMERIC_FAMILY | {_COB_TYPE_NUMERIC_EDITED}:
        # A numeric-edited item's storage is its edited text, exactly
        # like an alphanumeric one's: nothing to decode but the bytes.
        # Read as raw memory rather than gdb's own char-array printing of
        # `.data`, which renders as "<pointer> <string>" for a field's
        # data member (unlike a bare buffer expression) and would need
        # its own fragile parsing to extract just the string.
        return VariableValue(
            name=name,
            kind=(
                "numeric-edited"
                if type_code == _COB_TYPE_NUMERIC_EDITED
                else "alphanumeric"
            ),
            raw_repr=raw_repr,
            # UTF-8, not ASCII: a PIC X holding `Café` (the .cbl is read
            # and compiled as UTF-8) showed as `Caf\ufffd\ufffd`.
            decoded=raw_bytes.decode("utf-8", errors="replace"),
        )

    if type_code == _COB_TYPE_NUMERIC_PACKED:
        return VariableValue(
            name=name,
            kind="packed-decimal",
            raw_repr=raw_repr,
            decoded=_decode_packed_decimal(raw_bytes, digits, scale, flags),
        )
    if type_code == _COB_TYPE_NUMERIC_BINARY:
        signed = bool(flags & _COB_FLAG_HAVE_SIGN)
        return VariableValue(
            name=name,
            kind="binary",
            raw_repr=raw_repr,
            decoded=_decode_binary(
                raw_bytes,
                scale,
                signed,
                big_endian=bool(flags & _COB_FLAG_BINARY_SWAP),
            ),
        )
    if type_code == _COB_TYPE_NUMERIC_DISPLAY:
        return VariableValue(
            name=name,
            kind="numeric-display",
            raw_repr=raw_repr,
            decoded=_decode_numeric_display(raw_bytes, scale, flags),
        )

    if type_code in (_COB_TYPE_NUMERIC_FLOAT, _COB_TYPE_NUMERIC_DOUBLE):
        decoded = _decode_float(raw_bytes, double=type_code == _COB_TYPE_NUMERIC_DOUBLE)
        if decoded is not None:
            return VariableValue(
                name=name, kind="float", raw_repr=raw_repr, decoded=decoded
            )

    # An unrecognized/unhandled type code (long double, decimal floating
    # point, NATIONAL, ...): rather than guess a decode, a short marker --
    # the raw repr is gdb's whole `cob_field` struct, pointers and all,
    # which is no value at all to someone reading a COBOL variable.
    return VariableValue(
        name=name,
        kind="opaque",
        raw_repr=raw_repr,
        decoded=f"<unsupported type 0x{type_code:02x}>",
    )


def _decode_float(raw: bytes, double: bool) -> str | None:
    """COMP-1/COMP-2: an IEEE 754 single/double in the container's native
    order -- little-endian on every architecture the toolchain image runs
    on, as for COMP-5. Shown at the shortest precision that reads back as
    the same stored value, so COMP-1 0.1 is `0.1`, not the float32's exact
    0.100000001490116... None when the buffer is not the expected size."""
    fmt = "<d" if double else "<f"
    if len(raw) != struct.calcsize(fmt):
        return None
    (value,) = struct.unpack(fmt, raw)
    if double:
        return repr(value)
    for digits in range(1, 10):
        text = f"{value:.{digits}g}"
        if struct.pack(fmt, float(text)) == raw:
            return text
    return repr(value)


_REPEATS_RE = re.compile(r" <repeats (\d+) times>")


def _unquote_c_string(text: str) -> str | None:
    """If `text` is gdb's own quoted-and-escaped C-string printing (e.g.
    `"CUST00001 "`), return the unescaped content; otherwise None (it's
    some other kind of gdb value printing this module doesn't decode).

    gdb collapses a run of 10+ identical elements into a repeat block
    (`"JANE SMITH", ' ' <repeats 20 times>` for a `PIC X(30)`; an all-
    spaces field is only `' ' <repeats 30 times>`), so a value is a
    comma-separated list of quoted strings and repeated character
    literals -- verified against gdb's MI output. A value gdb truncated
    (`...`, past `print elements`) is not decoded. Escapes are gathered
    as bytes and decoded together (see `decode_gdb_bytes`)."""
    raw = bytearray()
    i = 0
    try:
        while True:
            if text[i : i + 1] == '"':
                chunk, i = unescape_c_bytes(text, i + 1, '"')
                if i >= len(text):
                    return None
                i += 1
                raw += chunk
            elif text[i : i + 1] == "'" and len(text) > i + 2:
                if text[i + 1] == "\\":
                    chunk, j = unescape_c_bytes(text, i + 1, "'")
                    # only the one escape: `'\\000'`, `'\\\\'`
                    if j >= len(text):
                        return None
                else:
                    chunk, j = text[i + 1].encode("utf-8"), i + 2
                    if text[j : j + 1] != "'":
                        return None
                i = j + 1
                repeats = _REPEATS_RE.match(text, i)
                if repeats is not None:
                    chunk *= int(repeats.group(1))
                    i = repeats.end()
                raw += chunk
            else:
                return None
            if i == len(text):
                return decode_gdb_bytes(bytes(raw))
            if not text.startswith(", ", i):
                return None
            i += 2
    except MalformedMIRecordError:
        return None


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
