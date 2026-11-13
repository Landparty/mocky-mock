"""Fixture-bundle-driven MOCK directives: per-fixture and per-group bodies,
SQL ROWS and DL/I row sequences, and a scenario's full directive set."""

from __future__ import annotations

import re
from dataclasses import replace

from mockymock.analysis.mock_surface import BoundarySite, MockSurface
from mockymock.dsl.fixture_bundle import BoundaryFixture, Scenario
from mockymock.dsl.generator._context import (
    CallCountOverride,
    ProgramContext,
    _comment_text,
)
from mockymock.dsl.generator.cics import _accept_loop_end_lines, _cics_loop_end_lines
from mockymock.dsl.generator.directives import (
    _directive_for,
    _per_target_body,
    _placeholder_body_for,
    _with_captures,
)
from mockymock.dsl.generator.files import (
    _at_end_handling,
    _merged_status_only_body,
    _read_body,
    _read_exhaustion_lines,
    _status_only_body,
    _status_read_eof,
)
from mockymock.dsl.generator.ims import (
    _call_loop_end_lines,
    _dli_function,
    _dli_loop_end_lines,
    _dli_sites,
    _dli_success_reply,
    _row_already_ends,
    _without_loop_control,
    dli_interfaces,
)
from mockymock.dsl.generator.keys import _directive_header, file_op_key
from mockymock.dsl.generator.mq import _mq_success_reply
from mockymock.dsl.generator.rows import _bundle_rendered_value, _single_row_body
from mockymock.dsl.generator.sql import (
    _SQL_ROWS_EXHAUSTED_BODY,
    _is_looped_fetch,
    _sql_output_layout,
    _sql_wants_rows,
)
from mockymock.dsl.model import MockCategory
from mockymock.splicer.naming import TallyRegistry


def _sql_rows_directive(
    category: MockCategory,
    key: str,
    fixture: BoundaryFixture,
    decimal_comma: bool = False,
) -> list[str]:
    lines = [f'MOCK {category.value} "{key}" ROWS']
    for row in fixture.sequence:
        pairs = ", ".join(
            f"{spec.column} = "
            f"{_bundle_rendered_value(row.get(spec.column, ''), spec.category, decimal_comma)}"
            for spec in fixture.layout
        )
        lines.append(f"    ( {pairs} )")
    lines.append("END-MOCK")
    return lines


