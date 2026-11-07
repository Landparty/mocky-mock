"""Bundle expectations and call counts: EXPECT/VERIFY rendering and the
site analysis that decides which call counts are exact."""

from __future__ import annotations

from collections.abc import Collection
from typing import Any, cast

from mockymock.analysis.loops import site_in_loop
from mockymock.analysis.mock_surface import BoundarySite, MockSurface
from mockymock.dsl.fixture_bundle import Expectation
from mockymock.dsl.generator._context import CallCountOverride, ProgramContext
from mockymock.dsl.generator.keys import _is_known_category, _unique_prefix
from mockymock.dsl.model import (
    EXEC_CATEGORIES,
    MockCategory,
    MockDirective,
    read_access_matches,
    split_read_access,
)
from mockymock.report.record_rewrite import picture_for, render_expect_value


def _is_boundary_level_ref(ref: str) -> bool:
    """True when `ref` is a `"CATEGORY:KEY"` boundary reference rather
    than a COBOL data-name -- COBOL names never contain a colon, so
    checking for one of the known category strings before it is an
    unambiguous, precise test."""
    category_str, sep, _ = ref.partition(":")
    return bool(sep) and _is_known_category(category_str)


def _rendered_call_count_refs(
    expectations: list[Expectation],
    declared_keys: set[tuple[MockCategory, str]],
    call_count_overrides: dict[tuple[MockCategory, str], CallCountOverride],
) -> set[tuple[MockCategory, str]]:
    """The boundaries this TESTCASE will actually emit a real `VERIFY ...
    WAS CALLED n TIMES` line for.

    Needed by `_render_expectation`'s tier-3 branch: a boundary-level stub
    expectation is redundant only when that same boundary genuinely got a
    live count assertion here, and "genuinely" excludes both the keys with
    no MOCK directive of their own and the counts demoted to a `*>` comment
    by a `--placeholder` downgrade. Deriving it once, from the same
    `declared_keys`/`call_count_overrides` the rendering itself reads, keeps
    the two decisions from drifting apart."""
    rendered: set[tuple[MockCategory, str]] = set()
    for expectation in expectations:
        if expectation.kind != "call_count":
            continue
        category_str, _, key = expectation.ref.partition(":")
        try:
            category = MockCategory(category_str)
        except ValueError:
            continue
        if (category, key) not in declared_keys:
            continue
        override = call_count_overrides.get((category, key))
        if override is not None and override.demote_reason is not None:
            continue
        rendered.add((category, key))
    return rendered


# OUT boundaries whose record area holds what the program wrote.
_RECORD_OUTPUT_CATEGORIES = frozenset(
    {MockCategory.WRITE, MockCategory.REWRITE, MockCategory.RELEASE}
)


def _describe_boundary_ref(ref: str) -> str:
    """`"WRITE:INV-REC"` -> `WRITE INV-REC`, matching how a MOCK/VERIFY
    directive for that boundary reads in the `.cut`. Falls back to the raw
    ref for a category this mockymock doesn't know."""
    category_str, sep, key = ref.partition(":")
    if not sep:
        return ref
    try:
        return MockDirective(MockCategory(category_str), key).describe()
    except ValueError:
        return ref


