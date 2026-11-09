"""Contract test (Phase 8 of the gen-fixtures initiative): for each example
program, the (category, key) set `mock_surface.analyze()` finds must equal
the set cobol-parser's own `BoundaryInventoryAnalyzer` reports (surfaced
here through a real `FixtureBundle`). This is the test that licenses the
two independent walks `generate --with-data` depends on -- see
docs/plans/2026-08-02-program-data-generation-implementation.md's Phase 8
step 5 and `dsl.generator._warn_on_key_mismatch`.

Every example here is expected to agree exactly (zero mismatch) -- that is
the whole point of pinning it as a contract rather than merely warning at
generation time. A newly-added example that doesn't yet agree should be
investigated (see the fix in cobol-parser's program_fixtures.py this
initiative's own Phase 8 work found empirically -- .okf/log.md), not have
its mismatch silently accepted here.

The one documented exception is custprog/CUSTPROG.cbl, marked
`xfail(strict=True)` below *on cobol-parser releases that cannot expand
`EXEC SQL INCLUDE`*: there it is mockymock-only on `(SQL, FETCH)` because
`expand_copybooks()` had no equivalent of mockymock's own
`splicer/sqlca.py` DCLGEN `EXEC SQL INCLUDE <member>` resolver, so
`CUST-ID`/`CUST-NAME` never became real WORKING-STORAGE items in
cobol-parser's AST and the FETCH boundary's host variables could not
resolve (see the xfail reason for the full empirical trace; `generate
--with-data` degrades safely there with a placeholder `MOCK SQL "FETCH"`
body). cobol-parser's 2026-09-15 release expands `EXEC SQL INCLUDE` from
the copybook path (`CopyStatementLexer(sql_include=True)`); the probe
below detects that, and on such a release custprog is held to the same
contract as every other example.
"""

import inspect
from pathlib import Path

from cobolparser.preprocess.copy_statement_parser import CopyStatementLexer

#: True on a cobol-parser that expands ``EXEC SQL INCLUDE member END-EXEC``
#: like ``COPY`` (2026-09-15 and later): its COPY lexer takes the
#: ``sql_include`` switch the expander turns on.
PARSER_EXPANDS_SQL_INCLUDE = (
    "sql_include" in inspect.signature(CopyStatementLexer.__init__).parameters
)

import pytest
from cobolparser import parse_cobol
from cobolparser.analysis.boundary_inventory import BoundaryInventoryAnalyzer
from cobolparser.generators.data import ProgramLayoutIndex
from cobolparser.generators.program_fixtures import ProgramFixtureGenerator
from cobolparser.preprocess import (
    expand_copybooks,
    normalize_fixed_format,
    strip_compiler_directives,
)

from mockymock.analysis.mock_surface import analyze
from mockymock.dsl.fixture_bundle import load_fixture_bundle
from mockymock.dsl.generator import (
    _bundle_boundary_keys,
    _known_unmockable_keys,
    _mockymock_boundary_keys,
)
from mockymock.splicer.source_map import annotate_nested_sites, collect_scope_map

EXAMPLES_DIR = Path(__file__).parent.parent.parent / "examples"

