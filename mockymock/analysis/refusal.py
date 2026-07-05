"""Refusal gate: whole-program (parse errors, unresolved COPY statements,
nested EXEC blocks) and per-TESTCASE (directive/site matching) checks.

Per-TESTCASE checks are computed over the statements reachable from that
case's PERFORM target. Reachability is a self-contained BFS over
PerformStatement targets within the same program -- not cobolparser's
ProgramFlowAnalyzer -- because that keeps this module's correctness
checkable against the same small set of verified attributes
(CobolParagraph.statements, PerformStatement.target_paragraph) the rest of
mockymock already depends on. A CALL is a leaf: it is never traversed into,
since the called program's source isn't part of this compilation unit.

v2 matching model: every reachable mockable BoundarySite must be matched by
exactly one MockDirective of the test case --

- zero matches  -> UNMOCKED_CALL / UNMOCKED_FILE_OP / UNMOCKED_SQL /
                   UNMOCKED_CICS / UNMOCKED_DLI / UNMOCKED_CONSOLE_ACCEPT
                   (an unmocked CALL has nowhere to link; unmocked file I/O
                   would hit a nonexistent file in the sandbox; unmocked
                   EXEC cannot compile; unmocked console ACCEPT reads
                   whatever stdin happens to be attached)
- two+ matches  -> AMBIGUOUS_MOCK (fail closed rather than pick one)
- matched but nested WITHOUT a validated span -> UNSUPPORTED_NESTED_MOCK_
                   TARGET: nested sites are spliceable when source_map's
                   annotate_nested_sites validated a replacement span for
                   them (scope words located by re-lexing; see docs/
                   2026-07-05-nested-mock-targets-design.md). Sites whose
                   layout fails a safety precondition -- or that were never
                   annotated -- refuse with the precise reason rather than
                   risk swallowing a block terminator and corrupting
                   control flow (an earlier attempt without the scope map
                   did exactly that; see task-14-report.md).

A directive matching no reachable site is UNMATCHED_MOCK; a VERIFY whose
(category, key) no MOCK directive of the same case declares is
VERIFY_WITHOUT_MOCK (its tally field would be stale or undeclared).

Detected-but-unmockable sites keep their own refusals: DYNAMIC_CALL (target
unknown at parse time) and UNSUPPORTED_SORT_MERGE (SORT/MERGE/RELEASE/
RETURN mock an algorithm plus its INPUT/OUTPUT PROCEDURE contract, not a
boundary statement). PERFORM ... THRU targets are deliberately NOT
range-expanded (that needs paragraph source-order guarantees this module
doesn't verify); any reachable paragraph containing one triggers
UNSUPPORTED_PERFORM_THRU.

check_nested_exec (NESTED_EXEC) is a whole-program check: GnuCOBOL cannot
compile raw EXEC blocks, so every EXEC site must be stubbed program-wide
regardless of reachability -- a nested EXEC with no validated splice span
(same preconditions as above) therefore refuses the file by its mere
existence anywhere in the program.

check_unresolved_copybooks (UNRESOLVED_COPYBOOK) is a whole-program check,
not a per-TESTCASE one: an unresolved COPY affects the whole program
regardless of which TESTCASE runs. It exists because cobolparser's
parse_cobol does NOT raise a parse error for an unresolved COPY statement --
verified empirically: parsing raw (unexpanded) source containing
`COPY ORDREC.` yields `result.success is True` and an empty `data_items`
list for that DATA DIVISION section. Worse, the AST-node `CopyStatement`
class is never instantiated by any parser, so an unresolved COPY leaves
*zero* trace in the AST. The only reliable signal is therefore textual:
this function re-lexes `raw_source` with cobolparser's own `CobolLexer`
(free_form=True -- the default fixed-format column rules would garble
already-normalized text) and looks for a `TokenType.COPY` token, rather
than a naive substring search that could false-positive on the word "COPY"
in a comment or string literal.
"""

from __future__ import annotations

from dataclasses import dataclass

from cobolparser.lexer import CobolLexer, TokenType
from cobolparser.models.statements.control import PerformStatement
from cobolparser.preprocess import normalize_fixed_format

from mockymock.analysis.mock_surface import (
    BoundarySite,
    MockSurface,
    _all_paragraphs,
    _nested_statement_lists,
    normalize_exec_text,
)
from mockymock.dsl.model import (
    EXEC_CATEGORIES,
    MockCategory,
    MockDirective,
    MockTestCase,
)

_UNMOCKED_CODES = {
    MockCategory.CALL: "UNMOCKED_CALL",
    MockCategory.SQL: "UNMOCKED_SQL",
    MockCategory.CICS: "UNMOCKED_CICS",
    MockCategory.DLI: "UNMOCKED_DLI",
    MockCategory.ACCEPT: "UNMOCKED_CONSOLE_ACCEPT",
}
# every file-op category shares one code
_UNMOCKED_FILE_OP_CODE = "UNMOCKED_FILE_OP"


