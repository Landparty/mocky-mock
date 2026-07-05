"""Refusal gate: whole-program (parse errors, unresolved COPY statements) and
per-TESTCASE (dynamic CALL / file I/O / EXEC reachable from PERFORM target,
an unmatched MOCK CALL directive, a MOCK CALL targeting a nested call site,
or a reachable static CALL that no MOCK CALL directive mocks) checks.

Reachability is computed with a self-contained BFS over PerformStatement
targets within the same program -- not cobolparser's ProgramFlowAnalyzer --
because that keeps this module's correctness checkable against the same
small set of verified attributes (CobolParagraph.statements,
PerformStatement.target_paragraph) the rest of mockymock already depends
on, rather than additionally depending on ProgramFlowAnalyzer's full edge
taxonomy. A CALL is a leaf: it is never traversed into, since the called
program's source isn't part of this compilation unit.

PerformStatements are discovered at any nesting depth -- including inside
IF/EVALUATE branches, inline PERFORM bodies, and IO clause bodies (AT END,
INVALID KEY, etc.) -- by reusing mock_surface.py's `_nested_statement_lists`
helper (see `_find_performs`), not a flat `paragraph.statements` scan.
PERFORM ... THRU targets are deliberately NOT range-expanded (that needs
paragraph source-order guarantees this module doesn't verify); instead, any
reachable paragraph containing a PERFORM ... THRU triggers its own
fail-closed refusal (UNSUPPORTED_PERFORM_THRU).

A MOCK CALL directive whose target call name has a *nested* reachable call
site (inside an IF/EVALUATE branch, inline PERFORM body, or similar) is
refused with UNSUPPORTED_NESTED_CALL_TARGET rather than spliced: the
splicer's replacement span depends on `source_map.py`'s boundary-list
approach, and cobolparser's AST has no location data for block terminators
(END-IF, END-EVALUATE, etc.), so a spliced nested CALL could swallow its
enclosing block's terminator and silently corrupt control flow. This is the
same fail-closed philosophy as UNSUPPORTED_PERFORM_THRU above -- refuse
rather than risk a wrong result. (An earlier fix attempt tried recursing the
splicer into nested bodies instead and discovered it corrupts control flow;
see task-14-report.md's "BLOCKED" section for the full analysis.)

The reverse of UNMATCHED_MOCK is UNMOCKED_CALL: a real, reachable static
CALL that the .cut file simply never mocks. In mockymock's architecture an
unmocked CALL has nowhere to link -- the called program's real source is
never part of the compilation unit -- so it fails to compile/link if left
in place. This applies uniformly to top-level and nested reachable static
call sites (both would fail to link if left unmocked); it deliberately does
not special-case nesting, since UNSUPPORTED_NESTED_CALL_TARGET above already
separately catches "tried to mock a nested site" (it only fires when the
name IS in mocked_call_names). A reachable static call that's both nested
AND unmocked gets only UNMOCKED_CALL, which is correct: don't also flag
nesting for a call nobody tried to mock.

check_unresolved_copybooks (UNRESOLVED_COPYBOOK) is a whole-program check,
not a per-TESTCASE one: an unresolved COPY affects the whole program
regardless of which TESTCASE runs. It exists because cobolparser's
parse_cobol does NOT raise a parse error for an unresolved COPY statement --
verified empirically: parsing raw (unexpanded) source containing
`COPY ORDREC.` yields `result.success is True` and an empty `data_items`
list for that DATA DIVISION section (see
tests/integration/test_copybook_expansion.py's
test_generate_without_copybook_path_leaves_copy_unresolved for the concrete
proof). Worse, the AST-node `CopyStatement` class in
cobolparser/models/statements/misc.py is never instantiated by any parser
(confirmed empirically: `ast.find_all_by_type("CopyStatement")` returns `[]`
and `"CopyStatement"` never appears in `ast.to_dict()`'s JSON for a program
with an unexpanded COPY) -- so an unresolved COPY leaves *zero* trace in the
AST. The only reliable signal is therefore textual: this function re-lexes
`raw_source` (the exact text handed to `parse_cobol`, before whatever
expansion was or wasn't applied) with cobolparser's own `CobolLexer` and
looks for a `TokenType.COPY` token, rather than a naive substring search
that could false-positive on the word "COPY" appearing in a comment or
string literal. Verified empirically against this repo's own COPY-bearing
fixture (tests/integration/fixtures/copybook_example/MAINPGM.cbl) and a
constructed false-positive probe (COPY inside a VALUE literal and as part
of an identifier like WS-COPYRIGHT): the lexer correctly tokenizes COPY as
a keyword only when it appears in COPY-statement position, never inside a
string or as a substring of another word. `free_form=True` is required --
`CobolLexer` defaults to `free_form=False` (fixed-format column rules),
which garbles already-normalized free-form text (each line loses its first
few characters, since the lexer treats them as sequence-number/indicator
columns); cobolparser's own `tokenize_cobol()` convenience function
hardcodes `free_form=False` too and so is not usable here directly.
"""

