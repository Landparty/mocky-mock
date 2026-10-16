"""Parses .cut files into MockTestSuite objects.

v2 grammar: MOCK takes a category — quoted-key categories
(CALL/MQ/SQL/CICS/DLI) vs bare-COBOL-word categories (the eight file-op
verbs and ACCEPT). `MOCK MQ "X"` is sugar for `MOCK CALL "X"`. CALL alone
takes both forms: `MOCK CALL "X"` mocks a static CALL with literal 'X',
while `MOCK CALL WS-PGM` (bare word) mocks a *dynamic* CALL through the
identifier WS-PGM (parsed as MockCategory.DYNCALL; MQ stays quoted-only —
the MQI is invoked through static CALLs by definition). `MOCK PARAGRAPH
<name>` / `MOCK SECTION <name>` (bare COBOL names) mock an internal flow
target: the named paragraph's/section's body is replaced by the mock body
whenever it is entered through its own header while this test case runs.
VERIFY mirrors the same key syntax; a bare `VERIFY "X"` stays CALL for v1
back-compat, and CALLED/PERFORMED are interchangeable. Lines starting with `*>` outside
MOCK bodies are comments; inside a body they pass through (they're valid
free-form COBOL).

BEFORE-ALL/BEFORE-EACH/AFTER-EACH/AFTER-ALL (see
docs/2026-07-20-before-blocks-and-file-status-design.md and
docs/2026-10-10-suite-hooks-design.md): at most one of each per
TESTSUITE, appearing after the TESTSUITE header and before the first
TESTCASE. Their MOVE/PERFORM lines become `HookStep`s on the suite, run
by the driver at JUnit's @BeforeAll/@BeforeEach/@AfterEach/@AfterAll
points. Their MOCK blocks (BEFORE-* only) are desugared, purely inside
this module: after the file is fully parsed, each TESTCASE's own mocks
list is extended with every BEFORE-EACH mock whose (category, key) it
didn't already declare, then every BEFORE-ALL mock neither it nor
BEFORE-EACH already declared -- so TESTCASE overrides BEFORE-EACH
overrides BEFORE-ALL, silently. The same directive objects are also kept
on the suite (`before_all_mocks`, which answer during the BEFORE-ALL/
AFTER-ALL steps, and `before_each_mocks`) so the static checks can tell
a shared default from a case's own mock.

FILE-STATUS IS <mnemonic-or-code> (see
docs/2026-07-20-before-blocks-and-file-status-design.md): usable once
inside a MOCK OPEN/CLOSE/READ/DELETE/START/UNLOCK body, resolved here to
a two-character status code and stored on MockDirective.file_status --
the WORKING-STORAGE field it targets isn't knowable until the target
.cbl's FILE-CONTROL has been analyzed, which happens later in the
pipeline (mock_surface.analyze_file_status_fields), not during .cut
parsing.

PROVIDER/HEADER/ROW (see
docs/2026-07-20-provider-parameterized-test-cases-design.md): a
`TESTCASE ... USING PROVIDER <name>` is expanded into one ordinary
MockTestCase per PROVIDER row (`_expand_providers`, applied after
BEFORE-ALL/BEFORE-EACH desugaring so each expanded row inherits the
template case's fully-resolved mocks) -- never stored on
MockTestSuite/MockTestCase, so every downstream consumer only ever sees
already-expanded MockTestCase objects and never learns PROVIDER exists.
"""

from __future__ import annotations

import re

from mockymock.dsl.model import (
    CAPTURE_CATEGORIES,
    FILE_STATUS_CATEGORIES,
    ROWS_CATEGORIES,
    SEQUENCED_CALL_CATEGORIES,
    TERMINAL_CATEGORIES,
    DataProvider,
    ExpectDirective,
    HookStep,
    MockCategory,
    MockDirective,
    MockTestCase,
    MockTestSuite,
    VerifyDirective,
)
from mockymock.splicer.cics_resp import expand_dfhresp_text

_QUOTED_CATS = "CALL|MQ|SQL|CICS|DLI"
# CALL also appears here: the bare-key form is the dynamic-CALL mock.
# PARAGRAPH/SECTION mock an internal flow target (a PROCEDURE DIVISION
# paragraph or section) rather than an external boundary. SORT/MERGE key
# on their own SD file name (bare COBOL word), same shape as READ/DELETE/
# START/UNLOCK -- only the plain USING ... GIVING ... file form, and the
# pure INPUT PROCEDURE ... OUTPUT PROCEDURE ... form (via its own
# RELEASE/RETURN below), are mockable; a form mixing USING/GIVING with a
# procedure clause on the other side stays unsupported (see
# mock_surface.py). RELEASE keys on the record name (WRITE-shaped);
# RETURN keys on the SD file name (READ-shaped, including an AT END
# clause).
# INITIATE/GENERATE/TERMINATE (Report Writer, 2026-09-02) key on the
# report name (GENERATE: report or group name) -- a bare COBOL word, no
# ROWS/TERMINAL/FILE-STATUS sugar (see model.REPORT_WRITER_CATEGORIES).
_BARE_CATS = (
    "CALL|OPEN|CLOSE|READ|WRITE|REWRITE|DELETE|START|UNLOCK|ACCEPT"
    "|SORT|MERGE|RELEASE|RETURN|INITIATE|GENERATE|TERMINATE|PARAGRAPH|SECTION"
)

_ROWS_SUPPORTED = (
    "ROWS is only supported for MOCK SQL, MOCK READ, MOCK RETURN, "
    "MOCK CALL (static or dynamic), MOCK MQ, MOCK DLI, and MOCK CICS"
)

