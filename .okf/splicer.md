---
type: Module
title: Splicer
description: Turns mock_surface boundary sites into spliced COBOL source — dispatch blocks, tally fields, WORKING-STORAGE reset, and the generated SQLCA.
tags: [splicer, injection, cobol-source]
timestamp: 2026-07-08T00:00:00Z
---

# Overview

The splicer is the codegen back-end: it takes a `MockSurface` (boundary
sites found by [analysis](analysis.md)'s `mock_surface`) plus a parsed
`MockTestSuite` ([dsl](dsl.md)) and produces the final COBOL text that
`mockymock run`/`mockymock generate` compiles with GnuCOBOL. Everything it
edits is **cobolparser's normalized free-form text**
(`cobolparser.preprocess.normalize_fixed_format` output), never the
original file — `SourceLocation.line` values from the AST are indexed into
that normalized text, so splicing the original would corrupt line offsets.
See [integration](integration.md).

```
MockSurface (boundary sites)  ─┐
MockTestSuite (parsed .cut)   ─┼─▶ orchestrator.splice_program ──▶ spliced lines
normalized COBOL lines        ─┘        │
                                         ├─ source_map: site → (start,end) span
                                         ├─ injector: span → EVALUATE dispatch / EXEC trap
                                         ├─ naming.TallyRegistry: (category,key) → UT-*-TALLY
                                         └─ stub_writer: comment span, insert replacement

driver.build_driver ──▶ UT-TESTSUITE-*/UT-TESTCASE-*/UT-RESET-WORKING-STORAGE
                        paragraphs, prepended as the new PROCEDURE DIVISION
                        entry point (original first paragraph never runs
                        automatically again)

reset.reset_move_lines ──▶ MOVE/INITIALIZE lines consumed by build_driver
                            as UT-RESET-WORKING-STORAGE's body

sqlca.transform_data_division_exec ──▶ runs on DATA DIVISION AFTER
                                        splice_program (see below), independently
```

**Ordering correction (fixes audit finding 7.1 — this file previously said
SQLCA ran "before any of the above"):** `mockymock/cli/main.py`'s `_cmd_run`
calls `transform_data_division_exec` **after** `splice_program`, not before.
The reason is line-number safety, not codegen convenience: every
PROCEDURE DIVISION splice span in `splice_program` is computed from
`SourceLocation.line` values the AST assigned against the pre-SQLCA-transform
text. `transform_data_division_exec` inserts/removes lines in the DATA
DIVISION (the generated `SQLCA_FIELDS` block is longer than the one-line
`EXEC SQL INCLUDE SQLCA END-EXEC.` it replaces); running it first would
shift every PROCEDURE DIVISION line number the splicer's spans depend on,
corrupting every span in a program that uses `INCLUDE SQLCA`. The CLI does
call `transform_data_division_exec` once, read-only-style, **before**
`splice_program` too — but only to collect `UNSUPPORTED_DATA_DIVISION_EXEC`
refusal reasons up front (so a bad DATA DIVISION EXEC SQL block is reported
before any compile attempt); it discards that call's transformed lines and
re-runs the transform for real after splicing, on the post-splice `lines`.

One compiled binary serves an entire TESTSUITE (Global Constraint), which
drives most of the design here: all TESTCASEs share one physical copy of
each mocked statement, so dispatch must happen at runtime via
`UT-CURRENT-CASE`, and WORKING-STORAGE must be explicitly reset between
cases rather than relying on process restart.

# Splice-Point Detection (source_map.py)

cobolparser's `SourceLocation` gives only a statement's **start** line.
`source_map.py` derives the *end* of a replacement span two different ways
depending on whether the site is top-level or nested.

**Top-level sites** (`collect_boundaries` + `statement_span`): the span
runs from the statement's start line to one line before the next
SECTION-header/paragraph-header-or-statement-start, or EOF if it's the
program's last statement. `collect_boundaries` walks every SECTION header
(`procedure._sections.values()`, keyed by `.location.line`), every
paragraph (including nested `_sections`), and every statement's
`.location.line`.

**SECTION headers are boundaries (2026-07-07 fix, audit finding 2.2):**
before this fix `collect_boundaries` collected only paragraph headers and
statement starts, so a paragraph's last statement immediately followed by
an `X SECTION.` header (no intervening paragraph header) had no boundary
between them — its span extended over and commented out the following
section header. Verified concretely: span `(6, 7)` swallowing a
`NEXT-SEC SECTION.` line. If that previous section were itself PERFORMed
as a section (see [analysis](analysis.md)'s PERFORM-section reachability
fix), its extent would then silently include the following section's
paragraphs too. `collect_scope_map` gained the identical fix, as a
`top_level=True` `ScopeBoundary` — both maps must agree on where a
top-level span may legally end.

**Phantom `"."` paragraphs**: cobolparser emits a paragraph literally named
`"."` for the sentence-terminating period line after an `EXEC ... END-EXEC`
block (verified empirically — a program with two EXEC SQL paragraphs
yields two extra `"."` paragraphs anchored at the END-EXEC lines).
`collect_boundaries` filters these out by checking
`paragraph.paragraph_name.strip(".") == ""`: treating one as a real
boundary would cut an EXEC statement's span one line short of its
END-EXEC, leaving a dangling END-EXEC in the spliced output.

## Top-Level Own-Line Guard (2026-07-07 fix, audit finding 2.1)

Before this fix, only NESTED sites got a "does this statement own its
source line(s)" check — top-level sites had none. Because a top-level
splice comments out *whole lines* (`stub_writer.comment_and_replace`),
that meant sibling code sharing a top-level boundary statement's line was
silently deleted: `MOVE 1 TO WS-A CALL "X" USING WS-A.` on one line got
its entire line commented out, deleting the MOVE, and the program still
compiled — a silent correctness bug, not a loud refusal. Same class: a
one-line paragraph `P1. CALL "X".` lost its paragraph header; two mocked
statements sharing one line could corrupt each other's replacement.

`annotate_nested_sites` now also walks every **top-level** `BoundarySite`
(previously it skipped anything with `site.nested is False`) and computes
`_top_level_site_problem`: a `str | None` reason stored in
`site.unspliceable_reason` (the site's `.span` stays `None` for top-level
sites — their replacement span still comes from `statement_span`, not this
field). The check is deliberately narrower than the nested one, because a
top-level span already extends up to (but not including) the *next*
boundary line — the only way sibling code can be swallowed is by sharing
the **start** line:

1. Text before the statement's column on its start line (`lines[start-1][:col-1].strip()`)
   → `"does not start its own line"` (catches both mid-line siblings and
   one-line paragraph headers, since a paragraph header text before the
   statement fails the same check).
2. Another top-level `ScopeBoundary` (`b.top_level` — a different
   statement or a paragraph/SECTION header) on the same line, at a
   different column → `"shares its line with another statement or
   paragraph header"` (this is what makes two mocked statements on one
   line mutually refuse instead of corrupting each other: the first
   statement fails check 2, the second fails check 1).

`refusal.check_test_case` turns a matched top-level site's
`unspliceable_reason` into `UNSUPPORTED_MOCK_TARGET_LAYOUT`;
`refusal.check_nested_exec` turns an EXEC site's into `UNSPLICEABLE_EXEC`
(EXEC sites are stubbed program-wide regardless of mock/reachability, so
that check lives in the whole-program EXEC gate, not the per-case one).
`orchestrator.splice_program` raises defensively if a top-level site with
a nonempty `unspliceable_reason` reaches it anyway — the refusal gate is
supposed to have caught it first, mirroring the existing nested-span
invariant check.

**Nested sites** (inside IF/ELSE, EVALUATE WHEN, inline PERFORM) need a
richer map because the AST has no location data for block words (ELSE,
WHEN, END-IF, ...) — "whatever comes next" from the plain boundary list
could be a terminator the span must not swallow. `collect_scope_map`
re-lexes the normalized text with `CobolLexer` to recover every scope-word
token's line/column, unions it with statement starts *at every depth*
(not just top-level), and excludes tokens that fall inside an
`EXEC ... END-EXEC` range (embedded SQL/CICS text may legally contain
WHEN/ELSE words that are not COBOL block words — `_exec_range` /
`_inside_exec_range` handle this).

`annotate_nested_sites` then stamps every nested `BoundarySite` with either
a validated `.span` or a precise `.unspliceable_reason` string (fail
closed) — see the spliceability rules in
[docs/2026-07-05-nested-mock-targets-design.md](../docs/2026-07-05-nested-mock-targets-design.md).
Key preconditions checked there: no ancestor is itself a boundary
statement, the site has no clause bodies of its own, it owns its start
line (own-verb terminators like END-CALL/END-READ are exempt — they
belong to the statement per `_VERB_TERMINATORS`), the next boundary owns
its line too, and (EXEC only) the span's text actually contains
`END-EXEC`. This must run **before** the refusal gate and the splicer look
at nested sites — it is idempotent.

# Dispatch and Trap Generation (injector.py)

`build_site_dispatch(site, suite, registry)` builds one `EVALUATE
UT-CURRENT-CASE` block per **site** (not per mock key): different test
cases can match the same physical statement through different keys (e.g.
case 1 mocks `OPEN IN-FILE`, case 2 mocks `OPEN OUT-FILE`, both matching
one `OPEN INPUT IN-FILE OUTPUT OUT-FILE` statement). Each matching case
gets a `WHEN "NNN"` branch that increments that case's own tally
(crediting the directive that matched) then splices in `directive.body_lines`
verbatim. A `WHEN OTHER` branch is always appended: if control reaches a
mocked site under a test case that doesn't mock it, that's a hard,
loud failure (`__MOCKYMOCK__ ERROR: ... reached from unmocked test case`),
never a silent fall-through.

`build_exec_trap(kind, line)` is the replacement for an **unmocked** EXEC
SQL/CICS/DLI site: GnuCOBOL cannot compile a raw EXEC block regardless of
reachability, so every EXEC site must be spliced program-wide even when no
test case mocks it. The refusal gate is supposed to guarantee such a site
is unreachable from every test case; the trap exists so that if
reachability analysis and reality ever disagree, the mismatch fails loudly
at runtime instead of silently doing nothing.

# Orchestration and Ordering Invariant (orchestrator.py)

`splice_program` computes every span **up front** against the original
(pre-splice) line numbers, then applies them to `lines` in **descending
start-line order**. This ordering is load-bearing: `comment_and_replace`
returns a list that has grown by `len(replacement)` lines, which would
silently shift every later (higher-line-number) not-yet-applied span if
splices were applied top-down instead. This was caught concretely during
review: a top-down splice landed one line short and commented out the
*next paragraph's header* instead of its CALL statement. Bottom-up
application keeps every unapplied span's line numbers valid throughout.

Other invariants enforced here:

- **Dedup by `id(statement)`**: several `BoundarySite` entries can
  reference one physical statement through distinct sites in the same
  paragraph list; each physical statement gets exactly one splice
  (`seen_statement_ids`).
- **Nested-span invariant**: a nested site reaching the splicer without a
  validated `site.span` raises — the refusal gate
  (`UNSUPPORTED_NESTED_MOCK_TARGET` / `NESTED_EXEC`) should have refused
  it first. This is a defensive check, not expected to fire in normal
  operation.
- **Trailing-period propagation**: if the last non-blank line of the
  replaced span ends with `.`, the replacement's last line gets that
  period appended. Otherwise, if the replaced statement was the final
  statement of its sentence/paragraph, the replacement leaves an
  unterminated sentence that runs into the next paragraph header and cobc
  rejects the whole program.
- **Unmocked non-EXEC sites are left untouched** — plain COBOL, no splice
  at all (if one were reachable, the refusal gate already fired before
  codegen).

# Tally-Field Naming (naming.py)

`TallyRegistry` assigns one `UT-*-TALLY` WORKING-STORAGE field per
`(category, key)` mocked anywhere in the suite, in first-appearance order,
deterministically for a given `.cut` file.

| Category | Body format | Example |
|---|---|---|
| `CALL` (static, quoted) | key only, no category prefix | `MOCK CALL "PGMA"` → `UT-PGMA-TALLY` |
| `DYNCALL` (bare identifier) | `CALL <key>` — the `.cut` keyword, not the internal category name | `MOCK CALL WS-PGM-NAME` → `UT-CALL-WS-PGM-NAME-TALLY` |
| everything else | `<category.keyword> <key>` | `MOCK OPEN IN-FILE` → `UT-OPEN-IN-FILE-TALLY`; `MOCK SQL "UPDATE..."` → `UT-SQL-UPDATE...-TALLY` |

`CALL` keeps v1's un-prefixed shape so existing `.cut` files whose mock
bodies reference tally fields by name keep working. `DYNCALL` deliberately
prefixes with its surface keyword `CALL` (what a `.cut` author would guess
from writing `MOCK CALL WS-PGM-NAME`) specifically so it can **never
collide** with a static CALL's tally for the same spelling — the two
categories are always distinguishable by name.

Body text is sanitized (non-COBOL-word chars → `-`, collapsed, trimmed)
and capped at 21 chars so `"UT-" + body + "-TALLY"` stays a conservative
30-char COBOL word (well under GnuCOBOL's 63-char limit). Sanitized keys
can collide (two SQL prefixes differing only in punctuation, or only
beyond the length cap) — collisions are resolved by suffixing `-2`, `-3`,
... in first-appearance order, so naming is still fully deterministic per
`.cut` file.

`driver.py`'s `_SUITE_PARAGRAPH_NAME_RE` sanitization for the
`UT-TESTSUITE-*` paragraph name follows the identical collapse-and-strip
pattern (a title like `"X (via copybook)"` must not yield a
trailing-hyphen COBOL word — cobc rejects that outright).

**Field widths widened (2026-07-07 fix, audit findings 2.5, 2.7):**
`UT-FAIL-COUNT` and every `UT-*-TALLY` field were `PIC 9(4)` and wrapped
silently at 10,000 — `VERIFY ... 500 TIMES` would pass with 10,500 actual
calls, `VERIFY ... NEVER` would pass at exactly 10,000 calls, and the
`SUMMARY` fail count wrapped identically. Batch loops of that size are
realistic in the target domain, so both are now `PIC 9(9)`.
`UT-CURRENT-CASE` was `PIC X(3)` and unguarded — a suite with 1000+ test
cases would `MOVE "1000" TO UT-CURRENT-CASE` truncated to `"100"`, so
case 1000 would actually execute case 100's mock dispatch branches (a
silent misattribution, not a compile error). It is now `PIC X(9)`,
matching `_build_testcase_paragraph`'s `f"{index:03d}"` zero-padding
convention (still 3-digit-padded for small suites, but no longer
truncating past 999) and the injector's `WHEN "{index:03d}"` literals in
`injector.build_site_dispatch`, which must stay in sync with this field's
width.

# WORKING-STORAGE Reset (reset.py)

Because one binary serves the whole suite, case N's leftover state would
otherwise leak into case N+1. `reset_move_lines(program)` produces one
reset line per top-level (level `01` **or** `77`) WORKING-STORAGE item —
`77`s are standalone items just like `01`s and would leak state if
skipped.

| Item shape | Reset line | Why |
|---|---|---|
| Elementary, has `VALUE` clause | `MOVE <value> TO <name>` | restores the declared initial value |
| Elementary, no `VALUE`, numeric or numeric-edited PIC | `MOVE 0 TO <name>` | numeric-edited PICs (e.g. `PIC ZZZ9`) reject `MOVE SPACES` — `_is_numeric` treats any of `9 V P Z * $ + -` in the (repeat-group-stripped) picture as numeric, not just `9`/`V`/`P` |
| Elementary, no `VALUE`, alphanumeric PIC | `MOVE SPACES TO <name>` | COBOL's conventional type default, a deliberate divergence from "truly undefined" memory in exchange for deterministic tests |
| Elementary, no `PICTURE` (usage-typed), `USAGE POINTER`/`PROCEDURE-POINTER`/`FUNCTION-POINTER`/`PROGRAM-POINTER` | `SET <name> TO NULL` | pointers can only be assigned with `SET`; `NULL` is their only legal literal value — `MOVE SPACES` (the old picture-blind fallback) is rejected by cobc |
| Elementary, no `PICTURE`, `USAGE COMP-1`/`COMP-2` (or `COMPUTATIONAL-1`/`-2`) | `MOVE 0 TO <name>` | floats have no `PICTURE`, so the old numeric test (`item.picture_clause is None → False`) misclassified them alphanumeric and emitted an illegal `MOVE SPACES` |
| Elementary, no `PICTURE`, `USAGE INDEX` | *(skipped — no line emitted)* | INDEX items accept neither `MOVE SPACES` nor `MOVE 0`; skipping is the only reset that never emits illegal COBOL (documented fidelity limit) |
| Elementary, no `PICTURE`, any other/unrecognized `USAGE` | *(skipped, fail-safe)* | unknown usage — skip rather than guess at a possibly-illegal MOVE |
| Group, no `VALUE` clause | `INITIALIZE <name>` | a `MOVE SPACES` over a group would write spaces across numeric children, corrupting them for the next case's arithmetic; `INITIALIZE` zeros numeric children and space-fills alphanumeric ones |

`_elementary_reset(item)` is the single function these rules route
through (used both for top-level elementary items and, recursively, for
`_child_value_restores`'s per-child VALUE restoration below) — it returns
`str | None`, and callers append the line only when it isn't `None`, so
"skip rather than emit illegal COBOL" is enforced in one place.

**Correcting a stale claim (audit finding 7.2):** this file previously
said `INITIALIZE does not restore a group's children's own VALUE clauses`
was a "known v1 fidelity limit." That was **false even before this
revision** — `_child_value_restores` (added prior to this fix, covered by
`test_reset.py`'s existing `test_group_children_value_clauses_are_restored`
and `test_nested_group_child_value_clause_is_restored`) already walked
every child of a `VALUE`-less group recursively and emitted a `MOVE
<value> TO <child>` for each one that declared its own `VALUE` clause,
specifically because `INITIALIZE` does not restore them. The real,
still-current fidelity limit is narrower and is documented next.

**Current fidelity limit: OCCURS-with-VALUE children are skipped, not
restored (audit finding 2.4).** `_child_value_restores` now checks
`getattr(child, "occurs_clause", None) is not None` and skips that child
(and its subtree) entirely — before this fix, a child like
`05 WS-CELL PIC 9 OCCURS 5 TIMES VALUE 7` produced `MOVE 7 TO WS-CELL`,
which is illegal COBOL (an OCCURS item needs a subscript on every
reference) and cobc rejected the whole program. A sound fix needs
subscripted MOVEs in a loop over the table's bounds; that's out of scope
for this pass, so such a child is left at `INITIALIZE`'s type default
(zero/spaces) instead of its declared `VALUE` — strictly better than not
compiling at all, but not full fidelity. Non-OCCURS siblings of a skipped
child are unaffected and still get their own restore line.

`_is_group` must only count children that carry a `level` attribute:
cobolparser's `children` list on a data item mixes in clause nodes (e.g.
`PictureClause`) alongside subordinate data items.

These reset lines feed `driver.build_driver`, which wraps them into the
`UT-RESET-WORKING-STORAGE` paragraph — called at the top of every
`UT-TESTCASE-NNN` paragraph (only generated at all `if reset_lines`).

**Upstream dependency**: requires cobolparser's numeric-VALUE-clause fix
(`tests/regression/test_numeric_value_clause.py` upstream) — before it,
`VALUE 5`, `VALUE IS <n>`, and `VALUE -5` parsed as `value_clause=None`,
which made `reset.py` silently reset to the type default instead of the
declared value.

`reset_lines_for_items(items)` (2026-07-08) factors the item-loop out of
`reset_move_lines` so any WORKING-STORAGE-*shaped* item list gets the
identical treatment without duplicating the rules table above —
`splicer.linkage` is the other caller, for LINKAGE items it has neutralized
into WORKING-STORAGE (see next section).

# ENTRY/LINKAGE Neutralization (linkage.py)

Fixes a real crash class, not a hypothetical: a program with a named
`ENTRY '<name>' USING <linkage-group>` alongside a bare, no-`USING` default
entry (the IMS DL/I `ENTRY 'DLITCBL'` idiom — `ACCTPRG`, `DEPTBMP`,
`DEPTIMSM`, `FNDTXFR`, `LNRECOV` in the real-world corpus). mockymock's
driver only ever `PERFORM`s the default entry directly, in the same
compilation unit; it never `CALL`s the program through the named `ENTRY`.
The LINKAGE SECTION storage that entry's `USING` would bind is therefore
never allocated, and any reference to it from code reachable off the
default entry dereferences unbound memory — verified against the real
GnuCOBOL toolchain: SIGSEGV, exit 139. See
[docs/2026-07-08-ims-linkage-support-design.md](../docs/2026-07-08-ims-linkage-support-design.md).

`analysis.linkage.linkage_plan(program)` detects the shape (`None` for an
ordinary CALL-only program: no `ENTRY` statement, or an absent/empty
LINKAGE SECTION). `refusal.check_linkage_layout(program, lines)` gates it
with three guardrails, refusing `UNSUPPORTED_LINKAGE_LAYOUT` rather than
guessing when any fails: the default entry must have no `USING` of its own
(the general CALL-driving case, Milestone B, is untested and out of scope
here); LINKAGE SECTION must be the last DATA DIVISION section (nothing
after it that would wrongly get absorbed too); and the computed header line
must textually verify as `LINKAGE SECTION` before ever being commented.

`neutralize(lines, program, plan)` — verified empirically to compile and
run clean — comments out every `ENTRY` statement's span (`statement_span`,
same helper other top-level splices use, unioned with each entry's own line
into the boundary set so multiple ENTRY statements can't swallow each
other) and the single `LINKAGE SECTION.` header line, via the same
`stub_writer.comment_and_replace` primitive everything else in this module
uses. No data is physically relocated: with no section header separating
them from WORKING-STORAGE, GnuCOBOL folds the LINKAGE items into it.
Because every call passes an empty `replacement`, no line is ever inserted
or removed — this transform cannot shift any other line-number-dependent
step in the pipeline, so it runs early, right after
`normalize_fixed_format`, unconditionally safe regardless of order.

