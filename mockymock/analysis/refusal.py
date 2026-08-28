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
  be paragraphs or sections. The BFS additionally closes over GO TO
  fall-through (2026-08-12 bug review): every reached GO TO target is
  walked forward through source order via `_falls_through`, and each
  paragraph reachable by falling off one's end is fed back into the BFS to
  a fixpoint -- without this, a boundary in a fallen-into paragraph passed
  every mock gate and then executed unmocked at runtime. (The same hazard
  for `find_terminator_plans` was already guarded: `_go_to_fallthrough_targets`
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
- A GO TO fully covered by a GotoExitPlan (`neutralized_goto_targets`,
  2026-08-25) is NOT an edge: the splicer replaces it with EXIT PARAGRAPH
  at its own call site, so modeling it would make the gate demand mocks
  for a fall-through cascade the compiled test can never execute -- the
  "GO TO <own-exit-label>" idiom used to pull in every paragraph from the
  exit label to the end of the program this way. check_test_case takes
  the neutralized set from its caller (cli.checks.run_static_checks
  computes it once per run); the same set already narrowed
  find_terminator_plans' hazard sets.

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

AMBIGUOUS_MOCK / UNSUPPORTED_NESTED_MOCK_TARGET / UNSUPPORTED_MOCK_TARGET_
LAYOUT are additionally re-checked a second time, program-wide (2026-08-11
fix): splicer.orchestrator.splice_program matches directives to sites by
category/key alone, with no reachability filter at all, so a case's own
directive can get spliced against a physical site its own PERFORM target
never reaches. check_test_case's reachable-set loop alone could pass
`lint` clean on a shape that then crashed `export`/`run` with an unhandled
ValueError from injector.build_site_dispatch or orchestrator's own
defensive checks. See check_test_case's second pass over
surface.boundary_sites (unfiltered) below, and .okf/analysis.md's
"check_test_case" section for the full writeup.

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
and UNSUPPORTED_SORT_MERGE (now only for a SORT/MERGE mixing a USING/
GIVING file with an INPUT/OUTPUT PROCEDURE on the other side -- that
shape touches a physical file mockymock cannot seed/read AND runs a
procedure whose other logic a whole-statement mock would silently skip,
so it stays unsupported. Two other SORT/MERGE shapes are NOT refused
here: a plain-file-form SORT/MERGE -- `USING ... GIVING ...`, no
procedure clause -- is mockable via MOCK SORT/MOCK MERGE <sd-file-name>
like any other file-op boundary (see mock_surface.py's
`_is_plain_sort_merge`), and a pure-procedure-form SORT -- `INPUT
PROCEDURE ... OUTPUT PROCEDURE ...`, no USING/GIVING at all -- is left
real/unspliced (see `_is_pure_procedure_sort`), with its RELEASE/RETURN
statements independently mockable via MOCK RELEASE/MOCK RETURN. All
three mockable categories fall through the ordinary UNMOCKED_FILE_OP/
AMBIGUOUS_MOCK/nested/layout checks below like any other file op).
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

CAPTURE_ARG_OUT_OF_RANGE lives in check_test_case (a CAPTURE ARG directive
belongs to exactly one test case) but is evaluated over the WHOLE program's
boundary sites for the same reason: splice_program matches directives to
sites by category+key alone, with no reachability filter, so a CAPTURE ARG
index is spliced against every physical site sharing the mocked key --
including ones the owning case never reaches.

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

from cobolparser.analysis.unused_variables import collect_declared_items
from cobolparser.lexer import CobolLexer, TokenType
from cobolparser.models.program import CobolParagraph
from cobolparser.models.statements.call import CallStatement
from cobolparser.models.statements.control import (
    GoStatement,
    PerformStatement,
    StopStatement,
)
from cobolparser.models.statements.misc import (
    AlterStatement,
    ExitStatement,
    GobackStatement,
    MergeStatement,
    SortStatement,
)
from cobolparser.preprocess import normalize_fixed_format

from mockymock.analysis.linkage import address_of_sites, linkage_plan
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
from mockymock.splicer.source_map import (
    collect_boundaries,
    nested_statement_span,
    statement_span,
    statement_top_level_problem,
)

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
    cobc, which cannot compile an unresolvable COPY).

    `neutralize_span` plays the same role for a waived CICS
    `DFHRESP(...)`/`DFHVALUE(...)` macro call -- (1-based line, 0-based
    start column, 0-based end column) of the call text, which
    run_static_checks overwrites in place with
    `CICS_MACRO_PLACEHOLDER`, space-padded to the identical width so no
    line or column any AST location indexes into ever moves. Same
    reasoning as `blank_span`: the unexpanded macro would otherwise still
    reach cobc, which has no CICS translator and cannot resolve it. At
    most one of the two spans is ever set."""

    paragraph_name: str
    reason: RefusalReason
    waiver_note: str
    blank_span: tuple[int, int] | None = None
    neutralize_span: tuple[int, int, int] | None = None


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


@dataclass
class GotoExitPlan:
    """One physical GO TO statement found safe to splice directly into
    EXIT PARAGRAPH at its own call site, because its target is a
    paragraph whose entire body is a no-op EXIT statement -- see
    docs/2026-08-17-goto-exit-paragraph-simplification-design.md.
    STATUS: implemented, not yet verified against real GnuCOBOL (no
    Docker daemon was available when this was written) -- see that
    design doc's Status note before trusting this in production.

    `exit_kind` is always "PARAGRAPH" today: find_goto_exit_plans only
    accepts a top-level enclosing paragraph (SECTION-scoped enclosing
    paragraphs are declined -- see that function's docstring for why).
    Kept as a field, matching TerminatorPlan's shape, in case SECTION
    support is added later.

    Unlike TerminatorPlan, this never carries chain_performs: the
    replacement ends the SAME paragraph the GO TO already lived in, so
    there is nothing to propagate through an intermediate PERFORM chain
    -- no UT-EARLY-EXIT flag is involved at all.

    `span` is precomputed by find_goto_exit_plans (never None on a
    returned plan -- a plan whose span could not be validated is not
    returned at all): a top-level GO TO's span comes from `statement_span`,
    a nested one's from `nested_statement_span`. Precomputing it here,
    once, at the same place the safety checks run, means the splicer
    never has to re-derive nested-vs-top-level span logic itself -- see
    `nested_statement_span`'s docstring for the bug this avoids."""

    statement: GoStatement
    paragraph_name: str
    exit_kind: str = "PARAGRAPH"
    span: tuple[int, int] | None = None


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
    program,
    line: int,
    normalized_lines: list[str] | None = None,
    *,
    label_scan_to_line: bool = False,
) -> str | None:
    """`_paragraph_body_span`'s owner name, or None -- see that function's
    docstring for the base attribution rules.

    When `normalized_lines` is given, ownership additionally requires
    `_has_unaccounted_label` to find nothing suspicious in the candidate
    owner's own body (see `_CANDIDATE_LABEL_RE`'s docstring for why):
    classification fails closed rather than trust a paragraph boundary
    that might not be where it looks. Every *_scoped call site must pass
    it; omitting it is only for callers that genuinely have no source
    text yet.

    `label_scan_to_line` narrows that scan to [owner header, `line`]
    instead of the owner's whole body. Use it -- and ONLY it -- when
    `line` marks evidence whose extent is exactly that one line, as a
    `DFHRESP(...)` call's does: an unrecognized label AFTER `line` cannot
    change which paragraph owns `line`, so scanning past it only produces
    false vetoes (a bare `END-IF.`/`EXIT.` closing the very statement the
    evidence sits in matches `_CANDIDATE_LABEL_RE`, and in the CICS
    `IF ... DFHRESP(...) ... END-IF.` idiom it always does). The default
    keeps the whole-body scan, which is what a PARSE_WARNING needs: its
    line proves only where a drop STARTS, and error recovery may have
    resynchronized past a real header further down inside the same
    body."""
    span = _paragraph_body_span(program, line)
    if span is None:
        return None
    owner, start, next_start = span
    if normalized_lines is not None:
        if label_scan_to_line:
            end = line
        else:
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


