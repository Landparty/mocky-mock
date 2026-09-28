---
type: Module
title: Test Result Reporting
description: TestResult/TestSuiteResult data model plus console and JUnit XML formatters for compiled COBOL test runs; record_rewrite.py turns recorded RECORD markers into rewritten .cut EXPECT lines.
tags: [report, results, cli-output]
timestamp: 2026-09-27T00:00:00Z
---
# Overview

The compiled COBOL test binary emits plain stdout lines prefixed with
`__MOCKYMOCK__` as it executes TESTCASE blocks. `results.py` parses that
stream into a structured model; `formatters.py` renders that model into
human- and machine-readable reports.

```
compiled test binary stdout
        │  (__MOCKYMOCK__ ... lines)
        ▼
results.parse_stdout()  ──► TestSuiteResult { results: [TestResult], tests_run, failures }
        │
        ├─► formatters.format_console()   → plain-text PASS/FAIL listing
        └─► formatters.format_junit_xml() → JUnit-compatible <testsuite> XML
```

# stdout Protocol

`parse_stdout` matches seven line shapes via regex, one case per marker kind:

| Marker | Regex group(s) | Effect |
|---|---|---|
| `__MOCKYMOCK__ TESTSUITE: <name>` | `name` | sets `suite.suite_name` |
| `__MOCKYMOCK__ CASE <id> START: <name>` | `id`, `name` | creates a `TestResult`, appended to `suite.results` and indexed in `by_id`; an `id` that collides with one already indexed is recorded in `suite.duplicate_case_starts` as `(id, previous_name, new_name)` before `by_id[id]` is repointed to the new result -- `previous_name` is whatever this specific collision overwrote, not necessarily the very first START to use this id |
| `__MOCKYMOCK__ CASE <id> FAIL: <reason>` | `id`, `reason` | appends `reason` to the matching `TestResult.failure_reasons` (looked up by id); an unknown id is recorded in `suite.orphan_failures` as `(id, reason)` rather than dropped |
| `__MOCKYMOCK__ CASE <id> END` | `id` | sets the matching `TestResult.ended = True`; an unknown id is recorded in `suite.orphan_ends` rather than dropped |
| `__MOCKYMOCK__ SUMMARY: RUN=<n> FAILURES=<n>` | `run`, `failures` | sets `suite.tests_run` / `suite.failures` |
| `__MOCKYMOCK__ MOCK: <label>` | `label` | appends to the most recently started case's `TestResult.mock_hits`. **Trace mode only** — emitted by the splicer's mock dispatch blocks when `run --trace` is used |
| `__MOCKYMOCK__ RECORD <id> <name>: <value>` | `id`, `name`, `value` | appends `(name, value)` to the matching `TestResult.recorded` (looked up by id, same as FAIL/END — **not** positional like `MOCK:`); an unknown id is recorded in `suite.orphan_records` as `(id, name, value)` rather than dropped. **`--record-expectations` mode only** — emitted by `splicer.driver.build_driver`'s `record_targets` addition (2026-08-04) |

The `MOCK` marker is the one shape carrying no case id: it is attributed
positionally, to the case whose `START` most recently printed. That is
sound because the driver emits it from inside the case's own dispatch,
between that case's `START` and `END`. It exists because mock firing
order cannot be recovered from the execution-trace file — the dispatch
blocks are splicer-inserted, and the trace's line remap drops inserted
lines by design. See [cli](cli.md)'s `--trace` and
docs/2026-07-21-debug-trace-design.md.