from __future__ import annotations

from dataclasses import dataclass

from cobolparser.lexer import CobolLexer, TokenType
from cobolparser.models.statements.control import PerformStatement
from cobolparser.preprocess import normalize_fixed_format

from mockymock.analysis.mock_surface import (
    MockSurface,
    _all_paragraphs,
    _nested_statement_lists,
)


@dataclass
class RefusalReason:
    code: str
    message: str


def check_whole_program(parse_result) -> list[RefusalReason]:
    if parse_result.success:
        return []
    return [
        RefusalReason(
            code="PARSE_ERROR",
            message=f"cobolparser reported {len(parse_result.errors)} parse error(s)",
        )
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
    perform_target: str,
    mocked_call_names: set[str],
) -> list[RefusalReason]:
    reasons: list[RefusalReason] = []
    reachable, thru_paragraphs = _reachable_paragraphs(program, perform_target)

    if perform_target not in reachable:
        reasons.append(
            RefusalReason(
                code="UNKNOWN_PARAGRAPH",
                message=f"PERFORM target '{perform_target}' not found in PROCEDURE DIVISION",
            )
        )
        return reasons

    for paragraph_name in sorted(thru_paragraphs):
        reasons.append(
            RefusalReason(
                code="UNSUPPORTED_PERFORM_THRU",
                message=(
                    f"paragraph '{paragraph_name}' uses PERFORM ... THRU, "
                    f"not supported in v1 (range expansion needs source-order "
                    f"guarantees not yet verified)"
                ),
            )
        )

    reachable_call_names: set[str] = set()
    nested_call_names: set[str] = set()
    for site in surface.call_sites:
        if site.paragraph_name not in reachable:
            continue
        if site.kind.value == "dynamic":
            reasons.append(
                RefusalReason(
                    code="DYNAMIC_CALL",
                    message=(
                        f"paragraph '{site.paragraph_name}' (line {site.line}) "
                        f"contains a dynamic CALL, not supported in v1"
                    ),
                )
            )
        else:
            reachable_call_names.add(site.program_name)
            if site.nested:
                nested_call_names.add(site.program_name)

    if reachable & surface.file_io_paragraphs:
        hit = sorted(reachable & surface.file_io_paragraphs)[0]
        reasons.append(
            RefusalReason(
                code="UNMOCKED_FILE_IO",
                message=f"paragraph '{hit}' performs file I/O, not mocked in v1",
            )
        )

    if reachable & surface.exec_paragraphs:
        hit = sorted(reachable & surface.exec_paragraphs)[0]
        reasons.append(
            RefusalReason(
                code="UNSUPPORTED_EXEC",
                message=f"paragraph '{hit}' contains EXEC SQL/CICS/DLI, not supported in v1",
            )
        )

    if reachable & surface.console_accept_paragraphs:
        hit = sorted(reachable & surface.console_accept_paragraphs)[0]
        reasons.append(
            RefusalReason(
                code="UNMOCKED_CONSOLE_ACCEPT",
                message=(
                    f"paragraph '{hit}' reads console input via ACCEPT, not "
                    f"mocked in v1 -- at test runtime it would read whatever "
                    f"stdin happens to be attached, making the result "
                    f"nondeterministic"
                ),
            )
        )

    for name in sorted(mocked_call_names & nested_call_names):
        reasons.append(
            RefusalReason(
                code="UNSUPPORTED_NESTED_CALL_TARGET",
                message=(
                    f'MOCK CALL "{name}" matches a CALL statement nested inside '
                    f"a conditional/loop body (IF/EVALUATE/inline PERFORM), which "
                    f"cannot be safely spliced in v1 (cobolparser has no location "
                    f"data for block terminators like END-IF, so the splicer "
                    f"cannot determine where the nested statement's replacement "
                    f"span should end)"
                ),
            )
        )

    for name in mocked_call_names - reachable_call_names:
        reasons.append(
            RefusalReason(
                code="UNMATCHED_MOCK",
                message=(
                    f"MOCK CALL \"{name}\" does not match any static CALL "
                    f"site reachable from '{perform_target}'"
                ),
            )
        )

    for name in sorted(reachable_call_names - mocked_call_names):
        reasons.append(
            RefusalReason(
                code="UNMOCKED_CALL",
                message=(
                    f'CALL "{name}" is reachable from \'{perform_target}\' but not '
                    f"mocked by any MOCK CALL directive in this test case -- an "
                    f"unmocked CALL has nowhere to link, since the called "
                    f"program's real source is never part of this compilation unit"
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
