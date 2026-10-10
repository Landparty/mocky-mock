"""Detects whether a program's LINKAGE-SECTION shape qualifies for the
neutralization transform in `mockymock.splicer.linkage` (comment out any
named ENTRY statement(s) and the LINKAGE SECTION header line, letting the
declared items fall into WORKING-STORAGE) -- see
docs/2026-07-08-ims-linkage-support-design.md and, for the no-ENTRY
generalization below,
docs/2026-08-27-cics-eib-linkage-support-design.md.

Detection here is a pure, side-effect-free query over the AST: `linkage_plan`
answers "is there anything to do" (None for an empty/absent LINKAGE SECTION
-- an ordinary CALL-only program, untouched by this feature). It does NOT
decide whether the shape is *safe* to neutralize -- that's
`refusal.check_linkage_layout`'s job, which calls `linkage_plan` and applies
the guardrails documented in the design.

`entry_statements` may be empty: originally this only fired when the
program had at least one named `ENTRY` (the IMS DL/I `ENTRY 'DLITCBL'`
idiom this was first built for). Generalized 2026-08-27 to any non-empty
LINKAGE SECTION regardless of ENTRY count -- the IMS design doc's own
empirical finding 2 already proved the storage is unbound (and crashes)
"regardless of whether anything declares USING against it", i.e. the risk
never depended on ENTRY being present, only on mockymock's PERFORM-based
driver never binding the LINKAGE SECTION either way. This covers the
idiomatic CICS `LINKAGE SECTION. 01 DFHCOMMAREA. ... PROCEDURE DIVISION.`
shape (no ENTRY at all) for free -- see the CICS design doc's Part 1.
`neutralize`'s ENTRY-commenting loop was already a no-op over an empty
list, so only this detection gate needed to change.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class LinkagePlan:
    """Everything the guardrail checks and the splicer transform need.

    `header_line` is 1-indexed into the NORMALIZED free-form text (the same
    text `mockymock.splicer` edits) -- taken directly from the LINKAGE
    SECTION's own `CobolSection.location`. cobolparser used to report every
    DATA DIVISION section at its parent division's location rather than its
    own header token; that was fixed upstream (cobolparser 2026-07-09,
    "Section/Paragraph Location Tracking"), so `location.line` is now
    reliable. Do NOT go back to deriving this from the first data item's
    location minus one -- that assumption silently breaks whenever anything
    (a comment block, blank lines) separates the LINKAGE SECTION header from
    its first 01-level item, which is common in real IMS PCB-mask linkage
    sections and was measured to drift 12-14 lines on real-world programs.
    """

    entry_statements: list
    linkage_items: list
    header_line: int


def linkage_plan(program) -> LinkagePlan | None:
    """None when there is nothing for this feature to do: LINKAGE SECTION
    absent/empty. `entries` may legitimately be empty -- see module
    docstring's 2026-08-27 generalization note.
    """
    entries = program.get_entry_statements()
    data = program.get_division("DATA")
    if data is None:
        return None
    linkage_section = data._sections.get("LINKAGE")
    if linkage_section is None or not linkage_section.data_items:
        return None
    if linkage_section.location is None:
        return None
    header_line = linkage_section.location.line
    return LinkagePlan(
        entry_statements=entries,
        linkage_items=linkage_section.data_items,
        header_line=header_line,
    )


# `SET ADDRESS OF <item> TO <pointer>` -- the one statement that stops being
# legal once `splicer.linkage.neutralize` has folded <item> out of LINKAGE and
# into WORKING-STORAGE (GnuCOBOL: "cannot change address of 'X', which is not
# BASED or a LINKAGE item"). Detected textually rather than off the AST because
# cobolparser's `SetStatement` drops the target-side ADDRESS OF entirely --
# `SET ADDRESS OF X TO Y` and `SET X TO Y` both arrive as `targets=["X"]`, so
# the AST cannot tell the two apart. Verified against cobolparser 1.8.0.
#
# Every OTHER use of `ADDRESS OF <folded item>` stays legal after the fold
# (verified against GnuCOBOL 3.1.2): `SET <ptr> TO ADDRESS OF X`,
# `CALL 'CBLTDLI' USING ... ADDRESS OF DLIUIB` (the CICS-DL/I UIB idiom),
# `IF ADDRESS OF X = NULL`. And an occurrence inside `EXEC ... END-EXEC`
# (`EXEC CICS ADDRESS TCTUA(ADDRESS OF TCTUA) END-EXEC`) never reaches cobc
# at all: the splicer replaces every EXEC block with a mock or a trap stub.
#
# Classification is therefore per STATEMENT, not per line, over a token
# stream spanning the whole text: walking back from `ADDRESS`, a receiving
# operand can only be preceded by `SET`, other receiving operands (names,
# `OF`/`IN` qualifiers, subscripts, commas, other `ADDRESS OF`s). Every SET
# form carries `TO` or `UP`/`DOWN BY` before any sending operand, so the
# first keyword outside that vocabulary decides: `SET` means receiving,
# anything else (`TO`, `BY`, `USING`, a verb, an unmatched `(`, `EXEC`, a
# sentence period) means the occurrence is not a rebind and is left alone.
#
# Not a plain `\b`: COBOL identifiers may contain hyphens, which are not `\w`
# characters, so `\bLK-DIB\b` would false-match inside `WS-LK-DIB-SAVE` (same
# reasoning as `analysis.cics_eib`'s name matching).
_NAME_CHARS = r"A-Za-z0-9$@#_-"
_TOKEN_RE = re.compile(
    rf"""(?P<string>"(?:[^"]|"")*"?|'(?:[^']|'')*'?)"""
    rf"|(?P<comment>\*>.*)"
    rf"|(?P<word>[{_NAME_CHARS}]+)"
    rf"|(?P<punct>\S)"
)
# Tokens that can sit between `SET` and one of its receiving operands.
_TARGET_LIST_WORDS = frozenset({"ADDRESS", "OF", "IN", ",", ";"})