@dataclass
class RefusalReason:
    code: str
    message: str


# Shown when a nested site reaches a check before annotate_nested_sites ran
# (or was skipped): treat it as unspliceable rather than assume it is safe.
_UNANNOTATED = "nested-site spliceability was not annotated"


def directive_matches_site(directive: MockDirective, site: BoundarySite) -> bool:
    """Category must agree; then CALL keys match the call literal exactly,
    file-op/ACCEPT keys match any of the site's (uppercased) names, and
    SQL/CICS/DLI keys prefix-match the site's normalized EXEC text."""
    if site.category is not directive.category:
        return False
    if directive.category in EXEC_CATEGORIES:
        prefix = normalize_exec_text(directive.key)
        return bool(prefix) and (site.match_text or "").startswith(prefix)
    if directive.category is MockCategory.CALL:
        return directive.key in site.keys
    return directive.key.upper() in site.keys


def check_whole_program(parse_result) -> list[RefusalReason]:
    if parse_result.success:
        return []
    return [
        RefusalReason(
            code="PARSE_ERROR",
            message=f"cobolparser reported {len(parse_result.errors)} parse error(s)",
        )
    ]


def check_nested_exec(surface: MockSurface) -> list[RefusalReason]:
    """Whole-program: a nested EXEC SQL/CICS/DLI with no validated splice
    span refuses the file. Every EXEC block must be commented out for cobc
    to compile the program at all; a nested EXEC whose span was validated
    by `annotate_nested_sites` can be stubbed like any other site, so only
    the unspliceable ones (or unannotated ones -- fail closed) refuse."""
    return [
        RefusalReason(
            code="NESTED_EXEC",
            message=(
                f"EXEC {site.label} at line {site.line} (paragraph "
                f"'{site.paragraph_name}') is nested inside a conditional/"
                f"loop body and cannot be stubbed safely: "
                f"{site.unspliceable_reason or _UNANNOTATED} -- every EXEC "
                f"block must be stubbed out for GnuCOBOL to compile the "
                f"program"
            ),
        )
        for site in surface.exec_sites()
        if site.nested and site.span is None
    ]


def check_unresolved_copybooks(raw_source: str) -> list[RefusalReason]:
    """Refuse if `raw_source` still contains an unresolved COPY statement.

    Must be called with the exact source text handed to `parse_cobol` (i.e.
    after whatever `--copybook-path` expansion was or wasn't applied): if
    expansion succeeded, the COPY statement itself is replaced by the
    copybook's expanded content and no COPY token remains; if expansion was
    skipped or didn't fully resolve, the literal `COPY ...` statement is
    still present and is detected here. See the module docstring for why a
    textual/lexer-based check is used instead of an AST-based one.
    """
    normalized = normalize_fixed_format(raw_source.splitlines())
    lexer = CobolLexer(normalized, free_form=True)
    tokens = lexer.tokenize()
    copy_tokens = [t for t in tokens if t.type == TokenType.COPY]
    if not copy_tokens:
        return []
    lines = sorted({t.location.line for t in copy_tokens})
    return [
        RefusalReason(
            code="UNRESOLVED_COPYBOOK",
            message=(
                f"unresolved COPY statement at line {line} -- the DATA "
                f"DIVISION section it belongs to has no expanded content "
                f"(cobolparser does not raise a parse error for an "
                f"unresolved COPY; it silently produces an empty data-item "
                f"list instead), so splicing/compiling would proceed with "
                f"missing WORKING-STORAGE fields -- pass --copybook-path "
                f"pointing at the copybook's directory"
            ),
        )
        for line in lines
    ]


