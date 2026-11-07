"""Fixture-bundle normalization passes run before scaffolding: READ forms,
OPEN modes, per-site call counts and ACCEPT keys."""

from __future__ import annotations

import re
from dataclasses import replace

from mockymock.analysis.mock_surface import BoundarySite, MockSurface, accept_key
from mockymock.dsl.fixture_bundle import BoundaryFixture, Expectation, FixtureBundle
from mockymock.dsl.generator.keys import (
    open_site_key,
    split_open_files,
    split_read_files,
)
from mockymock.dsl.model import MockCategory

#: The fixed scenario family whose failure path cobol-parser (3.1+) leaves
#: uncounted on purpose: the program's error path may skip the READ loop or
#: the CLOSE, so only the failed boundary's own count is known.
_ERROR_STATUS_SCENARIO_PREFIX = "error status:"
#: The file-status family (`file status 23: START CUST`): one statement is
#: given a status the program tests, so its flow after that statement is the
#: failure path too -- a browse loop driven by the status a failed START
#: leaves behind never runs (issue #430).
_FILE_STATUS_SCENARIO = re.compile(r"^file status \w{2}:", re.IGNORECASE)


def _is_failure_path_scenario(name: str) -> bool:
    """Whether a scenario injects a failing status, so that cobol-parser
    leaves the counts after it uncounted on purpose and no per-site count
    may be restored (`_with_site_call_counts`)."""
    return name.lower().startswith(_ERROR_STATUS_SCENARIO_PREFIX) or bool(
        _FILE_STATUS_SCENARIO.match(name)
    )


#: The cobol-parser note on a keyed READ whose key it cannot know; a
#: keyed READ mock keeps the key the program asked for instead.
_UNKNOWN_READ_KEY_NOTE = "the record key it reads by has no value known"


def _with_read_forms(bundle: FixtureBundle, surface: MockSurface) -> FixtureBundle:
    """`bundle` with each READ fixture fitted to the form of its READ site.

    - A keyed READ (`KEY` / `KEY <alternate key>`) never moves to the key
      it reads by: the record a KSDS returns has the key the program asked
      for, so the program's own value stays.
    - A status no READ of that form can give is dropped to success: an
      INVALID KEY code (2x) on a READ NEXT / PREVIOUS, an end-of-file code
      (1x) on a keyed READ. A file-wide error-status scenario otherwise
      left a browse loop reading "23" forever.
    - A file read in several forms (`split_read_files`) has its fixtures
      keyed `<file> <form>` by the site at their line, so the browse and
      the keyed lookup of one KSDS get their own MOCK. Its file-level call
      counts are dropped: the per-form ones are restored per site
      (`_with_site_call_counts`)."""
    reads = [
        site
        for site in surface.boundary_sites
        if site.category is MockCategory.READ and site.keys and site.read_form
    ]
    if not reads:
        return bundle
    split = split_read_files(surface)
    sites = {(site.keys[0].upper(), site.line): site for site in reads}
    first: dict[str, BoundarySite] = {}
    for site in reads:
        first.setdefault(site.keys[0].upper(), site)
    dropped = {f"{MockCategory.READ.value}:{name}" for name in split}
    scenarios = []
    for scenario in bundle.scenarios:
        fixtures = []
        for fixture in scenario.fixtures:
            name = fixture.key.upper()
            if fixture.category == MockCategory.READ.value and name in first:
                site = sites.get((name, fixture.line or 0)) or first[name]
                fixture = _fit_read_fixture(fixture, site, surface)
                if name in split:
                    fixture = replace(fixture, key=f"{name} {site.read_form}")
            fixtures.append(fixture)
        expectations = [
            e
            for e in scenario.expectations
            if not (e.kind == "call_count" and e.ref.upper() in dropped)
        ]
        scenarios.append(
            replace(scenario, fixtures=fixtures, expectations=expectations)
        )
    keyed_lines = {
        site.line
        for site in reads
        if site.read_form == "KEY" or str(site.read_form).startswith("KEY ")
    }
    unresolved = [
        note
        for note in bundle.unresolved
        if not (
            _UNKNOWN_READ_KEY_NOTE in note
            and any(f"(line {line})" in note for line in keyed_lines)
        )
    ]
    return replace(bundle, scenarios=scenarios, unresolved=unresolved)


def _with_open_modes(bundle: FixtureBundle, surface: MockSurface) -> FixtureBundle:
    """`bundle` with the OPEN fixtures of each file opened in several modes
    (`split_open_files`) keyed `<file> <mode>` by the site at their line,
    so a case that fails the OPEN EXTEND (35) does not fail the OPEN OUTPUT
    that creates the file, or the OPEN INPUT that reads it back. Their
    file-level call counts are dropped; `_with_site_call_counts` restores
    one per mode."""
    split = split_open_files(surface)
    if not split:
        return bundle
    sites = {
        (site.keys[0].upper(), site.line): site
        for site in surface.boundary_sites
        if site.category is MockCategory.OPEN and len(site.keys) == 1
    }
    dropped = {f"{MockCategory.OPEN.value}:{name}" for name in split}
    scenarios = []
    for scenario in bundle.scenarios:
        fixtures = []
        for fixture in scenario.fixtures:
            name = fixture.key.upper()
            if fixture.category == MockCategory.OPEN.value and name in split:
                site = sites.get((name, fixture.line or 0))
                key = open_site_key(site, split) if site is not None else None
                if key is not None:
                    fixture = replace(fixture, key=key.upper())
            fixtures.append(fixture)
        expectations = [
            e
            for e in scenario.expectations
            if not (e.kind == "call_count" and e.ref.upper() in dropped)
        ]
        scenarios.append(
            replace(scenario, fixtures=fixtures, expectations=expectations)
        )
    return replace(bundle, scenarios=scenarios)


