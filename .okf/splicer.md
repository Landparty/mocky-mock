---
type: Module
title: Splicer
description: Turns mock_surface boundary sites into spliced COBOL source — dispatch blocks, tally fields, WORKING-STORAGE reset, and the generated SQLCA.
tags: [splicer, injection, cobol-source]
timestamp: 2026-10-16T00:00:00Z
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

**Line splitting (2026-09-27):** every split of COBOL source text that is
later indexed by an AST line number goes through
`mockymock._lines.split_source_lines` (`\n` / `\r\n` / `\r` only, as
cobolparser counts records), never `str.splitlines()` -- that also breaks on
form feed / VT / `\x1c`-`\x1e` / NEL / U+2028, so a page-eject `\f` in a
comment line shifted every later splice one line early (the mock replaced
the statement before the CALL and the real CALL ran). The rule is agreement
with the *installed* cobolparser: releases without `cobolparser._lines`
(1.8.x and earlier, allowed by the `>=1.7.7` floor) still number records the
`str.splitlines()` way, so `split_source_lines` falls back to it there
(`PARSER_SPLITS_ON_RECORD_DELIMITERS`) -- the `cobol-parser-compat` CI job
runs against the published wheel and caught the mismatch.

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

# Flow-Mock Header Dispatch (2026-07-20, MOCK PARAGRAPH/SECTION)

`injector.build_flow_dispatch(plan, suite, registry)` handles the flow-
target categories: `orchestrator.splice_program`'s `flow_plans` parameter
(a `FlowMockPlan` list from `analysis.flow_mocks.find_flow_mock_plans`)
replaces ONLY the paragraph/section **header line** with: the re-emitted
header, an `EVALUATE UT-CURRENT-CASE` whose `WHEN` branches are the
mocking cases (tally increment + mock body) and whose `WHEN OTHER`
performs the relocated real body, then a `UT-REAL-<n>[-<KEY>]`
(`SECTION`) header that the original, physically-unmoved body lines now
belong to. Two invariants worth knowing:

- **Body lines never move**, so every other span-based splice inside the
  body (boundary dispatch, terminator neutralization, chain checks) stays
  valid; the bottom-up application order already guarantees the header
  splice (lower line number) is applied after any body-internal spans.
- **Flow spans bypass the trailing-period propagation** the other
  replacement spans get: a header line always ends with `.`, and the
  replacement is already sentence-complete -- propagation would emit a
  doubled period after the relocated header.

Unlike `build_site_dispatch`, `WHEN OTHER` is NOT an error trap here: a
case that doesn't mock the target must run the real code. Soundness
(target entered exclusively via PERFORM through its own header) is the
refusal gate's job -- see [analysis](analysis.md) and
docs/2026-07-20-paragraph-section-mocks-design.md.

# Dispatch and Trap Generation (injector.py)