_TESTSUITE_RE = re.compile(r'^TESTSUITE\s+"(?P<name>[^"]*)"$')
# `PROGRAM "<path>"`: names the program under test, so a suite can live
# anywhere and be called anything (cli/discovery.py reads it). Only legal
# between TESTSUITE and the first TESTCASE/hook/PROVIDER.
PROGRAM_RE = re.compile(r'^PROGRAM\s+"(?P<path>[^"]*)"$')
_TAG_LIST = r'"[^"]*"(?:\s+"[^"]*")*'
# TAGS may come before or after USING PROVIDER (issue #329): written after
# it, the line used to match nothing and, under an open PROVIDER, was
# reported as a statement not allowed inside the PROVIDER. Both groups
# filled at once (TAGS given twice) is rejected by the parser.
_TESTCASE_RE = re.compile(
    rf'^TESTCASE\s+"(?P<name>[^"]*)"(?:\s+TAGS\s+(?P<tags>{_TAG_LIST}))?'
    r"(?:\s+USING\s+PROVIDER\s+(?P<provider>[A-Za-z0-9][A-Za-z0-9-]*))?"
    rf"(?:\s+TAGS\s+(?P<tags_after>{_TAG_LIST}))?$"
)
_TAG_RE = re.compile(r'"([^"]*)"')
_HOOK_RE = re.compile(r"^(?P<hook>BEFORE-ALL|BEFORE-EACH|AFTER-EACH|AFTER-ALL)$")
# END-BEFORE is deliberately lenient, same rationale as END-MOCK below: a
# missed terminator must not silently swallow the rest of the file.
_END_BEFORE_RE = re.compile(r"^END-BEFORE\.?$", re.IGNORECASE)
_END_AFTER_RE = re.compile(r"^END-AFTER\.?$", re.IGNORECASE)
_MOCK_QUOTED_RE = re.compile(
    rf'^MOCK\s+(?P<cat>{_QUOTED_CATS})\s+"(?P<key>[^"]*)"(?:\s+(?P<rows>ROWS))?$'
)
_MOCK_BARE_RE = re.compile(
    rf"^MOCK\s+(?P<cat>{_BARE_CATS})\s+(?P<key>[A-Za-z0-9][A-Za-z0-9-]*)"
    rf"(?:\s+(?P<rows>ROWS))?$"
)
# END-MOCK is deliberately more forgiving than the other keywords: an
# optional trailing period (the natural COBOL habit) and any letter case
# are accepted, because a missed END-MOCK doesn't fail at this line -- it
# silently swallows the rest of the file into the mock body and surfaces
# later as a confusing refusal or compile error. Every other DSL keyword
# stays case-sensitive uppercase (see the "Case rules" section in
# .okf/dsl.md).
_END_MOCK_RE = re.compile(r"^END-MOCK\.?$", re.IGNORECASE)
# A data-name that may carry one non-nested `(...)` group -- a table
# subscript (`WS-TABLE(1, 1)`, `WS-TABLE(1 1)`) or reference modification
# (`FIELD(1:5)`) -- so a plain `\S+` would stop at the space after a
# comma/space-separated subscript. Nested parens (`TABLE(FUNCTION MOD(I 3))`)
# and qualification (`A OF B`) are out of scope: they fail closed
# (unrecognized statement) rather than being silently mis-parsed. The `\S+`
# fallback alternative preserves the pre-subscript behavior for
# non-identifier tokens -- notably a literal `{Placeholder}` name in a
# PROVIDER-templated TESTCASE, which is deliberately never substituted (see
# `_substitute`'s callers) and must still parse verbatim. Shared by MOVE's
# target and EXPECT's name -- both reference a data-item that may be a
# table element.
_SUBSCRIPTED_NAME = r"[A-Za-z0-9][A-Za-z0-9-]*(?:\s*\([^)]*\))?|\S+"
_MOVE_RE = re.compile(
    rf"^MOVE\s+(?P<value>.+?)\s+TO\s+(?P<target>{_SUBSCRIPTED_NAME})$"
)
_PERFORM_RE = re.compile(
    r"^PERFORM\s+(?P<target>\S+)(?:\s+(?:THRU|THROUGH)\s+(?P<thru>\S+))?$"
)
_EXPECT_RE = re.compile(
    rf"^EXPECT\s+(?P<name>{_SUBSCRIPTED_NAME})\s+(?P<negated>NOT\s+)?TO\s+BE"
    rf"(?:\s+(?P<comparison>GREATER\s+THAN(?:\s+OR\s+EQUAL\s+TO)?"
    rf"|LESS\s+THAN(?:\s+OR\s+EQUAL\s+TO)?))?"
    rf"\s+(?P<value>.+)$"
)
# A value that starts with one of the comparison-phrase words means the
# phrase itself was malformed ("TO BE GREATER 5", "GREATER THAN OR EQUAL
# 5") and the regex above fell back to swallowing the leftover words into
# <value> -- which would splice into the generated IF verbatim and surface
# as a cobc compile error pointing at generated code. Fail closed at the
# .cut line instead. The trailing (?:\s|$) keeps a legitimate hyphenated
# identifier like OR-FLAG or GREATER-VALUE parsing as an ordinary value.
# NOT belongs here too: `TO BE NOT 5` (NOT after TO BE rather than before
# it) otherwise parsed as the value `NOT 5` and generated `IF X NOT = NOT 5`.
_EXPECT_DANGLING_PHRASE_RE = re.compile(r"^(?:GREATER|LESS|THAN|OR|EQUAL|NOT)(?:\s|$)")
_VERIFY_QUOTED_RE = re.compile(
    rf'^VERIFY\s+(?:(?P<cat>{_QUOTED_CATS})\s+)?"(?P<key>[^"]*)"'
    rf"\s+WAS\s+(?:CALLED|PERFORMED)\s+(?P<expectation>.+)$"
)
_VERIFY_BARE_RE = re.compile(
    rf"^VERIFY\s+(?P<cat>{_BARE_CATS})\s+(?P<key>[A-Za-z0-9][A-Za-z0-9-]*)"
    rf"\s+WAS\s+(?:CALLED|PERFORMED)\s+(?P<expectation>.+)$"
)
_COMMENT_RE = re.compile(r"^\*>")
_ROW_RE = re.compile(r"^\((?P<pairs>.+)\)$")
_ROW_PAIR_RE = re.compile(r"^(?P<field>[A-Za-z][A-Za-z0-9-]*)\s*=\s*(?P<value>.+)$")
# TERMINAL ( F = v, ... ) -- READ-only, optional field assignments for the
# rows-exhausted (WHEN OTHER) branch of a MOCK READ ... ROWS block. See
# MockDirective.terminal_row.
_TERMINAL_RE = re.compile(r"^TERMINAL\s*\((?P<pairs>.*)\)$")
_PROVIDER_RE = re.compile(r"^PROVIDER\s+(?P<name>[A-Za-z0-9][A-Za-z0-9-]*)$")
_HEADER_RE = re.compile(
    r"^HEADER\s+(?P<fields>[A-Za-z][A-Za-z0-9-]*(?:\s*,\s*[A-Za-z][A-Za-z0-9-]*)*)$"
)
_PROVIDER_ROW_RE = re.compile(r"^ROW\s+(?P<values>.+)$")
_PLACEHOLDER_RE = re.compile(r"\{([A-Za-z][A-Za-z0-9-]*)\}")

# FILE-STATUS IS <mnemonic> -> two-character GnuCOBOL file status code.
# A quoted two-character literal (FILE-STATUS IS "92") always works too,
# as the escape hatch for a code not listed here.
_FILE_STATUS_MNEMONICS = {
    "SUCCESS": "00",
    "END-OF-FILE": "10",
    "DUPLICATE-KEY": "22",
    "RECORD-NOT-FOUND": "23",
    "FILE-NOT-FOUND": "35",
    "ALREADY-OPEN": "41",
    "NOT-OPEN": "42",
    "NO-CURRENT-RECORD": "43",
}
_FILE_STATUS_RE = re.compile(
    r'^FILE-STATUS\s+IS\s+(?:(?P<mnemonic>[A-Za-z][A-Za-z-]*)|"(?P<literal>[^"]*)")$'
)
# Any line that starts with the FILE-STATUS keyword but doesn't fully match
# _FILE_STATUS_RE above (unquoted numeric codes, mnemonics with digits, a
# missing value, ...) must not silently fall through to body_lines and get
# spliced verbatim into the generated COBOL -- that produces a cobc compile
# error pointing at generated code instead of a clear .cut-level refusal.
_FILE_STATUS_PREFIX_RE = re.compile(r"^FILE-STATUS\b")

# CAPTURE ARG <n> INTO <target> -- n is a 1-based USING-parameter
# position (never a COBOL variable name), resolved against the real call
# site's CallStatement.using_parameters at splice time (injector.py), not
# here -- .cut parsing has no access to the target .cbl's AST. <target>
# reuses _SUBSCRIPTED_NAME, same as MOVE/EXPECT.
_CAPTURE_RE = re.compile(
    rf"^CAPTURE\s+ARG\s+(?P<index>\S+)\s+INTO\s+(?P<target>{_SUBSCRIPTED_NAME})$"
)
_CAPTURE_INDEX_RE = re.compile(r"^[1-9][0-9]*$")
# Any line that starts with the CAPTURE keyword but doesn't fully match
# _CAPTURE_RE above (missing INTO, typos like FROM, missing target, etc.)
# must not silently fall through to body_lines and get spliced verbatim into
# the generated COBOL -- that produces a cobc compile error pointing at
# generated code instead of a clear .cut-level refusal.
_CAPTURE_PREFIX_RE = re.compile(r"^CAPTURE\b")


# The strict shape a data-name token containing parens must have: one
# non-nested, closed `(...)` group. _SUBSCRIPTED_NAME's `\S+` fallback
# exists for literal {Placeholder} tokens, but with no space before a
# stray `(` it also swallowed 'WS-TAB(1' whole -- a syntactically invalid
# COBOL target that only surfaced later as a confusing cobc compile error
# (2026-08-12 audit Finding 4). Any matched token that contains a paren is
# re-checked against this and refused at .cut level when it doesn't hold.
_BALANCED_SUBSCRIPT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]*\s*\([^()]*\)$")


