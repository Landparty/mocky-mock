"""Scaffolds a starter .cut file from a MockSurface -- with or without a
cobol-parser fixture bundle.

**Without a bundle** (`bundle=None`): one TESTCASE per paragraph that has
at least one mockable boundary site; the TESTCASE mocks ALL of that
paragraph's mockable sites (deduped by key) -- a scaffold that mocked only
some of them would walk users straight into the refusal gate's UNMOCKED_*
checks (an unmocked CALL has nowhere to link, unmocked file I/O would hit
a nonexistent sandbox file, unmocked EXEC cannot compile, unmocked console
ACCEPT reads stdin). Placeholder bodies are minimal-but-runnable (MOVE 0
TO RETURN-CODE for calls, MOVE 0 TO SQLCODE for SQL, empty for file ops)
and are expected to be replaced with real mock behavior. Nested sites
count as mockable only when `annotate_nested_sites` gave them a validated
splice span; unspliceable nested sites are skipped here and reported by
the CLI's unsupported-boundaries listing instead. The scaffold only covers
each paragraph's OWN sites: boundaries reached transitively through
PERFORM still need their MOCK directives added by hand.

**With a bundle** (`mockymock generate --with-data`, Phase 8 of the
`gen-fixtures` program-scoped test-data initiative): one TESTCASE per
*scenario* instead of per paragraph, `PERFORM <scenario.entry>`, mock
bodies built from the scenario's own generated fixture data (a plain body
for a single-invocation boundary, a tally-branching `EVALUATE` for a
multi-row `READ` sequence, `ROWS (...)` sugar for a multi-row SQL cursor
fetch), and per-scenario `EXPECT`/`VERIFY`/`*> STUB EXPECT` lines from the
bundle's tier 1/2/3 expectations. See
docs/plans/2026-08-02-program-data-generation-implementation.md's Phase 8
and cobol-parser's docs/fixture-bundle-schema.md.

Every mockable site this program's own `mock_surface.analyze()` finds
gets a MOCK directive in every generated TESTCASE, one way or another:
real fixture data when the bundle supplied it, or a placeholder body
(reusing the ordinary bundle-less `_directive_for` logic) otherwise -- an
OUT-direction boundary the bundle only stubbed (a WRITE, a SQL
INSERT/UPDATE/DELETE: the program produces that value, so there's nothing
to mock with), or one the bundle doesn't mention at all (a genuine
key-set gap between the two independent walks, reported by
`_warn_on_key_mismatch` but not otherwise treated specially). Leaving a
reachable site unmocked would make `run`/`lint` refuse the generated
`.cut` outright with UNMOCKED_*, which is worse than a placeholder a
human can improve on. See `_bundle_mock_directives`.

Explicitly out of scope for v1 (see that plan's own Phase 8 section):
collapsing scenarios that differ only in field values on the same
mock/entry shape into one `TESTCASE ... USING PROVIDER` -- every scenario
gets its own TESTCASE, even near-duplicates.
"""

from __future__ import annotations

from mockymock.dsl.generator._context import (
    CallCountOverride,
    ProgramContext,
    _unstring_layouts,
)
from mockymock.dsl.generator.bundle import (
    _bundle_directive_for,
    _bundle_directive_for_group,
)
from mockymock.dsl.generator.counts import _is_boundary_level_ref, _render_expectation
from mockymock.dsl.generator.directives import directive_snippet
from mockymock.dsl.generator.files import (
    _extract_at_end_imperative,
    _lifted_at_end_lines,
    _merged_status_only_body,
    _replicated_at_end_statements,
    _replicated_set_lines,
)
from mockymock.dsl.generator.keys import (
    _bundle_boundary_keys,
    _known_unmockable_keys,
    _mockymock_boundary_keys,
    file_op_key,
    open_site_key,
    read_site_key,
    split_open_files,
    split_read_files,
)
from mockymock.dsl.generator.normalize import _with_site_call_counts
from mockymock.dsl.generator.rows import (
    _bundle_rendered_value,
    _row_move_line,
    _single_row_body,
)
from mockymock.dsl.generator.scaffold import (
    _cancel_cover_lines,
    _first_paragraph,
    scaffold_cut,
)
from mockymock.dsl.generator.sql import _sql_wants_rows

__all__ = [
    "CallCountOverride",
    "ProgramContext",
    "_bundle_boundary_keys",
    "_bundle_directive_for",
    "_bundle_directive_for_group",
    "_bundle_rendered_value",
    "_cancel_cover_lines",
    "_extract_at_end_imperative",
    "_first_paragraph",
    "_is_boundary_level_ref",
    "_known_unmockable_keys",
    "_lifted_at_end_lines",
    "_merged_status_only_body",
    "_mockymock_boundary_keys",
    "_render_expectation",
    "_replicated_at_end_statements",
    "_replicated_set_lines",
    "_row_move_line",
    "_single_row_body",
    "_sql_wants_rows",
    "_unstring_layouts",
    "_with_site_call_counts",
    "directive_snippet",
    "file_op_key",
    "open_site_key",
    "read_site_key",
    "scaffold_cut",
    "split_open_files",
    "split_read_files",
]