def _bundle_directive_for(
    fixture: BoundaryFixture,
    mockymock_keys: dict[tuple[MockCategory, str], BoundarySite],
    registry: TallyRegistry,
    placeholder_keys: frozenset[tuple[str, str]] = frozenset(),
    source: ProgramContext | None = None,
    pinned: frozenset[str] = frozenset(),
) -> tuple[list[str], CallCountOverride | None] | None:
    """The full `MOCK ... END-MOCK` (or `MOCK ... ROWS ... END-MOCK`) block
    for one scenario's boundary fixture, or None if this (category, key)
    has no matching mockymock boundary site (already reported by
    `_warn_on_key_mismatch`). Also returns a `CallCountOverride` when this
    fixture's downgrade also changes its real call count (see that
    class's own docstring) -- `None` when the bundle's original tier-1
    `call_count` expectation still holds.

    `placeholder_keys` (`mockymock generate --placeholder CATEGORY:KEY`,
    repeatable) names fixtures whose body should be DOWNGRADED to strip
    the seeded data while KEEPING any loop-termination machinery that
    data drove -- checked against the fixture's own `(category, key)`
    (bundle-side string category, matching how the CLI parses
    `--placeholder`'s value), not `mockymock_keys`'s MockCategory keying.
    The fixture stays MOCKED either way; only its body (and, for SQL's
    ROWS-sugar directive line, the directive line itself) loses the row
    data. Every generated `.cut` must be RUNNABLE by construction (fix
    round 1, unify-with-data Task 4) -- so the two categories whose
    non-downgraded body embeds loop-termination sugar get a DEDICATED
    downgrade instead of the ordinary, category-generic
    `_placeholder_body_for`, which would silently drop it:

    - READ: `_read_exhaustion_lines` (the SAME helper `_read_body` uses
      for its own `WHEN OTHER` branch and its own empty-sequence case) --
      an "immediately at end" body, not an empty one, so a program's own
      `PERFORM ... UNTIL <eof-flag>` loop still terminates, after exactly
      ONE call -- `CallCountOverride(count=1)` when the body actually
      carries a real termination MOVE (`fixture.terminal` or a replicated
      `AT END` MOVE), else `CallCountOverride(demote_reason=...)` since an
      empty body's real call count cannot be known.
    - SQL, when this fixture would have used `ROWS` sugar
      (`_sql_wants_rows`): `_SQL_ROWS_EXHAUSTED_BODY` (`MOVE 100 TO
      SQLCODE`, mirroring `splicer/injector.py`'s own hardcoded
      exhausted-branch value for `MOCK SQL ... ROWS`), not the ordinary
      SQL placeholder's `MOVE 0 TO SQLCODE` (permanent "more rows
      available"), which would hang a `PERFORM UNTIL SQLCODE = 100`
      cursor-fetch loop the same way an empty READ body would --
      `CallCountOverride(count=1)` unconditionally, since this body is
      always an unconditional, real `MOVE` (no replication gap possible).

    Every other category's downgrade has no loop-termination sugar to
    lose (OPEN/CLOSE/etc.'s STATUS_ONLY body is a single-shot per-call
    status override; CALL/DYNCALL/ACCEPT/CICS/DLI/a single-row SQL
    fixture never emit ROWS sugar at all), so `_placeholder_body_for`
    stays correct for them and no override of THEIR OWN call count is
    needed. Only the downgraded boundary's own call_count is recomputed
    here -- a DIFFERENT boundary's call count that is itself program-flow-
    driven by how many times the now-downgraded loop executes, e.g. a CALL
    made once per row inside the same READ loop being downgraded, is NOT
    known here at all (this function sees one fixture at a time). That
    cascade is handled one level up, by `_bundle_mock_directives`'s own
    post-pass over the `CallCountOverride`s this function returns: every
    OTHER declared boundary in the SAME paragraph as a loop-driving
    downgrade (`site.paragraph_name`, mockymock's own analysis, not the
    bundle's `fixture.paragraph`) gets its own call_count demoted to a
    `*>` comment too, on the same "same paragraph as the READ/FETCH loop"
    heuristic the ordinary READ-loop-with-inline-CALL shape satisfies
    exactly. A boundary reached only through a nested PERFORM from inside
    that paragraph is not caught by this heuristic and can still go
    stale -- review the VERIFYs on any other boundary inside the same loop
    as a downgraded one before trusting the generated file."""
    try:
        category = MockCategory(fixture.category)
    except ValueError:
        return None
    site = mockymock_keys.get((category, fixture.key))
    if site is None:
        return None

    call_count_override: CallCountOverride | None = None
    status_eof_loop = False
    if category is MockCategory.READ:
        fixture, status_eof_loop = _status_read_eof(fixture, source)
    looped_fetch = category is MockCategory.SQL and _is_looped_fetch(
        fixture, site, source
    )
    if category is MockCategory.SQL:
        fixture = replace(fixture, layout=_sql_output_layout(fixture, source))
    if (fixture.category, fixture.key) in placeholder_keys:
        if category is MockCategory.READ:
            replicated, at_end, lifted = _at_end_handling(fixture, site, source)
            body = _read_exhaustion_lines(fixture, replicated, at_end, lifted)
            if fixture.terminal or replicated or lifted:
                call_count_override = CallCountOverride(count=1)
            else:
                call_count_override = CallCountOverride(
                    demote_reason=(
                        "downgraded READ body carries no termination "
                        "signal at all (no FILE STATUS field, and this "
                        "program's AT END clause could not be "
                        "auto-replicated) -- the real call count is not "
                        "known by construction"
                    )
                )
        elif category is MockCategory.SQL and _sql_wants_rows(fixture, looped_fetch):
            body = list(_SQL_ROWS_EXHAUSTED_BODY)
            if source is not None and source.references("SQLSTATE"):
                # The same "not found" SQLSTATE a ROWS mock's exhaustion
                # reports (issue #313).
                body.append('MOVE "02000" TO SQLSTATE')
            call_count_override = CallCountOverride(count=1)
        else:
            body = _dli_success_reply(
                _placeholder_body_for(category, fixture.key, site), site, source
            )
            end_lines = _call_loop_end_lines(site, source, None) + _cics_loop_end_lines(
                site, source, None
            )
            if category is MockCategory.ACCEPT:
                end_lines = _accept_loop_end_lines(site, source, None)
                if end_lines and not end_lines[0].startswith("*>"):
                    body = []  # the sentinel replaces the placeholder value
            body = body + end_lines
            if end_lines and not end_lines[0].startswith("*>"):
                call_count_override = CallCountOverride(count=1)
    elif fixture.direction == "STATUS_ONLY":
        body = _status_only_body(fixture)
    elif category is MockCategory.READ:
        body = _read_body(fixture, registry, category, site, source)
        if status_eof_loop:
            call_count_override = CallCountOverride(
                count=len(fixture.sequence) + 1,
                from_placeholder=False,
                cascades=False,
            )
    elif category is MockCategory.SQL and _sql_wants_rows(fixture, looped_fetch):
        # A looped FETCH runs once per row plus the call that finds the
        # cursor exhausted; the bundle counts only the rows.
        override = (
            CallCountOverride(count=len(fixture.sequence) + 1, from_placeholder=False)
            if looped_fetch
            else None
        )
        return (
            _sql_rows_directive(
                category,
                fixture.key,
                fixture,
                source is not None and source.decimal_comma,
            ),
            override,
        )
    else:
        loop_todo: list[str] = []
        if category in (MockCategory.CALL, MockCategory.DYNCALL, MockCategory.DLI):
            fixture, loop_todo = _without_loop_control(fixture, site, source)
        body = _single_row_body(fixture, source, pinned) + loop_todo
        if category is MockCategory.CALL:
            body = _dli_success_reply(
                _mq_success_reply(body, site, pinned), site, source
            )
        if category is MockCategory.DLI and registry.known(category, fixture.key):
            body = body + _dli_loop_end_lines(
                site, source, registry.name(category, fixture.key)
            )
        if category is MockCategory.CICS and registry.known(category, fixture.key):
            end_lines = _cics_loop_end_lines(
                site, source, registry.name(category, fixture.key)
            )
            if end_lines and not end_lines[0].startswith("*>"):
                # The row answers the first call, ENDFILE the second.
                call_count_override = CallCountOverride(count=2, from_placeholder=False)
            body = body + end_lines
        if category is MockCategory.ACCEPT and registry.known(category, fixture.key):
            end_lines = _accept_loop_end_lines(
                site, source, registry.name(category, fixture.key)
            )
            if end_lines and not end_lines[0].startswith("*>"):
                # The row answers the first ACCEPT, the sentinel the second.
                call_count_override = CallCountOverride(count=2, from_placeholder=False)
            body = body + end_lines
        if category is MockCategory.CALL and registry.known(category, fixture.key):
            end_lines = _call_loop_end_lines(
                site, source, registry.name(category, fixture.key)
            )
            if (
                end_lines
                and not end_lines[0].startswith("*>")
                and not _row_already_ends(body, site, source)
            ):
                # The row answers the first call and the end-of-data reply
                # the second, which ends the loop waiting on it.
                call_count_override = CallCountOverride(count=2, from_placeholder=False)
            body = body + end_lines

    if category is MockCategory.DYNCALL:
        body = _per_target_body(fixture.key, body, source)
    body = _with_captures(category, fixture.key, body, source)
    lines = [_directive_header(category, fixture.key, site)]
    lines.extend(f"    {line}" for line in body)
    lines.append("END-MOCK")
    return lines, call_count_override


