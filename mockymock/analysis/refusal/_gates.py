"""Refusal gate policy checks: whole-program (parse errors, unresolved
COPY statements, nested EXEC blocks) and per-TESTCASE (directive/site
matching) checks that turn a program + test suite into a list of
`RefusalReason`s.

Split out of the former monolithic `refusal.py` (2026-08-26 audit): this
module holds every function that produces refusal *policy* decisions,
built on top of `_reachability.py`'s graph primitives and `_plans.py`'s
terminator plan finder (`check_terminator_layout` is a thin wrapper over
`find_terminator_plans`).

Scoped checks (the `*_scoped` variants and `resolve_scoped_refusals`):
some refusal evidence is provably confined to one PROCEDURE DIVISION
paragraph's own body -- e.g. the single-line `COPY MEMBER.` layout owning
its whole line (`_copy_own_line_span`). Such evidence is held back as a
`ParagraphScopedRefusal` instead of an immediate reason, and resolved only
when some SELECTED test case can actually execute that paragraph (via
`union_executed_paragraphs`) -- so an unreachable paragraph's unresolvable
COPY doesn't block a suite that never runs it. Anything not provably
paragraph-local -- sibling code on the line, a second statement after a
terminator, multi-line COPY ... REPLACING -- stays whole-program.
`generate`/`fixtures` have no test cases to scope by, so the plain
`check_whole_program`/`check_unresolved_copybooks` entry points still
refuse everything, unchanged.

`check_unresolved_copybooks` (UNRESOLVED_COPYBOOK) is otherwise a
whole-program check, not a per-TESTCASE one: an unresolved COPY outside
the one provable paragraph-local shape above affects the whole program
regardless of which TESTCASE runs. It exists because cobolparser's
`parse_cobol` does NOT raise a parse error for an unresolved COPY
statement -- verified empirically: parsing raw (unexpanded) source
containing `COPY ORDREC.` yields `result.success is True` and an empty
`data_items` list for that DATA DIVISION section. Worse, the AST-node
`CopyStatement` class is never instantiated by any parser, so an
unresolved COPY leaves *zero* trace in the AST. The only reliable signal
is therefore textual: this function re-lexes `raw_source` with
cobolparser's own `CobolLexer` (free_form=True -- the default
fixed-format column rules would garble already-normalized text) and looks
for a `TokenType.COPY` token, rather than a naive substring search that
could false-positive on the word "COPY" in a comment or string literal.

See `.okf/analysis.md` for the full refusal-package overview.
"""

from __future__ import annotations

import re

from cobolparser.analysis.unused_variables import collect_declared_items
from cobolparser.lexer import CobolLexer, TokenType
from cobolparser.models.statements.call import CallStatement
from cobolparser.models.statements.misc import AlterStatement, UseStatement
from cobolparser.preprocess import normalize_fixed_format

from mockymock._lines import split_source_lines
from mockymock.analysis.linkage import (
    address_of_sites,
    linkage_plan,
    procedure_header_clause_spans,
)
from mockymock.analysis.mock_surface import (
    _TERMINATOR_LABELS,
    BoundarySite,
    MockSurface,
    NonInteractiveAccept,
    _all_paragraphs,
    normalize_exec_text,
)
from mockymock.analysis.sql_whenever import whenever_can_fire
from mockymock.dsl.generator import directive_snippet
from mockymock.dsl.model import (
    EXEC_CATEGORIES,
    FLOW_CATEGORIES,
    MockCategory,
    MockDirective,
    MockTestCase,
    MockTestSuite,
)

from ._plans import find_terminator_plans
from ._reachability import (
    _fallthrough_flags,
    _fallthrough_safe_sections,
    _find_statements_of_type,
    _go_to_targets,
    _paragraph_safe_section_map,
    _reachable_paragraphs,
    _source_ordered_paragraphs,
    _walk_fallthrough_from,
)
from ._types import (
    _UNANNOTATED,
    _UNMOCKED_CODES,
    _UNMOCKED_FILE_OP_CODE,
    _UNSUPPORTED_SITE_CODES,
    _UNSUPPORTED_STATEMENT_LABEL,
    ParagraphScopedRefusal,
    RefusalReason,
)

