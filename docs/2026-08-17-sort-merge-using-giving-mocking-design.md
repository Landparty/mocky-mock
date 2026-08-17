# mockymock — SORT/MERGE Mocking (USING/GIVING file form + RELEASE/RETURN)

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
which COBOL SORT/MERGE shape it used.

COBOL's SORT/MERGE grammar requires exactly one of {`USING`, `INPUT
PROCEDURE`} and exactly one of {`GIVING`, `OUTPUT PROCEDURE`} (MERGE has no
`INPUT PROCEDURE` clause at all — it always reads via `USING`), giving
three shapes with three very different mockability stories:

1. **Plain file form** (`USING <file>... GIVING <file>...`, no procedure
   clause): the SORT/MERGE statement is a single, self-contained boundary
   statement — structurally identical to READ/WRITE/OPEN/etc. It reads
   named FDs in and writes named FDs out; nothing else in the program
   supplies records to it mid-flight. Fits the existing per-site
   `EVALUATE UT-CURRENT-CASE` dispatch mockymock already uses for every
   other file-op boundary — no new mocking model needed.
2. **Pure procedure form** (SORT only — `INPUT PROCEDURE ... OUTPUT
   PROCEDURE ...`, no `USING`/`GIVING` at all): touches no physical file.
   The program supplies/consumes records through `RELEASE`/`RETURN`
   statements inside its own paragraphs — and those two statements are, on
   inspection, not "an algorithm" at all: `RELEASE record-name` is
   WRITE-shaped (keyed by record name), `RETURN file-name ... AT END ...`
   is READ-shaped (keyed by SD file name, already carries an `AT END`
   clause). Mocking them individually needs no new mechanism either — the
   `SORT`/`MERGE` verb itself can be left real and unspliced (its only
   effect is now entirely mediated through RELEASE/RETURN, which are
   independently mocked), and its INPUT/OUTPUT PROCEDURE paragraphs simply
   need to be reachable to the fail-closed gate the same way a PERFORM
   target is.
3. **Mixed form** (`USING ... OUTPUT PROCEDURE ...` or `INPUT PROCEDURE
   ... GIVING ...`): touches one physical file AND runs a procedure.
   Neither whole-statement replacement (would skip the procedure's other
   logic) nor leaving it real (would touch a physical file mockymock has
   no mechanism to seed/read) is safe. This shape remains genuinely
   unsupported.

This change closes shapes 1 and 2. Shape 3 stays exactly as unsupported as
SORT/MERGE always was.

## Scope

**In scope:**
- A `SortStatement`/`MergeStatement` with no `INPUT PROCEDURE` and no
  `OUTPUT PROCEDURE` clause (`_is_plain_sort_merge` in `mock_surface.py`)
  is classified as `MockCategory.SORT`/`MockCategory.MERGE`, keyed by its
  own SD file name (uppercased) — the same bare-word shape as
  READ/DELETE/START/UNLOCK. New `.cut` grammar: `MOCK SORT <sd-name> ...
  END-MOCK` / `MOCK MERGE <sd-name> ... END-MOCK`.
- A `SortStatement` with BOTH `input_procedure` and `output_procedure` set
  AND no `using_files`/`giving_files` at all (`_is_pure_procedure_sort`;
  MERGE can never satisfy this shape) is left real and unspliced — not
  even recorded as a `BoundarySite` (like `DISPLAY`).
- `ReleaseStatement`/`ReturnStatement` are always classified as mockable
  (`MockCategory.RELEASE` keyed by record name, `MockCategory.RETURN`
  keyed by SD file name), independent of which of the three SORT/MERGE
  shapes above encloses them. New `.cut` grammar: `MOCK RELEASE <record>
  ... END-MOCK` / `MOCK RETURN <sd-name> ... END-MOCK`; `RETURN` also
  joins the `ROWS ( ... ) TERMINAL ( ... )` sugar previously READ-only
  (`MOCK RETURN <sd-name> ROWS ( FIELD = value, ... ) ... TERMINAL ( ...
  )`), since its `AT END` clause is structurally identical to READ's.
- **The reachability BFS models a SORT/MERGE's INPUT/OUTPUT PROCEDURE as
  an implicit PERFORM edge** (`_reachable_paragraphs` in `refusal.py`,
  reusing `_expand_thru_range` for `input_procedure_thru`/
  `output_procedure_thru` exactly like `PERFORM ... THRU`). This is the
  load-bearing correctness piece of the whole feature: a SORT/MERGE
  statement is not a `PerformStatement` AST node, so without this edge, a
  `RELEASE`/`RETURN` (or ANY other boundary statement — a nested `CALL`,
  a file `READ`, anything) reachable only through an INPUT/OUTPUT
  PROCEDURE paragraph is invisible to the fail-closed gate. Confirmed as a
  real gap, not a theoretical one, before this fix landed: `git stash`-ing
  everything but the BFS fix and running `_reachable_paragraphs` against a
  minimal pure-procedure SORT program returned `{'MAIN-PARA'}` — its
  INPUT/OUTPUT PROCEDURE paragraphs entirely absent — exactly the failure
  class the project's 2026-07-07 "reachability-hole remediation" (GO TO,
  PERFORM section, SEARCH WHEN) and 2026-08-12 GO-TO-fall-through closure
  both exist to prevent. Modeled unconditionally for ANY SORT/MERGE with a
  procedure clause (both the pure-procedure and mixed-form shapes) — the
  mixed-form site still refuses the whole test case on its own account
  regardless, so extending the edge there too is conservative, not just
  convenient.
- `mockymock generate` scaffolds `MOCK SORT`/`MOCK MERGE`/`MOCK RELEASE`/
  `MOCK RETURN` stubs for these sites (via `FILE_OP_CATEGORIES`
  membership in `dsl/generator.py`) instead of reporting them as
  unsupported.
- An unmocked reachable site of any of these four categories refuses
  `UNMOCKED_FILE_OP` (the same catch-all code every other file-op category
  defaults to via `_UNMOCKED_CODES` in `refusal.py`) — no new refusal
  codes needed. A `MOCK RETURN ... ROWS` with no `TERMINAL` group
  unconditionally refuses `UNRESOLVED_FILE_STATUS_TARGET` (RETURN is never
  in `FILE_STATUS_CATEGORIES`, so unlike READ there is no FILE-STATUS
  fallback to lean on — widened from a READ-only check).

**Explicitly out of scope:**
- The mixed form (`USING ... OUTPUT PROCEDURE ...` / `INPUT PROCEDURE ...
  GIVING ...`). Stays `category=None`, label `"SORT/MERGE"`,
  `UNSUPPORTED_SORT_MERGE`.
- Simulating the actual sort/merge algorithm, or seeding/reading real
  physical USING/GIVING files on disk. mockymock never touches real files
  for ANY mocked statement (see `.okf/runtime.md`'s sandbox model) — this
  feature doesn't change that. A `.cut` author who mocks `MOCK SORT
  <sd-name>` replaces the ENTIRE statement, same as any other file-op
  mock; a `.cut` author mocking a pure-procedure SORT's `RELEASE`/`RETURN`
  is spying on/replacing individual record-supply calls while the real
  `SORT` verb and its (otherwise-real) INPUT/OUTPUT PROCEDURE paragraphs
  keep running.

## Why almost no splicer changes were needed

`splicer.orchestrator.splice_program` / `injector.build_site_dispatch`
were already fully category-generic: dispatch is built per matched
`(directive.category, directive.key)` against `directive_matches_site`
(itself already generic — category identity, then `directive.key.upper()
in site.keys` for every non-CALL/non-EXEC category). Once
`mock_surface.py` started emitting `BoundarySite`s with
`category=MockCategory.SORT`/`MERGE`/`RELEASE`/`RETURN` instead of `None`,
the splice pipeline handled the plain-file-form SORT/MERGE and RELEASE
with zero further changes — confirmed by tracing hand-built `.cut` files
through `collect_scope_map` → `annotate_nested_sites` → `splice_program`
(see `tests/unit/test_sort_merge_mocking.py`).

The one real gap was `directive.rows`/`FILE_STATUS_CATEGORIES`: RETURN's
`ROWS` dispatch (`injector.build_site_dispatch`) was gated on
`directive.category is MockCategory.READ` specifically, so a `MOCK RETURN
... ROWS` fell through into the SQL-shaped branch and emitted `MOVE ... TO
SQLCODE` — meaningless for a non-SQL boundary. Widened to `directive.category
in (MockCategory.READ, MockCategory.RETURN)`; `refusal.py`'s matching
`UNRESOLVED_FILE_STATUS_TARGET` check was widened the same way.

The BIG gap — and the one piece of this change that's genuinely
correctness-critical, not just plumbing — was the reachability BFS edge
described above. `refusal.py`'s per-site loop itself needed no change: it
already gates on `site.category is None` before reaching the SORT/MERGE-
specific `else` branch, so a now-mockable site (category set) skips that
branch and falls through to the ordinary unmocked/ambiguous/nested/layout
checks every other category already gets — but none of that matters if
the site is never in the reachable set to begin with.

## Alternatives considered

**Mock the whole SORT statement, bypassing INPUT PROCEDURE/OUTPUT
PROCEDURE entirely (for the pure-procedure form).** Rejected: this would
silently skip any OTHER logic those paragraphs contain besides RELEASE/
RETURN (a log write, a counter increment, ...) — a correctness footgun the
RELEASE/RETURN-level approach doesn't have, since the paragraphs keep
running for real and only their two record-supply statements are
intercepted.

**Seed/read real physical files instead of full-statement replacement
(for the plain file form).** Considered and rejected for this pass:
mockymock has no existing mechanism to write host-controlled file content
into the sandbox before a run or read it back after (every other mocked
statement is a pure in-process WORKING-STORAGE/EVALUATE replacement, never
touching disk) — building that would be new sandbox-lifecycle machinery,
not a `mock_surface.py` classification change.

**One shared `MockCategory.SORT_MERGE`.** Rejected: distinct `SORT`/
`MERGE` categories (mirroring the distinct COBOL verbs) keep `MOCK SORT`
and `MOCK MERGE` directives from ever cross-matching a site of the other
verb, the same reasoning `DYNCALL` being distinct from `CALL` already
established in this codebase (see `.okf/dsl.md`).

## See Also

- `.okf/analysis.md` — `mock_surface.py`'s `_is_plain_sort_merge`/
  `_is_pure_procedure_sort` classification, `refusal.py`'s reachability
  edge and per-site table, all updated by this change.
- `.okf/dsl.md` — the `SORT`/`MERGE`/`RELEASE`/`RETURN` grammar rows and
  the widened `ROWS`/`TERMINAL` sugar.
- `tests/unit/test_sort_merge_mocking.py` — classification, grammar,
  reachability-edge, refusal-gate, scaffold, and splice coverage for all
  three shapes.
