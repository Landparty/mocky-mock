"""File/site mock keys and the mockymock-vs-bundle boundary key sets."""

from __future__ import annotations

import sys

from mockymock.analysis.mock_surface import BoundarySite, MockSurface
from mockymock.dsl.fixture_bundle import FixtureBundle
from mockymock.dsl.model import (
    EXEC_CATEGORIES,
    FILE_OP_CATEGORIES,
    REPORT_WRITER_CATEGORIES,
    MockCategory,
)


def split_read_files(surface: MockSurface) -> set[str]:
    """Files whose READ sites come in more than one access form (READ NEXT
    and a keyed READ of one KSDS, say): each form gets its own `MOCK READ
    <file> <form>`, with its own rows and tally, since one sequence of
    records cannot answer a browse and a lookup alike."""
    forms: dict[str, set[str]] = {}
    for site in surface.boundary_sites:
        if site.category is MockCategory.READ and site.read_form and site.keys:
            forms.setdefault(site.keys[0].upper(), set()).add(site.read_form)
    return {name for name, seen in forms.items() if len(seen) > 1}


def _read_mock_key(site: BoundarySite, split: set[str]) -> str:
    """The upper-case MOCK key a READ site's fixture carries: `<file>
    <form>` for a split file (`read_site_key`), else the file name."""
    return (read_site_key(site, split) or site.keys[0]).upper()


def split_open_files(surface: MockSurface) -> set[str]:
    """Files OPENed by single-file OPEN statements in more than one mode
    (`OPEN EXTEND F`, then `OPEN OUTPUT F` when it is missing, then `OPEN
    INPUT F`): each mode gets its own `MOCK OPEN <file> <mode>`, so a case
    can fail one of them (35 on the EXTEND) and let the others succeed. A
    file of a multi-file OPEN keeps the bare key there."""
    modes: dict[str, set[str]] = {}
    for site in surface.boundary_sites:
        if site.category is MockCategory.OPEN and len(site.keys) == 1:
            name = site.keys[0].upper()
            mode = site.open_modes.get(name)
            if mode:
                modes.setdefault(name, set()).add(mode)
    return {name for name, seen in modes.items() if len(seen) > 1}


def open_site_key(site: BoundarySite, split: set[str]) -> str | None:
    """`<file> <mode>` for a single-file OPEN site of a file in `split`."""
    if site.category is not MockCategory.OPEN or len(site.keys) != 1:
        return None
    name = site.keys[0].upper()
    mode = site.open_modes.get(name)
    return f"{site.keys[0]} {mode}" if name in split and mode else None


def read_site_key(site: BoundarySite, split: set[str]) -> str | None:
    """`<file> <form>` for a READ site of a file in `split`, else None."""
    if (
        site.category is MockCategory.READ
        and site.keys
        and site.read_form
        and site.keys[0].upper() in split
    ):
        return f"{site.keys[0]} {site.read_form}"
    return None


def file_op_key(site: BoundarySite, surface: MockSurface | None) -> str:
    """The key a MOCK for this file-op site uses. A multi-file `OPEN A B`
    is one site matched by a MOCK for any of its files, and two MOCKs
    matching it are AMBIGUOUS_MOCK. When one of its files is also the only
    file of another site of the same verb (`CLOSE B` / `OPEN OUTPUT B`
    after it), keying both on that file lets one MOCK cover both sites;
    keying the multi-file site on its first file left the other site
    needing a second MOCK that the first site then also matched (issue
    #312)."""
    if surface is not None:
        qualified = read_site_key(site, split_read_files(surface)) or open_site_key(
            site, split_open_files(surface)
        )
        if qualified is not None:
            return qualified
    if len(site.keys) > 1 and surface is not None:
        for key in site.keys:
            if any(
                other is not site
                and other.category is site.category
                and other.keys == (key,)
                for other in surface.boundary_sites
            ):
                return key
    return site.keys[0]


