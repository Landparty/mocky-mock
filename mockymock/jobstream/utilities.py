"""The IBM utilities a job run emulates, exactly or not at all.

* `IEFBR14`: does nothing (the step's dispositions still apply).
* `IEBGENER` / `ICEGENER`: copies SYSUT1 to SYSUT2 when SYSIN is DUMMY or
  empty (a SYSIN with control statements is a gap).
* `SORT` / `ICEMAN` / `DFSORT` / `SYNCSORT`: `SORT FIELDS=COPY`,
  `OPTION COPY`, `MERGE FIELDS=COPY`, or `SORT|MERGE FIELDS=(p,l,f,o,...)`
  with CH, ZD and BI keys, on fixed-length records. Any other control
  statement (INCLUDE, OMIT, INREC, OUTREC, SUM, ...) is a gap.

A gap raises `UtilityGap`; the job runner stops there and says so.
"""

from __future__ import annotations

import re
from collections.abc import Callable

COPY_PROGRAMS = frozenset({"IEBGENER", "ICEGENER"})
SORT_PROGRAMS = frozenset({"SORT", "ICEMAN", "DFSORT", "SYNCSORT"})
NOOP_PROGRAMS = frozenset({"IEFBR14"})


class UtilityGap(Exception):
    """The step cannot be emulated exactly."""


_STATEMENT_RE = re.compile(r"^\s*(?P<verb>[A-Z]+)\s+(?P<rest>.*)$")
_KEY_RE = re.compile(r"(\d+),(\d+),(CH|ZD|BI),(A|D)", re.IGNORECASE)


def control_statements(lines: list[str]) -> list[tuple[str, str]]:
    """(verb, operands) per statement, continuation lines joined; comment
    lines (`*` in column 1) and blank lines dropped."""
    statements: list[tuple[str, str]] = []
    for raw in lines:
        line = raw[:71].rstrip()
        if not line.strip() or line.startswith("*"):
            continue
        match = _STATEMENT_RE.match(line.upper())
        if match is not None and match.group("verb") in (
            "SORT",
            "MERGE",
            "OPTION",
            "INCLUDE",
            "OMIT",
            "INREC",
            "OUTREC",
            "OUTFIL",
            "SUM",
            "RECORD",
            "END",
            "ALTSEQ",
            "MODS",
            "JOINKEYS",
        ):
            statements.append((match.group("verb"), match.group("rest").strip()))
        elif statements:
            verb, rest = statements[-1]
            statements[-1] = (verb, rest + line.strip())
        else:
            raise UtilityGap(f"cannot read control statement {line.strip()!r}")
    return statements


def sort_key(statements: list[tuple[str, str]]) -> Callable[[bytes], tuple] | None:
    """The record key of a SORT/MERGE (None for a copy).

    Raises:
        UtilityGap: A control statement the emulation does not do.
    """
    key: Callable[[bytes], tuple] | None = None
    copy = False
    seen_sort = False
    for verb, rest in statements:
        operands = rest.split(" ", 1)[0].upper()
        if verb == "END":
            continue
        if verb == "OPTION":
            words = {w.strip() for w in operands.split(",")}
            if "COPY" in words:
                copy = True
                words.discard("COPY")
            if words - {""}:
                raise UtilityGap(f"OPTION {operands} is not emulated")
            continue
        if verb in ("SORT", "MERGE"):
            seen_sort = True
            if operands in ("FIELDS=COPY", "FIELDS=(COPY)"):
                copy = True
                continue
            match = re.match(r"^FIELDS=\((?P<spec>[^)]*)\)(?:,|$)", operands)
            if match is None:
                raise UtilityGap(f"{verb} {operands} is not emulated")
            spec = match.group("spec")
            fields = _KEY_RE.findall(spec)
            if not fields or ",".join(
                ",".join(f) for f in fields
            ).upper() != spec.upper().replace(" ", ""):
                raise UtilityGap(
                    f"{verb} FIELDS=({spec}) uses a format other than CH, ZD or BI"
                )
            key = _record_key(
                [(int(p), int(n), f.upper(), o.upper()) for p, n, f, o in fields]
            )
            continue
        raise UtilityGap(f"{verb} is not emulated")
    if not seen_sort and not copy:
        raise UtilityGap("no SORT, MERGE or OPTION COPY statement")
    return None if copy and key is None else key


