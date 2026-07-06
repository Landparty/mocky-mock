---
type: Module
title: Test Result Reporting
description: TestResult/TestSuiteResult data model plus console and JUnit XML formatters for compiled COBOL test runs.
tags: [report, results, cli-output]
timestamp: 2026-07-06T01:00:00Z
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
| `__MOCKYMOCK__ CASE <id> FAIL: <reason>` | `id`, `reason` | appends `reason` to the matching `TestResult.failure_reasons` (looked up by id; silently ignored if id unknown) |
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

    @property
    def all_passed(self) -> bool: ...  # failures == 0 and tests_run > 0
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

`all_passed` also requires `tests_run > 0` — a suite with zero cases
executed (e.g. parse produced no SUMMARY line, or the binary crashed
before finishing) is not reported as passing. This means a crash-mid-suite
scenario already produces a non-zero CLI exit code even without the
per-case `crashed` tracking above; `crashed` fixes the *human-facing*
report (console/JUnit), which otherwise showed the crashed case as `[PASS]`
purely from absence of a FAIL marker.

# Formatters

| Function | Output | Notes |
|---|---|---|
| `format_console(suite)` | Plain text | `TESTSUITE: <name>` header, one `[PASS]`/`[FAIL]`/`[CRASH]` line per case (indented, failure reasons indented further below), trailing `<run> run, <failures> failed[, <n> crashed]` summary line (`<failures>` is the raw SUMMARY check-count as-is; `<run>` falls back to `len(suite.results)` when `suite.tests_run` is 0 -- see Gotchas; the `, <n> crashed` segment only appears when `<n> > 0`) |
| `format_junit_xml(suite)` | Pretty-printed JUnit XML via `xml.etree` + `minidom` | `<testsuite name tests failures errors>` with one `<testcase>` per result; failing cases get a `<failure message>` child per failure reason, crashed cases get a single `<error message>` child instead (JUnit's own failure-vs-error distinction); `tests` uses the same `len(suite.results)` fallback as the console `<run>` count |

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

**Unknown case id in a FAIL line is silently dropped:** `by_id.get(m.group("id"))`
returns `None` for an id never seen in a START line, and the `if target is
not None` guard just skips it — no error is raised. A malformed or
truncated stdout stream (e.g. binary crash mid-case) can silently lose
failure reasons rather than surfacing a parse error. (The crash itself is
now caught via `crashed`/`ended` above, but reasons recorded *before* an
unexpected crash could in principle still be lost the same way if the id
were ever wrong -- this is a distinct, still-open gap.)

# See Also

- [cli](cli.md)
- [dsl](dsl.md)
