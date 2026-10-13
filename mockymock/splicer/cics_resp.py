"""Expands `DFHRESP(<condition>)` the way the CICS translator does: into the
condition's literal EIBRESP number.

GnuCOBOL has no CICS translator, so an unexpanded `DFHRESP(NORMAL)` is a
compile error, and `refusal.check_cics_eib_layout` refused every program that
used one. But unlike `DFHVALUE` (hundreds of CVDA values), the DFHRESP table
is small, and IBM appends to it without ever renumbering: `NORMAL` has been 0
and `NOTFND` 13 since CICS/VS. So the translator's own substitution can be
reproduced exactly, and this module does that before the gate runs. Anything
it does not expand (DFHVALUE, a condition name missing from the table, a call
continued across lines, a call inside a string literal) is left for the gate
to handle exactly as before, fail closed.

The rewrite is column- and line-preserving (`stub_writer.replace_columns`,
space-padded to the call's own width), like `splicer.linkage`'s
`redirect_address_of`, so nothing any `SourceLocation` indexes into moves.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from mockymock.splicer.stub_writer import replace_columns

# EIBRESP decimal values, from IBM's "Response codes of EXEC CICS commands"
# (CICS TS 6.x) cross-checked against the complete EIBRESP list. Values not
# confirmed by both are deliberately absent: a wrong number would make a
# test silently take the wrong branch, whereas a missing one only refuses.
# DSIDERR is FILENOTFOUND's pre-CICS TS name, still accepted by the
# translator.
DFHRESP_VALUES: dict[str, int] = {
    "NORMAL": 0,
    "ERROR": 1,
    "RDATT": 2,
    "WRBRK": 3,
    "EOF": 4,
    "EODS": 5,
    "EOC": 6,
    "INBFMH": 7,
    "ENDINPT": 8,
    "NONVAL": 9,
    "NOSTART": 10,
    "TERMIDERR": 11,
    "FILENOTFOUND": 12,
    "DSIDERR": 12,
    "NOTFND": 13,
    "DUPREC": 14,
    "DUPKEY": 15,
    "INVREQ": 16,
    "IOERR": 17,
    "NOSPACE": 18,
    "NOTOPEN": 19,
    "ENDFILE": 20,
    "ILLOGIC": 21,
    "LENGERR": 22,
    "QZERO": 23,
    "SIGNAL": 24,
    "QBUSY": 25,
    "ITEMERR": 26,
    "PGMIDERR": 27,
    "TRANSIDERR": 28,
    "ENDDATA": 29,
    "EXPIRED": 31,
    "RETPAGE": 32,
    "RTEFAIL": 33,
    "RTESOME": 34,
    "TSIOERR": 35,
    "MAPFAIL": 36,
    "INVERRTERM": 37,
    "INVMPSZ": 38,
    "IGREQID": 39,
    "OVERFLOW": 40,
    "INVLDC": 41,
    "NOSTG": 42,
    "JIDERR": 43,
    "QIDERR": 44,
    "NOJBUFSP": 45,
    "DSSTAT": 46,
    "SELNERR": 47,
    "FUNCERR": 48,
    "UNEXPIN": 49,
    "NOPASSBKRD": 50,
    "NOPASSBKWR": 51,
    "SYSIDERR": 53,
    "ISCINVREQ": 54,
    "ENQBUSY": 55,
    "ENVDEFERR": 56,
    "IGREQCD": 57,
    "SESSIONERR": 58,
    "SYSBUSY": 59,
    "SESSBUSY": 60,
    "NOTALLOC": 61,
    "CBIDERR": 62,
    "INVEXITREQ": 63,
    "INVPARTNSET": 64,
    "INVPARTN": 65,
    "PARTNFAIL": 66,
    "USERIDERR": 69,
    "NOTAUTH": 70,
    "VOLIDERR": 71,
    "SUPPRESSED": 72,
    "NOSPOOL": 80,
    "TERMERR": 81,
    "ROLLEDBACK": 82,
    "END": 83,
    "DISABLED": 84,
    "ALLOCERR": 85,
    "STRELERR": 86,
    "OPENERR": 87,
    "SPOLBUSY": 88,
    "SPOLERR": 89,
    "NODEIDERR": 90,
    "TASKIDERR": 91,
    "TCIDERR": 92,
    "DSNNOTFOUND": 93,
    "LOADING": 94,
    "MODELIDERR": 95,
    "OUTDESCRERR": 96,
    "PARTNERIDERR": 97,
    "PROFILEIDERR": 98,
    "NETNAMEIDERR": 99,
    "LOCKED": 100,
    "RECORDBUSY": 101,
    "UOWNOTFOUND": 102,
    "UOWLNOTFOUND": 103,
    "LINKABEND": 104,
    "CHANGED": 105,
    "PROCESSBUSY": 106,
    "ACTIVITYBUSY": 107,
    "PROCESSERR": 108,
    "ACTIVITYERR": 109,
    "CONTAINERERR": 110,
    "EVENTERR": 111,
    "TOKENERR": 112,
    "NOTFINISHED": 113,
    "POOLERR": 114,
    "TIMERERR": 115,
    "SYMBOLERR": 116,
    "TEMPLATERR": 117,
    "CSDERR": 119,
    "DUPRES": 120,
    "RESUNAVAIL": 121,
    "CHANNELERR": 122,
    "CCSIDERR": 123,
    "TIMEDOUT": 124,
    "INCOMPLETE": 126,
    "BUSY": 128,
}

# Same name-boundary convention as `refusal._CICS_MACRO_CALL_RE`.
_DFHRESP_CALL_RE = re.compile(
    r"(?<![A-Za-z0-9-])DFHRESP\s*\(\s*([A-Za-z0-9$@#-]+)\s*\)", re.IGNORECASE
)
_STRING_RE = re.compile(r""""(?:[^"]|"")*"?|'(?:[^']|'')*'?""")


