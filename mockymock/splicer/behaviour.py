"""Behaviour trace: what a run sends out of the program, for baselines.

`mockymock run --record-baseline FILE` and `--baseline FILE` compile the
suite with this instrumentation on. Every mocked boundary a case reaches
prints one `EVENT` marker, followed by one `DATA` marker per value the
program hands to that boundary:

* a CALL (static, dynamic, MQ): each USING argument, as the program
  passed it (before the mock body runs);
* a WRITE / REWRITE / RELEASE: the record, after its FROM copy;
* an EXEC SQL statement: each host variable outside an INTO list; an
  `OPEN cursor` is followed by a `SQL CURSOR <name>` event with the
  host variables of that cursor's DECLARE (what DB2 reads at OPEN);
* an EXEC CICS command: each FROM / COMMAREA / INTO-free data option.

Other boundaries (OPEN, READ, ACCEPT, ...) print the EVENT alone: what
they send out is nothing, and what they answer is the mock's.

At the end of each case, a program entered with parameters (its
PROCEDURE DIVISION USING items, or a CICS program's DFHCOMMAREA) prints a
`RETURNED LINKAGE` event with the bytes of each: that is what a called
program or a LINKed CICS program hands back to its caller.

A value is printed as hexadecimal by `UTHEXDMP`, a small program compiled
into the same binary, so a COMP-3 or binary field reaches the report byte
for byte (stdout is decoded as UTF-8 with replacement, which would merge
different non-text bytes). `UTHEXDMP` takes the item by reference and its
`LENGTH OF`, so it works on any item without the GnuCOBOL 3.2
`FUNCTION HEX-OF`. At most `MAX_BYTES` bytes are printed per value; a
longer one ends in `+`.

USE REAL CALL sites print nothing: a call between programs of the same
load module is an implementation detail, and a refactor may change it.
See docs/2026-11-01-baseline-design.md.
"""

from __future__ import annotations

import re

from mockymock.splicer.io_copy import IORewriteStatement, IOWriteStatement

#: The helper program's name (a 8-character IBM program name).
HEXDUMP_PROGRAM = "UTHEXDMP"
#: The length field each instrumented program declares.
LENGTH_FIELD = "UT-BT-LEN"
LENGTH_DECLARATION = f"01  {LENGTH_FIELD}  PIC 9(8) COMP-5."
#: Bytes printed per value at most.
MAX_BYTES = 32768

_NAME = r"[A-Z0-9][A-Z0-9-]*"
_DATA_NAME_RE = re.compile(
    rf"^{_NAME}(?:\s+(?:OF|IN)\s+{_NAME})*(?:\s*\([^()]*\))?(?:\s*\([^()]*\))?$",
    re.IGNORECASE,
)
_FIGURATIVE = frozenset(
    {
        "OMITTED",
        "SPACE",
        "SPACES",
        "ZERO",
        "ZEROS",
        "ZEROES",
        "HIGH-VALUE",
        "HIGH-VALUES",
        "LOW-VALUE",
        "LOW-VALUES",
        "QUOTE",
        "QUOTES",
        "NULL",
        "NULLS",
    }
)
# A host variable: `:NAME`, `:GROUP.NAME`, with an optional indicator
# `:NAME:IND` / `:NAME INDICATOR :IND` (each becomes its own reference).
_HOST_VAR_RE = re.compile(rf":\s*({_NAME}(?:\.{_NAME})*)", re.IGNORECASE)
# `INTO :a, :b :ind, ...` up to the next keyword: values the statement
# fills, not values the program sends.
_INTO_LIST_RE = re.compile(
    rf"\bINTO\s+((?:(?:INDICATOR\s+)?:\s*{_NAME}(?:\.{_NAME})*\s*,?\s*)+)",
    re.IGNORECASE,
)
# CICS options that carry data out of the program.
_CICS_DATA_RE = re.compile(
    r"\b(FROM|COMMAREA|CHANNEL-DATA)\s*\(\s*([^()]+?(?:\([^()]*\))?)\s*\)",
    re.IGNORECASE,
)


#: Label of the pseudo-event that follows `SQL OPEN` with the cursor's
#: DECLARE host variables, and of the end-of-case LINKAGE event.
CURSOR_EVENT = "SQL CURSOR"
RETURNED_EVENT = "RETURNED LINKAGE"
#: Events a version-1 baseline never had (see report.baseline).
V2_EVENT_PREFIXES = (CURSOR_EVENT + " ", RETURNED_EVENT)