_DOTTED_NAME_RE = re.compile(r"[A-Za-z0-9-]\.[A-Za-z0-9]")


class CutParseError(ValueError):
    """Raised when a .cut file doesn't match the grammar."""


def _reject_before_perform(case, keyword: str, line_no: int) -> None:
    """EXPECT/VERIFY are checked after the PERFORM whatever their position,
    so one written above it would silently assert on the post-PERFORM
    state (issue #150)."""
    if not case.perform_target:
        raise CutParseError(
            f"line {line_no}: {keyword} before the PERFORM -- assertions are "
            f"checked after it runs, so write them below the PERFORM"
        )


def _reject_unbalanced_subscript(token: str, line_no: int) -> None:
    """Refuse a data-name token with a stray/unclosed paren that the `\\S+`
    fallback of _SUBSCRIPTED_NAME would otherwise pass through verbatim."""
    if ("(" in token or ")" in token) and _BALANCED_SUBSCRIPT_RE.match(token) is None:
        raise CutParseError(
            f"line {line_no}: unbalanced parenthesis in data-name "
            f"{token!r} -- a subscript must be one closed (...) group, "
            f"e.g. WS-TABLE(1, 2)"
        )
    # `RECORD.FIELD` is how a fixture bundle writes a qualified name, not
    # COBOL: spliced verbatim it is a cobc "incomplete expression" (issue
    # #144), so refuse it here, at the .cut line.
    if _DOTTED_NAME_RE.search(token.partition("(")[0]):
        raise CutParseError(
            f"line {line_no}: data-name {token!r} contains a '.' -- COBOL "
            f"names have none; name the elementary item itself (e.g. "
            f"{token.partition('(')[0].rsplit('.', 1)[-1]!r})"
        )


def _has_sentence_period(text: str) -> bool:
    """True when `text` holds a COBOL sentence-terminating period: a `.`
    followed by whitespace or end of text, outside any quoted literal and
    before any `*>` inline comment. A decimal point inside a numeric
    literal (`1.5`) is followed by a digit, so it never counts."""
    quote: str | None = None
    for index, char in enumerate(text):
        if quote is not None:
            if char == quote:
                quote = None
            continue
        if char in "'\"":
            quote = char
        elif text.startswith("*>", index):
            return False
        elif char == "." and (index + 1 == len(text) or text[index + 1].isspace()):
            return True
    return False


def _reject_body_sentence_period(line: str, line_no: int, directive: str) -> None:
    """Refuse a MOCK body line (or ROWS/TERMINAL value) carrying a
    sentence-terminating period (`MOVE 5 TO WS-A.` -- the natural COBOL
    habit). Body text is spliced verbatim into a `WHEN` branch of the
    generated `EVALUATE UT-CURRENT-CASE`, where the period ends the
    sentence mid-EVALUATE: cobc then rejects the instrumented program
    ("unexpected END-EVALUATE") at a generated line while `lint` reported
    nothing."""
    if _has_sentence_period(line):
        raise CutParseError(
            f"line {line_no}: {line!r} in MOCK {directive} ends a COBOL "
            f"sentence with a period -- drop the period (the mock body is "
            f"spliced into the middle of a generated EVALUATE, which a "
            f"period would terminate)"
        )


def _reject_sentence_period(value: str, line_no: int, verb: str = "EXPECT") -> None:
    """Refuse an EXPECT value ending in a period outside any quoted
    literal (`EXPECT WS-X TO BE 5.` -- the natural COBOL sentence habit).
    The value is spliced verbatim into the generated `IF <name> NOT =
    <value>`, where that period ends the sentence mid-IF: cobc then
    rejects the generated driver ("IF without imperative statement",
    "unexpected END-IF") while `lint` reported nothing. A COBOL numeric
    literal cannot end in a decimal point, so the period is never part of
    a legitimate value.

    A trailing `*>` inline comment is not part of the value: the generated
    `IF` line keeps it as a comment, so `5. *> note` still ends the
    sentence there (and a period inside the comment is harmless).

    A setup/hook `MOVE` value (`verb="MOVE"`) is spliced verbatim into the
    driver's `MOVE <value> TO <target>` the same way, where the period
    ends the sentence before `TO` and cobc rejects the driver (issue
    #197)."""
    quote: str | None = None
    code_end = len(value)
    for index, char in enumerate(value):
        if quote is not None:
            if char == quote:
                quote = None
        elif char in "'\"":
            quote = char
        elif value.startswith("*>", index):
            code_end = index
            break
    if quote is None and value[:code_end].rstrip().endswith("."):
        consequence = (
            "the period would terminate the generated IF"
            if verb == "EXPECT"
            else "the period would end the generated MOVE before its TO"
        )
        raise CutParseError(
            f"line {line_no}: {verb} value {value!r} ends with a period -- "
            f"drop it (a .cut {verb} is not a COBOL sentence, and "
            f"{consequence})"
        )


def _resolve_category(cat: str | None, bare_key: bool = False) -> MockCategory:
    if cat is None or cat == "MQ":  # bare VERIFY "X" and MOCK MQ are CALL
        return MockCategory.CALL
    if cat == "CALL" and bare_key:  # CALL <identifier> is the dynamic form
        return MockCategory.DYNCALL
    return MockCategory(cat)


def _expect_operator(negated: bool, comparison: str | None) -> str:
    """Normalize an EXPECT line's English phrase to its canonical COBOL
    relation operator (one of model.EXPECT_OPERATORS): `TO BE` -> "=",
    `TO BE GREATER THAN` -> ">", `TO BE LESS THAN OR EQUAL TO` -> "<=",
    with a leading `NOT` prefixing the operator (`NOT TO BE GREATER THAN`
    -> "NOT >"). driver.py compiles the operator's negation into the
    generated failure-branch IF."""
    if comparison is None:
        base = "="
    else:
        words = comparison.split()
        base = {"GREATER": ">", "LESS": "<"}[words[0]]
        if "EQUAL" in words:
            base += "="
    return f"NOT {base}" if negated else base


def _validate_expectation(expectation: str, line_no: int) -> None:
    """Reject a VERIFY expectation the driver codegen cannot compile.

    Must accept exactly what splicer/driver.py's `_verify_condition`
    accepts (it upper-cases and strips before matching) -- keep the two in
    sync. Validating here turns a late, tracebacking ValueError in codegen
    into a line-numbered CutParseError at parse time."""
    normalized = expectation.strip().upper()
    if normalized in ("ONCE", "NEVER", "AT LEAST ONCE"):
        return
    if re.match(r"^\d+\s+TIMES$", normalized):
        return
    raise CutParseError(
        f"line {line_no}: unrecognized VERIFY expectation {expectation!r} "
        f"(expected ONCE, NEVER, AT LEAST ONCE, or <n> TIMES)"
    )


def _balanced_parens(text: str) -> bool:
    """True when every `(` in `text` outside a quoted literal closes, and
    no `)` closes a group that was never opened. A ROWS/TERMINAL line's
    inner text failing this means the line was not ONE `( ... )` group --
    `( A = 1 ) ( B = 2 )` otherwise parsed as the single pair `A = 1 ) (
    B = 2`."""
    quote: str | None = None
    depth = 0
    for char in text:
        if quote is not None:
            if char == quote:
                quote = None
        elif char in "'\"":
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