# The five arithmetic statements whose scope terminator cobolparser (as of
# the pin this project resolves) fails to consume when it appears alone on
# its own line followed by a period -- it is parsed as a paragraph name
# instead, silently reparenting every following statement into it (see
# docs/2026-08-10-framework-audit-and-roadmap.md Finding 2; same bug class
# as the fixed ROUNDED-after-GIVING phantom paragraph, .okf/log.md
# 2026-07-21). Deliberately the exact five reserved words, not a pattern
# like `^END-[A-Z]+$` -- that would also match legitimate paragraph names
# such as END-OF-JOB or END-RUN.
_PHANTOM_TERMINATOR_PARAGRAPH_NAMES = frozenset(
    {"END-ADD", "END-SUBTRACT", "END-MULTIPLY", "END-DIVIDE", "END-COMPUTE"}
)


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
    for paragraph in _all_paragraphs(procedure):
        if paragraph.paragraph_name.upper() in _PHANTOM_TERMINATOR_PARAGRAPH_NAMES:
            reasons.append(
                RefusalReason(
                    code="UNSUPPORTED_PHANTOM_PARAGRAPH",
                    message=(
                        f"paragraph '{paragraph.paragraph_name}' (line "
                        f"{paragraph.location.line}) is named after a "
                        f"reserved arithmetic scope terminator -- cobolparser "
                        f"failed to consume it as the preceding "
                        f"ADD/SUBTRACT/MULTIPLY/DIVIDE/COMPUTE's own "
                        f"terminator and parsed it as a paragraph instead, "
                        f"silently reparenting every statement after it; "
                        f"drop the explicit terminator and end the "
                        f"statement with a period instead (moving it to "
                        f"the same line does not avoid this)"
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
    extra refusal, which is exactly today's behavior). The GO-TO-exit
    `neutralized_goto` narrowing (2026-08-25) is deliberately NOT applied
    here either, for the same reason plus a mechanical one: this runs in
    run_static_checks step 4b, before the normalized `lines`/`scope_map`
    find_goto_exit_plans validates spans against exist -- and leaving the
    spliced-away GO TO modeled as a live edge only ever waives FEWER
    warnings, never more.

    On top of the per-case union, this closes over the GO TO fall-through
    hazard the BFS deliberately does not model as a flow edge (see the
    module docstring): a paragraph entered via GO TO that falls off its own
    end continues into the next paragraph in source order, which therefore
    executes without any PERFORM/GO TO edge naming it. Every GO TO target
    the union reaches is walked forward via `_walk_fallthrough_from` (the
    same shared walk `_reachable_paragraphs` uses), and each newly
    executable paragraph's own downstream BFS is folded in, to a fixpoint.
    2026-08-26: that walk now stops at the end of a SECTION
    `_fallthrough_safe_sections` proves is entered only via `PERFORM
    <section-name>` instead of cascading past it -- section boundaries are
    NOT transparent for such a section -- with `case_seeds` excluding any
    section a selected case's own PERFORM target/thru bypasses by naming a
    member paragraph directly (see `_paragraph_safe_section_map`); a
    section that doesn't qualify is walked exactly as before."""
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
    # Computed once here, not per walk: the closure below is a fixpoint
    # loop over every reached GO TO target. See `_fallthrough_flags`.
    falls = _fallthrough_flags(ordered)
    section_members: dict[str, list[str]] = {}
    for section_name, section in getattr(procedure, "_sections", {}).items():
        if section_name:
            section_members.setdefault(
                section_name, [p.paragraph_name for p in section.paragraphs]
            )

    # Every selected case's own entry point(s): unlike _reachable_paragraphs
    # (one start/thru per call), this closure walk operates on the union
    # across the whole suite, so a section is excluded here whenever ANY
    # selected case's PERFORM target/thru names one of its member
    # paragraphs directly -- see _paragraph_safe_section_map's docstring.
    case_seeds: set[str] = set()
    for case in suite.test_cases:
        case_seeds.add(case.perform_target)
        if case.perform_thru:
            case_seeds.add(case.perform_thru)
    paragraph_safe_section = _paragraph_safe_section_map(
        section_members, _fallthrough_safe_sections(program), case_seeds
    )

    changed = True
    while changed:
        changed = False
        for name in sorted(union & go_to_targets):
            reached = _walk_fallthrough_from(
                name,
                ordered,
                index_by_name,
                section_members,
                paragraph_safe_section,
                falls=falls,
            )
            if reached is None:
                # A reached GO TO target the fall-through walk can't anchor
                # (e.g. an empty section): the closure is incomplete, so the
                # union cannot be trusted to waive anything.
                return None
            for fallen in reached:
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
    LINKAGE-SECTION neutralization transform (see
    docs/2026-07-08-ims-linkage-support-design.md and
    docs/2026-08-27-cics-eib-linkage-support-design.md for the no-ENTRY
    generalization). `[]` when `linkage.linkage_plan` finds nothing to do
    (an absent/empty LINKAGE SECTION -- an ordinary CALL-only program) or
    when the shape is safe to neutralize; otherwise one reason per guardrail that
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

    # `SET ADDRESS OF <folded item>` occurrences the rewrite in
    # `splicer.linkage.redirect_address_of` cannot classify or cannot express
    # as a single-line column span. Left in place they are a hard cobc error
    # ("cannot change address of 'X', which is not BASED or a LINKAGE item"),
    # so refuse rather than emit source that cannot compile.
    _, address_of_problems = address_of_sites(lines, plan)
    for problem in address_of_problems:
        reasons.append(
            RefusalReason(
                code="UNSUPPORTED_LINKAGE_ADDRESSING",
                message=(
                    f"{problem} -- folding the LINKAGE SECTION into "
                    "WORKING-STORAGE makes `SET ADDRESS OF` on its items "
                    "illegal (GnuCOBOL: not BASED or a LINKAGE item), and "
                    "this occurrence cannot be safely redirected"
                ),
            )
        )

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


# Not a plain `\b...\b`: COBOL identifiers may contain hyphens, which are
# not `\w` characters, so `\b` alone false-matches inside an unrelated
# hyphenated name (e.g. `\bDFHCOMMAREA\b` matches inside
# `WS-DFHCOMMAREA-LEN`). See `analysis.cics_eib`'s identical fix for the
# same reasoning. Matched case-insensitively -- COBOL identifiers are
# themselves case-insensitive.
_DFHRESP_MACRO_RE = re.compile(
    r"(?<![A-Za-z0-9-])(?:DFHRESP|DFHVALUE)\s*\(", re.IGNORECASE
)
_DFHCOMMAREA_RE = re.compile(
    r"(?<![A-Za-z0-9-])DFHCOMMAREA(?![A-Za-z0-9-])", re.IGNORECASE
)
# The full single-line call, condition name included -- `_DFHRESP_MACRO_RE`
# above only detects that one is present. A call this does not span
# (continued across lines, or an argument that is not a single COBOL word)
# is never classified as paragraph-local; it stays a whole-program refusal.
_CICS_MACRO_CALL_RE = re.compile(
    r"(?<![A-Za-z0-9-])(?:DFHRESP|DFHVALUE)\s*\(\s*[A-Za-z0-9$@#-]+\s*\)",
    re.IGNORECASE,
)

# What a WAIVED macro call is rewritten to in the instrumented source.
# cobc has no CICS translator, so leaving the call in place fails the
# compile no matter which paragraph holds it -- exactly the reason a
# waived unresolved COPY gets commented out (see `blank_span`). -1 is not
# a value any real CICS condition expands to, so every comparison against
# it is deterministically false: the honest reading of "this response code
# cannot be evaluated", in code that the waiver has already established no
# selected test case can execute.
CICS_MACRO_PLACEHOLDER = "-1"


def check_cics_eib_layout(program, lines: list[str]) -> list[RefusalReason]:
    """`UNSUPPORTED_CICS_MACRO` / `UNSUPPORTED_CICS_DFHCOMMAREA`: guards the
    two CICS-implicit-linkage situations `analysis.cics_eib`/`splicer.
    cics_eib` cannot safely handle (see
    docs/2026-08-27-cics-eib-linkage-support-design.md's "Guardrails"
    section). Independent of `cics_eib_plan` -- both checks below can fire
    even for a program that references no EIB field at all -- and
    independent of `check_linkage_layout`: additive, not exclusive-or.

    `lines` must be the same NORMALIZED free-form text
    (`normalize_fixed_format` output) the splicer edits, same convention as
    `check_linkage_layout`.
    """
    reasons, scoped = _cics_eib_reasons(program, lines, classify=False)
    assert not scoped  # classify=False never holds an occurrence back
    return reasons


def check_cics_eib_layout_scoped(
    program, lines: list[str]
) -> tuple[list[RefusalReason], list[ParagraphScopedRefusal]]:
    """check_cics_eib_layout, except each `DFHRESP(...)`/`DFHVALUE(...)`
    call that `_paragraph_owning_line` proves to sit inside exactly one
    PROCEDURE DIVISION paragraph's own body -- and whose whole call text
    `_CICS_MACRO_CALL_RE` spans on a single line -- is returned as a
    held-back ParagraphScopedRefusal instead of an immediate reason, to be
    resolved against `union_executed_paragraphs` like every other
    paragraph-scoped refusal (see the module docstring).

    Why this one is scopable at all: an unexpanded CICS macro is a
    property of the *code that evaluates it*, not of the program's storage
    layout, so a call in a paragraph no selected test case can execute
    cannot affect the test's behavior. That is the whole difference from
    `UNSUPPORTED_CICS_DFHCOMMAREA` below, which stays whole-program
    unconditionally: an undeclared DFHCOMMAREA is a missing *declaration*,
    and mockymock would have to synthesize storage of an unknowable size
    for it however unreachable its references are.

    A waived call still has to compile, so each held-back refusal carries
    a `neutralize_span` for run_static_checks to overwrite -- see
    `ParagraphScopedRefusal` and `CICS_MACRO_PLACEHOLDER`. Anything the
    classification cannot pin down -- a call outside any paragraph body (a
    DATA DIVISION VALUE clause, a line on a paragraph header), one
    continued across lines, one whose argument is not a single COBOL word,
    one too short to hold the placeholder -- stays in the first
    (whole-program, refuse-now) list, fail closed."""
    return _cics_eib_reasons(program, lines, classify=True)


def _cics_eib_reasons(
    program, lines: list[str], classify: bool
) -> tuple[list[RefusalReason], list[ParagraphScopedRefusal]]:
    reasons: list[RefusalReason] = []
    scoped: list[ParagraphScopedRefusal] = []
    text = "\n".join(lines)

    detected = _DFHRESP_MACRO_RE.findall(text)
    if detected:
        located = _classify_cics_macro_calls(program, lines) if classify else []
        if len(located) != len(detected):
            # Either classification is off (generate/fixtures), or at least
            # one detected call could not be pinned to a paragraph body and
            # rewritten -- refuse the whole program rather than waive an
            # occurrence nothing proved paragraph-local.
            reasons.append(
                RefusalReason(
                    code="UNSUPPORTED_CICS_MACRO",
                    message=(
                        "program references DFHRESP(...)/DFHVALUE(...) -- these "
                        "are CICS-translator macro-functions (e.g. "
                        "DFHRESP(NORMAL) expands to a literal response code from "
                        "a large, translator-version-sensitive condition table) "
                        "that mockymock cannot safely expand without a real CICS "
                        "translator, so this program is not supported"
                    ),
                )
            )
        else:
            scoped.extend(located)

    if _DFHCOMMAREA_RE.search(text):
        declared = {item.name.upper() for item in collect_declared_items(program)}
        if "DFHCOMMAREA" not in declared:
            reasons.append(
                RefusalReason(
                    code="UNSUPPORTED_CICS_DFHCOMMAREA",
                    message=(
                        "program references DFHCOMMAREA but never declares "
                        "it anywhere in its own DATA DIVISION -- its size "
                        "and layout are unknowable, so mockymock cannot "
                        "safely synthesize storage for it (a program that "
                        "declares its own `LINKAGE SECTION. 01 DFHCOMMAREA."
                        "..` is supported via the generalized LINKAGE "
                        "neutralization instead, see "
                        "docs/2026-08-27-cics-eib-linkage-support-design.md)"
                    ),
                )
            )

    return reasons, scoped


def _classify_cics_macro_calls(
    program, lines: list[str]
) -> list[ParagraphScopedRefusal]:
    """One held-back refusal per `DFHRESP(...)`/`DFHVALUE(...)` call that
    is provably confined to a single paragraph's body AND rewritable in
    place. Returns fewer entries than the program has calls whenever any
    of them fails either test -- the caller treats that as "classify
    nothing" and refuses the whole program, so a partial result can never
    waive an occurrence on its own."""
    classified: list[ParagraphScopedRefusal] = []
    for line_no, text in enumerate(lines, start=1):
        for hit in _DFHRESP_MACRO_RE.finditer(text):
            call = _CICS_MACRO_CALL_RE.match(text, hit.start())
            if call is None:
                continue
            owner = _paragraph_owning_line(
                program, line_no, lines, label_scan_to_line=True
            )
            if owner is None:
                continue
            start, end = call.start(), call.end()
            if end - start < len(CICS_MACRO_PLACEHOLDER):
                continue
            classified.append(
                ParagraphScopedRefusal(
                    paragraph_name=owner,
                    reason=RefusalReason(
                        code="UNSUPPORTED_CICS_MACRO",
                        message=(
                            f"CICS macro call {call.group(0)!r} at line "
                            f"{line_no} (inside paragraph '{owner}', which a "
                            f"selected test case can execute) -- DFHRESP/"
                            f"DFHVALUE are CICS-translator macro-functions "
                            f"(DFHRESP(NORMAL) expands to a literal response "
                            f"code from a large, translator-version-sensitive "
                            f"condition table) that mockymock cannot safely "
                            f"expand without a real CICS translator, so a test "
                            f"case whose execution can reach this code is not "
                            f"supported"
                        ),
                    ),
                    waiver_note=(
                        f"CICS macro call {call.group(0)!r} at line {line_no} "
                        f"waived: it is confined to paragraph '{owner}', which "
                        f"no selected test case can execute -- rewriting it to "
                        f"{CICS_MACRO_PLACEHOLDER} (space-padded to the same "
                        f"width, so no line or column moves) in the "
                        f"instrumented source, since GnuCOBOL has no CICS "
                        f"translator and could not compile the unexpanded macro"
                    ),
                    neutralize_span=(line_no, start, end),
                )
            )
    return classified


def check_test_case(
    surface: MockSurface,
    program,
    case: MockTestCase,
    file_status_fields: dict[str, str] | None = None,
    neutralized_goto: frozenset[str] | set[str] = frozenset(),
) -> list[RefusalReason]:
    """`neutralized_goto` must be `neutralized_goto_targets(...)` computed
    over the same (program, scope_map, lines) the splicer will use --
    passing it makes this gate's reachable set agree with the program
    that actually compiles (each covered GO TO becomes EXIT PARAGRAPH,
    so its exit-label target no longer cascades fall-through
    reachability). Callers without a scope map (or predicting a run that
    will not splice) leave the default: an empty set is strictly more
    conservative -- at worst extra UNMOCKED_* refusals, never a silently
    executing unmocked boundary."""
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
        neutralized_goto=neutralized_goto,
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
                # Only a mixed-form SORT/MERGE reaches this branch now
                # (category=None): plain-file-form is mockable
                # (MockCategory.SORT/MERGE), and a pure-procedure-form
                # SORT is left real/unspliced and never even recorded as
                # a boundary site -- see mock_surface.py's
                # `_is_plain_sort_merge`/`_is_pure_procedure_sort`.
                reasons.append(
                    RefusalReason(
                        code="UNSUPPORTED_SORT_MERGE",
                        message=(
                            f"paragraph '{site.paragraph_name}' (line {site.line}) "
                            f"contains a SORT/MERGE statement mixing a "
                            f"USING/GIVING file with an INPUT/OUTPUT "
                            f"PROCEDURE on the other side -- that shape "
                            f"touches a physical file mockymock cannot "
                            f"seed/read and runs a procedure whose other "
                            f"logic a whole-statement mock would silently "
                            f"skip, so it stays unsupported (a plain `SORT "
                            f"... USING ... GIVING ...`/`MERGE ... USING "
                            f"... GIVING ...` with no procedure clause is "
                            f"mockable via MOCK SORT/MOCK MERGE; a pure "
                            f"`INPUT PROCEDURE ... OUTPUT PROCEDURE ...` "
                            f"SORT with no USING/GIVING at all is left "
                            f"real, with its RELEASE/RETURN independently "
                            f"mockable via MOCK RELEASE/MOCK RETURN)"
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

    # Whole-program, NOT reachability-filtered -- same reasoning as
    # check_nested_exec's NESTED_EXEC/UNSPLICEABLE_EXEC (see .okf/
    # analysis.md, "Why NESTED_EXEC is whole-program, not per-case"):
    # orchestrator.splice_program iterates every BoundarySite in
    # surface.boundary_sites and splices any one that `directive_matches_
    # site` matches for ANY directive of ANY case -- pure category/key
    # (or normalized-text) matching, deliberately blind to which case's
    # control flow reaches which physical site, and not narrowed by
    # mocked_flow_names either (splice_program does not skip boundary
    # sites inside a flow-mocked paragraph's body -- see [splicer] Flow-
    # Mock Header Dispatch: body lines never move). build_site_dispatch
    # then re-derives AMBIGUOUS_MOCK itself (raising ValueError when 2+ of
    # THIS case's directives match one physical site), and orchestrator's
    # own defensive checks re-derive UNSUPPORTED_NESTED_MOCK_TARGET /
    # UNSUPPORTED_MOCK_TARGET_LAYOUT the same way -- all three against
    # surface.boundary_sites unfiltered. So the site set this gate checks
    # against this case's mocks must be a true superset of what the
    # splicer will actually process for it: every matching site program-
    # wide, not just the ones reachable from this case's own PERFORM
    # target. Sites already visited by the reachable-set loop above are
    # skipped here -- they were already reported with a precise
    # "reachable from ..." message, and re-checking them would double-
    # refuse the same physical site.
    already_checked_ids = {
        id(site.statement) for site in surface.sites_in(reachable - mocked_flow_names)
    }
    for site in surface.boundary_sites:
        if site.category is None or id(site.statement) in already_checked_ids:
            continue
        matches = [d for d in case.mocks if directive_matches_site(d, site)]
        if not matches:
            continue
        if len(matches) > 1:
            described = ", ".join(d.describe() for d in matches)
            reasons.append(
                RefusalReason(
                    code="AMBIGUOUS_MOCK",
                    message=(
                        f"{site.label} boundary at line {site.line} (paragraph "
                        f"'{site.paragraph_name}') is not reachable from "
                        f"'{case.perform_target}' but is matched by more than "
                        f"one of this test case's own MOCK directives "
                        f"({described}) -- the splicer matches directives to "
                        f"sites program-wide, independent of reachability, so "
                        f"this is refused too; make the keys unambiguous"
                    ),
                )
            )
        elif site.nested and site.span is None:
            reasons.append(
                RefusalReason(
                    code="UNSUPPORTED_NESTED_MOCK_TARGET",
                    message=(
                        f"MOCK {matches[0].describe()} matches a statement at "
                        f"line {site.line} that is not reachable from "
                        f"'{case.perform_target}' but is nested elsewhere in "
                        f"the program inside a conditional/loop body "
                        f"(IF/EVALUATE/inline PERFORM) that cannot be safely "
                        f"spliced: {site.unspliceable_reason or _UNANNOTATED}"
                    ),
                )
            )
        elif not site.nested and site.unspliceable_reason:
            reasons.append(
                RefusalReason(
                    code="UNSUPPORTED_MOCK_TARGET_LAYOUT",
                    message=(
                        f"MOCK {matches[0].describe()} matches a top-level "
                        f"statement at line {site.line} (paragraph "
                        f"'{site.paragraph_name}') that is not reachable from "
                        f"'{case.perform_target}' but {site.unspliceable_reason}"
                        f" elsewhere in the program -- splicing it would "
                        f"comment out the sibling code sharing its line(s); "
                        f"put the statement on its own line(s)"
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
        # RETURN joins READ here (2026-08-17, SORT/MERGE mocking): RETURN
        # is never in FILE_STATUS_CATEGORIES at all (see dsl/model.py), so
        # `missing_status_field` is unconditionally True for it -- a MOCK
        # RETURN ... ROWS with no TERMINAL group ALWAYS refuses, not just
        # when the SD happens to lack a FILE STATUS field.
        elif (
            directive.category in (MockCategory.READ, MockCategory.RETURN)
            and directive.rows is not None
            and directive.terminal_row is None
            and missing_status_field
        ):
            reasons.append(
                RefusalReason(
                    code="UNRESOLVED_FILE_STATUS_TARGET",
                    message=(
                        f"MOCK {directive.category.keyword} {directive.key} "
                        f"ROWS has no way to signal end-of-data: the file "
                        f"declares no FILE STATUS field and the mock has "
                        f"no TERMINAL ( ... ) group -- add one or the "
                        f"{directive.category.keyword.lower()} loop cannot "
                        f"terminate"
                    ),
                )
            )

    # Whole-program, NOT reachability-filtered -- same reasoning as
    # check_nested_exec's NESTED_EXEC/UNSPLICEABLE_EXEC (see .okf/
    # analysis.md, "Why NESTED_EXEC is whole-program, not per-case"):
    # splice_program iterates every BoundarySite in the program and splices
    # any one that `directive_matches_site` matches for ANY directive of ANY
    # case -- pure category+key matching, deliberately blind to which case's
    # control flow reaches which physical site, so that one directive can
    # cover several physical sites sharing a key. build_site_dispatch then
    # emits this directive's CAPTURE MOVEs into that site's dispatch block
    # (and raises ValueError when the index exceeds its USING count). So the
    # site set checked here must be a superset of what the splicer will
    # actually process for this directive: every matching site program-wide,
    # not just the ones reachable from this directive's own owning case.
    # Each directive belongs to exactly one case's `case.mocks`, so this
    # still reports each out-of-range capture exactly once per suite.
    for directive in case.mocks:
        if not directive.captures:
            continue
        matching_sites = [
            s for s in surface.boundary_sites if directive_matches_site(directive, s)
        ]
        for index, target in directive.captures:
            for site in matching_sites:
                if not isinstance(site.statement, CallStatement):
                    continue
                arg_count = len(site.statement.using_parameters)
                if index > arg_count:
                    reasons.append(
                        RefusalReason(
                            code="CAPTURE_ARG_OUT_OF_RANGE",
                            message=(
                                f"MOCK {directive.describe()} CAPTURE ARG "
                                f"{index} INTO {target} -- the CALL at "
                                f"line {site.line} (paragraph "
                                f"'{site.paragraph_name}') only declares "
                                f"{arg_count} USING parameter"
                                f"{'s' if arg_count != 1 else ''}"
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


def _find_sort_merge_statements(statements: list) -> list:
    """Recursively collect every SortStatement/MergeStatement in
    `statements`, same traversal as `_find_flow_statements`. A
    SORT/MERGE's INPUT/OUTPUT PROCEDURE names are an implicit PERFORM
    edge the reachability BFS must follow even though the AST node isn't
    a PerformStatement -- otherwise a RELEASE/RETURN (or any other
    boundary statement) reachable only through one of those paragraphs is
    invisible to the fail-closed gate, the same hazard class the GO TO
    fall-through / PERFORM-section / SEARCH-WHEN reachability fixes
    closed for other constructs (see the module docstring's "2026-07-07
    reachability-hole remediation" and .okf/analysis.md)."""
    return _find_statements_of_type(statements, (SortStatement, MergeStatement))


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
    neutralized_goto: frozenset[str] | set[str] = frozenset(),
) -> tuple[set[str], list[RefusalReason]]:
    """Return (reachable paragraph/section names, flow refusals), computed
    in a single BFS pass over PerformStatement and GoStatement edges, plus
    the implicit PERFORM edge a SORT/MERGE's INPUT PROCEDURE/OUTPUT
    PROCEDURE names represent (2026-08-17, SORT/MERGE mocking) -- see
    `_find_sort_merge_statements`.

    `skip_traversal` holds paragraph/section names mocked as flow targets
    (MOCK PARAGRAPH/SECTION) by the test case under analysis: a name in it
    is still recorded as reached (so the directive counts as matched and
    UNKNOWN_PARAGRAPH still works), but its body is never traversed -- no
    statements walked, no section members expanded -- because the mock
    dispatch replaces that body for this case, making everything inside it
    (boundary statements, terminators, further PERFORM/GO TO edges)
    unreachable. Callers that feed the result to `MockSurface.sites_in`
    must subtract these names first.

    The BFS additionally closes over the GO TO fall-through hazard
    (2026-08-12 bug review): a reached GO TO target whose body does not
    provably divert control (`_falls_through`) continues -- by ordinary
    sequential execution, not a flow edge -- into the next paragraph in
    source order, which therefore executes real statements (boundary
    sites included) without any PERFORM/GO TO edge naming it. Before this
    closure, a CALL/file-op/ACCEPT in such a paragraph passed every gate
    unmocked and then executed for real at runtime. The closure is the
    same fixpoint `union_executed_paragraphs` already applies for
    warning-waiving, and it fails closed (refusal, never a silent skip)
    when source order is unverifiable or a GO TO target cannot be
    anchored in it.

    2026-08-26: the walk (`_walk_fallthrough_from`) no longer cascades
    past the LAST paragraph of a SECTION `_fallthrough_safe_sections`
    proves is entered only via `PERFORM <section-name>` anywhere in the
    program -- reaching that exact point is where GnuCOBOL's own implicit
    PERFORM return marker fires, regardless of whether it was reached by
    plain fall-through or by an internal GO TO. Without this, a program's
    "several paragraphs each `GO TO` a shared, section-scoped exit label"
    idiom -- the common multi-caller shape `find_goto_exit_plans`' own
    per-enclosing-paragraph adjacency check can't neutralize (see that
    function's docstring) -- made every paragraph physically after the
    section look hazardous, demanding mocks for boundaries the compiled
    program never actually reaches. `start`/`thru` (this call's OWN entry
    point) additionally exclude any section either one enters by naming a
    member paragraph directly, since that DSL-level bypass of `PERFORM
    <section-name>` is invisible to the whole-program AST scan
    `_fallthrough_safe_sections` runs -- see `_paragraph_safe_section_map`.
    This only ever SHRINKS the reachable set (declines to add paragraphs
    fall-through would have added before), so it can only reduce refusals,
    never a soundness regression on its own -- and never changes what
    `find_goto_exit_plans`/`find_terminator_plans` actually splice, since
    neither reads this function's narrowed fall-through map.

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
    driver-side target into UNKNOWN_PARAGRAPH.)

    `neutralized_goto` holds exit-only paragraph names every GO TO of
    which is covered by a GotoExitPlan (`neutralized_goto_targets`) --
    the splicer replaces each of those GO TOs with EXIT PARAGRAPH at its
    own call site, so in the program that actually compiles and runs,
    control NEVER transfers to such a paragraph via GO TO. Two effects,
    mirroring the narrowing find_terminator_plans already applied to its
    own hazard sets (2026-08-25): a single-target unconditional GO TO
    naming a neutralized paragraph is not a flow edge (its target is not
    pushed), and the neutralized names are subtracted from the GO TO
    fall-through closure's seed set -- which is what stops the
    "GO TO <own-exit-label>" idiom's bare-EXIT landing pad from
    cascading the walk through the entire rest of the program. Sound
    only because find_goto_exit_plans is all-or-nothing per target and
    disqualifies any target also named by a computed/multi-target GO TO:
    a name in this set is therefore never reachable through any GO TO
    shape this walk would otherwise have to model. Callers that do not
    splice (or predict a run that will not splice) must leave it empty."""
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
    if thru is not None:
        if start in section_members or thru in section_members:
            # 2026-08-12 audit Finding 2: this seed used to be guarded by
            # `start in by_name` alone -- built from paragraphs only -- so
            # a section-named start silently skipped both the expansion
            # AND its fail-closed refusal, dropping `thru` entirely while
            # the spliced driver still emits the literal PERFORM ... THRU
            # (GnuCOBOL executes the full fall-through range). Refuse loud
            # instead of modeling less than the compiled driver runs.
            reasons.append(
                RefusalReason(
                    code="UNSUPPORTED_PERFORM_THRU",
                    message=(
                        f"test case PERFORM: PERFORM {start} THRU {thru} "
                        f"names a SECTION as a range endpoint -- THRU "
                        f"range expansion is only modeled over paragraphs, "
                        f"so the reachable set cannot be trusted; PERFORM "
                        f"the section without THRU, or name the range's "
                        f"boundary paragraphs directly"
                    ),
                )
            )
        elif start in by_name:
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
        # else: the seed itself is unresolvable -- check_test_case reports
        # it as UNKNOWN_PARAGRAPH and returns before reading thru_reasons.

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
    go_to_targets = _go_to_targets(program) - set(neutralized_goto)
    index_by_name = (
        {p.paragraph_name: i for i, p in enumerate(ordered)} if ordered else {}
    )
    # Computed once, not per walk: the closure below is a fixpoint loop
    # over every reached GO TO target. See `_fallthrough_flags`.
    falls = _fallthrough_flags(ordered) if ordered else []
    # This call's own entry point(s): a section otherwise safe for the GO
    # TO fall-through closure below is excluded whenever `start`/`thru`
    # name one of its member paragraphs directly, bypassing `PERFORM
    # <section-name>` -- see _paragraph_safe_section_map's docstring.
    paragraph_safe_section = _paragraph_safe_section_map(
        section_members,
        _fallthrough_safe_sections(program),
        {start} | ({thru} if thru else set()),
    )
    while True:
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
                # else: only the driver-side seed can be unresolved here
                # (every in-program edge was resolvability-checked before
                # pushing); check_test_case reports it as UNKNOWN_PARAGRAPH.
                continue
            seen.add(name)
            for statement in _find_flow_statements(by_name[name].statements):
                if isinstance(statement, GoStatement):
                    single_target = _go_statement_target(statement)
                    if single_target is not None and single_target in neutralized_goto:
                        # Covered by a GotoExitPlan: the splicer replaces
                        # this exact GO TO with EXIT PARAGRAPH, so it is
                        # not a flow edge in the program that runs. (A
                        # computed/multi-target GO TO can never name a
                        # neutralized paragraph -- its mere existence
                        # disqualifies the target in find_goto_exit_plans.)
                        continue
                    targets = list(statement.target_paragraphs)
                    if not targets and statement.target_paragraph:
                        targets = [statement.target_paragraph]
                    if not targets:
                        reasons.append(
                            RefusalReason(
                                code="UNRESOLVED_FLOW_TARGET",
                                message=(
                                    f"paragraph '{name}' (line "
                                    f"{statement.location.line}) contains a "
                                    f"GO TO whose target(s) the parser did "
                                    f"not capture -- fail closed"
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

            # A SORT/MERGE's INPUT PROCEDURE/OUTPUT PROCEDURE names an
            # implicit PERFORM edge no PerformStatement AST node
            # represents -- modeled unconditionally for any SORT/MERGE
            # with a procedure clause (both the now-mockable pure form
            # and the still-refused mixed form), so a RELEASE/RETURN
            # reachable only through one is never invisible to the gate.
            for statement in _find_sort_merge_statements(by_name[name].statements):
                for procedure_attr, thru_attr in (
                    ("input_procedure", "input_procedure_thru"),
                    ("output_procedure", "output_procedure_thru"),
                ):
                    procedure_target = getattr(statement, procedure_attr, None)
                    if procedure_target is None:
                        continue
                    push_target(procedure_target, name, statement.statement_type)
                    procedure_thru = getattr(statement, thru_attr, None)
                    if procedure_thru:
                        members, problem = _expand_thru_range(
                            ordered,
                            procedure_target,
                            procedure_thru,
                            f"paragraph '{name}'",
                        )
                        if problem is not None:
                            reasons.append(problem)
                        stack.extend(members)

        # GO TO fall-through closure (see docstring): every reached GO TO
        # target is walked forward through source order via _falls_through
        # -- the same conservative predicate _go_to_fallthrough_targets and
        # union_executed_paragraphs use -- and each paragraph reachable by
        # falling off one's end is fed back into the BFS, to a fixpoint.
        # `seen & go_to_targets` over-approximates (a paragraph both
        # PERFORMed here and GO-TO'd elsewhere still triggers the walk),
        # which is the fail-closed direction: at worst an extra required
        # mock, never a silently executing unmocked boundary.
        hazard_sources = seen & go_to_targets
        if not hazard_sources:
            break
        if ordered is None:
            reasons.append(
                RefusalReason(
                    code="UNRESOLVED_FLOW_TARGET",
                    message=(
                        "paragraph source order could not be verified, so "
                        "the GO TO fall-through walk cannot run -- the "
                        "reachable set cannot be trusted"
                    ),
                )
            )
            break
        anchor_failed = False
        additions: list[str] = []
        for name in sorted(hazard_sources):
            reached = _walk_fallthrough_from(
                name,
                ordered,
                index_by_name,
                section_members,
                paragraph_safe_section,
                falls=falls,
            )
            if reached is None:
                # A GO TO target the walk cannot anchor (e.g. an empty
                # section): the closure is incomplete, fail closed.
                reasons.append(
                    RefusalReason(
                        code="UNRESOLVED_FLOW_TARGET",
                        message=(
                            f"GO TO target '{name}' cannot be anchored in "
                            f"source order for the fall-through walk -- the "
                            f"reachable set cannot be trusted"
                        ),
                    )
                )
                anchor_failed = True
                continue
            for fallen in reached:
                if fallen not in seen and fallen not in additions:
                    additions.append(fallen)
        if anchor_failed or not additions:
            break
        stack.extend(additions)
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


def _fallthrough_flags(ordered: list) -> list[bool]:
    """`_falls_through` evaluated once per paragraph, in source order.

    Every fall-through walk in this module re-asked the same question
    about the same paragraph objects: `_go_to_fallthrough_targets` walks
    forward from EVERY GO TO target, and both fall-through closures run
    inside a fixpoint loop, so a program using the shared-exit-label
    idiom (where no paragraph on the chain provably diverts, so every
    walk runs to end of file) evaluated it O(targets x paragraphs) times
    -- measured as 4.4M calls, the single largest cost of the static
    check pass on a 53k-line program. The predicate depends only on the
    paragraph's own last statement, so one pass over `ordered` answers
    every walk."""
    return [_falls_through(paragraph) for paragraph in ordered]


def _first_non_fallthrough(falls: list[bool]) -> list[int | None]:
    """For each index, the smallest index at or after it whose paragraph
    does NOT fall through, or None when none does -- i.e. exactly where a
    forward fall-through walk starting there stops. One backward pass,
    so a walk costs only the paragraphs it actually reports."""
    stops: list[int | None] = [None] * len(falls)
    nxt: int | None = None
    for i in range(len(falls) - 1, -1, -1):
        if not falls[i]:
            nxt = i
        stops[i] = nxt
    return stops


def _fallthrough_safe_sections(program) -> set[str]:
    """SECTION names whose LAST paragraph a GO TO fall-through walk may
    treat as a hard stop (see `_walk_fallthrough_from`): reaching that
    exact physical point -- by ordinary fall-through from an earlier
    member, or by an internal GO TO landing anywhere within the section
    -- is where GnuCOBOL's own `PERFORM <section-name>` implicit return
    marker fires (the same address-based "own exit label" mechanism this
    module already relies on elsewhere for a single paragraph's own
    trailing EXIT landing pad), so modeling fall-through as continuing
    PAST it into whatever source text physically follows is wrong --
    exactly the false cascade that made every paragraph after a
    program's "GO TO <shared-validation-exit-label>" idiom look
    hazardous, all the way to the end of the file (2026-08-26 fix: this
    idiom -- several paragraphs each doing `GO TO <shared-exit>` as an
    early bailout -- was already the whole reason `find_goto_exit_plans`
    exists, but that function's own adjacency precondition only ever
    matches ONE of the several enclosing paragraphs, so its all-or-
    nothing neutralization declines the target and every case that ever
    reaches it inherits the full un-neutralized cascade; this closes the
    gate side of that gap without touching what `find_goto_exit_plans`
    splices).

    Deliberately STRICTER than `_safe_section_entry_points` (which only
    proves the section's FIRST paragraph has no other entry point
    anywhere in the program): here EVERY member paragraph must be
    provably unreachable except from within the section itself -- never
    a GO TO target from OUTSIDE it, never named by a PERFORM (plain,
    THRU endpoint, or conditional/looping, at any nesting depth) from
    OUTSIDE it. A GO TO/PERFORM from ONE member to ANOTHER member of the
    SAME section does not disqualify anything -- that is precisely the
    "several validation paragraphs share one section-scoped exit label"
    idiom this fix exists for, and an internal helper PERFORM among a
    section's own paragraphs doesn't change how the section itself was
    entered. A section failing the outside-entry check for even one
    non-first member is exactly as unsafe for this optimization as one
    failing it for its first member: a `PERFORM <that-member>` reached
    from elsewhere would start executing mid-section, where the implicit
    return marker this optimization trusts is that OTHER PERFORM's own
    (much narrower) range, not this section's end -- continuing to treat
    the section's own end as a safe stop there would silently hide
    paragraphs that genuinely execute.

    Whole-program AST only: a `.cut` test case's own PERFORM target/thru
    (DSL content, not a COBOL statement) can still name a member
    paragraph directly and is invisible to this scan -- callers must
    additionally exclude a section whenever their own entry point(s) do
    that; see `_paragraph_safe_section_map`."""
    procedure = program.get_division("PROCEDURE")
    if procedure is None:
        return set()
    section_of: dict[str, str] = {}
    for section_name, section in getattr(procedure, "_sections", {}).items():
        if not section_name:
            continue
        for paragraph in section.paragraphs:
            section_of[paragraph.paragraph_name] = section_name

    external_go_to_targets: set[str] = set()
    external_performed_names: set[str] = set()
    for paragraph in _all_paragraphs(procedure):
        enclosing_section = section_of.get(paragraph.paragraph_name)
        for statement in _find_statements_of_type(
            paragraph.statements, PerformStatement
        ):
            for target in (statement.target_paragraph, statement.thru_paragraph):
                if target and section_of.get(target) != enclosing_section:
                    external_performed_names.add(target)
        for statement in _find_statements_of_type(paragraph.statements, GoStatement):
            targets = (
                list(statement.target_paragraphs) if statement.target_paragraphs else []
            )
            if not targets and statement.target_paragraph:
                targets = [statement.target_paragraph]
            for target in targets:
                if section_of.get(target) != enclosing_section:
                    external_go_to_targets.add(target)

    safe: set[str] = set()
    for section_name, section in getattr(procedure, "_sections", {}).items():
        if not section_name or not section.paragraphs:
            continue
        members = [p.paragraph_name for p in section.paragraphs]
        if section_name in external_go_to_targets:
            continue
        if any(member in external_go_to_targets for member in members):
            continue
        if any(member in external_performed_names for member in members):
            continue
        safe.add(section_name)
    return safe


def _paragraph_safe_section_map(
    section_members: dict[str, list[str]],
    safe_sections: set[str],
    exclude_seeds: frozenset[str] | set[str] = frozenset(),
) -> dict[str, str]:
    """member paragraph name -> owning SECTION name, for every member of
    a section in `safe_sections` (`_fallthrough_safe_sections`) -- EXCEPT
    a section that `exclude_seeds` (a caller's own PERFORM target/thru,
    or any other DSL-level entry point invisible to that whole-program
    scan) enters directly by naming one of its member paragraphs instead
    of the section itself: that bypasses the `PERFORM <section-name>`
    return-marker guarantee the optimization depends on, so the section
    is excluded entirely for this caller rather than risk hiding
    paragraphs that genuinely execute from mid-section onward."""
    excluded = {
        section
        for section, members in section_members.items()
        if section in safe_sections and any(seed in members for seed in exclude_seeds)
    }
    return {
        member: section
        for section, members in section_members.items()
        if section in safe_sections and section not in excluded
        for member in members
    }


def _walk_fallthrough_from(
    name: str,
    ordered: list,
    index_by_name: dict[str, int],
    section_members: dict[str, list[str]],
    paragraph_safe_section: dict[str, str],
    falls: list[bool] | None = None,
) -> list[str] | None:
    """Every paragraph name reached, in source order, by walking forward
    from GO-TO-target `name` (a paragraph or section name) via
    `_falls_through` -- the shared walk `_reachable_paragraphs` and
    `union_executed_paragraphs` both apply (see module docstring: a
    paragraph reached this way carries the exact same EXIT PARAGRAPH
    hazard as one directly named by a GO TO). `name` unanchorable in
    `index_by_name`/`section_members` (e.g. an empty section) returns
    None -- callers must fail closed on that, same as before this helper
    existed.

    Stops at the first paragraph whose own last statement provably
    diverts control away (`_falls_through`), or -- the instant it would
    cross past -- the LAST paragraph of a SECTION `name` resolves into
    per `paragraph_safe_section` (see `_fallthrough_safe_sections`/
    `_paragraph_safe_section_map` for the soundness conditions that map
    already enforces).

    `falls` is `_fallthrough_flags(ordered)`; callers that walk repeatedly
    (both of this function's own call sites run inside a fixpoint loop)
    should compute it once and pass it in rather than pay for it per
    walk. Omitting it is equivalent, just slower."""
    if falls is None:
        falls = _fallthrough_flags(ordered)
    start = index_by_name.get(name)
    anchor_name = name
    if start is None:
        members = section_members.get(name)
        if not members:
            return None
        start = index_by_name.get(members[0])
        if start is None:
            return None
        anchor_name = members[0]
    origin_section = paragraph_safe_section.get(anchor_name)
    stop_before = None
    if origin_section is not None:
        section_paragraphs = section_members.get(origin_section)
        if section_paragraphs:
            stop_before = section_paragraphs[-1]
    reached: list[str] = []
    cursor = start
    while falls[cursor] and cursor + 1 < len(ordered):
        if stop_before is not None and ordered[cursor].paragraph_name == stop_before:
            break
        cursor += 1
        reached.append(ordered[cursor].paragraph_name)
    return reached


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

    falls = _fallthrough_flags(ordered)
    stops = _first_non_fallthrough(falls)
    last = len(ordered) - 1

    hazard: dict[str, str] = {}
    # Indices already recorded by an earlier walk. Two walks that both pass
    # through index k necessarily stop at the same index: the stop is
    # `stops[start]`, and there is no non-fall-through paragraph strictly
    # between two starts that both reach k. So hitting an already-recorded
    # index means the whole rest of this walk is already recorded too, and
    # the remaining `setdefault` calls would every one be a no-op -- which
    # is what lets the walk break there and keeps the total linear rather
    # than O(targets x paragraphs). Same keys, same first-writer-wins
    # values as the unconditional walk it replaces.
    recorded: set[int] = set()
    for name in go_to_targets:
        start = index_by_name.get(name)
        if start is None:
            members = section_members.get(name)
            if not members:
                continue
            start = index_by_name.get(members[0])
            if start is None:
                continue
        stop = stops[start]
        end = last if stop is None else stop
        for cursor in range(start + 1, end + 1):
            if cursor in recorded:
                break
            recorded.add(cursor)
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


def _is_exit_only_paragraph(paragraph) -> bool:
    """True when `paragraph`'s entire body is one bare EXIT statement --
    an ExitStatement whose exit_type is none of PARAGRAPH/SECTION/PROGRAM,
    the same no-op-placeholder shape _falls_through's docstring already
    names (`MAIN-EXIT. EXIT.`, the idiomatic mainframe early-exit landing
    pad .okf/analysis.md calls out by name). Deliberately does NOT accept
    an empty (zero-statement) body -- narrower, harder-to-misclassify
    shape chosen deliberately for v1; see
    docs/2026-08-17-goto-exit-paragraph-simplification-design.md's "What
    counts as an exit-only paragraph"."""
    statements = paragraph.statements
    if len(statements) != 1:
        return False
    statement = statements[0]
    return isinstance(statement, ExitStatement) and statement.exit_type not in (
        "PARAGRAPH",
        "SECTION",
        "PROGRAM",
    )


def _go_statements_with_nesting(
    statements: list, nested: bool = False, in_boundary: bool = False
) -> list[tuple[GoStatement, bool, bool]]:
    """Recursively collect every GoStatement in `statements`, tagged with
    `nested` (False only for a direct top-level member of the paragraph's
    own .statements list) and `in_boundary` (sticky -- True once recursion
    has entered another boundary statement's clause body) -- the exact
    same propagation `_plain_perform_statements` applies to PerformStatement
    and `mock_surface._walk_statements` applies to boundary sites. Needed
    because a top-level GO TO's replacement span comes from
    `statement_span` (correct only when nothing between it and the next
    top-level statement has its own scope terminator), while a nested GO
    TO (inside an IF/EVALUATE branch) needs the validated
    `nested_statement_span` instead -- see that function's docstring for
    the bug this distinction exists to avoid."""
    found: list[tuple[GoStatement, bool, bool]] = []
    for statement in statements:
        if isinstance(statement, GoStatement):
            found.append((statement, nested, in_boundary))
        child_in_boundary = in_boundary or isinstance(
            statement, _BOUNDARY_STATEMENT_TYPES
        )
        for nested_list in _nested_statement_lists(statement):
            found.extend(
                _go_statements_with_nesting(
                    nested_list, nested=True, in_boundary=child_in_boundary
                )
            )
    return found


def _go_statement_target(statement: GoStatement) -> str | None:
    """The single, unconditional target name of `statement`, or None when
    it is computed (`depending_on_variable` is not None) or names more
    than one paragraph -- both excluded because neither resolves to
    "always this one paragraph," which GO-TO-to-EXIT-PARAGRAPH splicing
    requires. Mirrors `_reachable_paragraphs`' own target-list handling
    (`target_paragraphs` first, falling back to the singular
    `target_paragraph`)."""
    if statement.depending_on_variable is not None:
        return None
    targets = list(statement.target_paragraphs) if statement.target_paragraphs else []
    if not targets and statement.target_paragraph:
        targets = [statement.target_paragraph]
    if len(targets) != 1:
        return None
    return targets[0]


def _go_statement_raw_targets(statement: GoStatement) -> list[str]:
    """Every name `statement` could possibly transfer control to,
    regardless of whether `_go_statement_target` can resolve it to one
    safe target -- used only to find every paragraph a computed or
    multi-target GO TO could ever land on, for disqualification. Same
    `target_paragraphs`-first-fallback-to-`target_paragraph` shape
    `_go_statement_target`/`_reachable_paragraphs`/`_go_to_targets` all
    use, deliberately not routed through one shared helper here since
    this one intentionally ignores `depending_on_variable`."""
    targets = list(statement.target_paragraphs) if statement.target_paragraphs else []
    if not targets and statement.target_paragraph:
        targets = [statement.target_paragraph]
    return targets


def find_goto_exit_plans(
    program, scope_map, lines: list[str]
) -> tuple[list[GotoExitPlan], list[str]]:
    """Whole-program, unconditional on any test case -- like NESTED_EXEC's
    reasoning, but "plan or silently skip" rather than "plan or refusal":
    declining this optimization is always safe, the program compiles and
    runs exactly as it does today, so an ineligible candidate is reported
    as an informational note, never a RefusalReason that would block the
    run. See
    docs/2026-08-17-goto-exit-paragraph-simplification-design.md.
    STATUS: implemented, not yet verified against real GnuCOBOL.

    Consumers beyond the splicer itself go through
    `neutralized_goto_targets` (the fully-neutralized target names):
    `find_terminator_plans`' hazard-set narrowing, and -- since
    2026-08-25 -- `check_test_case`/`_reachable_paragraphs`' reachable
    set, so the mock gates stop demanding mocks for the fall-through
    cascade a spliced-away GO TO can no longer trigger. Any soundness
    condition added or relaxed here therefore changes what those gates
    waive, not just what the splicer rewrites.

    A GO TO qualifies only when ALL of:
    - it names a single, unconditional target (`_go_statement_target`)
      that is an exit-only paragraph (`_is_exit_only_paragraph`);
    - no OTHER GoStatement anywhere in the program -- including a
      computed or multi-target one `_go_statement_target` can't resolve
      -- could ALSO land on that same paragraph (`_go_statement_raw_
      targets`): a computed `GO TO` naming the exit-only paragraph as one
      of several possible targets is invisible to the per-site checks
      below but is exactly as much of a real `GO TO` edge into it as the
      resolvable one, so its mere existence disqualifies the whole
      target;
    - a validated replacement span exists for the statement
      (`statement_top_level_problem`/`statement_span` for a top-level GO
      TO, `nested_statement_span` for one nested inside an
      IF/EVALUATE branch -- see that function's docstring for the bug
      this distinction exists to avoid) and it is not nested inside
      another boundary statement's own clause body;
    - its enclosing paragraph is itself safe to issue `EXIT PARAGRAPH`
      from -- top-level (`top_level_names`), not in `_go_to_targets`, not
      in `_go_to_fallthrough_targets` (the same preconditions
      `find_terminator_plans` enforces on a terminator's own paragraph);
    - the exit-only paragraph is the IMMEDIATE NEXT paragraph after the
      enclosing paragraph in source order, with nothing else between them
      (`_source_ordered_paragraphs`) other than a phantom "." paragraph --
      cobolparser's empty-artifact node for a bare "." line sitting before
      the next paragraph's header, tolerated the same way `_expand_thru_range`
      already tolerates it elsewhere in this file (`immediately_follows`).
      This is the one THRU-elision-safe shape the design doc describes:
      without it, a `PERFORM ... THRU <exit-paragraph>` range (declared by a
      `.cut` test, OR written in-program) covering real intermediate
      paragraphs would have its early-exit semantics silently changed by
      this splice -- the original `GO TO` skips those paragraphs entirely,
      but `EXIT PARAGRAPH` only ends the enclosing paragraph, so the THRU
      range's own fall-through would then run them on the early-exit path
      where it never did before. Confirmed empirically against this exact
      shape before this check existed (see the PR review that added it).

    SECTION-scoped enclosing paragraphs are NOT supported (unlike
    `find_terminator_plans`, which handles the one narrow safe-section-
    entry shape via `EXIT SECTION`): both a cleanup paragraph following
    the exit-only paragraph inside the same section (which `EXIT SECTION`
    would skip, where the original fall-through ran it) and
    `find_terminator_plans`' own "shape 3" gap (a `.cut` test's
    `perform_target` naming the section's first paragraph directly,
    bypassing `PERFORM <section-name>` -- a shape that function itself
    treats as unverified) would need suite-case context this whole-
    program function does not have. Deferred rather than half-solved;
    an enclosing paragraph that is a SECTION member is declined with a
    note, exactly like any other non-top-level enclosing paragraph.

    All-or-nothing per target paragraph: `_go_to_targets`/
    `_go_to_fallthrough_targets` are whole-program properties, so
    neutralizing some but not all GO TOs naming one exit-only paragraph
    would leave that paragraph exactly as hazardous as before. If every
    GO TO naming a given exit-only paragraph qualifies, all are
    neutralized together; if even one fails (including a computed/multi-
    target GO TO that merely NAMES it, never itself a "site"), none of
    that paragraph's GO TOs are touched and a note explains why.

    `_safe_section_entry_points`'s own internal `_go_to_targets` check is
    deliberately NOT narrowed by any OTHER goto-exit plan already found --
    composing two neutralizations to unlock a section entry is real
    additional complexity with no corpus example needing it; at worst
    this costs an extra declined optimization, never unsoundness.

    The fixpoint loop below is a narrower, unrelated thing: it re-narrows
    THIS function's own `_go_to_targets`/`_go_to_fallthrough_targets` by
    targets THIS function has already confirmed, within a single call --
    it never touches `_safe_section_entry_points`. Back-to-back
    validation-style paragraphs (`2211-VALIDER-MNT` /
    `2211-EXIT`, immediately followed by `2212-VALIDER-...` / `2212-EXIT`,
    and so on) chain: neutralizing `2211-EXIT` drops it out of
    `_go_to_targets`, which is exactly what un-marks `2212-VALIDER-...` as
    a `_go_to_fallthrough_targets` hazard (it was only hazardous because
    `2211-EXIT`, a bare-EXIT paragraph, falls through into it) -- which is
    what lets `2212-EXIT` neutralize in turn, and so on transitively
    through however many such paragraphs sit back-to-back. A single static
    pass over the RAW, whole-program `_go_to_targets`/
    `_go_to_fallthrough_targets` sees every paragraph on that chain as
    hazardous from the very first paragraph's still-live GO TO and
    declines the entire chain at once. So this evaluates every candidate
    target repeatedly, each round narrowing `_go_to_targets` (and, through
    it, `_go_to_fallthrough_targets`) by every target CONFIRMED in an
    EARLIER round -- mirroring the narrowing `find_terminator_plans` and
    `_reachable_paragraphs` already apply using this function's own FINAL
    output -- until a round confirms nothing new. Monotonic and therefore
    terminates: confirmed targets are never revisited, and each round
    either confirms at least one new target or the loop stops."""
    procedure = program.get_division("PROCEDURE")
    if procedure is None:
        return [], []

    paragraphs = _all_paragraphs(procedure)
    exit_only_names = {
        p.paragraph_name for p in paragraphs if _is_exit_only_paragraph(p)
    }
    if not exit_only_names:
        return [], []

    top_level_names = {p.paragraph_name for p in procedure.paragraphs}
    base_go_to_targets = _go_to_targets(program)
    boundaries = collect_boundaries(program)
    last_line = len(lines)
    ordered = _source_ordered_paragraphs(procedure) or []
    index_by_name = {p.paragraph_name: i for i, p in enumerate(ordered)}

    def immediately_follows(enclosing_name: str, target_name: str) -> bool:
        enclosing_idx = index_by_name.get(enclosing_name)
        target_idx = index_by_name.get(target_name)
        if enclosing_idx is None or target_idx is None:
            return False
        if target_idx <= enclosing_idx:
            return False
        # A phantom "." paragraph (cobolparser's empty-artifact node for a
        # bare "." line sitting before the next paragraph's header) is not
        # real code standing between enclosing and target -- it rides along
        # the same way _expand_thru_range already tolerates it elsewhere in
        # this file, rather than disqualifying an otherwise textually
        # adjacent exit-only paragraph.
        return all(
            ordered[i].paragraph_name == "."
            for i in range(enclosing_idx + 1, target_idx)
        )

    by_target: dict[str, list[tuple[GoStatement, str, bool, bool]]] = {}
    disqualified_by_computed_goto: set[str] = set()
    for paragraph in paragraphs:
        for statement, nested, in_boundary in _go_statements_with_nesting(
            paragraph.statements
        ):
            target = _go_statement_target(statement)
            if target is not None and target in exit_only_names:
                by_target.setdefault(target, []).append(
                    (statement, paragraph.paragraph_name, nested, in_boundary)
                )
                continue
            if target is None:
                # A computed or multi-target GO TO: every name it could
                # possibly reach is a standing GO TO edge into that
                # paragraph, regardless of whether this per-site loop
                # can ever resolve it to a single safe target.
                disqualified_by_computed_goto.update(
                    name
                    for name in _go_statement_raw_targets(statement)
                    if name in exit_only_names
                )

    plans: list[GotoExitPlan] = []
    notes: list[str] = []
    for target_name in sorted(disqualified_by_computed_goto & by_target.keys()):
        sites = by_target.pop(target_name)
        notes.append(
            f"GO TO {target_name} left as-is at {len(sites)} site(s) -- "
            f"also named by a computed or multi-target GO TO elsewhere in "
            f"the program, which cannot be safely excluded on a per-site "
            f"basis"
        )

    confirmed: set[str] = set()
    remaining = dict(by_target)
    last_problems: dict[str, list[str]] = {}
    while remaining:
        go_to_targets = base_go_to_targets - confirmed
        go_to_fallthrough = _go_to_fallthrough_targets(program, go_to_targets)
        newly_confirmed: list[str] = []

        for target_name, sites in sorted(remaining.items()):
            problems: list[str] = []
            computed: list[tuple[GoStatement, str, str, tuple[int, int]]] = []
            for statement, enclosing, nested, in_boundary in sites:
                if enclosing in go_to_targets:
                    problems.append(
                        f"line {statement.location.line}: enclosing paragraph "
                        f"'{enclosing}' is itself a GO TO target elsewhere in "
                        f"the program"
                    )
                    continue
                if enclosing in go_to_fallthrough:
                    problems.append(
                        f"line {statement.location.line}: enclosing paragraph "
                        f"'{enclosing}' is reached only by falling through "
                        f"past a GO TO target elsewhere in the program"
                    )
                    continue
                if enclosing not in top_level_names:
                    problems.append(
                        f"line {statement.location.line}: enclosing paragraph "
                        f"'{enclosing}' belongs to a SECTION -- SECTION-scoped "
                        f"enclosing paragraphs are not yet supported"
                    )
                    continue
                if not immediately_follows(enclosing, target_name):
                    problems.append(
                        f"line {statement.location.line}: '{target_name}' is "
                        f"not the paragraph immediately following enclosing "
                        f"paragraph '{enclosing}' in source order -- a "
                        f"PERFORM ... THRU range ending at '{target_name}' "
                        f"could cover real paragraphs between them, whose "
                        f"early-exit-path behavior this splice would change"
                    )
                    continue
                if in_boundary:
                    problems.append(
                        f"line {statement.location.line}: nested inside another "
                        f"boundary statement's clause body -- splicing the "
                        f"enclosing statement would remove this GO TO along "
                        f"with it"
                    )
                    continue

                if nested:
                    # Never true for a GoStatement in practice (it has no
                    # clause bodies of its own), checked anyway for the same
                    # reason _nested_site_span checks it: defense in depth
                    # against a future statement-model change.
                    if _nested_statement_lists(statement):
                        problems.append(
                            f"line {statement.location.line}: has conditional "
                            f"clause bodies of its own"
                        )
                        continue
                    span, reason = nested_statement_span(statement, scope_map, lines)
                    if span is None:
                        problems.append(f"line {statement.location.line}: {reason}")
                        continue
                else:
                    line_problem = statement_top_level_problem(
                        statement, scope_map, lines
                    )
                    if line_problem is not None:
                        problems.append(
                            f"line {statement.location.line}: the GO TO "
                            f"statement {line_problem}"
                        )
                        continue
                    span = statement_span(statement, boundaries, last_line, lines)

                computed.append((statement, enclosing, "PARAGRAPH", span))

            last_problems[target_name] = problems
            if problems:
                continue

            for statement, enclosing, exit_kind, span in computed:
                plans.append(
                    GotoExitPlan(
                        statement=statement,
                        paragraph_name=enclosing,
                        exit_kind=exit_kind,
                        span=span,
                    )
                )
            newly_confirmed.append(target_name)

        if not newly_confirmed:
            break
        for target_name in newly_confirmed:
            del remaining[target_name]
            confirmed.add(target_name)

    for target_name, sites in sorted(remaining.items()):
        problems = last_problems[target_name]
        notes.append(
            f"GO TO {target_name} left as-is at {len(sites)} site(s) -- "
            f"not all are safe to splice into EXIT PARAGRAPH "
            f"automatically: " + "; ".join(problems)
        )

    return plans, notes


def neutralized_goto_targets(program, scope_map, lines: list[str]) -> frozenset[str]:
    """The exit-only paragraph names every GO TO of which is covered by a
    GotoExitPlan -- i.e. the targets `find_goto_exit_plans` fully
    neutralizes (all-or-nothing per target, so a name appears here only
    when EVERY GO TO naming it gets spliced into EXIT PARAGRAPH). The
    shared narrowing set for every consumer that must agree with what the
    splicer actually compiles: `find_terminator_plans`' hazard sets and
    `_reachable_paragraphs`/`check_test_case`'s reachable-set walk
    (2026-08-25 -- before that, the reachability BFS still modeled the
    spliced-away GO TO as a live edge, so the "GO TO <own-exit-label>"
    idiom's bare-EXIT landing pad cascaded fall-through reachability
    through the entire rest of the program, demanding mocks for
    boundaries the compiled test can never execute)."""
    plans, _notes = find_goto_exit_plans(program, scope_map, lines)
    return frozenset(
        target
        for target in (_go_statement_target(plan.statement) for plan in plans)
        if target is not None
    )


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
    # A paragraph fully covered by a GotoExitPlan (every GO TO naming it
    # gets spliced into EXIT PARAGRAPH/SECTION at its own call site) is no
    # longer entered via GO TO at all once splicing runs -- narrow
    # go_to_targets before deriving go_to_fallthrough from it, so a
    # terminator chain whose only obstacle was this exact idiom
    # (docs/2026-08-17-goto-exit-paragraph-simplification-design.md)
    # qualifies for neutralization here too. _safe_section_entry_points'
    # own internal go_to_targets check is deliberately left un-narrowed --
    # see find_goto_exit_plans' docstring.
    neutralized_goto = neutralized_goto_targets(program, scope_map, lines)
    go_to_targets = _go_to_targets(program) - neutralized_goto
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
            neutralized_goto=neutralized_goto,
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
                    f"is unsafe to test automatically: paragraph "
                    f"'{paragraph_name}' is itself a GO TO target "
                    f"somewhere in this program, and a paragraph that can "
                    f"be entered via GO TO can't reliably use EXIT "
                    f"PARAGRAPH to signal an early exit back to its "
                    f"caller -- mockymock refuses rather than risk "
                    f"generating a test that silently runs further than "
                    f"it should. To make this testable, replace the "
                    f"`GO TO {paragraph_name}` with structured PERFORM/"
                    f"EXIT PARAGRAPH logic (e.g. if it exists purely as "
                    f"an early exit, an `EXIT PARAGRAPH` in its place "
                    f"usually removes the need for the jump entirely)"
                )
            elif paragraph_name in go_to_fallthrough:
                problem = (
                    f"is unsafe to test automatically: control reaches it "
                    f"by falling through past the end of paragraph "
                    f"'{go_to_fallthrough[paragraph_name]}', which is a GO "
                    f"TO target elsewhere in this program -- code entered "
                    f"via GO TO never goes through PERFORM, so mockymock "
                    f"can't insert an early-exit check here that would "
                    f"correctly return to the right caller. Fixing the "
                    f"`GO TO {go_to_fallthrough[paragraph_name]}` (e.g. "
                    f"replacing it with `EXIT PARAGRAPH` if it exists "
                    f"purely as an early exit) would remove this hazard"
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
                    f"is unsafe to test automatically: propagating this "
                    f"early exit back to the test would require passing "
                    f"through paragraph '{bad_name}', which is itself a "
                    f"GO TO target somewhere in this program -- mockymock "
                    f"can't safely instrument a paragraph that can be "
                    f"entered other than via PERFORM. To make this "
                    f"testable, replace the `GO TO {bad_name}` with "
                    f"structured PERFORM/EXIT PARAGRAPH logic (e.g. if it "
                    f"exists purely as an early exit, an `EXIT PARAGRAPH` "
                    f"in its place usually removes the need for the jump "
                    f"entirely)"
                )
            elif chain_fallthrough_names:
                bad_name = sorted(chain_fallthrough_names)[0]
                problem = (
                    f"is unsafe to test automatically: propagating this "
                    f"early exit back to the test would require passing "
                    f"through paragraph '{bad_name}', which is reached by "
                    f"falling through past the end of paragraph "
                    f"'{go_to_fallthrough[bad_name]}' -- a GO TO target "
                    f"elsewhere in this program -- rather than via "
                    f"PERFORM. mockymock can't safely instrument a "
                    f"paragraph reached this way. Fixing the "
                    f"`GO TO {go_to_fallthrough[bad_name]}` (e.g. "
                    f"replacing it with `EXIT PARAGRAPH` if it exists "
                    f"purely as an early exit) would remove this hazard"
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