def _render_expectation(
    expectation: Expectation,
    declared_keys: set[tuple[MockCategory, str]],
    call_count_overrides: (
        dict[tuple[MockCategory, str], CallCountOverride] | None
    ) = None,
    counted_boundaries: set[tuple[MockCategory, str]] | None = None,
    pictures: dict[str, str] | None = None,
    source: ProgramContext | None = None,
) -> list[str]:
    """Tier 1 (`call_count`) -> `VERIFY ... WAS CALLED n TIMES`; tier 2
    (`field_equals`) -> `EXPECT <name> TO BE <value>`; tier 3 (`stub`) ->
    a `*> STUB EXPECT ...` comment.

    A boundary-level tier-3 ref (`"WRITE:INV-REC"` rather than a data-name)
    is dropped ONLY when this same TESTCASE actually emits a live `VERIFY
    ... WAS CALLED` for that boundary -- `counted_boundaries`, from
    `_rendered_call_count_refs`. It used to be dropped unconditionally on
    that reasoning, which was wrong whenever the count assertion did not in
    fact get rendered (no MOCK directive of its own for that key, or a
    `--placeholder` downgrade demoting the count to a comment): the bundle
    knew something about an OUT boundary -- most visibly every `WRITE:` stub
    under `--scenarios all` -- and the generated `.cut` said nothing at all
    about it. A `*>` comment is inert, so surfacing it can never break the
    generated file; silently dropping it opened a gap between what the
    analysis knew and what reached the file, which is the one thing a
    scaffold must not do.

    `declared_keys` (from `_bundle_mock_directives`) -- not the broader
    `mockymock_keys` -- is what call_count is checked against: a key that
    only exists because it shares a physical site with the key a MOCK
    directive actually used (a multi-file OPEN/CLOSE's non-primary file)
    has no *literal* MOCK of its own in this TESTCASE, and VERIFYing it
    anyway is VERIFY_WITHOUT_MOCK.

    `call_count_overrides` (fix round 2, also from `_bundle_mock_directives`,
    same seam that decided each fixture's body) supersedes the bundle's own
    `expectation.value` for a `call_count` ref whose fixture was
    `--placeholder`-downgraded in a way that changed its real call count
    (see `CallCountOverride`'s own docstring) -- rendering the bundle's
    original, now-stale count would pin an assertion the generated `.cut`
    cannot itself satisfy, which is exactly the runnable-by-construction
    violation this fix closes. A `demote_reason` renders as a `*>` comment
    instead of a `VERIFY` line -- the real count is not known by
    construction in that case, and a speculative number would be worse
    than no assertion at all.
    """
    if expectation.kind == "call_count":
        category_str, _, key = expectation.ref.partition(":")
        try:
            category = MockCategory(category_str)
        except ValueError:
            return []
        if (category, key) not in declared_keys:
            return []  # no literal MOCK directive for this key in this TESTCASE
        directive_text = MockDirective(category, key).describe()
        override = (call_count_overrides or {}).get((category, key))
        if override is not None and override.demote_reason is not None:
            return [
                f"*> VERIFY {directive_text} WAS CALLED <count not exact "
                f"by construction"
                f"{' after --placeholder downgrade' if override.from_placeholder else ''}"
                f" -- {override.demote_reason}>"
            ]
        value = (
            override.count
            if override is not None and override.count is not None
            else expectation.value
        )
        return [f"VERIFY {directive_text} WAS CALLED {value} TIMES"]
    if expectation.kind == "field_equals":
        ref = _expect_name(expectation.ref, source)
        if ref is None:
            return [
                f"*> STUB EXPECT {expectation.ref} -- the program folds it to "
                f"{expectation.value}, but its name is declared under more "
                f"than one record and EXPECT takes no OF qualification"
            ]
        expectation = Expectation(
            kind=expectation.kind,
            ref=ref,
            value=expectation.value,
            note=expectation.note,
        )
        # The PICTURE decides bare vs quoted, exactly as it does for
        # `run --record-expectations`: a folded "-3" / "1.5" / "007" held in
        # a PIC X field rendered bare is an EXPECT that fails on the very
        # first run (GnuCOBOL compares it as text). `A OF B` resolves to
        # the declaration it qualifies (`picture_for`).
        picture = picture_for(expectation.ref, pictures)
        rendered = render_expect_value(
            str(expectation.value),
            picture,
            decimal_comma=source is not None and source.decimal_comma,
        )
        return [f"EXPECT {expectation.ref} TO BE {rendered}"]
    # kind == "stub"
    note = f" -- {expectation.note}" if expectation.note else ""
    if _is_boundary_level_ref(expectation.ref):
        category_str, _, key = expectation.ref.partition(":")
        try:
            pair = (MockCategory(category_str), key)
        except ValueError:
            pair = None
        if pair is not None and pair in (counted_boundaries or set()):
            return []  # already asserted by this case's own VERIFY ... WAS CALLED
        if pair is not None and pair[0] in _RECORD_OUTPUT_CATEGORIES:
            # The record area holds the last record written (a mocked
            # `WRITE r FROM y` keeps its implicit MOVE), so name the record
            # itself: `STUB EXPECT WRITE OUT-REC` is no data-name, and
            # `run --record-expectations` could never fill it (issue #255).
            directive = _describe_boundary_ref(expectation.ref)
            return [f"*> STUB EXPECT {key} -- last record written by {directive}"]
        return [f"*> STUB EXPECT {_describe_boundary_ref(expectation.ref)}{note}"]
    return [
        f"*> STUB EXPECT {_expect_name(expectation.ref, source) or expectation.ref}{note}"
    ]