def _dli_rows_directive(
    fixtures: list[BoundaryFixture],
    mockymock_keys: dict[tuple[MockCategory, str], BoundarySite],
    registry: TallyRegistry,
    placeholder_keys: frozenset[tuple[str, str]],
    source: ProgramContext,
    pinned: frozenset[str],
    target_paragraph: str | None = None,
) -> tuple[list[str], CallCountOverride | None] | None:
    """One `MOCK CALL "CBLTDLI"` answering each DL/I call with the row the
    bundle generated for THAT call, or None when this is not such a group.

    The bundle gives every CALL site its own fixture (the message GU on the
    I/O PCB, the GU on a database PCB with the segment and the status the
    scenario needs, the ISRT reply), but one MOCK answers every site of the
    key, and it used to render the first fixture alone: the segment and
    the DB PCB status a branch needed were dropped, so an MPP's found path
    (and every subprogram it calls) never ran. The body now dispatches on
    the function code the call passed and, when one function is used on
    several PCBs, on the PCB it passed (`UT-PASSED-ARG-2`, which the
    splicer replaces with the site's own argument name).

    One function on one PCB called from several paragraphs (a GHN priming
    the loop in 1000-INITIALIZE, the same GHN reading the next segment in
    2500-GET-NEXT) is dispatched on the calling paragraph too
    (`UT-CALLING-PARAGRAPH`). The status a scenario pins for a branch is
    then given only at the call in the branch's own paragraph
    (`target_paragraph`); the other calls report success, or the priming
    call already answered the loop's status and the loop never ran while
    the case was reported verified. The end-of-data reply counts the calls
    of each site (`UT-SITE-TALLY`), not of the key, so the loop's own call
    still returns its row once after the priming call."""
    first = fixtures[0]
    if first.category != MockCategory.CALL.value:
        return None
    if first.key.upper() not in dli_interfaces(source):
        return None
    if any((f.category, f.key) in placeholder_keys for f in fixtures):
        return None
    site = mockymock_keys.get((MockCategory.CALL, first.key))
    if site is None:
        return None
    capture = next(
        (
            line.split(" INTO ", 1)[1].strip()
            for line in source.captures_for(MockCategory.CALL, first.key)
            if line.upper().startswith("CAPTURE ARG 1 INTO ")
        ),
        None,
    )
    if capture is None:
        return None
    by_line = {other.line: (other, names) for other, names in _dli_sites(source)}
    rows: dict[tuple[str, str, str], tuple[BoundaryFixture, BoundarySite]] = {}
    pcbs_of: dict[str, set[str]] = {}
    paragraphs_of: dict[tuple[str, str], set[str]] = {}
    for other, names in by_line.values():
        if len(names) >= 2:
            function = _dli_function(names[0], source).strip().upper()
            pcbs_of.setdefault(function, set()).add(names[1].upper())
            paragraphs_of.setdefault((function, names[1].upper()), set()).add(
                str(other.paragraph_name or "").upper()
            )
    for fixture in fixtures:
        found = by_line.get(fixture.line or -1)
        if found is None or len(found[1]) < 2 or not fixture.sequence:
            return None
        other, names = found
        function = _dli_function(names[0], source).strip().upper()
        pcb = names[1].upper()
        paragraph = (
            str(other.paragraph_name or "").upper()
            if len(paragraphs_of.get((function, pcb), ())) > 1
            else ""
        )
        rows.setdefault((function, pcb, paragraph), (fixture, other))
    if len(rows) < 2:
        return None
    target = (target_paragraph or "").upper()
    # The PCBs whose status the scenario's branch reads right after a call
    # in its own paragraph: only that call gets the pinned status.
    pinned_at_target = {
        pcb for (_f, pcb, paragraph) in rows if paragraph and paragraph == target
    }
    body: list[str] = [
        "*> each DL/I call gets the row generated for it: by the function code"
        " it passed, and the PCB when one function is used on several",
        "EVALUATE TRUE",
    ]
    end_lines: list[str] = []
    if registry.known(MockCategory.CALL, first.key):
        # Split by paragraph, the priming call and the loop's call are both
        # counted by the key's tally: the loop's first call would already
        # end it. Each site's own count does not see the priming call.
        split = any(paragraph for (_f, _p, paragraph) in rows)
        end_lines = _call_loop_end_lines(
            site,
            source,
            "UT-SITE-TALLY" if split else registry.name(MockCategory.CALL, first.key),
        )
    ends_loop = bool(end_lines) and not end_lines[0].startswith("*> TODO")
    for (function, pcb, paragraph), (fixture, other) in rows.items():
        fixture, todo = _without_loop_control(fixture, other, source)
        row_pinned = pinned
        if pcb in pinned_at_target and paragraph != target:
            row_pinned = frozenset()
        # The end-of-data reply below ends the loop: no TODO saying so.
        row = _single_row_body(fixture, source, row_pinned) + (
            [] if ends_loop else todo
        )
        status_pinned = bool(source.names_under(pcb) & row_pinned) if pcb else False
        if not status_pinned:
            row = _dli_success_reply(row, other, source)
        condition = f'{capture} = "{function}"'
        if len(pcbs_of.get(function, ())) > 1:
            condition += f' AND UT-PASSED-ARG-2 = "{pcb}"'
        if paragraph:
            condition += f' AND UT-CALLING-PARAGRAPH = "{paragraph}"'
        body.append(f"    WHEN {condition}")
        body.extend(f"        {line}" for line in row or ["CONTINUE"])
    body.append("END-EVALUATE")
    override: CallCountOverride | None = None
    body += end_lines
    body = _with_captures(MockCategory.CALL, first.key, body, source)
    lines = [_directive_header(MockCategory.CALL, first.key, site)]
    lines.extend(f"    {line}" for line in body)
    lines.append("END-MOCK")
    return lines, override


