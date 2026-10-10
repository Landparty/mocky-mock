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
- `EXEC SQL INCLUDE <member> END-EXEC` (member != SQLCA) is resolved the
  same way plain `COPY` is: a synthetic `COPY <member>.` snippet is
  expanded through cobolparser's public `expand_copybooks` against
  `copybook_paths`, and the (normalized) result is spliced in and
  re-scanned in place -- so a DCLGEN-style member's own embedded
  `EXEC SQL DECLARE ... TABLE ... END-EXEC` stanza gets commented out by
  this module's existing DECLARE-TABLE branch automatically. No
  `--copybook-path`, or the member can't be found, refuses
  UNRESOLVED_COPYBOOK (the same code plain unresolved COPY uses). A second,
  live `EXEC SQL INCLUDE` found while re-scanning already-spliced content
  refuses UNSUPPORTED_DATA_DIVISION_EXEC (only one level of resolution is
  supported). Any other unrecognized DATA DIVISION EXEC SQL (WHENEVER,
  ...) still fails closed the same way.

The generated SQLCA is intentionally *not* part of the parsed AST (it is
spliced in after parsing), so `reset.py`'s working-storage reset never
touches it; `sqlca_reset_lines` supplies its reset instead, so a SQLCODE
one case's mock set does not leak into the next (issue #148).
"""

from __future__ import annotations

import re

from mockymock._lines import split_source_lines
from mockymock.analysis.refusal import RefusalReason, check_expansion_warnings

SQLCA_FIELDS = [
    "01  SQLCA.",
    '    05  SQLCAID              PIC X(8)  VALUE "SQLCA   ".',
    "    05  SQLCABC              PIC S9(9) COMP-5 VALUE 136.",
    "    05  SQLCODE              PIC S9(9) COMP-5 VALUE 0.",
    "    05  SQLERRM.",
    "        49  SQLERRML         PIC S9(4) COMP-5 VALUE 0.",
    "        49  SQLERRMC         PIC X(70) VALUE SPACES.",
    "    05  SQLERRP              PIC X(8)  VALUE SPACES.",
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
    "    05  SQLSTATE             PIC X(5)  VALUE SPACES.",
]

_DATA_DIVISION_RE = re.compile(r"^\s*DATA\s+DIVISION\s*\.", re.IGNORECASE)
_PROCEDURE_DIVISION_RE = re.compile(r"^\s*PROCEDURE\s+DIVISION", re.IGNORECASE)
_EXEC_SQL_RE = re.compile(r"\bEXEC\s+SQL\b", re.IGNORECASE)
_END_EXEC_RE = re.compile(r"\bEND-EXEC\b", re.IGNORECASE)


def _in_literal(line: str, position: int) -> bool:
    """True when `position` falls inside a COBOL string literal ('...' or
    "...") opened earlier on the same line. A doubled quote inside a
    literal toggles closed-then-open again, which leaves the state
    correctly 'inside'. (Literals spanning normalized lines are not
    handled -- continuation merging happens upstream in
    normalize_fixed_format.)"""
    quote: str | None = None
    for character in line[:position]:
        if quote is None:
            if character in "'\"":
                quote = character
        elif character == quote:
            quote = None
    return quote is not None


def _comment_start(line: str) -> int | None:
    """Index of the first `*>` inline comment marker in `line` that is not
    inside a string literal, or None if there is none. Everything from that
    index onward is a COBOL free-form comment, live nowhere -- normalized
    free-form text only drops *column-7* `*`/`/` full-line comments
    upstream, so an inline `*>` (including one that starts right after the
    indicator area, e.g. `      *> EXEC SQL ...`) still reaches this
    scanner as ordinary text unless this function's caller strips it."""
    quote: str | None = None
    index = 0
    length = len(line)
    while index < length:
        character = line[index]
        if quote is None:
            if character in "'\"":
                quote = character
            elif character == "*" and index + 1 < length and line[index + 1] == ">":
                return index
        elif character == quote:
            quote = None
        index += 1
    return None


def _search_outside_literals(pattern: re.Pattern, line: str):
    """First match of `pattern` in `line` that is not inside a string
    literal and not inside a `*>` inline comment, or None -- so
    `VALUE "EXEC SQL ERROR"` never starts a bogus block scan, `VALUE
    "END-EXEC"` never terminates a real one early, and a commented-out
    `*> EXEC SQL ...` / `*> END-EXEC` never starts or ends a block scan
    either."""
    comment_start = _comment_start(line)
    for match in pattern.finditer(line):
        if comment_start is not None and match.start() >= comment_start:
            continue
        if not _in_literal(line, match.start()):
            return match
    return None