def _expect_name(ref: str, source: ProgramContext | None) -> str | None:
    """A bundle names a field `RECORD.FIELD` (its schema's qualified form),
    which spliced into an EXPECT is a cobc syntax error (issue #144). The
    leaf is the COBOL name when it is unique; None when it is declared
    under more than one record -- the DSL has no `OF`."""
    base, paren, rest = ref.partition("(")
    if "." not in base:
        return ref
    leaf = base.rsplit(".", 1)[-1].strip()
    if source is not None and not source.is_unique_name(leaf):
        return None
    return leaf + paren + rest


def _merged_call_counts(expectations: list[Expectation]) -> list[Expectation]:
    """The bundle carries one `call_count` per call SITE, but a VERIFY (and
    the splicer's tally) counts per (category, key): two `CALL "FMT"`
    statements rendered as two `VERIFY ... 1 TIMES` lines that both failed
    with "got 2" (issue #142). Sum them into one expectation per ref, kept
    at the first one's position. READ and RETURN are the exception: every
    site of one file consumes the same sequential stream, so each site's
    count already covers the whole stream and the largest one is kept."""
    merged: list[Expectation] = []
    by_ref: dict[str, Expectation] = {}
    for expectation in expectations:
        if expectation.kind != "call_count":
            merged.append(expectation)
            continue
        existing = by_ref.get(expectation.ref)
        if existing is None:
            copy = Expectation(
                kind=expectation.kind,
                ref=expectation.ref,
                value=expectation.value,
                note=expectation.note,
            )
            by_ref[expectation.ref] = copy
            merged.append(copy)
        elif isinstance(existing.value, int) and isinstance(expectation.value, int):
            if expectation.ref.partition(":")[0] in ("READ", "RETURN"):
                existing.value = max(existing.value, expectation.value)
            else:
                existing.value += expectation.value
    return merged


def _sites_for_key(
    category: MockCategory,
    key: str,
    surface: MockSurface,
    reachable: set[str] | None = None,
    among: Collection[str] = (),
) -> list[BoundarySite]:
    """The sites a MOCK of `key` answers. `among` holds the other keys of
    the same category the case mocks: a READ / OPEN site goes only to the
    most specific of them that answers it, as at run time
    (`matching_directives`), so a `READ F KEY IS ALT` site counts under
    `READ F KEY ALT` and not also under `READ F KEY` (issue #402)."""
    return [
        site
        for site in surface.boundary_sites
        if site.category is category
        and (reachable is None or site.paragraph_name in reachable)
        and (
            _unique_prefix(site, surface) == key
            if category in EXEC_CATEGORIES
            else _site_answers(site, key) and _most_specific(site, key, among)
        )
    ]


def _key_specificity(key: str) -> int:
    """`F` 0, `F NEXT|PREVIOUS|KEY` or `F <open mode>` 1, `F KEY <name>` 2
    -- the order `matching_directives` picks a READ / OPEN directive by."""
    _, access = split_read_access(key)
    if access is None:
        return 0
    return 2 if " " in access else 1


def _most_specific(site: BoundarySite, key: str, among: Collection[str]) -> bool:
    """Whether no key in `among` answers `site` more narrowly than `key`."""
    if site.category not in (MockCategory.READ, MockCategory.OPEN):
        return True
    file_key = split_read_access(key)[0]
    mine = _key_specificity(key)
    return not any(
        other != key
        and split_read_access(other)[0] == file_key
        and _key_specificity(other) > mine
        and _site_answers(site, other)
        for other in among
    )


