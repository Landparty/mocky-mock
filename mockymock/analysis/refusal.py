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
  relies on falling through *past* its target paragraph is NOT a flow edge
  the reachability BFS itself follows -- but the hazard it creates for
  `find_terminator_plans` IS separately guarded: `_go_to_fallthrough_targets`
  walks source order forward from every GO TO target, via `_falls_through`,
  to find every paragraph reachable only by falling off the end of one --
  the same EXIT PARAGRAPH hazard spike #4 found for a direct GO TO target,
  since a paragraph reached this way was never PERFORMed either. Noted by
  the 2026-07-09 final branch review as an unmodeled, undefended gap
  (pre-neutralization it was a clean, loud crash; once a DIFFERENT case had
  neutralized the shared physical terminator via its own safe plain chain,
  a case reaching it through this path would instead hit `EXIT PARAGRAPH`
  from a paragraph entered via `GO TO`, which spike #4 found "just stops,
  no crash, no return" -- a subtler failure than the pre-branch behavior).
  Now refused (`UNSUPPORTED_TERMINATOR_LAYOUT`) instead of silently risked
  -- see docs/2026-07-10-goto-fallthrough-terminator-hazard-design.md.)
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

Both PARSE_WARNING and UNRESOLVED_COPYBOOK were originally unconditional
whole-program refusals. They are now the last two with a narrower, scoped
variant (check_whole_program_scoped / check_unresolved_copybooks_scoped,
used by cli.checks.run_static_checks): a warning or unresolved COPY whose
evidence is provably confined to ONE PROCEDURE DIVISION paragraph's own
body (_paragraph_owning_line -- strictly between that paragraph's header
line and the next paragraph/section header, never on a header line, never
in a multi-program unit, never attributable to a phantom "." paragraph,
and never when _has_unaccounted_label finds a line shaped like an
unrecognized paragraph/SECTION header inside that body -- a cross-check
against mockymock's own re-lexing of the source, independent of trusting
cobolparser's error-recovery internals to never have swallowed a real
paragraph boundary while resynchronizing after the very content that
triggered the warning: all of those stay whole-program, fail closed) is
held back as a ParagraphScopedRefusal and refused only when some SELECTED
test case can
execute that paragraph. "Can execute" is union_executed_paragraphs: the
union over every selected case of the same reachability BFS the per-case
gates trust, closed over the GO TO fall-through hazard (a paragraph
entered by falling off the end of a GO TO target executes without any
PERFORM/GO TO edge naming it -- the same unmodeled shape
_go_to_fallthrough_targets guards terminators against), and None --
meaning "treat every paragraph as executable" -- whenever any case's BFS
reports any flow refusal (an untrusted reachable set must not waive
anything). Why an unexecuted paragraph's incomplete AST is harmless: the
dropped/missing content still sits verbatim in the source GnuCOBOL
compiles (mockymock splices raw text, not the AST), no splice is ever
derived from statements inside it, edges FROM it cannot fire at runtime
because the paragraph never runs, and edges TO content the parser lost
are unresolvable names that refuse (UNRESOLVED_FLOW_TARGET /
UNKNOWN_PARAGRAPH) the moment a reachable paragraph carries one. A waived
unresolved COPY additionally has its statement commented out of the
spliced lines (its verified own-line span rides on the
ParagraphScopedRefusal) so cobc never sees a COPY it cannot resolve; only
the single-line `COPY MEMBER.` layout owning its whole line qualifies
(_copy_own_line_span), so sibling code on the line, a second statement
after the terminator, and multi-line COPY ... REPLACING all stay
whole-program. generate/fixtures have no test cases to scope
by, so the plain check_whole_program/check_unresolved_copybooks entry
points still refuse everything, unchanged.

check_unresolved_copybooks (UNRESOLVED_COPYBOOK) is otherwise a
whole-program check, not a per-TESTCASE one: an unresolved COPY outside
the one provable paragraph-local shape above affects the whole program
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
from cobolparser.models.statements.control import (
    GoStatement,
    PerformStatement,
    StopStatement,
)
from cobolparser.models.statements.misc import (
    AlterStatement,
    ExitStatement,
    GobackStatement,
)
from cobolparser.preprocess import normalize_fixed_format