**`_RECORD_RE`'s `name` group reuses `dsl.parser._SUBSCRIPTED_NAME`, not a
bare `\S+`** (fixed 2026-08-04, found by GitHub Copilot's automated review
of this PR and confirmed against the code before acting): a subscripted
data-name like `WS-TABLE(1, 1)` contains a space after the comma —
`scan_stub_expectations` explicitly supports this shape (see
[analysis.md](analysis.md)'s stub-expectations section) and `build_driver`
emits it into the `RECORD` line verbatim, so a plain `\S+` would stop at
that space, never find the `": "` the pattern then requires, and silently
drop the whole recorded value with no error at all.

`RECORD`, unlike `MOCK:`, carries a real case id — `build_driver` already
has `case_id` in scope at the exact point it emits this marker, so there's
no structural reason to fall back to `MOCK:`'s weaker positional
attribution. `value` is captured with `.*` (greedy, may be empty), not
`.+`, since a blank alphanumeric field or a value containing a literal `:`
(e.g. a time-of-day field) must parse whole rather than truncating at the
first colon. See [splicer](splicer.md) for the codegen and
[analysis](analysis.md)'s `stub_expectations.py` /
`record_rewrite.py` (below) for what consumes `recorded`/`orphan_records`
afterward, and docs/2026-08-04-record-expectations-design.md for the full
design.

The injector's `__MOCKYMOCK__ ERROR:` line (unmocked boundary reached) is
deliberately NOT in this table: nothing parses it. It reaches the user as
raw stdout text plus its `ADD 1 TO UT-FAIL-COUNT` contribution to SUMMARY.

Matching a FAIL line to its case is done purely by `id`, not by stream
position — so interleaved/out-of-order FAIL lines for different cases
still land correctly as long as each case's `id` is unique within the run.

# Data Model

```python
@dataclass
class TestResult:
    case_id: str
    case_name: str
    failure_reasons: list[str]   # empty list == no failures recorded
    ended: bool = False          # True once CASE <id> END is matched
    mock_hits: list[str]         # --trace only
    recorded: list[tuple[str, str]]  # (name, value) -- --record-expectations only

    @property
    def crashed(self) -> bool: ...  # not ended -- START seen, END never was

    @property
    def passed(self) -> bool: ...   # not failure_reasons and not crashed

@dataclass
class TestSuiteResult:
    suite_name: str
    results: list[TestResult]
    tests_run: int      # from SUMMARY RUN=
    failures: int        # from SUMMARY FAILURES= -- a *check* count, not a case count
    orphan_failures: list[tuple[str, str]]  # FAIL lines whose id never STARTed
    duplicate_case_starts: list[tuple[str, str, str]]  # (id, previous_name, new_name)
    orphan_ends: list[str]  # END lines whose id never STARTed -- recorded, doesn't gate
    orphan_records: list[tuple[str, str, str]]  # (id, name, value) -- same non-gating treatment

    @property
    def all_passed(self) -> bool: ...
    # failures == 0 and tests_run > 0 and not orphan_failures
    # and not duplicate_case_starts and all(r.passed for r in results)
    # (orphan_ends/orphan_records do NOT gate -- see Gotchas; the
    # per-case cross-check was added 2026-08-12, audit Finding 1: the
    # SUMMARY counter alone let a stray FAIL-shaped stdout line render
    # [FAIL] in every formatter while the exit code stayed 0)
```

Pass/fail/crash is derived, not stored directly. `crashed` is true when a
case's START marker printed but its END marker never did — the process
died mid-case (most commonly: its `PERFORM` target transitively reached
`STOP RUN`, which exits the whole compiled test binary before that case's
own `EXPECT`/`VERIFY` checks run, before its END marker prints, and before
any later case in the suite gets a chance to run). `passed` requires both
an empty `failure_reasons` *and* `not crashed` — a crashed case is never
reported as passed, regardless of what happened to print before the crash.
One COBOL TESTCASE can accumulate multiple failure reasons (e.g. multiple
failed EXPECT/VERIFY statements in the same case); all are recorded and
shown, not just the first.

`all_passed` also requires `tests_run > 0` and an empty
`orphan_failures` — a suite with zero cases executed (e.g. parse produced
no SUMMARY line, or the binary crashed before finishing), or with FAIL
lines it could not attribute to any case, is not reported as passing. This means a crash-mid-suite
scenario already produces a non-zero CLI exit code even without the
per-case `crashed` tracking above; `crashed` fixes the *human-facing*
report (console/JUnit), which otherwise showed the crashed case as `[PASS]`
purely from absence of a FAIL marker.

# Formatters

| Function | Output | Notes |
|---|---|---|
| `format_console(suite, crash_detail=None)` | Plain text | `TESTSUITE: <name>` header, one `[PASS]`/`[FAIL]`/`[CRASH]` line per case (indented, failure reasons indented further below), trailing `<run> run, <failures> failed[, <n> crashed]` summary line (`<failures>` is the raw SUMMARY check-count as-is; `<run>` falls back to `len(suite.results)` when `suite.tests_run` is 0 -- see Gotchas; the `, <n> crashed` segment only appears when `<n> > 0`) |
| `format_junit_xml(suite, crash_detail=None)` | Pretty-printed JUnit XML via `xml.etree` + `minidom` | `<testsuite name tests failures errors>` with one `<testcase>` per result; failing cases get a `<failure message>` child per failure reason, crashed cases get a single `<error message>` child instead (JUnit's own failure-vs-error distinction); orphan failures each get their own `<testcase name="orphan-<id>">` with an `<error>` child and are counted into `errors=` and `tests=`; `tests` uses the same `len(suite.results)` fallback as the console `<run>` count. All names/reasons/messages pass through `_xml_safe` first (see Gotchas) |

Both formatters take an optional `crash_detail: str | None`. The CLI passes
the *real* crash evidence when it has any -- `"binary timed out (exit 124);
see stderr below"` for a container-side timeout, `"binary exited with code
<n>"` for a runtime abort -- and the formatters render it under each
`[CRASH]` line (console) / inside the `<error>` message (JUnit). Only when
`crash_detail` is `None` (the binary exited 0, which is exactly what a
reached `STOP RUN` does) do they fall back to the
`_DEFAULT_CRASH_HYPOTHESIS` text `"PERFORM target reached STOP RUN?"`.
Do not re-hardcode that hypothesis into the message: it was previously
shown even for timeouts and aborts whose stderr evidence had been
discarded (audit 2026-07-07, findings 4.2/5.1).

## JSON run report (`report/json_report.py`)

`build_json_report(suite_result, cut_suite=None, crash_detail=None,
cut_file=None, program_file=None)` -> dict; `format_json_report(dict)` ->
str. Written by `run --json-report`. Adds what the XML cannot carry: per-case
`.cut` line numbers and tags (from the parsed `MockTestSuite`), per-failure
attribution (`kind` expect/verify/unknown, the failing directive's `.cut`
line, `expected`/`actual` split into fields — recovered by re-matching the
driver's failure-reason strings against the model: an EXPECT reason is
first matched against each directive's exact rendered head
`expected <name> <op> <value>, got `, since the runtime value after it may
itself contain `", got "`; only a reason no directive renders to falls
back to splitting on the LAST `", got "`), and a synthesized `"not_run"` entry for every selected case the
binary never printed a START marker for. An EXPECT failure head is split
into name/operator/expected by `_EXPECT_HEAD_RE` (the operator is one of
`model.EXPECT_OPERATORS`, echoed verbatim by the driver's FAIL line;
compound alternatives ordered before their prefixes so `NOT >=` never
mis-splits as `NOT >`); the reported `expected` field keeps the bare
value for plain `=` (the pre-operator shape) and is operator-prefixed
otherwise (`"> 5"`, `"NOT = 0"`). `format_junit_xml` additionally
stamps `classname="<suite name>"` on every `<testcase>` (suite-qualified
identity for consumers that merge reports or meet duplicate case names).

`build_json_report` keys its `.cut`-suite lookups (`cut_cases_by_index`)
by each case's 1-based position — matching the driver's own `case_id =
f"{index:03d}"` scheme — not by `MockTestCase.name`, since 2026-08-10
(audit finding F7). `TESTCASE` names are not required unique, and the old
name-keyed lookup (`dict.setdefault`, so a name's entry always pinned to
the *first* case with that name) mishandled a duplicate two different
ways depending on whether the second occurrence actually ran: if it
printed its own START/END markers, its result still made it into `cases`
(nothing in the main per-result loop drops it) but was attributed the
*first* same-named case's line numbers/tags/EXPECT-VERIFY matches instead
of its own -- silent misattribution, not a drop. Only a duplicate that
never ran at all actually vanished: the `"not_run"` synthesis loop's
`cut_case.name in seen_names` check saw the name as "seen" (added by the
first occurrence's real result) and skipped synthesizing an entry for the
second, so it appeared in neither `cases` nor the not-run count.

## Execution trace (`report/trace.py`)

Backs `mockymock run --trace` / `--trace-json` (see [cli](cli.md)). Two
independent channels compose into one report, and the split is load-bearing:

1. **Executed path** — GnuCOBOL writes a runtime trace to `COB_TRACE_FILE`
   (never stdout, so the protocol above stays clean). `parse_trace` reads it
   with `COB_TRACE_FORMAT='%P|%S|%L'`; fields stay space-padded even with an
   explicit format, and two preamble lines carry no delimiters. Its line
   numbers are **instrumented**-source lines, remapped by
   `coverage.build_original_line_map` — which drops splicer-inserted lines,
   so the path answers "which of MY lines ran".
2. **Mock timeline** — the `__MOCKYMOCK__ MOCK:` markers above. This channel
   exists *because* channel 1's remap drops inserted lines: the mock dispatch
   blocks are exactly those lines, so the trace file structurally cannot
   report which mocks fired.

A consequence worth knowing when reading a report: mocked statements never
appear in the path, so it shows gaps precisely where mocks fired. The two
lists are meant to be read together.

`format_trace_json` emits the versioned contract (`TRACE_JSON_VERSION = 1`)
the VS Code extension consumes; `format_trace_console` renders the same
payload for a plain `--trace`. `TRACE_ENTRY_CAP` (50,000) bounds a runaway
`PERFORM UNTIL`, setting `truncated: true` rather than streaming or sampling.

## Record-expectations rewrite (`report/record_rewrite.py`)

Backs `mockymock run --record-expectations` (see [cli](cli.md) and
docs/2026-08-04-record-expectations-design.md). The stage after
`analysis.stub_expectations.scan_stub_expectations` (see
[analysis](analysis.md)) and this module's own `parse_stdout`-produced
`TestSuiteResult`:

```
StubScanResult (analysis.stub_expectations)  ─┐
TestSuiteResult (this module's parse_stdout)  ─┼─► build_recording_report() ──► RecordingReport
                                               ┘         │
                                                          ▼
                                              rewrite_cut_text() ──► rewritten .cut text, or None
```

- `render_expect_value(raw_value)` — bare for a plain numeric-looking
  string (`^-?\d+(\.\d+)?$`), otherwise quoted with trailing spaces
  trimmed and embedded `"` doubled (mirrors `driver._display_text`'s
  escaping). Decides from the observed text's own shape, not by resolving
  the field's `PICTURE` — deliberate, see the design doc's "Value
  formatting" section, including the numeric-edited `PICTURE` caveat this
  does not yet resolve.
  Two PICTURE-aware exceptions (2026-09-27): a field whose PICTURE is
  alphanumeric/alphabetic/national (`is_alphanumeric_picture`: an
  `X`/`A`/`N`/`G` symbol) is always quoted, since `IF F NOT = 1.5` / `-3`
  against a full-width `PIC X` holding that text is TRUE under GnuCOBOL;
  and an all-spaces value renders as `SPACES`, never the zero-length
  `""` IBM Enterprise COBOL rejects.
- `build_recording_report(scan, suite_result)` — matches every
  `StubExpectation` the scanner found against `suite_result`'s recorded
  values by `f"{case_index:03d}"` (the same case-id convention
  `splicer.driver` uses) + data-name. A stub whose case has no matching
  recorded value is reported skipped as "case crashed before reaching the
  record point" — the only remaining explanation once `--case`/`--tag`
  exclusion is already filtered out upstream by the scanner (see
  [analysis](analysis.md)).
- `rewrite_cut_text(cut_text, report)` — replaces each recorded stub's
  comment line with a real `EXPECT` line (preserving its own leading
  indentation), returning `None` when nothing was recorded so the CLI
  never touches the file for a no-op run. No line is ever inserted or
  removed, so there's no splice-ordering hazard to manage.

This is also where the "never overwrite a hand-edited `EXPECT`" guarantee
actually holds: `rewrite_cut_text` only ever replaces a line the scanner
found by matching the `*> STUB EXPECT` pattern — once a stub becomes a
real `EXPECT` line (by this feature or by hand), it structurally cannot
match that pattern again, so a second `--record-expectations` run finds
nothing left to touch there. No provenance tracking needed.

# Gotchas

**`failures` count mismatch between console and JUnit output (formatters.py):**
`suite.failures` (from the SUMMARY line) counts failed *checks* — a case
with 2 failed EXPECT/VERIFY statements contributes 2 to that number. The
console formatter reports this raw check-count. But standard CI tooling
(Jenkins, GitHub Actions, GitLab) interprets a JUnit `<testsuite
failures="...">` attribute as a count of failed *test cases*. `format_junit_xml`
therefore does NOT reuse `suite.failures` — it recomputes
`failed_cases = sum(1 for r in suite.results if r.failure_reasons and not r.crashed)`
so that a single case with 2 failure reasons reports `failures="1"`, and a
crashed case is counted under `errors="..."` instead (see next entry). Do
not "simplify" this by reusing `suite.failures` in the XML path — that
reintroduces the mismatch.

**Crashed cases are `errors`, not `failures`, in JUnit output:** a case
with `crashed == True` contributes to `<testsuite errors="...">`, not
`failures="..."`, and gets a `<testcase><error .../></testcase>` child
instead of `<failure>`. This mirrors JUnit's own convention (failure =
assertion mismatch, error = the test didn't run to completion) and keeps a
STOP-RUN-killed case from being double-counted as an ordinary failure.

**`STOP RUN` reached from a test case's `PERFORM` target kills the whole
binary (results.py + formatters.py):** if a case's `PERFORM` target
directly or transitively reaches `STOP RUN`, the compiled test binary
exits immediately — no FAIL marker, no END marker, no SUMMARY line, and no
later test case in the suite runs at all. `parse_stdout` detects this via
`TestResult.ended` staying `False` (see Data Model above); `crashed` cases
render as `[CRASH]` / `<error>` rather than `[PASS]`. There is currently no
way to recover and continue running subsequent cases in the same suite
after a mid-suite `STOP RUN` — the fix here is honest reporting, not
recovery. See the README's "Known limitation" note.

**`suite.tests_run`/`suite.failures` are 0 whenever the SUMMARY line never
printed, even with visible case lines above them:** since a mid-suite crash
prevents `__MOCKYMOCK__ SUMMARY: ...` from ever printing, both fields stay
at their dataclass defaults regardless of how many cases actually started
or failed. This was the second half of the same crash-reporting bug as the
two entries above (only the per-case `[CRASH]`/`<error>` labels were fixed
first; the aggregate counts were still misleading on their own -- e.g. a
case that FAILS and completes, followed by a later case that crashes,
would print `[FAIL] ...` with its reason and then "0 failed" directly
beneath it). Both formatters now fall back to values reconstructed from
`suite.results` whenever the SUMMARY-derived field is falsy:
`run_count = suite.tests_run or len(suite.results)` and (console only)
`failed_count = suite.failures or sum(len(r.failure_reasons) for r in
suite.results)`. The two are mutually exclusive in practice — SUMMARY
printing means no crash occurred — so the `or` fallback never overwrites a
real clean-run count of 0 with a reconstructed one. Do not touch
`suite.tests_run`/`suite.failures` themselves to "fix" this —
`TestSuiteResult.all_passed` depends on `tests_run > 0` specifically
staying false after an unrecovered crash to produce the correct non-zero
CLI exit code; only the formatters' *displayed* numbers should fall back.

**Unknown case id in a FAIL line is an orphan, not a silent drop (fixed):**
`parse_stdout` records a FAIL line whose id never appeared in a START
marker as `(id, reason)` in `suite.orphan_failures` (`results.py`). Orphans
gate `all_passed` (any orphan means the run cannot pass) and render in both
formatters: the console prints an `ORPHANED FAILURES (unknown case id):`
block, and the JUnit output emits one `<testcase name="orphan-<id>">` per
orphan with an `<error>` child, folded into the `errors=` and `tests=`
attributes. An `END` for an unknown id is recorded in `suite.orphan_ends`
(so it's no longer silently dropped) but deliberately does **not** gate
`all_passed` or render in either formatter — an unattributable END carries
no failure evidence to lose, unlike a FAIL line.

**Duplicate CASE START id silently corrupted a result (fixed, audit
finding 5.4):** a case id colliding with one already seen used to
silently repoint `by_id[id]` in `parse_stdout` to the new `TestResult`,
permanently orphaning the earlier one from any later FAIL/END line for
that id — it stayed `crashed` forever (START seen, END never attributed)
with no failure reason and nothing anywhere explaining why. Driver-
generated ids are sequential, so this is defense-in-depth against a
hand-built `TestSuiteResult` or a future driver-codegen bug, not something
that fires against real generated output today. `parse_stdout` now records
every collision as `(id, previous_name, new_name)` in
`suite.duplicate_case_starts` *before* repointing `by_id` (the repoint
itself is unchanged — the newest START still wins subsequent FAIL/END
attribution, since the protocol has no better way to disambiguate).
`previous_name` is whatever this specific collision overwrote, not
necessarily the very first START to use this id — the same id can collide
more than once, and each occurrence past the second is its own entry in
`duplicate_case_starts` with the *previous* (not original) name.
Duplicates gate `all_passed` and render in both formatters: the console
prints a `DUPLICATE CASE IDS (a later START overwrote an earlier one):`
block, and the JUnit output emits one `<testcase name="duplicate-<id>">`
per collision with an `<error>` child explaining which case name absorbed
which lines, folded into `errors=`/`tests=` alongside orphaned failures.
`build_json_report` exposes both `duplicate_case_starts` and `orphan_ends`
as `duplicateCaseStarts`/`orphanEnds` (`json_report.py`).

**Control characters cannot crash the JUnit formatter (fixed 2026-07-07):**
suite/case names come from the .cut file and reasons from the binary's
stdout, either of which can carry control characters; `format_junit_xml`
used to hand them to ElementTree verbatim and `minidom.parseString` then
died with an `ExpatError` (verified with `\x01`). Every name/reason/message
now passes through `_xml_safe`, which replaces XML-1.0-illegal characters
(controls other than tab/LF/CR, lone surrogates) with a visible `\xNN`
escape so the document stays well-formed without hiding the evidence.
The console formatter deliberately does not sanitize.

**No `time` attributes:** neither `<testsuite>` nor `<testcase>` carries
timing — the driver protocol has no timestamps to derive it from (audit
5.3, still open).

# See Also

- [cli](cli.md)
- [dsl](dsl.md) — the `*> STUB EXPECT` comment convention `record_rewrite.py` fills in
- [analysis](analysis.md) — `stub_expectations.py`'s scan that `record_rewrite.py` consumes
- [splicer](splicer.md) — `build_driver`'s `record_targets` param and the `RECORD` marker codegen
- [coverage](coverage.md) — a separate, Docker-free parsing/formatting module
  following this one's design (gcov text in, a report model, a console formatter).