def _split_top_level(text: str, sep: str) -> list[str]:
    """Split `text` on `sep`, ignoring any occurrence inside a '...' or
    "..." span -- so a ROWS row value like EMP-NAME = "SMITH, JR." isn't
    cut at the comma inside the quoted literal -- or inside a `(...)`
    group, so a subscripted value like `WS-TAB(1, 2)` (the comma-separated
    subscript form MOVE/EXPECT already accept) or `FUNCTION MAX(A, B)`
    stays one value instead of being refused as a malformed assignment or
    a column-count mismatch.

    A comma between two digits is a decimal comma, not a separator: a
    program with `DECIMAL-POINT IS COMMA` writes `1,25`, and COBOL's
    separator comma is always followed by a space (issue #230). So
    `ROW 100,5, 125,62` is two values."""
    parts: list[str] = []
    current: list[str] = []
    quote: str | None = None
    depth = 0
    for index, char in enumerate(text):
        if quote is not None:
            current.append(char)
            if char == quote:
                quote = None
            continue
        if char in "'\"":
            quote = char
            current.append(char)
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth = max(depth - 1, 0)
        elif char == sep and depth:
            current.append(char)
            continue
        if (
            char == sep == ","
            and 0 < index < len(text) - 1
            and text[index - 1].isdigit()
            and text[index + 1].isdigit()
        ):
            current.append(char)
            continue
        if char == sep:
            parts.append("".join(current))
            current = []
            continue
        current.append(char)
    parts.append("".join(current))
    return parts


def _reject_mock_body_placeholder(
    line: str, line_no: int, provider: DataProvider, mock: MockDirective
) -> None:
    """Refuse a `{Column}` token for one of `provider`'s own columns inside
    a MOCK body of a provider-bound TESTCASE. Substitution covers only
    MOVE/EXPECT values (MOCK bodies stay verbatim by design, see
    docs/2026-07-20-provider-parameterized-test-cases-design.md), so the
    token used to reach cobc untouched -- lint passed, and the compile
    failed on `invalid symbol '{'` inside generated code."""
    if _COMMENT_RE.match(line):
        return
    for match in _PLACEHOLDER_RE.finditer(line):
        if match.group(1) in provider.header:
            raise CutParseError(
                f"line {line_no}: placeholder {match.group(0)} inside MOCK "
                f"{mock.describe()} is not substituted -- PROVIDER "
                f"{provider.name!r} values are substituted into the test "
                f"case's MOVE and EXPECT values only; a MOCK body is "
                f"spliced verbatim, so the token would reach the compiler"
            )


def _reject_hook_placeholders(
    hook_texts: list[tuple[int, str, str]], providers: dict[str, DataProvider]
) -> None:
    """Refuse a `{Column}` token for any PROVIDER's column in a hook step's
    MOVE or a hook MOCK body (issue #227). Placeholders are substituted only
    into a provider-bound case's own MOVE/EXPECT values; a hook belongs to
    no single row (BEFORE-ALL runs once for the whole suite), so the token
    reached cobc verbatim (`invalid symbol '{'`) after lint passed. Same
    fail-closed rule as `_reject_mock_body_placeholder`."""
    columns = {
        column: provider.name
        for provider in providers.values()
        for column in provider.header
    }
    if not columns:
        return
    for line_no, text, hook in hook_texts:
        if _COMMENT_RE.match(text):
            continue
        for match in _PLACEHOLDER_RE.finditer(text):
            if match.group(1) in columns:
                raise CutParseError(
                    f"line {line_no}: placeholder {match.group(0)} inside "
                    f"{hook} is not substituted -- PROVIDER "
                    f"{columns[match.group(1)]!r} values are substituted into "
                    f"a test case's own MOVE and EXPECT values only; a hook "
                    f"runs for every case (or once for the suite), so move "
                    f"the step into the TESTCASE"
                )


_COBOL_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]*$")


def _upper_cobol_name(name: str) -> str:
    """A paragraph or section name as the analysis knows it. COBOL names are
    case-insensitive and cobol-parser upper-cases paragraph and section
    names, so `PERFORM read-one` must find `READ-ONE` (issue #164) -- the
    same rule bare MOCK/VERIFY keys already follow. Anything that is not a
    plain COBOL word (a `{Column}` token, which `_reject_name_placeholder`
    reports verbatim) is left exactly as written."""
    if not _COBOL_NAME_RE.match(name):
        return name
    return name.upper()


def _reject_name_placeholder(
    name: str | None, line_no: int, provider: DataProvider, where: str
) -> None:
    """Refuse a `{Column}` token for one of `provider`'s own columns in a
    NAME position (MOVE target, EXPECT data-name, PERFORM target/THRU) of a
    provider-bound TESTCASE. Only values are substituted, so the token
    reached the spliced driver verbatim: `lint` passed (nothing resolves
    EXPECT/MOVE names against the program), and cobc then failed on
    `invalid symbol '{'` -- for an EXPECT, by aborting outright ("Please
    report this!"). Same rule as `_reject_mock_body_placeholder`."""
    if not name:
        return
    for match in _PLACEHOLDER_RE.finditer(name):
        if match.group(1) in provider.header:
            raise CutParseError(
                f"line {line_no}: placeholder {match.group(0)} as the "
                f"{where} is not substituted -- PROVIDER {provider.name!r} "
                f"values are substituted into the test case's MOVE and "
                f"EXPECT values only, never into data or paragraph names"
            )


def _substitute(
    text: str, provider: DataProvider, row: list[str], case_name: str, line_no: int
) -> str:
    """Replace every `{ColumnName}` token in `text` with that column's raw
    row value. An unknown column is a CutParseError, not a silent no-op --
    same fail-closed convention as the rest of this parser."""

    def repl(match: re.Match[str]) -> str:
        column = match.group(1)
        if column not in provider.header:
            raise CutParseError(
                f"line {line_no}: unknown placeholder {{{column}}} in "
                f"TESTCASE {case_name!r} -- PROVIDER {provider.name!r} "
                f"columns are {', '.join(provider.header)}"
            )
        return row[provider.header.index(column)]

    return _PLACEHOLDER_RE.sub(repl, text)


def _display_value(raw: str) -> str:
    """Strip one layer of matching quote characters for a human-readable
    generated case name -- cosmetic only; `_substitute` always uses the
    raw, unstripped row text."""
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "'\"":
        return raw[1:-1]
    return raw


def _instantiate_row(
    case: MockTestCase, provider: DataProvider, row: list[str], row_index: int
) -> MockTestCase:
    row_line = provider.row_lines[row_index - 1]
    for _, target in case.setup_moves:
        _reject_name_placeholder(target, case.line, provider, "MOVE target")
    for expectation in case.expectations:
        _reject_name_placeholder(
            expectation.data_name, expectation.line, provider, "EXPECT data-name"
        )
    _reject_name_placeholder(case.perform_target, case.line, provider, "PERFORM target")
    _reject_name_placeholder(case.perform_thru, case.line, provider, "PERFORM THRU")
    setup_moves = [
        (_substitute(value, provider, row, case.name, case.line), target)
        for value, target in case.setup_moves
    ]
    expectations = [
        ExpectDirective(
            data_name=expectation.data_name,
            expected_value=_substitute(
                expectation.expected_value,
                provider,
                row,
                case.name,
                expectation.line,
            ),
            line=expectation.line,
            operator=expectation.operator,
        )
        for expectation in case.expectations
    ]
    # A {Placeholder} substituted from a ROW like `5.` reaches the same
    # generated IF as a literal one -- checked against the row's own line.
    for expectation in expectations:
        _reject_sentence_period(expectation.expected_value, row_line)
    for value, _ in setup_moves:
        _reject_sentence_period(value, row_line, "MOVE")
    return MockTestCase(
        name=f"{case.name} [row {row_index}: {_display_value(row[0])}]",
        # `list(case.mocks)` copies the list, but not its elements: every
        # expanded row's MockTestCase ends up holding the *same*
        # MockDirective objects (is-identical) as every other row expanded
        # from this case. Safe only because downstream code treats
        # directives as read-only -- never mutate a MockDirective in place
        # per-case; copy it first if you need a per-case change.
        mocks=list(case.mocks),
        setup_moves=setup_moves,
        setup_move_lines=list(case.setup_move_lines),
        perform_target=case.perform_target,
        perform_thru=case.perform_thru,
        expectations=expectations,
        verifications=list(case.verifications),
        line=row_line,
        tags=list(case.tags),
        template_name=case.name,
    )