def _fit_read_fixture(
    fixture: BoundaryFixture, site: BoundarySite, surface: MockSurface
) -> BoundaryFixture:
    """One READ fixture fitted to its site's form (`_with_read_forms`)."""
    form = site.read_form or "NEXT"
    keyed = form == "KEY" or form.startswith("KEY ")
    impossible = "1" if keyed else "2"
    status = {
        name: ("00" if code.startswith(impossible) else code)
        for name, code in fixture.status.items()
    }
    if not keyed:
        return replace(fixture, status=status)
    select = surface.file_selects.get(site.keys[0].upper())
    key_field = form[len("KEY ") :] if form != "KEY" else None
    if key_field is None and select is not None and select.organization == "INDEXED":
        key_field = select.record_key
    layout = [
        spec
        for spec in fixture.layout
        if key_field is None or str(spec.name).upper() != key_field
    ]
    unresolved = [
        note for note in fixture.unresolved if _UNKNOWN_READ_KEY_NOTE not in note
    ]
    return replace(fixture, status=status, layout=layout, unresolved=unresolved)


def _with_site_call_counts(
    bundle: FixtureBundle, surface: MockSurface
) -> FixtureBundle:
    """`bundle` with one `call_count` per fixture (per call site) for every
    mocked (category, key) the bundle gave none.

    Before 3.1, cobol-parser counted every fixture: 1 for a CALL or a
    status-only boundary, and the row count (plus the call that hits end of
    file, when the statement has AT END) for one that is fed rows. Since
    3.1 (cobol-parser #363) it writes one count per (category, key), and
    only when control flow makes it exact. `generate` does that exactness
    analysis itself, per case and entry (`_conditional_call_count_keys`),
    and adds counts the bundle cannot know (the extra MQGET or DL/I call
    that ends a drain loop, a FILE STATUS read loop's end-of-file read), so
    it needs a count to start from for every mocked key: a key the bundle
    left uncounted gets the per-site counts back, and the analysis demotes
    them to a commented VERIFY or corrects them as before. A count the
    bundle did write is kept as it is. An "error status" or "file status"
    scenario is left alone: there the bundle drops counts because the
    failure path makes them untrue, which no per-site count can repair --
    a happy-path READ NEXT count on a case whose START failed is a VERIFY
    the generated case cannot pass (issue #430)."""
    scenarios = []
    for scenario in bundle.scenarios:
        if _is_failure_path_scenario(scenario.name):
            scenarios.append(scenario)
            continue
        counted = {e.ref for e in scenario.expectations if e.kind == "call_count"}
        added = [
            Expectation(
                kind="call_count",
                ref=f"{fixture.category}:{fixture.key}",
                value=_site_call_count(fixture, surface),
                note="one per call site, restored by mockymock",
            )
            for fixture in scenario.fixtures
            if f"{fixture.category}:{fixture.key}" not in counted
        ]
        if added:
            scenario = replace(scenario, expectations=[*scenario.expectations, *added])
        scenarios.append(scenario)
    return replace(bundle, scenarios=scenarios)


def _site_call_count(fixture: BoundaryFixture, surface: MockSurface) -> int:
    """The count cobol-parser before 3.1 gave one fixture (see
    `_with_site_call_counts`)."""
    if fixture.direction == "STATUS_ONLY" or fixture.category in (
        MockCategory.CALL.value,
        MockCategory.DYNCALL.value,
    ):
        return 1
    at_end = fixture.terminal is not None
    for site in surface.boundary_sites:
        if (
            site.category is not None
            and site.category.value == fixture.category
            and site.line == fixture.line
        ):
            at_end = bool(getattr(site.statement, "at_end_clause", None))
            break
    return len(fixture.sequence) + (1 if at_end else 0)


def _with_accept_keys(bundle: FixtureBundle) -> FixtureBundle:
    """`bundle` with every ACCEPT fixture and expectation keyed on the
    target's data-name, as mockymock keys the site (issue #311):
    cobol-parser keys it on the whole target (`FLD OF REC-B`, `WS-ENT ( WS-I
    )`), which no `MOCK ACCEPT` line can spell. Two fixtures that now share
    a key (`ACCEPT FLD OF REC-A` and `OF REC-B`) keep the first: one MOCK
    answers both sites; their call counts are summed downstream."""
    prefix = f"{MockCategory.ACCEPT.value}:"
    scenarios = []
    for scenario in bundle.scenarios:
        fixtures: list[BoundaryFixture] = []
        seen: set[str] = set()
        for fixture in scenario.fixtures:
            if fixture.category == MockCategory.ACCEPT.value:
                key = accept_key(fixture.key)
                if key in seen:
                    continue
                seen.add(key)
                fixture = replace(fixture, key=key)
            fixtures.append(fixture)
        expectations = [
            (
                replace(e, ref=prefix + accept_key(e.ref[len(prefix) :]))
                if e.ref.startswith(prefix)
                else e
            )
            for e in scenario.expectations
        ]
        scenarios.append(
            replace(scenario, fixtures=fixtures, expectations=expectations)
        )
    return replace(bundle, scenarios=scenarios)
