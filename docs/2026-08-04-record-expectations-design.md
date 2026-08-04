# mockymock — `run --record-expectations` (golden/characterization mode)

Date: 2026-08-04
Status: proposed

## Motivation

cobol-parser's `gen-fixtures` program-scoped test-data initiative
(`cobol-parser/docs/plans/2026-08-02-program-data-generation-*.md`) generates
a `FixtureBundle` per program: mocked input data for every IN/BIDIRECTIONAL
boundary, plus a per-scenario `Expectation` list asserting what the program
should do with it. As of that repo's Phase 7, every `Expectation` is one of
three tiers (`cobolparser/generators/program_fixtures.py`,
`docs/fixture-bundle-schema.md` in that repo):

- **Tier 1** (`kind="call_count"`) — exact by construction from the
  scenario's own generated sequence length.
- **Tier 2** (`kind="field_equals"`) — exact by construction from
  `cobolparser.analysis.const_fold.ConstantFolder`, a single-pass constant
  fold seeded with the scenario's own mocked inputs. Deliberately
  conservative: any ambiguity (a loop, a branch, `DIVIDE`, `CALL`,
  `ROUNDED`, self-referencing arithmetic, ...) poisons the field rather than
  guessing, so a field only ever appears here with a value that is
  *certainly* correct.