def _expand_providers(
    test_cases: list[MockTestCase],
    pending: list[tuple[MockTestCase, DataProvider]],
) -> list[MockTestCase]:
    """Replace every provider-bound TESTCASE with one ordinary
    MockTestCase per PROVIDER row (see
    docs/2026-07-20-provider-parameterized-test-cases-design.md). Every
    other consumer of the parsed suite -- analysis, splicer, runtime,
    report, cli -- only ever sees what this returns; PROVIDER never leaks
    past this function."""
    bound = {id(case): provider for case, provider in pending}
    expanded: list[MockTestCase] = []
    for case in test_cases:
        provider = bound.get(id(case))
        if provider is None:
            expanded.append(case)
            continue
        for row_index, row in enumerate(provider.rows, start=1):
            expanded.append(_instantiate_row(case, provider, row, row_index))
    return expanded


def _apply_before_blocks(
    suite: MockTestSuite,
    before_all: list[MockDirective],
    before_each: list[MockDirective],
) -> None:
    """Desugar BEFORE-ALL/BEFORE-EACH into every TESTCASE's own mocks list.
    Precedence when a (category, key) appears in more than one place:
    TESTCASE > BEFORE-EACH > BEFORE-ALL, silently -- see
    docs/2026-07-20-before-blocks-and-file-status-design.md.

    Note: the same MockDirective object from `before_each`/`before_all` is
    appended (is-identical, not copied) into every TESTCASE's mocks list
    that inherits it -- so one directive ends up aliased across many
    cases. This is safe only because every downstream consumer treats
    directives as read-only; never mutate a MockDirective in place, copy
    it first if a per-case change is ever needed."""
    if not before_all and not before_each:
        return
    for case in suite.test_cases:
        declared = {(m.category, m.key) for m in case.mocks}
        for directive in before_each:
            key = (directive.category, directive.key)
            if key in declared:
                continue
            declared.add(key)
            case.mocks.append(directive)
        for directive in before_all:
            key = (directive.category, directive.key)
            if key in declared:
                continue
            declared.add(key)
            case.mocks.append(directive)


def _reject_mock_outside(hook: str | None, line_no: int) -> None:
    if hook is not None and hook.startswith("AFTER"):
        raise CutParseError(
            f"line {line_no}: MOCK not allowed inside {hook} (only MOVE and "
            f"PERFORM are) -- {hook} steps run with the mocks of "
            + (
                "each TESTCASE (declare shared ones in BEFORE-EACH)"
                if hook == "AFTER-EACH"
                else "BEFORE-ALL, so declare the mock there"
            )
        )
    raise CutParseError(f"line {line_no}: MOCK outside TESTCASE/BEFORE-EACH/BEFORE-ALL")


