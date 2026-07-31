"""Mutant generation: pure text/line-level site discovery, no Docker.

v1 operates on the ORIGINAL source lines (the file the user edits, before
`normalize_fixed_format`), so every reported mutant points at a line the
user can open. Discovery is deliberately conservative: a site is only
mutated when the whole match sits outside quoted literals, on a line that
is (a) inside the PROCEDURE DIVISION, (b) not a comment, (c) free of
boundary verbs (those statements are mocked/replaced by the splicer --
mutating them fights the harness instead of testing the program), and
(d) not a terminator (STOP RUN / GOBACK lines are rewritten by the
splicer's terminator plans). A skipped real site costs one blind spot; a
false site costs a stillborn compile per mutant, so precision wins over
recall throughout. AST-driven discovery (via cobolparser statement nodes)
is the documented v2 upgrade path.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Statements the splicer owns: external boundaries (mocked) plus verbs the
# terminator/flow machinery rewrites. Any line where one of these appears
# as a word (outside literals) is excluded wholesale.
_EXCLUDED_VERBS = re.compile(
    r"\b(CALL|CANCEL|ENTRY|EXEC|OPEN|CLOSE|READ|WRITE|REWRITE|DELETE|START"
    r"|UNLOCK|ACCEPT|STOP|GOBACK|EXIT)\b",
    re.IGNORECASE,
)

_PROCEDURE_DIVISION = re.compile(r"\bPROCEDURE\s+DIVISION\b", re.IGNORECASE)

# A line whose only statement starts with one of these verbs may be
# replaced wholesale by CONTINUE (statement deletion). Conditional /
# scope-carrying lines are never deleted -- removing an IF or END-IF
# guarantees a stillborn (or worse, silently restructured) program.
_DELETABLE_VERB = re.compile(
    r"^(MOVE|ADD|SUBTRACT|COMPUTE|MULTIPLY|DIVIDE|INITIALIZE|SET)\b",
    re.IGNORECASE,
)
_SCOPE_TOKENS = re.compile(
    r"\b(IF|ELSE|EVALUATE|WHEN|PERFORM|UNTIL|VARYING)\b|END-", re.IGNORECASE
)

_CONDITION_CONTEXT = re.compile(r"\b(IF|UNTIL|WHEN)\b", re.IGNORECASE)

# Relational-symbol swaps, one mutant per occurrence. Compound symbols are
# matched before their single-character prefixes so `>=` never double-fires
# as `>` too.
_REL_SWAPS: list[tuple[str, str]] = [
    (">=", ">"),
    ("<=", "<"),
    (">", ">="),
    ("<", "<="),
]

_ADD_TO = re.compile(r"\bADD\b(?P<mid>.+?)\bTO\b", re.IGNORECASE)
_SUBTRACT_FROM = re.compile(r"\bSUBTRACT\b(?P<mid>.+?)\bFROM\b", re.IGNORECASE)
_MULTIPLY_BY = re.compile(r"\bMULTIPLY\b(?P<mid>.+?)\bBY\b", re.IGNORECASE)
_DIVIDE_INTO = re.compile(r"\bDIVIDE\b(?P<mid>.+?)\bINTO\b", re.IGNORECASE)

_MOVE_INT = re.compile(r"\b(MOVE)\s+(\d+)\s+(TO)\b", re.IGNORECASE)
# An integer directly following a relational symbol in a condition line --
# the loop/branch boundary itself.
_REL_INT = re.compile(r"([><]=?|=)\s*(\d+)\b")


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


def _sequence_area_end(line: str) -> int:
    """Best-effort guard for fixed-format identification columns: mutate
    nothing past column 72 (index 72). Lines shorter than that (the common
    case in this repo's fixtures and modern sources) are unaffected."""
    return min(len(line), 72)


def generate_mutants(lines: list[str]) -> list[Mutant]:
    """Walk the original source and produce every applicable mutant, in
    line order. Pure and deterministic; safe without Docker."""
    mutants: list[Mutant] = []
    in_procedure = False

    for index, line in enumerate(lines):
        line_no = index + 1
        if _is_comment(line):
            continue
        if not in_procedure:
            if _PROCEDURE_DIVISION.search(line):
                in_procedure = True
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

        excluded = any(
            _outside_literals(mask, m.start(), m.end())
            for m in _EXCLUDED_VERBS.finditer(code)
        )
        if excluded:
            continue

        mutants.extend(_relational_mutants(line, code, mask, line_no))
        mutants.extend(_arithmetic_verb_mutants(line, code, mask, line_no))
        mutants.extend(_move_literal_mutants(line, code, mask, line_no))
        mutants.extend(_boundary_literal_mutants(line, code, mask, line_no))
        deletion = _statement_deletion_mutant(line, code, mask, line_no)
        if deletion is not None:
            mutants.append(deletion)

    return mutants


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
            mutated = line[:pos] + target + line[end:]
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


def _arithmetic_verb_mutants(
    line: str, code: str, mask: list[bool], line_no: int
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
        mutated = (
            line[: match.start()]
            + verb
            + match.group("mid")
            + preposition
            + line[match.end() :]
        )
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
    value = int(match.group(2))
    replacement = str(value + 1)
    mutated = line[: match.start(2)] + replacement + line[match.end(2) :]
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
        mutated = line[: match.start(2)] + replacement + line[match.end(2) :]
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


def _statement_deletion_mutant(
    line: str, code: str, mask: list[bool], line_no: int
) -> Mutant | None:
    stripped = code.strip()
    if not _DELETABLE_VERB.match(stripped):
        return None
    if any(
        _outside_literals(mask, m.start(), m.end())
        for m in _SCOPE_TOKENS.finditer(code)
    ):
        return None
    indent = line[: len(line) - len(line.lstrip())]
    terminator = "." if stripped.rstrip().endswith(".") else ""
    mutated = f"{indent}CONTINUE{terminator}"
    return Mutant(
        line=line_no,
        operator="stmt-delete",
        original=line,
        mutated=mutated,
        description=f"delete {stripped.split()[0].upper()} statement",
    )
