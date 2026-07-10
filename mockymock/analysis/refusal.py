"""Refusal gate: whole-program (parse errors, unresolved COPY statements,
nested EXEC blocks) and per-TESTCASE (directive/site matching) checks.

Per-TESTCASE checks are computed over the statements reachable from that
case's PERFORM target. Reachability is a self-contained BFS over
PerformStatement AND GoStatement targets within the same program -- not
cobolparser's ProgramFlowAnalyzer -- because that keeps this module's
correctness checkable against the same small set of verified attributes
(CobolParagraph.statements, CobolParagraph.location.line,
PerformStatement.target_paragraph, PerformStatement.thru_paragraph,
GoStatement.target_paragraphs) the rest of mockymock already depends on.
A CALL is a leaf: it is never traversed into, since the called program's
source isn't part of this compilation unit.

Flow-edge model (fail closed):
- PERFORM <paragraph> pushes the paragraph; PERFORM <section> pushes every
  paragraph of that section (a performed section executes all of them by
  fall-through).
- GO TO pushes every target -- a computed `GO TO A B C DEPENDING ON X`
  carries all of its targets in GoStatement.target_paragraphs. Targets may
  be paragraphs or sections. (A GO TO that escapes its PERFORM range and
  relies on falling through *past* its target paragraph is not modeled --
  such control flow runs off the end of the program at test runtime and is
  covered by the documented STOP RUN limitation. Noted by the 2026-07-09
  final branch review: pre-neutralization this is a clean, loud crash --
  the real terminator exits the binary. Once ANY case has neutralized that
  terminator (via its own safe plain chain), a DIFFERENT case reaching the
  same, now-neutralized terminator through this unmodeled GO-TO-escape
  path would hit `EXIT PARAGRAPH` from a paragraph entered via `GO TO`,
  which per the design doc's spike #4 "just stops, no crash, no return" --
  a subtler failure than the pre-branch behavior. Exotic, not hardened
  against; documented here rather than silently assumed harmless.)
- Any PERFORM/GO TO target that resolves to neither a paragraph nor a
  section refuses with UNRESOLVED_FLOW_TARGET instead of being skipped: a
  target the model cannot resolve means the reachable set is not trusted.

check_whole_program additionally refuses two constructs the flow model
deliberately does not attempt to handle, by their mere presence anywhere
in the program: DECLARATIVES (UNSUPPORTED_DECLARATIVES -- USE procedures
run on I/O conditions, invisible to any PERFORM/GO TO edge) and ALTER
(UNSUPPORTED_ALTER -- it rewrites GO TO targets at runtime, so no static
edge set is sound).

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

- matched but sharing a source line with other code (top-level sites) ->
  UNSUPPORTED_MOCK_TARGET_LAYOUT: a top-level splice comments out whole
  lines, so a boundary statement that does not own its line(s) -- sibling
  code before it, a one-line paragraph header, or another statement
  starting on the same line -- would silently delete that sibling code.
  annotate_nested_sites stamps the layout problem; the gate refuses it.

Detected-but-unmockable sites keep their own refusals: DYNAMIC_CALL (now
only for a dynamic CALL whose target identifier cobolparser failed to
capture -- identifier-carrying dynamic CALLs are mockable via
MOCK CALL <identifier>, see docs/2026-07-06-dynamic-call-mocks-design.md)
and UNSUPPORTED_SORT_MERGE (SORT/MERGE/RELEASE/RETURN mock an algorithm
plus its INPUT/OUTPUT PROCEDURE contract, not a boundary statement).
A reachable CANCEL is covered when the test case mocks CALL (static or
dynamic) for the same name -- the mocked CALL never loads a real module,
so the CANCEL is a guaranteed GnuCOBOL no-op left in place -- and refuses
UNMOCKED_CANCEL otherwise.
PERFORM ... THRU ranges ARE expanded: every paragraph in the source-order
slice [target..thru] is reachable (fall-through executes them all), with
the required source-order guarantee checked at runtime
(_source_ordered_paragraphs). UNSUPPORTED_PERFORM_THRU survives only for
degenerate ranges -- unverifiable order, missing or ambiguous endpoints,
backwards ranges -- and a test case's own PERFORM ... THRU seeds the BFS
with its range (missing driver-side endpoints are UNKNOWN_PARAGRAPH).

check_nested_exec (NESTED_EXEC) is a whole-program check: GnuCOBOL cannot
compile raw EXEC blocks, so every EXEC site must be stubbed program-wide
regardless of reachability -- a nested EXEC with no validated splice span
(same preconditions as above) therefore refuses the file by its mere
existence anywhere in the program.

check_whole_program refuses on parse errors (PARSE_ERROR) and — since
cobolparser's 2026-07-07 silent-drop remediation gave dropped content a
signal — on every `ParseResult.warnings` entry (PARSE_WARNING): unsupported
verbs, unparsed clause leftovers, and multi-program compilation units all
mean the AST is incomplete, so a "clean" splice would silently drop program
behavior. check_expansion_warnings (EXPANSION_WARNING) does the same for
lossy-decode copybook-expansion warnings (U+FFFD already substituted into
the source this run would compile); the advisory lint heuristics sharing
that channel are deliberately NOT refused (see the marker constant).

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

import re
from dataclasses import dataclass, field

from cobolparser.lexer import CobolLexer, TokenType
from cobolparser.models.program import CobolParagraph
from cobolparser.models.statements.control import GoStatement, PerformStatement
from cobolparser.models.statements.misc import AlterStatement
from cobolparser.preprocess import normalize_fixed_format

from mockymock.analysis.linkage import linkage_plan
from mockymock.analysis.mock_surface import (
    _TERMINATOR_LABELS,
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
    MockTestSuite,
)
from mockymock.splicer.source_map import statement_top_level_problem

_UNMOCKED_CODES = {
    MockCategory.CALL: "UNMOCKED_CALL",
    MockCategory.DYNCALL: "UNMOCKED_CALL",
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


@dataclass
class TerminatorPlan:
    """One physical STOP RUN(RUN-form)/GOBACK statement found safe to
    neutralize, plus every intermediate PERFORM statement (deduped across
    the whole suite by identity) that needs the early-exit flag-check
    inserted after it for this terminator's propagation to correctly
    reach the test driver. Empty `chain_performs` means the terminator
    sits directly in a test's own PERFORM target -- no intermediate
    instrumentation needed. `exit_kind` is "PARAGRAPH" (the default) or
    "SECTION" for the one SECTION-scoped shape
    docs/2026-07-10-section-scoped-terminator-support-design.md supports
    -- a terminator in a SECTION's first paragraph, entered exclusively
    via PERFORM <section-name>. See
    docs/2026-07-08-goback-stop-run-support-design.md and
    docs/2026-07-10-section-scoped-terminator-support-design.md."""

    site: BoundarySite
    chain_performs: list = field(default_factory=list)
    exit_kind: str = "PARAGRAPH"


# Shown when a nested site reaches a check before annotate_nested_sites ran
# (or was skipped): treat it as unspliceable rather than assume it is safe.
_UNANNOTATED = "nested-site spliceability was not annotated"


def directive_matches_site(directive: MockDirective, site: BoundarySite) -> bool:
    """Category must agree; then CALL keys match the call literal exactly,
    file-op/ACCEPT/DYNCALL keys match any of the site's (uppercased) names
    (the identifier a dynamic CALL calls through), and SQL/CICS/DLI keys
    prefix-match the site's normalized EXEC text. The category identity
    check is what keeps quoted (static) and bare (dynamic) CALL keys from
    ever cross-matching."""
    if site.category is not directive.category:
        return False
    if directive.category in EXEC_CATEGORIES:
        prefix = normalize_exec_text(directive.key)
        return bool(prefix) and (site.match_text or "").startswith(prefix)
    if directive.category is MockCategory.CALL:
        return directive.key in site.keys
    return directive.key.upper() in site.keys


def check_whole_program(parse_result) -> list[RefusalReason]:
    """PARSE_ERROR for a failed parse; PARSE_WARNING for each entry in
    `ParseResult.warnings`. Since cobolparser's 2026-07-07 silent-drop fixes,
    a warning is the only signal that content was dropped from a "clean"
    parse (`success=True, errors=0`): unsupported verbs (INVOKE, EXHIBIT,
    ...), unparsed clause leftovers, and multi-program compilation units
    (only the first program's divisions are where mockymock looks) all
    surface here. Any of them means the AST the splicer would work from is
    incomplete, so each warning refuses fail-closed. (Lossy copybook-decode
    diagnostics travel a different channel on mockymock's CLI path —
    `CopybookExpansion.statistics.warnings` — and are gated by
    `check_expansion_warnings` instead.)

    Also whole-program, AST-based (both parse warning-free, verified
    empirically): UNSUPPORTED_DECLARATIVES for any program containing a
    DECLARATIVES block, and UNSUPPORTED_ALTER for any ALTER statement --
    see `_check_unsupported_control_flow` for why neither can ever be
    modeled by the reachability BFS."""
    reasons: list[RefusalReason] = []
    if not parse_result.success:
        reasons.append(
            RefusalReason(
                code="PARSE_ERROR",
                message=(
                    f"cobolparser reported {len(parse_result.errors)} parse "
                    f"error(s)"
                ),
            )
        )
    for warning in getattr(parse_result, "warnings", None) or []:
        reasons.append(
            RefusalReason(
                code="PARSE_WARNING",
                message=(
                    f"cobolparser reported a parse warning -- the AST is "
                    f"missing content, so splicing would silently drop "
                    f"program behavior: {warning}"
                ),
            )
        )
    program = getattr(parse_result, "ast", None)
    if program is not None:
        reasons.extend(_check_unsupported_control_flow(program))
    return reasons


def _check_unsupported_control_flow(program) -> list[RefusalReason]:
    """UNSUPPORTED_DECLARATIVES / UNSUPPORTED_ALTER, unconditional
    whole-program refusals (like SORT/MERGE, but independent of
    reachability):

    - DECLARATIVES sections hold USE procedures the runtime invokes on I/O
      conditions -- no PERFORM/GO TO edge ever points at them, so the
      reachability BFS structurally cannot gate the boundary statements
      inside them. cobolparser parses a DECLARATIVES block warning-free,
      leaving a paragraph literally named DECLARATIVES (a reserved word no
      valid user paragraph can use -- verified empirically), which is the
      detection signal here.
    - ALTER rewrites another paragraph's GO TO target at runtime, so no
      static edge set is sound for a program containing one.
    """
    procedure = program.get_division("PROCEDURE")
    if procedure is None:
        return []
    reasons: list[RefusalReason] = []
    for paragraph in _all_paragraphs(procedure):
        if paragraph.paragraph_name.upper() == "DECLARATIVES":
            reasons.append(
                RefusalReason(
                    code="UNSUPPORTED_DECLARATIVES",
                    message=(
                        f"program contains a DECLARATIVES block (line "
                        f"{paragraph.location.line}) -- USE procedures run "
                        f"on I/O conditions outside any PERFORM/GO TO edge, "
                        f"so the reachability gate cannot check the boundary "
                        f"statements inside them"
                    ),
                )
            )
            break
    for paragraph in _all_paragraphs(procedure):
        for statement in _find_statements_of_type(paragraph.statements, AlterStatement):
            reasons.append(
                RefusalReason(
                    code="UNSUPPORTED_ALTER",
                    message=(
                        f"paragraph '{paragraph.paragraph_name}' (line "
                        f"{statement.location.line}) contains an ALTER "
                        f"statement -- ALTER rewrites GO TO targets at "
                        f"runtime, so no static reachability analysis of "
                        f"this program is sound"
                    ),
                )
            )
    return reasons


def _find_statements_of_type(
    statements: list, statement_type: type | tuple[type, ...]
) -> list:
    """Recursively collect statements of `statement_type`, including ones
    nested inside IF/EVALUATE/SEARCH branches, inline PERFORM bodies, and
    IO clause bodies -- reusing mock_surface.py's `_nested_statement_lists`
    rather than reimplementing nested-statement detection."""
    found = []
    for statement in statements:
        if isinstance(statement, statement_type):
            found.append(statement)
        for nested in _nested_statement_lists(statement):
            found.extend(_find_statements_of_type(nested, statement_type))
    return found


# The only `ExpansionStatistics.warnings` class that means the expanded text
# is NOT a faithful copy of the copybook bytes. The same channel also carries
# advisory lint heuristics ("may be missing terminating period", "contains
# only comments", "possible unbalanced quotes") that false-positive on valid
# copybooks (verified against tests/integration/fixtures/copybook_example) --
# refusing on those would reject working programs, so only the lossy-decode
# diagnostics gate.
_LOSSY_DECODE_MARKER = "Lossy decode of"


def check_expansion_warnings(expansion) -> list[RefusalReason]:
    """EXPANSION_WARNING for each lossy-decode warning recorded on a
    `CopybookExpansion.statistics` — a copybook whose bytes could not be
    decoded losslessly has U+FFFD replacement characters already substituted
    into the expanded source this run would splice and compile. Corrupted
    DATA DIVISION content compiles into wrong PIC/VALUE clauses, so refuse
    instead."""
    warnings = getattr(getattr(expansion, "statistics", None), "warnings", None)
    return [
        RefusalReason(
            code="EXPANSION_WARNING",
            message=(
                f"copybook expansion reported a warning -- the expanded "
                f"source is not a faithful copy of the copybook content: "
                f"{warning}"
            ),
        )
        for warning in warnings or []
        if _LOSSY_DECODE_MARKER in warning
    ]


def check_nested_exec(surface: MockSurface) -> list[RefusalReason]:
    """Whole-program: an EXEC SQL/CICS/DLI site that cannot be spliced
    safely refuses the file. Every EXEC block must be commented out for
    cobc to compile the program at all -- even unmocked, unreachable ones
    get a trap stub -- so spliceability is checked program-wide:

    - NESTED_EXEC: a nested EXEC with no validated splice span (or never
      annotated -- fail closed).
    - UNSPLICEABLE_EXEC: a top-level EXEC that shares a source line with
      sibling code (annotate_nested_sites stamped the layout problem);
      splicing its whole-line span would delete that sibling code."""
    reasons = [
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
    reasons.extend(
        RefusalReason(
            code="UNSPLICEABLE_EXEC",
            message=(
                f"EXEC {site.label} at line {site.line} (paragraph "
                f"'{site.paragraph_name}') {site.unspliceable_reason} -- "
                f"every EXEC block must be stubbed out for GnuCOBOL to "
                f"compile the program, and stubbing this one would comment "
                f"out the sibling code sharing its line(s)"
            ),
        )
        for site in surface.exec_sites()
        if not site.nested and site.unspliceable_reason
    )
    return reasons


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


def check_linkage_layout(program, lines: list[str]) -> list[RefusalReason]:
    """UNSUPPORTED_LINKAGE_LAYOUT: gates `mockymock.splicer.linkage`'s
    ENTRY/LINKAGE-SECTION neutralization transform (see
    docs/2026-07-08-ims-linkage-support-design.md). `[]` when
    `linkage.linkage_plan` finds nothing to do (no ENTRY statement, or an
    absent/empty LINKAGE SECTION -- an ordinary CALL-only program) or when
    the shape is safe to neutralize; otherwise one reason per guardrail that
    failed, fail-closed rather than risk commenting out the wrong line or
    silently breaking a shape this transform was never verified against.

    `lines` must be the same NORMALIZED free-form text
    (`normalize_fixed_format` output) the splicer edits -- `SourceLocation`
    lines are indexed into it, not the original file.
    """
    plan = linkage_plan(program)
    if plan is None:
        return []
    reasons: list[RefusalReason] = []

    data = program.get_division("DATA")
    section_names = list(data._sections.keys())
    if section_names and section_names[-1] != "LINKAGE":
        reasons.append(
            RefusalReason(
                code="UNSUPPORTED_LINKAGE_LAYOUT",
                message=(
                    "LINKAGE SECTION is not the last DATA DIVISION section "
                    f"(order found: {', '.join(section_names)}) -- "
                    "commenting out its header would silently absorb "
                    "whatever section follows it into WORKING-STORAGE too, "
                    "so this program's ENTRY/LINKAGE shape is not "
                    "neutralized"
                ),
            )
        )

    procedure = program.get_division("PROCEDURE")
    proc_idx = procedure.location.line - 1 if procedure is not None else -1
    proc_line = lines[proc_idx] if 0 <= proc_idx < len(lines) else ""
    if re.search(r"\bUSING\b", proc_line, re.IGNORECASE):
        reasons.append(
            RefusalReason(
                code="UNSUPPORTED_LINKAGE_LAYOUT",
                message=(
                    "the program's default entry declares its own USING "
                    f"clause ({proc_line.strip()!r}) -- this feature only "
                    "neutralizes a LINKAGE SECTION bound solely through a "
                    "separate named ENTRY statement; a default entry that "
                    "itself needs bound parameters is the general "
                    "CALL-driving case (Milestone B), not yet supported"
                ),
            )
        )

    header_idx = plan.header_line - 1
    header_text = lines[header_idx] if 0 <= header_idx < len(lines) else ""
    if not re.match(r"^\s*LINKAGE\s+SECTION\b", header_text, re.IGNORECASE):
        reasons.append(
            RefusalReason(
                code="UNSUPPORTED_LINKAGE_LAYOUT",
                message=(
                    "could not locate the LINKAGE SECTION header line by "
                    f"position (expected line {plan.header_line}, found "
                    f"{header_text!r}) -- refusing rather than commenting "
                    "out the wrong line"
                ),
            )
        )

    return reasons


def check_test_case(
    surface: MockSurface,
    program,
    case: MockTestCase,
) -> list[RefusalReason]:
    reasons: list[RefusalReason] = []
    reachable, thru_reasons = _reachable_paragraphs(
        program, case.perform_target, case.perform_thru
    )

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

    reasons.extend(thru_reasons)

    matched_directives: set[int] = set()
    for site in surface.sites_in(reachable):
        if site.category is None:
            if site.label == "CANCEL":
                # Covered when this case mocks CALL (static: exact key;
                # dynamic: uppercased identifier) for every name the CANCEL
                # carries: the mocked CALL never loads a real module, so
                # the CANCEL -- left in place, never spliced -- is a
                # guaranteed GnuCOBOL no-op. Anything else fails closed.
                covering: list[MockDirective] = []
                uncovered: list[str] = []
                for key in site.keys:
                    matches = [
                        d
                        for d in case.mocks
                        if (d.category is MockCategory.CALL and d.key == key)
                        or (
                            d.category is MockCategory.DYNCALL
                            and d.key.upper() == key.upper()
                        )
                    ]
                    if matches:
                        covering.extend(matches)
                    else:
                        uncovered.append(key)
                if site.keys and not uncovered:
                    for directive in covering:
                        matched_directives.add(id(directive))
                else:
                    reasons.append(
                        RefusalReason(
                            code="UNMOCKED_CANCEL",
                            message=(
                                f"CANCEL at line {site.line} (paragraph "
                                f"'{site.paragraph_name}'"
                                + (
                                    f", names {'/'.join(site.keys)}"
                                    if site.keys
                                    else ", no program name captured"
                                )
                                + f") is reachable from "
                                f"'{case.perform_target}' but this test case "
                                f"does not mock a matching CALL -- CANCEL is "
                                f"only a safe no-op when the CALLs for the "
                                f"same program are mocked (the module is "
                                f"then never loaded)"
                            ),
                        )
                    )
            elif site.label == "dynamic CALL":
                reasons.append(
                    RefusalReason(
                        code="DYNAMIC_CALL",
                        message=(
                            f"paragraph '{site.paragraph_name}' (line {site.line}) "
                            f"contains a dynamic CALL whose target identifier "
                            f"could not be determined -- dynamic CALLs are "
                            f"mockable only through their identifier "
                            f"(MOCK CALL <identifier>)"
                        ),
                    )
                )
            elif site.label in _TERMINATOR_LABELS:
                # Handled entirely separately by check_terminator_layout
                # (Task 3, docs/2026-07-08-goback-stop-run-support-design.md)
                # -- not refused here, and deliberately not folded into
                # this function, so a safely-neutralizable terminator
                # doesn't need every OTHER test case in the suite to also
                # satisfy check_test_case's unrelated matching rules.
                pass
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
        elif not site.nested and site.unspliceable_reason:
            # Top-level splices comment out whole source lines: a boundary
            # statement that shares a line with sibling code (a one-line
            # paragraph `P1. CALL "X".`, code before it on the line, or a
            # second statement after it) would silently delete that sibling
            # code. annotate_nested_sites stamps the layout problem.
            reasons.append(
                RefusalReason(
                    code="UNSUPPORTED_MOCK_TARGET_LAYOUT",
                    message=(
                        f"MOCK {matches[0].describe()} matches a top-level "
                        f"statement at line {site.line} (paragraph "
                        f"'{site.paragraph_name}') that {site.unspliceable_reason}"
                        f" -- splicing it would comment out the sibling code "
                        f"sharing its line(s); put the statement on its own "
                        f"line(s)"
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
                        f"VERIFY {verification.category.keyword} "
                        f"{verification.key!r} has no matching MOCK directive "
                        f"in this test case -- its tally counter would be "
                        f"undeclared or stale"
                    ),
                )
            )

    return reasons


def _find_flow_statements(statements: list) -> list:
    """Recursively collect every PerformStatement and GoStatement in
    `statements`, including ones nested inside IF/EVALUATE/SEARCH branches,
    inline PERFORM bodies, and IO clause bodies (AT END, INVALID KEY, etc.)
    -- reusing mock_surface.py's `_nested_statement_lists` rather than
    reimplementing nested-statement detection.
    """
    return _find_statements_of_type(statements, (PerformStatement, GoStatement))


def _source_ordered_paragraphs(procedure) -> list | None:
    """All paragraphs sorted by location.line, or None when the sorted
    line sequence is not strictly increasing -- the runtime check behind
    the source-order guarantee THRU range expansion depends on. Verified
    to hold for plain and sectioned programs; a parser regression trips
    the None path and every expansion refuses fail-closed."""
    paragraphs = sorted(_all_paragraphs(procedure), key=lambda p: p.location.line)
    lines = [p.location.line for p in paragraphs]
    if any(later <= earlier for earlier, later in zip(lines, lines[1:], strict=False)):
        return None
    return paragraphs


def _expand_thru_range(
    ordered,
    start: str,
    thru: str,
    origin: str,
    missing_code: str = "UNSUPPORTED_PERFORM_THRU",
) -> tuple[list[str], RefusalReason | None]:
    """Names of every paragraph in the source-order slice [start..thru]
    inclusive (phantom '.' members ride along; they are empty artifacts),
    or ([], reason) for a degenerate range: unverifiable order, missing
    endpoint, ambiguous endpoint name, or thru preceding start. Never
    best-effort -- cobolparser's flow analyzer degrades to [start, end]
    endpoints when a range is malformed, but the refusal gate must not."""
    if ordered is None:
        return [], RefusalReason(
            code="UNSUPPORTED_PERFORM_THRU",
            message=(
                f"{origin}: PERFORM {start} THRU {thru} cannot be "
                f"range-expanded -- paragraph source order could not be "
                f"verified (location lines are not strictly increasing)"
            ),
        )
    names = [p.paragraph_name for p in ordered]
    for endpoint in (start, thru):
        count = names.count(endpoint)
        if count == 0:
            return [], RefusalReason(
                code=missing_code,
                message=(
                    f"{origin}: PERFORM {start} THRU {thru} endpoint "
                    f"'{endpoint}' not found in PROCEDURE DIVISION"
                ),
            )
        if count > 1:
            return [], RefusalReason(
                code="UNSUPPORTED_PERFORM_THRU",
                message=(
                    f"{origin}: PERFORM {start} THRU {thru} endpoint "
                    f"'{endpoint}' names {count} paragraphs -- the range "
                    f"is ambiguous"
                ),
            )
    i, j = names.index(start), names.index(thru)
    if j < i:
        return [], RefusalReason(
            code="UNSUPPORTED_PERFORM_THRU",
            message=(
                f"{origin}: PERFORM {start} THRU {thru} is a backwards "
                f"range ('{thru}' precedes '{start}' in source order)"
            ),
        )
    return names[i : j + 1], None


def _reachable_paragraphs(
    program, start: str, thru: str | None = None
) -> tuple[set[str], list[RefusalReason]]:
    """Return (reachable paragraph/section names, flow refusals), computed
    in a single BFS pass over PerformStatement and GoStatement edges.

    A PERFORM ... THRU pushes every paragraph of its source-order range
    (fall-through executes them all); `thru` seeds the BFS with the test
    case's own driver-side range, whose missing endpoints are the .cut
    author's typo and use UNKNOWN_PARAGRAPH. A PERFORM or GO TO naming a
    SECTION pushes every paragraph of that section (a performed section
    executes all of them by fall-through). Any in-program PERFORM/GO TO
    target resolving to neither a paragraph nor a section refuses with
    UNRESOLVED_FLOW_TARGET -- fail closed, never a silent skip: an edge
    the model cannot resolve means the reachable set cannot be trusted.
    (The seed `start` is exempt: check_test_case turns an unresolvable
    driver-side target into UNKNOWN_PARAGRAPH.)"""
    procedure = program.get_division("PROCEDURE")
    if procedure is None:
        return set(), []
    ordered = _source_ordered_paragraphs(procedure)
    by_name: dict[str, CobolParagraph] = {}
    for paragraph in _all_paragraphs(procedure):
        by_name.setdefault(paragraph.paragraph_name, paragraph)
    section_members: dict[str, list[str]] = {}
    for section_name, section in getattr(procedure, "_sections", {}).items():
        if not section_name:
            continue
        section_members.setdefault(
            section_name, [p.paragraph_name for p in section.paragraphs]
        )

    reasons: list[RefusalReason] = []
    stack = [start]
    if thru is not None and start in by_name:
        members, problem = _expand_thru_range(
            ordered,
            start,
            thru,
            "test case PERFORM",
            missing_code="UNKNOWN_PARAGRAPH",
        )
        if problem is not None:
            reasons.append(problem)
        stack.extend(members)

    def push_target(target: str, origin: str, verb: str) -> None:
        if target in by_name or target in section_members:
            stack.append(target)
        else:
            reasons.append(
                RefusalReason(
                    code="UNRESOLVED_FLOW_TARGET",
                    message=(
                        f"paragraph '{origin}': {verb} target '{target}' is "
                        f"neither a paragraph nor a section of the PROCEDURE "
                        f"DIVISION -- the reachability analysis cannot "
                        f"resolve this control-flow edge, so the reachable "
                        f"set cannot be trusted"
                    ),
                )
            )

    seen: set[str] = set()
    while stack:
        name = stack.pop()
        if name in seen:
            continue
        if name not in by_name:
            if name in section_members:
                # A performed/jumped-to section executes every one of its
                # paragraphs by fall-through.
                seen.add(name)
                stack.extend(section_members[name])
            # else: only the driver-side seed can be unresolved here (every
            # in-program edge was resolvability-checked before pushing);
            # check_test_case reports it as UNKNOWN_PARAGRAPH.
            continue
        seen.add(name)
        for statement in _find_flow_statements(by_name[name].statements):
            if isinstance(statement, GoStatement):
                targets = list(statement.target_paragraphs)
                if not targets and statement.target_paragraph:
                    targets = [statement.target_paragraph]
                if not targets:
                    reasons.append(
                        RefusalReason(
                            code="UNRESOLVED_FLOW_TARGET",
                            message=(
                                f"paragraph '{name}' (line "
                                f"{statement.location.line}) contains a GO TO "
                                f"whose target(s) the parser did not capture "
                                f"-- fail closed"
                            ),
                        )
                    )
                for target in targets:
                    push_target(target, name, "GO TO")
                continue
            if statement.target_paragraph:
                push_target(statement.target_paragraph, name, "PERFORM")
                if statement.thru_paragraph:
                    members, problem = _expand_thru_range(
                        ordered,
                        statement.target_paragraph,
                        statement.thru_paragraph,
                        f"paragraph '{name}'",
                    )
                    if problem is not None:
                        reasons.append(problem)
                    stack.extend(members)
    return seen, reasons


def _go_to_targets(program) -> set[str]:
    """Every paragraph/section name that is EVER a GO TO target anywhere
    in the whole program, regardless of reachability from any one test
    case -- a categorical, whole-program exclusion list.

    A paragraph that could ever be entered via GO TO cannot safely use
    EXIT PARAGRAPH/EXIT SECTION for early-exit propagation: verified
    empirically (docs/2026-07-08-goback-stop-run-support-design.md, spike
    #4) that EXIT PARAGRAPH silently fails to return to the correct
    caller when the paragraph it's issued from was entered via GO TO
    rather than PERFORM -- execution just stops, no crash, no return,
    the caller's checks never run."""
    procedure = program.get_division("PROCEDURE")
    if procedure is None:
        return set()
    targets: set[str] = set()
    for paragraph in _all_paragraphs(procedure):
        for statement in _find_statements_of_type(paragraph.statements, GoStatement):
            targets.update(statement.target_paragraphs)
            if statement.target_paragraph:
                targets.add(statement.target_paragraph)
    return targets


def _safe_section_entry_points(program) -> dict[str, str]:
    """Maps each SECTION name whose first paragraph is safely enterable
    ONLY via `PERFORM <section-name>` to that first paragraph's name --
    the one shape docs/2026-07-08-goback-stop-run-support-design.md's
    spike #5 proved `EXIT SECTION` correctly neutralizes (see
    docs/2026-07-10-section-scoped-terminator-support-design.md).

    Safe means: the section has at least one paragraph; neither the
    section's own name nor its first paragraph's name is ever a GO TO
    target anywhere in the program (`_go_to_targets`); and the first
    paragraph's name is never itself named as a PERFORM target -- plain
    or THRU, conditional or not, top-level or nested -- anywhere in the
    whole program. That last check is deliberately maximally inclusive:
    any second way to enter that paragraph is a standing risk regardless
    of whether any one test's execution happens to take it, the same
    reasoning already applied to the GO TO exclusion above.

    A section failing any of these is simply absent from the returned
    map -- callers must treat that identically to any other unresolvable
    PERFORM target (the existing dead-end/refusal behavior)."""
    procedure = program.get_division("PROCEDURE")
    if procedure is None:
        return {}

    go_to_targets = _go_to_targets(program)
    performed_names: set[str] = set()
    for paragraph in _all_paragraphs(procedure):
        for statement in _find_statements_of_type(
            paragraph.statements, PerformStatement
        ):
            if statement.target_paragraph:
                performed_names.add(statement.target_paragraph)
            if statement.thru_paragraph:
                performed_names.add(statement.thru_paragraph)

    safe_entries: dict[str, str] = {}
    for section_name, section in procedure._sections.items():
        if not section.paragraphs:
            continue
        first_name = section.paragraphs[0].paragraph_name
        if section_name in go_to_targets or first_name in go_to_targets:
            continue
        if first_name in performed_names:
            continue
        safe_entries[section_name] = first_name
    return safe_entries


def _plain_perform_edges_from(
    program, start: str, safe_section_entries: dict[str, str] | None = None
) -> tuple[set[str], list]:
    """BFS from `start` following ONLY plain (non-THRU), unconditional,
    single-shot, top-level PERFORM statements -- i.e. PerformStatement
    nodes that are direct members of a paragraph's own `.statements` list
    (not nested inside IF/EVALUATE), with `thru_paragraph is None` and
    `perform_type == "SIMPLE"`.

    A PERFORM ... UNTIL/VARYING/TIMES (perform_type != "SIMPLE") is
    deliberately NOT followed and NOT added to the edge set, even though
    it also carries a `target_paragraph` with `thru_paragraph is None`:
    the early-exit mechanism sets a flag and does `EXIT PARAGRAPH`, which
    only ends the CURRENT iteration of the looped paragraph -- control
    returns to the loop construct, which re-checks its own unrelated
    UNTIL/VARYING/TIMES condition and may iterate again. A terminator
    reached from inside a loop's target would silently run extra
    unwanted iterations instead of stopping, which was proven empirically
    (a synthetic STOP RUN placed inside a looped paragraph kept iterating
    past it). Excluding the edge means such a terminator's paragraph never
    enters `seen`, so `find_terminator_plans` naturally refuses it via the
    existing "reachable but not via a plain chain" check -- no new
    refusal branch needed.

    `safe_section_entries` (from `_safe_section_entry_points`, or omitted
    for callers that don't care about SECTIONs -- e.g. this module's own
    dead-end regression test) resolves a PERFORM target that names one of
    its KEYS (a SECTION whose first paragraph is provably safely
    enterable only that way) to that first paragraph's name, continuing
    the BFS from that paragraph's own statements exactly like any other
    paragraph -- see
    docs/2026-07-10-section-scoped-terminator-support-design.md. This is
    the ONLY SECTION shape this restricted BFS ever resolves: a target
    name that is a SECTION but not a safe entry (or any other
    unresolvable name) still dead-ends exactly as before, its raw,
    unresolved name landing in `seen`.

    SECTION members that aren't a safe entry's first paragraph are still
    excluded entirely, same as before: this only looks up names in
    `procedure.paragraphs` (top-level paragraphs) and, when
    `safe_section_entries` resolves one, the specific first-paragraph
    names it names -- never any other section member -- so a chain that
    would need to pass through one of those (fall-through, or a direct
    PERFORM of a non-first section member) still naturally refuses via
    the existing "reachable but not via a plain chain" check."""
    procedure = program.get_division("PROCEDURE")
    if procedure is None:
        return set(), []
    safe_section_entries = safe_section_entries or {}
    by_name = {p.paragraph_name: p for p in procedure.paragraphs}
    section_member_by_name = {
        paragraph.paragraph_name: paragraph
        for section in procedure._sections.values()
        for paragraph in section.paragraphs
    }

    def resolve(name):
        if name in by_name:
            return name, by_name[name]
        first_name = safe_section_entries.get(name)
        if first_name is not None:
            return first_name, section_member_by_name.get(first_name)
        return name, None

    start_name, start_paragraph = resolve(start)
    seen = {start_name}
    resolved = {}
    stack = []
    if start_paragraph is not None:
        resolved[start_name] = start_paragraph
        stack.append(start_name)
    edges: list = []
    while stack:
        name = stack.pop()
        paragraph = resolved.get(name)
        if paragraph is None:
            continue
        for statement in paragraph.statements:
            if (
                isinstance(statement, PerformStatement)
                and statement.thru_paragraph is None
                and statement.target_paragraph
                and statement.perform_type == "SIMPLE"
            ):
                edges.append(statement)
                target_name, target_paragraph = resolve(statement.target_paragraph)
                if target_name not in seen:
                    seen.add(target_name)
                    if target_paragraph is not None:
                        resolved[target_name] = target_paragraph
                        stack.append(target_name)
    return seen, edges


def find_terminator_plans(
    surface: MockSurface,
    program,
    suite: MockTestSuite,
    scope_map,
    lines: list[str],
) -> tuple[list[TerminatorPlan], list[RefusalReason]]:
    """For every STOP RUN(RUN-form)/GOBACK reachable from at least one test
    case, decide whether it is safely neutralizable and return either a
    TerminatorPlan or an UNSUPPORTED_TERMINATOR_LAYOUT RefusalReason --
    never both for the same physical statement. Sites unreachable from
    every test case are omitted entirely (left untouched, like any other
    unmocked boundary).

    Safe means: the terminator's enclosing paragraph is a top-level
    paragraph (not a SECTION member) -- or is the first paragraph of a
    SECTION whose only entry point, whole-program, is `PERFORM
    <section-name>` (`_safe_section_entry_points`; see
    docs/2026-07-10-section-scoped-terminator-support-design.md) -- is
    reachable from the test's own
    perform_target via `_plain_perform_edges_from` (a chain of nothing but
    plain, unconditional, top-level PERFORM statements), and no paragraph
    anywhere on that whole restricted-reachable chain -- not just the
    terminator's own paragraph, but every paragraph the case's
    over-inclusive chain_performs instrumentation would touch, including
    the perform_target itself -- is ever a GO TO target anywhere in the
    program, or is missing from `top_level_names` (a dead-end BFS target
    that turned out to be a SECTION name rather than a real paragraph, e.g.
    `PERFORM some-section`). The terminator's own statement must also own
    its line/have a validated span (`site.span`/`site.unspliceable_reason`,
    populated by a broadened `annotate_nested_sites` call the caller must
    have already made), and every intermediate PERFORM on the case's
    restricted-reachable chain must also own its own line
    (`statement_top_level_problem`, checked once per case since the same
    chain_performs set is a candidate for every terminator that case
    reaches -- the design doc describes a per-terminator backward walk,
    but this implementation computes one forward, whole-case reachable
    set instead and reuses it for every terminator that case finds,
    which is why the GO-TO/SECTION checks below are also computed over
    the whole chain rather than just the terminator's own paragraph: any
    terminator sharing this case's chain_performs would be instrumented
    with the same hazardous paragraph regardless of whether it sits on
    that specific terminator's own ancestor path -- noted by the
    2026-07-09 final branch review: this over-inclusiveness is fail-SAFE
    (it can only ever cause an extra, unnecessary refusal of a terminator
    that would actually have been fine, never miss an unsafe one), but it
    is a real usability cliff on large paragraphs -- a GO-TO target or
    SECTION member anywhere in the case's reachable set refuses every
    terminator that case finds, even ones with no path through the
    hazardous paragraph at all. If this bites in practice, narrowing to
    the terminator's actual ancestor path is the fix, not loosening the
    check). Once ANY test case
    finds a given terminator unsafe, it is
    refused permanently -- fail-closed, regardless of what other test
    cases' paths say. `scope_map`/`lines` must be the same
    `collect_scope_map(program, lines)` result and normalized lines the
    caller already computed for `annotate_nested_sites`."""
    procedure = program.get_division("PROCEDURE")
    if procedure is None:
        return [], []

    top_level_names = {p.paragraph_name for p in procedure.paragraphs}
    go_to_targets = _go_to_targets(program)
    safe_section_entries = _safe_section_entry_points(program)
    safe_section_first_names = set(safe_section_entries.values())
    terminator_sites = {
        id(s.statement): s
        for s in surface.boundary_sites
        if s.category is None and s.label in _TERMINATOR_LABELS
    }

    plans_by_statement: dict[int, TerminatorPlan] = {}
    reasons: list[RefusalReason] = []
    refused_statement_ids: set[int] = set()

    for case in suite.test_cases:
        reachable, _ = _reachable_paragraphs(
            program, case.perform_target, case.perform_thru
        )
        safe_names, chain_performs = _plain_perform_edges_from(
            program, case.perform_target, safe_section_entries
        )
        chain_section_names = safe_names - (top_level_names | safe_section_first_names)
        chain_go_to_names = safe_names & go_to_targets

        chain_problem: str | None = None
        for perform in chain_performs:
            line_problem = statement_top_level_problem(perform, scope_map, lines)
            if line_problem is not None:
                chain_problem = (
                    f"an intermediate PERFORM {perform.target_paragraph} at "
                    f"line {perform.location.line} {line_problem} -- "
                    f"inserting the early-exit check after it would corrupt "
                    f"sibling code sharing its line"
                )
                break

        qualified_keys: list[int] = []

        for site in surface.sites_in(reachable):
            key = id(site.statement)
            if key not in terminator_sites or key in refused_statement_ids:
                continue

            paragraph_name = site.paragraph_name
            problem = None
            if paragraph_name not in top_level_names and (
                paragraph_name not in safe_section_first_names
                # A safe_section_first_names entry is only genuinely safe
                # when reached via PERFORM <section-name> (an intermediate
                # chain edge, or perform_target naming the section itself).
                # _safe_section_entry_points already excludes any paragraph
                # that is a PERFORM target anywhere -- so the only other way
                # to land here is the test's own perform_target naming this
                # paragraph directly, bypassing the section name entirely.
                # That's shape 3 (docs/2026-07-10-section-scoped-terminator-
                # support-design.md), still out of scope and unverified.
                or paragraph_name == case.perform_target
            ):
                problem = (
                    "is inside a paragraph that belongs to a SECTION -- "
                    "SECTION-scoped terminators are not yet supported"
                )
            elif paragraph_name in go_to_targets:
                problem = (
                    "is reachable via GO TO somewhere in this program -- "
                    "the early-exit propagation mechanism (EXIT PARAGRAPH) "
                    "only works correctly when a paragraph is entered "
                    "exclusively via PERFORM"
                )
            elif paragraph_name not in safe_names:
                problem = (
                    f"is reachable from '{case.perform_target}' but not via "
                    f"a chain of plain, unconditional, top-level PERFORM "
                    f"statements -- this is the only shape this feature can "
                    f"safely neutralize today"
                )
            elif chain_section_names:
                bad_name = sorted(chain_section_names)[0]
                problem = (
                    f"is only reachable through this test's own early-exit "
                    f"propagation chain by way of '{bad_name}', which is "
                    f"not a top-level paragraph (it belongs to a SECTION) "
                    f"-- SECTION-scoped chains are not yet supported"
                )
            elif chain_go_to_names:
                # paragraph_name can't be a member here: the preceding elif
                # already excluded it from go_to_targets, and chain_go_to_names
                # is a subset of go_to_targets.
                bad_name = sorted(chain_go_to_names)[0]
                problem = (
                    f"is only reachable through this test's own early-exit "
                    f"propagation chain by way of '{bad_name}', which is "
                    f"reachable via GO TO somewhere in this program -- the "
                    f"early-exit propagation mechanism (EXIT PARAGRAPH) "
                    f"only works correctly when a paragraph is entered "
                    f"exclusively via PERFORM"
                )
            elif site.nested and site.span is None:
                problem = (
                    f"is nested inside a conditional/loop body and cannot "
                    f"be safely spliced: "
                    f"{site.unspliceable_reason or _UNANNOTATED}"
                )
            elif not site.nested and site.unspliceable_reason:
                problem = (
                    f"{site.unspliceable_reason} -- splicing it would "
                    f"corrupt sibling code sharing its line(s)"
                )
            elif chain_problem is not None:
                problem = chain_problem

            if problem is not None:
                reasons.append(
                    RefusalReason(
                        code="UNSUPPORTED_TERMINATOR_LAYOUT",
                        message=(
                            f"{site.label} at line {site.line} (paragraph "
                            f"'{paragraph_name}') {problem}"
                        ),
                    )
                )
                refused_statement_ids.add(key)
                plans_by_statement.pop(key, None)
                continue

            if key not in plans_by_statement:
                exit_kind = (
                    "SECTION"
                    if paragraph_name in safe_section_first_names
                    else "PARAGRAPH"
                )
                plans_by_statement[key] = TerminatorPlan(
                    site=terminator_sites[key], exit_kind=exit_kind
                )
            qualified_keys.append(key)

        for key in qualified_keys:
            plan = plans_by_statement[key]
            existing_ids = {id(p) for p in plan.chain_performs}
            for perform in chain_performs:
                if id(perform) not in existing_ids:
                    plan.chain_performs.append(perform)
                    existing_ids.add(id(perform))

    return list(plans_by_statement.values()), reasons


def check_terminator_layout(
    surface: MockSurface,
    program,
    suite: MockTestSuite,
    scope_map,
    lines: list[str],
) -> list[RefusalReason]:
    """Thin wrapper over find_terminator_plans for the CLI's refusal-gate
    loop, which only needs the refusal reasons, not the plans themselves
    (the plans are recomputed again right before splicing -- see the CLI
    wiring task -- matching this codebase's existing pattern of computing
    a cheap, pure "plan" twice rather than threading it through every
    caller, e.g. analysis.linkage.linkage_plan)."""
    return find_terminator_plans(surface, program, suite, scope_map, lines)[1]