def parse_cut(text: str) -> MockTestSuite:
    # A UTF-8 byte-order mark is an encoding artifact, not text (issue
    # #198): left in, it made line 1 an "unrecognized statement".
    text = text.removeprefix("\ufeff")
    suite: MockTestSuite | None = None
    case: MockTestCase | None = None
    in_mock: MockDirective | None = None
    in_mock_line = 0
    # (category, key) -> declaring line, reset per TESTCASE/BEFORE-EACH/
    # BEFORE-ALL: a duplicate MOCK would otherwise parse fine and surface
    # much later as an AMBIGUOUS_MOCK refusal with no line numbers and
    # misleading advice.
    mock_lines: dict[tuple[MockCategory, str], int] = {}
    providers: dict[str, DataProvider] = {}
    current_provider: DataProvider | None = None
    pending_expansions: list[tuple[MockTestCase, DataProvider]] = []
    # The PROVIDER the open TESTCASE is bound to (meaningful only while
    # `case` is not None) -- see the MOCK-body placeholder check below.
    case_provider: DataProvider | None = None

    def _close_provider() -> None:
        nonlocal current_provider
        if current_provider is not None and not current_provider.rows:
            raise CutParseError(
                f"line {current_provider.line}: PROVIDER "
                f"{current_provider.name!r} has no ROWs -- give at least "
                f"one row or drop the PROVIDER entirely"
            )
        current_provider = None

    # The list new MOCK directives are appended to: case.mocks inside a
    # TESTCASE, before_each/before_all inside those blocks, None
    # otherwise (MOCK outside any of them is a parse error).
    mock_target: list[MockDirective] | None = None
    before_all: list[MockDirective] = []
    before_each: list[MockDirective] = []
    hook_mocks = {"BEFORE-ALL": before_all, "BEFORE-EACH": before_each}
    hook_steps: dict[str, list[HookStep]] = {}
    # (line, text, hook) for every hook MOVE and hook MOCK body line, checked
    # for unsubstituted PROVIDER placeholders once every PROVIDER is known
    # (a PROVIDER may be declared after the hook block), see
    # _reject_hook_placeholders.
    hook_texts: list[tuple[int, str, str]] = []
    seen_testcase = False
    # None, or the open hook block: BEFORE-ALL/BEFORE-EACH/AFTER-EACH/AFTER-ALL.
    in_before: str | None = None
    before_open_line = 0

    def _hook_end(hook: str) -> str:
        return "END-BEFORE" if hook.startswith("BEFORE") else "END-AFTER"

    def _hook_allows(hook: str) -> str:
        if hook.startswith("BEFORE"):
            return "only MOCK, MOVE and PERFORM are"
        return "only MOVE and PERFORM are"

    def _current_scope_label() -> str:
        if case is not None:
            return f"TESTCASE {case.name!r}"
        assert in_before is not None
        return in_before

    def _open_mock(directive: MockDirective, line_no: int) -> MockDirective:
        assert mock_target is not None
        mock_id = (directive.category, directive.key)
        if mock_id in mock_lines:
            raise CutParseError(
                f"line {line_no}: duplicate MOCK {directive.describe()} in "
                f"{_current_scope_label()} (first declared at line "
                f"{mock_lines[mock_id]})"
            )
        mock_lines[mock_id] = line_no
        mock_target.append(directive)
        return directive

    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        if not _COMMENT_RE.match(line):
            # DFHRESP(...) in suite text expands exactly as it does in
            # program lines (splicer.cics_resp): GnuCOBOL has no CICS
            # translator, so a spliced-in `MOVE DFHRESP(NOTFND) TO WS-RESP`
            # would otherwise be a raw cobc error naming no .cut line.
            line, unknown_resp = expand_dfhresp_text(line)
            if unknown_resp:
                raise CutParseError(
                    f"line {line_no}: DFHRESP({unknown_resp[0]}) is not a "
                    f"CICS response condition mockymock knows -- use a "
                    f"condition name from the EIBRESP table (NORMAL, "
                    f"NOTFND, ENDFILE, ...) or the numeric RESP value"
                )

        if in_mock is not None:
            if case is not None and case_provider is not None:
                _reject_mock_body_placeholder(line, line_no, case_provider, in_mock)
            if case is None and in_before is not None:
                hook_texts.append((line_no, line, in_before))
            if _END_MOCK_RE.match(line):
                if in_mock.rows is not None and not in_mock.rows:
                    raise CutParseError(
                        f"line {line_no}: MOCK {in_mock.describe()} ROWS "
                        f"block has no rows -- give at least one row or "
                        f"drop ROWS entirely"
                    )
                if (
                    in_mock.rows is not None
                    and in_mock.category in SEQUENCED_CALL_CATEGORIES
                    and in_mock.terminal_row is None
                ):
                    raise CutParseError(
                        f"line {line_no}: MOCK {in_mock.describe()} ROWS "
                        f"needs a TERMINAL ( FIELD = value, ... ) group -- "
                        f"it is what every call after the last row returns, "
                        f"and without it a retrieve-and-loop program never "
                        f"sees its end condition"
                    )
                in_mock = None
            elif (
                in_mock.rows is not None
                and (term_match := _TERMINAL_RE.match(line)) is not None
            ):
                if in_mock.category not in TERMINAL_CATEGORIES:
                    raise CutParseError(
                        f"line {line_no}: TERMINAL is only supported for "
                        f"MOCK READ/RETURN/CALL/MQ/DLI/CICS ... ROWS, not MOCK "
                        f"{in_mock.category.keyword} ... ROWS (SQL rows "
                        f"always end with SQLCODE 100)"
                    )
                if in_mock.terminal_row is not None:
                    raise CutParseError(f"line {line_no}: duplicate TERMINAL group")
                if not _balanced_parens(term_match.group("pairs")):
                    raise CutParseError(
                        f"line {line_no}: malformed TERMINAL group {line!r} -- "
                        f"expected one TERMINAL ( FIELD = value, ... ) group"
                    )
                terminal: list[tuple[str, str]] = []
                for raw_pair in _split_top_level(term_match.group("pairs"), ","):
                    pair_match = _ROW_PAIR_RE.match(raw_pair.strip())
                    if pair_match is None:
                        raise CutParseError(
                            f"line {line_no}: malformed TERMINAL field "
                            f"assignment {raw_pair.strip()!r} -- expected "
                            f"FIELD = value"
                        )
                    _reject_body_sentence_period(
                        pair_match.group("value").strip(),
                        line_no,
                        in_mock.describe(),
                    )
                    terminal.append(
                        (pair_match.group("field"), pair_match.group("value").strip())
                    )
                in_mock.terminal_row = terminal
            elif (m := _FILE_STATUS_RE.match(line)) is not None:
                if in_mock.category not in FILE_STATUS_CATEGORIES:
                    eligible = "/".join(
                        sorted(c.keyword for c in FILE_STATUS_CATEGORIES)
                    )
                    raise CutParseError(
                        f"line {line_no}: FILE-STATUS IS is only valid "
                        f"inside MOCK {eligible} bodies, not MOCK "
                        f"{in_mock.category.keyword}"
                    )
                if in_mock.file_status is not None:
                    raise CutParseError(
                        f"line {line_no}: a second FILE-STATUS IS in one "
                        f"MOCK body -- only one is allowed"
                    )
                if m.group("literal") is not None:
                    code = m.group("literal")
                    if len(code) != 2:
                        raise CutParseError(
                            f"line {line_no}: FILE-STATUS IS {code!r} must "
                            f"be exactly two characters (a raw file status "
                            f"code)"
                        )
                else:
                    mnemonic = m.group("mnemonic").upper()
                    if mnemonic not in _FILE_STATUS_MNEMONICS:
                        valid = ", ".join(sorted(_FILE_STATUS_MNEMONICS))
                        raise CutParseError(
                            f"line {line_no}: unrecognized FILE-STATUS "
                            f"mnemonic {m.group('mnemonic')!r} (expected "
                            f"one of {valid}, or a quoted two-character "
                            f'code like "92")'
                        )
                    code = _FILE_STATUS_MNEMONICS[mnemonic]
                in_mock.file_status = code
            elif _FILE_STATUS_PREFIX_RE.match(line) is not None:
                valid = ", ".join(sorted(_FILE_STATUS_MNEMONICS))
                raise CutParseError(
                    f"line {line_no}: malformed FILE-STATUS IS {line!r} -- "
                    f"expected FILE-STATUS IS <mnemonic> (one of {valid}) "
                    f'or FILE-STATUS IS "xx" (a quoted two-character code)'
                )
            elif (m := _CAPTURE_RE.match(line)) is not None:
                if in_mock.category not in CAPTURE_CATEGORIES:
                    raise CutParseError(
                        f"line {line_no}: CAPTURE ARG is only valid inside "
                        f"MOCK CALL bodies (static or dynamic), not MOCK "
                        f"{in_mock.category.keyword}"
                    )
                index_text = m.group("index")
                if _CAPTURE_INDEX_RE.match(index_text) is None:
                    raise CutParseError(
                        f"line {line_no}: CAPTURE ARG {index_text!r} must "
                        f"be a positive integer (1-based USING parameter "
                        f"position)"
                    )
                try:
                    index = int(index_text)
                except ValueError as exc:
                    raise CutParseError(
                        f"line {line_no}: CAPTURE ARG {index_text!r} must "
                        f"be a positive integer (1-based USING parameter "
                        f"position)"
                    ) from exc
                if index in {n for n, _ in in_mock.captures}:
                    raise CutParseError(
                        f"line {line_no}: duplicate CAPTURE ARG {index} in "
                        f"one MOCK body -- only one CAPTURE per argument "
                        f"position is allowed"
                    )
                _reject_unbalanced_subscript(m.group("target"), line_no)
                in_mock.captures.append((index, m.group("target")))
                in_mock.capture_lines.append(line_no)
            elif _CAPTURE_PREFIX_RE.match(line) is not None:
                raise CutParseError(
                    f"line {line_no}: malformed CAPTURE statement {line!r} -- "
                    f"expected CAPTURE ARG <n> INTO <target> where <n> is a "
                    f"positive integer (1-based USING parameter position)"
                )
            elif in_mock.rows is not None:
                row_match = _ROW_RE.match(line)
                if row_match is None or not _balanced_parens(row_match.group("pairs")):
                    raise CutParseError(
                        f"line {line_no}: malformed ROWS row {line!r} -- "
                        f"expected ( FIELD = value, FIELD = value, ... )"
                    )
                row: list[tuple[str, str]] = []
                for raw_pair in _split_top_level(row_match.group("pairs"), ","):
                    pair_match = _ROW_PAIR_RE.match(raw_pair.strip())
                    if pair_match is None:
                        raise CutParseError(
                            f"line {line_no}: malformed ROWS field "
                            f"assignment {raw_pair.strip()!r} -- expected "
                            f"FIELD = value"
                        )
                    _reject_body_sentence_period(
                        pair_match.group("value").strip(),
                        line_no,
                        in_mock.describe(),
                    )
                    row.append(
                        (pair_match.group("field"), pair_match.group("value").strip())
                    )
                in_mock.rows.append(row)
            else:
                _reject_body_sentence_period(line, line_no, in_mock.describe())
                in_mock.body_lines.append(line)
            continue

        if _COMMENT_RE.match(line):
            continue

        # A PROVIDER block may hold only HEADER/ROW lines and is closed
        # only by the next TESTCASE or PROVIDER (handled by _close_provider
        # in those two branches below). Anything else -- MOVE, PERFORM,
        # MOCK, BEFORE-ALL/EACH, etc. -- must fail closed here: previously
        # none of the current-testcase/mock-collection state was reset when
        # a PROVIDER opened, so a stray statement silently attached to
        # whatever TESTCASE/BEFORE block was open before the PROVIDER, with
        # any {Placeholder} left unsubstituted.
        if current_provider is not None and not (
            _HEADER_RE.match(line)
            or _PROVIDER_ROW_RE.match(line)
            or _PROVIDER_RE.match(line)
            or _TESTCASE_RE.match(line)
        ):
            raise CutParseError(
                f"line {line_no}: {line!r} not allowed inside PROVIDER "
                f"{current_provider.name!r} -- a PROVIDER block may "
                f"contain only HEADER and ROW lines, and is closed by the "
                f"next TESTCASE or PROVIDER"
            )

        if (m := _TESTSUITE_RE.match(line)) is not None:
            if suite is not None:
                raise CutParseError(
                    f"line {line_no}: second TESTSUITE line (suite "
                    f"{suite.name!r} is already open); a .cut file holds "
                    f"exactly one TESTSUITE -- concatenated files would "
                    f"silently run only the last suite"
                )
            suite = MockTestSuite(name=m.group("name"), line=line_no)
        elif (m := PROGRAM_RE.match(line)) is not None:
            if suite is None:
                raise CutParseError(f"line {line_no}: PROGRAM before TESTSUITE")
            if suite.program_path is not None:
                raise CutParseError(
                    f"line {line_no}: second PROGRAM line (first at line "
                    f"{suite.program_line}); a suite tests exactly one program"
                )
            if (
                case is not None
                or in_before is not None
                or hook_steps
                or providers
                or before_all
                or before_each
            ):
                raise CutParseError(
                    f"line {line_no}: PROGRAM must come right after the "
                    f"TESTSUITE line, before any TESTCASE, hook or PROVIDER"
                )
            if not m.group("path").strip():
                raise CutParseError(f"line {line_no}: PROGRAM path is empty")
            suite.program_path = m.group("path")
            suite.program_line = line_no
        elif (m := _PROVIDER_RE.match(line)) is not None:
            if suite is None:
                raise CutParseError(f"line {line_no}: PROVIDER before TESTSUITE")
            if in_before is not None:
                # Without this check, opening a PROVIDER while a BEFORE
                # block is still open (author forgot END-BEFORE) parsed
                # cleanly here -- in_before was never reset by this branch
                # -- and only failed later, misattributed to whatever
                # TESTCASE line eventually followed instead of naming the
                # real culprit (audit follow-up, DSL parser/generator
                # verification pass).
                raise CutParseError(
                    f"line {line_no}: PROVIDER inside {in_before} -- "
                    f"missing {_hook_end(in_before)}"
                )
            _close_provider()
            name = m.group("name")
            if name in providers:
                raise CutParseError(
                    f"line {line_no}: duplicate PROVIDER {name!r} (first "
                    f"declared at line {providers[name].line})"
                )
            current_provider = DataProvider(name=name, line=line_no)
            providers[name] = current_provider
            # Clear the current-testcase / current-mock-collection state:
            # a PROVIDER block is not part of any TESTCASE/BEFORE block, so
            # nothing should still be able to attach to whichever one was
            # open before this PROVIDER line. (The gate above already
            # blocks every statement type that could observe this, but
            # clearing it here keeps the state honest regardless.)
            case = None
            mock_target = None
            mock_lines = {}
        elif (m := _HEADER_RE.match(line)) is not None:
            if current_provider is None:
                raise CutParseError(f"line {line_no}: HEADER outside PROVIDER")
            if current_provider.header:
                raise CutParseError(
                    f"line {line_no}: duplicate HEADER in PROVIDER "
                    f"{current_provider.name!r}"
                )
            current_provider.header = [
                field.strip() for field in m.group("fields").split(",")
            ]
        elif (m := _PROVIDER_ROW_RE.match(line)) is not None:
            if current_provider is None:
                raise CutParseError(f"line {line_no}: ROW outside PROVIDER")
            if not current_provider.header:
                raise CutParseError(
                    f"line {line_no}: ROW before HEADER in PROVIDER "
                    f"{current_provider.name!r}"
                )
            values = [v.strip() for v in _split_top_level(m.group("values"), ",")]
            if len(values) != len(current_provider.header):
                raise CutParseError(
                    f"line {line_no}: ROW has {len(values)} value(s) but "
                    f"PROVIDER {current_provider.name!r} HEADER has "
                    f"{len(current_provider.header)} column(s)"
                )
            # A missing/blank entry (nothing at all between the commas, or
            # a trailing comma with nothing after it) strips down to "" and
            # would substitute into spliced COBOL as nothing -- e.g.
            # `MOVE  TO F` or `EXPECT ... TO BE ` -- which fails to compile
            # with no .cut line attribution. Fail closed here instead. A
            # quoted empty string ("") is a deliberate empty literal and is
            # distinguishable: its quote characters survive .strip(), so it
            # is not caught by this check.
            for column, value in zip(current_provider.header, values, strict=True):
                if not value:
                    raise CutParseError(
                        f"line {line_no}: ROW value for column {column!r} "
                        f"in PROVIDER {current_provider.name!r} is blank -- "
                        f"missing/blank row values are not allowed (use a "
                        f'quoted empty string "" if you intend an empty '
                        f"value)"
                    )
            current_provider.rows.append(values)
            current_provider.row_lines.append(line_no)
        elif (m := _TESTCASE_RE.match(line)) is not None:
            if suite is None:
                raise CutParseError(f"line {line_no}: TESTCASE before TESTSUITE")
            _close_provider()
            if in_before is not None:
                raise CutParseError(
                    f"line {line_no}: TESTCASE inside {in_before} -- "
                    f"missing {_hook_end(in_before)}"
                )
            if m.group("tags") is not None and m.group("tags_after") is not None:
                raise CutParseError(
                    f"line {line_no}: TESTCASE {m.group('name')!r} has two "
                    f"TAGS lists -- give every tag in one TAGS list"
                )
            tags = _TAG_RE.findall(m.group("tags") or m.group("tags_after") or "")
            for tag in tags:
                if not tag.strip():
                    raise CutParseError(
                        f"line {line_no}: empty tag in TAGS list -- every "
                        f"tag must be a non-blank quoted word"
                    )
            provider_name = m.group("provider")
            if provider_name is not None and provider_name not in providers:
                raise CutParseError(
                    f"line {line_no}: TESTCASE {m.group('name')!r} uses "
                    f"PROVIDER {provider_name!r}, which was never declared "
                    f"-- declare a PROVIDER block before the TESTCASE that "
                    f"uses it"
                )
            case = MockTestCase(name=m.group("name"), line=line_no, tags=tags)
            suite.test_cases.append(case)
            case_provider = None
            if provider_name is not None:
                case_provider = providers[provider_name]
                pending_expansions.append((case, case_provider))
            seen_testcase = True
            mock_target = case.mocks
            mock_lines = {}
        elif (m := _HOOK_RE.match(line)) is not None:
            hook = m.group("hook")
            if suite is None:
                raise CutParseError(f"line {line_no}: {hook} before TESTSUITE")
            if in_before is not None:
                raise CutParseError(
                    f"line {line_no}: {hook} inside {in_before} -- "
                    f"missing {_hook_end(in_before)}"
                )
            if seen_testcase:
                raise CutParseError(
                    f"line {line_no}: {hook} must appear before the " f"first TESTCASE"
                )
            if hook in hook_steps:
                raise CutParseError(
                    f"line {line_no}: a second {hook} block -- a "
                    f"TESTSUITE holds at most one"
                )
            hook_steps[hook] = []
            in_before = hook
            before_open_line = line_no
            mock_target = hook_mocks.get(hook)
            mock_lines = {}
        elif _END_BEFORE_RE.match(line) or _END_AFTER_RE.match(line):
            keyword = "END-BEFORE" if _END_BEFORE_RE.match(line) else "END-AFTER"
            if in_before is None:
                opener = (
                    "BEFORE-EACH/BEFORE-ALL"
                    if keyword == "END-BEFORE"
                    else ("AFTER-EACH/AFTER-ALL")
                )
                raise CutParseError(
                    f"line {line_no}: {keyword} without an open {opener}"
                )
            if keyword != _hook_end(in_before):
                raise CutParseError(
                    f"line {line_no}: {keyword} closing {in_before} -- "
                    f"use {_hook_end(in_before)}"
                )
            in_before = None
            mock_target = None
            mock_lines = {}
        elif (m := _MOCK_QUOTED_RE.match(line)) is not None:
            if mock_target is None:
                _reject_mock_outside(in_before, line_no)
            if not m.group("key"):
                raise CutParseError(
                    f'line {line_no}: empty MOCK {m.group("cat")} key -- '
                    f"the quoted key must name what to mock"
                )
            category = _resolve_category(m.group("cat"))
            if m.group("rows") and category not in ROWS_CATEGORIES:
                raise CutParseError(
                    f"line {line_no}: {_ROWS_SUPPORTED}, not MOCK " f'{m.group("cat")}'
                )
            in_mock = _open_mock(
                MockDirective(
                    category=category,
                    key=m.group("key"),
                    rows=[] if m.group("rows") else None,
                ),
                line_no,
            )
            in_mock_line = line_no
        elif (m := _MOCK_BARE_RE.match(line)) is not None:
            if mock_target is None:
                _reject_mock_outside(in_before, line_no)
            category = _resolve_category(m.group("cat"), bare_key=True)
            if m.group("rows") and category not in ROWS_CATEGORIES:
                raise CutParseError(
                    f"line {line_no}: {_ROWS_SUPPORTED}, not MOCK " f'{m.group("cat")}'
                )
            in_mock = _open_mock(
                MockDirective(
                    category=category,
                    key=m.group("key").upper(),
                    rows=[] if m.group("rows") else None,
                ),
                line_no,
            )
            in_mock_line = line_no
        elif line.startswith("MOCK"):
            raise CutParseError(
                f"line {line_no}: malformed MOCK directive: {line!r} "
                f"(MQ/SQL/CICS/DLI take a quoted key; "
                f"{_BARE_CATS.replace('|', '/')} take a bare COBOL name; "
                f'CALL takes both -- quoted "X" for a static CALL, bare '
                f"WS-NAME for a dynamic CALL through that identifier)"
            )
        elif (m := _MOVE_RE.match(line)) is not None:
            _reject_sentence_period(m.group("value"), line_no, "MOVE")
            if case is None and in_before is not None:
                _reject_unbalanced_subscript(m.group("target"), line_no)
                hook_texts.append((line_no, line, in_before))
                hook_steps[in_before].append(
                    HookStep(
                        kind="MOVE",
                        target=m.group("target"),
                        value=m.group("value"),
                        line=line_no,
                    )
                )
                continue
            if case is None:
                raise CutParseError(f"line {line_no}: MOVE outside TESTCASE")
            _reject_unbalanced_subscript(m.group("target"), line_no)
            if case.perform_target:
                # Every setup MOVE runs before the PERFORM whatever its
                # position, so a MOVE written after it would silently run
                # first (issue #150).
                raise CutParseError(
                    f"line {line_no}: MOVE after the PERFORM -- setup MOVEs "
                    f"run before it, so write them above the PERFORM"
                )
            case.setup_moves.append((m.group("value"), m.group("target")))
            case.setup_move_lines.append(line_no)
        elif (m := _PERFORM_RE.match(line)) is not None:
            if case is None and in_before is None:
                raise CutParseError(f"line {line_no}: PERFORM outside TESTCASE")
            for name in (m.group("target"), m.group("thru")):
                if name is not None and name.endswith("."):
                    raise CutParseError(
                        f"line {line_no}: PERFORM {name!r} ends with a "
                        f"period -- drop it (a .cut PERFORM names a "
                        f"paragraph; it is not a COBOL sentence)"
                    )
            thru = m.group("thru")
            if case is None:
                assert in_before is not None
                hook_steps[in_before].append(
                    HookStep(
                        kind="PERFORM",
                        target=_upper_cobol_name(m.group("target")),
                        thru=_upper_cobol_name(thru) if thru else thru,
                        line=line_no,
                    )
                )
                continue
            if case.perform_target:
                raise CutParseError(
                    f"line {line_no}: TESTCASE {case.name!r} already has a "
                    f"PERFORM target {case.perform_target!r}; one PERFORM "
                    f"per test case"
                )
            case.perform_target = _upper_cobol_name(m.group("target"))
            case.perform_thru = _upper_cobol_name(thru) if thru else thru
        elif (m := _EXPECT_RE.match(line)) is not None:
            if case is None:
                if in_before is not None:
                    raise CutParseError(
                        f"line {line_no}: EXPECT not allowed inside "
                        f"{in_before} ({_hook_allows(in_before)})"
                    )
                raise CutParseError(f"line {line_no}: EXPECT outside TESTCASE")
            _reject_unbalanced_subscript(m.group("name"), line_no)
            if _EXPECT_DANGLING_PHRASE_RE.match(m.group("value")):
                raise CutParseError(
                    f"line {line_no}: malformed EXPECT comparison: {line!r} "
                    f"(expected [NOT] TO BE, [NOT] TO BE GREATER THAN "
                    f"[OR EQUAL TO], or [NOT] TO BE LESS THAN [OR EQUAL TO], "
                    f"followed by the value)"
                )
            _reject_sentence_period(m.group("value"), line_no)
            _reject_before_perform(case, "EXPECT", line_no)
            if m.group("comparison") and m.group("value").strip().upper() in (
                "TRUE",
                "FALSE",
            ):
                # TO BE TRUE/FALSE tests a level-88 condition-name, which
                # has no order: `TO BE GREATER THAN TRUE` means nothing.
                raise CutParseError(
                    f"line {line_no}: {m.group('value').strip()} can only "
                    f"follow [NOT] TO BE (it tests a level-88 "
                    f"condition-name): {line!r}"
                )
            case.expectations.append(
                ExpectDirective(
                    data_name=m.group("name"),
                    expected_value=m.group("value"),
                    line=line_no,
                    operator=_expect_operator(
                        m.group("negated") is not None, m.group("comparison")
                    ),
                )
            )
        elif (m := _VERIFY_QUOTED_RE.match(line)) is not None:
            if case is None:
                if in_before is not None:
                    raise CutParseError(
                        f"line {line_no}: VERIFY not allowed inside "
                        f"{in_before} ({_hook_allows(in_before)})"
                    )
                raise CutParseError(f"line {line_no}: VERIFY outside TESTCASE")
            _validate_expectation(m.group("expectation"), line_no)
            _reject_before_perform(case, "VERIFY", line_no)
            case.verifications.append(
                VerifyDirective(
                    category=_resolve_category(m.group("cat")),
                    key=m.group("key"),
                    expectation=m.group("expectation"),
                    line=line_no,
                )
            )
        elif (m := _VERIFY_BARE_RE.match(line)) is not None:
            if case is None:
                if in_before is not None:
                    raise CutParseError(
                        f"line {line_no}: VERIFY not allowed inside "
                        f"{in_before} ({_hook_allows(in_before)})"
                    )
                raise CutParseError(f"line {line_no}: VERIFY outside TESTCASE")
            _validate_expectation(m.group("expectation"), line_no)
            _reject_before_perform(case, "VERIFY", line_no)
            case.verifications.append(
                VerifyDirective(
                    category=_resolve_category(m.group("cat"), bare_key=True),
                    key=m.group("key").upper(),
                    expectation=m.group("expectation"),
                    line=line_no,
                )
            )
        else:
            raise CutParseError(f"line {line_no}: unrecognized statement: {line!r}")

    _close_provider()

    if in_mock is not None:
        raise CutParseError(
            f"line {in_mock_line}: unterminated MOCK {in_mock.describe()}: "
            f"reached end of file with no END-MOCK"
        )

    if in_before is not None:
        raise CutParseError(
            f"line {before_open_line}: unterminated {in_before}: reached "
            f"end of file with no {_hook_end(in_before)}"
        )

    if suite is None:
        raise CutParseError("no TESTSUITE found")

    _reject_hook_placeholders(hook_texts, providers)
    _apply_before_blocks(suite, before_all, before_each)
    suite.before_all_mocks = list(before_all)
    suite.before_each_mocks = list(before_each)
    suite.before_all_steps = hook_steps.get("BEFORE-ALL", [])
    suite.before_each_steps = hook_steps.get("BEFORE-EACH", [])
    suite.after_each_steps = hook_steps.get("AFTER-EACH", [])
    suite.after_all_steps = hook_steps.get("AFTER-ALL", [])

    if pending_expansions:
        suite.test_cases = _expand_providers(suite.test_cases, pending_expansions)

    return suite