def _zoned(raw: bytes) -> int:
    digits = raw.decode("latin-1")
    sign = 1
    last = digits[-1:] if digits else ""
    if last in "pqrstuvwxy" and last:
        sign = -1
        digits = digits[:-1] + str("pqrstuvwxy".index(last))
    try:
        return sign * int(digits or "0")
    except ValueError as exc:
        raise UtilityGap(f"ZD sort key {raw!r} is not zoned decimal") from exc


class _Descending:
    __slots__ = ("value",)

    def __init__(self, value: object) -> None:
        self.value = value

    def __lt__(self, other: _Descending) -> bool:
        return other.value < self.value  # type: ignore[operator]

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _Descending) and other.value == self.value


def _record_key(fields: list[tuple[int, int, str, str]]) -> Callable[[bytes], tuple]:
    def key(record: bytes) -> tuple:
        parts: list[object] = []
        for position, length, form, order in fields:
            # A key past the end of a short (blank-stripped) line reads blanks.
            raw = record[position - 1 : position - 1 + length].ljust(length, b" ")
            value: object
            if form == "ZD":
                value = _zoned(raw)
            elif form == "BI":
                value = int.from_bytes(raw, "big")
            else:
                value = raw
            parts.append(_Descending(value) if order == "D" else value)
        return tuple(parts)

    return key


def line_framed(data: bytes, record_length: int | None) -> bool:
    """Whether *data* is LINE SEQUENTIAL: newline-terminated records, none
    longer than the LRECL when one is known (GnuCOBOL strips trailing
    blanks, so lines may be shorter, #441)."""
    if not data.endswith(b"\n"):
        return False
    if record_length is None:
        return True
    return all(len(line) <= record_length for line in data[:-1].split(b"\n"))


def split_records(data: bytes, record_length: int | None) -> list[bytes]:
    """The records of *data*: newline-framed lines (each keeping its newline)
    when the data is LINE SEQUENTIAL, else LRECL-sized chunks. Framing that
    cannot be told for certain is a gap, never a guess."""
    if not data:
        return []
    if line_framed(data, record_length):
        return [line + b"\n" for line in data[:-1].split(b"\n")]
    if record_length:
        if len(data) % record_length:
            raise UtilityGap(
                f"{len(data)} bytes is not a whole number of {record_length}-byte records"
            )
        return [data[i : i + record_length] for i in range(0, len(data), record_length)]
    if b"\n" in data:
        raise UtilityGap("records are neither newline-terminated nor of a known LRECL")
    raise UtilityGap("record length unknown (no LRECL on the DD) for a sort")


def _without_newline(key: Callable[[bytes], tuple]) -> Callable[[bytes], tuple]:
    """*key* over a line record, its newline dropped (a key reaching past a
    short line reads blanks: see :func:`_record_key`)."""

    def stripped(record: bytes) -> tuple:
        return key(record[:-1] if record.endswith(b"\n") else record)

    return stripped


def refit_records(data: bytes, from_length: int, to_length: int) -> bytes:
    """*data*'s fixed *from_length* records, each padded with blanks or cut
    to *to_length* (DFSORT's PAD=RC0 / TRUNC=RC0, #460). Line-sequential
    data keeps its lines as they are."""
    if not data or line_framed(data, from_length):
        return data
    return b"".join(
        record[:to_length].ljust(to_length, b" ")
        for record in split_records(data, from_length)
    )


def sort_data(
    data: bytes, statements: list[tuple[str, str]], record_length: int | None
) -> bytes:
    key = sort_key(statements)
    if key is None:
        return data
    records = split_records(data, record_length)
    if records and line_framed(data, record_length):
        key = _without_newline(key)
    # A stable sort, as DFSORT's EQUALS: equal keys keep their input order.
    return b"".join(sorted(records, key=key))  # type: ignore[arg-type]
