"""Resolve the data names a `.cut` file writes into the generated driver
against the program under test, so a typo is refused by `lint`/`run` at
its `.cut` line instead of surfacing as a cobc error at a line of a
sandbox copy that no longer exists (issue #204).

Checked: every setup-MOVE / hook-MOVE target, every EXPECT data-name, every
`CAPTURE ... INTO` target that is not a synthesized `UT-CAP-` field, and
every MOVE/EXPECT value that is a single bare COBOL word (`EXPECT F TO BE
Y` -- an unquoted `Y` is a data-name to cobc, not a literal).

Deliberately loose on the "known" side, so it can never refuse a name cobc
would accept: a name is known when it appears as a COBOL word anywhere in
the program text the splicer compiles (literals and inline comments
removed) -- data items, copybook and `EXEC SQL INCLUDE` members, the
generated SQLCA alike -- or is a harness item (`UT-` prefix, the
synthesized DFHEIBLK/DLIDIB fields) or a special register. A misspelt data
name appears nowhere in the program, which is all this needs to catch.
Anything that is not a plain (possibly qualified/subscripted) name --
`LENGTH OF X`, `FUNCTION ...`, an expression -- is left unchecked.
"""

from __future__ import annotations

import re

from mockymock.analysis.refusal import RefusalReason
from mockymock.dsl.model import MockTestSuite

_LITERAL_RE = re.compile(r"\"(?:[^\"]|\"\")*\"?|'(?:[^']|'')*'?")
_WORD_RE = re.compile(r"[A-Za-z0-9][\w-]*")
_COBOL_WORD_RE = re.compile(r"^[A-Za-z0-9][\w-]*$")
_PARENS_RE = re.compile(r"\([^()]*\)")
_FLOAT_RE = re.compile(r"^\d+(?:\.\d+)?E[+-]?\d+$", re.IGNORECASE)

#: Words that are values, not data-names, when written bare.
_FIGURATIVE = frozenset(
    {
        "ZERO",
        "ZEROS",
        "ZEROES",
        "SPACE",
        "SPACES",
        "HIGH-VALUE",
        "HIGH-VALUES",
        "LOW-VALUE",
        "LOW-VALUES",
        "QUOTE",
        "QUOTES",
        "NULL",
        "NULLS",
        "TRUE",
        "FALSE",
        "ALL",
    }
)

#: Special registers and compiler-provided items no DATA DIVISION declares.
_SPECIAL_REGISTERS = frozenset(
    {
        "RETURN-CODE",
        "SORT-RETURN",
        "SORT-CONTROL",
        "SORT-CORE-SIZE",
        "SORT-FILE-SIZE",
        "SORT-MESSAGE",
        "SORT-MODE-SIZE",
        "TALLY",
        "WHEN-COMPILED",
        "LINAGE-COUNTER",
        "DEBUG-ITEM",
        "SHIFT-IN",
        "SHIFT-OUT",
        "XML-CODE",
        "XML-EVENT",
        "XML-TEXT",
        "XML-NTEXT",
        "XML-NAMESPACE",
        "XML-NAMESPACE-PREFIX",
        "XML-NNAMESPACE",
        "XML-NNAMESPACE-PREFIX",
        "JSON-CODE",
        "JSON-STATUS",
        "NUMBER-OF-CALL-PARAMETERS",
        "COB-CRT-STATUS",
    }
)

#: A name starting with one of these is not a plain data reference.
_UNCHECKED_LEADS = frozenset({"LENGTH", "ADDRESS", "FUNCTION"})

_HARNESS_PREFIX = "UT-"


def _program_words(lines: list[str]) -> set[str]:
    words: set[str] = set()
    for line in lines:
        text = _LITERAL_RE.sub(" ", line)
        comment = text.find("*>")
        if comment != -1:
            text = text[:comment]
        words.update(word.upper() for word in _WORD_RE.findall(text))
    return words


def _harness_words() -> set[str]:
    from mockymock.splicer.cics_eib import _DFHEIBLK_LINES, _DLIDIB_LINES

    return _program_words(_DFHEIBLK_LINES + _DLIDIB_LINES)


