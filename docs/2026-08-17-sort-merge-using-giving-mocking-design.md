# mockymock — Plain-File-Form SORT/MERGE Mocking (`USING ... GIVING ...`)

Date: 2026-08-17
Status: implemented

## Motivation

SORT/MERGE has been a documented, unstarted backlog item since
`docs/2026-07-06-real-world-readiness-audit.md` ("common in batch; whole
test refused if reachable... each is its own project"), re-confirmed still
open in the 2026-08-10 and 2026-08-12 follow-up audits. Before this
change, `mock_surface.py` classified every `SortStatement`/`MergeStatement`
(plus `ReleaseStatement`/`ReturnStatement`) as unconditionally unmockable
(`category=None`, label `"SORT/MERGE"`), so ANY reachable SORT/MERGE
refused the whole test case with `UNSUPPORTED_SORT_MERGE` — regardless of
which of COBOL's two SORT/MERGE shapes it used.

Those two shapes are not equally hard to mock:

- **INPUT/OUTPUT PROCEDURE form** (`SORT ... INPUT PROCEDURE IS
  <para>...`): the program itself supplies/consumes records through
  `RELEASE`/`RETURN` statements inside arbitrary paragraphs. Mocking this
  means mocking an algorithm plus a procedure *contract*, not a single
  boundary statement — genuinely a separate, much larger project (a new
  mocking model, not a new category).
- **Plain file form** (`SORT ... USING <file>... GIVING <file>...` /
  `MERGE ... USING <file>... GIVING <file>...`, no procedure clause): the
  SORT/MERGE statement is a single, self-contained boundary statement --
  structurally identical to READ/WRITE/OPEN/etc. It reads named FDs in and
  writes named FDs out; nothing else in the program supplies records to it
  mid-flight. This shape needs no new mocking model at all — it fits the
  existing per-site `EVALUATE UT-CURRENT-CASE` dispatch mockymock already
  uses for every other file-op boundary.

This change closes the plain-file-form gap. The INPUT/OUTPUT PROCEDURE
form (and RELEASE/RETURN, which only ever appear inside one) stays exactly
as unsupported as before.

## Scope

**In scope:**
- A `SortStatement`/`MergeStatement` with no `INPUT PROCEDURE` and no
  `OUTPUT PROCEDURE` clause (`_is_plain_sort_merge` in `mock_surface.py`)
  is classified as `MockCategory.SORT`/`MockCategory.MERGE`, keyed by its
  own SD file name (uppercased) — the same bare-word shape as
  READ/DELETE/START/UNLOCK.
- New `.cut` grammar: `MOCK SORT <sd-name> ... END-MOCK` / `MOCK MERGE
  <sd-name> ... END-MOCK` (bare key, `_BARE_CATS` in `parser.py`), and the
  matching `VERIFY SORT <sd-name> WAS CALLED ...` form.
- `mockymock generate` scaffolds a `MOCK SORT`/`MOCK MERGE` stub for a
  plain-form site (via `FILE_OP_CATEGORIES` membership in
  `dsl/generator.py`) instead of reporting it as unsupported.
- An unmocked reachable plain-form site refuses `UNMOCKED_FILE_OP` (the
  same catch-all code every other file-op category defaults to via
  `_UNMOCKED_CODES` in `refusal.py`) — no new refusal code needed.

**Explicitly out of scope** (unchanged from before this change):
- The INPUT/OUTPUT PROCEDURE form. `RELEASE`/`RETURN` always belong to one,
  so both stay `category=None`, label `"SORT/MERGE"`,
  `UNSUPPORTED_SORT_MERGE`.
- A SORT/MERGE mixing `USING` with `OUTPUT PROCEDURE`, or `INPUT
  PROCEDURE` with `GIVING` — any procedure clause at all keeps the
  statement in the unmockable path (`_is_plain_sort_merge` requires BOTH
  `input_procedure is None` and `output_procedure is None`).
- Simulating the actual sort/merge algorithm, or seeding/reading real
  physical USING/GIVING files on disk. A `.cut` author who mocks `MOCK
  SORT <sd-name>` replaces the ENTIRE statement (same as any other
  file-op mock) — the mock body is ordinary COBOL the author writes
  themselves (e.g. `OPEN OUTPUT`/`WRITE`/`CLOSE` against the GIVING file,
  or nothing at all if a downstream `MOCK READ <giving-file>` already
  covers what's consumed from it). mockymock never touches real files for
  ANY mocked statement today (see `.okf/runtime.md`'s sandbox model) —
  this feature doesn't change that.

## Why no splicer changes were needed

`splicer.orchestrator.splice_program` / `injector.build_site_dispatch`
were already fully category-generic: dispatch is built per matched
`(directive.category, directive.key)` against `directive_matches_site`
(itself already generic — category identity, then `directive.key.upper()
in site.keys` for every non-CALL/non-EXEC category), and `directive.rows`/
`FILE_STATUS_CATEGORIES` membership are the only category-specific
branches, neither of which SORT/MERGE opts into. Once `mock_surface.py`
started emitting `BoundarySite`s with `category=MockCategory.SORT`/`MERGE`
instead of `None`, the entire splice pipeline handled them with zero
changes — confirmed by tracing a hand-built `.cut` file through
`collect_scope_map` → `annotate_nested_sites` → `splice_program` (see
`tests/unit/test_sort_merge_mocking.py`'s
`test_splice_program_replaces_plain_sort_with_dispatch`): the SORT
statement's source line(s) are commented out and replaced by the usual
`EVALUATE UT-CURRENT-CASE` block, tally field `UT-SORT-<key>-TALLY`
included.

Likewise `refusal.py`'s per-site loop needed no code change: it gates on
`site.category is None` before reaching the SORT/MERGE-specific `else`
branch, so a plain-form site (now `category` is set) skips that branch
entirely and falls through to the ordinary unmocked/ambiguous/nested/
layout checks every other category already gets.

## Alternatives considered

**Seed/read real physical files instead of full-statement replacement.**
Considered and rejected for this pass: mockymock has no existing mechanism
to write host-controlled file content into the sandbox before a run or
read it back after (every other mocked statement is a pure in-process
WORKING-STORAGE/EVALUATE replacement, never touching disk) — building that
would be new sandbox-lifecycle machinery, not a `mock_surface.py`
classification change, and is a reasonable candidate for a future pass if
a `.cut` author wants their mock to actually exercise GnuCOBOL's real SORT
against literal file content rather than replace the statement outright.

**One shared `MockCategory.SORT_MERGE`.** Rejected: distinct `SORT`/
`MERGE` categories (mirroring the distinct COBOL verbs) keep `MOCK SORT`
and `MOCK MERGE` directives from ever cross-matching a site of the other
verb, the same reasoning `DYNCALL` being distinct from `CALL` already
established in this codebase (see `.okf/dsl.md`).

## See Also

- `.okf/analysis.md` — `mock_surface.py`'s `_is_plain_sort_merge`
  classification and `refusal.py`'s per-site table, both updated by this
  change.
- `.okf/dsl.md` — the `SORT`/`MERGE` grammar rows.
- `tests/unit/test_sort_merge_mocking.py` — classification, grammar,
  refusal-gate, scaffold, and splice coverage for both the newly-mockable
  plain form and the still-unmockable procedure/mixed forms.