def _bundle_directive_for_group(
    fixtures: list[BoundaryFixture],
    mockymock_keys: dict[tuple[MockCategory, str], BoundarySite],
    registry: TallyRegistry,
    placeholder_keys: frozenset[tuple[str, str]] = frozenset(),
    source: ProgramContext | None = None,
    pinned: frozenset[str] = frozenset(),
    target_paragraph: str | None = None,
) -> tuple[list[str], CallCountOverride | None] | None:
    """Like `_bundle_directive_for`, but for every fixture that resolves
    to the SAME physical mockymock `BoundarySite` (only possible for
    STATUS_ONLY -- a multi-file `OPEN`/`CLOSE` is one physical statement
    even though cobol-parser's `BoundaryInventoryAnalyzer` reports one
    `Boundary` per file, see `_mockymock_boundary_keys`). Declaring a
    separate MOCK directive per file would double-match the one physical
    site and refuse AMBIGUOUS_MOCK -- exactly one directive is emitted,
    keyed on the first fixture's own key, with every group member's status
    merged in (see `_merged_status_only_body`). Never returns a
    `CallCountOverride`: STATUS_ONLY (the only category that groups) has
    no loop-termination concept for a downgrade to lose -- see
    `_bundle_directive_for`'s own docstring.

    `placeholder_keys` is checked against EVERY group member's own
    `(category, key)`, not just the primary's: the shared MOCK directive
    is keyed on the primary fixture, but a user naming the group's
    SECONDARY file (e.g. `--placeholder OPEN:RPT-FILE` when INV-FILE is
    primary) must still trigger the downgrade -- that key genuinely has a
    fixture, so silently no-op'ing on it would be exactly the
    matched-nothing case the CLI's own unmatched-placeholder warning
    exists to catch, made worse by staying silent instead.

    A group holding any non-STATUS_ONLY fixture is not a multi-file
    statement: it is several statements on one file that mockymock mocks
    as one site (a priming READ plus the READ inside the loop). Those
    render from the first fixture alone, whose rows end the loop; merging
    them as status-only left the READ mock empty and the loop endless."""
    if len(fixtures) > 1 and source is not None:
        merged = _dli_rows_directive(
            fixtures,
            mockymock_keys,
            registry,
            placeholder_keys,
            source,
            pinned,
            target_paragraph,
        )
        if merged is not None:
            return merged
    if len(fixtures) == 1 or any(f.direction != "STATUS_ONLY" for f in fixtures):
        return _bundle_directive_for(
            fixtures[0], mockymock_keys, registry, placeholder_keys, source, pinned
        )
    primary = fixtures[0]
    try:
        category = MockCategory(primary.category)
    except ValueError:
        return None
    site = mockymock_keys.get((category, primary.key))
    if site is None:
        return None
    if any((f.category, f.key) in placeholder_keys for f in fixtures):
        body = _placeholder_body_for(category, primary.key, site)
    else:
        body = _merged_status_only_body(fixtures)
    lines = [_directive_header(category, primary.key, site)]
    lines.extend(f"    {line}" for line in body)
    lines.append("END-MOCK")
    return lines, None