def _resolve_include_member(
    member: str, copybook_paths: list[str] | None
) -> tuple[list[str] | None, list[RefusalReason]]:
    """Resolve `member` the same way plain COPY is resolved: build a
    synthetic `COPY <member>.` snippet and expand it through cobolparser's
    public `expand_copybooks` -- not a reimplementation of copybook path
    resolution, so INCLUDE resolves exactly the way COPY does (same
    extensions, same case rules, same path-traversal protection; see
    cobolparser.preprocess.path_resolver, which this module deliberately
    does not import -- it isn't in cobolparser.preprocess's __all__).
    Returns (normalized lines, []) on success, or (None, [<refusal>]) on
    failure -- never both a result and a reason."""
    if not copybook_paths:
        return None, [
            RefusalReason(
                code="UNRESOLVED_COPYBOOK",
                message=(
                    f"EXEC SQL INCLUDE {member} could not be resolved -- "
                    f"pass --copybook-path pointing at the copybook's "
                    f"directory"
                ),
            )
        ]

    from cobolparser.preprocess import (
        CopybookNotFoundError,
        expand_copybooks,
        normalize_fixed_format,
    )

    try:
        expansion = expand_copybooks(
            f"       COPY {member}.", copybook_paths=copybook_paths
        )
    except CopybookNotFoundError:
        return None, [
            RefusalReason(
                code="UNRESOLVED_COPYBOOK",
                message=(
                    f"EXEC SQL INCLUDE {member} could not be resolved in "
                    f"{copybook_paths} -- pass --copybook-path pointing at "
                    f"the copybook's directory"
                ),
            )
        ]
    except Exception as exc:  # noqa: BLE001 -- surfaced as a refusal
        # A member that COPYs itself, an over-deep/oversized chain, ...:
        # cobolparser raises (CircularReferenceError, NestingDepthError,
        # ...). The program's own COPY expansion already reports these
        # (checks.py); cobol-parser releases that do not expand EXEC SQL
        # INCLUDE themselves (1.8.x) only ever reach them here, where the
        # traceback escaped `lint`/`run`/`export`.
        return None, [
            RefusalReason(
                code="UNRESOLVED_COPYBOOK",
                message=f"EXEC SQL INCLUDE {member} could not be expanded: {exc}",
            )
        ]

    expansion_reasons = check_expansion_warnings(expansion)
    if expansion_reasons:
        return None, expansion_reasons

    normalized = split_source_lines(
        normalize_fixed_format(split_source_lines(expansion.expanded_source))
    )
    return normalized, []


def sqlca_reset_lines(lines: list[str]) -> list[str]:
    """Reset lines for the generated SQLCA, when `lines` (the output of
    `transform_data_division_exec`) carry it. It is spliced in after
    parsing, so `reset.py` never sees it, and a SQLCODE one case's mock
    left behind leaked into the next case (issue #148)."""
    stripped = {line.strip() for line in lines}
    if (
        not {SQLCA_FIELDS[0], SQLCA_FIELDS[1].strip(), SQLCA_FIELDS[2].strip()}
        <= stripped
    ):
        return []
    return [
        "INITIALIZE SQLCA",
        'MOVE "SQLCA   " TO SQLCAID',
        "MOVE 136 TO SQLCABC",
    ]


def transform_data_division_exec(
    lines: list[str],
    copybook_paths: list[str] | None = None,
) -> tuple[list[str], list[RefusalReason]]:
    """Return (new lines, refusal reasons) for the DATA DIVISION EXEC SQL
    blocks in already-normalized free-form `lines`.

    All transforms here replace or comment out WHOLE lines, so a block that
    shares a line with other content -- data-item text before the
    `EXEC SQL`, or trailing content after the `END-EXEC.` -- refuses
    (UNSUPPORTED_DATA_DIVISION_EXEC) instead of silently deleting the
    sibling content. `EXEC SQL` / `END-EXEC` appearing inside VALUE-clause
    string literals is ignored entirely (see `_search_outside_literals`).

    `copybook_paths` is threaded through to a resolved EXEC SQL INCLUDE
    member's content -- see `_resolve_include_member`. When an INCLUDE is
    resolved, the scan does NOT advance past the newly-spliced lines
    (`include_splice_end` tracks the boundary instead): this lets the
    DECLARE-TABLE/DECLARE-CURSOR/BEGIN-END-DECLARE-SECTION branches below
    catch content the resolved member itself embeds (a DCLGEN copybook
    always carries its own `EXEC SQL DECLARE ... TABLE ... END-EXEC`) with
    no separate recursion path, while a second live INCLUDE found inside
    that re-scanned region refuses instead of resolving (only one level of
    INCLUDE resolution is supported)."""
    result = list(lines)
    reasons: list[RefusalReason] = []

    in_data_division = False
    include_splice_end: int | None = None
    index = 0
    while index < len(result):
        if include_splice_end is not None and index >= include_splice_end:
            include_splice_end = None
        line = result[index]
        exec_match = None
        if _DATA_DIVISION_RE.match(line):
            in_data_division = True
        elif _PROCEDURE_DIVISION_RE.match(line):
            in_data_division = False
        elif in_data_division:
            exec_match = _search_outside_literals(_EXEC_SQL_RE, line)
        if exec_match is not None:
            end = index
            end_match = _search_outside_literals(_END_EXEC_RE, result[end])
            while end_match is None:
                end += 1
                if end == len(result):
                    break
                end_match = _search_outside_literals(_END_EXEC_RE, result[end])
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
            shared_line_problem = _shared_line_problem(
                result, index, exec_match, end, end_match
            )
            if shared_line_problem is not None:
                reasons.append(shared_line_problem)
                index = end + 1
                continue
            block = " ".join(
                " ".join(result[i].upper().split()) for i in range(index, end + 1)
            )
            nested_include = include_splice_end is not None
            index, splice_end = _handle_block(
                result, index, end, block, reasons, copybook_paths, nested_include
            )
            if splice_end is not None:
                include_splice_end = splice_end
            continue
        index += 1

    return result, reasons


