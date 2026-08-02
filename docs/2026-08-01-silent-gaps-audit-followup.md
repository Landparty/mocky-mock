# mockymock — Silent-Gaps Audit Follow-Up — 2026-08-01

Date: 2026-08-01
Status: re-verification + targeted fixes (this document records what was
checked, what was fixed in this pass, and what remains open)

---

## Scope and method

The user asked for an audit to make sure the project has no silent gaps —
places where mockymock produces a wrong-but-plausible result, or drops
information, without any warning. Two prior audits already exist:

- [`docs/2026-07-06-real-world-readiness-audit.md`](2026-07-06-real-world-readiness-audit.md)
  — strategic/scope-level findings, already carries its own inline
  "Resolved"/"Partially resolved" annotations through 2026-07-10.
- [`docs/2026-07-07-audit-report.md`](2026-07-07-audit-report.md) — a
  detailed, line-level code audit with 48 numbered findings across 7
  sections (reachability/refusal gate, splicer, DSL, runtime/CLI, report
  layer, packaging/CI, docs drift). This is the one this follow-up
  re-verifies in full.

~100 commits landed between 2026-07-07 and today. This pass re-verified
**all 48 findings** in the 2026-07-07 audit against current `HEAD`
(`1194277`), fixed three confirmed-still-open issues directly, and found
one new suspected high-severity gap that could not be safely fixed in this
session (see below). The 2026-07-06 readiness audit was read for context
but not independently re-walked finding-by-finding here — it already
self-updates in place, and its findings are mostly higher-level restatements
of items the 2026-07-07 audit covers at the code level.