from mockymock.analysis.linkage import linkage_plan
from mockymock.analysis.mock_surface import (
    _BOUNDARY_STATEMENT_TYPES,
    _TERMINATOR_LABELS,
    BoundarySite,
    MockSurface,
    _all_paragraphs,
    _nested_statement_lists,
    normalize_exec_text,
)
from mockymock.dsl.model import (
    EXEC_CATEGORIES,
    FLOW_CATEGORIES,
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
class ParagraphScopedRefusal:
    """A refusal whose evidence is provably confined to one PROCEDURE
    DIVISION paragraph's own body (see the module docstring): held back by
    the *_scoped check variants and resolved by resolve_scoped_refusals
    against union_executed_paragraphs -- `reason` refuses when some
    selected test case can execute `paragraph_name`; `waiver_note` is the
    transparency line printed instead when none can. `blank_span` is only
    set for an unresolved COPY statement: the 1-based inclusive
    normalized-line span, verified to own its lines outright, that
    cli.checks.run_static_checks comments out of the spliced source when
    the refusal is waived (the raw COPY text would otherwise still reach
    cobc, which cannot compile an unresolvable COPY)."""

    paragraph_name: str
    reason: RefusalReason
    waiver_note: str
    blank_span: tuple[int, int] | None = None


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


# The line reference cobolparser embeds in dropped-content warning text.
# Deliberately strict: a warning that carries no recognizable line number
# cannot be located, so it stays a whole-program refusal (fail closed).
# Lines named this way index the NORMALIZED free-form text, the same
# space as every SourceLocation mockymock consumes.
_WARNING_LINE_RE = re.compile(r"\bline\s+(\d+)\b", re.IGNORECASE)


# A line that LOOKS like a paragraph-name or SECTION header on its own --
# used only as a NEGATIVE safety check, never a positive detector: cheap,
# deliberately broad free-form-COBOL shape (a bare identifier, optionally
# "... SECTION", terminated by a period, alone on its line). If a line
# shaped like this turns up strictly INSIDE what the AST claims is one
# paragraph's body -- between its header and the next AST-recorded
# boundary -- that is suspicious: either it's an ordinary reserved-word
# one-liner (EXIT./CONTINUE.) or EXEC-block noise (END-EXEC.), or it is
# exactly the failure mode this guards against -- cobolparser's error-
# recovery swallowed what should have been a separate paragraph header
# while resynchronizing after dropped content, silently merging that
# paragraph's body into this one and erasing it from the AST's own
# paragraph list. mockymock has no visibility into cobolparser's recovery
# internals to rule that out directly, so instead of trusting the
# warning's line number on faith, this cross-checks it against source
# text mockymock already controls. False positives (the common,
# harmless EXIT./END-EXEC. case) only cost a classification -- the
# warning falls back to whole-program, today's behavior -- never an
# unsound one.
_CANDIDATE_LABEL_RE = re.compile(
    r"^\s*[A-Z0-9][A-Z0-9-]*(?:\s+SECTION)?\s*\.\s*$", re.IGNORECASE
)


def _has_unaccounted_label(normalized_lines: list[str], start: int, end: int) -> bool:
    """True if any line in [start, end] (1-based, inclusive; a reversed or
    out-of-range span is simply empty) of `normalized_lines` matches
    `_CANDIDATE_LABEL_RE`. Only ever called with a span strictly between
    two consecutive AST-recorded PROCEDURE DIVISION boundaries -- see
    `_CANDIDATE_LABEL_RE`."""
    for line_no in range(max(start, 1), min(end, len(normalized_lines)) + 1):
        if _CANDIDATE_LABEL_RE.match(normalized_lines[line_no - 1]):
            return True
    return False


def _paragraph_body_span(program, line: int) -> tuple[str, int, int | None] | None:
    """(owner_name, owner_header_line, next_boundary_line) for the
    PROCEDURE DIVISION paragraph whose own body strictly contains
    normalized-text line `line`, or None when that cannot be proven --
    fail closed. None covers: a multi-program compilation unit (warning
    lines could index a contained program the AST doesn't model here), no
    PROCEDURE DIVISION, unverifiable paragraph source order, any line at
    or before the first paragraph header (DATA DIVISION content is
    program-global), a line ON a paragraph/section header line, and any
    line whose nearest preceding header is a SECTION header or a phantom
    '.'/'' paragraph rather than a real paragraph (content there has no
    single owning paragraph body). `next_boundary_line` is None when no
    further boundary follows -- the owner is the program's last paragraph,
    its body runs to end of file.

    "Strictly contains" means: the last header line before `line`
    (paragraph headers, named-section headers, and phantom-paragraph
    anchor lines all count as headers) is a real paragraph's, and `line`
    is strictly greater than it. Ties on a shared line resolve to the
    non-owner, so a header-sharing layout never classifies."""
    if getattr(program, "contained_programs", None):
        return None
    procedure = program.get_division("PROCEDURE")
    if procedure is None:
        return None
    ordered = _source_ordered_paragraphs(procedure)
    if not ordered:
        return None
    # (line, tie_rank, owner): owner None marks a boundary that owns no
    # body (section header, phantom paragraph). tie_rank 1 > 0 so a
    # non-owner sharing a line with a paragraph header wins the tie and
    # the classification fails closed.
    boundaries: list[tuple[int, int, str | None]] = []
    for paragraph in ordered:
        name = paragraph.paragraph_name
        if name.strip("."):
            boundaries.append((paragraph.location.line, 0, name))
        else:
            boundaries.append((paragraph.location.line, 1, None))
    for section_name, section in getattr(procedure, "_sections", {}).items():
        if (section_name or "").strip("."):
            boundaries.append((section.location.line, 1, None))
    boundaries.sort(key=lambda boundary: boundary[:2])
    if any(start == line for start, _, _ in boundaries):
        # ON a header line (a one-line `P. <content>` layout, a section
        # header, a phantom anchor): never attributable to a body.
        return None
    owner_idx: int | None = None
    for i, (start, _, _) in enumerate(boundaries):
        if start < line:
            owner_idx = i
        else:
            break
    if owner_idx is None or boundaries[owner_idx][2] is None:
        return None
    owner_start = boundaries[owner_idx][0]
    owner_name = boundaries[owner_idx][2]
    assert owner_name is not None  # just checked above
    next_start = (
        boundaries[owner_idx + 1][0] if owner_idx + 1 < len(boundaries) else None
    )
    return owner_name, owner_start, next_start


def _paragraph_owning_line(
    program, line: int, normalized_lines: list[str] | None = None
) -> str | None:
    """`_paragraph_body_span`'s owner name, or None -- see that function's
    docstring for the base attribution rules.

    When `normalized_lines` is given, ownership additionally requires
    `_has_unaccounted_label` to find nothing suspicious in the candidate
    owner's own body (see `_CANDIDATE_LABEL_RE`'s docstring for why):
    classification fails closed rather than trust a paragraph boundary
    that might not be where it looks. Every *_scoped call site must pass
    it; omitting it is only for callers that genuinely have no source
    text yet."""
    span = _paragraph_body_span(program, line)
    if span is None:
        return None
    owner, start, next_start = span
    if normalized_lines is not None:
        end = next_start - 1 if next_start is not None else len(normalized_lines)
        if _has_unaccounted_label(normalized_lines, start + 1, end):
            return None
    return owner


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
    modeled by the reachability BFS.

    This entry point refuses every warning unconditionally -- it serves
    the callers with no test cases to scope by (generate/fixtures).
    run_static_checks uses check_whole_program_scoped instead, which holds
    provably paragraph-local warnings back for the reachability-union gate
    (see the module docstring)."""
    reasons, scoped = _whole_program_reasons(
        parse_result, classify=False, raw_source=None
    )
    assert not scoped  # classify=False never holds a warning back
    return reasons


def check_whole_program_scoped(
    parse_result, raw_source: str
) -> tuple[list[RefusalReason], list[ParagraphScopedRefusal]]:
    """check_whole_program, except each PARSE_WARNING whose text carries a
    line number that `_paragraph_owning_line` proves to sit inside exactly
    one PROCEDURE DIVISION paragraph's own body -- AND that survives
    `_paragraph_owning_line`'s independent label-scan safety net over
    `raw_source` (see `_CANDIDATE_LABEL_RE`) -- is returned as a held-back
    ParagraphScopedRefusal instead of an immediate reason. Everything else
    -- parse errors, warnings with no recognizable line, lines that cannot
    be attributed to one paragraph, DECLARATIVES/ALTER -- stays in the
    first (whole-program, refuse-now) list, fail closed. `raw_source` must
    be the exact text `parse_cobol` was called with -- it is normalized
    here independently, purely for the label-scan; nothing derived from it
    is spliced or otherwise trusted as authoritative over the AST."""
    return _whole_program_reasons(parse_result, classify=True, raw_source=raw_source)


def _whole_program_reasons(
    parse_result, classify: bool, raw_source: str | None
) -> tuple[list[RefusalReason], list[ParagraphScopedRefusal]]:
    reasons: list[RefusalReason] = []
    scoped: list[ParagraphScopedRefusal] = []
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
    program = getattr(parse_result, "ast", None)
    normalized_lines = (
        normalize_fixed_format(raw_source.splitlines()).splitlines()
        if classify and raw_source is not None
        else None
    )
    for warning in getattr(parse_result, "warnings", None) or []:
        # cobolparser >= af08deb blanks un-expanded COPY statements before
        # lexing and reports each as a "COPY <member> not expanded" warning
        # (previously it silently produced empty data-item lists). That
        # exact condition is already refused -- with an actionable message
        # naming the fix (--copybook-path) -- by check_unresolved_copybooks,
        # which every CLI path runs on the same raw source; re-refusing it
        # here as a generic PARSE_WARNING would only bury the specific code.
        text = str(warning)
        if text.startswith("COPY ") and "not expanded" in text:
            continue
        owner: str | None = None
        if classify and parse_result.success and program is not None:
            match = _WARNING_LINE_RE.search(text)
            if match:
                owner = _paragraph_owning_line(
                    program, int(match.group(1)), normalized_lines
                )
        if owner is None:
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
        else:
            scoped.append(
                ParagraphScopedRefusal(
                    paragraph_name=owner,
                    reason=RefusalReason(
                        code="PARSE_WARNING",
                        message=(
                            f"cobolparser reported a parse warning -- the "
                            f"AST is missing content confined to paragraph "
                            f"'{owner}', which a selected test case can "
                            f"execute, so splicing would silently drop "
                            f"program behavior: {warning}"
                        ),
                    ),
                    waiver_note=(
                        f"parse warning waived: its dropped content is "
                        f"confined to paragraph '{owner}', which no selected "
                        f"test case can execute -- that content is neither "
                        f"analyzed nor run: {warning}"
                    ),
                )
            )
    if program is not None:
        reasons.extend(_check_unsupported_control_flow(program))
    return reasons, scoped


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

    This entry point refuses every unresolved COPY unconditionally -- it
    serves the callers with no test cases to scope by (generate/fixtures).
    run_static_checks uses check_unresolved_copybooks_scoped instead."""
    reasons, scoped = check_unresolved_copybooks_scoped(raw_source, None)
    assert not scoped  # with no program to classify against, nothing is held
    return reasons


def check_unresolved_copybooks_scoped(
    raw_source: str, program
) -> tuple[list[RefusalReason], list[ParagraphScopedRefusal]]:
    """check_unresolved_copybooks, except a COPY statement that
    `_paragraph_owning_line` proves to sit inside exactly one PROCEDURE
    DIVISION paragraph's own body (a procedural copybook) AND whose
    single-line span `_copy_own_line_span` verifies to own its
    normalized-text line outright is returned as a held-back
    ParagraphScopedRefusal carrying that span. When the refusal is later
    waived (no selected test case can execute the paragraph), the caller
    must comment the span out of the spliced lines -- the raw COPY text
    would otherwise still reach cobc, which cannot compile an
    unresolvable COPY. Every other COPY -- DATA DIVISION ones, ones
    on/between headers, ones whose line cannot be verified -- stays in
    the first (whole-program, refuse-now) list, fail closed. `program` is
    the parsed AST of this same source (pass None to classify
    nothing)."""
    normalized = normalize_fixed_format(raw_source.splitlines())
    lexer = CobolLexer(normalized, free_form=True)
    tokens = lexer.tokenize()
    copy_indices = [i for i, t in enumerate(tokens) if t.type == TokenType.COPY]
    if not copy_indices:
        return [], []
    normalized_lines = normalized.splitlines()
    whole_lines: set[int] = set()
    scoped: list[ParagraphScopedRefusal] = []
    for index in copy_indices:
        line = tokens[index].location.line
        owner = (
            _paragraph_owning_line(program, line, normalized_lines)
            if program is not None
            else None
        )
        span = (
            _copy_own_line_span(normalized_lines, line) if owner is not None else None
        )
        if owner is None or span is None:
            whole_lines.add(line)
            continue
        scoped.append(
            ParagraphScopedRefusal(
                paragraph_name=owner,
                reason=RefusalReason(
                    code="UNRESOLVED_COPYBOOK",
                    message=(
                        f"unresolved COPY statement at line {line} (inside "
                        f"paragraph '{owner}', which a selected test case "
                        f"can execute) -- the copybook's statements are "
                        f"missing from that paragraph's body, so splicing/"
                        f"compiling would proceed without them -- pass "
                        f"--copybook-path pointing at the copybook's "
                        f"directory"
                    ),
                ),
                waiver_note=(
                    f"unresolved COPY statement at line {line} waived: it "
                    f"is confined to paragraph '{owner}', which no selected "
                    f"test case can execute -- commenting lines "
                    f"{span[0]}-{span[1]} out of the instrumented source so "
                    f"GnuCOBOL never sees the unresolvable COPY"
                ),
                blank_span=span,
            )
        )
    reasons = [
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
        for line in sorted(whole_lines)
    ]
    return reasons, scoped


def _copy_own_line_span(
    normalized_lines: list[str], line: int
) -> tuple[int, int] | None:
    """The single-line span (line, line) of a COPY statement verified to
    own its normalized-text line outright, or None -- fail closed, purely
    textual (no reliance on the lexer's token inventory beyond the COPY
    detection that located `line`). The line must start with the COPY
    keyword (nothing before it), end with its terminating period, and
    contain no other period, so a second statement after the terminator
    (`COPY A. DISPLAY X.`), a quoted text-name containing '.', and a
    multi-line `COPY ... REPLACING` (its first line has no period) never
    qualify -- those stay whole-program refusals. Single-line
    `COPY MEMBER.` is the one procedural-copybook layout this narrowing
    supports: commenting out exactly that one line cannot touch sibling
    code or a following paragraph header."""
    if not 1 <= line <= len(normalized_lines):
        return None
    stripped = normalized_lines[line - 1].strip()
    upper = stripped.upper()
    if not upper.startswith("COPY") or upper[4:5].strip():
        return None
    if not stripped.endswith("."):
        return None
    if stripped.find(".") != len(stripped) - 1:
        return None
    return line, line


def union_executed_paragraphs(program, suite: MockTestSuite) -> set[str] | None:
    """Union over every selected test case of the paragraph/section names
    the reachability model says that case could execute, or None when the
    union cannot be established -- callers must treat None as "every
    paragraph may execute" (fail closed on: no PROCEDURE DIVISION,
    unverifiable paragraph source order, or ANY flow refusal from any
    case's BFS, since a reachable set the model itself distrusts must not
    waive anything -- the per-case gates will refuse those same flow
    problems anyway).

    Per case this is the same `_reachable_paragraphs` BFS check_test_case
    trusts, deliberately WITHOUT the flow-mock skip_traversal narrowing: a
    MOCK PARAGRAPH dispatch replaces a body per-case at runtime, but the
    original text still compiles, so for warning-waiving purposes a
    flow-mocked paragraph stays "executable" (conservative -- at worst an
    extra refusal, which is exactly today's behavior).

    On top of the per-case union, this closes over the GO TO fall-through
    hazard the BFS deliberately does not model as a flow edge (see the
    module docstring): a paragraph entered via GO TO that falls off its own
    end continues into the next paragraph in source order, which therefore
    executes without any PERFORM/GO TO edge naming it. Every GO TO target
    the union reaches is walked forward through `_falls_through` (the same
    conservative predicate `_go_to_fallthrough_targets` uses, section
    boundaries transparent), and each newly executable paragraph's own
    downstream BFS is folded in, to a fixpoint."""
    procedure = program.get_division("PROCEDURE")
    if procedure is None:
        return None
    ordered = _source_ordered_paragraphs(procedure)
    if ordered is None:
        return None
    union: set[str] = set()
    for case in suite.test_cases:
        seen, flow_reasons = _reachable_paragraphs(
            program, case.perform_target, case.perform_thru
        )
        if flow_reasons:
            return None
        union |= seen

    go_to_targets = _go_to_targets(program)
    index_by_name = {p.paragraph_name: i for i, p in enumerate(ordered)}
    section_members: dict[str, list[str]] = {}
    for section_name, section in getattr(procedure, "_sections", {}).items():
        if section_name:
            section_members.setdefault(
                section_name, [p.paragraph_name for p in section.paragraphs]
            )

    def entry_index(name: str) -> int | None:
        i = index_by_name.get(name)
        if i is not None:
            return i
        members = section_members.get(name)
        return index_by_name.get(members[0]) if members else None

    changed = True
    while changed:
        changed = False
        for name in sorted(union & go_to_targets):
            cursor = entry_index(name)
            if cursor is None:
                # A reached GO TO target the fall-through walk can't anchor
                # (e.g. an empty section): the closure is incomplete, so the
                # union cannot be trusted to waive anything.
                return None
            while _falls_through(ordered[cursor]) and cursor + 1 < len(ordered):
                cursor += 1
                fallen = ordered[cursor].paragraph_name
                if fallen in union:
                    continue
                fallen_seen, fallen_reasons = _reachable_paragraphs(program, fallen)
                if fallen_reasons:
                    return None
                union |= fallen_seen
                changed = True
    return union


def resolve_scoped_refusals(
    scoped: list[ParagraphScopedRefusal], executed: set[str] | None
) -> list[RefusalReason]:
    """The refusal reasons among `scoped` that must fire given `executed`
    (union_executed_paragraphs' result): every held-back refusal whose
    paragraph some selected test case can execute, or ALL of them when the
    union could not be established (None -- fail closed). An empty return
    means every scoped refusal is waived."""
    if executed is None:
        return [item.reason for item in scoped]
    return [item.reason for item in scoped if item.paragraph_name in executed]


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
    file_status_fields: dict[str, str] | None = None,
) -> list[RefusalReason]:
    from mockymock.analysis.flow_mocks import resolved_flow_targets

    file_status_fields = file_status_fields or {}

    reasons: list[RefusalReason] = []
    mocked_paragraphs, mocked_sections = resolved_flow_targets(program, case)
    mocked_flow_names = mocked_paragraphs | mocked_sections
    reachable, thru_reasons = _reachable_paragraphs(
        program,
        case.perform_target,
        case.perform_thru,
        skip_traversal=mocked_flow_names,
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

    # Flow-target directives (MOCK PARAGRAPH/SECTION) don't match boundary
    # sites -- they match the paragraph/section itself. Matched when the
    # reachability BFS hit the name through a PERFORM/GO TO edge (or the
    # driver's own PERFORM); a directive naming this case's own entry point
    # refuses -- the dispatch would replace the very code under test.
    for directive in case.mocks:
        if directive.category not in FLOW_CATEGORIES:
            continue
        if directive.key in (case.perform_target, case.perform_thru):
            matched_directives.add(id(directive))
            reasons.append(
                RefusalReason(
                    code="UNSUPPORTED_FLOW_MOCK_TARGET",
                    message=(
                        f"MOCK {directive.describe()} names this test "
                        f"case's own PERFORM entry point -- mocking the "
                        f"entry point would replace the very code the test "
                        f"performs; PERFORM a caller of it instead"
                    ),
                )
            )
        elif directive.key in reachable:
            matched_directives.add(id(directive))

    # Boundary sites inside a flow-mocked paragraph/section are unreachable
    # for this case (the dispatch replaces the body), so they need no mocks
    # of their own -- that is the point of a flow mock.
    for site in surface.sites_in(reachable - mocked_flow_names):
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
        if id(directive) in matched_directives:
            continue
        if directive.category in FLOW_CATEGORIES:
            if directive.key not in mocked_flow_names:
                # Unresolvable name: check_flow_mocks refuses it with the
                # precise UNRESOLVED_FLOW_MOCK_TARGET reason -- don't bury
                # that under a generic UNMATCHED_MOCK here.
                continue
            reasons.append(
                RefusalReason(
                    code="UNMATCHED_MOCK",
                    message=(
                        f"MOCK {directive.describe()} is not reachable "
                        f"from '{case.perform_target}' -- no PERFORM/GO TO "
                        f"edge on this test case's flow ever enters it"
                    ),
                )
            )
            continue
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

    for directive in case.mocks:
        missing_status_field = directive.key.upper() not in file_status_fields
        if directive.file_status is not None and missing_status_field:
            reasons.append(
                RefusalReason(
                    code="UNRESOLVED_FILE_STATUS_TARGET",
                    message=(
                        f"MOCK {directive.describe()} uses FILE-STATUS IS, "
                        f"but '{directive.key}' has no FILE STATUS IS "
                        f"<field> clause declared in its SELECT entry -- "
                        f"there is no WORKING-STORAGE field to move the "
                        f"status into"
                    ),
                )
            )
        # elif, not a second independent `if`: both checks share the same
        # missing_status_field root cause. When FILE-STATUS IS sugar is
        # ALSO in play the block above already reported it for this exact
        # directive -- firing this one too would double-refuse the same
        # directive with a second, redundant message (audit finding F27).
        elif (
            directive.category is MockCategory.READ
            and directive.rows is not None
            and directive.terminal_row is None
            and missing_status_field
        ):
            reasons.append(
                RefusalReason(
                    code="UNRESOLVED_FILE_STATUS_TARGET",
                    message=(
                        f"MOCK READ {directive.key} ROWS has no way to "
                        f"signal end-of-data: the file declares no FILE "
                        f"STATUS field and the mock has no "
                        f"TERMINAL ( ... ) group -- add one or the read "
                        f"loop cannot terminate"
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
    program,
    start: str,
    thru: str | None = None,
    skip_traversal: frozenset[str] | set[str] = frozenset(),
) -> tuple[set[str], list[RefusalReason]]:
    """Return (reachable paragraph/section names, flow refusals), computed
    in a single BFS pass over PerformStatement and GoStatement edges.

    `skip_traversal` holds paragraph/section names mocked as flow targets
    (MOCK PARAGRAPH/SECTION) by the test case under analysis: a name in it
    is still recorded as reached (so the directive counts as matched and
    UNKNOWN_PARAGRAPH still works), but its body is never traversed -- no
    statements walked, no section members expanded -- because the mock
    dispatch replaces that body for this case, making everything inside it
    (boundary statements, terminators, further PERFORM/GO TO edges)
    unreachable. Callers that feed the result to `MockSurface.sites_in`
    must subtract these names first.

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
        if name in skip_traversal:
            # Flow-mocked for this case: reached, but its body is replaced
            # by the mock dispatch -- never walk into it.
            seen.add(name)
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


def _falls_through(paragraph) -> bool:
    """True unless `paragraph`'s last top-level statement provably diverts
    control away -- GOBACK, STOP RUN (not STOP <literal>, which only
    pauses for operator input and resumes), a single-target GO TO (a
    computed GO TO ... DEPENDING ON is NOT included: GnuCOBOL falls
    through to the next statement when the subscript is out of range, so
    it is not a guaranteed unconditional transfer), or EXIT PARAGRAPH/
    SECTION/PROGRAM (a bare EXIT./EXIT PERFORM does not qualify -- the
    former is a no-op placeholder, the latter exits an in-line loop body,
    not the paragraph). Everything else -- no statements at all, or
    ending in MOVE/DISPLAY/PERFORM/IF/EVALUATE/... -- is conservatively
    assumed to fall through, matching this module's fail-closed posture
    elsewhere: no attempt is made to prove that every branch of a
    trailing IF/EVALUATE terminates. See
    docs/2026-07-10-goto-fallthrough-terminator-hazard-design.md."""
    statements = paragraph.statements
    if not statements:
        return True
    last = statements[-1]
    if isinstance(last, GobackStatement):
        return False
    if isinstance(last, StopStatement) and last.stop_type == "RUN":
        return False
    if isinstance(last, GoStatement) and last.depending_on_variable is None:
        return False
    if isinstance(last, ExitStatement) and last.exit_type in (
        "PARAGRAPH",
        "SECTION",
        "PROGRAM",
    ):
        return False
    return True


def _go_to_fallthrough_targets(program, go_to_targets: set[str]) -> dict[str, str]:
    """Every paragraph reachable ONLY by falling through past a GO TO
    target's own end -- an unmodeled shape the reachability BFS does not
    represent as a flow edge (see the module docstring). Maps each such
    paragraph name to the GO-TO-target paragraph/section name whose
    fall-through chain reaches it, for diagnosable refusal messages.

    A paragraph entered this way carries the exact same EXIT PARAGRAPH
    hazard as a paragraph directly named by a GO TO (spike #4, docs/
    2026-07-08-goback-stop-run-support-design.md): the runtime frame-stack
    context at the point its code executes never went through a genuine
    PERFORM call, whether that paragraph is itself the GO TO target or was
    merely fallen into afterward.

    Conservative and fail-closed like the rest of this module: propagates
    through every paragraph after a GO TO target in source order until one
    is found whose own last top-level statement provably cannot fall
    through further (see _falls_through). A GO TO targeting a SECTION name
    is seeded from that section's first paragraph -- fall-through is
    transparent to SECTION boundaries, a header doesn't stop it; the
    section's own member paragraphs are covered by the walk since
    _source_ordered_paragraphs includes every paragraph regardless of
    section membership.

    Returns {} when _source_ordered_paragraphs can't establish a strict
    source order -- the same pre-existing blind spot that already limits
    other checks in this module (e.g. _expand_thru_range) to refusing only
    the specific reachability question they were asked, not every
    reachability question in the file."""
    procedure = program.get_division("PROCEDURE")
    if procedure is None:
        return {}
    ordered = _source_ordered_paragraphs(procedure)
    if ordered is None:
        return {}
    index_by_name = {p.paragraph_name: i for i, p in enumerate(ordered)}
    section_members: dict[str, list[str]] = {}
    for section_name, section in getattr(procedure, "_sections", {}).items():
        if not section_name:
            continue
        section_members.setdefault(
            section_name, [p.paragraph_name for p in section.paragraphs]
        )

    hazard: dict[str, str] = {}
    for name in go_to_targets:
        start = index_by_name.get(name)
        if start is None:
            members = section_members.get(name)
            if not members:
                continue
            start = index_by_name.get(members[0])
            if start is None:
                continue
        cursor = start
        while _falls_through(ordered[cursor]) and cursor + 1 < len(ordered):
            cursor += 1
            hazard.setdefault(ordered[cursor].paragraph_name, name)
    return hazard


def _plain_perform_statements(
    statements: list, nested: bool = False, in_boundary: bool = False
) -> list[tuple[PerformStatement, bool, bool]]:
    """Recursively collect every plain, unconditional, single-shot,
    out-of-line PerformStatement in `statements` -- thru_paragraph is
    None, target_paragraph set, perform_type == "SIMPLE" -- at ANY
    nesting depth, tagged with:

    - `nested`: False only for a direct member of the paragraph's own
      top-level `.statements` list (today's only supported shape); True
      at any depth >= 1 -- an IF/ELSE branch, an EVALUATE
      WHEN/WHEN OTHER branch, or an inline PERFORM ... END-PERFORM loop
      body (via _nested_statement_lists' then_statements/else_statements/
      when_clauses/inline_statements).
    - `in_boundary`: sticky -- True once recursion has entered another
      boundary statement's clause body (CALL's ON EXCEPTION, a file
      statement's AT END, ...). Mirrors mock_surface._walk_statements'
      identical child_in_boundary propagation: a PERFORM found there is
      never a valid chain edge, because splicing the enclosing boundary
      statement (when it's mocked) removes the PERFORM and any inserted
      check along with it -- the same structural reason a nested
      BoundarySite there is unsplicable.

    Every recursive call passes nested=True literally (not the parent's
    nested value), matching mock_surface._walk_statements' own pattern,
    so a PERFORM is marked nested at every depth >= 1 while a genuinely
    top-level one (the initial call, nested defaults to False) stays
    unmarked. See docs/2026-07-10-conditionally-nested-intermediate-perform-design.md.
    """
    found: list[tuple[PerformStatement, bool, bool]] = []
    for statement in statements:
        if (
            isinstance(statement, PerformStatement)
            and statement.thru_paragraph is None
            and statement.target_paragraph
            and statement.perform_type == "SIMPLE"
        ):
            found.append((statement, nested, in_boundary))
        child_in_boundary = in_boundary or isinstance(
            statement, _BOUNDARY_STATEMENT_TYPES
        )
        for nested_list in _nested_statement_lists(statement):
            found.extend(
                _plain_perform_statements(
                    nested_list, nested=True, in_boundary=child_in_boundary
                )
            )
    return found


def _plain_perform_edges_from(
    program, start: str, safe_section_entries: dict[str, str] | None = None
) -> tuple[set[str], list[tuple[PerformStatement, bool]]]:
    """BFS from `start` following plain (non-THRU), unconditional,
    single-shot PERFORM statements -- PerformStatement nodes with
    thru_paragraph is None and perform_type == "SIMPLE" -- at ANY nesting
    depth within a paragraph (top-level, or nested inside an IF/ELSE
    branch, an EVALUATE WHEN/WHEN OTHER branch, or an inline
    PERFORM ... END-PERFORM loop body). A PERFORM nested inside another
    boundary statement's clause body (CALL's ON EXCEPTION, a file
    statement's AT END, ...) is never followed -- see
    _plain_perform_statements.

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
    refusal branch needed. (This is distinct from a PERFORM nested INSIDE
    an inline `PERFORM ... END-PERFORM` loop BODY, which IS followed --
    EXIT PARAGRAPH from inside an inline loop body correctly exits the
    whole enclosing paragraph, verified empirically 2026-07-10; the
    excluded case here is an OUT-OF-LINE PERFORM that IS itself a loop
    over a different paragraph.)

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
    unresolved name landing in `seen`. SECTION members that aren't a safe
    entry's first paragraph are still excluded entirely, same as before:
    this only looks up names in `procedure.paragraphs` (top-level
    paragraphs) and, when `safe_section_entries` resolves one, the
    specific first-paragraph names it names -- never any other section
    member -- so a chain that would need to pass through one of those
    (fall-through, or a direct PERFORM of a non-first section member)
    still naturally refuses via the existing "reachable but not via a
    plain chain" check.

    Returns (reachable paragraph names via this restricted edge set, the
    (PerformStatement, nested) pairs that ARE those edges) -- every one of
    those statements is a candidate for the early-exit flag-check
    instrumentation, `nested` telling the caller which validator/
    insertion-point computation applies. Deliberately NOT the same as
    `_reachable_paragraphs`: that function also follows GO TO and
    section/THRU fall-through edges, exactly the unsafe shapes this
    restricted variant must exclude."""
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
    edges: list[tuple[PerformStatement, bool]] = []
    while stack:
        name = stack.pop()
        paragraph = resolved.get(name)
        if paragraph is None:
            continue
        for statement, nested, in_boundary in _plain_perform_statements(
            paragraph.statements
        ):
            if in_boundary:
                continue
            edges.append((statement, nested))
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
    docs/2026-07-10-section-scoped-terminator-support-design.md; notably,
    for a SECTION-scoped terminator, the test's own perform_target must name
    the SECTION itself, not the paragraph directly, as direct paragraph
    naming (shape 3 of the design doc) bypasses the section entry point and
    remains unverified) -- is reachable from the test's own
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
    go_to_fallthrough = _go_to_fallthrough_targets(program, go_to_targets)
    terminator_sites = {
        id(s.statement): s
        for s in surface.boundary_sites
        if s.category is None and s.label in _TERMINATOR_LABELS
    }

    plans_by_statement: dict[int, TerminatorPlan] = {}
    reasons: list[RefusalReason] = []
    refused_statement_ids: set[int] = set()

    from mockymock.analysis.flow_mocks import resolved_flow_targets

    for case in suite.test_cases:
        # A terminator inside a paragraph/section this case flow-mocks
        # (MOCK PARAGRAPH/SECTION) is unreachable for this case -- the mock
        # dispatch replaces the body -- so it must not demand a plan or a
        # refusal on this case's account. Other cases still evaluate it.
        mocked_paragraphs, mocked_sections = resolved_flow_targets(program, case)
        mocked_flow_names = mocked_paragraphs | mocked_sections
        reachable, _ = _reachable_paragraphs(
            program,
            case.perform_target,
            case.perform_thru,
            skip_traversal=mocked_flow_names,
        )
        reachable -= mocked_flow_names
        safe_names, chain_performs = _plain_perform_edges_from(
            program, case.perform_target, safe_section_entries
        )
        chain_section_names = safe_names - (top_level_names | safe_section_first_names)
        chain_go_to_names = safe_names & go_to_targets
        chain_fallthrough_names = safe_names & go_to_fallthrough.keys()

        chain_problem: str | None = None
        for perform, _nested in chain_performs:
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
            elif paragraph_name in go_to_fallthrough:
                problem = (
                    f"is reached by falling through past the end of "
                    f"paragraph '{go_to_fallthrough[paragraph_name]}', which "
                    f"is itself reachable via GO TO somewhere in this "
                    f"program -- a paragraph entered this way was never "
                    f"PERFORMed either, so it shares the same EXIT PARAGRAPH "
                    f"hazard as a direct GO TO target even though it is "
                    f"never named by a GO TO itself"
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
            elif chain_fallthrough_names:
                bad_name = sorted(chain_fallthrough_names)[0]
                problem = (
                    f"is only reachable through this test's own early-exit "
                    f"propagation chain by way of '{bad_name}', which is "
                    f"reached by falling through past the end of paragraph "
                    f"'{go_to_fallthrough[bad_name]}' rather than via "
                    f"PERFORM -- the early-exit propagation mechanism "
                    f"(EXIT PARAGRAPH) only works correctly when every "
                    f"paragraph on the chain is entered exclusively via "
                    f"PERFORM"
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
            for perform, _nested in chain_performs:
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