#: Punctuation whose surrounding whitespace is token spacing, not SQL.
_EXEC_PUNCTUATION_SPACING_RE = re.compile(r"\s*([.,():])\s*")


def _exec_match_form(text: str) -> str:
    """`normalize_exec_text` plus the whitespace around `. , ( ) :` removed:
    the form an SQL/CICS/DLI key and a site's EXEC text are compared in.

    Both sides of that comparison carry token spacing rather than the
    author's text: the site's comes from cobolparser's `sql_text`, which
    rejoins tokens with spaces the source never had -- and differently per
    release (the published 1.8.x renders `BANK.TRANSACTION_HIST` as
    `BANK. TRANSACTION_HIST`, later releases do not; both render
    `(A, B)` as `( A, B )` and `INTO :WS-A` as `INTO:WS-A`). Comparing
    raw, a key copied verbatim from the program's own source failed to
    match (UNMATCHED_MOCK) and a `.cut` written against one cobol-parser
    release broke under another."""
    return _EXEC_PUNCTUATION_SPACING_RE.sub(r"\1", normalize_exec_text(text))


#: Characters that continue one SQL/CICS/DLI name (a cursor, table, host
#: variable, CICS command word): a key may only end where the site's text
#: does not continue the same name.
_EXEC_NAME_CHARS = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_#@$"
)


def _exec_prefix_matches(prefix: str, text: str) -> bool:
    """`prefix` starts `text` and ends on a name boundary there.

    A bare character prefix let `MOCK SQL "FETCH C1"` also mock
    `FETCH C10 INTO ...` (and `MOCK CICS "READ"` mock `READQ TS ...`): the
    other cursor's site was silently served this directive's body and its
    ROWS tally instead of refusing UNMOCKED_SQL, and a case mocking both
    cursors refused AMBIGUOUS_MOCK. A key is a prefix of whole names."""
    if not prefix or not text.startswith(prefix):
        return False
    if len(text) == len(prefix):
        return True
    return not (
        prefix[-1] in _EXEC_NAME_CHARS and text[len(prefix)] in _EXEC_NAME_CHARS
    )


def directive_matches_site(directive: MockDirective, site: BoundarySite) -> bool:
    """Category must agree; then CALL keys match the call literal exactly,
    file-op/ACCEPT/DYNCALL keys match any of the site's (uppercased) names
    (the identifier a dynamic CALL calls through), and SQL/CICS/DLI keys
    prefix-match the site's normalized EXEC text on a name boundary. The category identity
    check is what keeps quoted (static) and bare (dynamic) CALL keys from
    ever cross-matching."""
    if site.category is not directive.category:
        return False
    if directive.category in EXEC_CATEGORIES:
        return _exec_prefix_matches(
            _exec_match_form(directive.key), _exec_match_form(site.match_text or "")
        )
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