# (relative path under examples/, copybook dirs relative to examples/<name>/)
PROGRAMS = [
    pytest.param("ordrproc/ORDRPROC.cbl", None, id="ordrproc/ORDRPROC.cbl"),
    pytest.param("invupdt/INVUPDT.cbl", None, id="invupdt/INVUPDT.cbl"),
    pytest.param("custinq/CUSTINQ.cbl", None, id="custinq/CUSTINQ.cbl"),
    pytest.param("raterte/RATERTE.cbl", None, id="raterte/RATERTE.cbl"),
    pytest.param("claimseg/CLAIMSEG.cbl", None, id="claimseg/CLAIMSEG.cbl"),
    pytest.param("regnavg/REGNAVG.cbl", None, id="regnavg/REGNAVG.cbl"),
    pytest.param("statelkup/STATELKUP.cbl", None, id="statelkup/STATELKUP.cbl"),
    pytest.param("taxfile/TAXFILE.cbl", None, id="taxfile/TAXFILE.cbl"),
    pytest.param("flowmock/FLOWMOCK.cbl", None, id="flowmock/FLOWMOCK.cbl"),
    pytest.param(
        "cpyproc/CPYPROC.cbl", ["cpyproc/copybooks"], id="cpyproc/CPYPROC.cbl"
    ),
    pytest.param(
        "custprog/CUSTPROG.cbl",
        ["custprog/copybooks"],
        id="custprog/CUSTPROG.cbl",
        marks=pytest.mark.xfail(
            condition=not PARSER_EXPANDS_SQL_INCLUDE,
            reason=(
                "known v1 gap: cobol-parser's expand_copybooks() does not "
                "understand DCLGEN-style `EXEC SQL INCLUDE CUSTREC "
                "END-EXEC` (only plain COPY statements), unlike mockymock's "
                "own splicer/sqlca.py which resolves it via its own "
                "copybook-path search purely for compiling test runs. "
                "CUST-ID/CUST-NAME therefore never become real "
                "WORKING-STORAGE items in cobol-parser's AST, so "
                "BoundaryInventoryAnalyzer's FETCH boundary has host "
                "variables ProgramFixtureGenerator can't resolve -- it "
                "correctly drops the fixture/expectation rather than "
                "guessing (see cp_bundle.unresolved: 'SQL host variable "
                "CUST-ID/CUST-NAME not resolvable in layout index'), which "
                "leaves (SQL, FETCH) mockymock-only. Verified this degrades "
                "safely: `generate --with-data` emits a placeholder `MOCK "
                'SQL "FETCH"` body via the mockymock-only-key fallback in '
                "_bundle_mock_directives, and the resulting .cut passes "
                "`mockymock lint` clean. Extending cobol-parser's copybook "
                "expansion to handle EXEC SQL INCLUDE is a real but "
                "separate preprocessing feature, out of scope for the "
                "gen-fixtures initiative."
            ),
            strict=True,
        ),
    ),
]


def _key_sets(rel_path: str, copybook_dirs: list[str] | None):
    program_path = EXAMPLES_DIR / rel_path
    copybook_paths = (
        [str(EXAMPLES_DIR / d) for d in copybook_dirs] if copybook_dirs else None
    )
    raw_source = program_path.read_text(encoding="utf-8")
    if copybook_paths:
        expansion = expand_copybooks(raw_source, copybook_paths=copybook_paths)
        raw_source = expansion.expanded_source
    result = parse_cobol(raw_source, filename=program_path.name)
    assert result.success, result.errors

    # Mirrors cli/main.py::_cmd_generate's own pipeline exactly: nested
    # sites (a CALL/EXEC inside an IF, PERFORM, etc.) carry `span=None`
    # until annotate_nested_sites stamps them, and _mockymock_boundary_keys
    # skips any nested site without a validated span (see its own
    # docstring) -- so leaving this step out silently drops every nested
    # boundary from mockymock_set, not just the ones this test happens to
    # exercise.
    lines = normalize_fixed_format(
        strip_compiler_directives(raw_source).splitlines()
    ).splitlines()
    surface = analyze(result.ast)
    annotate_nested_sites(surface, collect_scope_map(result.ast, lines), lines)
    mockymock_keys = _mockymock_boundary_keys(surface)
    mockymock_set = {(category.value, key) for category, key in mockymock_keys}

    index = ProgramLayoutIndex.build(result.ast)
    report = BoundaryInventoryAnalyzer().analyze(result.ast, index)
    # copybook_paths already applied above (expand_copybooks ran on
    # raw_source before parse_cobol) -- .generate() takes an already-parsed
    # AST and has no copybook_paths kwarg of its own, unlike the _from_file
    # variants which do their own expansion.
    cp_bundle = ProgramFixtureGenerator().generate(result.ast, index, report, seed=1)
    bundle = load_fixture_bundle(cp_bundle.to_dict())
    # Keys generate itself knows are not boundaries (a PROCEDURE DIVISION
    # EXEC SQL DECLARE, issue #267; WHENEVER, #195; ...) -- as generate does.
    bundle_set = _bundle_boundary_keys(bundle) - _known_unmockable_keys(surface)

    return mockymock_set, bundle_set


@pytest.mark.parametrize("rel_path,copybook_dirs", PROGRAMS)
def test_boundary_key_sets_agree(rel_path, copybook_dirs):
    mockymock_set, bundle_set = _key_sets(rel_path, copybook_dirs)
    only_in_mockymock = mockymock_set - bundle_set
    only_in_bundle = bundle_set - mockymock_set
    assert only_in_mockymock == set(), (
        f"mock_surface found boundaries the bundle doesn't know about: "
        f"{only_in_mockymock}"
    )
    assert only_in_bundle == set(), (
        f"the bundle references boundaries mock_surface doesn't know about: "
        f"{only_in_bundle}"
    )
