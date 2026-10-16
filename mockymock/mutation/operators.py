"""Mutant generation: pure text/line-level site discovery, no Docker.

v1 operates on the ORIGINAL source lines (the file the user edits, before
`normalize_fixed_format`), so every reported mutant points at a line the
user can open. Discovery is deliberately conservative: a site is only
mutated when the whole match sits outside quoted literals, on a line that
is (a) inside the PROCEDURE DIVISION, (b) not a comment or a
continuation, (c) free of boundary verbs (those statements are
mocked/replaced by the splicer -- mutating them fights the harness
instead of testing the program), and (d) not a terminator (STOP RUN /
GOBACK lines are rewritten by the splicer's terminator plans). A skipped
real site costs one blind spot; a false site costs a stillborn compile
per mutant, so precision wins over recall throughout. AST-driven
discovery (via cobolparser statement nodes) is the documented v2 upgrade
path.

**Column discipline.** Every mutated line is rewritten *within columns
1-72* with the identification area (columns 73-80) pinned exactly where
it was. This is not cosmetic: mockymock feeds the patched source through
`normalize_fixed_format`, which slices columns 8-72 and discards the
rest, so a rewrite that grows the code (`ADD..TO` -> `SUBTRACT..FROM`
adds seven characters) silently loses its own tail, and one that shrinks
it (`>=` -> `>`) silently drags an identification-area character into
column 72. Both are guaranteed stillborns. `_rewrite_code` reclaims what
it can from interior whitespace and refuses the mutant when it cannot.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: 1-based last column of the program-text area. `normalize_fixed_format`
#: slices columns 8-72 and throws away everything past this, so a mutated
#: line whose code reaches beyond it is a stillborn by construction.
CODE_END_COL = 72
#: 1-based first column of the program-text area (Area A starts here).
TEXT_START_COL = 8


# Plain `\b` treats `-` as a boundary (it's not a `\w` character), so
# `\bREAD\b` false-matches inside an identifier like WS-READ-COUNT or
# WS-CALL-FLAG -- COBOL naming conventions routinely compose exactly these
# verbs with hyphens. A COBOL word boundary must also reject a neighboring
# `-` (or alphanumeric), which `\b` alone cannot express. Every verb and
# keyword pattern in this module must use it -- `\bADD\b` matches inside
# `GRP-FOR-ADD-CORR-R`, and the resulting `SUBTRACT`/`FROM` rewrite of an
# ordinary MOVE is a stillborn.
def _cobol_word(alternatives: str) -> str:
    return rf"(?<![A-Z0-9-])(?:{alternatives})(?![A-Z0-9-])"


# Statements the splicer owns: external boundaries (mocked) plus verbs the
# terminator/flow machinery rewrites. Any line where one of these appears
# as a word (outside literals) is excluded wholesale.
_EXCLUDED_VERBS = re.compile(
    _cobol_word(
        "CALL|CANCEL|ENTRY|EXEC|OPEN|CLOSE|READ|WRITE|REWRITE|DELETE|START"
        "|UNLOCK|ACCEPT|STOP|GOBACK|EXIT|SORT|MERGE|RELEASE|RETURN"
        "|INITIATE|GENERATE|TERMINATE"
    ),
    re.IGNORECASE,
)

# An EXEC SQL/CICS/DLI block runs from its EXEC to its END-EXEC, usually
# across several lines. The splicer replaces the whole statement, so no
# line of it -- not just the EXEC line `_EXCLUDED_VERBS` catches -- may
# yield a mutant: an SQL `WHEN BALANCE > 1000` or a `SET(ADDRESS OF X)`
# mutated there could never be killed.
_EXEC_OPEN = re.compile(_cobol_word("EXEC"), re.IGNORECASE)
_EXEC_CLOSE = re.compile(_cobol_word("END-EXEC"), re.IGNORECASE)

_PROCEDURE_DIVISION = re.compile(r"\bPROCEDURE\s+DIVISION\b", re.IGNORECASE)
# A source file can hold more than one program (nested or batched). Once
# either of these appears the PROCEDURE DIVISION we were in has ended, so
# discovery must fall back to "not in a procedure" until the next
# PROCEDURE DIVISION header -- otherwise the *next* program's DATA
# DIVISION is treated as mutable procedural code.
_PROGRAM_BOUNDARY = re.compile(
    r"\bEND\s+PROGRAM\b|\bIDENTIFICATION\s+DIVISION\b|\bID\s+DIVISION\b",
    re.IGNORECASE,
)

# A line whose only statement starts with one of these verbs may be
# replaced wholesale by CONTINUE (statement deletion). Conditional /
# scope-carrying lines are never deleted -- removing an IF or END-IF
# guarantees a stillborn (or worse, silently restructured) program.
_DELETABLE_VERB = re.compile(
    r"^(?:MOVE|ADD|SUBTRACT|COMPUTE|MULTIPLY|DIVIDE|INITIALIZE|SET)(?![A-Z0-9-])",
    re.IGNORECASE,
)
_SCOPE_TOKENS = re.compile(
    _cobol_word("IF|ELSE|EVALUATE|WHEN|PERFORM|UNTIL|VARYING") + r"|(?<![A-Z0-9-])END-",
    re.IGNORECASE,
)

# What may legally follow a *complete* statement. Deleting a line is only
# safe when the statement provably ends on it, and a period is the only
# self-evident proof; short of one, the next code line must open something
# new. Note which scope terminators are absent: `END-ADD` and friends bind
# to the very verb `_DELETABLE_VERB` deletes, so a line followed by one is
# a multi-line statement, not a complete one. `END-IF`/`END-PERFORM` and
# the rest belong to an enclosing construct and are fine.
_STATEMENT_OPENER = re.compile(
    _cobol_word(
        "ACCEPT|ADD|ALLOCATE|ALTER|CALL|CANCEL|CLOSE|COMMIT|COMPUTE|CONTINUE"
        "|DELETE|DISPLAY|DIVIDE|EJECT|ELSE|ENTRY|EVALUATE|EXEC|EXIT|FREE"
        "|GENERATE|GO|GOBACK|IF|INITIALIZE|INITIATE|INSPECT|INVOKE|JSON"
        "|MERGE|MOVE|MULTIPLY|OPEN|PERFORM|PURGE|RAISE|READ|RELEASE|RESUME"
        "|RETURN|REWRITE|ROLLBACK|SEARCH|SET|SORT|START|STOP|STRING"
        "|SUBTRACT|SUPPRESS|TERMINATE|UNLOCK|UNSTRING|USE|VALIDATE|WHEN"
        "|WRITE|XML"
        "|END-IF|END-PERFORM|END-EVALUATE|END-SEARCH|END-READ|END-WRITE"
        "|END-REWRITE|END-DELETE|END-START|END-CALL|END-ACCEPT|END-DISPLAY"
        "|END-STRING|END-UNSTRING|END-RETURN|END-EXEC|END-INVOKE|END-XML"
        "|END-JSON"
    ),
    re.IGNORECASE,
)
# `NAME.` / `NAME SECTION.` / `<x> DIVISION` / `END PROGRAM <name>.` --
# the other shapes that cannot be the tail of the previous statement.
# Area A is columns 8-11: a paragraph/section header starts there. A bare
# `NAME.` further right is a statement's last operand (`MOVE 1 TO WS-A` /
# `WS-B.`), not a header.
_AREA_B_COL = 12
# `END-IF.` is a scope terminator, not an operand, wherever it sits.
_BARE_NAME_LINE = re.compile(r"^(?!END-)[A-Z0-9][A-Z0-9-]*\s*\.", re.IGNORECASE)
_HEADER_LINE = re.compile(
    r"^(?:[A-Z0-9][A-Z0-9-]*(?:\s+SECTION)?\s*\."
    r"|[A-Z]+\s+DIVISION\b"
    r"|END\s+PROGRAM\b"
    r"|DECLARATIVES\s*\.)",
    re.IGNORECASE,
)
# A line ending in one of these is unambiguously mid-statement, whatever
# the next line looks like. This is what keeps `MOVE WS-A TO` / `WS-B.`
# (whose second line is indistinguishable from a paragraph header) out of
# the deletion set.
_DANGLING_TAIL = re.compile(
    _cobol_word(
        "TO|FROM|BY|INTO|GIVING|REMAINDER|OF|IN|AND|OR|NOT|USING|THRU"
        "|THROUGH|DELIMITED|POINTER|REPLACING|TALLYING|CORRESPONDING|CORR"
    )
    + r"\s*$|[=+\-*/(,]\s*$",
    re.IGNORECASE,
)

_CONDITION_CONTEXT = re.compile(_cobol_word("IF|UNTIL|WHEN"), re.IGNORECASE)

# Relational-symbol swaps, one mutant per occurrence. Compound symbols are
# matched before their single-character prefixes so `>=` never double-fires
# as `>` too.
_REL_SWAPS: list[tuple[str, str]] = [
    (">=", ">"),
    ("<=", "<"),
    (">", ">="),
    ("<", "<="),
]

_ADD_TO = re.compile(
    _cobol_word("ADD") + r"(?P<mid>.+?)" + _cobol_word("TO"), re.IGNORECASE
)
_SUBTRACT_FROM = re.compile(
    _cobol_word("SUBTRACT") + r"(?P<mid>.+?)" + _cobol_word("FROM"), re.IGNORECASE
)
_MULTIPLY_BY = re.compile(
    _cobol_word("MULTIPLY") + r"(?P<mid>.+?)" + _cobol_word("BY"), re.IGNORECASE
)
_DIVIDE_INTO = re.compile(
    _cobol_word("DIVIDE") + r"(?P<mid>.+?)" + _cobol_word("INTO"), re.IGNORECASE
)

_MOVE_INT = re.compile(
    _cobol_word("MOVE") + r"\s+(?P<value>\d+)\s+" + _cobol_word("TO"), re.IGNORECASE
)
# An integer directly following a relational symbol in a condition line --
# the loop/branch boundary itself. The integer must end on a COBOL word
# boundary: `\b` treats `-` as one, so `= 100-LIMIT` (a data name) would
# otherwise mutate into `= 101-LIMIT`.
_REL_INT = re.compile(r"([><]=?|=)\s*(\d+)(?![A-Za-z0-9-])")

_SPACE_RUN = re.compile(r"  +")


@dataclass(frozen=True)
class Mutant:
    """One candidate mutation: replace `original` (the full line at
    1-based `line` in the original source) with `mutated`."""

    line: int
    operator: str
    original: str
    mutated: str
    description: str


def _literal_mask(line: str) -> list[bool]:
    """True per character position inside a quoted literal (either quote
    style; the closing quote itself counts as inside). Doubled quotes
    inside a literal re-enter a literal immediately, which is close enough
    for a skip-mask."""
    mask = [False] * len(line)
    quote: str | None = None
    for i, char in enumerate(line):
        if quote is not None:
            mask[i] = True
            if char == quote:
                quote = None
        elif char in "'\"":
            quote = char
            mask[i] = True
    return mask


def _outside_literals(mask: list[bool], start: int, end: int) -> bool:
    return not any(mask[start:end])


def _is_comment(line: str) -> bool:
    stripped = line.lstrip()
    if stripped.startswith("*>"):
        return True
    # Fixed-format indicator column: column 7 (index 6) '*' or '/'.
    return len(line) > 6 and line[6] in "*/"


_DEBUGGING_MODE = re.compile(r"\bWITH\s+DEBUGGING\s+MODE\b", re.IGNORECASE)


def _is_debug_line(line: str) -> bool:
    """A `D` in the fixed-format indicator column: compiled only when the
    program declares WITH DEBUGGING MODE, a comment otherwise -- so a mutant
    on it can never be killed."""
    return len(line) > 6 and line[6] in "Dd"


def _is_compiler_directive(line: str) -> bool:
    """A `>>IF` / `>>DEFINE` / `>>EVALUATE` ... compiler-directing line.
    Its relational symbols and `IF` belong to the directive, not to the
    program's logic: `>>IF DEBUG > 1` must never become `>=>IF` (or
    `>>IF DEBUG >= 1`, which flips conditional compilation, not a
    branch)."""
    return line.lstrip().startswith(">>") or line[6:].lstrip().startswith(">>")


def _is_continuation(line: str) -> bool:
    """Fixed-format continuation line (indicator column `-`). Its text is
    a fragment of the previous line's statement -- often the tail of a
    split literal -- so neither the word-level matching nor the deletion
    rules below hold on it. Same best-effort indicator-column read as
    `_is_comment`."""
    return len(line) > 6 and line[6] == "-"


def _sequence_area_end(line: str) -> int:
    """Best-effort guard for fixed-format identification columns: an
    EXCLUSIVE slice end, so `line[: _sequence_area_end(line)]` is the
    program text through column 72 and nothing beyond it. Columns are
    1-based and indices are not, so column 72 is index 71 and the slice
    end is `CODE_END_COL` itself. Lines shorter than that (the common
    case in this repo's fixtures and modern sources) are unaffected."""
    return min(len(line), CODE_END_COL)


def _text_start(code: str) -> int:
    """Index of the first program-text character: the first non-blank at
    or after column 8, skipping the sequence area and the indicator
    column. Everything before it is layout that decides Area A vs Area B
    for the statement's first word."""
    i = TEXT_START_COL - 1
    while i < len(code) and code[i] == " ":
        i += 1
    return i


def _squeeze_code(code: str, needed: int) -> str | None:
    """Reclaim `needed` columns from `code` by collapsing runs of two or
    more spaces down to one, left to right. Only runs interior to the
    statement qualify: the sequence area and the indent that positions
    the statement's first word are never touched (collapsing those walks
    the statement leftwards into Area A), and neither is anything inside
    a quoted literal (that would change the program's data, not just its
    layout). Returns None when the line cannot give up that many
    columns."""
    head = _text_start(code)
    out = code
    while needed > 0:
        mask = _literal_mask(out)
        run = next(
            (
                m
                for m in _SPACE_RUN.finditer(out)
                if m.start() >= head and _outside_literals(mask, m.start(), m.end())
            ),
            None,
        )
        if run is None:
            return None
        drop = min(needed, run.end() - run.start() - 1)
        out = out[: run.end() - drop] + out[run.end() :]
        needed -= drop
    return out


def _rewrite_code(line: str, start: int, end: int, replacement: str) -> str | None:
    """Replace `line[start:end]` -- a span that must lie inside the code
    area -- with `replacement`, returning the whole rewritten line, or
    None when the result cannot be made to fit columns 1-72.

    The identification area (columns 73-80) is re-pinned to column 73
    rather than carried along by the edit, so neither a growing rewrite
    (its own tail falls off the end) nor a shrinking one (an
    identification character slides into column 72 and becomes code) can
    produce a line that means something other than what the mutant says
    it means.
    """
    tail = line[CODE_END_COL:]
    code = line[:CODE_END_COL]
    new_code = code[:start] + replacement + code[end:]
    overflow = len(new_code.rstrip()) - CODE_END_COL
    if overflow > 0:
        squeezed = _squeeze_code(new_code, overflow)
        if squeezed is None or len(squeezed.rstrip()) > CODE_END_COL:
            return None
        new_code = squeezed
    if not tail:
        return new_code
    return new_code[:CODE_END_COL].ljust(CODE_END_COL) + tail


def generate_mutants(lines: list[str]) -> list[Mutant]:
    """Walk the original source and produce every applicable mutant, in
    line order. Pure and deterministic; safe without Docker."""
    mutants: list[Mutant] = []
    in_procedure = False
    debugging_mode = any(_DEBUGGING_MODE.search(line) for line in lines)
    in_exec = False

    for index, line in enumerate(lines):
        line_no = index + 1
        if _is_comment(line) or _is_continuation(line):
            continue
        if _is_debug_line(line) and not debugging_mode:
            continue
        if _is_compiler_directive(line):
            continue
        if not in_procedure:
            if _PROCEDURE_DIVISION.search(line):
                in_procedure = True
            continue
        if _PROGRAM_BOUNDARY.search(line):
            in_procedure = False
            continue

        mask = _literal_mask(line)
        code_end = _sequence_area_end(line)
        code = line[:code_end]
        # Truncate at an inline `*>` comment (outside literals) so its text
        # -- including the `>` of the marker itself -- never yields a site.
        comment_at = code.find("*>")
        while comment_at != -1 and not _outside_literals(
            mask, comment_at, comment_at + 2
        ):
            comment_at = code.find("*>", comment_at + 1)
        if comment_at != -1:
            code = code[:comment_at]

        if in_exec:
            in_exec = _exec_block_open_after(code, mask, 0)
            continue
        opener = next(
            (
                m
                for m in _EXEC_OPEN.finditer(code)
                if _outside_literals(mask, m.start(), m.end())
            ),
            None,
        )
        if opener is not None:
            in_exec = _exec_block_open_after(code, mask, opener.end())
            continue

        excluded = any(
            _outside_literals(mask, m.start(), m.end())
            for m in _EXCLUDED_VERBS.finditer(code)
        )
        if excluded:
            continue

        mutants.extend(_relational_mutants(line, code, mask, line_no))
        mutants.extend(
            _arithmetic_verb_mutants(
                line, code, mask, line_no, _statement_tail(lines, index, code)
            )
        )
        mutants.extend(_move_literal_mutants(line, code, mask, line_no))
        mutants.extend(_boundary_literal_mutants(line, code, mask, line_no))
        deletion = _statement_deletion_mutant(lines, index, code, mask, line_no)
        if deletion is not None:
            mutants.append(deletion)

    return mutants


def _exec_block_open_after(code: str, mask: list[bool], start: int) -> bool:
    """Whether an EXEC block that is open at `code[start]` is still open
    at the end of the line, i.e. no END-EXEC (outside literals) closes it
    on this line."""
    return not any(
        _outside_literals(mask, m.start(), m.end())
        for m in _EXEC_CLOSE.finditer(code, start)
    )


def _in_condition_context(code: str, mask: list[bool]) -> bool:
    return any(
        _outside_literals(mask, m.start(), m.end())
        for m in _CONDITION_CONTEXT.finditer(code)
    )


def _relational_mutants(
    line: str, code: str, mask: list[bool], line_no: int
) -> list[Mutant]:
    if not _in_condition_context(code, mask):
        return []
    mutants: list[Mutant] = []
    claimed: set[int] = set()
    for source, target in _REL_SWAPS:
        start = 0
        while (pos := code.find(source, start)) != -1:
            end = pos + len(source)
            start = end
            if pos in claimed or not _outside_literals(mask, pos, end):
                continue
            # A bare `>`/`<` must not re-match inside an already-claimed
            # `>=`/`<=`; compound symbols run first and claim their span.
            claimed.update(range(pos, end))
            mutated = _rewrite_code(line, pos, end, target)
            if mutated is None:
                continue
            mutants.append(
                Mutant(
                    line=line_no,
                    operator="rel-swap",
                    original=line,
                    mutated=mutated,
                    description=f"{source!r} -> {target!r}",
                )
            )
    return mutants


_REMAINDER = re.compile(_cobol_word("REMAINDER"), re.IGNORECASE)


def _opens_something_new(follower: str) -> bool:
    """Whether the code-bearing line `follower` starts a new statement, an
    unrelated scope terminator, a paragraph or a header -- rather than
    carrying on the statement above it."""
    area = follower[TEXT_START_COL - 1 : CODE_END_COL]
    text = area.strip()
    if _STATEMENT_OPENER.match(text):
        return True
    if not _HEADER_LINE.match(text):
        return False
    indent = len(area) - len(area.lstrip())
    in_area_b = TEXT_START_COL + indent >= _AREA_B_COL
    return not (in_area_b and _BARE_NAME_LINE.match(text))


def _statement_tail(lines: list[str], index: int, code: str) -> str:
    """The text of the statement starting on `lines[index]` from that line
    on, as far as it provably runs: the line itself, then every following
    code line until one ends in a period or the next one opens something
    new (the same follower rule `_statement_ends_on_line` applies). Quoted
    literals are blanked so a word inside one never counts."""
    parts: list[str] = []
    current = code
    follower_index = index
    while True:
        mask = _literal_mask(current)
        parts.append(
            "".join(" " if m else c for c, m in zip(current, mask, strict=True))
        )
        if current.rstrip().endswith("."):
            break
        follower_index += 1
        while follower_index < len(lines) and (
            _is_comment(lines[follower_index])
            or not lines[follower_index][TEXT_START_COL - 1 : CODE_END_COL].strip()
        ):
            follower_index += 1
        if follower_index >= len(lines):
            break
        follower = lines[follower_index]
        if not _is_continuation(follower) and _opens_something_new(follower):
            break
        current = follower[:CODE_END_COL]
    return " ".join(parts)


def _arithmetic_verb_mutants(
    line: str, code: str, mask: list[bool], line_no: int, statement: str = ""
) -> list[Mutant]:
    swaps = [
        (_ADD_TO, "SUBTRACT", "FROM", "ADD..TO -> SUBTRACT..FROM"),
        (_SUBTRACT_FROM, "ADD", "TO", "SUBTRACT..FROM -> ADD..TO"),
        (_MULTIPLY_BY, "DIVIDE", "INTO", "MULTIPLY..BY -> DIVIDE..INTO"),
        (_DIVIDE_INTO, "MULTIPLY", "BY", "DIVIDE..INTO -> MULTIPLY..BY"),
    ]
    mutants: list[Mutant] = []
    for pattern, verb, preposition, description in swaps:
        match = pattern.search(code)
        if match is None or not _outside_literals(mask, match.start(), match.end()):
            continue
        if pattern is _DIVIDE_INTO and _REMAINDER.search(statement or code):
            # `DIVIDE a INTO b GIVING c REMAINDER d` has no MULTIPLY
            # counterpart: `MULTIPLY ... REMAINDER` does not compile, so the
            # swap is a stillborn by construction. The phrase may sit on a
            # later line of the same statement, hence `statement`.
            continue
        mutated = _rewrite_code(
            line, match.start(), match.end(), verb + match.group("mid") + preposition
        )
        if mutated is None:
            continue
        mutants.append(
            Mutant(
                line=line_no,
                operator="arith-verb-swap",
                original=line,
                mutated=mutated,
                description=description,
            )
        )
    return mutants


def _move_literal_mutants(
    line: str, code: str, mask: list[bool], line_no: int
) -> list[Mutant]:
    match = _MOVE_INT.search(code)
    if match is None or not _outside_literals(mask, match.start(), match.end()):
        return []
    value = int(match.group("value"))
    replacement = str(value + 1)
    mutated = _rewrite_code(line, match.start("value"), match.end("value"), replacement)
    if mutated is None:
        return []
    return [
        Mutant(
            line=line_no,
            operator="move-literal",
            original=line,
            mutated=mutated,
            description=f"MOVE {value} -> MOVE {replacement}",
        )
    ]


def _boundary_literal_mutants(
    line: str, code: str, mask: list[bool], line_no: int
) -> list[Mutant]:
    if not _in_condition_context(code, mask):
        return []
    mutants: list[Mutant] = []
    for match in _REL_INT.finditer(code):
        if not _outside_literals(mask, match.start(), match.end()):
            continue
        value = int(match.group(2))
        replacement = str(value + 1)
        mutated = _rewrite_code(line, match.start(2), match.end(2), replacement)
        if mutated is None:
            continue
        mutants.append(
            Mutant(
                line=line_no,
                operator="boundary-literal",
                original=line,
                mutated=mutated,
                description=f"{match.group(1)} {value} -> {match.group(1)} {replacement}",
            )
        )
    return mutants


def _statement_ends_on_line(lines: list[str], index: int, code: str) -> bool:
    """True when the statement starting on `lines[index]` provably ends
    there. A trailing period proves it outright; short of one, the line
    must not trail off mid-clause AND the next code-bearing line must open
    something new (a statement, an unrelated scope terminator, a paragraph
    or a header). Deleting the head of a multi-line statement leaves its
    own continuation behind -- `CONTINUE` followed by `TO WS-TIME-AVG` or
    by `END-ADD` -- which is a stillborn every time."""
    stripped = code.rstrip()
    if stripped.endswith("."):
        return True
    if _DANGLING_TAIL.search(stripped):
        return False
    for follower in lines[index + 1 :]:
        if _is_continuation(follower):
            # A continuation line is by definition part of this statement.
            return False
        if _is_comment(follower):
            continue
        # Columns 8-72 only: a sequence number in columns 1-6 would
        # otherwise sit in front of the follower's first word.
        text = follower[TEXT_START_COL - 1 : CODE_END_COL].strip()
        if not text:
            continue
        return _opens_something_new(follower)
    # Nothing follows at all: there is no continuation for the deletion to
    # strand, whatever the source's own missing period says about it.
    return True


def _statement_deletion_mutant(
    lines: list[str], index: int, code: str, mask: list[bool], line_no: int
) -> Mutant | None:
    line = lines[index]
    # Match on the program-text area (columns 8-72), not the whole line: a
    # fixed-format source routinely carries a sequence number in columns
    # 1-6, which would otherwise hide the verb from `_DELETABLE_VERB` --
    # and, before that was noticed, from the rewrite below too.
    stripped = code[TEXT_START_COL - 1 :].strip()
    if not _DELETABLE_VERB.match(stripped):
        return None
    if any(
        _outside_literals(mask, m.start(), m.end())
        for m in _SCOPE_TOKENS.finditer(code)
    ):
        return None
    if not _statement_ends_on_line(lines, index, code):
        return None
    # Keep everything before the first program-text character verbatim:
    # sequence area, indicator column and Area A/B indent.
    head = line[: _text_start(line)]
    terminator = "." if stripped.rstrip().endswith(".") else ""
    mutated = f"{head}CONTINUE{terminator}"
    if len(mutated) > CODE_END_COL:
        return None
    return Mutant(
        line=line_no,
        operator="stmt-delete",
        original=line,
        mutated=mutated,
        description=f"delete {stripped.split()[0].upper()} statement",
    )
