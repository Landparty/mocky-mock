"""DATA DIVISION EXEC SQL handling on the normalized free-form text.

GnuCOBOL cannot process any EXEC SQL block, including the declarative ones
that live in the DATA DIVISION, so before compiling:

- `EXEC SQL INCLUDE SQLCA END-EXEC` is replaced by a generated standard
  SQLCA group item so mock bodies can set SQLCODE/SQLSTATE/SQLERRD.
- `EXEC SQL BEGIN/END DECLARE SECTION END-EXEC` is commented out (the host
  variables between them are plain COBOL and stay).
- `EXEC SQL DECLARE ... TABLE ... END-EXEC` and `EXEC SQL DECLARE <cursor>
  CURSOR FOR SELECT ... END-EXEC` are commented out (declarative only, no
  runtime effect -- the cursor's OPEN/FETCH/CLOSE statements later in the
  PROCEDURE DIVISION are separate EXEC SQL statements handled by the
  boundary-mocking machinery, not by this module).
- Any other DATA DIVISION EXEC SQL (INCLUDE <member>, WHENEVER, ...) is a
  whole-program refusal (UNSUPPORTED_DATA_DIVISION_EXEC): an INCLUDE pulls
  in host-variable declarations this tool cannot resolve (same spirit as
  UNRESOLVED_COPYBOOK), and anything unrecognized fails closed.

The generated SQLCA is intentionally *not* part of the parsed AST (it is
spliced in after parsing), so `reset.py`'s working-storage reset never
touches it -- mock bodies are expected to set SQLCODE explicitly in every
case, which the scaffold generator's placeholder bodies do.
"""

from __future__ import annotations

import re

from mockymock.analysis.refusal import RefusalReason

SQLCA_FIELDS = [
    "01  SQLCA.",
    '    05  SQLCAID              PIC X(8)  VALUE "SQLCA   ".',
    "    05  SQLCABC              PIC S9(9) COMP-5 VALUE 136.",
    "    05  SQLCODE              PIC S9(9) COMP-5 VALUE 0.",
    "    05  SQLERRM.",
    "        49  SQLERRML         PIC S9(4) COMP-5 VALUE 0.",
    "        49  SQLERRMC         PIC X(70) VALUE SPACES.",
    '    05  SQLERRP              PIC X(8)  VALUE SPACES.',
    "    05  SQLERRD              PIC S9(9) COMP-5 OCCURS 6 TIMES.",
    "    05  SQLWARN.",
    "        10  SQLWARN0         PIC X(1)  VALUE SPACE.",
    "        10  SQLWARN1         PIC X(1)  VALUE SPACE.",
    "        10  SQLWARN2         PIC X(1)  VALUE SPACE.",
    "        10  SQLWARN3         PIC X(1)  VALUE SPACE.",
    "        10  SQLWARN4         PIC X(1)  VALUE SPACE.",
    "        10  SQLWARN5         PIC X(1)  VALUE SPACE.",
    "        10  SQLWARN6         PIC X(1)  VALUE SPACE.",
    "        10  SQLWARN7         PIC X(1)  VALUE SPACE.",
    '    05  SQLSTATE             PIC X(5)  VALUE SPACES.',
]

_DATA_DIVISION_RE = re.compile(r"^\s*DATA\s+DIVISION\s*\.", re.IGNORECASE)
_PROCEDURE_DIVISION_RE = re.compile(r"^\s*PROCEDURE\s+DIVISION", re.IGNORECASE)
_EXEC_SQL_RE = re.compile(r"\bEXEC\s+SQL\b", re.IGNORECASE)
_END_EXEC_RE = re.compile(r"\bEND-EXEC\b", re.IGNORECASE)


def transform_data_division_exec(
    lines: list[str],
) -> tuple[list[str], list[RefusalReason]]:
    """Return (new lines, refusal reasons) for the DATA DIVISION EXEC SQL
    blocks in already-normalized free-form `lines`."""
    result = list(lines)
    reasons: list[RefusalReason] = []

    in_data_division = False
    index = 0
    while index < len(result):
        line = result[index]
        if _DATA_DIVISION_RE.match(line):
            in_data_division = True
        elif _PROCEDURE_DIVISION_RE.match(line):
            in_data_division = False
        elif in_data_division and _EXEC_SQL_RE.search(line):
            end = index
            while end < len(result) and not _END_EXEC_RE.search(result[end]):
                end += 1
            if end == len(result):
                reasons.append(
                    RefusalReason(
                        code="UNSUPPORTED_DATA_DIVISION_EXEC",
                        message=(
                            f"EXEC SQL block starting at line {index + 1} has "
                            f"no END-EXEC"
                        ),
                    )
                )
                break
            block = " ".join(
                " ".join(result[i].upper().split()) for i in range(index, end + 1)
            )
            index = _handle_block(result, index, end, block, reasons)
            continue
        index += 1

    return result, reasons


def _handle_block(
    result: list[str], start: int, end: int, block: str, reasons: list[RefusalReason]
) -> int:
    """Apply the transform for one EXEC SQL block spanning result[start:end+1]
    (already uppercased/whitespace-collapsed into `block`). Returns the index
    scanning should continue from."""
    if re.search(r"\bINCLUDE\s+SQLCA\b", block):
        replacement = [
            "      *> EXEC SQL INCLUDE SQLCA replaced by mockymock-generated SQLCA:"
        ] + [f"       {field}" for field in SQLCA_FIELDS]
        result[start : end + 1] = replacement
        return start + len(replacement)

    if re.search(r"\b(BEGIN|END)\s+DECLARE\s+SECTION\b", block) or re.search(
        r"\bDECLARE\b.*\b(TABLE|CURSOR)\b", block
    ):
        for i in range(start, end + 1):
            if result[i].strip():
                result[i] = "      *> " + result[i]
        return end + 1

    if re.search(r"\bINCLUDE\s+(\S+)", block):
        member = re.search(r"\bINCLUDE\s+(\S+)", block).group(1).rstrip(".")
        reasons.append(
            RefusalReason(
                code="UNSUPPORTED_DATA_DIVISION_EXEC",
                message=(
                    f"EXEC SQL INCLUDE {member} at line {start + 1} pulls "
                    f"host-variable declarations from a precompiler member "
                    f"this tool cannot resolve -- inline the member's "
                    f"content (same spirit as UNRESOLVED_COPYBOOK)"
                ),
            )
        )
        return end + 1

    reasons.append(
        RefusalReason(
            code="UNSUPPORTED_DATA_DIVISION_EXEC",
            message=(
                f"unrecognized DATA DIVISION EXEC SQL block at line "
                f"{start + 1}: {block[:80]!r} -- fail closed"
            ),
        )
    )
    return end + 1
