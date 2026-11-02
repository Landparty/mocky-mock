"""
Refusal gate: whole-program (parse errors, unresolved COPY statements,
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

check_whole_program additionally refuses three constructs the flow model
deliberately does not attempt to handle, by their mere presence anywhere
in the program: DECLARATIVES (UNSUPPORTED_DECLARATIVES -- USE procedures
run on I/O conditions, invisible to any PERFORM/GO TO edge; detected from
cobol-parser's modelled ``is_declarative`` section flag first, with the
older stray-paragraph artifact and the USE statement itself as fallbacks),
ALTER (UNSUPPORTED_ALTER -- it rewrites GO TO targets at runtime, so no
static edge set is sound), and a multi-unit compilation unit
(UNSUPPORTED_NESTED_PROGRAM -- nested or stacked PROGRAM-IDs, or an
object-oriented CLASS-ID with its factory/object/method units: cobol-parser
parses every unit into ``contained_programs``, but the splicer and the
reachability BFS only see the outermost one, so a contained unit's
boundaries would go unmocked. Previously refused as PARSE_WARNING, which
misdescribed a complete AST as "missing content").

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

A directive matching no reachable site is UNMATCHED_MOCK -- with one
carve-out: a MOCK ACCEPT naming an `ACCEPT <target> FROM DATE/TIME/DAY/
COMMAND-LINE/...` refuses UNMOCKABLE_ACCEPT_SOURCE instead. Those ACCEPTs
read a system register, never the console, so mock_surface deliberately
creates no boundary site for them (there is nothing to intercept and
nothing that could hang) -- reporting that as "does not match any boundary
site reachable from ..." describes a reachability failure that never
happened. A VERIFY whose (category, key) no MOCK directive of the same case
declares is VERIFY_WITHOUT_MOCK (its tally field would be stale or
undeclared).

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
- matched, with clause bodies (AT END, INVALID KEY, ON EXCEPTION, ...)
  that `analysis.clause_bodies` cannot lift -> UNLIFTABLE_CLAUSE_BODY
  (check_clause_bodies, issue #319): the splice would delete every body
  of the statement with it.

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
verbs and unparsed clause leftovers mean the AST is incomplete, so a
"clean" splice would silently drop program behavior (the multi-program
warning is the one exception: it is routed to UNSUPPORTED_NESTED_PROGRAM,
see above). check_expansion_warnings (EXPANSION_WARNING) does the same for
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

Package layout (2026-08-26 audit split -- this was previously one 3,153-
line module, the codebase's single most fix-churned file; the split keeps
the same import surface below so no caller changes):

- `_types.py` -- `RefusalReason`/`ParagraphScopedRefusal` dataclasses and
  the small constants shared by the other two.
- `_reachability.py` -- the BFS/fall-through/section-safety primitives
  described above (`_reachable_paragraphs` and its helpers).
- `_plans.py` -- `TerminatorPlan`/`GotoExitPlan` construction
  (`find_terminator_plans`, `find_goto_exit_plans`, `neutralized_goto_targets`),
  built on `_reachability.py`.
- `_gates.py` -- the refusal policy checks themselves (`check_whole_program`,
  `check_test_case`, `check_linkage_layout`, the `*_scoped` variants, ...),
  built on both of the above.

Every name below is re-exported here so `from mockymock.analysis.refusal
import X` keeps working exactly as it did when this was a single module --
including the private (underscore-prefixed) helpers several tests reach
into directly for targeted coverage of one BFS step or plan-finding rule.
"""

from __future__ import annotations

from ._explanations import REFUSAL_EXPLANATIONS
from ._gates import (
    _CANDIDATE_LABEL_RE,
    _CICS_MACRO_CALL_RE,
    _DFHCOMMAREA_RE,
    _DFHRESP_MACRO_RE,
    _LOSSY_DECODE_MARKER,
    _PHANTOM_TERMINATOR_PARAGRAPH_NAMES,
    _WARNING_LINE_RE,
    CICS_MACRO_PLACEHOLDER,
    _check_unsupported_control_flow,
    _copy_own_line_span,
    _has_unaccounted_label,
    _paragraph_body_span,
    _paragraph_owning_line,
    _whole_program_reasons,
    check_cics_eib_layout,
    check_cics_eib_layout_scoped,
    check_clause_bodies,
    check_expansion_warnings,
    check_linkage_layout,
    check_mock_body_line_length,
    check_nested_exec,
    check_source_format,
    check_terminator_layout,
    check_test_case,
    check_unresolved_copybooks,
    check_unresolved_copybooks_scoped,
    check_whole_program,
    check_whole_program_scoped,
    directive_matches_site,
    matching_directives,
    per_file_matches,
    resolve_scoped_refusals,
    union_executed_paragraphs,
)
from ._plans import (
    PROGRAM_END_PARAGRAPH,
    GotoExitPlan,
    TerminatorPlan,
    find_goto_exit_plans,
    find_terminator_plans,
    neutralized_goto_targets,
    program_end_thru,
    program_last_paragraph,
)
from ._reachability import (
    _expand_thru_range,
    _falls_through,
    _fallthrough_flags,
    _fallthrough_safe_sections,
    _find_flow_statements,
    _find_sort_merge_statements,
    _find_statements_of_type,
    _first_non_fallthrough,
    _go_statement_raw_targets,
    _go_statement_target,
    _go_statements_with_nesting,
    _go_to_fallthrough_targets,
    _go_to_targets,
    _is_exit_only_paragraph,
    _paragraph_safe_section_map,
    _plain_perform_edges_from,
    _plain_perform_statements,
    _reachable_paragraphs,
    _safe_section_entry_points,
    _section_member_modes,
    _source_ordered_paragraphs,
    _walk_fallthrough_from,
    duplicated_paragraph_names,
)
from ._types import (
    _UNANNOTATED,
    _UNMOCKED_CODES,
    _UNMOCKED_FILE_OP_CODE,
    ParagraphScopedRefusal,
    RefusalReason,
)

__all__ = [
    "RefusalReason",
    "ParagraphScopedRefusal",
    "TerminatorPlan",
    "GotoExitPlan",
    "PROGRAM_END_PARAGRAPH",
    "program_end_thru",
    "program_last_paragraph",
    "directive_matches_site",
    "matching_directives",
    "per_file_matches",
    "check_source_format",
    "check_whole_program",
    "check_whole_program_scoped",
    "check_expansion_warnings",
    "check_nested_exec",
    "check_unresolved_copybooks",
    "check_unresolved_copybooks_scoped",
    "union_executed_paragraphs",
    "resolve_scoped_refusals",
    "CICS_MACRO_PLACEHOLDER",
    "check_linkage_layout",
    "check_mock_body_line_length",
    "check_cics_eib_layout",
    "check_cics_eib_layout_scoped",
    "check_test_case",
    "find_goto_exit_plans",
    "neutralized_goto_targets",
    "find_terminator_plans",
    "check_clause_bodies",
    "check_terminator_layout",
    "_fallthrough_flags",
    "_first_non_fallthrough",
    "REFUSAL_EXPLANATIONS",
    "duplicated_paragraph_names",
]