# Words that end the backward walk as "not a receiving operand". Only `TO`,
# `BY` and the sentence period are load-bearing (every SET form reaches one of
# them before its sending side); the rest just stop the walk early and
# document the shapes seen in real programs.
_STOP_WORDS = frozenset(
    {
        "TO",
        "BY",
        "UP",
        "DOWN",
        "USING",
        "RETURNING",
        "REFERENCE",
        "CONTENT",
        "VALUE",
        "CALL",
        "EXEC",
        "EXECUTE",
        "END-EXEC",
        "IF",
        "WHEN",
        "ELSE",
        "THEN",
        "AND",
        "OR",
        "NOT",
        "UNTIL",
        "VARYING",
        "FROM",
        "INTO",
        "GIVING",
        "MOVE",
        "DISPLAY",
        "PERFORM",
        "EVALUATE",
        "COMPUTE",
        "INVOKE",
        "ENTRY",
        "END-CALL",
        "END-IF",
        "END-EVALUATE",
        "END-PERFORM",
        "NULL",
        "NULLS",
        "TRUE",
        "FALSE",
        "=",
        "<",
        ">",
        ".",
    }
)


@dataclass(frozen=True)
class _Token:
    text: str  # upper-cased for words/punctuation; string literals as "'"
    line: int  # 1-indexed
    start: int  # 0-based, half-open
    end: int
    is_word: bool


def _tokenize(lines: list[str]) -> list[_Token]:
    tokens: list[_Token] = []
    for index, text in enumerate(lines, start=1):
        for match in _TOKEN_RE.finditer(text):
            kind = match.lastgroup
            if kind == "comment":
                break
            if kind == "string":
                tokens.append(_Token("'", index, match.start(), match.end(), False))
                continue
            tokens.append(
                _Token(
                    match.group().upper(),
                    index,
                    match.start(),
                    match.end(),
                    kind == "word",
                )
            )
    return tokens


def _is_set_receiving(tokens: list[_Token], position: int) -> bool:
    """True when the `ADDRESS` token at `position` is a receiving operand of
    a SET statement (see the module-level comment above for the rule)."""
    depth = 0
    for token in reversed(tokens[:position]):
        if token.text == ")":
            depth += 1
            continue
        if token.text == "(":
            if depth == 0:
                return False  # an operand in parentheses: EXEC CICS, a function
            depth -= 1
            continue
        if depth:
            continue  # inside a subscript/reference modifier
        if token.text == "SET":
            return True
        if token.text in _TARGET_LIST_WORDS:
            continue
        if token.is_word and not token.text.isdigit() and token.text not in _STOP_WORDS:
            continue  # a data name in the target list (or an unknown word)
        return False
    return False


@dataclass(frozen=True)
class AddressOfSite:
    """One `ADDRESS OF <folded item>` occurrence on the RECEIVING side of a
    SET, with the exact half-open column span to overwrite.

    `line` is 1-indexed into the same normalized free-form text
    `splicer.linkage.neutralize` edits; `start_column`/`end_column` are
    0-based and half-open, the convention `stub_writer.replace_columns` takes.
    """

    line: int
    start_column: int
    end_column: int
    item_name: str


