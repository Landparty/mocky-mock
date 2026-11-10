"""Lint gate (Phase 8 step 6 of the gen-fixtures initiative): every `.cut`
`mockymock generate --with-data` produces for the examples corpus must
pass `mockymock lint` -- a generator that emits a refusable `.cut` is
worse than none. See
docs/plans/2026-08-02-program-data-generation-implementation.md's Phase 8
step 6 (cobol-parser repo) and `dsl.generator.scaffold_cut`'s own
docstring.

Docker-free by design (`run_static_checks` never imports
mockymock.runtime.docker_toolchain -- see engine/checks.py), so this runs in
every CI lane, not just the Docker-gated one.

Covers every `--scenarios` mode (happy/branches/all), not just the
default: branches/all route through ScenarioPlanner-pinned
witnesses/status-overrides, an entirely different code path from the
happy-path-only contract test in test_fixture_bundle_contract.py.
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
from mockymock.dsl.fixture_bundle import load_fixture_bundle
from mockymock.dsl.generator import scaffold_cut
from mockymock.engine.checks import run_static_checks
from mockymock.splicer.source_map import annotate_nested_sites, collect_scope_map

EXAMPLES_DIR = Path(__file__).parent.parent.parent / "examples"

# Same corpus as tests/unit/test_fixture_bundle_contract.py's PROGRAMS --
# deliberately not imported from there: that module's list is wrapped in
# pytest.param(..., marks=...) for its own xfail bookkeeping, which has no
# bearing on whether a *generated* .cut lints clean here (verified
# separately, manually, for custprog: see this repo's own .okf/log.md).
PROGRAMS = [
    ("ordrproc/ORDRPROC.cbl", None),
    ("invupdt/INVUPDT.cbl", None),
    ("custinq/CUSTINQ.cbl", None),
    ("raterte/RATERTE.cbl", None),
    ("claimseg/CLAIMSEG.cbl", None),
    ("regnavg/REGNAVG.cbl", None),
    ("statelkup/STATELKUP.cbl", None),
    ("taxfile/TAXFILE.cbl", None),
    ("flowmock/FLOWMOCK.cbl", None),
    ("cpyproc/CPYPROC.cbl", ["cpyproc/copybooks"]),
    ("custprog/CUSTPROG.cbl", ["custprog/copybooks"]),
]

SCENARIO_MODES = ["happy", "branches", "all"]


def _generate_cut(
    program_path: Path,
    copybook_paths: list[str] | None,
    mode: str,
    tmp_path: Path,
) -> Path | None:
    """Mirrors cli/main.py::_cmd_generate's --with-data pipeline exactly
    (bundle generation, then a separate raw-source re-read/expand for
    mockymock's own analyze()/annotate_nested_sites() pass) so this test
    exercises the real code path, not a simplified stand-in. Returns None
    when the bundle has zero scenarios (possible for branches/all on a
    program with no branch arms) -- there is genuinely nothing to
    scaffold, matching _cmd_generate's own documented "happy always
    produces exactly one scenario" guarantee."""
    cp_bundle = ProgramFixtureGenerator().generate_with_scenarios_from_file(
        str(program_path), mode=mode, seed=1, copybook_paths=copybook_paths
    )
    if not cp_bundle.scenarios:
        return None
    bundle = load_fixture_bundle(cp_bundle.to_dict())

    raw_source = program_path.read_text(encoding="utf-8")
    if copybook_paths:
        expansion = expand_copybooks(raw_source, copybook_paths=copybook_paths)
        raw_source = expansion.expanded_source
    result = parse_cobol(raw_source, filename=program_path.name)
    assert result.success, result.errors

    lines = normalize_fixed_format(
        strip_compiler_directives(raw_source).splitlines()
    ).splitlines()
    surface = analyze(result.ast)
    annotate_nested_sites(surface, collect_scope_map(result.ast, lines), lines)

    cut_text = scaffold_cut(result.ast.program_name, surface, bundle)
    cut_path = tmp_path / f"{program_path.stem}_{mode}.cut"
    cut_path.write_text(cut_text, encoding="utf-8")
    return cut_path


@pytest.mark.parametrize("mode", SCENARIO_MODES)
@pytest.mark.parametrize(
    "rel_path,copybook_dirs", PROGRAMS, ids=[p[0] for p in PROGRAMS]
)
def test_generated_cut_passes_lint(rel_path, copybook_dirs, mode, tmp_path):
    program_path = EXAMPLES_DIR / rel_path
    copybook_paths = (
        [str(EXAMPLES_DIR / d) for d in copybook_dirs] if copybook_dirs else None
    )

    cut_path = _generate_cut(program_path, copybook_paths, mode, tmp_path)
    if cut_path is None:
        pytest.skip(f"{rel_path}: zero scenarios in mode={mode!r}, nothing to lint")

    result = run_static_checks(program_path, cut_path, copybook_paths)
    assert result.ok, (
        f"{rel_path} (mode={mode}) generated a .cut that fails "
        f"mockymock lint:\n" + "\n".join(result.problems)
    )