def _unique_prefix(site: BoundarySite, surface: MockSurface) -> str:
    """The EXEC key for `site`: the shortest word prefix of its text no
    other same-category site's text starts with, else its full text.

    When another site's whole text is itself a prefix of this one
    (`SYNCPOINT` beside `SYNCPOINT ROLLBACK`, a bare `RETURN` beside
    `RETURN TRANSID(...)`), that site's key -- its full text -- already
    matches this site too, so a second, longer key made the scaffold's
    own directives AMBIGUOUS_MOCK (issue #248). Such a site takes the
    shortest of those texts instead, so both share one directive."""
    words = (site.match_text or "").split()
    if not words:
        return ""
    others = [
        other.match_text or ""
        for other in surface.boundary_sites
        if other.category is site.category and other is not site
    ]
    key = " ".join(words)
    for length in range(1, len(words) + 1):
        prefix = " ".join(words[:length])
        collisions = [o for o in others if o.startswith(prefix)]
        if not collisions:
            key = prefix
            break
    # Imported here: refusal imports the generator.
    from mockymock.analysis.refusal._gates import _exec_match_form, _exec_prefix_matches

    own = _exec_match_form(" ".join(words))
    for other in others:
        other_key = " ".join(other.split())
        if (
            other_key
            and len(other_key) < len(key)
            and _exec_prefix_matches(_exec_match_form(other_key), own)
        ):
            key = other_key
    return key


# --- bundle-driven scaffold (mockymock generate --with-data) -----------------


def _directive_header(category: MockCategory, key: str, site: BoundarySite) -> str:
    """The `MOCK ...` opening line for `(category, key)`, in the exact
    syntax `site` (a matching mockymock BoundarySite) requires -- mirrors
    `_directive_for`'s header logic exactly, factored out so the
    bundle-driven path can reuse it without also inheriting the
    placeholder-body choice."""
    if category is MockCategory.CALL:
        keyword = "MQ" if site.is_mq else "CALL"
        return f'MOCK {keyword} "{key}"'
    if category is MockCategory.DYNCALL:
        return f"MOCK CALL {key}"
    if category in FILE_OP_CATEGORIES:
        return f"MOCK {category.value} {key}"
    if category is MockCategory.ACCEPT:
        return f"MOCK ACCEPT {key}"
    if category in REPORT_WRITER_CATEGORIES:
        return f"MOCK {category.value} {key}"
    return f'MOCK {category.value} "{key}"'  # SQL / CICS / DLI


def _mockymock_boundary_keys(
    surface: MockSurface,
) -> dict[tuple[MockCategory, str], BoundarySite]:
    """First-seen site per (category, key) among surface's mockable sites.

    A multi-file `OPEN`/`CLOSE` (`OPEN INPUT A OUTPUT B`) is one physical
    `BoundarySite` whose `.keys` tuple names *every* file on the
    statement -- registers one dict entry per key, all pointing at the
    same site, since cobol-parser's own `BoundaryInventoryAnalyzer`
    independently reports one `Boundary` per file name for exactly this
    shape (`_classify_file_op`), not one per statement. Every other
    category's `.keys` is always a single entry, so this loop is a no-op
    widening for them. SQL/CICS/DLI key on `_unique_prefix` instead, since
    they have no `.keys` at all (only free-form `match_text`)."""
    keys: dict[tuple[MockCategory, str], BoundarySite] = {}
    split = split_read_files(surface)
    split_opens = split_open_files(surface)
    # A site in the main line before one in DECLARATIVES (which come first
    # in the source): a case's reach is checked against this one site, and
    # a USE procedure is reached only through its file's statements.
    ordered_sites = sorted(
        surface.boundary_sites,
        key=lambda s: s.paragraph_name in surface.declarative_names,
    )
    for site in ordered_sites:
        if site.category is None or (site.nested and site.span is None):
            continue
        qualified = read_site_key(site, split)
        if qualified is not None:
            keys.setdefault((MockCategory.READ, qualified), site)
            continue
        qualified = open_site_key(site, split_opens)
        if qualified is not None:
            keys.setdefault((MockCategory.OPEN, qualified), site)
            continue
        if site.category in EXEC_CATEGORIES:
            prefix = _unique_prefix(site, surface)
            if '"' in prefix:
                # Unrepresentable in the .cut grammar (see _directive_for's
                # quote skip) -- excluding it here makes the bundle path
                # degrade through the existing loud machinery: the key
                # shows up "only in the fixture bundle" in
                # _warn_on_key_mismatch and is left unmocked.
                continue
            pair = (site.category, prefix)
            if pair not in keys:
                keys[pair] = site
            continue
        for key in site.keys:
            if site.category is MockCategory.CALL and '"' in key:
                continue  # same unrepresentable-quote skip as above
            pair = (site.category, key)
            if pair not in keys:
                keys[pair] = site
    return keys


