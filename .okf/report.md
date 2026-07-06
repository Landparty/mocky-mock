---
type: Module
title: Test Result Reporting
description: TestResult/TestSuiteResult data model plus console and JUnit XML formatters for compiled COBOL test runs.
tags: [report, results, cli-output]
timestamp: 2026-07-06T00:00:00Z
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
| `__MOCKYMOCK__ CASE <id> END` | `id` | **not handled** — see Gotchas |
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
    failure_reasons: list[str]   # empty list == passed

    @property
    def passed(self) -> bool: ...   # not failure_reasons

@dataclass
class TestSuiteResult:
    suite_name: str
    results: list[TestResult]
    tests_run: int      # from SUMMARY RUN=
    failures: int        # from SUMMARY FAILURES= -- a *check* count, not a case count

    @property
    def all_passed(self) -> bool: ...  # failures == 0 and tests_run > 0
```

A `TestResult` has no explicit pass/fail flag — pass/fail is derived
entirely from whether `failure_reasons` is empty. One COBOL TESTCASE can
accumulate multiple failure reasons (e.g. multiple failed EXPECT/VERIFY
statements in the same case); all are recorded and shown, not just the
first.

`all_passed` also requires `tests_run > 0` — a suite with zero cases
executed (e.g. parse produced no SUMMARY line, or the binary crashed
before finishing) is not reported as passing.

# Formatters

| Function | Output | Notes |
|---|---|---|
| `format_console(suite)` | Plain text | `TESTSUITE: <name>` header, one `[PASS]`/`[FAIL]` line per case (indented, failure reasons indented further below), trailing `<run> run, <failures> failed` summary line (uses the raw SUMMARY counts as-is) |
| `format_junit_xml(suite)` | Pretty-printed JUnit XML via `xml.etree` + `minidom` | `<testsuite name tests failures>` with one `<testcase>` per result and one `<failure message>` child per failure reason |

# Gotchas

**`failures` count mismatch between console and JUnit output (formatters.py):**
`suite.failures` (from the SUMMARY line) counts failed *checks* — a case
with 2 failed EXPECT/VERIFY statements contributes 2 to that number. The
console formatter reports this raw check-count. But standard CI tooling
(Jenkins, GitHub Actions, GitLab) interprets a JUnit `<testsuite
failures="...">` attribute as a count of failed *test cases*. `format_junit_xml`
therefore does NOT reuse `suite.failures` — it recomputes
`failed_cases = sum(1 for r in suite.results if not r.passed)` so that a
single case with 2 failure reasons reports `failures="1"`, matching what
CI dashboards expect. Do not "simplify" this by reusing `suite.failures` in
the XML path — that reintroduces the mismatch.

**CASE END marker is intentionally a no-op (results.py):** `_CASE_END_RE`
is defined but never dispatched in `parse_stdout`. It exists only to
bracket cases on the COBOL/codegen side; the Python parser matches FAIL
lines to cases purely by `id`, so END carries no information the parser
needs. If you add logic that depends on knowing when a case's output
block ends, you'll need to wire this branch in — it is not currently a bug,
just dead-looking code left for symmetry with the emitter.

**Unknown case id in a FAIL line is silently dropped:** `by_id.get(m.group("id"))`
returns `None` for an id never seen in a START line, and the `if target is
not None` guard just skips it — no error is raised. A malformed or
truncated stdout stream (e.g. binary crash mid-case) can silently lose
failure reasons rather than surfacing a parse error.

# See Also

- [cli](cli.md)
- [dsl](dsl.md)
