---
type: Module
title: Test Result Reporting
description: TestResult/TestSuiteResult data model plus console and JUnit XML formatters for compiled COBOL test runs.
tags: [report, results, cli-output]
timestamp: 2026-07-07T00:00:00Z
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

`parse_stdout` matches five line shapes via regex, one case per marker kind:

| Marker | Regex group(s) | Effect |
|---|---|---|
| `__MOCKYMOCK__ TESTSUITE: <name>` | `name` | sets `suite.suite_name` |
| `__MOCKYMOCK__ CASE <id> START: <name>` | `id`, `name` | creates a `TestResult`, appended to `suite.results` and indexed in `by_id` |
| `__MOCKYMOCK__ CASE <id> FAIL: <reason>` | `id`, `reason` | appends `reason` to the matching `TestResult.failure_reasons` (looked up by id); an unknown id is recorded in `suite.orphan_failures` as `(id, reason)` rather than dropped |
| `__MOCKYMOCK__ CASE <id> END` | `id` | sets the matching `TestResult.ended = True` |
| `__MOCKYMOCK__ SUMMARY: RUN=<n> FAILURES=<n>` | `run`, `failures` | sets `suite.tests_run` / `suite.failures` |

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

    @property
    def all_passed(self) -> bool: ...
    # failures == 0 and tests_run > 0 and not orphan_failures
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
driver's failure-reason strings against the model, splitting on the LAST
`", got "`), and a synthesized `"not_run"` entry for every selected case the
binary never printed a START marker for. `format_junit_xml` additionally
stamps `classname="<suite name>"` on every `<testcase>` (suite-qualified
identity for consumers that merge reports or meet duplicate case names).

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
attributes. An `END` for an unknown id is still silently ignored — that
asymmetry is deliberate (an unattributable END carries no failure
evidence to lose).

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
- [dsl](dsl.md)
- [coverage](coverage.md) — a separate, Docker-free parsing/formatting module
  following this one's design (gcov text in, a report model, a console formatter).