def check_test_case(
    surface: MockSurface,
    program,
    case: MockTestCase,
) -> list[RefusalReason]:
    reasons: list[RefusalReason] = []
    reachable, thru_paragraphs = _reachable_paragraphs(program, case.perform_target)

    if case.perform_target not in reachable:
        reasons.append(
            RefusalReason(
                code="UNKNOWN_PARAGRAPH",
                message=(
                    f"PERFORM target '{case.perform_target}' not found in "
                    f"PROCEDURE DIVISION"
                ),
            )
        )
        return reasons

    for paragraph_name in sorted(thru_paragraphs):
        reasons.append(
            RefusalReason(
                code="UNSUPPORTED_PERFORM_THRU",
                message=(
                    f"paragraph '{paragraph_name}' uses PERFORM ... THRU, "
                    f"not supported (range expansion needs source-order "
                    f"guarantees not yet verified)"
                ),
            )
        )

    matched_directives: set[int] = set()
    for site in surface.sites_in(reachable):
        if site.category is None:
            if site.label == "dynamic CALL":
                reasons.append(
                    RefusalReason(
                        code="DYNAMIC_CALL",
                        message=(
                            f"paragraph '{site.paragraph_name}' (line {site.line}) "
                            f"contains a dynamic CALL, not supported"
                        ),
                    )
                )
            else:
                reasons.append(
                    RefusalReason(
                        code="UNSUPPORTED_SORT_MERGE",
                        message=(
                            f"paragraph '{site.paragraph_name}' (line {site.line}) "
                            f"contains a SORT/MERGE-family statement "
                            f"(SORT/MERGE/RELEASE/RETURN), which mocks an "
                            f"algorithm plus its INPUT/OUTPUT PROCEDURE "
                            f"contract rather than a boundary -- not supported"
                        ),
                    )
                )
            continue

        matches = [d for d in case.mocks if directive_matches_site(d, site)]
        for directive in matches:
            matched_directives.add(id(directive))

        if not matches:
            code = _UNMOCKED_CODES.get(site.category, _UNMOCKED_FILE_OP_CODE)
            reasons.append(
                RefusalReason(
                    code=code,
                    message=(
                        f"{site.label} boundary at line {site.line} (paragraph "
                        f"'{site.paragraph_name}'"
                        + (f", keys {'/'.join(site.keys)}" if site.keys else "")
                        + (
                            f', text "{site.match_text[:60]}"'
                            if site.match_text
                            else ""
                        )
                        + f") is reachable from '{case.perform_target}' but "
                        f"no MOCK directive in this test case matches it"
                    ),
                )
            )
        elif len(matches) > 1:
            described = ", ".join(d.describe() for d in matches)
            reasons.append(
                RefusalReason(
                    code="AMBIGUOUS_MOCK",
                    message=(
                        f"{site.label} boundary at line {site.line} (paragraph "
                        f"'{site.paragraph_name}') is matched by more than one "
                        f"MOCK directive ({described}) -- make the keys "
                        f"unambiguous"
                    ),
                )
            )
        elif site.nested and site.span is None:
            reasons.append(
                RefusalReason(
                    code="UNSUPPORTED_NESTED_MOCK_TARGET",
                    message=(
                        f"MOCK {matches[0].describe()} matches a statement at "
                        f"line {site.line} nested inside a conditional/loop "
                        f"body (IF/EVALUATE/inline PERFORM) that cannot be "
                        f"safely spliced: "
                        f"{site.unspliceable_reason or _UNANNOTATED}"
                    ),
                )
            )

    for directive in case.mocks:
        if id(directive) not in matched_directives:
            reasons.append(
                RefusalReason(
                    code="UNMATCHED_MOCK",
                    message=(
                        f"MOCK {directive.describe()} does not match any "
                        f"boundary site reachable from '{case.perform_target}'"
                    ),
                )
            )

    declared = {(m.category, m.key) for m in case.mocks}
    for verification in case.verifications:
        if (verification.category, verification.key) not in declared:
            reasons.append(
                RefusalReason(
                    code="VERIFY_WITHOUT_MOCK",
                    message=(
                        f"VERIFY {verification.category.value} "
                        f"{verification.key!r} has no matching MOCK directive "
                        f"in this test case -- its tally counter would be "
                        f"undeclared or stale"
                    ),
                )
            )

    return reasons


def _find_performs(statements: list) -> list[PerformStatement]:
    """Recursively collect every PerformStatement in `statements`, including
    ones nested inside IF/EVALUATE branches, inline PERFORM bodies, and IO
    clause bodies (AT END, INVALID KEY, etc.) -- reusing mock_surface.py's
    `_nested_statement_lists` rather than reimplementing nested-statement
    detection.
    """
    found = []
    for statement in statements:
        if isinstance(statement, PerformStatement):
            found.append(statement)
        for nested in _nested_statement_lists(statement):
            found.extend(_find_performs(nested))
    return found


def _reachable_paragraphs(program, start: str) -> tuple[set[str], set[str]]:
    """Return (reachable paragraph names, paragraph names containing a
    reachable PERFORM ... THRU), both computed in a single BFS pass over
    PerformStatement.target_paragraph edges. PERFORM ... THRU targets
    themselves are not followed -- see module docstring / check_test_case's
    UNSUPPORTED_PERFORM_THRU refusal for why range expansion is out of
    scope.
    """
    procedure = program.get_division("PROCEDURE")
    if procedure is None:
        return set(), set()
    by_name = {p.paragraph_name: p for p in _all_paragraphs(procedure)}
    if start not in by_name:
        return set(), set()

    seen: set[str] = set()
    thru_paragraphs: set[str] = set()
    stack = [start]
    while stack:
        name = stack.pop()
        if name in seen or name not in by_name:
            continue
        seen.add(name)
        for statement in _find_performs(by_name[name].statements):
            if statement.thru_paragraph:
                thru_paragraphs.add(name)
            if statement.target_paragraph:
                stack.append(statement.target_paragraph)
    return seen, thru_paragraphs