The promoted items still belong to the LINKAGE section in `result.ast` —
the transform edits text, not the AST — so `reset.reset_move_lines`'s
WORKING-STORAGE walk never sees them. `extra_reset_lines(plan)` generates
their reset lines separately (via `reset.reset_lines_for_items`, reusing
the identical VALUE-restoring rules) and the CLI appends them to
`reset_move_lines`'s output before building the driver. Consequence: no new
mocking primitive was needed for these programs at all — their only IMS
access pattern, `CALL 'CBLTDLI' USING ...`, was already an ordinary
`MockCategory.CALL` boundary; a `.cut` author can `MOCK CALL "CBLTDLI"` and
`MOVE` a status value into what is now real, addressable WORKING-STORAGE
(e.g. `CUST-STATUS`) to simulate a DL/I outcome.

# Terminator Neutralization (GOBACK/STOP RUN, Approach B)

`refusal.find_terminator_plans` finds every `StopStatement`(RUN-form)/
`GobackStatement` reachable from at least one test case whose enclosing
paragraph -- and every intermediate paragraph between it and the test's
`perform_target` -- is reached exclusively via plain, unconditional,
single-shot, top-level `PERFORM` statements (`refusal._plain_perform_edges_from`,
which excludes `PERFORM ... UNTIL`/`VARYING`/`TIMES` edges --
`perform_type != "SIMPLE"` -- since `EXIT PARAGRAPH` only ends the
current loop iteration, not the loop itself, so a terminator reachable
only through a loop's target paragraph is not safely neutralizable),
never a `GO TO` target anywhere in the program
(`refusal._go_to_targets`), never a `SECTION` member. Safe terminators
are replaced with `MOVE "Y" TO UT-EARLY-EXIT` + `EXIT PARAGRAPH`
(`injector.build_terminator_neutralization`); every intermediate
`PERFORM` statement on the chain gets `IF UT-EARLY-EXIT = "Y" EXIT
PARAGRAPH END-IF` inserted immediately after it
(`injector.build_chain_check`, via `stub_writer.insert_lines_after` --
the only splice primitive in this codebase that preserves the original
statement rather than replacing it). `driver.py` needs only one addition:
`UT-EARLY-EXIT` declared once, reset to `"N"` per test case. No paragraph
restructuring -- `UT-TESTCASE-NNN`'s existing checks run automatically
once the flag has propagated back via ordinary, unmodified `PERFORM`
returns. An earlier design (`GO TO` redirect into a `PERFORM ... THRU
...` range) was proven unsound by a verification spike and replaced
before any of it shipped -- see
[docs/2026-07-08-goback-stop-run-support-design.md](../docs/2026-07-08-goback-stop-run-support-design.md).

# Generated SQLCA (sqlca.py)

GnuCOBOL cannot process any EXEC SQL block at all, including declarative
ones in the DATA DIVISION, so `transform_data_division_exec` handles them
on the normalized lines, independently of the PROCEDURE DIVISION splicing
above but run **after** it in the CLI (see the ordering correction under
Overview — this file previously and incorrectly said "before"):

| DATA DIVISION construct | Transform |
|---|---|
| `EXEC SQL INCLUDE SQLCA END-EXEC` | replaced by the literal `SQLCA_FIELDS` group item (standard SQLCA layout: SQLCAID, SQLCABC, SQLCODE, SQLERRM/SQLERRML/SQLERRMC, SQLERRP, SQLERRD OCCURS 6, SQLWARN0-7, SQLSTATE) |
| `EXEC SQL BEGIN/END DECLARE SECTION END-EXEC` | commented out; host variables between the markers are plain COBOL and stay |
| `EXEC SQL DECLARE ... TABLE ... END-EXEC` | commented out (declarative only, no runtime effect) |
| `EXEC SQL DECLARE <cursor> CURSOR FOR SELECT ... END-EXEC` | commented out (declarative only; the standard `PERFORM ... UNTIL SQLCODE = 100` fetch-loop idiom's OPEN/FETCH/CLOSE are separate PROCEDURE DIVISION EXEC SQL statements the boundary-mocking machinery already handles) |
| `EXEC SQL INCLUDE <member>` (anything else) | whole-program refusal `UNSUPPORTED_DATA_DIVISION_EXEC` — an INCLUDE pulls in host-variable declarations this tool cannot resolve, same spirit as `UNRESOLVED_COPYBOOK` |
| anything unrecognized | `UNSUPPORTED_DATA_DIVISION_EXEC`, fail closed |

**Important invariant**: the generated SQLCA is spliced in **after
parsing** and is therefore not part of the parsed AST at all. This means
`reset.py`'s WORKING-STORAGE reset never touches it — SQLCODE/SQLSTATE
are expected to survive across test cases unless a mock body explicitly
sets them, which is why the scaffold generator's placeholder EXEC SQL mock
bodies always set SQLCODE explicitly in every case.

**Literal-text and shared-line hardening (2026-07-07 fix, audit finding
2.6):** the block scanner previously keyed off the literal substring
`EXEC SQL` anywhere in a DATA DIVISION line and `END-EXEC` anywhere in a
line to close the block. A `VALUE "EXEC SQL ERROR"` string literal in a
data item's `VALUE` clause would start a bogus block scan; if a real EXEC
block followed before a real `END-EXEC` line, every intervening *live*
data item would be swallowed and commented out as if it were part of the
(fictitious) block. `_search_outside_literals` fixes this: it scans a
line for the first `EXEC SQL` / `END-EXEC` match that is NOT inside a
`'...'`/`"..."` string literal, using `_in_literal` (a simple quote-parity
scan across the line up to the candidate match's column — a doubled quote
inside a literal toggles closed-then-open again, which correctly leaves
the scan "inside"). Both the block-start search and the block-end search
now route through this helper.

Whole-line replacement/commenting is also now guarded against **sharing a
line with other content**: `_shared_line_problem` checks the text before
the matched `EXEC SQL` on the start line and the text after the matched
`END-EXEC` (and its optional trailing period) on the end line. Either one
being non-blank refuses `UNSUPPORTED_DATA_DIVISION_EXEC` naming the
offending content, instead of silently deleting a data item declared on
the same line as `EXEC SQL INCLUDE SQLCA END-EXEC.` or after it on the
`END-EXEC.` line. A full general fix (splitting a shared line into a kept
part and a transformed part) was judged riskier than refusing the
ambiguous layout — this mirrors the splicer's own top-level own-line
guard (finding 2.1) in spirit: detect the unsafe layout and fail closed
rather than guess.

# Statement Splicing Mechanics (stub_writer.py)

`comment_and_replace(lines, start_line, end_line, replacement)` is the
single low-level primitive both PROCEDURE DIVISION splices go through: it
comments out every non-blank line in `[start_line, end_line]` (1-indexed
inclusive) by prefixing `      *> `, then inserts `replacement` immediately
after the (now-commented) span, returning a new list. It does not touch
input `lines`. Comments-out-rather-than-deletes is deliberate: it keeps
line numbers of the commented region stable for anyone diffing generated
output against the original, and preserves the original text as a visible
audit trail in the compiled artifact.

# Driver Scaffold (driver.py)

`build_driver` generates the new PROCEDURE DIVISION entry point:
`UT-TESTSUITE-<name>` performs `UT-TESTCASE-001`, `002`, ... in order, then
displays a `__MOCKYMOCK__ SUMMARY` line and `STOP RUN`. Because these
paragraphs are **prepended** before the program's own paragraphs and
COBOL's PROCEDURE DIVISION execution starts at the first paragraph after
the header, the program's original first paragraph never runs
automatically — it can only run via an explicit `PERFORM` from a test
case's `perform_target` (with optional `perform_thru`).

Each `UT-TESTCASE-NNN` paragraph: optionally performs the reset paragraph,
moves the case ID into `UT-CURRENT-CASE` (this is what every injected
EVALUATE dispatch block switches on), zeroes every tally this case's mocks
touch, displays a `CASE NNN START` marker, runs any `setup_moves`,
performs the target paragraph, then checks `expectations` (data-name
equality) and `verifications` (tally-based `VERIFY ... WAS CALLED`
conditions from `_verify_condition`: `ONCE` → `NOT = 1`, `NEVER` → `NOT =
0`, `AT LEAST ONCE` → `< 1`, `N TIMES` → `NOT = N`), incrementing
`UT-FAIL-COUNT` and displaying a `CASE NNN FAIL` line on any mismatch.

`_display_text` doubles embedded `"` characters before embedding a value
in a generated `DISPLAY "..."` literal — without it, an EXPECT/VERIFY
value containing a quote (e.g. an expected string `OK"`) would split the
literal and cobc would read the remainder as undefined identifiers.

**`suite.name` escaping (2026-07-07 fix, audit finding 2.8):** the
`__MOCKYMOCK__ TESTSUITE: <name>` `DISPLAY` line interpolated `suite.name`
directly while `case.name` already went through `_display_text` — a
latent trap on the public `build_driver` API (not reachable via
`parse_cut` today, since the `.cut` grammar doesn't let a `TESTSUITE`
title contain an embedded quote, but real for any other caller). Fixed by
routing `suite.name` through `_display_text` too, matching `case.name`'s
existing treatment.

A `verifications` entry whose `(category, key)` isn't in the test case's
own declared mock set raises `ValueError` at codegen time — this is a
defensive check; the refusal gate is expected to have already refused
`VERIFY_WITHOUT_MOCK` before codegen is reached.

# See Also

- [dsl](dsl.md) — `MockTestSuite`/`MockTestCase`/`MockDirective` model and
  `.cut` parsing that the splicer consumes.
- [analysis](analysis.md) — `mock_surface` boundary-site detection and the
  refusal gate that must run before `orchestrator.splice_program`.
- [runtime](runtime.md) — compiling and executing the spliced output
  through GnuCOBOL, and parsing the `__MOCKYMOCK__` DISPLAY markers back
  into results.
