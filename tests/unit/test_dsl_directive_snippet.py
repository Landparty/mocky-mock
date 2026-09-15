"""dsl.generator.directive_snippet: the shared MOCK-block renderer behind
RefusalReason.suggested_fix and `generate --fill`. See
docs/2026-09-15-actionable-refusals-and-fill-design.md."""

from cobolparser import parse_cobol

from mockymock.analysis.mock_surface import analyze
from mockymock.dsl.generator import directive_snippet, scaffold_cut

_PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. P.
       PROCEDURE DIVISION.
       0000-MAIN-PROCESS.
           OPEN INPUT INV-FILE.
           READ INV-FILE
               AT END DISPLAY "DONE"
           END-READ.
           CALL "DISCRATE" USING WS-AMT.
           CLOSE INV-FILE.
           STOP RUN.
"""


def _surface():
    result = parse_cobol(_PROGRAM, filename="P.cbl")
    assert not result.errors
    return analyze(result.ast), result.ast


def test_directive_snippet_matches_scaffolds_own_rendering_for_every_site():
    """Regression guard against drift: directive_snippet must render
    exactly what a plain (bundle-less) generate scaffold would produce
    for the same site, since generate's own scaffold is `_directive_for`
    plumbed through `_scaffold_placeholder` with the same 4/8-space
    indentation."""
    surface, _ = _surface()
    scaffolded = scaffold_cut("P", surface)
    for site in surface.boundary_sites:
        if site.category is None:
            continue
        snippet = directive_snippet(site, surface)
        assert snippet is not None
        header = snippet.splitlines()[0].strip()
        assert header in scaffolded


def test_directive_snippet_read_shape():
    surface, _ = _surface()
    read_site = next(s for s in surface.boundary_sites if s.label == "READ")
    snippet = directive_snippet(read_site, surface)
    assert snippet == "    MOCK READ INV-FILE\n    END-MOCK"


def test_directive_snippet_call_shape():
    surface, _ = _surface()
    call_site = next(s for s in surface.boundary_sites if s.label == "CALL")
    snippet = directive_snippet(call_site, surface)
    assert snippet.splitlines()[0].strip() == 'MOCK CALL "DISCRATE"'
    assert snippet.splitlines()[-1].strip() == "END-MOCK"


def test_directive_snippet_none_for_unrenderable_site():
    """A site directive_for itself declines to render (category=None)
    has no mechanical fix."""
    surface, _ = _surface()

    class _FakeSite:
        category = None

    assert directive_snippet(_FakeSite(), surface) is None