- **Tier 3** (`kind="stub"`) — everything the fold couldn't resolve: a field
  the program `DISPLAY`s or `WRITE`s whose value depends on something the
  fold refuses to guess at (a loop-computed total, a value read from a
  mocked `CALL`'s OUT parameter, ...). cobol-parser's own plan is explicit
  that these become "a `*>` comment, never as a live assertion" — the
  generator that will consume this bundle (mockymock `generate
  --with-data`, cobol-parser Phase 8 / this repo's own next phase) is
  expected to emit each tier-3 stub as an inert comment next to where a
  real `EXPECT` would go, precisely because cobol-parser has no way to know
  the right value and asserting a wrong one is worse than asserting
  nothing.

That leaves a gap: a scaffolded `.cut` file can end up with dozens of
`TESTCASE`s that assert *nothing* about their tier-3 fields, forever,
unless a human manually runs the suite, reads the output, and hand-types
each `EXPECT`. That's exactly the "characterization test" workflow this
repo doesn't have a tool for yet — record what the code *actually* does
right now, so future changes are checked against that recording (the same
shape as Jest's `--updateSnapshot` or Python's `syrupy`, applied to COBOL
boundary behavior instead of object trees).

`mockymock run --record-expectations` closes it: run the suite once,
capture the real runtime value behind every still-open stub in the
`.cut` file, and rewrite the file with those stubs turned into real
`EXPECT` lines. It is intentionally the **only** piece of this that lives
in mockymock — cobol-parser's plan says so explicitly ("Keep it out of
cobol-parser entirely"), because turning an *observed* value into an
*asserted* one is a test-authoring decision about a `.cut` file, not
something the static generator should ever do on its own.

## Scope

**In scope (v1):**
- A `*> STUB EXPECT <data-name> -- <note>` comment convention: syntactically
  an ordinary `*>` comment (parses today with zero grammar changes — the
  DSL parser already ignores `*>` lines outside a `MOCK` body), carrying
  just enough structure for this feature's own text scanner to find it.
- `mockymock run --record-expectations`: runs the exact same
  parse → splice → compile → run pipeline `run` already does (no new
  refusal rules, no new compile mode), with one addition — every stub
  comment inside an ordinary (non-`PROVIDER`) `TESTCASE` gets a matching
  `__MOCKYMOCK__ RECORD` marker spliced in, at the same point `EXPECT`/
  `VERIFY` checks already run.
- Rewriting the `.cut` file in place: each stub line whose value was
  actually observed this run becomes `EXPECT <data-name> TO BE <value>`,
  textually replacing only that one line. Cumulative, best-effort:
  everything recordable gets recorded and reported; everything not
  (crashed case, case excluded by `--case`/`--tag`, a stub outside any
  `TESTCASE`) is reported as skipped with a specific reason, never silently
  dropped.
- The "never overwrite a hand-edited `EXPECT`" guarantee, achieved
  structurally (see Design) rather than by tracking provenance.
- Numeric/alphanumeric literal-quoting for the written-back value, and the
  trailing-space trim that follows from COBOL's own space-padding
  comparison rule.

**Explicitly out of scope (v1):**
- Stub comments inside a `PROVIDER`-templated `TESTCASE`. A `PROVIDER`
  template's body is written **once** in the file but expands into *N*
  independent runtime cases (`dsl.md`: expanded cases' `.line` points at
  their own `ROW` line, not the shared template header) — one physical
  stub comment would need *N* different recorded values, one per row,
  which is a fundamentally different (and more useful, once `PROVIDER`
  rows can hold expected-value columns too) feature. A stub caught inside
  such a template is reported as skipped, not silently ignored and not
  guessed at.
- Any new refusal rule beyond what `run` already enforces. If the suite
  doesn't compile or run today, `--record-expectations` doesn't change
  that — it can only ever record fewer things, never more, than a plain
  successful `run`.
- A `--case`/`--tag`-aware "your selection excluded fields with open stubs"
  warning beyond the existing per-stub skip reasons. Composing
  `--record-expectations` with `--case`/`--tag` is supported (only
  selected cases can record anything, which falls out for free — see
  Design), but no extra UX is added to point out cases the user didn't
  select.
- A `--output PATH` escape hatch to write the rewrite somewhere other than
  `--cut`'s own file. `generate`/`export` have `-o`/`--output` because they
  produce a *new* artifact from a `.cbl`; this command mutates an existing,
  version-controlled `.cut` in place, the same way `black`/`ruff --fix`
  mutate source in place. Can be added later if a real need shows up.
- Re-recording a value that already has a real `EXPECT` line, whether that
  line was hand-written or produced by an earlier `--record-expectations`
  run. To refresh a recorded value, regenerate the stub (re-run
  `mockymock generate --with-data`, or hand-delete the `EXPECT` line and
  replace it with a `*> STUB EXPECT ...` comment) and record again. A
  finer-grained `--force`/`--update` mode is a plausible fast-follow, not
  needed for v1's core value (turning silence into a checked assertion at
  least once).

## Design

### Stub comment grammar

```cobol
TESTCASE "CALC-TOTALS boundaries: CALL DISCOUNT"
    MOCK CALL "DISCOUNT"
        MOVE 5 TO RETURN-CODE
    END-MOCK
    PERFORM CALC-TOTALS
    EXPECT WS-DISCOUNT-CODE TO BE 5
    *> STUB EXPECT WS-NET-TOTAL -- computed in CALC-TOTALS
```

```
*> STUB EXPECT <data-name> [-- <note>]
```

- `<data-name>` reuses `dsl/parser.py`'s existing `_SUBSCRIPTED_NAME`
  fragment (the same one `EXPECT`/`MOVE` targets already parse with) so a
  subscripted stub (`*> STUB EXPECT WS-TABLE(1, 1) -- ...`) is recognized
  identically to how a hand-written `EXPECT` would parse the same name.
  This is a plain regex match against raw text, not a grammar addition —
  see "Why a raw-text scanner, not a grammar addition" below.
- `-- <note>` is optional and carries through unchanged from cobol-parser's
  `Expectation.note` (e.g. `"computed in CALC-TOTALS"`, echoing tier 2's
  own note style for consistency between tiers). Purely documentation; the
  scanner never parses its contents.
- Case-sensitive `STUB EXPECT` (matching this DSL's existing "every keyword
  is case-sensitive uppercase" rule) so a human note that happens to start
  with lowercase "stub expect..." is never mistaken for the directive.
- Because it's an ordinary `*>` comment, a `.cut` file full of unfilled
  stubs is valid, parses today with **zero parser changes**, and runs
  clean — the stub does nothing at runtime until it's recorded. This is
  the same design property cobol-parser's plan calls for ("never as a live
  assertion").

### Why a raw-text scanner, not a grammar addition

`mockymock collect --cut PATH` parses a `.cut` file with no `.cbl` argument
at all (`.okf/cli.md`), and every other subcommand shares one `parse_cut()`
→ `MockTestSuite` path. Teaching the grammar about stub comments would mean
either giving `MockTestCase` a new field every consumer (`collect`, `lint`,
`generate` cross-checks, the splicer) has to learn to ignore, or forking
`parse_cut()`'s behavior by caller — the same tradeoff the CSV-rows design
doc rejected for a similar reason. A stub comment carries no information
any other subcommand needs; it matters to exactly one feature. So
`--record-expectations` gets its own small, self-contained scanner
(`mockymock/analysis/stub_expectations.py`, new module) that:

1. Regex-scans the raw `.cut` text (not the parsed model) for two things:
   - Every line matching `^\s*TESTCASE\s+"` — a real `TESTCASE` header.
     `"USING PROVIDER" in line` (a plain substring check — the grammar
     requires this literal spelling, uppercase, on the same physical line)
     flags it as provider-templated.
   - Every line matching `^\s*\*>\s*STUB EXPECT\s+(?P<name>...)\s*(?:--\s*(?P<note>.*))?$`
     using the shared `_SUBSCRIPTED_NAME` fragment for `<name>`.
2. Attributes each stub line to the nearest **preceding** `TESTCASE` header
   line (by raw line number). No preceding header → `"not inside any
   TESTCASE"`. Preceding header is provider-templated → `"inside a
   PROVIDER-templated TESTCASE, unsupported in v1"`.
3. For a stub attributed to an ordinary header, cross-references
   `suite.test_cases` (the real, already-parsed, post-`_expand_providers`
   list) by matching `.line` against that same header's line number —
   `MockTestCase.line` for a **non**-provider case is documented to be the
   original header line verbatim ("strict backward compatibility" —
   `dsl.md`), so this match is exact, not approximate. The matching
   entry's 1-based position in `suite.test_cases` is exactly the case-id
   `driver.py` will assign it (`_build_testcase_paragraph`'s
   `f"{index:03d}"`), which is what makes the whole thing attributable
   without touching the parser or the driver's existing indexing scheme.

This two-step raw-header-scan-plus-cross-reference is deliberately more
careful than the simpler "just bucket stubs between consecutive
`suite.test_cases[i].line` values" approach: that simpler version breaks
silently the moment any earlier `TESTCASE` in the file is
provider-expanded into anything other than exactly one row, because every
later case's position in `suite.test_cases` (and therefore its assumed
line-ordering relative to the raw file) shifts. Scanning raw `TESTCASE`
header positions directly sidesteps that shift entirely — it never
depends on expansion having happened at all.

### Threading recorded targets into the driver

`build_driver(suite, reset_lines, registry)` gains one new parameter,
defaulting to "record nothing" so ordinary `run` (no
`--record-expectations`) is byte-for-byte unaffected:

```python
def build_driver(
    suite: MockTestSuite,
    reset_lines: list[str],
    registry: TallyRegistry,
    record_targets: dict[int, list[str]] | None = None,  # case index (1-based) -> data-names
) -> DriverArtifact: ...
```

`_build_testcase_paragraph` emits one new `DISPLAY` line per recorded name,
placed right after the existing `EXPECT`/`VERIFY` checks and before the
`CASE ... END` marker (same position a real `EXPECT` for that field would
occupy) — deliberately mirroring the FAIL line's own proven-safe technique
(`driver.py`, today):

```cobol
DISPLAY "__MOCKYMOCK__ RECORD 003 WS-NET-TOTAL: " WS-NET-TOTAL
```

This is the *exact* shape `driver.py` already uses for a FAIL line's `got
" <data-name>` suffix — a string literal directly followed by the bare
identifier, letting GnuCOBOL's own `DISPLAY` render the field in its
native `PICTURE` formatting. No new codegen primitive, no new escaping
rule: reusing a mechanism this codebase has already compiled and run
thousands of times is safer than inventing a second way to print a field's
value. Unlike the `MOCK:` trace marker (which carries no case id because
trace mode's dispatch blocks don't have one in scope), the `RECORD` marker
**does** carry the case id — `_build_testcase_paragraph` already has
`case_id` in scope at this point, so there's no reason to fall back to
positional attribution the way trace mode had to.

### New stdout marker (`report/results.py`)

```python
_RECORD_RE = re.compile(
    r"^__MOCKYMOCK__ RECORD (?P<id>\S+) (?P<name>\S+): (?P<value>.*)$"
)
```

`TestResult` gains `recorded: list[tuple[str, str]] = field(default_factory=list)`
(name, raw displayed value), appended by id-lookup through `by_id` — the
same attribution `CASE ... FAIL`/`CASE ... END` already use, **not** the
positional "most recently started case" trick `MOCK:` needs (this marker
already carries a real id, so there's no reason to weaken its attribution
to match a marker that doesn't). An id with no matching `TestResult` is
recorded in a new `suite.orphan_records: list[tuple[str, str, str]]`
(id, name, value) — diagnostic only, does not gate `all_passed` (mirroring
`orphan_ends`'s treatment: a marker that doesn't participate in pass/fail
carries no failure evidence to lose by going unattributed). Recording
markers are **only ever emitted when `--record-expectations` is passed**
(the `record_targets` parameter is `None`/empty otherwise), so
`suite.recorded`/`orphan_records` stay empty and `parse_stdout`'s existing
behavior is unchanged for every caller that isn't this feature —
mirroring exactly how `mock_hits` stays empty outside `--trace`.

### Value formatting: quoting and trimming

Deciding whether a recorded value becomes a bare numeric literal or a
quoted string in the rewritten `EXPECT` line is done by **inspecting the
observed text itself**, not by resolving the field's `PICTURE` from the
AST:

| Observed text matches `^-?\d+(\.\d+)?$` | Rendered as |
|---|---|
| Yes | bare (`EXPECT WS-TOTAL TO BE 12345`) |
| No | quoted, trailing spaces trimmed, embedded `"` doubled (`EXPECT WS-NAME TO BE "SMITH"`) |

This is deliberately a text-shape check, not an AST/`PICTURE` lookup,
because a numeric (or numeric-edited) `PICTURE`'s `DISPLAY` output is
*already* constrained by GnuCOBOL to be plain digits/optional
decimal-point/optional leading `-` for a plain numeric item — there is no
"resolve the field, then decide" step needed, and skipping it also means
this feature never needs to resolve a data-name to a `CobolDataItem` at
all (no new by-name index, no new "field not found" failure mode to
design around). Trailing-space trimming on the alphanumeric path is safe
by construction, not a fidelity compromise: COBOL's `=` comparison pads
the shorter of two operands with spaces before comparing, so
`WS-NAME = "SMITH"` and `WS-NAME = "SMITH               "` are the
identical comparison against a `PIC X(20)` field — trimming changes zero
runtime behavior and matches how a human author would actually type the
literal. Quote-doubling reuses `driver._display_text`'s exact technique
for consistency with how this codebase already escapes embedded quotes.

**Flagged for empirical verification at implementation time** (matching
this repo's own established practice — the CSV-rows design doc's typing
table was verified against a real `mockymock-cobc` container rather than
assumed, and this should be too): a numeric-**edited** `PICTURE` (`PIC
ZZZ9`, `PIC $$$,$$9.99`) can `DISPLAY` leading spaces, `$`, or `,`, which
fails the bare-numeric regex above and falls to the quoted path. Whether
`EXPECT <name> TO BE "<edited text>"` round-trips as the *same* comparison
`driver.py` would generate for a numeric-edited field needs a real
compile-and-run check before this is trusted for that PICTURE family;
until verified, treat a quoted recording against a numeric-edited field as
a known v1 fidelity gap, not a silent correctness assumption.

### Rewriting the `.cut` file

For every stub with a recorded value: build the replacement line
`<original leading whitespace>EXPECT <data-name> TO BE <rendered value>`
(reusing the stub comment's own indentation, so the rewritten file's
formatting stays consistent with its neighbors), and replace that one
line, by its 1-based line number, in the file's text. No lines are
inserted or removed (a stub comment and its replacement `EXPECT` are both
exactly one line), so there is no bottom-up/top-down ordering hazard the
splicer's own `comment_and_replace` has to worry about — a simple
`line_number -> new_text` map applied in one pass over
`text.splitlines()` is sufficient and correct regardless of application
order.

**The file is only ever written if at least one stub was actually
recorded.** Zero recordings (every stub skipped, or the `.cut` had none to
begin with) leaves the file untouched — no diff, no timestamp change, for
a command that did nothing.

### "Never overwrite a hand-edited `EXPECT`" — structural, not tracked

The scanner's regex only ever matches literal `*> STUB EXPECT ...` comment
lines. The moment a stub is recorded (by this feature) or hand-written (by
a person) into a real `EXPECT <name> TO BE <value>` line, that line
**cannot match the stub regex again** — it is no longer a comment at all.
There is no separate "was this auto-generated or hand-edited" bit to track,
no hash to compare, no risk of the tracking itself drifting from reality:
the invariant holds because a rewritten line has structurally left the set
of things this feature ever looks at. Running `--record-expectations`
twice in a row against a `.cut` with no intervening edits is therefore
provably idempotent — the second run finds zero remaining stub comments
and (per the rule above) touches nothing. This is the property the
implementation's idempotency test pins directly (see Testing), and it is
also this design's answer to the parent plan's "refuse to overwrite a
hand-edited `EXPECT`" requirement: refusal isn't a check that has to run
and might have a bug in it, it's a consequence of what text pattern the
scanner is looking for.

### Best-effort, cumulative reporting

`--record-expectations` never aborts the run early over one bad stub. It
collects, for every stub found by the scanner:

| Outcome | Reason text |
|---|---|
| Recorded | (none — printed as `recorded <name> (line <N>) = <value>`) |
| Case not selected this run | `case excluded by --case/--tag` |
| Case never printed a RECORD marker for this name | `case crashed before reaching the record point` (mirrors `TestResult.crashed`'s own STOP-RUN hypothesis) |
| Stub not inside any `TESTCASE` | `not inside any TESTCASE` |
| Stub inside a `PROVIDER`-templated `TESTCASE` | `inside a PROVIDER-templated TESTCASE, unsupported in v1` |

Printed as a summary block after the normal `format_console` run report
(record mode is additive — the suite's own pass/fail report, JUnit/JSON
output, coverage, and trace all behave exactly as they do for a plain
`run`; recording is a side channel, not a replacement mode):

```
mockymock run: --record-expectations: recorded 2, skipped 1
  recorded WS-NET-TOTAL (line 42) = 145.50
  recorded WS-DISCOUNT-CODE (line 43) = 5
  skipped WS-DEBUG-COUNTER (line 61): case crashed before reaching the record point
```

**Exit code is unaffected by recording outcomes** — it stays exactly
`0 if suite_result.all_passed and executed.exit_code == 0 else 1`, same as
plain `run`. Recording is orthogonal to pass/fail by design: a case whose
*other*, hand-written `EXPECT`s currently fail can still have its stub
recorded (you are characterizing what the code does today, not asserting
it's correct), and a `--case`-restricted run that could only attempt a
subset of stubs shouldn't fail a CI job over the ones it didn't touch.

### CLI

```
mockymock run <program> --cut PATH --record-expectations [... existing run flags]
```

One new `store_true` flag on the existing `run` subcommand (not a new
subcommand — it's the same pipeline, plus one splice-time addition and one
post-run rewrite step), following the same `run_parser.add_argument(...)`
convention every other `run` flag already uses. Composes with
`--case`/`--tag` (only stubs inside selected cases can record anything —
falls out of the pipeline for free, no special-casing needed) and with
`--coverage`/`--trace`/`--junit-xml`/`--json-report` (all independent
concerns; the new `RECORD` markers are simply additional stdout lines the
existing formatters never look at, so nothing about them needs to change).

## Implementation slices

Each independently testable, in dependency order:

1. **Stub scanner** (`mockymock/analysis/stub_expectations.py`): raw-text
   scan → list of `StubExpectation(line, case_index, data_name, note)` (or
   a skip reason). Pure text in, structured data out — no splicer, no
   Docker, fully unit-testable against literal `.cut` text fixtures
   (including the `PROVIDER`-adjacent and outside-any-`TESTCASE` edge
   cases).
2. **Driver/splicer plumbing**: `build_driver`'s new `record_targets`
   parameter, `_build_testcase_paragraph`'s new `DISPLAY` line. Unit-tested
   the same way `test_driver.py` already tests generated procedure text —
   assert the exact `DISPLAY "__MOCKYMOCK__ RECORD ..."` line appears (or
   doesn't, when `record_targets` is `None`) in the generated lines, no
   compiler needed.
3. **`results.py` RECORD marker**: `_RECORD_RE`, `TestResult.recorded`,
   `suite.orphan_records`. Unit-tested with synthetic `parse_stdout(...)`
   strings exactly like every other marker in that module already is —
   no Docker needed for this slice either.
4. **CLI wiring + rewrite step** (`mockymock/cli/main.py`): the
   `--record-expectations` flag, threading the scanner's output into
   `build_driver`, and the post-run value-formatting + line-rewrite +
   summary-printing logic. This is the slice that needs the full pipeline,
   so its direct tests are integration tests (below); the
   formatting/quoting decision table itself is still unit-testable in
   isolation (pure string-in, string-out).

## Testing

- **Unit** (`tests/unit/test_stub_expectations.py`): the scanner against
  hand-written `.cut` text — a stub inside an ordinary case, a stub before
  any `TESTCASE`, a stub inside a `PROVIDER`-templated case (both the
  case-id cross-reference and the provider-detection path), a subscripted
  stub name, a stub with no `-- note` suffix, two stubs in the same case.
  `tests/unit/test_driver.py`: `record_targets` produces the expected
  `DISPLAY "__MOCKYMOCK__ RECORD ..."` line at the right position, and is
  fully absent when the parameter is omitted (byte-identical to today's
  output — this is the regression test that guarantees ordinary `run`
  never changes). `tests/unit/test_report.py`: `_RECORD_RE` parsing,
  including an orphan (unknown id) case. A dedicated
  `tests/unit/test_record_expectations_format.py` for the
  numeric-vs-quoted rendering table (including the empirically-flagged
  numeric-edited case, once verified) and the trailing-space/quote-doubling
  rules.
- **Integration** (`tests/integration/fixtures/record_expectations/` — new
  fixture pair, `@requires_docker`): a small program with one tier-3-shaped
  field (something the `.cut` deliberately leaves as a `*> STUB EXPECT`
  rather than a real `EXPECT`, simulating what `generate --with-data` will
  eventually scaffold), run with `--record-expectations`, asserting the
  rewritten `.cut` text contains the expected `EXPECT` line and that a
  **second** `--record-expectations` run against the now-rewritten file is
  a no-op (byte-identical file before/after) — this is the "golden re-run
  drift test" the parent plan's PR-slicing table names as this slice's
  gate. A second fixture proves the crash-skip path (a case whose
  `PERFORM` target reaches `STOP RUN` before the record point) reports the
  correct skip reason and leaves that one stub comment untouched while
  still recording sibling stubs in other cases.

## Docs to update after implementation

- `.okf/dsl.md` — the `*> STUB EXPECT` comment convention (framed clearly
  as a convention this one feature's scanner reads, not a grammar
  addition the core parser knows about).
- `.okf/cli.md` — `run --record-expectations` under the existing `run`
  section.
- `.okf/splicer.md` — `build_driver`'s new parameter, the `RECORD` marker
  codegen.
- `.okf/report.md` — the `RECORD` marker in the stdout-protocol table,
  `TestResult.recorded`/`orphan_records` in the data model.
- `README.md` — DSL reference section.
- `.okf/log.md` — dated entry once implemented. `CHANGELOG.md` is
  `release-please`-generated from Conventional Commits here (unlike
  cobol-parser's hand-maintained Keep-a-Changelog file) — nothing to
  hand-edit; just use a `feat(cli): ...` commit message.
- cobol-parser's `interface-contract.md` is **not** touched by this
  feature — it consumes only the `.cut` text convention documented here,
  never cobol-parser's bundle JSON or Python API directly (that
  integration is Phase 8's job, not this one's).

## Alternatives considered

- **Teaching the `.cut` grammar a real `STUB` directive** (parsed into
  `MockTestCase`, visible to `collect`/`lint`/every consumer) — rejected
  for the same reason the CSV-rows doc rejected threading the AST into
  `parse_cut()`: `collect` parses `.cut` files with no `.cbl` at all, and
  this feature is the only consumer that needs stub information, so it
  should own its own (much smaller) parsing rather than growing the shared
  grammar and shared model for one caller.
- **Tracking provenance explicitly** (e.g. a trailing `*> [auto-recorded]`
  marker after a filled-in `EXPECT`, or a checksum file) to distinguish
  "safe to re-record" from "hand-edited, leave alone" — rejected in favor
  of the structural invariant (a real `EXPECT` line can never match the
  stub-comment regex again). Provenance-tracking would need to survive
  hand-edits, reordering, and reformatting without going stale; "the thing
  we look for no longer exists" needs no such maintenance and cannot drift
  from reality.
- **Resolving each stub's data item from the AST to decide numeric-vs-
  quoted rendering** (mirroring how `reset.py`/the CSV-rows resolver look
  up `PICTURE` clauses) — rejected in favor of inspecting the observed
  `DISPLAY` text directly. A numeric `PICTURE`'s rendered text is already
  constrained to a shape a regex can recognize unambiguously for the
  common case, and skipping AST resolution entirely removes a whole
  "data-name not found" failure mode this feature would otherwise need a
  refusal reason for. Numeric-edited PICTUREs are the one place this
  shortcut is honestly uncertain — flagged for empirical verification
  rather than silently assumed either way.
- **Positional attribution for the `RECORD` marker** (like `MOCK:` trace
  markers, "belongs to whichever case's `START` printed most recently") —
  rejected: unlike the trace dispatch blocks, `_build_testcase_paragraph`
  already has the case id in scope at the exact point the `RECORD` line is
  emitted, so there's no structural reason to accept positional attribution's
  weaker guarantee when id-based attribution (already proven by
  `CASE ... FAIL`/`CASE ... END`) is available for free.
- **A whole-suite "all or nothing" rewrite** (only touch the file if every
  stub recorded cleanly) — rejected in favor of best-effort/cumulative:
  matches this codebase's consistent "collect every problem, report all of
  them, never silently drop one" posture (refusal gates, orphaned
  failures, duplicate case ids) rather than making one crashed case block
  recording for every other, unrelated case in the same file.
- **Gating the exit code on skipped stubs** (nonzero if anything was
  skipped, even if the suite itself passed) — rejected: would make
  `--record-expectations` unusable in a normal `--case`-scoped CI lane
  (every run would "fail" over stubs it never intended to touch) for no
  actual safety benefit, since skips are already fully reported in the
  printed summary.