def _name_words(name: str) -> list[str] | None:
    """The data-name words of a (qualified, subscripted, reference-
    modified) name, or None when it is not that shape."""
    text = name.strip()
    while True:
        stripped = _PARENS_RE.sub(" ", text)
        if stripped == text:
            break
        text = stripped
    if "(" in text or ")" in text:
        return None
    words = text.split()
    if not words or words[0].upper() in _UNCHECKED_LEADS:
        return None
    names: list[str] = []
    for position, word in enumerate(words):
        if position % 2 == 1:
            if word.upper() not in ("OF", "IN"):
                return None
            continue
        if not _COBOL_WORD_RE.match(word):
            return None
        names.append(word.upper())
    return names if len(words) % 2 == 1 else None


def _is_bare_word_value(value: str) -> bool:
    text = value.strip()
    if not _COBOL_WORD_RE.match(text) or not re.search(r"[A-Za-z]", text):
        return False
    upper = text.upper()
    return upper not in _FIGURATIVE and not _FLOAT_RE.match(text)


def check_cut_data_names(
    suite: MockTestSuite, lines: list[str], program_name: str | None = None
) -> list[RefusalReason]:
    """UNKNOWN_DATA_NAME for each `.cut` data reference no program text
    declares -- see the module docstring for what is checked."""
    known = _program_words(lines) | _harness_words() | _SPECIAL_REGISTERS
    owner = f" of {program_name}" if program_name else ""
    reasons: list[RefusalReason] = []
    seen: set[tuple[int, str, str]] = set()

    def unknown(word: str) -> bool:
        return word not in known and not word.startswith(_HARNESS_PREFIX)

    def name(line: int, role: str, text: str) -> None:
        for word in _name_words(text) or []:
            if unknown(word) and (line, role, word) not in seen:
                seen.add((line, role, word))
                reasons.append(
                    RefusalReason(
                        code="UNKNOWN_DATA_NAME",
                        message=(
                            f".cut line {line}: {role} {word} is not a data "
                            f"item{owner}"
                        ),
                    )
                )

    def value(line: int, role: str, text: str) -> None:
        if not _is_bare_word_value(text):
            return
        word = text.strip().upper()
        if unknown(word) and (line, role, word) not in seen:
            seen.add((line, role, word))
            reasons.append(
                RefusalReason(
                    code="UNKNOWN_DATA_NAME",
                    message=(
                        f".cut line {line}: {role} {text.strip()} is neither a "
                        f"literal nor a data item{owner} -- quote it if it "
                        f"is text"
                    ),
                )
            )

    hook_steps = (
        suite.before_all_steps
        + suite.before_each_steps
        + suite.after_each_steps
        + suite.after_all_steps
    )
    for step in hook_steps:
        if step.kind == "MOVE":
            name(step.line, "MOVE target", step.target)
            value(step.line, "MOVE value", step.value)
    mocks = list(suite.before_all_mocks) + list(suite.before_each_mocks)
    for case in suite.test_cases:
        move_lines = case.setup_move_lines or [case.line] * len(case.setup_moves)
        for (move_value, target), line in zip(
            case.setup_moves, move_lines, strict=False
        ):
            name(line, "MOVE target", target)
            value(line, "MOVE value", move_value)
        for expectation in case.expectations:
            line = expectation.line or case.line
            name(line, "EXPECT", expectation.data_name)
            value(line, "EXPECT value", expectation.expected_value)
        mocks.extend(case.mocks)
    seen_mocks: set[int] = set()
    for directive in mocks:
        if id(directive) in seen_mocks:
            continue
        seen_mocks.add(id(directive))
        capture_lines = directive.capture_lines or [0] * len(directive.captures)
        for (_, target), line in zip(directive.captures, capture_lines, strict=False):
            if target.upper().startswith(_HARNESS_PREFIX):
                continue
            name(line, "CAPTURE INTO target", target)
    return reasons