def _count_keys(expectations: list[Expectation]) -> dict[MockCategory, set[str]]:
    """The keys each category's call-count expectations name."""
    keys: dict[MockCategory, set[str]] = {}
    for expectation in expectations:
        if expectation.kind != "call_count":
            continue
        category_str, _, key = expectation.ref.partition(":")
        try:
            category = MockCategory(category_str)
        except ValueError:
            continue
        keys.setdefault(category, set()).add(key)
    return keys


def _site_answers(site: BoundarySite, key: str) -> bool:
    """Whether a bare-key MOCK of `key` answers `site`: one of its names,
    or, for `READ <file> <form>`, its file and access form."""
    file_key, access = split_read_access(key)
    if site.category is MockCategory.READ and access is not None:
        return file_key in site.keys and read_access_matches(access, site.read_form)
    if site.category is MockCategory.OPEN and access is not None:
        return file_key in site.keys and site.open_modes.get(file_key) == access
    return key in site.keys


_SEVERAL_SITES_REASON = (
    "called from several sites, some inside an IF/EVALUATE/loop, so how "
    "many of them this case reaches is not known"
)
_CONDITIONAL_SITE_REASON = (
    "called only under an IF/EVALUATE, or from a paragraph PERFORMed "
    "conditionally, so whether this case reaches it is not known"
)
_AFTER_STOP_REASON = (
    "called after a branch that may end the run (an IF holding a GOBACK / "
    "STOP RUN), so whether this case reaches it is not known"
)
_LOOPED_SITE_REASON = (
    "called inside a PERFORM loop (UNTIL/VARYING/TIMES) or from a paragraph "
    "PERFORMed more than once, which the bundle counts once"
)
_USE_PROCEDURE_REASON = (
    "the program has USE AFTER EXCEPTION procedures, which a mocked error "
    "or end-of-file outcome runs and which can change what runs next"
)
_NO_END_READ_REASON = (
    "read inside a loop that its AT END does not end (the READ has no AT "
    "END clause: a keyed/random READ, or a loop run a fixed number of "
    "TIMES), so the number of generated rows is not the number of reads"
)
_UNREACHED_SITE_REASON = (
    "also called from a paragraph this case's PERFORM never reaches (a CICS "
    "HANDLE CONDITION target, or code nothing PERFORMs), which the bundle's "
    "count includes"
)


_BRANCH_NODE_TYPES = frozenset({"IfStatement", "EvaluateStatement", "WhenClause"})


def _statement_under_branch(statement: object) -> bool:
    """Whether `statement` sits inside an IF or EVALUATE of its paragraph."""
    node = getattr(statement, "parent", None)
    while node is not None and type(node).__name__ not in (
        "CobolParagraph",
        "CobolSection",
        "CobolDivision",
    ):
        if type(node).__name__ in _BRANCH_NODE_TYPES:
            return True
        node = getattr(node, "parent", None)
    return False


def _paragraph_of(statement: object) -> str | None:
    node = getattr(statement, "parent", None)
    while node is not None:
        if type(node).__name__ == "CobolParagraph":
            return str(getattr(node, "paragraph_name", "") or "").upper() or None
        node = getattr(node, "parent", None)
    return None


def _site_under_branch(site: BoundarySite, program: object) -> bool:
    """Whether a case reaches `site` only through an IF/EVALUATE branch:
    the statement is inside one, or every PERFORM of its paragraph is
    (recursively). A site an earlier `IF ... GOBACK` merely guards is not:
    the happy path still reaches it. A loop-end count (a browse READNEXT
    answered by a row, then ENDFILE) holds only for a case that reaches the
    loop, so for such a site it is demoted like any other conditional
    count."""
    if _statement_under_branch(site.statement):
        return True
    if program is None or not hasattr(program, "find_all_by_type"):
        return False
    performs = cast(Any, program).find_all_by_type("PerformStatement")
    seen: set[str] = set()

    def paragraph_under_branch(name: str) -> bool:
        if name in seen:
            return False
        seen.add(name)
        callers = [
            perform
            for perform in performs
            if str(getattr(perform, "target_paragraph", "") or "").upper() == name
        ]
        if not callers:
            return False
        return all(
            _statement_under_branch(perform)
            or paragraph_under_branch(_paragraph_of(perform) or "")
            for perform in callers
        )

    return paragraph_under_branch(site.paragraph_name.upper())