_TARGET_ARM_RE = re.compile(r"\btargets branch arm ([A-Z0-9#@$-]+)@\d+:", re.IGNORECASE)


def _target_paragraph(scenario: Scenario) -> str | None:
    """The paragraph of the branch arm `scenario` is named for, from its
    intent (`targets branch arm 2500-GET-NEXT@375:5/WHEN_2`), or None for
    a scenario that targets no branch."""
    match = _TARGET_ARM_RE.search(scenario.intent or "")
    return match.group(1).upper() if match else None


def _pinned_fields(scenario: Scenario) -> frozenset[str]:
    """Leaf names (uppercased) of the fields cobol-parser pinned to reach
    the branch `scenario` is named for (`verification.fields`): their
    generated values are the point of the scenario and are never replaced
    by a success default. Empty for the happy path."""
    fields = (scenario.verification or {}).get("fields") or []
    return frozenset(
        str(entry.get("field") or "").upper().rsplit(".", 1)[-1]
        for entry in fields
        if isinstance(entry, dict) and entry.get("field")
    )


def _fixture_pair(fixture: BoundaryFixture) -> tuple[MockCategory, str] | None:
    try:
        return MockCategory(fixture.category), fixture.key
    except ValueError:
        return None


def _bundle_mock_directives(
    scenario: Scenario,
    surface: MockSurface,
    mockymock_keys: dict[tuple[MockCategory, str], BoundarySite],
    registry: TallyRegistry,
    placeholder_keys: frozenset[tuple[str, str]] = frozenset(),
    source: ProgramContext | None = None,
) -> tuple[
    list[str],
    set[tuple[MockCategory, str]],
    dict[tuple[MockCategory, str], CallCountOverride],
]:
    """Every `MOCK ... END-MOCK` block this scenario's TESTCASE needs: real
    fixture data grouped and deduplicated by physical site (see
    `_bundle_directive_for_group`) for everything the bundle generated
    data for, plus a placeholder body (reusing the ordinary,
    already-tested `_directive_for`) for every OTHER mockymock-known site
    -- an OUT-direction boundary the bundle only stubbed (no fixture at
    all, per fixture-bundle-schema.md), or one the bundle doesn't mention
    at all (a genuine key-set gap `_warn_on_key_mismatch` already
    reported). Either way, a boundary this program's own analysis found is
    always mocked with *something*: leaving it unmocked would make the
    generated `.cut` fail `run`/`lint`'s UNMOCKED_* check outright, which
    is worse than a placeholder body a human can improve on. This mirrors
    the ordinary bundle-less scaffold's own "mock everything mockable,
    unconditionally" philosophy (see the module docstring).

    Also returns the exact (category, key) pairs this TESTCASE actually
    declared a MOCK directive for -- when a physical site's OTHER keys
    (a multi-file OPEN/CLOSE's non-primary file) were folded into that one
    directive rather than getting their own, `VERIFY`/`EXPECT` rendering
    (`_render_expectation`) must know to skip them: a `VERIFY OPEN
    RPT-FILE` with no literal `MOCK OPEN RPT-FILE` in this same TESTCASE
    is VERIFY_WITHOUT_MOCK even though "RPT-FILE" is a perfectly valid key
    for the shared site in general.

    And (fix round 2) the `CallCountOverride` `_bundle_directive_for`/
    `_bundle_directive_for_group` computed for each (category, key) whose
    downgrade changed its real call count -- collected here rather than
    recomputed at expectation-rendering time, so `_render_expectation`
    reads the SAME downgrade decision the body rendering above it just
    made instead of re-deriving it from `placeholder_keys` a second time.
    """
    pinned = _pinned_fields(scenario)
    fixtures_by_site: dict[int, list[BoundaryFixture]] = {}
    site_order: list[int] = []
    for fixture in scenario.fixtures:
        try:
            category = MockCategory(fixture.category)
        except ValueError:
            continue
        site = mockymock_keys.get((category, fixture.key))
        if site is None:
            continue  # already reported by _warn_on_key_mismatch
        site_id = id(site)
        if site_id not in fixtures_by_site:
            fixtures_by_site[site_id] = []
            site_order.append(site_id)
        fixtures_by_site[site_id].append(fixture)

    lines: list[str] = []
    declared_keys: set[tuple[MockCategory, str]] = set()
    call_count_overrides: dict[tuple[MockCategory, str], CallCountOverride] = {}
    covered_site_ids: set[int] = set()
    for site_id in site_order:
        group = fixtures_by_site[site_id]
        # A multi-file OPEN/CLOSE is keyed the way the bundle-less scaffold
        # and lint's suggestion key it, so one MOCK can also cover a later
        # single-file statement on the same file (issue #312).
        pair = _fixture_pair(group[0])
        group_site = mockymock_keys.get(pair) if pair is not None else None
        if group_site is not None and len(group_site.keys) > 1:
            preferred = file_op_key(group_site, surface)
            group.sort(key=lambda f: f.key != preferred)
        result = _bundle_directive_for_group(
            group,
            mockymock_keys,
            registry,
            placeholder_keys,
            source,
            pinned,
            _target_paragraph(scenario),
        )
        if result is not None:
            directive, override = result
            lines.extend(
                f"*> NOTE: {_comment_text(note)}"
                for note in dict.fromkeys(
                    note for fixture in group for note in fixture.unresolved
                )
            )
            lines.extend(directive)
            try:
                key_pair = (MockCategory(group[0].category), group[0].key)
                declared_keys.add(key_pair)
                if override is not None:
                    call_count_overrides[key_pair] = override
            except ValueError:
                pass
        covered_site_ids.add(site_id)

    for (category, key), site in mockymock_keys.items():
        if id(site) in covered_site_ids:
            continue
        covered_site_ids.add(id(site))
        placeholder = _directive_for(site, surface)
        if placeholder is None:
            continue
        directive_line, body = placeholder
        if category is MockCategory.DLI and registry.known(category, key):
            body = body + _dli_loop_end_lines(
                site, source, registry.name(category, key)
            )
        if category is MockCategory.CALL and registry.known(category, key):
            body = body + _call_loop_end_lines(
                site, source, registry.name(category, key)
            )
        if category is MockCategory.CICS and registry.known(category, key):
            body = body + _cics_loop_end_lines(
                site, source, registry.name(category, key)
            )
        lines.append(directive_line)
        lines.extend(f"    {line}" for line in body)
        lines.append("END-MOCK")
        declared_keys.add((category, key))

    # Issue #47: a loop-driving downgrade's own CallCountOverride (READ
    # ROWS / SQL ROWS -- the only categories `_bundle_directive_for` ever
    # attaches one to) changes how many times ITS OWN loop runs, which can
    # make any OTHER boundary reached only inside that loop stale too (a
    # CALL made once per row, for instance) -- the bundle's original count
    # assumed the loop's un-downgraded row count. "Reached only inside
    # that loop" is approximated by "declared in the SAME paragraph as the
    # downgraded boundary's own statement" (`site.paragraph_name`,
    # mockymock's own program analysis -- not the bundle's `fixture.
    # paragraph`, so this holds even for a bundle that leaves it blank):
    # exact for the ordinary READ/FETCH-loop-with-inline-CALL shape the
    # issue's own repro uses, though a boundary reached through a nested
    # PERFORM from inside that paragraph still isn't caught. Demoting
    # reuses the same `*>` comment `CallCountOverride.demote_reason`
    # already renders for a downgraded boundary's own unknowable count.
    for (loop_category, loop_key), loop_override in list(call_count_overrides.items()):
        if not loop_override.cascades:
            continue
        loop_site = mockymock_keys.get((loop_category, loop_key))
        if loop_site is None:
            continue
        for other_key_pair in declared_keys:
            if other_key_pair == (loop_category, loop_key):
                continue
            if other_key_pair in call_count_overrides:
                continue
            other_site = mockymock_keys.get(other_key_pair)
            if other_site is None:
                continue
            if other_site.paragraph_name != loop_site.paragraph_name:
                continue
            why = (
                "downgraded by --placeholder -- how many times that loop "
                "actually executes changed"
                if loop_override.from_placeholder
                else "a loop that runs once more than it has rows"
            )
            call_count_overrides[other_key_pair] = CallCountOverride(
                demote_reason=(
                    f"in the same paragraph as {loop_category.value}:"
                    f"{loop_key}, {why}, so this call count is no longer "
                    f"known by construction"
                ),
                from_placeholder=loop_override.from_placeholder,
            )
    return lines, declared_keys, call_count_overrides