_DECLARE_CURSOR_RE = re.compile(
    rf"EXEC\s+SQL\s+DECLARE\s+({_NAME})\s+(?:(?:NO\s+)?SCROLL\s+|"
    rf"(?:IN)?SENSITIVE\s+(?:STATIC\s+|DYNAMIC\s+)?SCROLL\s+|ASENSITIVE\s+)?"
    rf"CURSOR\b(.*?)END-EXEC",
    re.IGNORECASE | re.DOTALL,
)
_OPEN_CURSOR_RE = re.compile(rf"\bSQL\s+OPEN\s+({_NAME})", re.IGNORECASE)


def cursor_host_variables(source_lines: list[str]) -> dict[str, list[str]]:
    """Host variables of each `EXEC SQL DECLARE c CURSOR FOR ...`, by
    cursor name (upper case). A cursor over a prepared statement
    (`FOR stmt`) has none: its inputs are the OPEN's own USING list."""
    text = "\n".join(
        line.split("*>", 1)[0] for line in source_lines if line[:1] not in ("*", "/")
    )
    out: dict[str, list[str]] = {}
    for match in _DECLARE_CURSOR_RE.finditer(text):
        names = sql_host_variables(match.group(2))
        if names:
            out[match.group(1).upper()] = names
    return out


def opened_cursor(statement_text: str) -> str | None:
    """The cursor an `EXEC SQL OPEN c` statement opens, upper case."""
    match = _OPEN_CURSOR_RE.search(statement_text)
    return match.group(1).upper() if match else None


def returned_items(program: object) -> list[str]:
    """What a program hands back to its caller: its default entry's
    PROCEDURE DIVISION USING items and, for a CICS program, DFHCOMMAREA
    when its LINKAGE SECTION declares one."""
    names: list[str] = []
    procedure = program.get_division("PROCEDURE")  # type: ignore[attr-defined]
    if procedure is not None:
        for name in procedure.get_metadata("using_parameters") or []:
            text = str(name).upper()
            if _is_data_name(text) and text not in names:
                names.append(text)
    data = program.get_division("DATA")  # type: ignore[attr-defined]
    sections = getattr(data, "_sections", {}) if data is not None else {}
    linkage = sections.get("LINKAGE")
    for item in getattr(linkage, "data_items", None) or []:
        name = str(getattr(item, "name", "") or "").upper()
        if name == "DFHCOMMAREA" and name not in names:
            names.append(name)
    return names


def returned_lines(names: list[str], indent: str) -> list[str]:
    """The end-of-case `RETURNED LINKAGE` event and one dump per item."""
    if not names:
        return []
    lines = [f'{indent}DISPLAY "__MOCKYMOCK__ EVENT: {RETURNED_EVENT}"']
    for name in names:
        lines.extend(dump_lines(name, indent))
    return lines


def event_line(label: str, key: str, indent: str) -> str:
    """The EVENT marker for one firing of a mocked boundary."""
    safe = f"{label} {key}".replace('"', "'")
    return f'{indent}DISPLAY "__MOCKYMOCK__ EVENT: {safe}"'


def dump_lines(name: str, indent: str) -> list[str]:
    """Print one data item's bytes as a DATA marker."""
    return [
        f"{indent}MOVE LENGTH OF {name} TO {LENGTH_FIELD}",
        f'{indent}CALL "{HEXDUMP_PROGRAM}" USING {name} {LENGTH_FIELD}',
    ]


def _is_data_name(text: str) -> bool:
    stripped = text.strip()
    if not stripped or stripped.upper() in _FIGURATIVE:
        return False
    if stripped[0] in "\"'" or re.match(r"^[+-]?\d", stripped):
        return False
    if re.match(r"^(ADDRESS|LENGTH)\s+OF\b", stripped, re.IGNORECASE):
        return False
    return _DATA_NAME_RE.match(stripped) is not None


def _host_name(reference: str) -> str:
    """`GROUP.FIELD` -> `FIELD OF GROUP` (COBOL qualification)."""
    parts = [part for part in reference.split(".") if part]
    return " OF ".join(reversed(parts))


def sql_host_variables(statement_text: str) -> list[str]:
    """Host variables an EXEC SQL statement sends, in order, without
    duplicates; those in an INTO list are left out."""
    sent = _INTO_LIST_RE.sub(" ", statement_text)
    names: list[str] = []
    for match in _HOST_VAR_RE.finditer(sent):
        name = _host_name(match.group(1).upper())
        if name not in names:
            names.append(name)
    return names


def cics_data_items(statement_text: str) -> list[str]:
    """Data items an EXEC CICS command sends (FROM, COMMAREA)."""
    names: list[str] = []
    for match in _CICS_DATA_RE.finditer(statement_text):
        name = match.group(2).strip()
        if _is_data_name(name) and name.upper() not in names:
            names.append(name.upper())
    return names