def _conditional_call_count_keys(
    expectations: list[Expectation],
    surface: MockSurface,
    reachable: set[str] | None = None,
    scope: tuple[set[str], set[int]] | None = None,
    row_scope: tuple[set[str], set[int]] | None = None,
) -> list[tuple[tuple[MockCategory, str], str]]:
    """Keys whose bundle count (`_merged_call_counts`) is not exact, each
    with the reason. The bundle counts every site once per scenario whether
    or not its branch runs, so a count is kept only when every site runs on
    every pass: `scope` is `analysis.exact_counts.exact_count_scope` for
    this case's entry (issue #160 -- a single site behind `IF SQLCODE NOT =
    0`, or one in a paragraph PERFORMed only from inside `IF RECORD-OK`).
    Without a scope, any nested site is enough to demote (issue #142 for
    several sites, #160 for one). `_merged_call_counts` sums the bundle's
    per-site counts over every site of the key, so a key that also has a
    site outside `reachable` (ACCTINQ's CICS RETURN in its HANDLE
    CONDITION NOTFND paragraph) carries a count this case cannot reach --
    READ/RETURN excepted, whose merged count is the largest one, not a
    sum.

    `scope` takes a looping PERFORM's target (and a paragraph PERFORMed
    twice) out, since the bundle counts such a site once however often it
    runs (issue #290). READ/RETURN are checked against `row_scope` instead
    (the scope with `loops_exact=True`, falling back to `scope`): their
    counts come from the bundle's row data, which models the read loop."""
    keys: list[tuple[tuple[MockCategory, str], str]] = []
    count_keys = _count_keys(expectations)
    for expectation in expectations:
        if expectation.kind != "call_count":
            continue
        category_str, _, key = expectation.ref.partition(":")
        try:
            category = MockCategory(category_str)
        except ValueError:
            continue
        among = count_keys.get(category, ())
        sites = _sites_for_key(category, key, surface, reachable, among)
        if (
            reachable is not None
            and category not in (MockCategory.READ, MockCategory.RETURN)
            and len(_sites_for_key(category, key, surface, among=among)) > len(sites)
        ):
            keys.append(((category, key), _UNREACHED_SITE_REASON))
        elif len(sites) > 1 and any(site.nested for site in sites):
            keys.append(((category, key), _SEVERAL_SITES_REASON))
        elif scope is None:
            if any(site.nested for site in sites):
                keys.append(((category, key), _CONDITIONAL_SITE_REASON))
        elif category in (MockCategory.READ, MockCategory.RETURN):
            if any(not _site_in_scope(site, row_scope or scope) for site in sites):
                keys.append(((category, key), _CONDITIONAL_SITE_REASON))
        elif any(not _site_in_scope(site, scope) for site in sites):
            looped = row_scope is not None and all(
                _site_in_scope(site, row_scope) for site in sites
            )
            keys.append(
                (
                    (category, key),
                    _LOOPED_SITE_REASON if looped else _CONDITIONAL_SITE_REASON,
                )
            )
    return keys


#: Boundaries one statement invokes exactly once each time it runs.
_ONE_SHOT_CATEGORIES = frozenset(
    {
        MockCategory.CALL,
        MockCategory.DYNCALL,
        MockCategory.OPEN,
        MockCategory.CLOSE,
        MockCategory.WRITE,
        MockCategory.REWRITE,
        MockCategory.DELETE,
        MockCategory.START,
        MockCategory.UNLOCK,
        MockCategory.SQL,
        MockCategory.CICS,
    }
)