`build_site_dispatch(site, suite, registry, file_status_fields=None)` builds
one `EVALUATE UT-CURRENT-CASE` block per **site** (not per mock key):
different test cases can match the same physical statement through
different keys (e.g. case 1 mocks `OPEN IN-FILE`, case 2 mocks `OPEN
OUT-FILE`, both matching one `OPEN INPUT IN-FILE OUTPUT OUT-FILE`
statement). Each matching case gets a `WHEN "NNN"` branch that increments
that case's own tally (crediting the directive that matched) then splices
in `directive.body_lines` verbatim. A `WHEN OTHER` branch is always
appended: if control reaches a mocked site under a test case that doesn't
mock it, that's a hard, loud failure (`__MOCKYMOCK__ ERROR: ... reached
from unmocked test case`), never a silent fall-through.

**FILE-STATUS default-success/override injection.** For a directive whose
category is in `FILE_STATUS_CATEGORIES` (the 6 eligible file ops --
`OPEN`/`CLOSE`/`READ`/`DELETE`/`START`/`UNLOCK`; `WRITE`/`REWRITE` are not
eligible), `build_site_dispatch` looks up `directive.key.upper()` in the
`file_status_fields` map (`mock_surface.analyze_file_status_fields`'s
uppercased-file-name -> declared `FILE STATUS IS <field>` result, computed
once per program and threaded down from `run_static_checks`/`_cmd_run`
through `splice_program`). If the file declares a status field, the `WHEN`
branch always starts with an implicit `MOVE "00" TO <field>` (default
success) *before* the directive's own `body_lines` -- whether or not the
`.cut` author used `FILE-STATUS IS` sugar. When the directive's body used
`FILE-STATUS IS` (`directive.file_status` holding the resolved two-digit
code, from the mnemonic table or a quoted literal — see [dsl](dsl.md)), a
second `MOVE "<code>" TO <field>` is emitted right after the default,
which therefore wins since it comes later in the same `WHEN` branch —
same as any hand-written `MOVE` to that field a mock author adds after it.
A statement naming several files (`OPEN INPUT A OUTPUT B`, `CLOSE A B`) is one site matched by one directive, so the default `MOVE "00"` is emitted for **every** file in `site.keys` that declares a status field, all before the `FILE-STATUS IS` override (which still targets only the directive's own file) -- round 7: defaulting only the directive's file left the other file's status blank, and a program checking both took its failure branch. A file with no declared `FILE STATUS` field gets neither MOVE: there is no
WORKING-STORAGE target to write into (`refusal.check_test_case`'s
`UNRESOLVED_FILE_STATUS_TARGET` refuses fail-closed before splicing is
ever reached if the `.cut` file used `FILE-STATUS IS` sugar against such a
file, or -- see below -- a `MOCK READ ... ROWS` directive with no
`TERMINAL` group targets one). See
`docs/2026-07-20-before-blocks-and-file-status-design.md`.

**`CAPTURE ARG` resolution.** For a matched `CALL`/`DYNCALL` directive
with `directive.captures`, `build_site_dispatch` emits one `MOVE
<real-arg-name> TO <target>` line per `(n, target)` pair, resolved
against *this exact physical site's* own AST node
(`site.statement`, narrowed via `isinstance(..., CallStatement)` --
`BoundarySite.statement` already carries the original AST statement for
every site, so no new analysis-phase field was needed) --
`site.statement.using_parameters[n - 1].name` -- except that cobolparser
reports a *literal* argument by its quote-stripped value (`BY CONTENT
"ABC"` -> `ABC`), indistinguishable from a data-name, so
`_call_using_literals` re-scans the site's own spliced span
(`splice_program` now builds the dispatch after computing the span and
passes it as `statement_text`) and emits the literal token verbatim
(`MOVE "ABC" TO target`). It trusts the text only when its operand list
agrees with the parser's operand for operand; otherwise it falls back to
the name (2026-09-28 -- before, the MOVE silently copied an unrelated item
named ABC, or failed in cobc). `plan_captures` (given `lines` by
`cli.checks`) applies the same recognition via `_site_argument`, so a
`UT-CAP-` target for a literal is declared from the literal itself
(`_literal_declaration`: `PIC X(len)` for a quoted literal, `PIC [S]9(i)[V9(d)]`
for a numeric one, refused for X/N/G-prefixed) -- before 2026-09-28 it
mirrored a same-named item's layout (`"ABC"` into `PIC 9(2)` read back
`BC`) or refused as "not a uniquely-named data item". Emitted before
`directive.body_lines`, in declared order. See [dsl](dsl.md)'s `CAPTURE
ARG` grammar section and docs/2026-08-11-argument-capture-design.md.

The *target* half of the same feature lives in its own module,
`splicer/captures.py` (2026-09-04), because it runs at static-check time
rather than splice time. A target whose name starts with
`CAPTURE_TARGET_PREFIX` (`UT-CAP-`) is mockymock's to declare:
`plan_captures(program, suite, surface)` resolves each one against the
matching CALL site's own `using_parameters` — the identical resolution
`build_site_dispatch` does above, so the synthesized declaration always
mirrors the item the generated `MOVE` will read — and returns
`CapturePlan`s plus a reason per target it could not mirror.
`capture_working_storage_lines` / `capture_reset_lines` then feed
`driver.build_driver` through `cli.checks.extra_working_storage` /
`extra_reset_lines_for`, the same route `cics_eib` and `UT-ADDR-SINK`
take, so all four splice-and-compile pipelines (`run`, `debug`, `export`,
`mutate`) declare and reset them identically. The reset half is
load-bearing and was briefly lost in `mutate` (2026-09-04): one binary
serves the whole suite, so an unreset capture lets a case that never
reached its CALL assert against the previous case's value — and in
`mutate` that stale value can "kill" a mutant, inflating the score.
Anything unmirrorable (a table, a PICTURE-less `COMP-1`/`POINTER`, a group
holding non-DISPLAY bytes, or one directive matching two sites whose
argument `n` names different items) fails closed as
`UNRESOLVED_CAPTURE_TARGET` rather than emitting a declaration that would
not compile or would compare against raw binary. Full grammar and
`generate` behavior in [dsl](dsl.md)'s "Synthesized targets" section.

**`ROWS` dispatch (`MOCK SQL/READ/RETURN/CALL/MQ/DLI ... ROWS`, see
[dsl](dsl.md)).** `build_rows_block(tally_name, rows, *, row_suffix_moves,
exhausted_moves)` is category-generic: it builds an `EVALUATE TRUE` /
`WHEN <tally> = N` chain where row N's field `MOVE`s are followed by
`row_suffix_moves` verbatim, and `WHEN OTHER` (rows exhausted) fires
`exhausted_moves` verbatim -- the caller decides what those two lists
contain, `build_rows_block` itself has no category knowledge. Both call
sites live in `build_site_dispatch`, one per `directive.rows is not None`
category:

- **CALL / DYNCALL / DLI** (`SEQUENCED_CALL_CATEGORIES`, 2026-10-05):
  `row_suffix_moves=[]`, `exhausted_moves` = the directive's own
  (mandatory) `TERMINAL` group's MOVEs -- there is no implicit default for
  a CALL. A hand-built directive without one raises `ValueError`; the
  parser rejects it first. Row N fires on the key's Nth call in the case,
  counted across every site the key matches (one shared tally).
- **SQL**: `row_prefix_moves=["MOVE 0 TO SQLCODE"]`, ahead of the row's
  own MOVEs so a row that sets `SQLCODE` (an error mid-cursor) wins (as a
  suffix it overwrote it, until 2026-10-13); `row_suffix_moves=[]`;
  `exhausted_moves=["MOVE 100 TO SQLCODE"]` -- fixed in v1.
- **READ**: `row_suffix_moves=[]` (the ordinary FILE-STATUS
  default-success `MOVE "00"` above already covers every row when the
  file declares a status field, so there is nothing left to append per
  row). `exhausted_moves` is built additively, not as an either/or choice
  (fixed post-PR #46 review, Task 3 -- see log.md): when the file has a
  `file_status_fields` entry it ALWAYS starts with the implicit `MOVE
  "10" TO <status field>` (COBOL's real end-of-file status code), and the
  directive's own `TERMINAL ( FIELD = value, ... )` group's MOVEs (`[f"MOVE
  {value} TO {field}" for field, value in directive.terminal_row]`) --
  when present -- are appended right after, same "implicit default,
  explicit override" ordering as the FILE-STATUS default/override pair
  above: an author's own MOVE to that same field (if TERMINAL happens to
  include one) naturally wins by coming later in the same WHEN branch,
  and a TERMINAL group that never mentions the status field no longer
  leaves it stuck at whatever "00" the default-success MOVE set on the
  call that triggered this WHEN OTHER path -- it gets the correct "10"
  instead. When the file has no status field, `exhausted_moves` is just
  the TERMINAL group's own MOVEs (nothing to default). When **neither** a
  status field nor a TERMINAL group exists, `build_site_dispatch` raises
  `ValueError` rather than emit a READ loop with no way to terminate --
  but every production call site gates on `refusal.check_test_case` first
  (same `UNRESOLVED_FILE_STATUS_TARGET` code as the `FILE-STATUS IS` case
  above, a second, structurally different trigger under that one code:
  `directive.category is MockCategory.READ and directive.rows is not None
  and directive.terminal_row is None and directive.key.upper() not in
  file_status_fields`), so this `ValueError` should be unreachable in
  practice -- a production invariant enforced by the refusal gate, not a
  normal control path this module expects to hit.

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

# BEFORE-ALL state snapshot (snapshot.py)

2026-10-10, suite hooks (`docs/2026-10-10-suite-hooks-design.md`). When
a `.cut` has `BEFORE-ALL` steps, every case must start from the state
they leave, not from the reset. `plan_snapshot(program, linkage_items)`
covers exactly the items `reset.py` covers (top-level WORKING-STORAGE /
LOCAL-STORAGE, each FD's longest record, neutralized LINKAGE items; no
top-level REDEFINES or FILLER) and returns `UT-SNAP-nnn` declarations
plus `UT-SAVE-STATE` / `UT-RESTORE-STATE` bodies, and one problem per
item it can't copy exactly (`cli.checks` step 10 turns them into
`UNSAVABLE_BEFORE_ALL_STATE`). The driver runs reset, BEFORE-ALL steps,
save once; each case runs reset then restore -- the reset still handles
harness fields, captures and the EIB.

