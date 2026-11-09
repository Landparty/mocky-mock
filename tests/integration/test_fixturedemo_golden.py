"""Regression test: the gen-fixtures initiative's worked example (Phase 9 of
cobol-parser's docs/plans/2026-08-02-program-data-generation-*.md).
examples/fixtures/FIXTUREDEMO.cbl and FIXTUREDEMO.bundle.json are copied
verbatim from the sibling cobol-parser repo's own examples/fixtures/ (see
that repo's own golden test, tests/regression/test_fixturedemo_golden.py) --
FIXTUREDEMO.cut is generated here, from that exact checked-in bundle, and
checked in as this repo's own golden.

Deliberately loads the bundle from the checked-in JSON file rather than
regenerating it via ProgramFixtureGenerator: this test's job is to pin
mockymock's OWN generator output, decoupled from whatever cobol-parser
commit happens to be pinned in pyproject.toml at any given moment -- see
--fixtures PATH's own reason for existing (dsl/generator.py's module
docstring, .okf/cli.md's `generate` flow: "CI use, and it keeps the JSON
schema honest").
"""

from pathlib import Path

from cobolparser import parse_cobol
from cobolparser.preprocess import normalize_fixed_format, strip_compiler_directives

from mockymock.analysis.mock_surface import analyze
from mockymock.cli.main import main
from mockymock.dsl.fixture_bundle import load_fixture_bundle_file
from mockymock.dsl.generator import ProgramContext, scaffold_cut
from mockymock.engine.checks import run_static_checks
from mockymock.splicer.source_map import annotate_nested_sites, collect_scope_map
from tests.integration._docker import requires_docker

EXAMPLE_DIR = Path(__file__).parent.parent.parent / "examples" / "fixtures"


def _generate_cut_text() -> str:
    program_path = EXAMPLE_DIR / "FIXTUREDEMO.cbl"
    bundle = load_fixture_bundle_file(EXAMPLE_DIR / "FIXTUREDEMO.bundle.json")

    raw_source = program_path.read_text(encoding="utf-8")
    result = parse_cobol(raw_source, filename=program_path.name)
    assert result.success, result.errors

    lines = normalize_fixed_format(
        strip_compiler_directives(raw_source).splitlines()
    ).splitlines()
    surface = analyze(result.ast)
    annotate_nested_sites(surface, collect_scope_map(result.ast, lines), lines)

    # The same ProgramContext `_cmd_generate` passes: without it the scaffold
    # emits no CAPTURE ARG lines (and no `*> STUB EXPECT` for them), so the
    # text would silently diverge from what `mockymock generate --fixtures`
    # actually writes -- which is what this golden pins.
    return scaffold_cut(
        result.ast.program_name,
        surface,
        bundle,
        source=ProgramContext.build(result.ast, lines, surface),
    )


def test_fixturedemo_cut_matches_checked_in_golden():
    generated = _generate_cut_text()
    golden = (EXAMPLE_DIR / "FIXTUREDEMO.cut").read_text(encoding="utf-8")
    assert generated == golden


def test_fixturedemo_cut_is_deterministic():
    assert _generate_cut_text() == _generate_cut_text()


def test_fixturedemo_committed_cut_passes_lint():
    result = run_static_checks(
        EXAMPLE_DIR / "FIXTUREDEMO.cbl", EXAMPLE_DIR / "FIXTUREDEMO.cut", None
    )
    assert result.ok, result.problems


@requires_docker
def test_committed_fixturedemo_example_passes():
    exit_code = main(
        [
            "run",
            str(EXAMPLE_DIR / "FIXTUREDEMO.cbl"),
            "--cut",
            str(EXAMPLE_DIR / "FIXTUREDEMO.cut"),
        ]
    )
    assert exit_code == 0