def _bundle_boundary_keys(bundle: FixtureBundle) -> set[tuple[str, str]]:
    """Every (category string, key) pair appearing in ANY scenario's
    fixtures, or as a boundary-level (`"CATEGORY:KEY"`-shaped ref)
    expectation, across the whole bundle -- the union mockymock's own key
    set is compared against (see `_warn_on_key_mismatch`).

    Boundary-level expectations matter here as much as fixtures do: an
    OUT-direction boundary (a WRITE, a SQL INSERT/UPDATE/DELETE) gets NO
    fixture at all (see fixture-bundle-schema.md), only a `kind="stub"`
    expectation -- that `ref` is the *only* place such a boundary's
    (category, key) appears in the bundle, so skipping stub refs here
    would misreport every OUT-direction boundary as a mismatch.
    """
    keys: set[tuple[str, str]] = set()
    for scenario in bundle.scenarios:
        for fixture in scenario.fixtures:
            keys.add((fixture.category, fixture.key))
        for expectation in scenario.expectations:
            if expectation.kind in ("call_count", "stub"):
                category_str, sep, key = expectation.ref.partition(":")
                if sep and _is_known_category(category_str):
                    keys.add((category_str, key))
    return keys


def _known_unmockable_keys(surface: MockSurface) -> set[tuple[str, str]]:
    """(category, key) pairs whose only sites are nested inside a clause
    body with no span -- the shape mockymock already reports as "not
    mockable" and `_mockymock_boundary_keys` skips. cobol-parser's bundle
    still lists them, so without this set every such key showed up as a
    "boundary key mismatch ... should not happen" (issue #164). A key with
    at least one mockable site is in mockymock's own key set and never
    reaches this filter.

    A non-interactive ACCEPT (`ACCEPT X FROM DATE YYYYMMDD`) is in the same
    position: mockymock records it as nothing to mock, while cobol-parser's
    bundle can still list it when a date-format qualifier follows the
    source (BATCHSEQ).

    So is `EXEC SQL WHENEVER`: a precompiler declaration mockymock emulates
    instead of mocking (issue #195), which cobol-parser's bundle lists as
    an SQL boundary keyed `WHENEVER` -- and a PROCEDURE DIVISION `DECLARE
    ... CURSOR` / `INCLUDE` / `BEGIN DECLARE SECTION` (issue #267), keyed by
    its first word."""
    keys: set[tuple[str, str]] = {
        (MockCategory.ACCEPT.value, accept.target)
        for accept in surface.non_interactive_accepts
    }
    for declaration in surface.whenever_sites:
        # WHENEVER (#195), the other precompiler declarations (#267) and
        # CICS HANDLE/IGNORE CONDITION (#268): keyed by their first word.
        if declaration.category is MockCategory.CICS:
            command = getattr(declaration.statement, "cics_command", "") or ""
            keys.add((MockCategory.CICS.value, command.strip().upper()))
            continue
        words = (getattr(declaration.statement, "sql_text", "") or "").split()
        keys.add((MockCategory.SQL.value, words[0].upper() if words else "WHENEVER"))
    for site in surface.boundary_sites:
        if site.category is None or not (site.nested and site.span is None):
            continue
        if site.category in EXEC_CATEGORIES:
            keys.add((site.category.value, _unique_prefix(site, surface)))
            continue
        for key in site.keys:
            keys.add((site.category.value, key))
    return keys


#: Categories cobol-parser's fixture bundle never lays out (issue #262).
_BUNDLELESS_CATEGORIES = frozenset(
    {MockCategory.RELEASE.value, MockCategory.RETURN.value}
)