def _once_per_site_counts(
    expectations: list[Expectation],
    surface: MockSurface,
    reachable: set[str] | None,
    scope: tuple[set[str], set[int]],
) -> dict[tuple[MockCategory, str], int]:
    """The count of a one-shot boundary whose every reachable site is in
    the case's exact scope: one per site, since each such site runs once
    per `PERFORM entry`.

    The bundle counts the program's whole main-line run, which can fall
    through from the entry paragraph into the paragraphs after it (a
    sectioned main line: `0000-START. PERFORM 1000-INIT ...` falling into
    `1000-INIT`, so its OPEN is counted twice), while a case PERFORMs the
    entry paragraph alone and returns at its end."""
    counts: dict[tuple[MockCategory, str], int] = {}
    count_keys = _count_keys(expectations)
    for expectation in expectations:
        if expectation.kind != "call_count":
            continue
        category_str, _, key = expectation.ref.partition(":")
        try:
            category = MockCategory(category_str)
        except ValueError:
            continue
        if category not in _ONE_SHOT_CATEGORIES:
            continue
        sites = _sites_for_key(
            category, key, surface, reachable, count_keys.get(category, ())
        )
        if not sites or not all(_site_in_scope(site, scope) for site in sites):
            continue
        if expectation.value != len(sites):
            counts[(category, key)] = len(sites)
    return counts


def _after_possible_stop(site: BoundarySite, scope: tuple[set[str], set[int]]) -> bool:
    """Whether `site` is a top-level statement of a straight-path paragraph
    that the scope still leaves out: it comes after a statement that may
    end the run (`analysis.exact_counts`)."""
    paragraphs, statement_ids = scope
    return (
        not site.nested
        and site.paragraph_name in paragraphs
        and id(site.statement) not in statement_ids
    )


def _site_in_scope(site: BoundarySite, scope: tuple[set[str], set[int]]) -> bool:
    paragraphs, statement_ids = scope
    return site.paragraph_name in paragraphs and id(site.statement) in statement_ids


def _unlooped_read_counts(
    expectations: list[Expectation],
    surface: MockSurface,
    reachable: set[str] | None,
    source: ProgramContext,
) -> dict[tuple[MockCategory, str], int]:
    """A READ outside any loop (a run-parameter card read once at start-up)
    runs once per site, whatever number of rows the bundle generated for
    it; the bundle counts the rows (DORMACCT: "10 TIMES, got 1")."""
    counts: dict[tuple[MockCategory, str], int] = {}
    among = _count_keys(expectations).get(MockCategory.READ, ())
    for expectation in expectations:
        if expectation.kind != "call_count":
            continue
        category_str, _, key = expectation.ref.partition(":")
        if category_str != MockCategory.READ.value:
            continue
        sites = _sites_for_key(MockCategory.READ, key, surface, reachable, among)
        if sites and not any(
            site.nested or site_in_loop(site, source.looped) for site in sites
        ):
            counts[(MockCategory.READ, key)] = len(sites)
    return counts


def _endless_read_keys(
    expectations: list[Expectation],
    surface: MockSurface,
    reachable: set[str] | None,
    source: ProgramContext,
) -> list[tuple[MockCategory, str]]:
    """READ keys read inside a loop by a READ with no AT END clause. The
    bundle's count for a READ is its row count, which is the number of
    reads only when the loop runs until the read hits end of file (the
    AT END, or a FILE STATUS loop, which `_status_read_eof` counts
    itself). A keyed READ in `PERFORM X 3 TIMES` reads 3 times, not 10."""
    keys: list[tuple[MockCategory, str]] = []
    among = _count_keys(expectations).get(MockCategory.READ, ())
    for expectation in expectations:
        if expectation.kind != "call_count":
            continue
        category_str, _, key = expectation.ref.partition(":")
        if category_str != MockCategory.READ.value:
            continue
        sites = _sites_for_key(MockCategory.READ, key, surface, reachable, among)
        if any(
            (site.nested or site_in_loop(site, source.looped))
            and not getattr(site.statement, "at_end_clause", None)
            for site in sites
        ):
            keys.append((MockCategory.READ, key))
    return keys