| Item | Snapshot field | Copy |
|---|---|---|
| Group | `01 UT-SNAP-nnn.` + `05 FILLER PIC X(n)`, n an upper bound (`_max_bytes`: REDEFINES children summed, every elementary at least 16 bytes, national x4) | `MOVE` (group move = byte copy; restore copies back exactly the group's own bytes) |
| Elementary with PICTURE / PICTURE-less usage (COMP-1/2, BINARY-x) | same PIC + USAGE + SIGN | `MOVE` |
| POINTER family, INDEX | same USAGE | `SET` |
| Group holding OCCURS ... DEPENDING ON, unreadable OCCURS bound, irreproducible description | -- | refused |

The size is an upper bound, not cobol-parser's `calculate_size`, on
purpose: releases before 2026-09-10 undercounted some usages (COMP-1 as
0, POINTER as 4), and an undercount would truncate the copy.
Not compiled in CI (the integration job is off); the shapes are pinned by
`tests/unit/test_suite_hooks.py`.

# WORKING-STORAGE Reset (reset.py)

Because one binary serves the whole suite, case N's leftover state would
otherwise leak into case N+1. `reset_move_lines(program)` produces one
reset line per top-level (level `01` **or** `77`) WORKING-STORAGE item —
`77`s are standalone items just like `01`s and would leak state if
skipped.

| Item shape | Reset line | Why |
|---|---|---|
| Elementary, has `VALUE` clause | `MOVE <value> TO <name>` | restores the declared initial value (the clause first passes through `cobol_literal` -- see below) |
| Elementary, no `VALUE`, numeric or numeric-edited PIC | `MOVE 0 TO <name>` | numeric-edited PICs (e.g. `PIC ZZZ9`) reject `MOVE SPACES` — `_is_numeric` treats any of `9 V P Z * $ + -` in the (repeat-group-stripped) picture as numeric, not just `9`/`V`/`P` |
| Elementary, no `VALUE`, alphanumeric PIC | `MOVE SPACES TO <name>` | COBOL's conventional type default, a deliberate divergence from "truly undefined" memory in exchange for deterministic tests |
| Elementary, no `PICTURE` (usage-typed), `USAGE POINTER`/`PROCEDURE-POINTER`/`FUNCTION-POINTER`/`PROGRAM-POINTER` | `SET <name> TO NULL` | pointers can only be assigned with `SET`; `NULL` is their only legal literal value — `MOVE SPACES` (the old picture-blind fallback) is rejected by cobc |
| Elementary, no `PICTURE`, `USAGE COMP-1`/`COMP-2` (or `COMPUTATIONAL-1`/`-2`) | `MOVE 0 TO <name>` | floats have no `PICTURE`, so the old numeric test (`item.picture_clause is None → False`) misclassified them alphanumeric and emitted an illegal `MOVE SPACES` |
| Elementary, no `PICTURE`, `USAGE INDEX` | *(skipped — no line emitted)* | INDEX items accept neither `MOVE SPACES` nor `MOVE 0`; skipping is the only reset that never emits illegal COBOL (documented fidelity limit) |
| Elementary, no `PICTURE`, any other/unrecognized `USAGE` | *(skipped, fail-safe)* | unknown usage — skip rather than guess at a possibly-illegal MOVE |
| Group, no `VALUE` clause | `INITIALIZE <name>` | a `MOVE SPACES` over a group would write spaces across numeric children, corrupting them for the next case's arithmetic; `INITIALIZE` zeros numeric children and space-fills alphanumeric ones |
| Any top-level item with a `REDEFINES` clause | *(skipped — no line emitted)* | it shares the redefined item's storage, which that item's own line already reset/restored; a second reset through the redefining view ran after it and overwrote it (2026-09-27 fix: `01 WS-CODE PIC X(4) VALUE "AB12".` + `01 WS-CODE-NUM REDEFINES WS-CODE PIC 9(4).` left `WS-CODE` = `"0000"` in every case, the first included). Skipping matches program start-up, where GnuCOBOL initializes the storage from the first description |

**Embedded double quotes in a VALUE clause (2026-08-28 fix).** cobolparser
hands an alphanumeric VALUE clause back double-quote-delimited around the
literal's DECODED content, and versions through 1.8.0 did not re-double an
embedded `"`. CICS's `DFHAID` copybook legitimately declares
`DFHTRIG PIC X VALUE IS '"'` -- content: one quote character -- which arrived
as three quote characters, an unterminated literal. Emitted verbatim it
produced `MOVE """ TO DFHTRIG`, desynchronizing `cobc`'s tokenizer for
the rest of the program: the error it eventually reports is a bogus
`invalid symbol '%'` two lines further on, nowhere near the cause. Fixed
upstream (`cobolparser._literals.quote_literal`), but this project's floor
is `cobol-parser>=1.7.7`, so `_elementary_reset` routes every VALUE clause
through `reset.cobol_literal` regardless of which parser produced it. That
function grows each run of quote characters to the next EVEN length, which
both repairs the malformed shape and is idempotent against the fixed parser
(an already-doubled pair is left alone) -- so bumping the dependency floor
later cannot double anything a second time. It handles the `ALL <literal>`
repetition prefix and returns non-literal clauses (numerics, figurative
constants, identifiers) untouched. The one shape it cannot recover is a
literal whose real content is two adjacent quotes coming from an UNFIXED
parser: indistinguishable from one correctly-escaped quote, resolved in
favour of the well-formed reading.

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

**OCCURS-with-VALUE children (audit finding 2.4, issue #156).** An
unsubscripted `MOVE 7 TO WS-CELL` against an OCCURS child is illegal COBOL,
so `_child_value_restores` still skips OCCURS children. A VALUE-less group
with a VALUE anywhere inside a table (`_has_occurs_value`: an OCCURS item
with a VALUE, or a VALUE under an OCCURS group) is instead reset with
`INITIALIZE <group> ALL TO VALUE THEN TO DEFAULT`, which restores every
occurrence's VALUE and every other child's VALUE in one statement and
zero/space-fills the rest (checked against GnuCOBOL 3.1's cobc). Before
#156 those occurrences were left at INITIALIZE's zero/space default, so a
test saw different starting data from the real program. Groups with no
VALUE inside a table keep the plain INITIALIZE plus per-child restores.

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
ordinary CALL-only program: an absent/empty LINKAGE SECTION -- `ENTRY`
statements are optional, generalized 2026-08-27 to cover the idiomatic CICS
`LINKAGE SECTION. 01 DFHCOMMAREA. ...` / `PROCEDURE DIVISION.` shape with no
`ENTRY` at all, since the IMS design's own finding 2 already proved the
storage is unbound regardless of `ENTRY`'s presence -- see
docs/2026-08-27-cics-eib-linkage-support-design.md Part 1).
`refusal.check_linkage_layout(program, lines)` gates it
with three guardrails, refusing `UNSUPPORTED_LINKAGE_LAYOUT` rather than
guessing when any fails: the default entry's header must be delimitable
(`analysis.linkage.procedure_header_clause_spans`: no `CHAINING`, and a
closing period within 50 lines of a `USING`/`RETURNING` list); LINKAGE
SECTION must be the last DATA DIVISION section (nothing after it that
would wrongly get absorbed too); and the computed header line must
textually verify as `LINKAGE SECTION` before ever being commented.

**Entry parameters (2026-10-10).** A default entry with its own
`PROCEDURE DIVISION USING ... [RETURNING ...]` -- the ordinary CALLed
subprogram, a translated CICS LINK server, an IMS MPP's PCB list, a DB2
stored procedure -- used to be refused (the "Milestone B" CALL-driving
case). The driver PERFORMs paragraphs and never CALLs the program, so
nothing would bind those parameters anyway: `neutralize` now also blanks
the clause (width-preserving `replace_columns`, every wrapped line up to
the closing period) and the parameters fold into WORKING-STORAGE with the
rest of the LINKAGE SECTION. A `.cut` sets entry values with `MOVE`
(TESTCASE, BEFORE-EACH, BEFORE-ALL) and asserts output parameters with
`EXPECT`; `extra_reset_lines` resets them before every case and
`splicer.snapshot` saves them after BEFORE-ALL. The enterprise corpus's
CICSLINK, IMSMPP and DB2SP now scaffold instead of refusing.

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

## `SET ADDRESS OF` on a folded item (2026-08-28 fix)

Folding the LINKAGE items into WORKING-STORAGE gives them real storage --
which is precisely what makes rebinding their address illegal afterwards.
GnuCOBOL only accepts `SET ADDRESS OF X TO <ptr>` when `X` is a LINKAGE or
`BASED` item, and rejects a folded one with `cannot change address of 'X',
which is not BASED or a LINKAGE item`. On the IMS DL/I PSB-scheduling idiom
(a `7000-SCHEDULE-PSB` paragraph doing this once per PCB/DIB mask -- 
`LK-DIB-LIST`, `HY7000-DIB`, `LKPCB-*`, ...) that is ~20 hard compile
errors per program, every one of them introduced by the fold itself.

Marking the folded items `BASED` is the obvious-looking fix and is wrong:
a `BASED` item has no storage until something gives it an address, which
puts the program straight back into the unbound-memory SIGSEGV this whole
transform exists to prevent (the pointer would come from a mocked
`CALL 'CBLTDLI'`, i.e. NULL). So the **statement** gives, not the storage.

`analysis.linkage.address_of_sites(lines, plan)` finds every
`ADDRESS OF <folded item>` occurrence on the RECEIVING side of a `SET` and
`splicer.linkage.redirect_address_of` overwrites each one with
`DISCARD_POINTER` (`UT-ADDR-SINK`), space-padded to the identical width via
`stub_writer.replace_columns`. Consequences worth knowing:

- **Column- and line-preserving**, like `neutralize` above and unlike
  `cics_eib`'s insertion: nothing any `SourceLocation` indexes into moves,
  so this is safe at the point in the pipeline where it runs (step 5 of
  `cli.checks.run_static_checks`, right after `neutralize`).
- **The `SET` keeps executing** -- the rebind is discarded, control flow and
  sentence structure are unchanged, and (unlike commenting the statement
  out) a sibling statement sharing the line is untouched.
- **`UT-ADDR-SINK` is only declared when a site needed it**
  (`extra_working_storage_lines`), reaching the source through
  `driver.build_driver`'s `extra_working_storage_lines` -- the same route
  `cics_eib`'s synthesized block takes, merged with it by
  `cli.checks.extra_working_storage` so all four splice-and-compile
  pipelines stay in step. It needs no reset line: nothing ever reads it.
- **Value-side occurrences are deliberately left alone.**
  `SET <ptr> TO ADDRESS OF <folded item>` is legal COBOL and stays correct
  after the fold -- only *rebinding* the item becomes illegal. So are a
  `CALL ... USING ... ADDRESS OF <folded item>` argument (the CICS-DL/I
  `CALL 'CBLTDLI' USING PCB-FUNC PSB-NAME ADDRESS OF DLIUIB` idiom -- legal
  on a WORKING-STORAGE item, verified against GnuCOBOL 3.1.2) and anything
  inside `EXEC ... END-EXEC` (`EXEC CICS ADDRESS TCTUA(ADDRESS OF TCTUA)`),
  which the splicer replaces wholesale with a mock or a trap stub.
- **Classified per statement, not per line (2026-09-28 fix).** Sites used to
  be classified per line (nearest `SET` on the same line), which refused
  every multi-line shape above -- and even the bare `EXEC CICS ADDRESS`
  line, whose trailing `ADDRESS` keyword read as a dangling `ADDRESS OF`.
  `address_of_sites` now tokenizes the whole text (string literals and `*>`
  comments skipped) and walks back from each `ADDRESS OF <folded item>`:
  a SET receiving operand can only be preceded by `SET`, other receiving
  operands (names, `OF`/`IN`, subscripts, commas). The first token outside
  that vocabulary decides -- `SET` means receiving; `TO`/`BY` (every SET
  form reaches one before its sending side), `USING`, a verb, an unmatched
  `(`, `EXEC`, a sentence period mean it is left alone. A receiving operand
  on a later line than its `SET` is now rewritten, not refused.
- **Detection is textual, not AST-driven**, because cobolparser's
  `SetStatement` drops the target-side `ADDRESS OF` entirely -- `SET ADDRESS
  OF X TO Y` and `SET X TO Y` both arrive as `targets=["X"]`, so the AST
  cannot tell the two apart (verified against cobolparser 1.8.0). Only the
  *value* side carries a flag (`value_is_address_of`).
- **Anything unclassifiable refuses** rather than being guessed at:
  `refusal.check_linkage_layout` turns each problem `address_of_sites`
  reports into `UNSUPPORTED_LINKAGE_ADDRESSING` -- since 2026-09-28 only a
  receiving `ADDRESS OF <item>` whose own span is split across lines
  (`SET ADDRESS OF` / `LK-ITEM TO P`): no single-line span to rewrite.

Verified end to end against real GnuCOBOL 4.0: the rewritten program
compiles, runs and passes its test case; the un-rewritten one does not
compile at all.

# DFHRESP Expansion (cics_resp.py, 2026-09-28)

`expand_dfhresp(lines)` does what the CICS translator does to
`DFHRESP(<condition>)`: replaces it with the condition's EIBRESP number
(`DFHRESP(NORMAL)` -> `0`, `DFHRESP(MAPFAIL)` -> `36`). Unlike DFHVALUE's
hundreds of CVDAs, the DFHRESP table is small and IBM only ever appends to
it, so `DFHRESP_VALUES` reproduces it exactly -- restricted to values two
independent sources agree on (IBM's "Response codes of EXEC CICS commands"
and the full EIBRESP list); a missing entry refuses, a wrong one would
silently flip a branch.

- **Width-preserving** via `stub_writer.replace_columns`, like
  `redirect_address_of`: no line or column moves, so it runs in step 5b of
  `run_static_checks` (and in `generate`) without disturbing any
  `SourceLocation`.
- **Runs before `check_cics_eib_layout[_scoped]`**, so the gate only ever
  sees what was not expanded: DFHVALUE, an unknown condition name, a call
  split across lines. A call inside a string literal is left alone (text).
- One note per run lists every condition expanded and its value.
- **`.cut` text too** (2026-10-13, #169): `expand_dfhresp_text(line)` is
  the parser-side counterpart (not width-preserving; skips strings and
  inline `*>` comments) and returns unknown condition names, which
  `parse_cut` refuses -- see [dsl](dsl.md).

# CICS EIB Field Synthesis (cics_eib.py)

Fixes a compile-time gap, not a runtime one: a real CICS translator inserts
`DFHEIBLK`'s LINKAGE SECTION layout ahead of `cobc` ever seeing the source,
so a program referencing `EIBCALEN`/`EIBAID`/etc. from ordinary COBOL
(outside any `EXEC CICS` block, which `injector.build_exec_trap` already
splices away whole) has no declaration for those names anywhere mockymock's
pipeline ever sees -- an undeclared-data-name `cobc` compile error, not the
IMS case's runtime SIGSEGV. See
docs/2026-08-27-cics-eib-linkage-support-design.md.

`analysis.cics_eib.cics_eib_plan(program, lines)` detects the shape (`None`
when no EIB name is referenced anywhere in `lines`, or every referenced name
is already declared somewhere in the program's own DATA DIVISION -- e.g. a
hand-declared or `COPY DFHEIBLK`-expanded copy). `refusal.check_cics_eib_
layout(program, lines)` guards the two situations this feature cannot
safely handle -- `UNSUPPORTED_CICS_MACRO` (`DFHRESP(...)`/`DFHVALUE(...)`
macro calls, which only a real CICS translator can expand) and
`UNSUPPORTED_CICS_DFHCOMMAREA` (`DFHCOMMAREA` referenced but never declared
anywhere -- unknowable size, refuse rather than guess one; a program that
*does* declare its own `LINKAGE SECTION. 01 DFHCOMMAREA. ...` is covered by
the generalized ENTRY/LINKAGE neutralization above instead) -- independent
of `cics_eib_plan`, additive to `check_linkage_layout`, not exclusive-or.

`UNSUPPORTED_CICS_MACRO` is reachability-scoped for `run`/`lint`/`export`/
`debug` (`check_cics_eib_layout_scoped`; `generate`/`fixtures` keep the
unscoped entry point). When a macro call is confined to a paragraph no
selected test case can execute, `cli.checks.run_static_checks` waives the
refusal and rewrites the call's own columns to `-1` with
`stub_writer.replace_columns` -- space-padded to the identical width, so
unlike `cics_eib`'s insertion below this edit moves neither a line nor a
column, and is safe at the point in the pipeline where it happens (step
5b, before `collect_scope_map`). See [analysis](analysis.md)'s
whole-program refusal table for the full classification rules.

Unlike `splicer.linkage.neutralize` (comment-only, line-count-preserving,
safe to run at any point in the pipeline), `splicer.cics_eib.working_
storage_lines(plan)` *inserts* new physical lines -- a synthesized `01
DFHEIBLK.` group with the standard IBM CICS EIB layout (29 named fields,
2 `FILLER` reserved slots for byte-alignment; see the design doc for the
full PICTURE clauses). Every `SourceLocation`-driven step downstream of
`normalize_fixed_format` would misalign if this ran early like `linkage.py`
does, so it never edits `lines` directly. Instead its output is merged into
`driver.DriverArtifact.working_storage_lines` via `build_driver`'s new
`extra_working_storage_lines` parameter, reaching `cli.main._insert_driver`
the same way the driver's own bookkeeping fields (`UT-CURRENT-CASE` etc.)
already do -- the one insertion point already proven safe, no second splice
mechanism needed. `splicer.cics_eib.reset_lines(plan)` is a single
`INITIALIZE DFHEIBLK` line, appended to `reset_move_lines`'s output the same
way `linkage.extra_reset_lines` already is; `DFHEIBLK` carries no `VALUE`
clauses, so `reset.py`'s existing VALUE-less-group rule (zero COMP/COMP-3,
space-fill alphanumeric) applies, which happens to already be the realistic
"no COMMAREA passed, first invocation" default (`EIBCALEN = 0`).

Wired into all four splice-and-compile pipelines identically to `linkage`'s
own wiring: `_cmd_run`, `_cmd_debug`, `_cmd_export`, and `mutation.runner.
_run_suite_once`; `_cmd_generate` prints the same transparency preview
(`applied=False`) `linkage` does. **Not yet verified against real GnuCOBOL**
-- no working Docker daemon when this was built; see the design doc's "No
corpus evidence" section for the required follow-up.

# Terminator Neutralization (GOBACK/STOP RUN, Approach B)

`refusal.find_terminator_plans` finds every `StopStatement`(RUN-form)/
`GobackStatement`/`EXIT PROGRAM` (issue #212) reachable from at least one test case whose enclosing
paragraph -- and every intermediate paragraph between it and the test's
`perform_target` -- is reached exclusively via plain, unconditional,
single-shot, top-level `PERFORM` statements (`refusal._plain_perform_edges_from`,
which excludes `PERFORM ... UNTIL`/`VARYING`/`TIMES` edges --
`perform_type != "SIMPLE"` -- since `EXIT PARAGRAPH` only ends the
current loop iteration, not the loop itself, so a terminator reachable
only through a loop's target paragraph is not safely neutralizable.
Caveat found by the 2026-07-09 final branch review: the *out-of-line*
form of `PERFORM para VARYING ...` isn't parsed by cobolparser at all
-- the clause is silently dropped, leaving `perform_type` mistagged as
`"SIMPLE"`. What actually keeps this shape from reaching the terminator
logic today is the unrelated `PARSE_WARNING` gate in `check_whole_program`,
triggered by cobolparser's own dropped-clause warning -- pinned by
regression tests in `test_refusal.py`/`test_terminator_support.py` so a
future cobolparser fix that silences the warning without also fixing
`perform_type` tagging fails loudly instead of reopening this silently.
See `docs/2026-07-08-goback-stop-run-support-design.md`'s "Out of scope"
section for the full writeup),
never a `GO TO` target anywhere in the program
(`refusal._go_to_targets`), never a `SECTION` member — except the one
narrow, whole-program-verified shape: a `SECTION`'s own first paragraph,
entered exclusively via `PERFORM <section-name>`
(`refusal._safe_section_entry_points`), replaced with `EXIT SECTION`
instead of `EXIT PARAGRAPH` (`TerminatorPlan.exit_kind`) — see
`docs/2026-07-10-section-scoped-terminator-support-design.md`. Safe
terminators
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

**EXEC CICS RETURN/XCTL/ABEND** (issue #215, option (a)): these never
give control back, so `mock_surface.is_terminator_site` counts a CICS site
whose command is one of `CICS_TERMINATOR_COMMANDS` as a terminator too.
It stays an ordinary mockable CICS site (the gates still demand its
MOCK), but `find_terminator_plans` plans or refuses it exactly like
GOBACK, and the orchestrator wraps the site's own dispatch block with
`injector.build_cics_terminator_exit`: the flag + `EXIT PARAGRAPH` after
`END-EVALUATE`, so the mock body runs first. With `RESP(field)`
(`TerminatorPlan.resp_field`) a failed command returns control, so the
field is preset to 0 before the dispatch (what a successful command
leaves there; the mock body may set a failure code) and the exit is taken
only `IF field = 0`. A RESP operand that is not one data name refuses.
`_falls_through` and `exact_counts` treat these commands as path ends.

**`RETURNING`/`GIVING` operands** (issue #219): `STOP RUN RETURNING n` /
`GOBACK RETURNING n` (cobolparser's `StopStatement.returning` /
`GobackStatement.returning_value`) set RETURN-CODE, so the replacement
starts with `MOVE n TO RETURN-CODE` (`TerminatorPlan.return_code`). An
operand that is not an integer literal or a single data name refuses
`UNSUPPORTED_TERMINATOR_LAYOUT` rather than being dropped.

**A test's (or hook step's) own `PERFORM X THRU Y`** (issue #211): the
neutralization only ends `X`, after which the driver's THRU range falls
through into the rest of the range. `_plans._thru_tail_problem` therefore
refuses `UNSUPPORTED_TERMINATOR_LAYOUT` for every terminator such a case
reaches unless every paragraph after `X` in the range is exit-only
(`X-EXIT. EXIT.`) or a phantom `"."` -- so the common `PERFORM X THRU
X-EXIT` idiom still plans, while a range covering real paragraphs refuses
instead of running them on the early-exit path.

# GO-TO-to-EXIT-PARAGRAPH Simplification

**STATUS: implemented, not yet verified against real GnuCOBOL** -- see
[docs/2026-08-17-goto-exit-paragraph-simplification-design.md](../docs/2026-08-17-goto-exit-paragraph-simplification-design.md)'s
Status note before trusting this in production; the Docker-required
integration fixture that would confirm it has not been run.

`refusal.find_goto_exit_plans(program, scope_map, lines)` is whole-program
and unconditional on any test case (like `NESTED_EXEC`'s reasoning, but
"plan or silently skip" rather than "plan or refusal" -- declining this
optimization is always safe). It targets the idiomatic mainframe
early-exit pattern `find_terminator_plans`'s own `UNSUPPORTED_TERMINATOR_
LAYOUT` message already names as a workaround: `IF cond GO TO MAIN-EXIT
END-IF ... MAIN-EXIT. EXIT.` -- a `GO TO` into a paragraph whose entire
body is one bare `EXIT.` (`refusal._is_exit_only_paragraph`). Rather than
trying to fix the *target* paragraph's return machinery the way the two
rejected candidates in
[docs/2026-07-10-goto-reachable-terminators-design.md](../docs/2026-07-10-goto-reachable-terminators-design.md)
did, this splices the `GO TO` **itself**, at its own call site, into
`EXIT PARAGRAPH`/`EXIT SECTION` -- control never physically transfers to
the target at runtime, so the "was this paragraph ever entered via GO TO"
hazard never applies to it.

Safety preconditions mirror `find_terminator_plans`' own: the GO TO's
enclosing paragraph must not itself be in `_go_to_targets`/
`_go_to_fallthrough_targets`, and must be top-level -- `SECTION`-scoped
enclosing paragraphs are declined, not supported (see below). The
exit-only paragraph must also be the enclosing paragraph's immediate
successor in source order, with nothing else between them. And no
in-program `PERFORM` (any form) or SORT/MERGE/XML PARSE procedure range may
*end* at the enclosing paragraph (`_plans._in_program_range_ends`, issue
#213): under a plain `PERFORM 1000-A` (no `THRU 1000-EXIT`) the real GO TO
leaves the PERFORM range and never returns, which is the classic
forgotten-THRU bug, and rewriting it into a clean return would hide that
bug. A `.cut`/hook PERFORM of the enclosing paragraph without THRU is
deliberately not checked: that THRU elision is the intended convenience
(without the rewrite the GO TO would run off the end of the test driver).
All-or-nothing
per target paragraph -- `_go_to_targets` is a whole-program property, so
neutralizing some but not all `GO TO`s naming one exit-only paragraph
would leave it exactly as hazardous as before; a computed or multi-target
`GO TO` merely *naming* the target (even one `_go_statement_target` can't
resolve to a site) disqualifies it too (`_go_statement_raw_targets`).

**An independent code review (same day, pre-Docker-verification) found
three more soundness holes beyond the span bug, all fixed before the PR
left draft:**
1. Nothing enforced the immediate-successor adjacency requirement above
   -- it was described in the design doc but not checked in code. A
   `PERFORM ... THRU <exit-paragraph>` range (a `.cut` test's own, or one
   written in-program) covering a real intermediate paragraph got a
   clean plan and a silently changed early-exit path: the original
   `GO TO` skips the intermediate paragraph, `EXIT PARAGRAPH` doesn't.
2. `EXIT SECTION` support (the original `_safe_section_entry_points`
   first-paragraph shape) was unsound two ways -- a cleanup paragraph
   after the exit-only paragraph inside the same section was silently
   skipped, and the splice applied even in `find_terminator_plans`' own
   unverified "shape 3" (a `.cut` `perform_target` naming the section's
   first paragraph directly). Both need suite-case context this
   whole-program function doesn't have; SECTION support is removed for
   now rather than patched further (`GotoExitPlan.exit_kind` is always
   `"PARAGRAPH"`).
3. A computed or multi-target `GO TO` naming the exit-only paragraph was
   invisible to the all-or-nothing check (`_go_statement_target` returns
   `None` for it), so it never disqualified that target even though it's
   a real GO TO edge into it -- `find_terminator_plans` could narrow
   `_go_to_targets` by a paragraph that wasn't actually fully
   neutralized. Fixed with a separate scan
   (`_go_statement_raw_targets`) that disqualifies any target named by a
   GO TO the per-site loop can't resolve.

The same review also caught a fourth `find_terminator_plans` call site
(`mutation/runner.py`, backing `mockymock mutate`) that was never wired
up to compute or pass `goto_exit_plans` -- fixed the same way as
`run`/`debug`/`export`. See
`docs/2026-08-17-goto-exit-paragraph-simplification-design.md`'s
"Revision note 2" for the full account.

**Span computation is the load-bearing detail, and the first
implementation got it wrong** (caught by actually running `mockymock
export` on the textbook idiom, not by any check): a `GO TO` nested inside
an `IF`/`EVALUATE` branch -- the idiom's own motivating shape -- cannot
use `statement_span` (correct only for top-level statements; it has no
location data for block words like `END-IF`, so it silently extended the
replacement span past the `GO TO` and commented out the enclosing
`END-IF` too, turning `EXIT PARAGRAPH` unconditional and permanently
dead-coding whatever followed the `IF`). Fixed with `source_map.
nested_statement_span` -- `_nested_site_span`'s "stop before the next
scope-map boundary" rule, factored out to operate on a raw statement
with no `MockCategory`/own-terminator concept -- and a
`refusal._go_statements_with_nesting` walker (mirrors
`_plain_perform_statements`' `nested`/`in_boundary` tagging) so
`find_goto_exit_plans` knows which span function applies. `GotoExitPlan`
carries the precomputed, validated `span` (never `None` on a returned
plan); `splicer.orchestrator.splice_program`'s `goto_exit_plans` loop
uses it as-is via `comment_and_replace`, never re-deriving it. Regression-
pinned by `tests/unit/test_goto_exit.py::test_nested_goto_replacement_
does_not_swallow_the_enclosing_end_if`.

No `UT-EARLY-EXIT` flag is involved -- unlike terminator neutralization,
this never propagates through an intermediate `PERFORM` chain (no
`chain_performs`, no `build_chain_check`), since it always ends the SAME
paragraph the `GO TO` already lived in
(`injector.build_goto_exit_replacement`).

`refusal.find_terminator_plans` narrows its own `_go_to_targets` by every
fully-neutralized `GotoExitPlan` target before deriving
`_go_to_fallthrough_targets` from it -- so a terminator chain whose only
obstacle was this exact idiom (the exit-only paragraph falling through,
per `_falls_through`, into whatever follows it in source order) now
qualifies for flag-propagation neutralization too, where before it
refused `UNSUPPORTED_TERMINATOR_LAYOUT`.

Also closes, for this one shape, an adjacent gap the design doc names but
does not otherwise fix: mockymock's reachability BFS always follows a
`GO TO` edge regardless of whether the `.cut` test declared a matching
`PERFORM ... THRU`, but the compiled driver's own `PERFORM {target}
[THRU {thru}]` has no cross-check against what the program's control flow
needs for correct runtime return semantics -- a `.cut` author who forgot
`THRU MAIN-EXIT` could get a suite that compiles clean and runs silently
wrong. Once the `GO TO` is spliced away, a plain `PERFORM` (no `THRU`)
behaves correctly on both paths, provided the exit-only paragraph is the
immediate next paragraph after the perform target in source order (the
one THRU-elision shape this feature claims; a THRU range covering real
intermediate paragraphs is not touched).

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
| `EXEC SQL INCLUDE <member>` (anything else) | resolved via `--copybook-path` — a synthetic `COPY <member>.` snippet is expanded through cobolparser's public `expand_copybooks` (not `path_resolver` internals, which aren't in `cobolparser.preprocess`'s `__all__`) and the normalized result is spliced in and re-scanned in place, so an embedded `DECLARE ... TABLE` stanza (DCLGEN-style) gets commented out by the branch above with no new recursion. No `--copybook-path`, or member not found → `UNRESOLVED_COPYBOOK` (same code plain unresolved `COPY` uses). A second live `EXEC SQL INCLUDE` found while re-scanning already-spliced content → `UNSUPPORTED_DATA_DIVISION_EXEC` (only one level of resolution supported) |
| anything unrecognized | `UNSUPPORTED_DATA_DIVISION_EXEC`, fail closed |

**EXEC SQL INCLUDE member resolution**: unlike SQLCA (a hardcoded field
list), a non-SQLCA `INCLUDE <member>` has no fixed content -- it must be
read from disk. Resolution deliberately goes through the *public*
`cobolparser.preprocess.expand_copybooks` on a synthetic one-line
`COPY <member>.` snippet, not `cobolparser.preprocess.path_resolver`'s
`find_copybook_file`/`CopybookSearchPath` -- those live outside
`cobolparser.preprocess`'s `__all__` and are not pinned by
`interface-contract.md`. This also means INCLUDE resolves exactly the way
plain COPY does (same extensions, same case rules, same path-traversal
protection) for free, rather than risking a second resolution
implementation that quietly diverges from the first.

**Important invariant**: the generated SQLCA is spliced in **after
parsing** and is therefore not part of the parsed AST at all. This means
`reset.py`'s WORKING-STORAGE reset never touches it — SQLCODE/SQLSTATE
are expected to survive across test cases unless a mock body explicitly
sets them, which is why the scaffold generator's placeholder EXEC SQL mock
bodies always set SQLCODE explicitly in every case. A resolved `EXEC SQL
INCLUDE <member>` (non-SQLCA) shares this exact property for the same
reason: `expand_copybooks` runs on a synthetic `COPY <member>.` snippet at
splice time, not on `raw_source` before `parse_cobol`, so these fields are
equally invisible to `reset.py` and equally expected to be set fresh by a
mock body on every run — the `ROWS` sugar (`build_rows_block`, "Dispatch
and Trap Generation" above) does this automatically via its per-row
`MOVE`s.

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
performs the target paragraph, then checks `expectations` (the
directive's own relation from `ExpectDirective.operator` — `=` for plain
`TO BE`, plus `NOT =`/`>`/`<`/`>=`/`<=` and their negations from the
`[NOT] TO BE [GREATER|LESS THAN [OR EQUAL TO]]` phrases, compiled to the
operator's *negation* via `_EXPECT_FAIL_CONDITIONS` since the generated
IF guards the failure branch; `>=`/`<=` negate to plain `<`/`>` so every
emitted condition stays a simple COBOL-85 relational — keep the map in
sync with `model.EXPECT_OPERATORS`) and `verifications` (tally-based
`VERIFY ... WAS CALLED` conditions from `_verify_condition`: `ONCE` →
`NOT = 1`, `NEVER` → `NOT = 0`, `AT LEAST ONCE` → `< 1`, `N TIMES` →
`NOT = N`), incrementing `UT-FAIL-COUNT` and displaying a `CASE NNN
FAIL` line on any mismatch.

FAIL lines include the actual value alongside the expectation, mirroring
the format the MVP plan and `report` tests always assumed: an EXPECT
mismatch displays `expected <name> <operator> <value>, got ` (the
operator echoed verbatim, so the pre-operator `=` shape is unchanged for
plain `TO BE`) followed by the data
item itself (shown in the field's own PIC formatting, e.g. `00090.00`),
and a VERIFY mismatch appends `, got <n>` where `<n>` is the tally moved
through the shared `UT-TALLY-EDITED` scratch field (`PIC Z(8)9`, declared
only when the suite has verifications) and trimmed via `FUNCTION TRIM` so
the count prints as `3` rather than `000000003`.

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

## Per-case state, implicit moves and DIB synthesis (2026-10-05 bug hunt)

- **RETURN-CODE (#140).** `build_driver` emits `MOVE 0 TO RETURN-CODE`
  at the start of every case and before the final `STOP RUN`: pass/fail
  travels in the markers, not the exit status.
- **Reset coverage (#147).** `reset.reset_move_lines` now covers FILE
  SECTION (the first record of each FD -- the others share its storage),
  WORKING-STORAGE and LOCAL-STORAGE.
- **SQLCA (#148).** `sqlca.sqlca_reset_lines` adds `INITIALIZE SQLCA` plus
  the SQLCAID/SQLCABC eye-catchers to the reset when mockymock generated
  the SQLCA, so one case's SQLCODE no longer leaks into the next.
- **READ ... INTO / WRITE ... FROM (#149).** `splicer/io_copy.py`: the
  dispatch block moves the FROM item to the record before the body, and
  the record to the INTO item after each `ROWS` row or after the body --
  skipped when the mock body or rows already name the INTO item or
  anything under it (how bodies written earlier set it). `MockSurface.
  data_layout` carries the FD-record and subtree map it needs.
- **DLIDIB (#145).** `analysis/cics_eib.py` also detects references to
  `DIBSTAT` and the other DIB fields in an `EXEC DLI` program that does not
  declare them; `splicer/cics_eib.py` then emits an `01 DLIDIB` layout
  (reset with `INITIALIZE DLIDIB`).

## `record_targets` — `mockymock run --record-expectations` (2026-08-04)

`build_driver` takes an optional fourth parameter,
`record_targets: dict[int, list[str]] | None` (case index -> data-names),
defaulting to `None`/`{}` so ordinary `run` (the flag not passed) is
byte-for-byte unaffected — the same "opt-in, zero-cost when absent"
property `--trace`'s `MOCK:` markers already have. `_build_testcase_paragraph`
emits one additional line per name in that case's list, right after the
`EXPECT`/`VERIFY` checks and before the `CASE ... END` marker (the exact
point a real `EXPECT` for that field would run):

```cobol
DISPLAY "__MOCKYMOCK__ RECORD 001 WS-NET-TOTAL: " WS-NET-TOTAL
```

This deliberately reuses the FAIL line's own proven-safe shape — a string
literal immediately followed by a bare identifier, letting GnuCOBOL's own
`DISPLAY` render the field in its native `PICTURE` formatting — rather
than inventing a new codegen primitive. Unlike the `--trace` `MOCK:`
marker (which has no case id in scope at its splice site and is therefore
attributed positionally, by `report.results.parse_stdout`, to "whichever
case's START printed most recently"), the `RECORD` marker carries a real
case id (`case_id` is already in scope inside `_build_testcase_paragraph`)
and is attributed by id, the same way `CASE ... FAIL`/`CASE ... END` are.

`mockymock.analysis.stub_expectations.scan_stub_expectations` is what
builds the `record_targets` dict the CLI passes in — see
[analysis](analysis.md) — and `mockymock.report.record_rewrite` is what
turns the recorded `__MOCKYMOCK__ RECORD` lines back into a rewritten
`.cut` file after the run — see [report](report.md). Full design:
docs/2026-08-04-record-expectations-design.md.

# See Also

- [dsl](dsl.md) — `MockTestSuite`/`MockTestCase`/`MockDirective` model and
  `.cut` parsing that the splicer consumes.
- [analysis](analysis.md) — `mock_surface` boundary-site detection and the
  refusal gate that must run before `orchestrator.splice_program`.
- [runtime](runtime.md) — compiling and executing the spliced output
  through GnuCOBOL, and parsing the `__MOCKYMOCK__` DISPLAY markers back
  into results.
- [report](report.md) — the `RECORD` marker in `parse_stdout`'s protocol
  table, and `record_rewrite.py`'s post-run `.cut` rewrite.