def _shared_line_problem(
    result: list[str],
    start: int,
    exec_match,
    end: int,
    end_match,
) -> RefusalReason | None:
    """UNSUPPORTED_DATA_DIVISION_EXEC when the block's first line has
    content before `EXEC SQL` or its last line has content after the
    `END-EXEC` (and its optional period) -- whole-line replacement would
    delete that sibling content, so fail closed instead."""
    prefix = result[start][: exec_match.start()]
    if prefix.strip():
        return RefusalReason(
            code="UNSUPPORTED_DATA_DIVISION_EXEC",
            message=(
                f"EXEC SQL block at line {start + 1} shares its first line "
                f"with other DATA DIVISION content ({prefix.strip()[:40]!r}) "
                f"-- whole-line replacement would delete it; put the EXEC "
                f"SQL block on its own line(s)"
            ),
        )
    trailing = result[end][end_match.end() :].lstrip()
    trailing = trailing.removeprefix(".").strip()
    if trailing:
        return RefusalReason(
            code="UNSUPPORTED_DATA_DIVISION_EXEC",
            message=(
                f"EXEC SQL block ending at line {end + 1} has trailing "
                f"content after its END-EXEC ({trailing[:40]!r}) -- "
                f"whole-line replacement would delete it; put the content "
                f"on its own line"
            ),
        )
    return None


def _handle_block(
    result: list[str],
    start: int,
    end: int,
    block: str,
    reasons: list[RefusalReason],
    copybook_paths: list[str] | None,
    nested_include: bool,
) -> tuple[int, int | None]:
    """Apply the transform for one EXEC SQL block spanning result[start:end+1]
    (already uppercased/whitespace-collapsed into `block`). Returns (next
    scan index, splice-end index or None) -- the second element is set only
    when this call spliced in a resolved EXEC SQL INCLUDE member's content,
    so the caller can track "inside spliced INCLUDE content" for the
    nested-INCLUDE refusal. The first element is `start` (not past the
    splice) exactly when that happens, so the caller re-scans the newly
    inserted lines instead of skipping them."""
    if re.search(r"\bINCLUDE\s+SQLCA\b", block):
        replacement = [
            "      *> EXEC SQL INCLUDE SQLCA replaced by mockymock-generated SQLCA:"
        ] + [f"       {field}" for field in SQLCA_FIELDS]
        result[start : end + 1] = replacement
        return start + len(replacement), None

    if re.search(r"\b(BEGIN|END)\s+DECLARE\s+SECTION\b", block) or re.search(
        r"\bDECLARE\b.*\b(TABLE|CURSOR)\b", block
    ):
        for i in range(start, end + 1):
            if result[i].strip():
                result[i] = "      *> " + result[i]
        return end + 1, None

    include_match = re.search(r"\bINCLUDE\s+(\S+)", block)
    if include_match:
        member = include_match.group(1).rstrip(".")
        if nested_include:
            reasons.append(
                RefusalReason(
                    code="UNSUPPORTED_DATA_DIVISION_EXEC",
                    message=(
                        f"EXEC SQL INCLUDE {member} at line {start + 1} is "
                        f"nested inside another resolved EXEC SQL INCLUDE -- "
                        f"only one level of EXEC SQL INCLUDE resolution is "
                        f"supported; inline {member}'s content directly"
                    ),
                )
            )
            return end + 1, None
        resolved_lines, resolve_reasons = _resolve_include_member(
            member, copybook_paths
        )
        if resolved_lines is None:
            reasons.extend(resolve_reasons)
            return end + 1, None
        replacement = [
            f"      *> EXEC SQL INCLUDE {member} replaced by resolved "
            f"copybook content:"
        ] + resolved_lines
        result[start : end + 1] = replacement
        new_index = start + len(replacement)
        return start, new_index

    reasons.append(
        RefusalReason(
            code="UNSUPPORTED_DATA_DIVISION_EXEC",
            message=(
                f"unrecognized DATA DIVISION EXEC SQL block at line "
                f"{start + 1}: {block[:80]!r} -- fail closed"
            ),
        )
    )
    return end + 1, None