def check_source_format(raw_source: str) -> list[RefusalReason]:
    """UNSUPPORTED_SOURCE_FORMAT when `raw_source` is free-format COBOL.

    cobol-parser decides fixed vs. free itself
    (`detect_fixed_format`), so a free-format program parses correctly --
    but every text the splicer edits and cobc compiles is cut down to
    columns 8-72 by `normalize_fixed_format`, which chops the first seven
    characters off each free-format line. The AST's line/column facts
    then describe text that no longer exists, and the run fails in cobc on
    garbage (or with a false layout refusal). Refuse up front, using the
    same decision cobol-parser parsed with (issue #210)."""
    from cobolparser.preprocess.source_format import detect_fixed_format

    if detect_fixed_format(raw_source):
        return []
    return [
        RefusalReason(
            code="UNSUPPORTED_SOURCE_FORMAT",
            message=(
                "the program is free-format COBOL; mockymock only splices "
                "and compiles fixed-format source (sequence area in "
                "columns 1-6, indicator in column 7, code in columns 8-72)"
            ),
        )
    ]


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
        split_source_lines(normalize_fixed_format(split_source_lines(raw_source)))
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
        if text.startswith("Compilation unit contains "):
            # cobol-parser parses every program unit of a multi-program
            # compilation unit (nested and stacked PROGRAM-IDs, and an OO
            # class's factory/object/method units) into
            # ``ast.contained_programs`` -- the AST is complete. What is
            # missing is mockymock's own support: the splicer and the
            # reachability BFS only see the outermost unit, so a CALL
            # into a contained program is neither a boundary nor a flow
            # edge. Refuse under a code that says so, rather than as a
            # dropped-content PARSE_WARNING, which it is not.
            reasons.append(
                RefusalReason(
                    code="UNSUPPORTED_NESTED_PROGRAM",
                    message=(
                        "program is a multi-unit compilation unit (nested "
                        "or stacked PROGRAM-IDs, or an object-oriented "
                        "class) -- mockymock splices and gates only the "
                        f"outermost unit, so a contained unit's boundaries "
                        f"would go unmocked: {warning}"
                    ),
                )
            )
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
      valid user paragraph can use -- verified empirically); that is the
      primary detection signal here, but it is a coincidental parser
      artifact, not a modeled "this is a declaratives section" flag (see
      .okf/analysis.md's "DECLARATIVES detection relies on cobolparser
      emitting it as a paragraph name" caveat) -- resynchronization after
      dropped content elsewhere, or a future parser change, could swallow
      that stray paragraph and erase it from the AST without necessarily
      producing a warning of its own (see the GH issue this guards:
      Landparty/mocky-mock#106, where a real IMS DL/I program with
      DECLARATIVES + USE FOR DEBUGGING was spliced and compiled with no
      refusal at all). USE statements are legal nowhere else in COBOL, so
      any UseStatement node anywhere in PROCEDURE DIVISION is an
      independent, structural proof that a DECLARATIVES section exists --
      checked as a second, unconditional detection path so the whole
      refusal does not rest on the one coincidental artifact.
    - ALTER rewrites another paragraph's GO TO target at runtime, so no
      static edge set is sound for a program containing one.
    """
    procedure = program.get_division("PROCEDURE")
    if procedure is None:
        return []
    reasons: list[RefusalReason] = []
    # cobol-parser (2026-09-15 and later) models DECLARATIVES: every section
    # between ``DECLARATIVES.`` and ``END DECLARATIVES.`` carries
    # ``is_declarative`` (metadata ``declarative``), and the two marker
    # lines no longer leave a paragraph behind. That flag is the primary
    # signal; the stray-paragraph artifact of older parsers and the USE
    # statement fallback below stay, so the refusal holds on every pin.
    declarative_section = next(
        (
            section
            for section in getattr(procedure, "_sections", {}).values()
            if getattr(section, "is_declarative", False)
            or bool(section.get_metadata("declarative"))
        ),
        None,
    )
    if declarative_section is not None:
        reasons.append(
            RefusalReason(
                code="UNSUPPORTED_DECLARATIVES",
                message=(
                    f"program contains a DECLARATIVES block (section "
                    f"'{declarative_section.section_name}', line "
                    f"{declarative_section.location.line}) -- USE "
                    f"procedures run on I/O conditions outside any "
                    f"PERFORM/GO TO edge, so the reachability gate cannot "
                    f"check the boundary statements inside them"
                ),
            )
        )
    declaratives_paragraph = None
    if declarative_section is None:
        for paragraph in _all_paragraphs(procedure):
            if paragraph.paragraph_name.upper() == "DECLARATIVES":
                declaratives_paragraph = paragraph
                break
    if declarative_section is not None:
        pass
    elif declaratives_paragraph is not None:
        reasons.append(
            RefusalReason(
                code="UNSUPPORTED_DECLARATIVES",
                message=(
                    f"program contains a DECLARATIVES block (line "
                    f"{declaratives_paragraph.location.line}) -- USE "
                    f"procedures run on I/O conditions outside any "
                    f"PERFORM/GO TO edge, so the reachability gate cannot "
                    f"check the boundary statements inside them"
                ),
            )
        )
    else:
        for paragraph in _all_paragraphs(procedure):
            use_statements = _find_statements_of_type(
                paragraph.statements, UseStatement
            )
            if use_statements:
                reasons.append(
                    RefusalReason(
                        code="UNSUPPORTED_DECLARATIVES",
                        message=(
                            f"paragraph '{paragraph.paragraph_name}' (line "
                            f"{use_statements[0].location.line}) contains a "
                            f"USE statement -- legal only inside a "
                            f"DECLARATIVES section, so the program has one "
                            f"even though no paragraph literally named "
                            f"DECLARATIVES survived parsing; USE procedures "
                            f"run on I/O conditions outside any PERFORM/GO "
                            f"TO edge, so the reachability gate cannot check "
                            f"the boundary statements inside them"
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
    # A WHENEVER whose action cannot be read cannot be emulated, and an
    # EXEC that is not emulated cannot stay (cobc can't compile it) --
    # dropping it would silently run different control flow (issue #195).
    reasons.extend(
        RefusalReason(
            code="UNSUPPORTED_SQL_WHENEVER",
            message=(
                f"EXEC SQL WHENEVER at line {site.line} (paragraph "
                f"'{site.paragraph_name}'): {site.whenever.problem} -- "
                f"mockymock emulates the precompiler's checks only for "
                f"those forms"
            ),
        )
        for site in surface.whenever_sites
        if site.whenever is not None and site.whenever.problem
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
    normalized = normalize_fixed_format(split_source_lines(raw_source))
    lexer = CobolLexer(normalized, free_form=True)
    tokens = lexer.tokenize()
    copy_indices = [i for i, t in enumerate(tokens) if t.type == TokenType.COPY]
    if not copy_indices:
        return [], []
    normalized_lines = split_source_lines(normalized)
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
    # Hook PERFORM steps are entry points too (suite hooks).
    entry_cases = suite.analysis_cases()
    for case in entry_cases:
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
    for case in entry_cases:
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

    # A default-entry `PROCEDURE DIVISION USING ...` is blanked out of the
    # instrumented copy (`splicer.linkage.neutralize`), its parameters
    # becoming ordinary folded storage a `.cut` MOVEs into -- refused only
    # when the clause can't be delimited (2026-10-10, entry parameters).
    if procedure_header_clause_spans(lines, program) is None:
        procedure = program.get_division("PROCEDURE")
        proc_idx = procedure.location.line - 1 if procedure is not None else -1
        proc_line = lines[proc_idx] if 0 <= proc_idx < len(lines) else ""
        reasons.append(
            RefusalReason(
                code="UNSUPPORTED_LINKAGE_LAYOUT",
                message=(
                    "the program's default entry header "
                    f"({proc_line.strip()!r}) uses CHAINING, or its USING "
                    "clause has no closing period mockymock can find -- "
                    "its parameters cannot be turned into storage a test "
                    "sets with MOVE"
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

    # A macro call inside `EXEC ... END-EXEC` (`DATATYPE(DFHVALUE(CHAR))`,
    # `RESP(...)` compared in an INQUIRE) never reaches cobc: the splicer
    # replaces every EXEC block wholesale with its mock or a trap stub, and
    # refuses one it cannot replace (NESTED_EXEC / UNSPLICEABLE_EXEC). Only
    # calls in ordinary COBOL need expanding, so only those are looked at
    # (string literals are blanked too: text, not a call).
    macro_lines = _mask_exec_blocks(lines)
    detected = _DFHRESP_MACRO_RE.findall("\n".join(macro_lines))
    if detected:
        located = _classify_cics_macro_calls(program, macro_lines) if classify else []
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


# String literals are matched first (and blanked too) so that
# `DISPLAY 'EXEC FAILED'` cannot
# open a "block" running on to some later, real END-EXEC and hide the code in
# between (a missed macro would then reach cobc unexpanded).
_EXEC_BLOCK_RE = re.compile(
    r"""(?P<string>"(?:[^"\n]|"")*"?|'(?:[^'\n]|'')*'?)"""
    r"|(?P<exec>(?<![A-Za-z0-9-])EXEC(?![A-Za-z0-9-]).*?"
    r"(?<![A-Za-z0-9-])END-EXEC(?![A-Za-z0-9-]))",
    re.IGNORECASE | re.DOTALL,
)