**Sandbox constraints, stated up front:** this session had no Docker daemon
and no access to the private `cobolparser` sibling repository (the pinned
git dependency mockymock's parser/splicer/analysis layers are built on;
`uv sync` cannot clone it without credentials this sandbox doesn't have).
Concretely, that means:

- Re-verification of findings in modules that import `cobolparser` at
  module level (analysis, splicer, most of runtime/CLI's integration
  surface) was done by careful code + existing-test reading, cross-checked
  against `interface-contract.md`, **not** by executing crafted `.cbl`
  fixtures the way the original 2026-07-07 audit did.
- Findings in modules with **no** `cobolparser` dependency — `mockymock/dsl/`,
  `mockymock/report/`, `mockymock/runtime/docker_toolchain.py` (mocked
  subprocess, no real Docker needed) — were verified with real, executed
  `pytest` runs. All fixes made in this pass land in that second category
  and are backed by passing tests, not just static reading.
- `tests/unit -q` currently collects 426 tests; 385 pass standalone (18
  files error at collection — they `import cobolparser` directly — and 41
  more fail at runtime via a transitive import in `mockymock/cli/checks.py`
  → `mockymock/analysis/flow_mocks.py`). This is a pre-existing sandbox
  limitation, not something introduced here; a real dev/CI environment with
  the `cobolparser` checkout and Docker available should run the full suite
  (see the project's own CI config, which does exactly that).

---

## Part 1 — Re-verification of docs/2026-07-07-audit-report.md (48 findings)

**37 of 48 were already fixed** before this session started, each backed by
a dedicated regression test whose docstring/comment names the audit finding
it pins (e.g. `# --- audit 2.1 ---`). This is a strong remediation record —
the codebase's own discipline did most of the work. Full per-finding
evidence (exact file:line, code excerpts, and matching test names) was
collected during this pass and is available on request; this table is the
condensed result.

| # | Finding | Status |
|---|---|---|
| 1.1 | GO TO edges never traversed by reachability BFS | **FIXED** — `refusal.py` `_find_flow_statements` now collects `GoStatement` alongside `PerformStatement`; unresolvable targets refuse `UNRESOLVED_FLOW_TARGET` |
| 1.2 | `PERFORM <section-name>` silently dropped | **FIXED** — section-member map added, BFS expands into every member paragraph |
| 1.3 | `SEARCH ... WHEN` bodies invisible to boundary detection | **FIXED** — `_nested_statement_lists` now opens `SearchStatement.when_clauses` |
| 1.4 | DECLARATIVES unmodeled | **FIXED** — refused outright (`UNSUPPORTED_DECLARATIVES`), the fail-closed option the original audit itself offered |
| 1.5 | ALTER not refused | **FIXED** — unconditional whole-program refusal (`UNSUPPORTED_ALTER`) |
| 1.6 | CANCEL not classified as a boundary | **FIXED** — classified and gated (`UNMOCKED_CANCEL` unless every named program has a covering CALL mock) |
| 1.7 | Docs overstate the reachability guarantee | **FIXED** — current README/`.okf/analysis.md`/`orchestrator.py` wording is hedged and specific, not a blanket claim |
| 2.1 | Top-level splices had no "owns its line" guard | **FIXED** — `UNSUPPORTED_MOCK_TARGET_LAYOUT` / `UNSPLICEABLE_EXEC` refusals now apply to top-level sites, not just nested ones |
| 2.2 | `collect_boundaries` omitted SECTION header lines | **FIXED** — SECTION headers are now protected span boundaries; SECTIONs are now exercised across many splicer tests |
| 2.3 | Illegal reset MOVEs for PICTURE-less items | **FIXED** — POINTER→`SET...TO NULL`, INDEX→skipped, COMP-1/2→`MOVE 0` |
| 2.4 | Unsubscripted MOVEs to OCCURS children | **FIXED** — OCCURS children skipped (documented fidelity limit, not a compile break) |
| 2.5 | Tally/fail-count fields `PIC 9(4)`, silent wrap at 10,000 | **FIXED** — widened to `PIC 9(9)` |
| 2.6 | SQLCA scan false-positives on literal text | **FIXED** — quote-parity + comment-aware scan; sharing a line with `EXEC SQL`/`END-EXEC` now refuses instead of corrupting |
| 2.7 | Case IDs `PIC X(3)` unguarded | **FIXED** — widened to `PIC X(9)`, `:03d` grows naturally |
| 2.8 | `suite.name` not quote-escaped | **FIXED** |
| 3.1 | Second TESTSUITE line silently discarded prior cases | **FIXED** — raises `CutParseError` |
| 3.2 | `END-MOCK.` / `end-mock` not recognized | **FIXED** — case-insensitive, optional trailing period |
| 3.3 | Unvalidated VERIFY expectation crashed codegen | **FIXED** — validated at parse time with a line number |
| 3.4 | `CutParseError` never caught in CLI | **FIXED** — caught in the shared `run_static_checks` path (run/lint/debug/mutate) and in `collect` |
| 3.5 | Duplicate MOCK keys surfaced as misleading `AMBIGUOUS_MOCK` | **FIXED** — raises at parse time, naming both line numbers |
| 3.6 | Unterminated-MOCK error had no line number; empty keys accepted | **FIXED** — both resolved |
| 3.7 | Generator emitted `MOCK CALL ""`; `suite_name` unescaped | **FIXED** |
| 4.1 | Container never recreated on image change | **FIXED** — `ensure_toolchain` compares the running container's image and recreates on mismatch |
| 4.2 | `stderr`/`exit_code` ignored by `run` | **FIXED** — timeout gets distinct framing, stderr always printed, nonzero exit after SUMMARY flips the exit code |
| 4.3 | Root, network, no resource limits | **PARTIAL** — network/pids/memory limits added (`_HARDENING_FLAGS`); root + read-write `/work` mount are a documented, deliberate tradeoff (`.okf/runtime.md` Threat model), not an oversight |
| 4.4 | Concurrent first-run race on `docker run --name` | **FIXED** — re-checks and adopts instead of failing |
| 4.5 | Foreign/stale container silently adopted | **PARTIAL** — wrong-image case now auto-recreates (side effect of 4.1); a stale bind mount on an otherwise-matching container is still only caught indirectly (compile's phantom-success guard), with no specific remediation hint |
| 4.6 | Container timeout had no SIGKILL escalation | **FIXED** — `timeout -k 5` added |
| 4.7 | No output size limit (unbounded stdout/stderr capture) | **STILL OPEN** — see Part 3 |
| 4.8 | Missing-file paths produced raw tracebacks after a slow toolchain start | **FIXED** — existence checks run before any toolchain/parse work |
| 4.9 | `--junit-xml` only written on the happy path; unguarded writes | **PARTIAL** — fixed in this session (see Part 2); the happy-path-only half remains, see Part 3 |
| 4.10 | Stdout-only diagnostics, flat exit codes, no `--timeout`/`clean` | **STILL OPEN** — not touched (ergonomics, not silence; see Part 3) |
| 4.11 | `IMAGE` computed at import time, raw `FileNotFoundError` | **PARTIAL** — Dockerfile now ships inside the package (real installs no longer hit this); the bare `.read_text()` itself is unchanged |
| 5.1 | Crash diagnosis hardcoded a STOP-RUN hypothesis | **FIXED** — real exit-code/stderr evidence used when available |
| 5.2 | `format_junit_xml` crashed on control characters | **FIXED** — `_xml_safe` escapes XML-illegal characters |
| 5.3 | No timing anywhere (JUnit/JSON reports) | **STILL OPEN** — see Part 3 |
| 5.4 | Duplicate case IDs silently corrupted a result; orphan END silently dropped | **FIXED in this session** — see Part 2 |
| 6.1 | cobol-parser unpinned in CI | **FIXED** — pinned to an exact 40-char commit SHA in both CI jobs and `pyproject.toml` |
| 6.2 | No linter/formatter/type-checker | **FIXED** — ruff + black + mypy configured and enforced in CI (pre-commit hooks still absent, minor) |
| 6.3 | No coverage threshold | **FIXED** — `--cov-fail-under=83` in `pyproject.toml` |
| 6.4 | Stale corpus sweep; regex-scrapes CLI stdout | **PARTIAL** — sweep re-run and current (34/34 clean); the regex-scraping architecture itself is unchanged and the sweep is already ~2 weeks behind the latest cobolparser pin bump — same failure mode, recurring |
| 6.5 | `py.typed` missing | **FIXED** (was already stale by the time of the original finding) |
| 6.6 | DEPTMQC/DEPTMQP lack READMEs; no CHANGELOG | **PARTIAL** — a consolidated `examples/real-world/README.md` now documents both programs (different mechanism than one-per-directory); no CHANGELOG file exists yet, though release-please automation is now wired up to generate one |
| 7.1–7.5 | `.okf/*.md` docs contradicting code (SQLCA ordering, stale fidelity-limit claim, false PERFORM/MOCK claims, stale "orphan gap open" claim, stale image name/flags) | **ALL FIXED** — every `.okf/*.md` file in scope now matches code, several with explicit "corrects audit finding N" callouts |

**Summary: 39 fixed, 6 partial, 3 still open** (after this session's fixes;
see Part 2). Zero regressions from the original 48 — nothing that was
fixed has regressed.

---

## Part 2 — Fixes made in this session

### A. Report layer: duplicate CASE ids and orphan END markers (closes 5.4)

`mockymock/report/results.py`'s `parse_stdout` indexes each `TestResult` by
its case id in a `by_id` dict. A CASE START whose id collided with one
already seen **silently repointed** `by_id[id]` to the new result — the
earlier `TestResult` stayed in `suite.results` but was permanently orphaned
from any later FAIL/END line for that id. It reported as a bare `[CRASH]`
forever, with no failure reason and nothing anywhere explaining why. This
is defense-in-depth (the driver's generated ids are sequential; this can't
fire against real generated output today) but was a real, silent, and
completely undocumented data-corruption path for a hand-built
`TestSuiteResult` or a future driver-codegen bug. Separately, an `END` for
an id that never `START`ed vanished with zero trace anywhere — documented
as an intentional *design* choice (an unattributable END carries no failure
evidence to lose), but "silently ignored" and "recorded but doesn't gate
pass/fail" are different things, and only the former was actually true.

Fixed:
- `TestSuiteResult` gained `duplicate_case_starts: list[tuple[str, str, str]]`
  (id, first name, colliding name) and `orphan_ends: list[str]`.
- A duplicate START is now recorded *before* the repoint (the repoint
  itself — newest START wins subsequent attribution — is unchanged; the
  protocol has no better way to disambiguate). Duplicates gate `all_passed`
  and render in both formatters (console: `DUPLICATE CASE IDS` block; JUnit:
  one `<testcase name="duplicate-<id>">` per collision, folded into
  `errors=`/`tests=`), mirroring how orphaned FAIL lines already render.
- An orphan END is now recorded in `suite.orphan_ends`. It deliberately
  still does **not** gate `all_passed` or render in either formatter —
  preserving the documented design intent — but it is no longer silently
  discarded with zero trace; it's readable off the `TestSuiteResult` object
  and exposed in the JSON report.
- `build_json_report` gained `duplicateCaseStarts`/`orphanEnds` keys.
- `.okf/report.md` updated to match (stdout-protocol table, data model,
  Gotchas section).

Files: `mockymock/report/results.py`, `mockymock/report/formatters.py`,
`mockymock/report/json_report.py`, `.okf/report.md`.
Tests: 8 new tests across `tests/unit/test_report.py` and
`tests/unit/test_json_report.py` (executed, all passing — this module has
no `cobolparser` dependency).

### B. DSL parser: PROVIDER opened while a BEFORE block is still open

Found during re-verification (not one of the original 48): opening a
`PROVIDER` block while a `BEFORE-EACH`/`BEFORE-ALL` block was still open
(author forgot `END-BEFORE`) parsed cleanly at the `PROVIDER` line — the
`PROVIDER` branch reset every other piece of current-block state
(`case`, `mock_target`, `mock_lines`) but never reset `in_before`. The
mistake still failed closed (nothing silently succeeded), but several lines
later and misattributed to whatever `TESTCASE` line eventually followed,
instead of naming the actual, earlier culprit. Low severity (cosmetic —
still fail-closed either way) but cheap, safe, and directly analogous to
the `TESTCASE`-inside-`BEFORE` and `BEFORE`-inside-`BEFORE` guards that
already existed right next to it.

Fixed: `mockymock/dsl/parser.py`'s `PROVIDER` branch now raises
`CutParseError(f"line {line_no}: PROVIDER inside {in_before} -- missing
END-BEFORE")`, mirroring the existing sibling guards exactly.

Test: `test_provider_while_before_each_still_open_is_a_parse_error` in
`tests/unit/test_dsl_parser_before_blocks.py` (executed, passing).

### C. CLI: report-file writes no longer crash on a bad target path

Confirms and fixes the second half of 4.9. `mockymock run`'s five optional
output files (`--junit-xml`, `--json-report`, `--coverage-json`,
`--coverage-out`, `--trace-json`) all shared the same unguarded
`Path(target).write_text(...)` pattern — a bad parent directory raised a
raw traceback *after* an otherwise fully successful compile-and-run,
discarding the real pass/fail result the user was waiting on. All five
sites now route through one new `_write_report_file(flag, target, content)`
helper that catches `OSError` and prints a clean, consistent message
instead (`mockymock run: could not write --junit-xml to <path>: <error>`),
matching the existing style of `_check_input_files`'s upfront path checks.
The run's own exit code is unaffected by a report-write failure — it still
reflects the actual test outcome, not whether a report file happened to be
writable.

This does **not** close the other half of 4.9 (no report is written at all
on the refusal / compile-failure early-return paths) — see Part 3 for why
that was left open and what it would take.

File: `mockymock/cli/main.py`. Tests: 2 new tests in
`tests/unit/test_cli_docker.py`, calling `_write_report_file` directly
(it has no `cobolparser` dependency, so — unlike most of this file's other
tests, which need real COBOL parsing and fail in this sandbox for
pre-existing reasons — these two execute and pass for real).

### Verification

```
tests/unit -q (collectible portion): 396 passed, 41 failed, 18 errors
  (baseline before this session: 385 passed, 41 failed, 18 errors --
  the 41 failures and 18 errors are 100% pre-existing/cobolparser-related,
  unchanged by this session; the +11 passing tests are all new)
ruff check .: all checks passed (repo-wide, before and after)
```

---

## Part 3 — Remaining open items

### New suspected gap (unconfirmed): `ON SIZE ERROR` may hide nested boundaries

**This is the single highest-priority item in this document.** While
re-verifying 1.1–1.7, the reachability-gate check surfaced a plausible gap
in the *same class* as the now-fixed 1.1/1.2/1.3, potentially with a
**larger** blast radius, that was **not** part of the original 48 findings
and could not be confirmed or fixed in this session because it requires
running the real `cobolparser` against a crafted fixture.

`mockymock/analysis/mock_surface.py`'s `_nested_statement_lists` /
`_NESTED_STATEMENT_ATTRS` is the single function that every boundary-site
detector, the GO TO/PERFORM reachability BFS, ALTER detection, and the
splicer's span computation all rely on to see inside nested statement
bodies (`IF`/`ELSE`, `EVALUATE WHEN`, `SEARCH WHEN`, I/O `AT END`/`INVALID
KEY` clauses, etc.). It has **no entry at all** for arithmetic statements'
`ON SIZE ERROR` / `NOT ON SIZE ERROR` clause
(`ADD`/`SUBTRACT`/`MULTIPLY`/`DIVIDE`/`COMPUTE ... ON SIZE ERROR
imperative-statement-1 [NOT ON SIZE ERROR imperative-statement-2]`) — no
attribute name in `_NESTED_STATEMENT_ATTRS`, no dedicated `isinstance`
branch, and zero references to "size error" anywhere in
`mockymock/`, `.okf/`, or `interface-contract.md`.

This is not a guess: `cobolparser` demonstrably parses this clause into
some structured form today — `.github/workflows/ci.yml`'s pin-bump comment
names cobolparser's own `parse_size_error_clauses()` function directly, and
`docs/corpus-sweep-report.md` cites cobolparser's own
`tests/unit/test_arithmetic_size_error_branches.py` regression suite. What
isn't known from mockymock's side alone is the *exact attribute name(s)*
`cobolparser` exposes for the parsed branches (candidates by analogy to
sibling statement types: something like
`ArithmeticStatement.on_size_error` / `.not_on_size_error`, each a
`list[CobolStatement] | None` — but this is an unverified guess, not a
citable fact, and guessing wrong in a code fix would either silently no-op
(if defensively `getattr`'d) or crash on every arithmetic-with-SIZE-ERROR
program (if accessed directly) — either outcome is worse than leaving this
undone until it's confirmed).

If confirmed, the blast radius is larger than 1.3 was: because the
reachability BFS reuses this same function, a `PERFORM`/`GO TO` (not just a
`CALL`/file-op/EXEC/`ACCEPT`) buried inside
`COMPUTE X = Y / Z ON SIZE ERROR PERFORM ERR-PARA END-COMPUTE` could make
an entire downstream paragraph subgraph invisible to the reachability BFS —
not just one boundary site.

**Exact next step for whoever has `cobolparser` access:** parse
`ADD 1 TO WS-X ON SIZE ERROR CALL "HIDDENPGM" END-ADD` (and the `DIVIDE`
form, which already has one confirmed-fixed parser bug in this exact
neighborhood — see `.okf/log.md`'s 2026-07-21 entry on `ROUNDED` after
`GIVING`), inspect where the AST puts the nested `CALL`, and confirm the
real attribute name(s) across `AddStatement`/`SubtractStatement`/
`MultiplyStatement`/`DivideStatement`/`ComputeStatement` (they may not be
uniform). Then add either the attribute name(s) to
`_NESTED_STATEMENT_ATTRS` (`mock_surface.py`) or a dedicated branch
matching the `SearchStatement` pattern immediately above it — no other
function needs touching, since refusal/splicer/source-map all consume this
one function. This session attempted to get read access to the
`Landparty/cobol-parser` repository specifically to confirm this and was
blocked by a tool-approval step this sandbox couldn't clear; it should be a
five-minute check for a session that has it.

### 4.7 — No output size limit on captured stdout/stderr

Still open. `_docker()`, `compile_source`, `run_binary`, and `run_gcov` in
`mockymock/runtime/docker_toolchain.py` all use
`subprocess.run(capture_output=True)`, which buffers the *entire* child
output in host memory before returning — a runaway `DISPLAY` loop inside
the 30s timeout window can still balloon host RAM with no cap. This is a
robustness/resource-exhaustion concern more than a silent-*wrongness* one
(the failure mode is loud — a crash or OOM — not a false-clean result), and
genuinely closing it means switching from `subprocess.run` to `Popen` with
a streaming, capped read loop across two pipes (stdout and stderr) without
deadlocking, while preserving the existing timeout/SIGKILL-escalation/
trace-file semantics exactly. That's real new concurrent-I/O code in the
tool's single most load-bearing execution path, and this sandbox has no
Docker daemon to run it against. Shipping it unverified risked trading a
memory-growth bug for a deadlock-every-run bug — worse, and much harder to
notice in review. Left open rather than guessed at.

### 4.9 (remaining half) — no report written on refusal/compile-failure exit

The guarded-write fix in Part 2 stops a bad output path from tracebacking,
but `--junit-xml`/`--json-report` are still only written when a run reaches
actual test execution — a refusal (`checked.problems` non-empty, `cli/main.py`
returns at line ~286) or a compile failure (`return 1` at line ~365) still
produces **no** report file at all. A CI collector configured to expect one
at a fixed path can read that as "no tests" rather than "totally broken
build" — exactly the kind of pipeline-silent-green risk both prior audits
flag as the worst class of problem for this tool. Not fixed here because
doing so requires a real design decision (how does "refused before any test
ran" map into the existing `TestSuiteResult`/JUnit/JSON schemas — as a
synthetic single "error" case? a new top-level field? something else) that
deserves a maintainer's sign-off, and because `cli/main.py`'s `run` command
cannot be executed at all in this sandbox (it needs real `cobolparser`
parsing against real `.cbl` fixtures, not just importability — confirmed by
inspecting `tests/unit/test_cli_docker.py`'s own fixtures) — meaning any
fix beyond the pure-function extraction in Part 2 would ship completely
unverified.

### 5.3 — No timing data in JUnit/JSON reports

Still open, matches `.okf/report.md`'s own "audit 5.3, still open" note.
Low severity (missing data, not wrong data). Closing it means capturing
wall-clock around `docker_toolchain.run_binary()` in `cli/main.py` and
threading a duration through to the formatters — again blocked on
`cli/main.py` being untestable in this sandbox for the reasons above.

### 4.10 — Flat exit codes, stdout-only diagnostics, no `--timeout`/`clean`

Still open, unchanged. This is ergonomics (missing CLI features), not a
silent-correctness gap — every one of these is a loud absence, not a
misleading presence — so it was deprioritized relative to genuinely silent
issues given this session's verification constraints.

### 6.4 / 6.6 — Corpus-sweep architecture, per-example READMEs, CHANGELOG

Both partial, both process/documentation-completeness items rather than
runtime-silent gaps. Noted for completeness; not attempted here.

---

## Priority summary for a follow-up session with `cobolparser` + Docker access

1. **Confirm/fix the `ON SIZE ERROR` reachability blind spot.** Same
   severity class as the now-fixed 1.1–1.3; unconfirmed only because this
   sandbox couldn't reach `cobolparser`. Five-minute check, small fix once
   confirmed.
2. **4.7 — bounded/streaming subprocess output capture.** Needs real Docker
   to verify a `Popen`-based rewrite doesn't introduce a deadlock or break
   timeout/trace semantics.
3. **4.9 — decide and implement the refusal/compile-failure report-writing
   design**, then it becomes straightforward to implement and test.
