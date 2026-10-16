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
from dataclasses import dataclass, field


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
    # Folded items whose `SET ADDRESS OF` keeps its real meaning (issue
    # #226): `splicer.linkage.Rebinding`s, filled in by `cli.checks` once
    # `splicer.linkage.mark_based` has made them BASED.
    rebindings: list = field(default_factory=list)


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
# `IF ADDRESS OF X = NULL` (legal, but always false after the fold -- lint
# warns when a case reaches one, see `omitted_argument_tests`, issue #288).
# And an occurrence inside `EXEC ... END-EXEC`
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
    keyword through the header's closing period, across as many lines as
    the list wraps. `splicer.linkage.neutralize` writes the period back at
    the start of the first span, so the header always ends on its first
    line: the driver is inserted right after that line, and a period left
    on a later line put the driver inside the header (cobc: syntax error). `[]` when the header has no such
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
        end = period.end() if period else len(text.rstrip())
        if end > start:
            spans.append((idx + 1, start, end))
        if period:
            return spans
        start = 0
    return None


def rebindable_sites(
    lines: list[str], sites: list[AddressOfSite]
) -> list[AddressOfSite]:
    """The receiving `SET ADDRESS OF` sites that can keep their real meaning
    (issue #226): the address they bind to is one the program itself takes,
    so it is valid storage in a test run too.

    A site qualifies when its sending operand is `ADDRESS OF <item>`, or a
    pointer the program only ever writes with `SET <ptr> TO ADDRESS OF
    <item>` (and only otherwise reads as the sending side of another
    rebind). Any other source -- a pointer a CALL fills in (the IMS
    `UIBPCBAL` idiom, NULL from a mocked CBLTDLI), one a MOVE or an EXEC
    touches, `NULL` -- keeps the old redirect into `UT-ADDR-SINK`, which can
    never dereference an address the test run does not have."""
    tokens = _tokenize(lines)
    procedure = _procedure_start(tokens)
    by_position = {(t.line, t.start): i for i, t in enumerate(tokens)}
    sources: dict[AddressOfSite, tuple[str, int] | None] = {}
    for site in sites:
        index = by_position.get((site.line, site.start_column))
        sources[site] = None if index is None else _set_source(tokens, index)

    rebind_source_positions = {
        source[1]
        for source in sources.values()
        if source is not None and not source[0].startswith("ADDRESS OF ")
    }
    owned: dict[str, bool] = {}

    def program_owned(pointer: str) -> bool:
        if pointer not in owned:
            owned[pointer] = _only_set_to_addresses(
                tokens, procedure, pointer, rebind_source_positions
            )
        return owned[pointer]

    out: list[AddressOfSite] = []
    for site in sites:
        source = sources[site]
        if source is None:
            continue
        text = source[0]
        if text.startswith("ADDRESS OF ") or (
            text not in ("NULL", "NULLS") and program_owned(text)
        ):
            out.append(site)
    return out


def _procedure_start(tokens: list[_Token]) -> int:
    for i in range(len(tokens) - 1):
        if tokens[i].text == "PROCEDURE" and tokens[i + 1].text == "DIVISION":
            return i
    return len(tokens)


def _set_source(tokens: list[_Token], index: int) -> tuple[str, int] | None:
    """(`ADDRESS OF <NAME>` or `<NAME>`, token index of the source) for the
    SET whose receiving `ADDRESS` token sits at `index`, or None when its
    sending operand is anything else (qualified, subscripted, unreadable)."""
    depth = 0
    for i in range(index, len(tokens)):
        text = tokens[i].text
        if text == "(":
            depth += 1
        elif text == ")":
            depth -= 1
        elif depth == 0 and text == "TO":
            rest = tokens[i + 1 : i + 5]
            if (
                len(rest) >= 3
                and rest[0].text == "ADDRESS"
                and rest[1].text == "OF"
                and rest[2].is_word
            ):
                tail = rest[3:]
                if tail and tail[0].text in ("OF", "IN", "("):
                    return None
                return f"ADDRESS OF {rest[2].text}", i + 1
            if rest and rest[0].is_word and rest[0].text not in _STOP_WORDS:
                if len(rest) > 1 and rest[1].text in ("OF", "IN", "("):
                    return None
                return rest[0].text, i + 1
            return (rest[0].text, i + 1) if rest else None
        elif depth == 0 and text in (".", "SET") and i != index:
            return None
    return None


def _only_set_to_addresses(
    tokens: list[_Token], procedure: int, pointer: str, rebind_sources: set[int]
) -> bool:
    """True when every PROCEDURE DIVISION occurrence of `pointer` is either
    the receiving operand of `SET <pointer> TO ADDRESS OF <item>` or the
    sending operand of a receiving `SET ADDRESS OF ... TO <pointer>` -- and
    there is at least one of the first kind."""
    assigned = False
    for i in range(procedure, len(tokens)):
        if tokens[i].text != pointer:
            continue
        if i in rebind_sources:
            continue
        previous = tokens[i - 1].text if i > 0 else ""
        following = [t.text for t in tokens[i + 1 : i + 4]]
        if (
            previous == "SET"
            and following[:3] == ["TO", "ADDRESS", "OF"]
            and len(tokens) > i + 4
            and tokens[i + 4].is_word
        ):
            assigned = True
            continue
        return False
    return assigned


