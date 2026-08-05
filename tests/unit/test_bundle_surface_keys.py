"""Broad-corpus complement to `test_fixture_bundle_contract.py`: for every
`examples/*/` program that qualifies (see `EXAMPLE_PROGRAMS` below), the
(category, key) set the cobol-parser fixture bundle references must be a
SUBSET of the (category, key) set `mock_surface.analyze()` finds -- pins
the upstream Phase 8 design requirement that a bundle never names a
boundary mockymock's own walk doesn't also see.

This repo has no `tests/contract/` directory (only `tests/unit` and
`tests/integration`), so the test lives in `tests/unit/`, alongside its
sibling `test_fixture_bundle_contract.py`.

**Why this is a subset check, not an equality check** (`bundle_keys <=
surface_keys`, not `==`): an OUT-direction boundary (a WRITE/REWRITE, an SQL
INSERT/UPDATE/DELETE, an OUT-direction CALL argument) legitimately emits no
bundle fixture at all -- there is nothing to mock, the program *produces*
that value (see cobol-parser's `docs/fixture-bundle-schema.md`'s "No
fixture at all is emitted" rule). So `surface_keys` can be a strict
superset of `bundle_keys` by design, never the reverse: every key the
bundle DOES emit must correspond to a real mockable site, or
`dsl/generator.py`'s bundle-driven scaffold (`_bundle_directive_for`,
keyed off `_mockymock_boundary_keys`) would have nothing to attach that
fixture's data to.

**Why EXEC (SQL/CICS/DLI) needs a second, separate comparison instead of
joining the same `surface_keys` set:** `mock_surface.BoundarySite.keys` is
empty by design for EXEC sites -- `mock_surface.py` matches those by
normalized-text *prefix* (`match_text`), not a stable key (see
`mock_surface.py`'s module docstring). The bundle, on the other hand, gives
an EXEC fixture a `key` derived from the SQL/CICS/DLI verb itself (e.g.
`"SELECT"`, `"DECLARE"`, `"OPEN"`) -- a naive join against `.keys` (empty)
would therefore report every EXEC fixture as unmatched regardless of
correctness. This test instead joins EXEC fixtures/sites on `(category,
str(line))`, mirroring the actual join target: `dsl/generator.py`'s real
`--with-data` path does NOT use a naive `.keys` join for EXEC either -- it
keys `_mockymock_boundary_keys` on `_unique_prefix(site, surface)` (the
shortest word-prefix of `match_text` unique among same-category sites in
that program), which is what `test_fixture_bundle_contract.py` pins
directly, program-by-program, as an equality. This test's line-based join
is a deliberately different, more corpus-robust invariant: it holds
regardless of how many same-verb EXEC statements a program has (an
ambiguous `_unique_prefix` needs a longer, statement-specific prefix to
disambiguate multiple same-verb sites, which a bare-verb line-based check
sidesteps entirely) and runs across every qualifying example, not the
curated program list `test_fixture_bundle_contract.py` hand-maintains --
so it catches a class of bundle/surface disagreement (e.g. a genuinely new
example program regressing) that test wouldn't see until someone remembers
to add the new program to its list.
"""

from pathlib import Path

import pytest
from cobolparser import parse_cobol
from cobolparser.generators import ProgramFixtureGenerator
from cobolparser.preprocess import (
    expand_copybooks,
    normalize_fixed_format,
    strip_compiler_directives,
)

from mockymock.analysis.mock_surface import analyze
from mockymock.dsl.model import EXEC_CATEGORIES
from mockymock.splicer.source_map import annotate_nested_sites, collect_scope_map

# String form of dsl.model.EXEC_CATEGORIES -- a bundle fixture's "category"
# is a plain str (see cobol-parser's docs/fixture-bundle-schema.md), not a
# MockCategory member.
_EXEC_CATEGORY_NAMES = frozenset(category.value for category in EXEC_CATEGORIES)