def _mask_exec_blocks(lines: list[str]) -> list[str]:
    """`lines` with every `EXEC ... END-EXEC` block and every string literal
    (text, not a macro call: `DISPLAY 'DFHRESP(NORMAL)'` compiles as is)
    blanked to spaces --
    same line count, same line widths, so every line/column found in the
    result indexes the original text unchanged."""

    def blank(match: re.Match[str]) -> str:
        return "".join(c if c == "\n" else " " for c in match.group())

    return _EXEC_BLOCK_RE.sub(blank, "\n".join(lines)).split("\n")


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


def _unmockable_accept_for(
    directive: MockDirective, surface: MockSurface
) -> NonInteractiveAccept | None:
    """The `ACCEPT ... FROM <system source>` a MOCK ACCEPT directive was
    aiming at, when that is why it matched nothing.

    Only ever consulted on the fallthrough path where a directive matched
    no boundary site at all, so it never competes with a real match. The
    key is compared against the ACCEPT's target data-name, the same key
    `_classify_statement` would have used had the statement been a
    console ACCEPT -- so a directive that WOULD have matched a mockable
    ACCEPT of the same name is the one this identifies."""
    if directive.category is not MockCategory.ACCEPT:
        return None
    key = directive.key.upper()
    for accept in surface.non_interactive_accepts:
        if accept.target == key:
            return accept
    return None