# Words that may sit between an `ADDRESS OF <item>` operand and the NULL it is
# compared with (`= NULL`, `IS NOT EQUAL TO NULLS`, ...), in either order.
_NULL_COMPARE_WORDS = frozenset({"IS", "NOT", "=", "EQUAL", "TO"})


@dataclass(frozen=True)
class OmittedArgumentTest:
    """One PROCEDURE DIVISION test for an argument the caller did not pass
    (`ADDRESS OF <folded item> = NULL`, or `NUMBER-OF-CALL-PARAMETERS`),
    which can never see an omitted argument once the item is folded into
    WORKING-STORAGE: the item always has storage, and the driver PERFORMs
    rather than CALLs (issue #288). `line` is 1-indexed into the normalized
    text; `item_name` is None for NUMBER-OF-CALL-PARAMETERS."""

    line: int
    item_name: str | None


def omitted_argument_tests(
    lines: list[str],
    plan: LinkagePlan,
    rebound: set[str] | frozenset[str] = frozenset(),
) -> list[OmittedArgumentTest]:
    """Every omitted-argument test in the PROCEDURE DIVISION of `lines`.
    Items in `rebound` (made BASED because the program rebinds them itself,
    issue #226) are skipped: their address is the program's to set, NULL
    included."""
    folded = {
        (getattr(item, "name", None) or "").upper() for item in plan.linkage_items
    } - {name.upper() for name in rebound}
    folded.discard("")
    tokens = _tokenize(lines)
    out: list[OmittedArgumentTest] = []
    for i in range(_procedure_start(tokens), len(tokens)):
        token = tokens[i]
        if token.text == "NUMBER-OF-CALL-PARAMETERS":
            out.append(OmittedArgumentTest(token.line, None))
            continue
        if (
            token.text != "ADDRESS"
            or i + 2 >= len(tokens)
            or tokens[i + 1].text != "OF"
            or tokens[i + 2].text not in folded
        ):
            continue
        if not _is_set_receiving(tokens, i) and _compared_with_null(tokens, i, i + 3):
            out.append(OmittedArgumentTest(token.line, tokens[i + 2].text))
    return out


def _compared_with_null(tokens: list[_Token], start: int, end: int) -> bool:
    """True when the operand `tokens[start:end]` is compared with NULL/NULLS
    on either side, through only `_NULL_COMPARE_WORDS` in between."""
    j = end
    while j < len(tokens) and tokens[j].text in _NULL_COMPARE_WORDS:
        j += 1
    if j > end and j < len(tokens) and tokens[j].text in ("NULL", "NULLS"):
        return True
    j = start - 1
    while j >= 0 and tokens[j].text in _NULL_COMPARE_WORDS:
        j -= 1
    return j < start - 1 and j >= 0 and tokens[j].text in ("NULL", "NULLS")


OMITTED_ARGUMENT = "OMITTED_ARGUMENT_UNTESTABLE"


def omitted_argument_warnings(
    program, tests: list[OmittedArgumentTest], executed: set[str] | None
) -> list[str]:
    """One unprefixed warning line per omitted-argument test in a paragraph
    some selected test case can execute (`executed` is the reachability
    union; None means "may be any", so every test is reported). A warning,
    not a refusal: the branch for a passed argument still runs and can be
    tested; only the omitted-argument branch cannot (issue #288)."""
    if not tests:
        return []
    procedure = program.get_division("PROCEDURE") if program is not None else None
    starts: list[tuple[int, str, str | None]] = []  # (line, paragraph, section)
    if procedure is not None:
        for paragraph in procedure.paragraphs:
            if paragraph.location is not None:
                starts.append((paragraph.location.line, paragraph.paragraph_name, None))
        for section_name, section in procedure._sections.items():
            if section.location is not None:
                starts.append((section.location.line, section_name, section_name))
            for paragraph in section.paragraphs:
                if paragraph.location is not None:
                    starts.append(
                        (
                            paragraph.location.line,
                            paragraph.paragraph_name,
                            section_name,
                        )
                    )
    starts.sort(key=lambda entry: entry[0])
    executed_upper = None if executed is None else {n.upper() for n in executed}
    warnings: list[str] = []
    for test in tests:
        owner = None
        for start in starts:
            if start[0] > test.line:
                break
            owner = start
        if executed_upper is not None:
            names = {owner[1].upper()} if owner else set()
            if owner and owner[2]:
                names.add(owner[2].upper())
            if not names & executed_upper:
                continue
        where = f"paragraph {owner[1]}, " if owner else ""
        if test.item_name is None:
            what = (
                "NUMBER-OF-CALL-PARAMETERS is tested, but the test driver "
                "PERFORMs the program's paragraphs rather than CALLing it"
            )
        else:
            what = (
                f"ADDRESS OF {test.item_name} is compared with NULL, but "
                f"{test.item_name} is folded into WORKING-STORAGE and always "
                f"has storage, so the comparison is always false"
            )
        warnings.append(
            f"warning ({OMITTED_ARGUMENT}): {where}line {test.line}: {what}. "
            f"The program's branch for an omitted argument cannot be reached "
            f"by any TESTCASE; mockymock has no way yet to omit a LINKAGE "
            f"parameter"
        )
    return warnings