# Platform-independent match, deliberately NOT `glob("*/[A-Z]*.cbl")`: the
# `[A-Z]*` bracket expression is case-sensitive on every platform (fine --
# every example program is genuinely uppercase-first by COBOL naming
# convention), but a literal `.cbl` suffix in the glob pattern itself is
# case-*insensitive* only on Windows (NTFS) -- on POSIX (CI runs on
# ubuntu-latest) it would silently drop the two uppercase-extension NIST
# programs, `examples/nist-cobol85/IC117M.CBL` and `.../OBIC1A.CBL`, since
# `*.cbl` never matches `*.CBL` there. Matching `[A-Z]*` for the name and
# checking `.suffix.lower()` for the extension separately keeps both
# platforms in agreement.
EXAMPLE_PROGRAMS = sorted(
    p
    for p in Path("examples").glob("*/[A-Z]*")
    if p.suffix.lower() == ".cbl"
    and ((p.parent / "copybooks").exists() or "COPY " not in p.read_text())
)

# Self-guard against a silent shrink of the above: 14 is the current count
# with EXAMPLE_PROGRAMS's filters applied (verified on both Windows and, via
# the reasoning above, POSIX). If this drops, either a real example went
# missing or the platform-independence fix above regressed -- most likely
# by losing IC117M.CBL/OBIC1A.CBL again to a case-sensitivity bug.
assert len(EXAMPLE_PROGRAMS) >= 14, (
    f"EXAMPLE_PROGRAMS shrank to {len(EXAMPLE_PROGRAMS)} -- expected at "
    "least 14, including the uppercase-extension IC117M.CBL/OBIC1A.CBL "
    "(a common regression: a case-sensitive .cbl suffix match drops them "
    "on POSIX); got: "
    f"{sorted(p.parent.name + '/' + p.name for p in EXAMPLE_PROGRAMS)}"
)


@pytest.mark.parametrize("path", EXAMPLE_PROGRAMS, ids=lambda p: p.parent.name)
def test_surface_and_bundle_agree_on_keys(path):
    copybooks = (
        [str(path.parent / "copybooks")]
        if (path.parent / "copybooks").exists()
        else None
    )
    bundle = (
        ProgramFixtureGenerator()
        .generate_with_scenarios_from_file(
            str(path), copybook_paths=copybooks, mode="happy", seed=1
        )
        .to_dict()
    )

    source = path.read_text(encoding="utf-8")
    if copybooks:
        source = expand_copybooks(source, copybook_paths=copybooks).expanded_source
    result = parse_cobol(source, filename=path.name)
    assert result.success, result.errors
    surface = analyze(result.ast)
    # A nested site (a CALL/EXEC inside an IF, PERFORM, etc.) carries
    # `span=None` until annotate_nested_sites stamps it -- skipping this
    # step would silently narrow surface_keys, understating what
    # mock_surface actually covers rather than falsely failing (a
    # subset check only gets MORE permissive as surface_keys shrinks), but
    # matching test_fixture_bundle_contract.py's own established practice
    # here keeps both contract tests exercising the same real pipeline
    # cli/main.py's `_cmd_generate` runs.
    lines = normalize_fixed_format(
        strip_compiler_directives(source).splitlines()
    ).splitlines()
    annotate_nested_sites(surface, collect_scope_map(result.ast, lines), lines)

    # Non-EXEC: same (category, key) join every other test in this repo
    # uses (surface's BoundarySite.keys vs. the bundle fixture's own key).
    surface_keys = {
        (s.category.value, k)
        for s in surface.boundary_sites
        if s.category is not None
        for k in s.keys
    }
    non_exec_bundle_keys = {
        (f["category"], f["key"])
        for s in bundle["scenarios"]
        for f in s["fixtures"]
        if f["category"] not in _EXEC_CATEGORY_NAMES
    }
    assert non_exec_bundle_keys <= surface_keys, non_exec_bundle_keys - surface_keys

    # EXEC (SQL/CICS/DLI): mock_surface carries no stable key for these
    # sites at all (prefix-matched by text instead), so join on line number
    # instead of the key set above, which EXEC keys were never a member of
    # in the first place.
    exec_surface_lines = {
        (s.category.value, str(s.line))
        for s in surface.boundary_sites
        if s.category is not None and s.category.value in _EXEC_CATEGORY_NAMES
    }
    exec_bundle_lines = {
        (f["category"], str(f["line"]))
        for s in bundle["scenarios"]
        for f in s["fixtures"]
        if f["category"] in _EXEC_CATEGORY_NAMES
    }
    assert exec_bundle_lines <= exec_surface_lines, (
        exec_bundle_lines - exec_surface_lines
    )