def _program_supplied_call_keys(program) -> set[tuple[str, str]]:
    """(category, key) of every CALL / DYNCALL boundary in cobol-parser's
    own inventory whose arguments the program supplies all of (each
    `call_args` direction OUT): the bundle counts such a boundary but has
    no fixture or call_count expectation for it -- there is nothing to
    generate -- so its absence from the bundle's keys is no disagreement
    (issue #300). Empty when the inventory cannot be built, which keeps
    the warning loud."""
    if program is None:
        return set()
    try:
        from cobolparser.analysis.boundary_inventory import BoundaryInventoryAnalyzer
        from cobolparser.generators.data.program_layout import ProgramLayoutIndex

        report = BoundaryInventoryAnalyzer().analyze(
            program, ProgramLayoutIndex.build(program)
        )
    except Exception:  # noqa: BLE001 -- a warning helper never fails generate
        return set()
    keys: set[tuple[str, str]] = set()
    for boundary in report.boundaries:
        category = str(getattr(boundary.ref.category, "value", boundary.ref.category))
        if category not in (MockCategory.CALL.value, MockCategory.DYNCALL.value):
            continue
        if all(arg.direction == "OUT" for arg in boundary.call_args or []):
            keys.add((category, str(boundary.ref.key)))
    return keys


def _warn_on_key_mismatch(
    mockymock_keys: dict[tuple[MockCategory, str], BoundarySite],
    bundle_keys: set[tuple[str, str]],
    unmockable_keys: set[tuple[str, str]],
    program_supplied_keys: set[tuple[str, str]] | None = None,
) -> None:
    """Loud, never-silent warning when the two independent boundary walks
    (mockymock's own `mock_surface.analyze()` and cobol-parser's bundle)
    disagree on the (category, key) set -- this mismatch is the
    integration's primary failure mode (see the Phase 8 plan's "the join"
    step). A mockymock-only key gets a placeholder mock body as usual (see
    `_bundle_directive_for`); a bundle-only key has nothing to attach a
    MOCK directive to at all and is simply not mocked -- its `EXPECT`/
    `VERIFY` lines are dropped too (`_render_expectation`), since emitting
    either without a matching MOCK directive would fail `mockymock lint`.
    """
    mockymock_set = {(category.value, key) for category, key in mockymock_keys}
    # The bundle has no fixtures for a SORT's RELEASE / RETURN (they
    # touch the sort work file, not a mockable dataset): their placeholder
    # bodies are the expected path, not a disagreement (issue #262).
    only_in_mockymock = {
        (category, key)
        for category, key in mockymock_set - bundle_keys
        if category not in _BUNDLELESS_CATEGORIES
        and (category, key) not in (program_supplied_keys or set())
    }
    # A key mockymock already lists as "not mockable" is an expected gap,
    # not a disagreement between the two walks.
    only_in_bundle = bundle_keys - mockymock_set - unmockable_keys
    if not only_in_mockymock and not only_in_bundle:
        return
    print(
        "mockymock generate --with-data: WARNING: boundary key mismatch "
        "between this program's own boundary analysis and the fixture "
        "bundle. This should not happen for a program the two independent "
        "walks agree on (see this repo's own "
        "tests/unit/test_fixture_bundle_contract.py) -- mismatched "
        "keys are handled defensively, not silently: a mockymock-only key "
        "falls back to a placeholder mock body; a bundle-only key is left "
        "unmocked (its expectations are dropped rather than emitted "
        "without a matching MOCK directive, which mockymock lint would "
        "refuse).",
        file=sys.stderr,
    )
    if only_in_mockymock:
        print(
            "  only in this program's own boundary analysis (no bundle "
            "fixture/expectation) -- falls back to a placeholder body:",
            file=sys.stderr,
        )
        for category, key in sorted(only_in_mockymock):
            print(f"    {category} {key}", file=sys.stderr)
    if only_in_bundle:
        print(
            "  only in the fixture bundle (no matching boundary site in "
            "this program) -- left unmocked:",
            file=sys.stderr,
        )
        for category, key in sorted(only_in_bundle):
            print(f"    {category} {key}", file=sys.stderr)


def _is_known_category(category_str: str) -> bool:
    try:
        MockCategory(category_str)
    except ValueError:
        return False
    return True