def check_test_case(
    surface: MockSurface,
    program,
    case: MockTestCase,
    file_status_fields: dict[str, str] | None = None,
    neutralized_goto: frozenset[str] | set[str] = frozenset(),
    shared: frozenset[int] | set[int] = frozenset(),
    matched_out: set[int] | None = None,
) -> list[RefusalReason]:
    """`shared` holds the ids of BEFORE-ALL/BEFORE-EACH directives (aliased
    into every case by the parser): one of them that this case never
    reaches is NOT refused here, because a shared mock is a default -- it
    is refused only when no test case and no hook step reaches it, which
    the caller decides from the ids collected in `matched_out` (see
    cli.checks, docs/2026-10-10-suite-hooks-design.md).

    `neutralized_goto` must be `neutralized_goto_targets(...)` computed
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
        # A WHENEVER handler is reached only when this case's mocks can set
        # SQLCODE so that its check fires (issue #244).
        follow_whenever=whenever_can_fire(program, case.mocks),
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
            elif site.label in _UNSUPPORTED_SITE_CODES:
                # INVOKE / CHAIN / Communication Module / STOP literal /
                # an unknown statement class (mock_surface's fail-closed
                # catch-all): detected, never mockable, refused when
                # reachable. The code and explanation live in _types.py.
                code, explanation = _UNSUPPORTED_SITE_CODES[site.label]
                what = (
                    f"{site.keys[0]}"
                    if site.label == _UNSUPPORTED_STATEMENT_LABEL and site.keys
                    else site.label + (f" {'/'.join(site.keys)}" if site.keys else "")
                )
                reasons.append(
                    RefusalReason(
                        code=code,
                        message=(
                            f"paragraph '{site.paragraph_name}' (line {site.line}) "
                            f"contains {what}, reachable from "
                            f"'{case.perform_target}' -- {explanation}"
                        ),
                    )
                )
            else:
                # Only a mixed-form SORT/MERGE reaches this branch now
                # (category=None): plain-file-form is mockable
                # (MockCategory.SORT/MERGE), and a pure-procedure-form
                # SORT is left real/unspliced and never even recorded as
                # a boundary site -- see mock_surface.py's
                # `_is_plain_sort_merge`/`_is_pure_procedure_sort`.
                assert site.label == "SORT/MERGE", site.label
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
            # A site that cannot be spliced where it stands is not fixed by
            # adding a MOCK -- that MOCK would be refused in turn -- so it
            # gets no suggested fix, and says why.
            unspliceable = (
                site.unspliceable_reason or _UNANNOTATED
                if site.nested and site.span is None
                else None
            )
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
                        + (
                            f" -- and a MOCK could not replace it either "
                            f"({unspliceable})"
                            if unspliceable is not None
                            else ""
                        )
                    ),
                    suggested_fix=(
                        directive_snippet(site, surface)
                        if unspliceable is None
                        else None
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

    if matched_out is not None:
        matched_out.update(matched_directives)
    for directive in case.mocks:
        if id(directive) in matched_directives:
            continue
        if (
            id(directive) in shared
            and _unmockable_accept_for(directive, surface) is None
        ):
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
        unmockable = _unmockable_accept_for(directive, surface)
        if unmockable is not None:
            # Not a reachability problem at all -- this ACCEPT reads a
            # system register, never the console, so mockymock never makes
            # a boundary site for it and there is nothing a mock could
            # intercept. Reporting it as UNMATCHED_MOCK ("does not match
            # any boundary site reachable from ...") sends the author off
            # verifying a call graph that was never the issue.
            reasons.append(
                RefusalReason(
                    code="UNMOCKABLE_ACCEPT_SOURCE",
                    message=(
                        f"MOCK {directive.describe()} targets `ACCEPT "
                        f"{unmockable.target} FROM {unmockable.from_source}` "
                        f"at line {unmockable.line} (paragraph "
                        f"'{unmockable.paragraph_name}'), which is not "
                        f"mockable at all: FROM {unmockable.from_source} "
                        f"reads a runtime/system value, never the console, "
                        f"so it is deterministic, never blocks, and has no "
                        f"boundary for a mock to intercept. Drop this MOCK "
                        f"directive; to control the value, assign the field "
                        f"in the mock body of a boundary the test does "
                        f"reach, or make the program take it as a CALL/file "
                        f"input"
                    ),
                )
            )
            continue
        if (
            directive.category is MockCategory.SQL
            and surface.whenever_sites
            and _exec_match_form(directive.key).startswith("WHENEVER")
        ):
            # Before issue #195 lint asked for exactly this mock; say why
            # it now goes rather than send the author after reachability.
            reasons.append(
                RefusalReason(
                    code="UNMATCHED_MOCK",
                    message=(
                        f"MOCK {directive.describe()} targets an EXEC SQL "
                        f"WHENEVER, which is a precompiler declaration, not "
                        f"a boundary: mockymock now emulates it (the "
                        f"IF SQLCODE ... GO TO check after every later SQL "
                        f"statement) and nothing mocks it. Drop this MOCK "
                        f"directive and its VERIFY"
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
                elif _is_omitted_argument(site.statement.using_parameters[index - 1]):
                    # `CALL "X" USING OMITTED B`: nothing is passed in that
                    # position, so the splice's `MOVE OMITTED TO <target>`
                    # is a cobc syntax error that lint never saw.
                    reasons.append(
                        RefusalReason(
                            code="CAPTURE_ARG_OUT_OF_RANGE",
                            message=(
                                f"MOCK {directive.describe()} CAPTURE ARG "
                                f"{index} INTO {target} -- argument {index} "
                                f"of the CALL at line {site.line} (paragraph "
                                f"'{site.paragraph_name}') is OMITTED, so "
                                f"there is no value to capture"
                            ),
                        )
                    )

    return reasons


def _is_omitted_argument(parameter: object) -> bool:
    """True for a `USING OMITTED` placeholder: cobolparser reports it as a
    CallParameter named OMITTED (a reserved word, never a data name)."""
    return str(getattr(parameter, "name", "")).strip().upper() == "OMITTED"


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