@dataclass(frozen=True)
class RespExpansion:
    line: int  # 1-indexed into the normalized text
    condition: str
    value: int


def expand_dfhresp(lines: list[str]) -> tuple[list[str], list[RespExpansion]]:
    """Every single-line `DFHRESP(<known condition>)` outside a string
    literal, overwritten by its EIBRESP number. Returns the new lines and
    what was expanded, in source order."""
    expansions: list[RespExpansion] = []
    for index, text in enumerate(lines, start=1):
        strings = [(m.start(), m.end()) for m in _STRING_RE.finditer(text)]
        hits = []
        for call in _DFHRESP_CALL_RE.finditer(text):
            if any(start <= call.start() < end for start, end in strings):
                continue
            condition = call.group(1).upper()
            value = DFHRESP_VALUES.get(condition)
            if value is None:
                continue
            hits.append((call.start(), call.end(), condition, value))
        # Right to left, so one rewrite cannot move the next one's columns
        # (they cannot anyway -- the rewrite is width-preserving -- but this
        # keeps the invariant local rather than inherited).
        for start, end, _, value in reversed(hits):
            lines = replace_columns(lines, index, start, end, str(value))
        expansions.extend(
            RespExpansion(line=index, condition=condition, value=value)
            for _, _, condition, value in hits
        )
    return lines, expansions


def expand_dfhresp_text(text: str) -> tuple[str, list[str]]:
    """The `.cut` counterpart of `expand_dfhresp`, for one line of suite
    text (mock bodies, ROWS/TERMINAL values, setup MOVEs, EXPECT values):
    every `DFHRESP(<known condition>)` outside a string literal and before
    an inline `*>` comment, replaced by its EIBRESP number. Not
    width-preserving -- .cut text has no column contract. Returns the new
    text and every condition name that is not in `DFHRESP_VALUES` (left
    unexpanded; the caller refuses them, since the compile error they would
    otherwise become names no .cut line)."""
    strings = [(m.start(), m.end()) for m in _STRING_RE.finditer(text)]

    def in_string(pos: int) -> bool:
        return any(start <= pos < end for start, end in strings)

    comment = next(
        (m.start() for m in re.finditer(r"\*>", text) if not in_string(m.start())),
        len(text),
    )
    unknown: list[str] = []

    def repl(call: re.Match[str]) -> str:
        if call.start() >= comment or in_string(call.start()):
            return call.group(0)
        condition = call.group(1).upper()
        value = DFHRESP_VALUES.get(condition)
        if value is None:
            unknown.append(condition)
            return call.group(0)
        return str(value)

    return _DFHRESP_CALL_RE.sub(repl, text), unknown


def expansion_note(expansions: list[RespExpansion]) -> str:
    """One transparency line naming every condition expanded (callers add
    their own `mockymock <command>:` prefix, as for every other note)."""
    pairs = sorted({(e.condition, e.value) for e in expansions}, key=lambda p: p[1])
    listed = ", ".join(f"{name}={value}" for name, value in pairs)
    return (
        f"expanded {len(expansions)} DFHRESP(...) call(s) "
        f"to their EIBRESP values ({listed}), as the CICS translator would"
    )