def address_of_sites(
    lines: list[str], plan: LinkagePlan
) -> tuple[list[AddressOfSite], list[str]]:
    """Every `SET ADDRESS OF <folded item>` receiving-side occurrence, plus a
    list of human-readable reasons for any occurrence this cannot rewrite.

    Value-side occurrences (`SET <ptr> TO ADDRESS OF <folded item>`), CALL
    arguments and EXEC operands are deliberately NOT returned: they stay legal
    after the fold (or never reach cobc). Only the receiving side of a SET --
    which asks the runtime to *rebind* the item's storage -- becomes illegal.

    A receiving occurrence may sit on a later line than its `SET` (a continued
    target list); it is still rewritten, since the span replaced is only
    `ADDRESS OF <item>`. The one shape reported as a problem is a receiving
    `ADDRESS OF <item>` that is itself split across lines: that span cannot be
    expressed as a single-line column edit.
    """
    folded = {
        item.name.upper() for item in plan.linkage_items if getattr(item, "name", None)
    }
    tokens = _tokenize(lines)
    sites: list[AddressOfSite] = []
    problems: list[str] = []
    for position, token in enumerate(tokens):
        if token.text != "ADDRESS" or position + 2 >= len(tokens):
            continue
        of_token, name_token = tokens[position + 1], tokens[position + 2]
        if of_token.text != "OF" or not name_token.is_word:
            continue
        if name_token.text not in folded:
            continue
        if not _is_set_receiving(tokens, position):
            continue
        if not token.line == of_token.line == name_token.line:
            problems.append(
                f"line {token.line}: `SET ADDRESS OF {name_token.text}` is "
                f"continued onto the next line ({lines[token.line - 1].strip()!r}) "
                "-- its operand cannot be rewritten within one line"
            )
            continue
        sites.append(
            AddressOfSite(
                line=token.line,
                start_column=token.start,
                end_column=name_token.end,
                item_name=lines[name_token.line - 1][name_token.start : name_token.end],
            )
        )
    return sites, problems


# `PROCEDURE DIVISION [USING ...] [RETURNING ...].` on the default entry.
# Since 2026-10-10 (docs/2026-10-10-suite-hooks-design.md, "Entry
# parameters") the clause is blanked out of the instrumented copy instead of
# refused: the driver PERFORMs paragraphs and never CALLs the program, so
# nothing binds those parameters anyway -- with the LINKAGE SECTION folded
# into WORKING-STORAGE they become ordinary storage a `.cut` sets with MOVE
# (BEFORE-ALL / BEFORE-EACH / TESTCASE) and reads back with EXPECT, reset
# between cases like every other folded item.
_DIVISION_RE = re.compile(r"\bPROCEDURE\s+DIVISION\b", re.IGNORECASE)
_HEADER_CLAUSE_RE = re.compile(
    r"(?<![A-Za-z0-9-])(USING|RETURNING|CHAINING)(?![A-Za-z0-9-])", re.IGNORECASE
)
# A sentence-ending period: followed by whitespace or the end of the line,
# so a decimal point never counts (none can appear here, but stay strict).
_PERIOD_RE = re.compile(r"\.(?=\s|$)")
# How far a USING list may wrap before we stop looking for its period.
_HEADER_MAX_LINES = 50


def procedure_header_clause_spans(
    lines: list[str], program
) -> list[tuple[int, int, int]] | None:
    """Column spans `(line_number, start_column, end_column)` (1-based line,
    0-based half-open columns, as `stub_writer.replace_columns` takes them)
    holding the default entry's `USING` / `RETURNING` clause, from the
    keyword up to -- not including -- the header's closing period, across
    as many lines as the list wraps. `[]` when the header has no such
    clause. None when it cannot be blanked safely: a `CHAINING` clause (a
    different mechanism, never neutralized) or no closing period within
    `_HEADER_MAX_LINES` lines."""
    procedure = program.get_division("PROCEDURE")
    if procedure is None or procedure.location is None:
        return []
    first = procedure.location.line - 1
    if not 0 <= first < len(lines):
        return []
    division = _DIVISION_RE.search(lines[first])
    if division is None:
        return []
    clause = _HEADER_CLAUSE_RE.search(lines[first], division.end())
    if clause is None:
        return []
    spans: list[tuple[int, int, int]] = []
    start = clause.start()
    for idx in range(first, min(first + _HEADER_MAX_LINES, len(lines))):
        text = lines[idx]
        segment = text[start:]
        if any(
            m.group(1).upper() == "CHAINING"
            for m in _HEADER_CLAUSE_RE.finditer(segment)
        ):
            return None
        period = _PERIOD_RE.search(text, start)
        end = period.start() if period else len(text.rstrip())
        if end > start:
            spans.append((idx + 1, start, end))
        if period:
            return spans
        start = 0
    return None
