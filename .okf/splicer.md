---
type: Module
title: Splicer
description: Turns mock_surface boundary sites into spliced COBOL source — dispatch blocks, tally fields, WORKING-STORAGE reset, and the generated SQLCA.
tags: [splicer, injection, cobol-source]
timestamp: 2026-07-06T01:00:00Z
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

sqlca.transform_data_division_exec ──▶ runs on DATA DIVISION before any of
                                        the above, independently
```

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
paragraph-header-or-statement-start, or EOF if it's the program's last
statement. `collect_boundaries` walks every paragraph (including nested
`_sections`) and every statement's `.location.line`.

**Phantom `"."` paragraphs**: cobolparser emits a paragraph literally named
`"."` for the sentence-terminating period line after an `EXEC ... END-EXEC`
block (verified empirically — a program with two EXEC SQL paragraphs
yields two extra `"."` paragraphs anchored at the END-EXEC lines).
`collect_boundaries` filters these out by checking
`paragraph.paragraph_name.strip(".") == ""`: treating one as a real
boundary would cut an EXEC statement's span one line short of its
END-EXEC, leaving a dangling END-EXEC in the spliced output.

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

# WORKING-STORAGE Reset (reset.py)

Because one binary serves the whole suite, case N's leftover state would
otherwise leak into case N+1. `reset_move_lines(program)` produces one
reset line per top-level (level `01` **or** `77`) WORKING-STORAGE item —
`77`s are standalone items just like `01`s and would leak state if
skipped.

| Item shape | Reset line | Why |
|---|---|---|
| Elementary, has `VALUE` clause | `MOVE <value> TO <name>` | restores the declared initial value |
| Elementary, no `VALUE` clause | `MOVE 0 \| SPACES TO <name>` | COBOL's conventional type default (numeric vs alphanumeric), a deliberate divergence from "truly undefined" memory in exchange for deterministic tests |
| Group, no `VALUE` clause | `INITIALIZE <name>` | a `MOVE SPACES` over a group would write spaces across numeric children, corrupting them for the next case's arithmetic; `INITIALIZE` zeros numeric children and space-fills alphanumeric ones |

**Known v1 fidelity limit**: `INITIALIZE` does not restore a group's
children's own `VALUE` clauses — still strictly better than
space-filling, but not perfect fidelity to declared initial state.

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

# Generated SQLCA (sqlca.py)

GnuCOBOL cannot process any EXEC SQL block at all, including declarative
ones in the DATA DIVISION, so `transform_data_division_exec` runs on the
normalized lines independently of (and before) the PROCEDURE DIVISION
splicing above:

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