def payload_names(
    statement: object, statement_text: str, category_value: str
) -> list[str | None]:
    """What one boundary statement sends out, in order. None stands for
    an argument that is not a data item (a literal, OMITTED, ADDRESS OF):
    the marker says so, and the slot keeps argument positions aligned."""
    from cobolparser.models.statements import CallStatement, ReleaseStatement

    if isinstance(statement, CallStatement):
        return [
            str(param.name) if _is_data_name(str(param.name)) else None
            for param in statement.using_parameters
        ]
    if isinstance(statement, (IOWriteStatement, IORewriteStatement, ReleaseStatement)):
        record = getattr(statement, "record_name", None)
        return [str(record)] if record and _is_data_name(str(record)) else []
    if category_value == "SQL":
        return list(sql_host_variables(statement_text))
    if category_value == "CICS":
        return list(cics_data_items(statement_text))
    return []


def site_lines(
    label: str,
    key: str,
    statement: object,
    statement_text: str,
    category_value: str,
    indent: str,
    cursor_hosts: dict[str, list[str]] | None = None,
) -> list[str]:
    """The EVENT marker and the DATA dumps for one mocked site's branch.

    `cursor_hosts` (`cursor_host_variables`): an `OPEN` of a cursor whose
    DECLARE names host variables is followed by a `SQL CURSOR <name>`
    event carrying them, since DB2 reads them at OPEN."""
    lines = [event_line(label, key, indent)]
    for name in payload_names(statement, statement_text, category_value):
        if name is None:
            lines.append(f'{indent}DISPLAY "__MOCKYMOCK__ DATA: -"')
        else:
            lines.extend(dump_lines(name, indent))
    if category_value == "SQL" and cursor_hosts:
        cursor = opened_cursor(statement_text)
        hosts = cursor_hosts.get(cursor or "")
        if cursor and hosts:
            lines.append(event_line(CURSOR_EVENT, cursor, indent))
            for name in hosts:
                lines.extend(dump_lines(name, indent))
    return lines


def hexdump_program() -> list[str]:
    """Free-form source of `UTHEXDMP`, compiled into the test binary."""
    return [
        "       IDENTIFICATION DIVISION.",
        f"       PROGRAM-ID. {HEXDUMP_PROGRAM}.",
        "       DATA DIVISION.",
        "       WORKING-STORAGE SECTION.",
        '       01  UT-HX-DIGITS PIC X(16) VALUE "0123456789ABCDEF".',
        "       01  UT-HX-I      PIC 9(8) COMP-5.",
        "       01  UT-HX-N      PIC 9(8) COMP-5.",
        "       01  UT-HX-B      PIC 9(4) COMP-5.",
        "       01  UT-HX-HI     PIC 9(4) COMP-5.",
        "       01  UT-HX-LO     PIC 9(4) COMP-5.",
        "       01  UT-HX-MORE   PIC X.",
        f"       01  UT-HX-OUT    PIC X({MAX_BYTES * 2}).",
        "       LINKAGE SECTION.",
        f"       01  L-DATA       PIC X({MAX_BYTES}).",
        "       01  L-LEN        PIC 9(8) COMP-5.",
        "       PROCEDURE DIVISION USING L-DATA L-LEN.",
        "           MOVE L-LEN TO UT-HX-N",
        "           MOVE SPACE TO UT-HX-MORE",
        f"           IF UT-HX-N > {MAX_BYTES}",
        f"               MOVE {MAX_BYTES} TO UT-HX-N",
        '               MOVE "+" TO UT-HX-MORE',
        "           END-IF",
        "           IF UT-HX-N = 0",
        '               DISPLAY "__MOCKYMOCK__ DATA: "',
        "               GOBACK",
        "           END-IF",
        "           PERFORM VARYING UT-HX-I FROM 1 BY 1 UNTIL UT-HX-I > UT-HX-N",
        "               COMPUTE UT-HX-B = FUNCTION ORD(L-DATA(UT-HX-I:1)) - 1",
        "               DIVIDE UT-HX-B BY 16 GIVING UT-HX-HI REMAINDER UT-HX-LO",
        "               MOVE UT-HX-DIGITS(UT-HX-HI + 1:1)",
        "                 TO UT-HX-OUT(UT-HX-I * 2 - 1:1)",
        "               MOVE UT-HX-DIGITS(UT-HX-LO + 1:1)",
        "                 TO UT-HX-OUT(UT-HX-I * 2:1)",
        "           END-PERFORM",
        '           IF UT-HX-MORE = "+"',
        '               DISPLAY "__MOCKYMOCK__ DATA: " UT-HX-OUT(1:UT-HX-N * 2) "+"',
        "           ELSE",
        '               DISPLAY "__MOCKYMOCK__ DATA: " UT-HX-OUT(1:UT-HX-N * 2)',
        "           END-IF",
        "           GOBACK.",
        f"       END PROGRAM {HEXDUMP_PROGRAM}.",
    ]
