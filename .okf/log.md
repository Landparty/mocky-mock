# mocky-mock OKF Bundle — Update Log

## 2026-08-14 — Cache Nuitka onefile extraction across launches

User reported the VS Code extension's Program Tree and Boundaries views
taking a long time to show up. Investigation (spanning both repos) found
two compounding causes: the extension fires several CLI invocations per
editor switch (`fixtures` for Boundaries, `analyze program-flow --compact`
for the Paragraph Tree, and both `--compact` + `--format mermaid` for the
Program Flow view), and every one of those invocations paid Nuitka's
onefile extraction cost from scratch — the bundled binary is built with
`--onefile` and no `--onefile-tempdir-spec`, so the whole payload
(mockymock + compiled cobolparser + data files) gets unpacked to a fresh
temp dir and deleted again on every single launch.

Fixed the extraction side here: `scripts/build_executable.sh` now passes
`--onefile-tempdir-spec="{CACHE_DIR}/mockymock/{VERSION}"` and
`--product-version` (read from `mockymock.__version__`), so repeated
launches of the same build reuse the already-extracted payload instead of
re-unpacking it every time. Documented the version-string caveat (CI's
cobolparser force-reinstall doesn't bump mockymock's own version) in
publishing.md's Gotchas — safe because Nuitka's bootstrap detects a
payload mismatch and re-extracts, just worth knowing when debugging.

Not done here (filed as follow-up, not requested for this pass): a
lighter `fixtures`-equivalent that skips scenario-data generation for the
Boundaries tree (which currently parses the program twice — once for the
refusal gate, once inside `generate_with_scenarios_from_file`), and a
longer-lived `mockymock serve` daemon to eliminate process-startup cost
entirely. The VS Code side of this same investigation (deduping the
Paragraph Tree and Program Flow views' redundant `analyze program-flow`
calls) landed in the sibling mocky-mock-vscode repo, same branch.

No test run here beyond `bash -n scripts/build_executable.sh` (syntax
check) — verifying the Nuitka build itself requires the actual toolchain
and is exercised by mocky-mock-vscode's `build-and-release.yml` CI, not a
mocky-mock-local test.

## 2026-08-13 — Reworded the four GO TO/fall-through `UNSUPPORTED_TERMINATOR_LAYOUT` messages

A user hit the `chain_fallthrough_names` refusal on `examples/real-world/
INTCALC/INTCALC.cbl` (its `GO TO 2200-EXIT` early-exit idiom falls through
past `2200-EXIT` into `3000-FINALIZE`) and, from the message alone, read it
as a mockymock limitation rather than a property of the COBOL. The old
wording was mechanism-first ("early-exit propagation chain", "EXIT
PARAGRAPH only works correctly when...") — accurate, but it explains
mockymock's own transform internals before ever saying what's true about
the user's source.

Reworded all four `problem` strings in `find_terminator_plans`
(`analysis/refusal.py`, the `go_to_targets`/`go_to_fallthrough`/
`chain_go_to_names`/`chain_fallthrough_names` branches, ~lines 2236-2292):
now leads with "is unsafe to test automatically" + which paragraph is a GO
TO target (or is reached by falling through past one), and ends with a
concrete remediation hint — replace the named `GO TO <target>` with `EXIT
PARAGRAPH` when it exists purely as an early exit. `RefusalReason`'s shape
(`code`, `message`) is unchanged — this is a content-only edit, so nothing
downstream (JSON report, JUnit, VS Code diagnostics) needed touching.
Verified no test asserts on the old exact substrings (only `.code` is
checked); full `tests/unit/test_terminators.py` (32) still green. Did not
extend this framing to other `UNSUPPORTED_*` refusal families in this
pass — flagged as a natural follow-up, not done here.

## 2026-08-13 — Test-coverage follow-up: `run` reports on failure, `--timeout`, one new fixture-bundle gap

Requested test-coverage analysis, then asked to implement a scoped subset
of its own recommendations (CI coverage measurement turned out to already
be wired up via `pyproject.toml`'s `[tool.pytest.ini_options]` addopts
--cov-fail-under=83`, contradicting the analysis's own claim — corrected,
no change needed there). Environment had neither Docker nor a usable
`cobolparser` install (`add_repo` for the `Landparty/cobol-parser` sibling
returned an approval error this session couldn't grant itself — same
constraint the 2026-08-01/2026-08-12 audits hit); CLI-level changes were
verified by direct unit-level exercise of the touched functions plus
manual code tracing, not a live `pytest tests/` run — the ~26 test files
that import cobolparser at module level fail to collect here, same as
those audits.

- **`_write_failure_reports`** (new helper, `cli/main.py`): `mockymock
  run`'s `--junit-xml`/`--json-report` now get written on a static refusal
  or a compile failure too, not just a run that reached execution — a
  carried-over open item from the 2026-08-10 audit ("No report written on
  refusal/compile-failure exit"). Builds one synthetic `TestResult`
  standing in for the whole run and reuses the existing
  `format_junit_xml`/`build_json_report` formatters rather than a bespoke
  shape. Tests in `tests/unit/test_cli_docker.py`.
- **`run --timeout S`** (default 30, mirrors `mutate`'s own flag): threads
  into `docker_toolchain.run_binary(timeout_seconds=...)` — previously
  only `mutate` could shorten/lengthen the bound a hung mocked CALL is
  killed by. Test in `tests/unit/test_cli_docker.py`.
- **`dsl/fixture_bundle.py`: `load_fixture_bundle` rejected a non-dict
  argument with a raw `AttributeError`, not `MalformedBundleError`** — a
  genuinely new gap, found while building a malformed-input regression
  sweep (`tests/unit/test_malformed_input_sweep.py`), in the same class as
  the 2026-08-12 audit's Finding 15 but missed by it: `data.get(...)` ran
  one line before that fix's try/except block, so was invisible to it.
  `parse_fixture_bundle` (the JSON-text entry point) already guarded
  non-dict JSON, but `load_fixture_bundle` is itself public and called
  directly by `cli/main.py`'s `--with-data` path — a future caller (or a
  misbehaving cobolparser version) handing it a non-dict would still have
  hit the raw traceback. Fixed with an `isinstance` check at the top of
  the function, matching `parse_fixture_bundle`'s own message wording.
  Regression test in `test_fixture_bundle.py`.
- **`tests/unit/test_report.py`**: two new regression tests pin Finding
  11 (deferred, 2026-08-12 audit — the stdout protocol has no escaping, so
  a raw newline in a RECORD/FAIL marker's value truncates it at the
  newline) as documented, unchanging behavior, so a future protocol-level
  escaping fix has a red test to turn green.
- **`tests/unit/test_malformed_input_sweep.py`** (new file): a standing,
  parametrized "garbage input must never surface an untyped exception"
  net for `dsl.parser.parse_cut` (always `CutParseError`) and
  `report.results.parse_stdout` (never raises at all) — both already had
  extensive per-shape coverage elsewhere; this file's value is a single
  discoverable place checking the CONTRACT itself against a wide
  adversarial battery (binary/control bytes, BOM prefixes, pathological
  repetition, oversized fields) rather than only named shapes.

Deliberately NOT done this pass (scoped out with the requester up front):
bounding `docker_toolchain.run_binary`'s in-memory stdout/stderr capture
(the remaining "resource/robustness" item — reworking it to a streaming
Popen-based read with a size cap needs live-Docker verification this
session didn't have, and the existing `test_run_binary_*` tests mock
`subprocess.run` in a way a streaming rewrite would have to invasively
change); the large-program-scale test; splitting `cli/main.py`/
`refusal.py`; and extending Docker/GnuCOBOL verification to
non-Linux CI runners.

## 2026-08-12 — Reachability BFS closed over GO TO fall-through (HIGH)

Cross-repo bug review (cobol-parser + mocky-mock, same session). Found and
fixed the one gap where the per-case mock gate under-approximated
execution: `_reachable_paragraphs` stopped at a `GO TO` target, but the
target's own body falls through — ordinary sequential execution, not a
flow edge — into the next paragraph in source order whenever
`_falls_through` can't prove it diverts. A `CALL`/file-op/`ACCEPT` in that
fallen-into paragraph passed `lint`/`run` unmocked ("no problems found",
exit 0), survived splicing verbatim, and executed for real. Three sibling
models already agreed the paragraph executes (`union_executed_paragraphs`'
closure, `_go_to_fallthrough_targets`' terminator guard, cobolparser's own
`ProgramFlowAnalyzer` FALL_THROUGH edge) — only the safety-critical one
didn't. The BFS now runs the same `_falls_through` fixpoint closure over
every reached GO TO target, failing closed (`UNRESOLVED_FLOW_TARGET`) when
source order is unverifiable or a target can't be anchored in it.
[analysis.md](analysis.md)'s Gotcha claiming "no under-approximation
results" was the documented misunderstanding that hid this; rewritten.
Pinned by `tests/unit/test_refusal_goto_fallthrough.py` (6 tests: single
hop, multi-paragraph chain, GOBACK stops the walk, gate refuses
UNMOCKED_CALL, mocking the fallen CALL satisfies it, past-terminator
paragraphs still need no mock). Full suite 1211 passed / 97 skipped /
1 xfailed.

## 2026-08-12 — Audit remediation: 19 of the 20 findings fixed, TDD, at the pin

Same-day follow-up to the audit below, in a session that DID have
cobolparser (cloned and checked out at the exact `pyproject.toml` pin
`83478ba7`, installed `--no-deps -e`; still no Docker, so the integration
tier self-skipped — the end-to-end GnuCOBOL re-verification of Finding 2
remains for a Docker session). Every fix landed test-first (each new test
confirmed failing before its fix), full gates green after: 1204 passed /
97 skipped / 1 xfailed (`pytest tests/`), `ruff` + `black` + `mypy` clean.
42 new regression tests. Highlights, in audit-finding order:

- **F1** `report/results.py`: `all_passed` now cross-checks
  `all(result.passed ...)` against the per-case FAIL/END lines instead of
  trusting the driver's `SUMMARY FAILURES=` counter alone — exit code can
  no longer say 0 while the rendered report says `[FAIL]`/`[CRASH]`.
- **F2** `analysis/refusal.py`: a driver-side `PERFORM <start> THRU
  <thru>` where either endpoint names a SECTION now refuses
  `UNSUPPORTED_PERFORM_THRU` (section-specific message) instead of
  silently dropping the THRU range from the reachable set; section
  targets without THRU unchanged.
- **F3** `analysis/mock_surface.py`: the audit's two suspected missing
  nested-clause attrs both confirmed real against cobolparser's own
  `_CLAUSE_BODY_ATTRS` at the pin and added: `not_at_eop_clause`,
  `not_on_overflow`. Same bug class as 2026-08-10's `on_size_error` fix.
- **F4** `dsl/parser.py`: `_reject_unbalanced_subscript` refuses
  `WS-TAB(1` (no-space unbalanced paren, previously swallowed whole by
  `_SUBSCRIPTED_NAME`'s `\S+` fallback) at MOVE/EXPECT/CAPTURE sites.
- **F5** `cli/skills_cmd.py`: a dangling-symlink target now counts as
  occupied (refuse without `--force`, replace with it) instead of
  crashing copytree.
- **F6–F9** `debug/`: framing errors now cover truncated/non-UTF-8
  bodies and non-ASCII headers; `_dispatch`/`_send_response` survive
  requests missing `command`/`seq`; `call_stack` skips a frame whose gdb
  location has no `line`; relaunch clears `_current_stop` so a pre-stop
  `stackTrace` reports no frames instead of the previous session's.
- **F10/F12** `report/record_rewrite.py` + `json_report.py`: recorded
  values are matched per (case, data-name) in emission order (two stubs
  for one field each get their own value; dict-collapse corrupted the
  earlier golden); orphan RECORD markers now surface as
  `orphanRecords` in the JSON report and get their own skip reason
  instead of the misleading "crashed" one. **F11** (newline-in-value
  marker truncation) deliberately deferred — needs protocol-level
  escaping in the generated driver; documented in `parse_stdout`.
- **F13–F16** `cli/`: `generate -o` and `mutate --json-report` route
  through `_write_report_file` (generate's file is the deliverable →
  exit 1; mutate's is auxiliary → exit code stands on the outcome);
  bare `mockymock skills` prints its own usage; `fixture_bundle.py`
  raises typed `MalformedBundleError`; `mutate --list` refuses
  `--json-report`/`--fail-under` instead of ignoring them.
- **F17–F19** `runtime/` + `web/`: the "already in use" race-recovery
  branch now compares the adopted container's image to `IMAGE` and
  rm+recreates once on mismatch; `_inspect_container`/`cobc_version`
  take a `timeout` param so `status.py`'s probes are genuinely bounded
  by `PROBE_TIMEOUT`; `/api/status` coalesces concurrent polls behind a
  lock + 2s TTL cache.
- **F20** `dsl/generator.py`: a MOCK key containing `"` (representable
  in COBOL via a single-quoted literal, unrepresentable in the .cut
  grammar) is skipped fail-closed like an unparsed key — run's refusal
  gate names the unmocked site — rather than scaffolding a `.cut` that
  `parse_cut` itself rejects; `_quote_safe` substitution stays
  names-only since substituting inside a KEY would silently unmatch it.

Concept docs refreshed: [analysis](analysis.md) (attrs tuple + the two
2026-08-12 fixes), [report](report.md) (`all_passed` semantics). The
audit doc itself now carries per-finding status lines.

## 2026-08-12 — Sixth framework audit: 20 new findings, none fixed yet

[docs/2026-08-12-framework-audit.md](../docs/2026-08-12-framework-audit.md) —
a static read-through (no Docker, no `cobolparser` reachable in this
environment — the private-repo clone hit the same auth wall the 2026-08-10
CI-outage finding described) split across six areas run in parallel: core
engine (`analysis/`, `splicer/`), DSL (`dsl/`), CLI (`cli/`), runtime/web
(`runtime/`, `web/`), report (`report/`), and debugger/mutation (`debug/`,
`mutation/`). Two HIGH findings worth flagging here specifically since they
bear on trust in the tool's own signal: (1) `TestSuiteResult.all_passed`
(the CLI's exit-code source, `report/results.py`) is derived only from the
driver's own `SUMMARY: FAILURES=` count, never cross-checked against parsed
`CASE ... FAIL:` markers, so a COBOL program's own `DISPLAY` output
colliding with the `__MOCKYMOCK__` line-start protocol can produce exit 0
while console/JUnit/JSON simultaneously render that case as `[FAIL]`; (2) a
`.cut` test case's own `PERFORM <section> THRU <target>` (section, not
paragraph, as the seed) silently drops the THRU range in
`analysis/refusal.py`'s reachability BFS — same silent-under-approximation
bug class as the 2026-08-10 audit's Finding 1, in a different corner of the
same function. Eighteen more findings (DSL parser accepting an unbalanced
subscript when there's no space before the stray `(`; `skills install`
crashing on a dangling symlink target; several DAP-adapter/gdb crash paths
on malformed input; a `record_rewrite.py` dedup-by-dict silently corrupting
a golden value when the same field is stub-recorded twice per case; and
more) are detailed in the doc. Nothing in this entry has been fixed yet —
this session was audit-only; see the doc's "Prioritized recommendations"
for suggested fix order.

## 2026-08-11 — `AMBIGUOUS_MOCK` (and nested/layout checks) widened to a whole-program site set

The refusal gate's `AMBIGUOUS_MOCK` check in `check_test_case` only examined
sites reachable from the owning test case's own PERFORM target
(`surface.sites_in(reachable - mocked_flow_names)`), but
`splicer.orchestrator.splice_program` does not filter by reachability at
all: it walks every `surface.boundary_sites` entry and splices any one that
`directive_matches_site` matches for any directive of any case (category/key
or normalized-text only), not narrowed by `mocked_flow_names` either. So a
multi-file `OPEN INPUT A OUTPUT B` in a paragraph no test case's PERFORM
ever reaches, incidentally matched by one case's `MOCK OPEN A` + `MOCK OPEN
B` (each individually satisfying that same case's own reachable single-file
sites elsewhere, so nothing looked ambiguous within its reachable set),
passed `mockymock lint` clean and then died in `export`/`run` with an
unhandled `ValueError` from `injector.build_site_dispatch` ("matched by
multiple directives ... refusal gate should have caught this
(AMBIGUOUS_MOCK)"). One test case reproduces it; no `PROVIDER`/multi-case
machinery needed.

`check_test_case` now runs a second pass, after the reachable-set loop, over
`surface.boundary_sites` unfiltered (skipping sites the first pass already
visited, to avoid double-refusing), for the same reachability-narrowing bug
this checks for on **three** conditions, not just `AMBIGUOUS_MOCK`:
`orchestrator.splice_program`'s own defensive invariant checks re-derive
`UNSUPPORTED_NESTED_MOCK_TARGET`/`UNSUPPORTED_MOCK_TARGET_LAYOUT` the exact
same way, against the exact same unfiltered site set, and would raise their
own (differently-worded) unhandled `ValueError`s if a case's directive
happened to match an unspliceable site elsewhere in the program that no
case's own reachability BFS ever visits. Confirmed concretely for
`UNSUPPORTED_NESTED_MOCK_TARGET`: `tests/unit/test_refusal.py`'s
`test_per_case_check_allows_static_call_only_paragraph` had been asserting
zero refusals for exactly this shape (a clean top-level `CALL "DISCRATE"`
whose key coincidentally also matches an unspliceable nested `CALL
"DISCRATE"` inside a different, unreachable paragraph's `ON SIZE ERROR`
clause) — retargeted to an isolated single-paragraph fixture with no key
collision, and the original shape became a new positive test,
`test_per_case_check_refuses_nested_mock_target_matched_program_wide`,
proving the fix. Same general invariant as `NESTED_EXEC`'s own whole-program
check: for any refusal-gate check whose violation the splicer treats as
"should have been refused already," the gate's site set must be a true
superset of the splicer's site set — reachability was never the operative
filter for what the splicer processes. Regression coverage is CLI-level
(`tests/unit/test_cli.py`, `main(["lint", ...])` and `main(["export",
...])`) because that is the layer the original bug escaped through. Full
unit (1219 passed) and Docker-gated integration suites re-run clean (one
pre-existing, unrelated `test_read_rows_terminal_example` failure confirmed
via `git stash` to predate this change). Updated `.okf/analysis.md`.

## 2026-08-11 — `CAPTURE_ARG_OUT_OF_RANGE` widened to a whole-program site set

Final whole-branch review of the argument-capture feature caught a gate/
splicer disagreement no single task's scope could see. The refusal check in
`check_test_case` filtered candidate sites by the owning test case's own
reachability (`surface.sites_in(reachable - mocked_flow_names)`), but
`splicer.orchestrator.splice_program` does not filter by reachability at
all: it walks every `surface.boundary_sites` entry and splices any one that
`directive_matches_site` matches for any directive of any case (category+key
only). So a program with `CALL "X" USING A B` in one paragraph and
`CALL "X" USING A` in another, mocked by two independent cases where only
the first uses `CAPTURE ARG 2`, passed `mockymock lint` clean and then died
in `export`/`run` with an unhandled `ValueError` from
`injector.build_site_dispatch`. The check now runs against
`surface.boundary_sites` unfiltered -- a superset of what the splicer
processes -- for the same reason `NESTED_EXEC` is whole-program rather than
per-case. Regression coverage is CLI-level
(`tests/unit/test_cli.py`, `main(["lint", ...])` and `main(["export", ...])`)
because that is the layer the bug escaped through; the unit tests in
`tests/unit/test_refusal_capture.py` were retargeted (one of them had
encoded the buggy assumption). Also closed the stale "still open" entries
for this feature in `docs/2026-08-10-framework-audit-and-roadmap.md`, whose
originally-proposed `VERIFY ... WAS CALLED WITH ...` syntax the design doc
had explicitly rejected. Updated `.okf/analysis.md` and `.okf/dsl.md`.

## 2026-08-11 — Argument-capture assertions on mocked CALLs

`CAPTURE ARG <n> INTO <target>` inside a `MOCK CALL`/`MOCK MQ`/bare-DYNCALL
body: positionally resolves the real call site's Nth `USING` parameter
(via `BoundarySite.statement`, already carrying the AST node -- no new
analysis field needed) into an ordinary WORKING-STORAGE field, asserted
with the existing `EXPECT` (no new assertion syntax or report protocol).
New fail-closed `CAPTURE_ARG_OUT_OF_RANGE` refusal when an index exceeds
some matching site's real argument count (program-wide -- see the
2026-08-11 follow-up entry above). Closes the "argument
capture/spies on mocked CALLs" gap named in the 2026-07-06 readiness
audit's Finding 6. Proven end-to-end via `examples/ordrproc/`'s existing
Docker-gated integration test. See
docs/2026-08-11-argument-capture-design.md and
docs/superpowers/plans/2026-08-11-argument-capture.md.

## 2026-08-11 — Add `mockymock skills install` and two Claude Code skills

Two Claude Code skills: `.claude/skills/mockymock-dev/` (repo-local,
routes contributors into this OKF bundle) and a packaged end-user skill
teaching an AI assistant to scaffold/edit/run `.cut` files, installed via
the new `mockymock skills install [--project] [--force]` subcommand
(`mockymock/cli/skills_cmd.py`). Skill content lives under
`mockymock/cli/skills/mockymock/` rather than a new top-level
`mockymock/skills/` package -- setuptools `package-data` only applies
under an already-discovered package (one with `__init__.py`), so it rides
along with `mockymock.cli` the same way the Dockerfile and dashboard
static assets ride along with `mockymock.runtime`/`mockymock.web`. See
`docs/superpowers/specs/2026-08-11-mockymock-ai-skills-design.md`.

## 2026-08-10 — Framework audit findings 1 & 2: ON SIZE ERROR blind spot, phantom-paragraph guard

`docs/2026-08-10-framework-audit-and-roadmap.md` (executed audit: live
Docker + `cobolparser` pinned to `83478ba7` in an isolated venv, not a
static read) confirmed the one gap the prior 2026-08-01 follow-up had to
leave unconfirmed for lack of exactly that access, plus one new upstream
bug. Both fixed same day, each via a regression test that failed for the
right reason before the fix (confirmed via `git stash`), then the fix,
then the full unit (`1058 passed`) and integration (`124 passed`) suites
for regressions, matching this project's usual discipline.

* **`mock_surface.py`** (`_NESTED_STATEMENT_ATTRS`) — added
  `on_size_error`/`not_on_size_error`. Before this, a `CALL`/file-op/EXEC/
  `ACCEPT`/`PERFORM` nested inside an arithmetic statement's `ON SIZE
  ERROR` clause was invisible to both boundary detection and the
  reachability BFS: an unmocked boundary there produced a silent `PASS`
  end to end against real GnuCOBOL, not a refusal — confirmed via a
  controlled contrast against the identical construct nested in `IF`
  (which correctly refused `UNMOCKED_CALL`). See [analysis](analysis.md).
* **`refusal.py`** (`_check_unsupported_control_flow`) — new
  `UNSUPPORTED_PHANTOM_PARAGRAPH` whole-program refusal. A separate,
  upstream `cobol-parser` bug: `END-ADD`/`END-SUBTRACT`/`END-MULTIPLY`/
  `END-DIVIDE`/`END-COMPUTE` written alone on their own line parse as
  paragraph *names* instead of being consumed as their statement's scope
  terminator, silently reparenting every following statement (same class
  as the fixed `ROUNDED`-after-`GIVING` phantom paragraph). Converts an
  unexplained `[CRASH]` into a loud, actionable refusal. Deliberately
  matches the five exact reserved names, not a `^END-[A-Z]+$` pattern —
  that broader form would also refuse legitimate paragraphs like
  `END-OF-JOB`/`END-RUN` (a false-positive regression test guards this).
  Root cause is still open upstream in cobol-parser.

Not addressed in this pass: Finding 3 (CI red on `main` since 2026-08-09,
`COBOL_PARSER_PAT` no longer resolving) needs GitHub secrets access this
session doesn't have.

## 2026-08-10 — PR #57 review fixes: gdb session teardown, DAP framing validation, ledger corrections

Automated review on the audit-remediation PR (below) found two real gaps
in the F4/F17 fixes themselves, plus three OKF inaccuracies in that same
PR's own doc updates.

* **`gdb_session.py`/`adapter.py`** (`2db89b0`) — F4's read deadline
  raised `GdbSessionClosedError` but left the `GdbSession` looking
  alive: a before-response handler (evaluate/variables/stackTrace)
  just failed its one request and left the dead session in place, so
  the *next* request tried it again -- spawning a second per-call
  reader thread racing the first, still-blocked one for whatever the
  pipe produced next, able to silently hand one command's response to
  a different command's caller. Run-control handlers (continue/next/
  step) stopped the adapter's own loop but never actually closed the
  gdb subprocess, leaking it into the shared container. Fixed with a
  `_closed` flag on `GdbSession` (set the moment EOF or the deadline
  fires; every later read short-circuits instead of starting a new
  reader) and by having `DapAdapter._dispatch` call `_shutdown()`
  whenever the caught exception is specifically `GdbSessionClosedError`
  (not `GdbCommandError` or a malformed-request exception -- neither
  means the session itself died).
* **`adapter.py`** (`2db89b0`) — F17's `Content-Length` validation only
  caught a non-numeric header. A missing or explicit-zero header
  defaulted to length 0 and reached `json.loads(b"")` -- a
  `JSONDecodeError`, not a `DapFramingError`, so it escaped `run()`'s
  clean-shutdown handling and would have crashed the adapter process. A
  negative length reached `stream.read(n)` with `n < 0`, which reads to
  EOF instead of raising -- on a live stdin pipe, blocks forever. Now
  requires the header to parse as a positive integer.
* **Ledger corrections** —
  [log.md](log.md) itself listed F20 in a "not fixed" range even though
  it was closed in the same PR; [cli.md](cli.md) described
  `_cmd_generate`'s copybook-expansion guard as printing
  `run_static_checks`'s message (`copybook expansion failed: ...`)
  instead of its own (`mockymock generate: {exc}`); [report.md](report.md)
  said the pre-F7 JSON report *dropped* a duplicate-named TESTCASE that
  emitted a START marker, when it actually misattributed that case's
  metadata/failures to the first same-named model case instead --
  dropping only happened to an unrun duplicate via the name-based
  `not_run` synthesis.

## 2026-08-10 — Audit remediation: 20 findings fixed across runtime, debug, mutation, DSL, report

Worked through a code-quality/reliability audit (41 findings: 1 P0
infra, 1 P0 coverage gap, 11 High, 8 Medium, 9 Low, 8 Cleanup, plus 8
verified strengths). Every fix followed the same discipline: a
regression test proving the bug, confirmed failing via `git stash` of
the source-only change, then the fix, then the full unit suite
(`python -m pytest tests/unit -q --no-cov`) for regressions, then a
commit. Verified against an isolated `uv venv` pinned to the exact
cobol-parser commit CI/production actually resolve (`83478ba7`), not
the locally-drifted sibling checkout — see [testing](testing.md)'s
Gotchas.

**P0 / test-coverage gap:**
* **F-0b** (`551c9c7`) — 8 of `test_scoped_refusals.py`'s tests
  depended on `INVOKE` producing a `PARSE_WARNING`; cobolparser's
  pinned commit now parses it into its own AST node instead. Fixture
  swapped to `TRANSFORM "x".` — see [analysis](analysis.md)'s
  `PARSE_WARNING` row and [testing](testing.md)'s Gotchas for two real
  cobolparser bugs hit picking the replacement (flagged upstream, not
  fixed here).
* **F11** (`ba37243`) — `UNMOCKED_CICS`/`UNMOCKED_DLI`/`DYNAMIC_CALL`
  had zero test coverage despite being core fail-closed refusal codes.

**High (11/11 closed):**
* **F1** (`2261a30`) — `compile_source`/`run_gcov` had no in-container
  kill wrapper; a hang inside the shared container outlived even the
  host-side `subprocess.run` timeout. Wrapped in `timeout -k 5 585` /
  `timeout -k 5 50`, matching `run_binary`'s existing pattern.
* **F2** (`b156b62`) — `_HARDENING_FLAGS` lived only on `docker run`,
  never fed `IMAGE`; editing them left an already-running container's
  hardening silently stale. `_image_tag()` now hashes the flags
  alongside the Dockerfile content.
* **F3** (`d46da86`) — README's "fully containerized and sandboxed"
  had no caveat about the shared, unpartitioned `WORK_ROOT` mount.
  Softened the claim and pointed at [runtime](runtime.md)'s Threat
  model.
* **F4** (`99e27e0`) — `GdbSession.send`/`_read_until_stopped` blocked
  forever on a hung debuggee, wedging the whole DAP adapter. Bounded
  to 30s via a one-shot daemon thread per read (Windows pipes support
  no portable timeout mechanism otherwise).
* **F5** (`601eb5d`) — non-UTF-8 debuggee output crashed the whole
  debug session (`UnicodeDecodeError`); `start_gdb_session`'s `Popen`
  now sets `errors="replace"`.
* **F6** (`3ab4e4b`) — `expand_copybooks()` was unguarded on 6 of 7
  call sites; a circular/oversized/mis-encoded copybook chain
  tracebacked instead of refusing.
* **F7** (`c8e1891`) — `build_json_report` keyed TESTCASE lookups by
  name; duplicate names silently dropped the second case. Keyed by
  1-based index instead, matching the driver's own `case_id` scheme.
* **F8** (`bcd23ab`) — mutation operator regexes used plain `\b`,
  matching `READ` inside `WS-READ-COUNT`. Added a COBOL-word boundary
  helper treating `-` as part of the identifier.
* **F9** (`dca29a9`) — concurrent stale-container removal raced: the
  loser's `docker rm -f` failed against an already-gone container and
  raised, instead of falling through to recreate like the sibling
  "already in use" race does.
* **F10** (`c912865`, corrected in a follow-up commit same day) —
  sandbox retention leaked permanently when `run_binary`/`run_gcov`
  raised, since the cleanup statement lived after the `with` block
  instead of in a `finally`. The first pass over-applied this to the
  compile-failure `return 1` branch too, which broke an existing,
  intentional, integration-tested contract (`--verbose`'s printed
  "instrumented source at `<path>`" message on compile failure must
  still resolve after `main()` returns) — caught by
  `tests/integration/test_cli.py::test_run_verbose_prints_instrumented_source_path_on_compile_failure`
  when re-run against the real Docker toolchain (the unit suite alone,
  with Docker mocked, did not exercise this). Fixed by scoping the
  `try/finally` to only the `run_binary`/`run_gcov` phase, leaving the
  compile-failure branch's deliberate no-cleanup behavior untouched.
* **F12** (`3a355ff`) — `--coverage-out` alone was a silent no-op;
  only `--coverage-json` actually implied `--coverage` in code, though
  both were documented to.

**Medium/Low (selected):**
* **F14, F16, F17** (`3ab4507`) — `synthesize_stack`
  failed its whole `stackTrace` request on one unresolvable frame
  instead of skipping it (F14); a second `launch` leaked the first
  gdb session and stale breakpoint numbers (F16); a malformed
  `Content-Length` header crashed the adapter process instead of
  shutting down cleanly (F17).
* **F15** (`f6ad5a1`) — gdb's octal byte-escape (`\NNN`) decoded as
  literal digit characters instead of the byte it represents, in both
  `gdb_session.py` and `variable_map.py`'s C-string unquoters.
* **F19** (`ad3e0e2`) — `FILE-STATUS IS` inside an open `MOCK READ ...
  ROWS` body fell into "malformed ROWS row" instead of parsing —
  `elif` ordering checked the generic ROWS-row branch first.
* **F27** (`e284894`) — a directive using both `FILE-STATUS IS` sugar
  and a `ROWS` block with no `TERMINAL`, on a file missing a status
  field, refused `UNRESOLVED_FILE_STATUS_TARGET` twice for the one
  root cause.
* **F28** (`bb752b6`) — the mutation runner's fallback classification
  cited "binary exited N" even when N was 0 and the real cause was a
  duplicate `CASE START`, an orphan `CASE FAIL`, or zero cases run.
* **F20** (`c912865`, alongside F10) — `--keep-sandbox`'s own retention
  path had no test at all (`test_keep_sandbox_retains_the_directory_
  after_a_clean_run`); the flag itself was untouched.

**Cleanup:**
* **F35** (`c7bee0f`) — removed `_step`'s unused `_dap_command`
  parameter, threaded through 3 call sites for no reason.

**Not fixed (out of scope for a code change, or deliberately deferred
— see the session's final ledger for the full ~20-item ledger):**
F-0a (P0: CI's `COBOL_PARSER_PAT` secret needs a repo admin, not a PR),
F13, F18, F21–F26, F29–F34, F36.

Docs touched: [runtime](runtime.md) (F1, F2, F9, F10 sections plus a
leftover-stale F2 mention in Threat model's Tuning paragraph),
[cli](cli.md) (F4, F5, F6, F8, F12, F14, F16, F17, F28 — debug/mutate
sections), [coverage](coverage.md) (F12), [analysis](analysis.md) (F27,
plus the F-0b `INVOKE` PARSE_WARNING correction), [dsl](dsl.md) (F19),
[report](report.md) (F7), [testing](testing.md) (F-0b Gotchas, two new
cobolparser landmines found along the way).

## 2026-08-07 — Standalone executable distribution retired; build moved to mocky-mock-vscode

Part of the cross-repo-dispatch-build initiative (see the sibling
`mocky-mock-vscode` repo's own `PUBLISHING.md` and its
`build-and-release.yml` workflow for the full pipeline). This repo no
longer builds or publishes standalone `mockymock` executables.

* **Deleted `.github/workflows/build-executables.yml` and
  `.github/workflows/publish-public.yml`** (`c159d02`): the reusable
  Nuitka matrix build and the manual relay to the public
  `cobol-mocky-mock` repo are both gone. That public repo is now unused —
  `publish-public.yml` was its only writer.
* **`release-please.yml` stripped down**: it still cuts this repo's own
  version-bump PRs and a GitHub Release with generated changelog notes on
  merge to `main`, but no longer calls `build-executables.yml` or attaches
  any binaries to that release — its `build-nuitka-executables`/`publish`
  jobs are gone.
* **The sole remaining build path** is the sibling `mocky-mock-vscode`
  repo's new `build-and-release.yml` (`workflow_dispatch` only): it checks
  out this repo at its latest release tag, runs the same Nuitka build
  (`scripts/build_executable.sh`) this repo used to run itself, and
  packages the result straight into the VS Code extension's `.vsix` — no
  intermediate binary artifact or public relay repo involved.
* Docs updated to match: `PUBLISHING.md` (the "Reaching people with no
  repo access at all" section replaced with "Standalone distribution has
  been retired"), [publishing.md](publishing.md) (frontmatter description
  and Overview rewritten; Gotchas' `build-executables.yml` citation
  repointed to the sibling repo's `build-and-release.yml` — the Nuitka
  `--include-data-*` and `release-please-config.json` gotchas themselves
  are still accurate wherever the build now runs), and [index.md](index.md)'s
  Publishing one-liner.

## 2026-08-07 — Independent label-scan safety net for the PARSE_WARNING narrowing (PR #49 review)

* **Closed a real gap in the paragraph-scoped `PARSE_WARNING` narrowing**
  (below): a reviewer pointed out that `_paragraph_owning_line` trusted a
  dropped-content warning's reported `line N` to bound the *entire*
  extent of what cobolparser dropped, when the text only actually proves
  where the drop *starts*. If cobolparser's error-recovery ever skips
  past a real paragraph header while resynchronizing, that header
  vanishes from the AST's own paragraph list entirely — silently merging
  what should have been a separate paragraph into the one the warning
  gets attributed to, which would make the whole narrowing unsound (a
  warning waived as "confined to paragraph X" when the dropped content
  actually also covered a different, reachable paragraph).
* **mockymock cannot verify cobolparser's recovery-loop internals to rule
  this out** — `cobolparser` is a private, cross-owner sibling repo this
  session had no read path into (a dedicated research session against it
  reported a positive finding, but with no way in this environment to
  retrieve its full transcript/citations, that one-line summary wasn't
  enough to stand on for a load-bearing correctness claim). Rather than
  either trust an unverifiable external claim or leave the gap open,
  added a check that stands on mockymock's own verifiable ground instead:
  `_has_unaccounted_label` (new) re-lexes the same normalized source
  independently and scans the candidate owner paragraph's ENTIRE body
  (from `_paragraph_body_span`, a refactor of the old inline boundary
  walk in `_paragraph_owning_line` that now also returns the next
  boundary line) for anything shaped like an unrecognized paragraph-name
  or `SECTION` header — a bare identifier, optionally `... SECTION`,
  alone on its own line. Any match vetoes classification (the warning
  reverts to whole-program, today's behavior) rather than trust that the
  AST-recorded body boundary is really where cobolparser landed.
* **Deliberately conservative, not exact**: a bare COBOL scope terminator
  (`END-IF.`/`EXIT.`/`CONTINUE.`) or `END-EXEC.` alone on its own line is
  syntactically indistinguishable from a paragraph name to this regex and
  will false-positive — accepted, since a false positive only costs a
  classification (the narrowing simply doesn't apply there), never
  produces an unsound one. Both `check_whole_program_scoped` (now takes
  `raw_source` so it can independently normalize and run the guard) and
  `check_unresolved_copybooks_scoped` (already had `normalized_lines`
  locally) route through the same guarded `_paragraph_owning_line`.
* Tests: `tests/unit/test_scoped_refusals.py` adds direct coverage of
  `_has_unaccounted_label` (bare-identifier and `SECTION` shapes detected;
  ordinary multi-token statement lines ignored; the accepted
  scope-terminator false positive pinned explicitly) and a synthetic
  "swallowed header" reproduction that proves the veto fires even when
  the base attribution alone would have classified cleanly.

## 2026-08-07 — Narrow the last whole-program refusals (paragraph-scoped PARSE_WARNING / UNRESOLVED_COPYBOOK)

* **`PARSE_WARNING` and `UNRESOLVED_COPYBOOK` are no longer unconditionally
  whole-program on the `run`/`lint`/`export`/`debug` path** ([analysis](analysis.md),
  [cli](cli.md)): `refusal.check_whole_program_scoped` /
  `check_unresolved_copybooks_scoped` hold back the one provably-narrow
  shape — evidence confined to a single PROCEDURE DIVISION paragraph's own
  body — as a `ParagraphScopedRefusal`, and `cli.checks.run_static_checks`
  (new step 4b) refuses it only when `union_executed_paragraphs` says some
  SELECTED test case could execute that paragraph. The union is the same
  `_reachable_paragraphs` BFS the per-case gates trust, per selected case,
  deliberately without the flow-mock `skip_traversal` narrowing
  (conservative), closed to a fixpoint over the GO TO fall-through hazard
  (`_falls_through` walk from every reached GO TO target — the same
  unmodeled entry shape `_go_to_fallthrough_targets` guards terminators
  against), and `None` (= refuse everything held back) the moment any
  case's BFS reports any flow refusal.
* **Classification fails closed everywhere it can't prove confinement**:
  a warning with no `line N` in its text (`_WARNING_LINE_RE`), a line on a
  paragraph/section header line or before the first paragraph (DATA
  DIVISION content is program-global), a phantom-`.`/section-header
  nearest-boundary attribution, an unverifiable paragraph source order,
  or any multi-program compilation unit (warning lines could index a
  contained program) all stay whole-program refusals — worst case is
  exactly yesterday's behavior.
* **A waived unresolved COPY is also commented out of `lines`**
  (`_copy_own_line_span` → `comment_and_replace`, count-preserving):
  cobc cannot compile an unresolvable COPY even in an unexecuted
  paragraph, so waiving the static refusal without the text edit would
  just trade a clean refusal for a cryptic compile failure. Only the
  single-line `COPY MEMBER.` layout owning its whole normalized line
  qualifies, verified textually (starts with COPY, ends with its
  terminating period, no other period) — the lexer exposes no PERIOD
  token type, so a token-walk to the terminator isn't available; sibling
  code on the line, a second statement after the terminator, and
  multi-line COPY ... REPLACING all refuse whole-program instead.
* **Why an unexecuted paragraph's incomplete AST is safe to waive**: the
  dropped/missing text still compiles verbatim (mockymock splices raw
  text, not the AST); no splice is derived from statements inside it;
  hidden edges FROM it cannot fire at runtime because the paragraph never
  runs; and edges TO parser-lost content are unresolvable names that
  already refuse (`UNRESOLVED_FLOW_TARGET`/`UNKNOWN_PARAGRAPH`) wherever
  a reachable paragraph carries one.
* **Transparency**: waivers are never silent — `StaticCheckResult.notes`
  carries one line per waived warning/COPY (and names the commented-out
  span), printed by `run`/`debug`/`export`/`lint` with their own prefix.
* `generate`/`fixtures` keep the plain unconditional entry points
  (`check_whole_program`/`check_unresolved_copybooks`, now thin wrappers
  over the scoped variants with classification off): with no test cases
  there is no reachable set to scope against.
* Tests: `tests/unit/test_scoped_refusals.py` — including a pin that
  cobolparser's dropped-content warnings carry a locatable line number in
  the same normalized-text space as `SourceLocation` (if that upstream
  format ever changes, the feature degrades safely to whole-program
  refusals and the pin fails loudly), GO TO fall-through closure both
  ways, own-line span verification, DATA DIVISION COPYs staying
  whole-program, and `generate`-path behavior unchanged.

## 2026-08-06 — PR #46 post-review polish pass (unify-with-data)

Five pre-merge, non-blocking fixes from PR #46's code review, applied after
approval (see `.superpowers/sdd/2026-08-04-unify-with-data-plan/
pr46-review-fixes-report.md` for the full writeup):

* **Corrected an overclaim about VERIFY counts under `--placeholder`**
  ([dsl](dsl.md), `generator.py`'s `_bundle_directive_for` docstring and
  `CallCountOverride`'s own docstring): both previously said/implied other
  categories' call counts are "unaffected by which data the mock body
  carries." False — a `CallCountOverride` only recomputes the DOWNGRADED
  boundary's own `call_count`; a different boundary reached a
  program-flow-driven number of times *inside the same loop being
  downgraded* (e.g. a `CALL` made once per row in a `PERFORM ... UNTIL
  <eof-flag>` loop whose READ was downgraded to signal EOF on call 1) is
  NOT recomputed and can go stale. Inherited heuristic behavior, not new;
  `--placeholder` just makes it easier to reach. Doc-only, both
  docstrings and `.okf/dsl.md`'s mirror of the same claim corrected;
  `CallCountOverride`'s "not a guess" phrasing softened to the precise
  guarantee (exact assuming the program stops reading/fetching that
  boundary once the end-of-data signal fires — the same assumption the
  rest of the engine already makes).
* **Fixed a real bug**: [splicer](splicer.md)'s `injector.build_site_
  dispatch`, READ ROWS exhaustion branch. When a directive has BOTH `rows`
  and a `TERMINAL` group, and the file declares a `FILE STATUS` field, the
  exhausted (`WHEN OTHER`) branch used to emit ONLY the TERMINAL group's
  own MOVEs — if TERMINAL set an EOF flag but never mentioned the status
  field, that field was silently left at whatever `"00"` the default-
  success MOVE set on the call that triggered `WHEN OTHER`, an EOF-flag/
  status-field inconsistency a program checking both would see. Fixed by
  applying the SAME "implicit default, explicit override" ordering the
  plain FILE-STATUS default/override pair a few lines above already uses:
  the exhausted branch now always emits `MOVE "10" TO <status field>`
  first (when the file has one), then the directive's own TERMINAL MOVEs
  after — so an author's own MOVE to that field (if TERMINAL has one)
  naturally overrides the default by coming later in the same WHEN
  branch, and an absent one still gets the correct "10" instead of a
  stale "00". SQL ROWS (no TERMINAL grammar) is untouched. Two new tests
  in `tests/unit/test_injector.py` pin both shapes (TERMINAL without the
  status field: both lines present, default before TERMINAL; TERMINAL
  targeting the status field: both lines present, author's value last).
* **`mockymock fixtures`/`generate --rows` now reject a negative value at
  the CLI layer** ([cli](cli.md)): new shared `_check_rows_non_negative`
  helper (mirrors `_check_input_files`'s "fail fast on a bad invocation"
  placement), called right after the input-file check in both
  subcommands, before any parsing or generator construction. Previously
  `--rows -1` on `fixtures` crashed with a raw traceback
  (`DataGeneratorOptions` construction sat outside any try/except there);
  on `generate --with-data` it was caught but only after other work and
  with the wrong message/stream. New tests in `test_cli_fixtures.py` and
  `test_cli_generate_with_data.py`.
* **`tests/unit/test_bundle_surface_keys.py` hygiene**: `EXAMPLE_PROGRAMS`
  corpus discovery's `read_text()` now passes `encoding="utf-8"`
  explicitly (was implicit-locale-dependent); the `assert len(...) >= 14`
  corpus-shrink guard moved out of module level (where a failure is a
  pytest collection ERROR, and vanishes entirely under `python -O`) into
  its own `test_example_corpus_has_expected_minimum_size` test function.

## 2026-08-05 — unify-with-data: hand-authored `ROWS`/`TERMINAL` on READ, `mockymock fixtures`, `--rows`/`--placeholder` on `generate --with-data`

Reconciliation branch that ports the parked `feature/generate-with-data`
branch's unique deliverables onto origin/main's already-released Phase 8
bundle-driven `generate --with-data`/`--fixtures` engine (see the entry
above), rather than the other way around — main's `dsl/fixture_bundle.py`
+ `dsl/generator.py` + AT-END replication (`3ad3378`) stayed the emission
engine throughout; nothing here changes their behavior. Plan:
`docs/2026-08-04-unify-with-data-plan.md`.

* **cobolparser pin bumped** to `ff64b25` (origin/main at reconciliation
  time — PR #110's gen-fixtures fixes, PR #112's EJECT support), superseding
  main's `b3e2b32`. Ported `tests/unit/test_bundle_surface.py` (bundle-shape
  smoke test) verbatim from the parked branch.
* **New DSL grammar, hand-authoring only**: `MOCK READ <file> ROWS ( FIELD
  = value, ... ) ( ... ) [TERMINAL ( FIELD = value, ... )] END-MOCK` —
  `ROWS` was previously SQL-only; `TERMINAL` is new, giving the
  rows-exhausted branch its own field assignments instead of a default. A
  human (or an editor integration) writes this against `mockymock
  fixtures`' JSON output; the bundle-driven scaffold below does **not**
  emit it — it still hand-rolls its own `EVALUATE` for a multi-row READ.
  `splicer/injector.build_rows_block` generalized from a SQL-only,
  SQLCODE-hardcoded function to `build_rows_block(tally_name, rows, *,
  row_suffix_moves, exhausted_moves)`; both call sites (SQL, READ) now
  live in `build_site_dispatch`, which is also where the SQLCODE 0/100
  literals actually live post-generalization (not in `build_rows_block`
  itself — a docstring in `dsl/generator.py`'s `_sql_wants_rows` still
  pointed at the old location and was corrected in the same pass as this
  entry). A `MOCK READ ... ROWS` with no `TERMINAL` group **and** no
  resolvable `FILE STATUS` field refuses `UNRESOLVED_FILE_STATUS_TARGET`
  (`refusal.check_test_case`, a second trigger under the code the
  `FILE-STATUS IS` sugar case already used) — fail-closed rather than
  splice a READ loop with no way to signal end-of-data.
  See [dsl.md](dsl.md)'s "`ROWS` cursor sugar" section, [splicer.md](splicer.md)'s
  "Dispatch and Trap Generation" section, and [analysis.md](analysis.md)'s
  `check_test_case` writeup.
* **New `mockymock fixtures <program>` subcommand**: prints a cobol-parser
  `FixtureBundle` as JSON on stdout (`--scenarios happy|branches|all`,
  `--seed N`, `--rows N`, `--copybook-path DIR ...`), for editor
  integrations rather than `.cut` scaffolding — stdout is JSON only, every
  diagnostic (including "no such file") goes to stderr. Hand-ported (not
  cherry-picked — `cli/main.py` had diverged too far from the parked
  branch) with its copybook-expansion-before-parse-gate ordering matching
  `_cmd_generate`'s own. See [cli.md](cli.md)'s `fixtures` entry.
* **`--rows N` / `--placeholder CATEGORY:KEY` on `generate --with-data`**:
  `--rows` maps to `DataGeneratorOptions(rows=N)` on the self-generating
  `--with-data` path only (`--rows` + `--fixtures` is a clean stderr
  rejection — that bundle's row count is already baked in); `--rows 0` is
  honored (`is not None`, not truthiness). `--placeholder` (repeatable)
  downgrades a matched fixture's mock body to its ordinary
  non-data-seeded placeholder while keeping it MOCKED, valid with either
  `--with-data` or `--fixtures`; a malformed value (no `:`) exits 1, an
  unmatched pair warns on stderr instead of the parked branch's own silent
  no-op.
  Two loop-termination bugs found and fixed empirically (not by lint,
  which is static and cannot see a splice-time infinite loop — by
  reasoning through what the downgraded body actually does at runtime,
  same discipline as the `3ad3378`/gen-fixtures-Phase-8 fixes above):
  * A downgraded (or `--rows 0`, or bundle-"empty input"-family) READ
    fell back to a completely empty `MOCK READ` body, dropping the
    replicated `AT END` handling along with the seeded rows and hanging
    the program's own `PERFORM ... UNTIL <eof-flag>` loop forever;
    likewise a downgraded SQL-ROWS fixture fell back to the ordinary `MOVE
    0 TO SQLCODE` placeholder (permanent "more rows available"), hanging a
    `PERFORM UNTIL SQLCODE = 100` cursor loop the same way. Fixed via a
    shared `_read_exhaustion_lines` helper (the same content `_read_body`
    already used for its own `WHEN OTHER` branch, now also used for the
    empty-sequence and `--placeholder`-downgraded cases) and a
    `_SQL_ROWS_EXHAUSTED_BODY` constant mirroring the splicer's own
    hardcoded value.
  * That fix alone left a second bug: a downgraded READ's corrected body
    signals EOF on the very first call, so the program calls it exactly
    once at runtime — but the generated `.cut` still carried the bundle's
    original, now-stale `VERIFY READ <file> WAS CALLED N TIMES` from the
    un-downgraded sequence, an assertion the file could never itself
    satisfy. Fixed via `CallCountOverride`, computed at the same seam that
    decided the downgraded body: `count=1` when the downgraded body
    carries a real termination signal, else `demote_reason=...` (rendered
    as a `*>` comment instead of a speculative `VERIFY` number) when it
    doesn't — the runnable-by-construction invariant covers the whole
    generated file, assertions included, not just mock bodies.
  See [dsl.md](dsl.md)'s "`--rows` / `--placeholder` on the bundle-driven
  scaffold" section.
* **Contract test**: ported `tests/unit/test_bundle_surface_keys.py` from
  the parked branch, adapted (its `mockymock/generation/with_data.py`
  references didn't exist in this codebase's architecture — corrected to
  the real join in `dsl/generator.py`'s `_mockymock_boundary_keys`/
  `_unique_prefix`; added the `annotate_nested_sites` step main's own
  `test_fixture_bundle_contract.py` established as necessary). Kept
  alongside (not instead of) that existing contract test: this one is a
  weaker subset check (`bundle_keys <= surface_keys`, joining EXEC by
  line) over a broader, glob-discovered corpus (14 programs incl.
  `examples/fixtures/FIXTUREDEMO` and two NIST programs, vs. the other
  test's curated 11); the existing one is a stricter equality check
  (`bundle-key == _unique_prefix(site, surface)`, the exact join the real
  `--with-data` emission path uses) over a hand-maintained list. Genuinely
  complementary, not redundant — different join strategy, different
  corpus.
* Examples: `examples/fixtures/FIXTUREDEMO` (main's existing golden,
  Phase 9) stays canonical; the parked branch's duplicate
  `examples/fixturedemo/` was not ported. `--rows`/`--placeholder`
  against that same example are already covered end-to-end by
  `tests/unit/test_cli_generate_with_data.py` (includes a
  no-new-flags-byte-identical assertion against the checked-in golden), so
  `tests/integration/test_fixturedemo_golden.py` itself was left
  unextended.
* Updated: [dsl.md](dsl.md), [splicer.md](splicer.md), [analysis.md](analysis.md),
  [cli.md](cli.md), [index.md](index.md) (this entry's sections above/below);
  `CHANGELOG.md`'s Unreleased section.

## 2026-08-04 — PR #44 Copilot review: `_RECORD_RE` couldn't match a subscripted name

GitHub Copilot's automated review of PR #44 left one comment; verified
against the actual code before acting (a stale local checkout initially
made the flagged file look like it didn't even contain `_RECORD_RE` at
all — fixed by `git fetch` + `git merge --ff-only` before investigating
further, same fix as the sibling cobol-parser repo's own PR #108 hit the
same session).

`report/results.py`'s `_RECORD_RE` used a bare `(?P<name>\S+)` for the
data-name in `__MOCKYMOCK__ RECORD <id> <name>: <value>`. A subscripted
name like `WS-TABLE(1, 1)` contains a space after the comma —
`analysis.stub_expectations.scan_stub_expectations` explicitly supports
this shape (`dsl.parser._SUBSCRIPTED_NAME`, pinned by
`test_stub_expectations.py::test_subscripted_stub_name_parses`), and
`splicer.driver.build_driver` emits it into the `RECORD` line verbatim —
confirmed by reading `build_driver`'s own f-string, which interpolates
`name` both into the marker's literal-text portion and as the actual
COBOL operand displayed. `\S+` stops at the first space, so for that
input the regex would look for `": "` right after `WS-TABLE(1,` — never
finds it there — and the whole line fails to match, silently dropping the
recorded value with no error signal at all.

Fixed: `_RECORD_RE`'s `name` group now reuses `dsl.parser._SUBSCRIPTED_NAME`
directly (imported, not reimplemented) rather than a parallel pattern that
could drift from the one `scan_stub_expectations` already established and
tested. New test:
`test_report.py::test_parse_stdout_records_a_subscripted_name_containing_a_space`.
Updated: [report.md](report.md) (new gotcha entry cross-referencing the fix
and its rationale).

## 2026-08-04 — Auto-generated READ mocks silently produced infinite loops

Found by PR #44's own CI: `examples/fixtures/FIXTUREDEMO`'s Docker-gated
`@requires_docker` run (the one check `mockymock lint`, Docker-free by
design, cannot exercise) timed out after 30s with "a mocked CALL may have
removed a loop's terminating condition, producing an infinite loop" --
actually a mocked READ, same mechanism. Root cause: `dsl/generator.py`'s
`_read_body` (the bundle-driven READ mock body, Phase 8) built its
exhaustion (`WHEN OTHER`) branch purely from `fixture.terminal` (the FILE
STATUS field), with zero awareness that the splicer deletes the *whole*
READ statement (`splicer/orchestrator.py`'s own module docstring) --
including its source `AT END MOVE "Y" TO WS-EOF` clause, the idiom that
actually flips the program's own loop-guard flag. A generated mock that
moves only the FILE STATUS field never flips that flag, so `PERFORM ...
UNTIL WS-EOF = ...` never terminates. `examples/invupdt/INVUPDT.cbl`'s own
`INV-FILE` (no `FILE STATUS` clause at all) turned out to have an even
worse version of the same bug: `fixture.terminal` is correctly `None`
there (cobol-parser's own `_resolve_status_field` fix), so the old code
emitted an `EVALUATE` with **no `WHEN OTHER` branch at all** -- confirmed
by manually re-generating INVUPDT's `--with-data` output (its own
hand-written `.cut`, which explicitly does `MOVE "Y" TO WS-EOF`, was never
affected; only the auto-generated path was).

Fixed: new `_replicated_at_end_moves`/`_is_safe_literal_source` helpers
walk the source READ statement's own `at_end_clause` (available via
`BoundarySite.statement`, the raw AST node `mock_surface.py` already
carries) and replicate any `MOVE` whose source is a quoted literal,
numeric literal, or figurative constant -- deliberately never a bare
identifier, whose value in the mock's own splice-time context isn't the
real program's runtime state. Whether `WHEN OTHER` is emitted at all is
now gated on the *source* clause existing, not on `fixture.terminal`
being truthy, so INVUPDT's no-status-field case gets a `WHEN OTHER` too.
When the clause exists but nothing in it is safely replicable (a bare
identifier, an IF, ...), a `*> TODO` comment flags the gap in the
generated `.cut` instead of silently doing nothing.

Both `examples/fixtures/FIXTUREDEMO.cut` and (verified manually, not
checked in there) `examples/invupdt/INVUPDT.cbl`'s own `--with-data`
output now correctly emit `MOVE "Y" TO WS-EOF` in their `WHEN OTHER`
branch. New unit tests in `test_dsl_generator_bundle.py`: no-status-field
replication, replication alongside a real status field (order-checked:
status MOVE before the replicated MOVE), and the identifier-source TODO
fallback. This class of bug is invisible to `mockymock lint` (static,
never compiles/runs) and to the corpus lint-gate test
(`test_generate_with_data_lint_gate.py`) by the same token -- a real
Docker run was the only thing that caught it; worth remembering next time
a "lints clean" result feels like enough.

## 2026-08-04 — `examples/fixtures/FIXTUREDEMO`: the gen-fixtures worked example (Phase 9)

Cross-repo worked example closing out the `gen-fixtures` program-scoped
test-data initiative: `FIXTUREDEMO.cbl` (copied verbatim from
`Landparty/cobol-parser`'s own `examples/fixtures/`) touches all four
boundary categories the initiative supports -- `ACCEPT`,
`OPEN`/`READ`/`CLOSE`, `SQL` (a plain host-variable `SELECT`, no cursor,
so it stays clear of `examples/custprog/`'s documented DCLGEN gap), and a
static `CALL` -- with every boundary resolving cleanly (zero entries in
`bundle.unresolved`). `FIXTUREDEMO.bundle.json` (seed 42, `mode="happy"`)
is also copied verbatim from cobol-parser's repo, where it is the
checked-in golden for that repo's own `ProgramFixtureGenerator` output.

`FIXTUREDEMO.cut` is generated *here*, from that exact bundle
(`mockymock generate FIXTUREDEMO.cbl --fixtures FIXTUREDEMO.bundle.json`),
and checked in as this repo's own golden -- deliberately via `--fixtures`
rather than `--with-data`, so the golden is pinned against a fixed JSON
rather than whatever cobol-parser commit `pyproject.toml` happens to have
pinned when a contributor re-runs the regeneration command (see
`--fixtures`'s own reason for existing: dsl/generator.py's own module
docstring, "CI use, and it keeps the JSON schema honest"). Output covers
every mock-body shape the bundle-driven scaffolder produces: a
single-value body (`ACCEPT`, `SQL`, `CALL`), a status-only body
(`OPEN`/`CLOSE`), and a tally-branching multi-row `EVALUATE` chain
(`READ`, 10 rows then exhaustion) -- verified by inspection against the
actual generated text, not assumed from the category list alone.

New `tests/integration/test_fixturedemo_golden.py`: byte-identical
regeneration (Docker-free), determinism (two independent calls agree,
Docker-free), the checked-in `.cut` still passes `mockymock lint`
(Docker-free), and a `@requires_docker` case proving the real run stays
green -- the last one could not be exercised in this sandbox (no Docker
daemon) but runs for real in CI, matching every other worked example's own
`@requires_docker` pattern.

New `examples/fixtures/README.md` (this repo) cross-references
cobol-parser's own `examples/fixtures/README.md` (the program walkthrough
and boundary/category table) rather than repeating it. Updated
[testing.md](testing.md) (new FIXTUREDEMO write-up section, overview
paragraph's example count 7 -> 8).

## 2026-08-04 — `mockymock generate --with-data`: bundle-driven scaffold (gen-fixtures Phase 8)

`generate` now has a second scaffold mode: `--with-data` calls cobol-parser's
`ProgramFixtureGenerator().generate_with_scenarios_from_file(...)` directly (no
subprocess) and threads the resulting `FixtureBundle` through `scaffold_cut`,
which builds one `TESTCASE` per scenario — real generated data in each `MOCK`
body, `EXPECT`/`VERIFY`/`*> STUB EXPECT` lines from the bundle's own
expectations — instead of one placeholder-bodied `TESTCASE` per paragraph.
`--fixtures PATH` accepts a pre-generated bundle JSON instead (CI use, and it
keeps the JSON schema honest as a real serialization boundary rather than a
Python-object handoff mockymock and cobol-parser could silently drift apart
on). Full design: `docs/plans/2026-08-02-program-data-generation-*.md`
(cobol-parser repo). New: `dsl/fixture_bundle.py` (loader — parses the bundle
JSON into mockymock-local dataclasses; never imports cobol-parser's own bundle
*classes*, only the serialized shape). Rewritten: `dsl/generator.py` (the
bundle branch of `scaffold_cut`). Extended: `cli/main.py`'s `_cmd_generate`.
See [dsl.md](dsl.md)'s "Bundle-driven scaffold" section and
[cli.md](cli.md)'s `generate` entry for the full mechanism.

Three integration bugs found and fixed empirically (generate a real bundle,
inspect it, find the discrepancy — not guessed from reading either side's
code in isolation):

* **Multi-file `OPEN`/`CLOSE` silently dropped the second file's key.**
  `_mockymock_boundary_keys` (and the pre-existing `_directive_for`) only
  ever looked at `site.keys[0]`; `OPEN INPUT INV-FILE OUTPUT RPT-FILE` lost
  `RPT-FILE` entirely. Fixed by widening the loop to every entry of
  `site.keys`. That alone then caused a *second* bug: emitting one `MOCK
  OPEN` directive per key (`INV-FILE` **and** `RPT-FILE`) declares two
  directives that both match the *same* physical `BoundarySite`, which the
  refusal gate correctly refuses as `AMBIGUOUS_MOCK`. Fixed by
  `_bundle_mock_directives` grouping fixtures by `id(site)` (physical
  identity, not key) and emitting one directive per group with one chosen
  representative key.
* **`VERIFY_WITHOUT_MOCK` after fixing the ambiguous-mock bug.** Once only
  one directive per physical site is declared, checking `_render_expectation`'s
  `VERIFY` gate against the *full* `mockymock_keys` set (every key mockymock's
  own walk knows about) is too permissive — `RPT-FILE` is in that set but was
  never literally declared as this TESTCASE's primary key. Fixed by having
  `_bundle_mock_directives` return `(lines, declared_keys)` and gating the
  `VERIFY` line on `declared_keys` (only the literally-emitted primary keys),
  not the broader mockymock-wide set.
* **OUT-direction boundaries (WRITE, SQL UPDATE/INSERT/DELETE) read as
  `UNMOCKED_*`.** `_bundle_boundary_keys` originally only walked
  `call_count`-kind expectations; an OUT-direction boundary gets no fixture at
  all (see cobol-parser's `docs/fixture-bundle-schema.md`) — only a
  `kind="stub"` expectation is the *sole* place its `(category, key)` appears
  in the whole bundle. Fixed by including `stub`-kind refs in the mismatch set,
  and by widening `_bundle_mock_directives` to unconditionally cover *every*
  `mockymock_keys` entry not yet emitted with a placeholder body (not just ones
  a boundary-level stub flagged) — a simpler rule that, as a side effect, also
  papers safely over the custprog gap below.

One upstream (cobol-parser) bug found and fixed in that repo, not worked
around here, per this initiative's own established precedent: a READ
boundary with no declared `FILE STATUS` field was defaulting `terminal` to
a literal `"FILE-STATUS"` placeholder string instead of `None` — see
cobol-parser's own log for `program_fixtures.py`'s `_resolve_status_field`/
`_status_dict` fix (commit `b3e2b32`).

**Contract test** (`tests/unit/test_fixture_bundle_contract.py`): pins that
`mock_surface.analyze()`'s `(category, key)` set exactly equals the bundle's,
across an 11-program corpus under `examples/`. Two of the three failures hit
while first writing this test were not product bugs at all: the test harness
itself never called `annotate_nested_sites` before computing
`_mockymock_boundary_keys`, so *every* nested boundary site (a CALL/EXEC
inside an IF, PERFORM, etc.) was silently filtered out by that function's own
"skip an unspliced nested site" guard — `claimseg/CLAIMSEG.cbl`'s `DLI ISRT`
(nested in an IF) and `regnavg/REGNAVG.cbl`'s `CALL "LOGALERT"` (also nested
in an IF) both disappeared from `mockymock_set` for this reason alone, not
because of any real analysis gap. Fixed by mirroring `cli/main.py`'s own
pipeline exactly (`normalize_fixed_format` + `strip_compiler_directives` +
`collect_scope_map` + `annotate_nested_sites`) in the test's `_key_sets`
helper. The third, `custprog/CUSTPROG.cbl`'s `(SQL, FETCH)`, is a real,
accepted gap (see below) and is the test's one documented
`xfail(strict=True)` case, with the full empirical trace in its own reason
string — not silently accepted.

**Known, accepted v1 gap: DCLGEN-style `EXEC SQL INCLUDE`.**
cobol-parser's `expand_copybooks` only expands plain `COPY <member>`
statements — `EXEC SQL INCLUDE CUSTREC END-EXEC` (custprog's DCLGEN-style
host-variable copybook, `examples/custprog/copybooks/CUSTREC.CPY`) is left
untouched, so `CUST-ID`/`CUST-NAME` never become real `CobolDataItem`s in
cobol-parser's own AST and `ProgramFixtureGenerator` can't resolve the FETCH
boundary's host variables (correctly reported via `bundle.unresolved`, not
guessed at). mockymock's own splicer (`splicer/sqlca.py`) resolves this exact
construct independently, via its own copybook-path search purely for
compiling test runs — the two tools' preprocessing pipelines are not unified.
Verified this degrades safely rather than refusing: `generate --with-data`
emits a placeholder `MOCK SQL "FETCH"` body via the "cover every
mockymock-known key" fallback above, and the result passes `mockymock lint`
clean. Extending cobol-parser's copybook expansion to understand `EXEC SQL
INCLUDE` is a real, separate preprocessing feature — out of scope for this
initiative; tracked as a known limitation, not fixed here.

**Lint gate** (`tests/integration/test_generate_with_data_lint_gate.py`,
Docker-free): generates a `.cut` for every corpus program across all three
`--scenarios` modes (happy/branches/all) and asserts `mockymock lint`
(`cli.checks.run_static_checks`) finds zero problems in each — "a generator
that emits a refusable `.cut` is worse than none," per the parent plan's own
Phase 8 gate.

**Dependency pin**: `pyproject.toml` and both `.github/workflows/ci.yml`
`ref:` occurrences bumped to cobol-parser's
`claude/data-generation-function-k2mbbj` branch (commit
`b3e2b329f014c3a8e52f5fac5679e812acbb44b2`) — an interim branch pin, not
`main`, since Phases 1-8's cobol-parser work (everything `--with-data`
depends on) isn't merged there yet (cobol-parser PR #108). Re-bump to a
`main` commit once that PR merges; see [integration.md](integration.md)'s new
gotcha entry.

Docs updated: [dsl.md](dsl.md) ("Bundle-driven scaffold" section),
[cli.md](cli.md) (`generate` flow), [integration.md](integration.md) (two new
gotchas: the interim branch pin, the `EXEC SQL INCLUDE` gap).

## 2026-08-04 — `mockymock run --record-expectations`: golden/characterization mode

New `run` flag, not a new subcommand: reuses the exact same parse → static-checks →
splice → compile → run pipeline `run` already has, adding one splice-time input and
one post-run step. Backs cobol-parser's `gen-fixtures` initiative's tier-3 stubs
(`Expectation(kind="stub")`) — fields the constant-folder couldn't resolve a value
for, meant to be filled in by actually running the program once, not guessed at
statically. Design doc written first, per the parent plan's own gate:
[docs/2026-08-04-record-expectations-design.md](../docs/2026-08-04-record-expectations-design.md).

Mechanism, three new pieces:
- A `*> STUB EXPECT <data-name> [-- <note>]` comment convention — an ordinary `*>`
  comment as far as `parse_cut()` is concerned (zero grammar changes), scanned as
  raw text by the new `analysis.stub_expectations` module and attributed to its
  owning TESTCASE by runtime case id, deliberately *not* via the `.cut` grammar
  (`mockymock collect` parses `.cut` files with no `.cbl` at all — see [dsl.md](dsl.md)).
- `splicer.driver.build_driver` gains an optional `record_targets` param; when set,
  it emits one `__MOCKYMOCK__ RECORD <id> <name>: <value>` DISPLAY line per
  recorded field, right where a real `EXPECT` would run — reusing the FAIL line's
  own proven-safe "literal text + bare identifier" DISPLAY shape rather than a new
  primitive. `report.results.parse_stdout` gained a seventh marker regex for it,
  attributed by id (unlike `--trace`'s positional `MOCK:` marker, since `RECORD`
  carries a real case id already in scope at its splice site).
- New `report.record_rewrite` module: matches a stub scan against the run's
  recorded values, decides bare-vs-quoted rendering from the observed text's own
  shape (not by resolving the field's PICTURE), and rewrites the `.cut` file in
  place — never touching a line that isn't a stub comment, never writing the file
  at all if nothing was recorded.

The "never overwrite a hand-edited EXPECT" guarantee the parent plan asked for
turned out to need no tracking at all: once a stub becomes a real `EXPECT` line
(by this feature or by hand), it structurally can never match the stub-comment
scan again. Pinned by an idempotency test at both the unit and integration
(Docker) tiers — running `--record-expectations` twice in a row against an
already-recorded file is byte-for-byte identical.

New: `analysis/stub_expectations.py`, `report/record_rewrite.py`,
`tests/unit/test_stub_expectations.py`, `tests/unit/test_record_rewrite.py`,
`tests/integration/test_record_expectations.py` +
`tests/integration/fixtures/record_expectations_example.{cbl,cut}`. Updated:
`splicer/driver.py`, `report/results.py`, `cli/main.py`. Docs updated:
[dsl.md](dsl.md), [analysis.md](analysis.md), [splicer.md](splicer.md),
[report.md](report.md), [cli.md](cli.md), [testing.md](testing.md),
`README.md`, `CHANGELOG.md`.

## 2026-08-03 — `mockymock export`: write instrumented source for z/OS compilation

New subcommand, Docker-free, reusing the same parse → static-checks → splice → driver-insert
pipeline that `run` uses (`_cmd_run` steps 2–13 per [cli.md](cli.md)), but stopping before
Docker and writing to a file instead. Three z/OS-portability adjustments: preserved `PROCESS`/`CBL`
directives (which `run`/`lint` strip for GnuCOBOL's consumption), restored fixed-format columns
(7-space Area A prefix, column-72 wrapping for over-long generated `DISPLAY` statements), and a
provenance/disclaimer header documenting that the build is mock-only and listing known GnuCOBOL-
vs-IBM-COBOL gaps a clean compile here does not rule out. Output defaults to `<program>.mainframe.cbl`.

Full design, including empirical validation of the wrapping algorithm and the three adjustments:
[docs/2026-08-03-mainframe-export-command-design.md](../docs/2026-08-03-mainframe-export-command-design.md).
Unit tests cover the refusals (column overflow, etc.) and the directive-preservation behavior.

## 2026-08-03 — `mockymock dashboard`: a local status page for the toolchain

New concept: [dashboard.md](dashboard.md). A static page (plain HTML/CSS/JS
under `mockymock/web/static/`, no build step) served on `127.0.0.1` by a
stdlib `ThreadingHTTPServer`, polling one read-only JSON endpoint every 5s
to show whether Docker and the GnuCOBOL toolchain are up. First deliberately
extensible surface — the page renders purely from the payload, so future
panels are additive.

Two decisions worth keeping: the probe (`mockymock/runtime/status.py`)
mirrors `ensure_toolchain`'s lifecycle checks but **never calls it** —
`ensure_toolchain` builds images and rm+recreates containers, so a polling
page would trigger rebuilds from a browser refresh; and the bind address is
fixed at loopback since the endpoint is unauthenticated.

Adding the subcommand also surfaced a latent CLI rule that
[cli.md](cli.md)'s Gotchas now states explicitly: `build_parser()` runs on
every `--help`/`--version`, so an import *there* defeats the deferred-import
discipline more thoroughly than a module-top import in a single `_cmd_*`
would. The first draft read `web.server.DEFAULT_PORT` for an argparse
default, which pulled `runtime.docker_toolchain` (and its import-time
Dockerfile read) into every invocation. Now pinned by a subprocess test.

Packaging needed three separate mechanisms, not one:
`[tool.setuptools.package-data]` covers the wheel (verified against a built
wheel), but **Nuitka ignores it entirely**, so the static assets also needed
`--include-data-dir` in `scripts/build_executable.sh` or the released
binaries — the primary artifact — would have 404'd while every test passed.
`build-executables.yml` now curls the dashboard out of the freshly built
binary on all three platforms. [publishing.md](publishing.md)'s Gotchas
generalizes this for the next data file.

## 2026-08-03 — v0.1.0's binaries were missing; recovered as v0.1.1

`v0.1.0` (released earlier the same day) had **no binary assets attached** —
the Windows leg of `build-executables.yml` failed to authenticate the
private `cobolparser` git dependency (`pwsh` doesn't expand `${TOKEN}` the
way `bash` does, so the rewritten clone URL silently embedded an empty
token), which failed that matrix job and skipped `release-please.yml`'s
`publish` job for all three platforms, not just Windows. Root cause fixed
earlier the same day (`257dcbf`, `shell: bash` pinned on the credential
step) but nothing re-triggered the pipeline, since `ci:` commits don't bump
the version on their own.

Forcing a release turned up a second, previously-latent bug:
`release-please-config.json` still had `"release-as": "0.1.0"` pinned from
the original bootstrap release. That silently overrode a `Release-As:
0.1.1` commit trailer and made `release-please` propose a no-op release
back against the already-existing `v0.1.0` tag (PR #37, closed unmerged).
Removed the stale pin (`2c08bd2`) so `release-please` resumed computing
versions normally; the corrected PR #38 (`chore(main): release 0.1.1`)
merged cleanly and the now-fixed pipeline built and attached all three
executables. `v0.1.0` stays published as-is (tagged, no assets) — an
accurate record that the first attempt was broken, not amended after the
fact. See [publishing.md](publishing.md)'s new Gotchas section for both
root causes.

## 2026-08-02 — Manual publish pipeline to the public cobol-mocky-mock repo

New concept: [publishing.md](publishing.md). The existing
`build-nuitka-executables` job in `release-please.yml` (matrix Nuitka
build, 3 OS executables bundling the pinned `cobolparser` dependency) was
extracted into a reusable workflow, `build-executables.yml`
(`workflow_call`), so a new manually-triggered workflow,
`publish-public.yml` (`workflow_dispatch` only), can share the same build
without duplicating it. `publish-public.yml` publishes only the 3 binaries
plus `LICENSE` to a GitHub Release on the separate public repo
`samdion1994/cobol-mocky-mock` (its own new `README.md` documents
install/requirements for that audience) — closing the gap `PUBLISHING.md`
had flagged as unsolved ("a separate public releases-only repo... someone
with repo-admin context needs to decide that part"). `release-please.yml`'s
existing automatic private-repo release is unchanged apart from calling the
same reusable workflow.

Confirmed during design, not just assumed: the compiled binary already
exposes mockymock's full CLI surface (`setup`/`generate`/`run`/`debug`/
`lint`/`mutate`/`collect`) with no external access needed —
`cobolparser` is consumed as an internal library, fully compiled in by
Nuitka, and the bundled Docker base image (`debian:trixie-slim`) is public.
`cobolparser`'s own separate standalone CLI (`cobol-parser` console script:
`parse`/`tokenize`/`program-flow`/etc.) is not part of this build and stays
unavailable to a binary-only user — a known, accepted gap, not an
oversight.

## 2026-07-29 — Added CPYPROC: PROCEDURE DIVISION copybook + PERFORM + paragraph mocks

New worked example (`examples/cpyproc/`) closing a documentation gap: every
existing copybook example resolves *data* (`tests/integration/fixtures/
copybook_example`, `examples/custprog`) — none exercised a copybook that
supplies *procedure logic*: a whole paragraph, `COPY`'d straight into
PROCEDURE DIVISION and invoked with `PERFORM`, the idiomatic mainframe
pattern for sharing business logic across programs. `copybooks/
CALCPERF.CPY` supplies one paragraph, `CALC-DISCOUNT` (a `CALL "DISCRATE"`
boundary plus a `COMPUTE`); `CPYPROC.cbl`'s `MAIN-PROCESS` performs it.
Three test cases prove the two testing strategies this combination
enables: (1) direct — `PERFORM CALC-DISCOUNT` as the case's own entry
point, unit-testing the copybook's logic in isolation; (2) collaborator,
stubbed — `PERFORM MAIN-PROCESS` with `MOCK PARAGRAPH CALC-DISCOUNT`
replacing it, `VERIFY ... WAS PERFORMED ONCE` proving the caller's own
logic (`WS-ORDER-COUNT`) without running the real copybook body; (3)
collaborator, unmocked — same caller, real copybook body, needing (and
getting) its own `MOCK CALL "DISCRATE"`, same lesson as `examples/
flowmock`'s third case. See [testing](testing.md).

No code changes to `mockymock` itself — the point of the example is that
none were needed. `--copybook-path` expands `COPY` textually before
`parse_cobol` ever runs (confirmed by reading `cli/main.py`/`cli/
checks.py`), so a copybook-sourced paragraph is bit-for-bit
indistinguishable from an inline one by the time `mock_surface.py`'s
reachability walk or `flow_mocks.py`'s header-dispatch splice look at it —
neither is copybook-aware, and neither has to be.

Verified two ways, both short of a full `mockymock run` in this sitting:
(1) `mockymock/dsl/parser.py::parse_cut` (no `cobolparser` dependency)
against the committed `.cut` confirms all three cases parse to the exact
expected model (`perform_target`, `mocks`, `expectations`,
`verifications`). (2) The novel COBOL claim — a whole paragraph `COPY`'d
into PROCEDURE DIVISION, `PERFORM`ed directly and `PERFORM`ed transitively
through a caller — compiled and ran correctly against a real `cobc`
(GnuCOBOL 3.1.2, installed via `apt` rather than the project's own Docker
image) using two throwaway driver programs reproducing `CPYPROC.cbl`'s
exact structure; output matched the `.cut`'s expected values exactly
(`90.00` direct; `80.00` and order-count `1` through the caller). The
`MOCK PARAGRAPH` splice itself (test case 2) was not independently
re-verified against this specific fixture — that mechanism is already
proven end-to-end by `examples/flowmock`/`test_flow_mock_example.py`, and
splicing runs on the post-expansion source, so there is no
copybook-specific code path left to prove. Installing this project's own
`cobolparser` dependency (`git+https://github.com/Landparty/
cobol-parser.git@...`) was not possible in that sitting's sandbox — its
git access was scoped to `mocky-mock`/`mocky-mock-vscode` only. CI
(`.github/workflows/ci.yml`, credentialed via `COBOL_PARSER_PAT`) runs the
full suite, including the Docker/GnuCOBOL tier, against `tests/
integration/test_cpyproc_example.py` on push.
## 2026-07-29 — Feature: `mockymock mutate` (mutation testing v1)

New `mockymock/mutation/` package (`operators.py`, `runner.py`,
`report.py`) and `mutate` CLI subcommand — see
docs/2026-07-29-mutation-testing-design.md for the full design, operator
table, and deferred roadmap (coverage filtering, per-case targeting,
mutant schemata). v1 is a serial kill loop: text-level mutant generation
over the ORIGINAL source (conservative fail-toward-not-mutating rules;
boundary statements and terminators are never touched), then per mutant
the same static-check → splice → compile → run pipeline `run` uses, in
its own sandbox. Baseline must be green or the run aborts. Pinned by
`tests/unit/test_mutation_operators.py` (site discovery + the
integration fixture's exact mutant population) and Docker-gated
`tests/integration/test_mutation.py` (every mutant of
`mutation_target.cbl` classified as predicted: 5 killed, 1 deliberate
equivalent survivor — `stmt-delete` of `MOVE 0` masked by `VALUE 0` +
driver reset — plus the red-baseline refusal). Demo: `debug_spike.cut`
(no EXPECTs) scores 0% — 10/10 mutants survive — despite executing
every line; `mutation_target.cut` scores 83.3%. `.okf/cli.md` has the
subcommand entry.

## 2026-07-23 — Fix: Watch panel / hover / Debug Console showed "unsupported request: evaluate"

User report, with a screenshot: adding `WS-CLAIM-ID` to VS Code's Watch
panel while stopped at a breakpoint in `examples/claimseg/CLAIMSEG.cbl`
showed `unsupported request: evaluate` instead of a value. Root cause,
confirmed by reading `adapter.py`'s dispatch (`_dispatch` looks up
`_handle_<command>` via `getattr` and falls through to a generic failure
when missing): `DapAdapter` never implemented an `evaluate` handler.
`evaluate` is the one DAP request VS Code funnels the Watch panel,
hover-inspect, and the Debug Console through — none of them are a gdb
watchpoint (a genuine v1 non-goal per the design doc); this was simply an
unimplemented capability, not a scoped-out one.

Fix: new `_handle_evaluate` in `adapter.py`, added TDD-first
(`tests/unit/test_adapter.py::test_evaluate_reports_the_decoded_value_for_a_known_variable`
failed against `unsupported request: evaluate` before the handler
existed). Resolves `arguments.expression` against `session.variable_table`
and decodes via the same `read_variable` call `_handle_variables` already
uses — same read-only, identifier-only scope, no new gdb surface.
Arithmetic/member-access expressions fail cleanly with `unknown variable:
<expr>` rather than being silently misread. Full unit suite (752 tests)
green after the change. See `.okf/cli.md`'s `adapter.py` bullet.

## 2026-07-23 — Fix: Step Over appeared to loop on splicer-inserted statements

User report: "when I did a step over looks like it was looping" while
debugging `examples/claimseg/CLAIMSEG.cbl`. Root-caused empirically (not
by reasoning about GnuCOBOL codegen in the abstract) by driving the debug
session's internals directly against a real container and comparing raw
`GdbSession.step()` output to the DAP `stackTrace` position it produced at
each step.

Finding: `step()`'s coalescing predicate only checked that the stopped
frame was back in the instrumented `.cbl` file. But the splicer inserts
mock/driver statements (MOCK DLI bodies, test-case dispatch, tally/VERIFY
checks) into that same file, and those have no original-line counterpart.
Landing on one satisfied the old predicate, so `step()` returned there —
and `call_stack.py`'s `_resolve_frame` drops any frame it can't map back
to an original line, so `stackTrace` fell back to a stale caller frame (or
an empty frame list). Across several such statements in a row (confirmed:
5 consecutive Step Over clicks all reported the same `PERFORM` line), the
position VS Code displays never advances no matter how many times the
user clicks Step Over — reads exactly as an infinite loop, even though the
underlying program is progressing normally.

Fix: `GdbSession.step()` now takes an optional `is_visible_line` callable;
`adapter.py` always passes `line_map.to_original(line) is not None`, so
coalescing continues past invisible splicer-inserted statements until it
reaches one the user can actually see. Re-running the same empirical
repro after the fix: 9 real stop positions (15→19→20→24→25→16→30→31→36,
each with a valid original line and no repeats), down from 30 raw gdb
steps with 3 stuck-line stretches and 2 empty-frame stretches before the
fix. See `.okf/cli.md`'s `gdb_session.py` bullet.

Known limitation surfaced but not fixed here (flagged to the user, not
silently decided): "step over" still steps *into* a `PERFORM`'d paragraph
one statement at a time rather than skipping it as a unit — GnuCOBOL
compiles `PERFORM` as a computed-goto, not a real C call, so plain
`-exec-next` can't skip it. True step-over would need a temp breakpoint at
the return site plus continue; bigger change, not attempted in this fix.

## 2026-07-22 — Interactive DAP debugger implemented (`mockymock debug`)

Implemented the design in `docs/2026-07-22-dap-debugger-design.md` per
`docs/superpowers/plans/2026-07-22-dap-debugger-cli.md`. The design doc's
own empirical questions (originally unverified — the Docker daemon was
unreachable when it was drafted) were all answered against a real
hardened container before any implementation code was written, and the
doc was revised in place with the findings. One finding changed the
architecture from what the doc originally sketched: gdb's own backtrace
is useless for a COBOL call stack (GnuCOBOL compiles PROCEDURE DIVISION
into one C function), so a new `call_stack.py` module walks GnuCOBOL's own
`frame_stack` instead — not scoped in the original six empirical
questions, found only once call stack synthesis was actually driven
against a real container (`frame_stack[0]` turned out to be a sentinel,
not a real caller).

New: `mockymock/debug/` (`gdb_session.py`, `line_map.py`,
`variable_map.py`, `call_stack.py`, `adapter.py`), `mockymock debug`
subcommand, `gdb`/`gdbserver` added to the toolchain Dockerfile,
`compile_source(debug=True)` / `docker_toolchain.start_gdb_session`. See
`.okf/cli.md`'s `mockymock debug` section for the full flow.

Verified end-to-end against the real container
(`tests/integration/test_debug.py`): breakpoint on an original `.cbl`
line (through the real splicer line map), stop, correct COBOL call stack,
correctly decoded COBOL-named variable values (`PIC X`, `COMP-3`, `COMP`),
coalesced stepping past generated-C plumbing lines. Not yet verified:
group items/`OCCURS`/`REDEFINES` in variable mapping, deeper
`PERFORM`/`PERFORM THRU`/`GO TO` control flow in call stack synthesis —
both flagged as a follow-up fixture pass in the CLI plan's Task 10, not
blocking this implementation.

## 2026-07-21 — Cross-OS install audit: pin verified pushed, Windows/macOS unit CI added

Requested audit: "make sure everything is super easy to install and get up
running on any OS." Findings, verified empirically rather than by reading
docs (per [[feedback-empirical-verification]]):

- **The install path itself already works, on Windows, end to end.** Both
  README-documented commands --
  `uv tool install --from . mockymock` and
  `uv tool install git+https://github.com/samdion1994/mocky-mock.git` --
  succeeded on a clean `uv tool uninstall` + reinstall, followed by
  `mockymock setup` (built the image, started the container) and
  `mockymock run examples/ordrproc/ORDRPROC.cbl --cut
  examples/ordrproc/ORDRPROC.cut` (both cases passed). The 2026-07-04
  Docker-only rewrite's Windows fixes (see [runtime](runtime.md)) hold up
  in practice, not just in the design doc -- at least on this one
  authorized machine.
- **`pyproject.toml`'s and `ci.yml`'s "NOT YET PUSHED" comments on the
  `cobolparser@4db8394` pin were stale.** Verified via `gh api
  repos/Landparty/cobol-parser/commits/4db8394...` (200, sha matches) and
  the successful installs above -- the commit has been pushed since the
  comments were written. Both comments corrected in place rather than
  left to keep scaring off the next reader into thinking the pin is
  broken.
- **The actual ceiling on "easy to install on any OS" is distribution,
  not engineering.** `gh repo view` confirms both `samdion1994/mocky-mock`
  and `Landparty/cobol-parser` are still private, and mockymock's runtime
  dependency is a git URL straight to the private cobol-parser repo (see
  [integration](integration.md)). No amount of OS-specific polish changes
  that a fresh installer needs GitHub credentials with read access to
  *two* private repos before `uv tool install` resolves at all. This is a
  product/distribution decision (keep private + document the auth step
  clearly vs. make cobol-parser public vs. a private package index vs.
  vendoring a snapshot), not a bug -- put to the user rather than decided
  unilaterally.
- **CI never verified any of this.** `.github/workflows/ci.yml` ran
  `ubuntu-latest` only, despite the Docker-only rewrite's whole premise
  being "fix chronic Windows failures." Added a `test-cross-platform` job
  (`windows-latest`, `macos-latest`, Python 3.13, `tests/unit` only --
  see [testing](testing.md#ci-githubworkflowsciyml)) as real, durable
  evidence rather than a one-off manual check. Deliberately does not
  attempt the Docker/GnuCOBOL integration tier on those runners:
  macOS GitHub-hosted runners have no reachable Docker daemon (the
  tier's own `@requires_docker` gate skips cleanly there), but
  Windows runners ship a *Windows-container* Docker Engine -- `docker
  info` can report a live daemon while still being unable to build/run
  the Linux `mockymock-gnucobol` image, which would fail loudly instead
  of skipping. Verified the new job would actually pass before adding it:
  ran `tests/unit` locally against the same editable
  `-e ../cobol-parser` setup CI uses, native Windows Python 3.14 --
  681 passed.
- **Fixed: every `.read_text()`/`.write_text()` call across
  `mockymock/cli/main.py`, `mockymock/cli/checks.py`, and
  `mockymock/runtime/docker_toolchain.py` now pins `encoding="utf-8"`.**
  Without it, Python resolves the platform's locale-preferred encoding
  (commonly a Windows code page, not UTF-8) for every read/write --
  `.cbl`/`.cut` source, `--json-report`/`--junit-xml`/`--coverage-json`/
  `--coverage-out`/`--trace-json` output, the Docker-container-produced
  gcov/trace files, and even `docker_toolchain._image_tag()`'s read of
  its own `Dockerfile` (whose content hash becomes the image tag --
  a decode/re-encode round-trip through the wrong codec could silently
  hash the identical file differently on Windows than on Linux/macOS,
  though the current all-ASCII Dockerfile doesn't yet trigger it). A
  program or `.cut` file with a non-ASCII byte (accented name in a
  comment, curly quote pasted from a spec doc) would previously decode
  identically on Linux/macOS (UTF-8 default) but differently -- or
  outright crash -- on Windows. Verified with the full local suite
  (`tests/unit`, 681 passed) plus a manual smoke test exercising every
  touched write path end to end against live Docker: `run` with
  `--json-report`, `--junit-xml`, `--coverage`/`--coverage-json`/
  `--coverage-out`, and `--trace`/`--trace-json` all together, plus
  `generate --output`.
- **One low-priority polish item noted, not fixed** (cosmetic, no
  product decision needed, just not worth the Dockerfile-content-hash
  churn without being asked): every `mockymock run` prints a
  `Warning: program compiled against libxml 212 using older 209` line
  from the Docker image's GnuCOBOL build on every single run, including
  passing ones -- harmless, but easy for a first-time user to mistake
  for something broken.

## 2026-07-21 — New worked example: REGNAVG (subscripted tables, REDEFINES, DIVIDE ROUNDED, --trace)

`examples/regnavg/` closes the gap that four features shipped earlier today
-- subscripted `.cut` `EXPECT`/`MOVE` targets, `REDEFINES` data items,
`DIVIDE ... GIVING ... ROUNDED`, and `run --trace` -- were each proven only
by unit/integration tests, never by a polished worked example (the
convention every other feature in this repo follows). `BEFORE-EACH`,
`MOCK PARAGRAPH`/`SECTION`, and `PROVIDER` were deliberately left out of
scope: each already has its own dedicated example (`taxfile`, `flowmock`,
`statelkup`), confirmed with the user rather than assumed, and the
README's own "one distinctive feature per example" convention argues
against a kitchen-sink program.

- **Program, revised mid-build**: originally one paragraph looping over
  both regions; changed to two paragraphs
  (`1000-CALCULATE-REGION-1-AVERAGE` / `2000-CALCULATE-REGION-2-AVERAGE`,
  one per region) after review caught that the single-loop version
  unconditionally recomputed *both* regions' averages on every `PERFORM`,
  so a "the untouched region reads back zero" check was passing because
  that run's own `DIVIDE` had just overwritten it with `0/3`, not because
  cross-case reset had run -- the check had zero power to catch a broken
  reset. With two paragraphs, each test case `PERFORM`s only one region's
  paragraph, so the *other* region's `WS-REGION-AVG` slot is genuinely
  untouched by that run, and reading it back is real proof reset happened.
  Verified the fix has teeth by deliberately asserting the previous case's
  leftover value and watching it fail against the real, correctly-reset
  `0000000` (see README). `CALL "LOGALERT"` is a real boundary that must
  be mocked in every case despite living inside an `IF`, since
  reachability is static, not data-flow (same lesson INVUPDT and CLAIMSEG
  already teach).
- **A stale local `cobolparser` install produced two false leads while
  building this, both root-caused rather than worked around:**
  1. A subscripted `DIVIDE ... GIVING` target and a subscripted `CALL ...
     USING` argument both appeared to fail to parse at a paragraph's top
     level. Root cause: `python -c "import cobolparser"` in this
     environment resolved to a non-editable install pinned at commit
     `c9a94999` (2026-07-10) -- eleven days stale, silently shadowing the
     editable `-e ../cobol-parser` sibling checkout via a leftover
     `site-packages/cobolparser/` directory that survived a prior
     uninstall (same root cause as the 2026-07-09 log entry below, now
     recurring). At that stale commit, `DIVIDE ... GIVING ...
     ROUNDED` regresses to today's already-documented phantom-`ROUNDED`-
     paragraph bug even on the *already-committed*
     `tests/integration/fixtures/divide_rounded.cbl` fixture -- meaning
     this bug was silently live in the local dev environment for
     anything invoked via bare `python`, not just this new example.
     Fixed by deleting the stale directory and reinstalling
     `--no-deps -e ../cobol-parser`; confirmed via
     `cobolparser.__file__` resolving into the sibling checkout, and via
     re-parsing `divide_rounded.cbl` (phantom paragraph gone). The full
     unit suite went from 679 passed / 2 failed to 681 passed / 0 failed
     on the same code with no other changes -- the 2 "failures" from the
     earlier `git stash` check (see [[project-mockymock-cobolparser-
     regression]] for the general pattern) were also this staleness, not
     a `main`-branch regression; the stash check couldn't catch it
     because stashing example files doesn't touch installed packages.
     That comparison was against the sibling checkout's `HEAD`, though,
     not the pin -- re-run against the isolated pinned-commit venv
     described below to be sure it wasn't yet another
     ahead-of-the-pin mirage: **681 passed / 0 failed there too**, plus
     `test_regnavg_example.py`, `test_divide_rounded.py`, and
     `test_trace.py`'s 10 Docker-backed integration tests, all green
     against the exact pin. Documented in [testing](testing.md)'s
     Gotchas section (new entry, distinct from the existing `uv tool
     install`-staleness one -- this one hits `import cobolparser`
     directly, no `PATH` binary involved).
  2. After fixing the environment, `DIVIDE ... GIVING <table>(n)
     ROUNDED` (subscripted target) parsed clean and the whole example
     went green -- tempting to call it the stale-parser artifact and move
     on. It wasn't, fully: the "fixed" environment was the sibling
     checkout's `HEAD` (`3eaf120`), **two commits ahead of the pin**
     (`4db8394`) `pyproject.toml`/`ci.yml` actually resolve. Diffing the
     two intervening commits directly (`git show`, not reasoned about)
     found `4917576` ("fix silent data loss in ... arithmetic clauses")
     is what actually adds subscripted-target support to `ADD`/
     `SUBTRACT`/`MULTIPLY`/`DIVIDE`'s `GIVING`/`TO`/`FROM` clauses -- the
     pinned `4db8394` only consumes `ROUNDED`, nothing about subscripts.
     Confirmed empirically in an isolated venv installed straight from
     the exact pinned commit
     (`pip install --no-deps "git+file:///../cobol-parser@4db8394..."`,
     avoiding any checkout of the shared sibling working tree): a
     subscripted `GIVING` target genuinely still warns `PARSE_WARNING`
     at the pin. Reverted the `.cbl` to target an unsubscripted scratch
     field (`WS-REGION-AVG-SCRATCH`) and `MOVE` it into the table cell --
     re-verified clean (`lint`, `run`, both broken-expectation checks,
     and a re-captured `--trace`) against that same pinned-commit venv,
     not the racier sibling `HEAD`. `CALL ... USING <table>(n)`
     (subscripted argument) independently still doesn't parse outside a
     `PERFORM VARYING` body at every commit tested, pin included -- a
     real, separate, still-open gap; the `CALL` never takes the average
     as an argument at all now. Neither gap is fixed here (that's
     cobol-parser work, a sibling repo, out of scope for adding an
     example) -- both are documented inline in `REGNAVG.cbl`'s header
     comment and the README rather than silently avoided. Lesson for next
     time: "the sibling checkout now agrees with my change" is not the
     same claim as "the pinned dependency does" -- verify against the
     exact pinned commit specifically before trusting a green result
     that depends on cobolparser behavior, the same discipline
     [[project-mockymock-cobolparser-regression]] already asks for.
- **Rounding is proven, not assumed**: region 2's `50.00 + 50.00 + 51.10 =
  151.10`, `/ 3 = 50.3666...` -- `ROUNDED` must read back `50.37`. A new
  integration test
  (`tests/integration/test_regnavg_example.py::test_regnavg_fails_when_rounded_expectation_is_truncated`)
  asserts the truncated `50.36` expectation actually fails against real
  GnuCOBOL, mirroring `test_divide_rounded.py`'s existing load-bearing
  check. A second new test,
  `test_regnavg_fails_when_a_stale_redefines_value_is_asserted`, is the
  committed version of the two-paragraph reset proof above: asserting
  case 2's leftover `50.37`/`"0005037"` in case 3 (instead of the
  correctly-reset `0`/`"0000000"`) must fail -- and does.
- All three cases verified end-to-end against real GnuCOBOL in Docker
  (with the corrected `cobolparser` installed), including a captured
  `run --trace` output pasted into the README (real CLI output, not
  hand-written) and both deliberately-broken-expectation proofs above.
- Also updated: `README.md`'s Examples table; `.okf/testing.md`'s
  frontmatter description, worked-examples section (added a `##
  REGNAVG` write-up matching the existing six; also surfaced, while
  editing that section, that `flowmock`/`taxfile`/`statelkup` never got
  their own write-up there -- a pre-existing gap, not fixed here beyond
  noting it), and Gotchas section (the stale-`cobolparser` entry above).

## 2026-07-21 — `EXPECT` and `MOVE` support subscripted table data-names

`_EXPECT_RE` and `_MOVE_RE` in `mockymock/dsl/parser.py` captured their
data-name/target as plain `\S+`, so `EXPECT WS-TABLE(1, 1) TO BE 100`
(idiomatic COBOL, space after the comma), `WS-TABLE(1 1)` (space-separated
subscripts), and `MOVE 100 TO WS-TABLE(1, 1)` all failed to parse — only
the no-space `WS-TABLE(1,1)` form matched, and the line fell through to
`CutParseError: unrecognized statement` otherwise. Confirmed empirically
with a standalone regex test before touching code.

Fixed by extracting a shared `_SUBSCRIPTED_NAME` fragment that accepts one
non-nested `(...)` group after an identifier, falling back to the original
`\S+` for non-identifier tokens — the fallback specifically preserves
parsing of a literal `{Placeholder}` data-name/target in a
`PROVIDER`-templated `TESTCASE` (data-names and MOVE targets are
deliberately never substituted; see `dsl.md`'s `PROVIDER` section), which
the first regex draft (EXPECT-only) broke
(`test_placeholder_substitution_scoped_to_move_and_expect_values_only`).
Nested parens (`TABLE(FUNCTION MOD(I 3))`) and qualification (`A OF B`)
remain unsupported and still fail closed rather than mis-parsing.
`PERFORM`'s target stays plain `\S+` — a paragraph/section name is never
subscripted, so it wasn't touched.

Added regression tests in `tests/unit/test_dsl_parser.py` (comma+space,
space-separated, no-space, plain name, unbalanced-paren-still-raises, for
both EXPECT and MOVE, plus a case with subscripts on both sides of a
single MOVE) and `tests/unit/test_json_report.py` (a subscripted
data-name failure round-trips through the driver's DISPLAY text back to
its own `.cut` line via `_attribute_failure`). Full existing suite still
green except 6 pre-existing failures unrelated to this change (confirmed
via `git stash` against `main`).

See [dsl.md](dsl.md).

## 2026-07-21 — DIVIDE/MULTIPLY `GIVING ... ROUNDED` fixed upstream in cobolparser

`ROUNDED` after `GIVING` on `DIVIDE`/`MULTIPLY` was silently dropped by
cobolparser's `_parse_binary_arithmetic` (only `ON`/`NOT ON SIZE ERROR`
were recognized after `GIVING`) and the leftover `ROUNDED` token was
misread as a phantom paragraph literally named `ROUNDED`, silently
reparenting every statement after it in the real paragraph. Confirmed
this has real end-to-end impact, not just cosmetic AST noise: a `MOCK
CALL` placed right after a `ROUNDED` `DIVIDE` in the same paragraph was
refused (`UNMATCHED_MOCK`, "does not match any boundary site reachable
from '<paragraph>'") because mockymock's reachability BFS no longer saw
the CALL as belonging to that paragraph.

Fixed in cobol-parser (commit `4db8394`, local — not yet pushed to
`Landparty/cobol-parser`): `_parse_binary_arithmetic` now consumes
`ROUNDED` (with or without a preceding `GIVING`) and records it on a new
`ArithmeticStatement.rounded` field. `pyproject.toml` and
`.github/workflows/ci.yml` are both bumped to the new commit **but it
is not yet pushed** — `uv tool install` and CI will fail to resolve this
ref until the cobol-parser commit is pushed to its remote.

Proven end-to-end against real GnuCOBOL in
`tests/integration/test_divide_rounded.py`: `5 / 2 GIVING ... ROUNDED`
must produce `3` (rounds half up), not `2` (truncated) — a second test
asserts the wrong (truncated) expectation actually fails, so the
assertion is load-bearing rather than trivially green. ADD/SUBTRACT have
the same class of bug in their own (separate) GIVING branches; left
open, not fixed here — see cobol-parser's `arithmetic_parsers.py`.

## 2026-07-21 — `run --trace`: execution trace for debugging one case

Adds `mockymock run --trace` / `--trace-json PATH`, backing a "Debug Test"
action in the VS Code extension (extension side not yet built; this is the
CLI half, and the JSON contract is the seam between them). Design:
`docs/2026-07-21-debug-trace-design.md`; plan:
`docs/superpowers/plans/2026-07-21-debug-trace-cli.md`.

Verified in-container before designing, not assumed: `cobc -ftraceall`
alone emits **nothing** — GnuCOBOL 3.x gates tracing at run time on
`COB_SET_TRACE=yes`. `COB_TRACE_FILE` sends it to its own file, which is
what keeps the `__MOCKYMOCK__` stdout protocol clean, and
`COB_TRACE_FORMAT='%P|%S|%L'` makes it parseable.

- **Two channels, because one mapper destroys the other.** The executed
  path reuses [report](report.md)'s coverage remap, which deliberately
  drops splicer-inserted lines ("which of MY lines ran"). But the mock
  dispatch blocks *are* splicer-inserted, so mock firing order can never
  come from the trace file. It comes instead from a new trace-mode-only
  `__MOCKYMOCK__ MOCK: <label> <key>` DISPLAY in
  [splicer](splicer.md)'s `build_site_dispatch` and `build_flow_dispatch`,
  landing between the driver's CASE START/END markers so per-case
  attribution is free.
- **`--trace` refuses unless exactly one `--case` and no `--tag`.** The
  suite runs as a single binary and the trace stream carries no case
  markers, so an unscoped trace cannot be attributed. Refusal fires before
  static checks and before Docker.
- **New `report/trace.py`**; `coverage.py` grew
  `build_original_line_map`, extracted from `map_coverage_to_original` so
  both consumers share one alignment instead of duplicating difflib logic.
- Flow (`MOCK PARAGRAPH`/`SECTION`) mocks emit markers too — a timeline
  omitting declared flow mocks would be quietly incomplete.
- Each marker names the directive key, not just the site verb: `OPEN
  PURGEIN` vs `OPEN PURGRPT`. Caught by reading real output, where the
  first version rendered two indistinguishable `OPEN`s.
- Proven end-to-end against real GnuCOBOL in
  `tests/integration/test_trace.py` (ACCTPRG), including that every
  reported line is a non-blank, non-comment line of the ORIGINAL `.cbl`
  and that the traced run's verdict matches an untraced one.

## 2026-07-21 — Doc sync: README + OKF concepts for BEFORE/FILE-STATUS/PROVIDER wave

A code review found the README and three OKF concepts had fallen behind
the merge below (`6f6786e`), which shipped `BEFORE-EACH`/`BEFORE-ALL`,
`FILE-STATUS IS`, and (from an earlier merge) `PROVIDER`. This entry is
docs-only -- no production code changed.

- **README.md** DSL bullet list: added `BEFORE-EACH`/`BEFORE-ALL` (block
  placement, `END-BEFORE`, precedence) and `FILE-STATUS IS` (eligible
  categories, mnemonic table, implicit default-success `MOVE "00"`)
  bullets ported from [dsl](dsl.md), matching the list's existing tone.
  Both README and [dsl](dsl.md) now state explicitly that `BEFORE-ALL`/
  `BEFORE-EACH` differ **only** in override precedence, not execution
  timing, despite the xUnit-style names.
- **[analysis](analysis.md)**: `check_test_case`'s documented signature
  refreshed to its actual 4th parameter, `file_status_fields` (from
  `mock_surface.analyze_file_status_fields`); added the
  `UNRESOLVED_FILE_STATUS_TARGET` refusal (a `MOCK ... FILE-STATUS IS`
  must target a file whose `SELECT` declares `FILE STATUS IS <field>`,
  else it refuses fail-closed) to both the module table and the
  per-test-case checks section.
- **[cli](cli.md)**: refreshed the `_cmd_run` flow's `check_test_case`
  and `splice_program` call shapes to their current arities
  (`file_status_fields` threaded through both, plus `splice_program`'s
  `terminator_plans`/`flow_plans` params), matching
  `mockymock/cli/checks.py` and `mockymock/cli/main.py`.
- **[splicer](splicer.md)**: documented `build_site_dispatch`'s
  FILE-STATUS default-success/override injection -- an implicit
  `MOVE "00" TO <field>` before a mocked file-op's body whenever the file
  declares a `FILE STATUS` field, followed by an explicit
  `MOVE "<code>"` when the directive used `FILE-STATUS IS` sugar (which
  wins by ordering, not by branching).
- Timestamps bumped on `analysis.md`, `cli.md`, `splicer.md` (already
  current on `dsl.md`, itself only gaining the one clarifying sentence
  above).

## 2026-07-21 — PROVIDER blocks fail closed on stray statements

- **Bug fix** ([dsl](dsl.md)): `dsl/parser.py` never reset the current
  `TESTCASE`/`BEFORE-*` state when a `PROVIDER` block opened, and only
  `TESTCASE`/`PROVIDER`/EOF closed it. A statement placed between/after
  `ROW` lines while a `PROVIDER` was open silently attached to whichever
  `TESTCASE`/`BEFORE-*` block was open *before* the `PROVIDER`, with any
  `{Placeholder}` left unsubstituted -- and a `BEFORE-EACH`/`BEFORE-ALL`
  appearing after an intervening `END-BEFORE` would still leak `ROW` lines
  into the earlier `PROVIDER`. Fixed fail-closed: opening `PROVIDER` now
  clears `case`/`mock_target`, and while a `PROVIDER` is open only
  `HEADER`/`ROW`/blank/`*>` lines are accepted -- everything else
  (`MOVE`/`PERFORM`/`EXPECT`/`VERIFY`/`MOCK`/`BEFORE-ALL`/`BEFORE-EACH`)
  raises `CutParseError` naming the offending line.
- New tests in `tests/unit/test_dsl_parser.py`:
  `test_stray_move_inside_open_provider_raises`,
  `test_stray_mock_inside_open_provider_raises`,
  `test_row_after_intervening_before_each_block_raises`,
  `test_statelkup_example_still_parses` (regression pin for
  `examples/statelkup/STATELKUP.cut`, the canonical real-world
  `PROVIDER`/`HEADER`/`ROW` usage).

## 2026-07-21 — malformed FILE-STATUS lines now fail closed at parse time

- **Bug fix** ([dsl](dsl.md)): `dsl/parser.py`'s `_FILE_STATUS_RE` only
  matches well-formed `FILE-STATUS IS <mnemonic>` / `FILE-STATUS IS "xx"`
  lines. Previously, any mock-body line that started with the
  `FILE-STATUS` keyword but didn't fully match (an unquoted numeric code
  like `FILE-STATUS IS 92`, a digit-bearing mnemonic like `FILE-STATUS IS
  EOF10`, or a missing value) silently fell through to `body_lines` and was
  spliced verbatim into the generated COBOL, surfacing as a confusing
  `cobc` compile error pointing at generated code instead of the offending
  `.cut` line. Fixed with a new `_FILE_STATUS_PREFIX_RE` word-boundary
  check: any such line now raises `CutParseError` at parse time naming the
  accepted forms (the mnemonic table or a quoted two-character literal).
  Tests added in `tests/unit/test_dsl_parser_file_status.py`.

## 2026-07-21 — Docker verification of the BEFORE/FILE-STATUS/PROVIDER wave; ACCTPRG coverage pin refreshed

- The full integration suite ran against real GnuCOBOL in Docker for the
  first time since the `feature/before-blocks-and-file-status` merge
  (`6f6786e`) — the merge had been unit-test-only because Docker was
  unreachable that session. Result: everything green, including
  `test_taxfile_example.py` (BEFORE-EACH + FILE-STATUS IS) and
  `test_statelkup_example.py` (PROVIDER rows), closing the disclosed
  verification gap.
- The one anticipated casualty,
  `test_realworld_acctprg_example.py::test_committed_acctprg_example_reports_coverage`,
  failed exactly as its breadcrumb comment predicted: the implicit
  default-success `MOVE "00" TO WS-PURGEIN-STATUS` injection added 8
  executable (and executed) lines to ACCTPRG's spliced output. Re-pinned
  `81.13% (460/567)` → `81.39% (468/575)`; not a regression.
- Gotcha re-confirmed (see [testing](testing.md) Gotchas): the global
  `uv tool install`-ed `mockymock` CLI had gone stale again — its parser
  predated BEFORE-EACH/PROVIDER entirely. Refreshed via
  `uv tool install --from . mockymock --force`. The sibling
  `mocky-mock-vscode-extension`'s `.cut` TextMate grammar still has no
  highlighting for `BEFORE-EACH`/`BEFORE-ALL`/`FILE-STATUS IS`/
  `PROVIDER`/`HEADER`/`ROW` (open follow-up in that repo).

## 2026-07-21 — BEFORE-EACH/BEFORE-ALL mock scoping and FILE-STATUS IS sugar

- **New `.cut` grammar** ([dsl](dsl.md)): `BEFORE-EACH`/`BEFORE-ALL` blocks
  (at most one of each per `TESTSUITE`, appearing after the `TESTSUITE`
  header and before the first `TESTCASE`, `MOCK`-only bodies) desugar
  entirely inside `dsl/parser.py` at parse time into every `TESTCASE`'s own
  `mocks` list — no other module ever learns the blocks existed. Precedence
  on a `(category, key)` collision is `TESTCASE` > `BEFORE-EACH` >
  `BEFORE-ALL`, silently. `FILE-STATUS IS <mnemonic-or-code>` is new sugar,
  usable once inside a `MOCK OPEN|CLOSE|READ|DELETE|START|UNLOCK` body (not
  `WRITE`/`REWRITE`): a fixed mnemonic table (`SUCCESS`, `END-OF-FILE`,
  `DUPLICATE-KEY`, `RECORD-NOT-FOUND`, `FILE-NOT-FOUND`, `ALREADY-OPEN`,
  `NOT-OPEN`, `NO-CURRENT-RECORD`) or a quoted two-character literal
  resolves to `MockDirective.file_status`. Every eligible category also
  gets an implicit `MOVE "00"` (default success) before the mock's own
  body whenever the target file declares a `FILE STATUS` field, whether or
  not `FILE-STATUS IS` is used (codegen in `injector.build_site_dispatch`).
- **New refusal** ([analysis](analysis.md)): `UNRESOLVED_FILE_STATUS_TARGET`
  in `refusal.check_test_case` — a `MOCK` using `FILE-STATUS IS` must
  target a file whose `SELECT` declares a `FILE STATUS IS <field>` clause
  (resolved via a new `mock_surface.analyze_file_status_fields` analysis);
  otherwise there is no WORKING-STORAGE field to move the status into, and
  the program refuses fail-closed rather than silently dropping the
  directive.
- Both features compose by construction — a desugared `BEFORE-EACH`/
  `BEFORE-ALL` directive with `file_status` set flows into a `TESTCASE`'s
  `mocks` list exactly like any directive written directly on a
  `TESTCASE`, and both the refusal and the codegen read
  `directive.file_status` the same way regardless of origin — now proven
  by a direct test
  (`tests/unit/test_dsl_parser_before_blocks.py::test_file_status_is_inside_before_each_survives_desugaring`).
- See docs/2026-07-20-before-blocks-and-file-status-design.md and
  `examples/taxfile/`.

## 2026-07-20 — Flow-target mocks: `MOCK PARAGRAPH` / `MOCK SECTION`

- **New mock categories PARAGRAPH/SECTION** ([dsl](dsl.md), [analysis](analysis.md),
  [splicer](splicer.md)): the first non-boundary mocks — they replace an
  internal paragraph's/section's whole body for the mocking case while
  every other case still runs the real code. Implemented as a
  header-line-only splice (`analysis/flow_mocks.py` plans it,
  `injector.build_flow_dispatch` + `orchestrator.splice_program`'s new
  `flow_plans` parameter emit it): the header becomes an
  `EVALUATE UT-CURRENT-CASE` dispatch whose `WHEN OTHER` performs the
  relocated real body (`UT-REAL-<n>[-<KEY>]`), which keeps every body
  line at its original line number so all other span-based splices
  (boundary dispatch, terminator neutralization, chain checks) stay
  valid. Reachability now takes a `skip_traversal` set so boundaries/
  terminators inside a mocked body need no mocks for that case. New
  refusals: UNRESOLVED_FLOW_MOCK_TARGET, UNSUPPORTED_FLOW_MOCK_TARGET
  (GO TO target, THRU-range membership, GO-TO fall-through, paragraph
  inside a performed SECTION, shared-line header, own entry point) —
  fail-closed against every entry path that isn't PERFORM-through-the-
  header. Verified end-to-end in the container (including
  `VERIFY PARAGRAPH ... WAS PERFORMED 3 TIMES` under
  `PERFORM ... 3 TIMES`); see
  docs/2026-07-20-paragraph-section-mocks-design.md,
  `examples/flowmock/`, `tests/unit/test_flow_mocks.py`,
  `tests/integration/test_flow_mock_example.py`.

## 2026-07-19 (cobol-parser pin bump: out-of-line PERFORM VARYING)

* **CI pin bumped** (`.github/workflows/ci.yml` + the matching
  `pyproject.toml` git pin): `392f8ce` → cobol-parser main `d70b8a7`, to
  pull in out-of-line `PERFORM ... VARYING` parsing (upstream `59a016c`).
  At the old pin the VARYING clause was dropped with an "Unparsed token"
  content-drop warning and the PERFORM mistagged `SIMPLE`, failing the
  three VARYING tests (`test_refusal.py`, `test_terminators.py`, and
  `test_terminator_support.py`'s Docker-gated case) — they were written
  against the fixed parser but the pin was never bumped, which is why
  main's CI went red between runs 74 and 75. Verified at the new pin:
  tests/unit 484 passed locally against an editable checkout of
  `d70b8a7`. Debugging note for the next agent: a plain
  `pip install -e .` (without `--no-deps`) installs the *pyproject-pinned*
  cobolparser into site-packages, and its package directory shadows the
  editable sibling checkout even after `pip uninstall cobolparser` — the
  stale `site-packages/cobolparser/` directory must be deleted by hand.
  That shadowing initially masqueraded as an upstream parser regression
  on cobol-parser main; there is none.

## 2026-07-19 (FAIL lines now show actual values)

* **Assert-message gap closed** ([splicer](splicer.md), driver): generated
  `CASE NNN FAIL` lines only restated the expectation (`expected
  WS-NET-AMOUNT = 85.00`, `VERIFY CALL DISCRATE WAS CALLED 2 TIMES`) with
  no hint of what actually happened -- even though the MVP plan and
  `tests/unit/test_report.py` sample outputs always modeled the
  `..., got <actual>` format. `build_driver` now appends `, got ` plus the
  data item to EXPECT failures and `, got <n>` to VERIFY failures, where
  `<n>` is the tally routed through a new shared `UT-TALLY-EDITED`
  scratch field (`PIC Z(8)9`, declared only when the suite has any
  VERIFY) and `FUNCTION TRIM`med so counts print as `1`, not
  `000000001`. EXPECT actuals display in the field's own PIC formatting
  (e.g. `got 00090.00` for a PIC 9(5)V99) -- the driver cannot know the
  field's picture, so no reformatting is attempted. Report parsing is
  unaffected (`_CASE_FAIL_RE` captures the reason as free text) and
  existing substring assertions in tests still match since the new text
  is appended. Verified end-to-end with a local `cobc -free` compile+run
  of a deliberately failing ORDRPROC suite.
* **Coverage pins re-baselined** ([coverage](coverage.md)): the committed
  real-world coverage numbers shift because each VERIFY now contributes
  one (uncovered, fail-path-only) `MOVE <tally> TO UT-TALLY-EDITED` line
  and the `UT-TALLY-EDITED` declaration's initialization counts as one
  covered line: ACCTPRG `81.82% (459/561)` → `81.13% (460/567)`
  (CI-observed), DEPTIMSM `76.30% (692/907)` → `75.90% (693/913)`. The
  two coverage tests now regex-extract the actual coverage line before
  comparing, so a future mismatch's failure message shows the actual
  value instead of a page of captured stdout.

## 2026-07-18 (examples discoverability + two new worked examples: CUSTPROG, CLAIMSEG)

* **Documentation gap closed**: the top-level `README.md` had no `##
  Examples` section at all -- it showed one inline `.cut` snippet and
  never linked to any `examples/` subdirectory, so a newcomer reading only
  the README couldn't discover `invupdt`/`ordrproc`/`custinq`/`raterte`/
  `real-world`/`nist-cobol85` existed. Added an Examples table. Separately,
  `examples/real-world/` (ACCTPRG, DEPTIMSM, DEPTMQC, DEPTMQP) had zero
  READMEs despite [testing](testing.md) and [cli](cli.md) both pointing to
  "their own READMEs" -- added `examples/real-world/README.md` covering
  all four, the required `--copybook-path` flag, and a runnable
  `--coverage` demo against DEPTIMSM (confirmed still reports 76.30%
  lines executed, 692/907).
* **New example**: `examples/custprog/` elevates
  `tests/integration/fixtures/sql_cursor_example/` (COBOL/`.cut` copied
  unchanged, proven identical output) into a documented example. Closes
  the gap that `MOCK SQL "..." ROWS (...)` cursor-fetch sugar and
  DCLGEN-style `EXEC SQL INCLUDE <member>` (non-`SQLCA`, via
  `--copybook-path`) were each proven only by that one regression fixture,
  never by a polished `examples/` program.
* **New example**: `examples/claimseg/` -- a new hand-written program
  (`CLAIMSEG`, raw `EXEC DLI GU`/`ISRT` claim-retrieval-and-payment-insert)
  proving `MOCK DLI` end-to-end for the first time. `MockCategory.DLI` has
  been classified since the v2 all-boundaries design but was previously
  exercised only by unit tests -- the same "classified but never proven"
  gap `EXEC CICS` had before `examples/custinq` closed it. 5 test cases,
  including a static-reachability-driven-refusal case mirroring INVUPDT's
  unreached-`WRITE` lesson, and a `GOBACK`-neutralization case via the
  real `0000-MAIN` entry point. Both new examples compiled and ran green
  against real GnuCOBOL in Docker via the local dev checkout (note: the
  globally `uv tool install`-ed `mockymock` on `PATH` is a stale build
  that predates the `ROWS` feature -- don't use it to validate against
  current source; invoke `mockymock.cli.main.main()` from the checkout,
  or reinstall, instead).
* Updated [testing](testing.md)'s worked-examples section and frontmatter
  description to list CUSTPROG and CLAIMSEG alongside the original four.
* **Stale-global-CLI caveat above, resolved**: verifying the new
  `mockymock-vscode` extension (`../mocky-mock-vscode-extension/`, built
  today) drove all 14 `examples/**/*.cut` suites through the exact
  invocation the extension's Test Controller uses (`mockymock run <cbl>
  --cut <cut> --junit-xml <path> --copybook-path <dir>...`). Against the
  globally `uv tool install`-ed `mockymock` on `PATH`, 3 of 14 failed:
  `CUSTPROG` (the `ROWS` grammar noted above wasn't recognized -- confirms
  the caveat), plus two more the caveat didn't call out —
  `ACCTPRG` (spurious `refused (UNMATCHED_MOCK)` on `CLOSE
  PURGEIN`/`PURGRPT`) and `DEPTIMSM` (1 of 20 cases crashed on the
  real-entry-point `GOBACK` case). All three passed when invoked in-process
  from the checkout, confirming the global binary — not the examples or the
  extension — was stale. Fixed by `uv tool install --from . mockymock
  --force` (also picked up a `cobolparser` bump, 1.1.0 -> 1.2.0); re-ran
  all 14 suites against the refreshed `PATH` binary and all pass (58 cases,
  0 failures, 0 errors). Anyone re-validating the worked examples against a
  pre-existing `uv tool install` should reinstall first rather than
  trusting a stale global shim.
* `mockymock-vscode`'s already-`.vsix`-packaged/installed build (commit
  `b2432fc`) predated a same-day Windows-specific fix round (`870c9b0`:
  Docker-not-installed detection under `shell:true`+cmd.exe, argument
  quoting for paths with spaces, re-verifying the CLI after a `uv tool
  install`). Rebuilt (`npm run package`) and reinstalled
  (`code --install-extension --force`) from current HEAD (`93ccec0`) so the
  installed extension actually has those fixes.

## 2026-07-17 (coverage reporting: --coverage/--coverage-out, DEPTIMSM example)

* **New feature**: `mockymock run --coverage` compiles with GnuCOBOL's
  native `--coverage` flag (builds on gcc's gcov, since `cobc` transpiles
  COBOL to C) and reports per-line coverage of the instrumented source
  after the run; `--coverage-out PATH` writes the full report to a file.
  New `runtime/docker_toolchain.py` `run_gcov` + `GcovResult`; new
  `report/coverage.py` (`parse_gcov`/`format_coverage_console`); no new
  Dockerfile/dependency changes (`gcc`/`gcov` already present in the
  `mockymock-cobc` image). See `docs/2026-07-17-coverage-reporting-design.md`
  and the new [coverage](coverage.md) OKF concept.
* **New example**: `examples/real-world/DEPTIMSM/` (IMS MPP deposit
  transaction, IMS DL/I via `CALL 'CBLTDLI'`) — 20 test cases including
  one driving the real `0000-MAIN-PROCESS` entry point to `GOBACK`
  end-to-end, proven against real GnuCOBOL in Docker. First real-world
  proof this repo's 17-program `legacy-application/cobol/` corpus can go
  beyond `mockymock generate`'s parse-only sweep to an actual
  compile-and-run — 3 of 17 corpus programs (`ACCTPRG`, `DEPTMQP`,
  `DEPTMQC`, now `DEPTIMSM`) are proven end-to-end; the remaining 13 are
  explicit, named follow-up work, not attempted here.
* **Coverage numbers are lower than "every branch exercised" would
  suggest, and that's expected**: `DEPTIMSM`'s 20-case suite hits every
  real branch (verified by hand while writing it) yet reports 76.30%
  (692/907) — see the design doc's addendum and the new `coverage.md`
  concept for why (driver dead-fail branches, terminator-neutralization
  guard branches, and — the largest source — the splicer's per-boundary-
  site mock dispatch emitting one `WHEN` branch per test case sharing a
  mock key, most structurally unreachable from any single case's own
  `PERFORM` target). `ACCTPRG`'s existing, unmodified suite reports
  81.82% (459/561) under the same feature, proving it composes with a
  suite written years before coverage reporting existed.

## 2026-07-17 (corpus re-sweep back to fully clean: cobolparser VALUE ALL fix pin, corpus col-72 fixes, walking_skeleton fixture fix, .CBL sweep coverage)

* **Pin bumped** `b3e81ed` → `392f8ce` (cobol-parser branch
  `claude/cobol-parser-mocking-cq2wse`, on top of the previous pin) in
  `pyproject.toml` and the CI sibling checkout `ref:`. Brings in
  `VALUE ALL <literal>` data-item clause support: `ALL` lexes as a
  figurative constant, so the old `parse_value_clause` consumed it as a
  complete value and dropped the repeated literal as an "Unparsed token"
  content-drop warning — which our PARSE_WARNING gate correctly refused
  on `legacy-application/cobol/EODPROC.cbl`'s
  `05 FILLER PIC X(133) VALUE ALL '='.` separator. New shape:
  `value_clause='ALL "="'`, which `splicer/reset.py` splices as legal
  COBOL (`MOVE ALL "=" TO <item>`). Upstream regression suite:
  `tests/regression/test_value_all_clause.py`.
* **Corpus fixes (sibling legacy-application repo, same branch)**:
  removed the invalid `INDICATOR IS` data clause from `ACCTMNT.cbl` and
  fixed ten column-72 truncation sites across `ACCTMNT.cbl`,
  `CTRRPT.cbl`, `EODPROC.cbl`, and `copybook/MQMSG.cpy` — several were
  fully silent (no warning): EODPROC's SQL `SUM(CASE ...)` tails,
  ACCTMNT's `DISPLAY` operand truncated to an undeclared name, and two
  sentence periods at column 73.
* **Fixture fix**: `tests/integration/fixtures/walking_skeleton.cbl`
  line 7 was 80 chars, clipping the CASE-marker string's closing quote
  at column 72 (the 2026-07-14 log flagged this as cosmetic; it became a
  PARSE_WARNING refusal in `generate` once the lexer started warning on
  unterminated literals). Display text shortened;
  `test_walking_skeleton.py` only asserts on the marker prefix.
* **Sweep coverage fix**: `scripts/corpus_sweep.py` now also globs
  `examples/**/*.CBL` — `rglob` is case-sensitive on Linux, so the four
  NIST CCVS85 examples were silently missing from Linux sweeps. This
  also confirms the 2026-07-14 follow-up flag on `IC101A`/`IC116M`
  (VALUE-literal-on-next-line parsed as `None`) is resolved at the new
  pin: all four NIST examples generate clean.
* **Re-sweep result** (`docs/corpus-sweep-report.md`, new top section):
  34/34 programs parse OK and generate exit 0, zero refusal codes, zero
  unmockable-boundary categories.

## 2026-07-14 (cobolparser pin bump: legacy-corpus boundary fixes, REPLACE/COPY pseudo-text, all-459 NIST; UNRESOLVED_COPYBOOK adapter)

* **Pin bumped** `d2bc7c2` → `b130ec8` (cobol-parser branch
  `claude/mockymock-cobol-parser-readiness-bcn267`, on top of the previous
  pin) in `pyproject.toml` and the CI sibling checkout `ref:`. Brings in:
  clause-continuation keyword (`DELIMITED`, `TALLYING`, ...) + SQL special
  register (`SQLCODE`/`SQLSTATE`) exclusions in
  `looks_like_paragraph_boundary` — the two false-boundary shapes the
  legacy-application corpus sweep surfaced; the `REPLACE`
  compiler-directing statement + un-expanded `COPY ... REPLACING`
  pseudo-text stripping; and comment-entry-aware division boundaries. All
  459 NIST CCVS85 programs parse error-free at this pin (upstream
  `KNOWN_ISSUES` is empty).
* **Behavior change adapted in `analysis/refusal.py`**: cobolparser now
  blanks un-expanded COPY statements before lexing and reports each as a
  structured `COPY <member> not expanded` warning (previously: silent
  empty data-item list). `check_whole_program` skips exactly that warning
  so the dedicated, textual `check_unresolved_copybooks` (run on the same
  raw source by every CLI path) surfaces the actionable
  `UNRESOLVED_COPYBOOK` code instead of a generic `PARSE_WARNING`
  burying it. Fail-closed is preserved — the same condition still refuses.
* This pin bump also caught (and upstream reverted) a cobolparser
  boundary-lookahead change that truncated `COMPUTE X =` /
  continuation-line operand shapes when the operand's name lives in an
  un-expanded copybook — `tests/integration/test_copybook_expansion.py`
  was the detecting suite.
* Local suite at this pin: 471 passed, 48 skipped (Docker-gated skips);
  the 3 `mockymock run` CLI tests that need a live Docker daemon run in
  CI.

## 2026-07-10 (Fix: cobolparser pin bump closes ACCTPRG/looping-PERFORM silent-drop; statement_span blank-line trim)
* **Root cause, confirmed empirically, not guessed**: at the previously-pinned
  cobolparser commit (`8c3c881d`), a period-less out-of-line
  `PERFORM x UNTIL cond` immediately followed by another statement (legal
  COBOL -- no period required between statements sharing a sentence) silently
  dropped **every statement after it** from the enclosing paragraph, with
  zero `PARSE_WARNING`. Reproduced directly against the parsed AST (the
  trailing statements were simply absent from `paragraph.statements`), not
  inferred from symptoms. This broke two things sharing the one root cause:
  `examples/real-world/ACCTPRG`'s "runs end-to-end via its real entry point"
  test case (lost `PERFORM 3000-FINALIZE` + `GOBACK`, so its `CLOSE
  PURGEIN`/`CLOSE PURGRPT` mocks became `UNMATCHED_MOCK`) and
  `tests/unit/test_terminators.py::test_looping_perform_is_excluded_from_the_safe_chain`.
* **Fix**: bumped the pin (`pyproject.toml` dependency +
  `.github/workflows/ci.yml`'s `ref:`) from `8c3c881d` to cobolparser
  `origin/main`'s tip `c9a94999` (released as cobolparser 1.2.0), which
  includes upstream commit `7405700` ("H9: missing period absorbs following
  paragraph header") — the actual fix. Verified by bisecting each
  intermediate commit against the real, reinstalled package (not a
  `sys.path` source shim) before adopting: `acc0842` (an earlier point that
  already included the `b54348e` silent-drop fix from the same PR) still
  failed both tests; `7405700` fixed both with no new regressions at that
  point. Chose `origin/main`'s tip over the local `cobol-parser` checkout's
  further-ahead `HEAD`, which had 14 additional unpushed/uncommitted-local
  commits from concurrent work in that sibling repo -- origin/main is the
  shared, released, reproducible-by-CI state.
* **Mockymock-side fix, surfaced by the same bump**: cobolparser's
  `normalize_fixed_format` blanks out (rather than deletes) blank/comment/
  directive lines as of commit `b419281`, so later line numbers stay
  accurate -- but `mockymock/splicer/source_map.py`'s `statement_span` and
  `_nested_site_span` computed a span's end line as "one line before the
  next boundary," which can now land on one of those blank placeholders
  instead of the statement's true last content line. Fixed by trimming
  `end` back to the last non-blank line (`_trim_trailing_blank_lines`),
  restoring `tests/unit/test_source_map.py`'s original assertions with no
  test changes needed.
* **Surfaced, not introduced, by the bump**: `examples/nist-cobol85/IC101A`
  and `IC116M` now correctly `PARSE_WARNING`-refuse instead of silently
  proceeding. Root cause: cobolparser's VALUE clause parser has never
  handled a literal that begins on the physical line after the `VALUE`
  keyword without a fixed-format `-` continuation indicator (ordinary
  multi-line clause continuation, legal COBOL) -- confirmed by inspecting
  the parsed AST directly at the *old* pin too: the affected FILLER's
  `value_clause` was already `None` there, just without a warning. The
  content lost either way is a decorative CCVS85 boilerplate banner field
  ("FEATURE ... PARAGRAPH-NAME ... REMARKS"), not load-bearing conformance-
  test logic. Not fixed here -- deliberately out of scope for this pin-bump
  task (an upstream cobolparser parser change, and that sibling repo has
  unrelated concurrent work in flight) -- flagged for follow-up.
* **Also newly visible via `scripts/corpus_sweep.py`, no functional impact**:
  `tests/integration/fixtures/walking_skeleton.cbl` now reports one
  `PARSE_WARNING` (a `DISPLAY` literal's closing quote lands in the
  traditional fixed-format columns-73-80 sequence area and is truncated --
  a pre-existing, cosmetic quirk of that fixture, not new). Harmless:
  `test_walking_skeleton_compiles_and_runs` compiles the raw fixture
  directly through GnuCOBOL and never goes through mockymock's
  parse-warning gate at all. `legacy-application/cobol/ACCTMNT.cbl` and
  `EODPROC.cbl` (sibling-repo corpus, not curated mocky-mock examples) also
  show new warnings -- not investigated, lower priority.

## 2026-07-10 (SECTION-scoped terminator support, narrow shape)
* **Added**: `refusal._safe_section_entry_points` (whole-program check: a
  `SECTION`'s first paragraph is safe to neutralize with `EXIT SECTION`
  only when neither it nor its `SECTION` is ever a `GO TO` target, and
  the paragraph is never itself a direct `PERFORM` target anywhere in
  the program) and wired it into `_plain_perform_edges_from` and
  `find_terminator_plans` (`TerminatorPlan.exit_kind`,
  `injector.build_terminator_neutralization(exit_kind)`). Closes the
  narrow half of spike #5's deferred scope from
  `docs/2026-07-08-goback-stop-run-support-design.md` — see
  `docs/2026-07-10-section-scoped-terminator-support-design.md`.
  Fall-through and direct-paragraph-`PERFORM` section shapes remain
  refused.
* **Side effect**: `test_section_scoped_terminator_refuses` (renamed
  `test_section_touched_only_via_safe_entry_no_longer_refuses`) now
  asserts a plan is produced instead of a refusal, since its `SECTION`'s
  only paragraph is a genuinely safe entry — the old blanket "any
  `SECTION` anywhere in the chain is unsafe" check was strictly more
  conservative than necessary for that shape. A new fixture
  (`CHAIN_SECTION_STILL_UNSAFE_SOURCE`) keeps the true-unsafe chain-level
  case covered.


## 2026-07-10 (Fix: GO TO fall-through terminator hazard now refused, not just documented)
* **What changed**: `refusal.py`'s module docstring (added by the
  2026-07-09 final review of `docs/2026-07-08-goback-stop-run-support-design.md`)
  documented, but did not guard against, a gap in the reachability BFS: a
  `GO TO` target paragraph that falls through past its own end (no
  `PERFORM`/`GO TO`/`GOBACK`/`STOP RUN` of its own) into the next paragraph
  in source order is invisible to `_go_to_targets`, even though a paragraph
  reached that way shares the exact same `EXIT PARAGRAPH` hazard spike #4
  found for a direct `GO TO` target — silent halt instead of return, once a
  *different* test case has neutralized the terminator it falls into via
  its own safe plain chain.
* **Fix**: two new functions in `refusal.py` — `_falls_through(paragraph)`
  (true unless the paragraph's last top-level statement is `GOBACK`,
  `STOP RUN` (not `STOP <literal>`, which only pauses), a plain
  single-target `GO TO` (a computed `GO TO ... DEPENDING ON` does NOT
  count — GnuCOBOL falls through on an out-of-range subscript), or
  `EXIT PARAGRAPH`/`SECTION`/`PROGRAM`) and `_go_to_fallthrough_targets`
  (walks source order forward from every GO TO target, seeding from a
  section's first paragraph when the target is a section name, until
  `_falls_through` says stop). Wired into `find_terminator_plans`'s two
  existing GO TO checks (per-terminator and chain-level) as new `elif`
  branches, refusing `UNSUPPORTED_TERMINATOR_LAYOUT` with a message naming
  the fall-through path. No Docker spike needed — this only ever *adds* a
  refusal, so it can't produce a wrong transform; spike #4 already proved
  the runtime hazard, this just widens which paragraphs are recognized as
  sharing it. See [docs/2026-07-10-goto-fallthrough-terminator-hazard-design.md](../docs/2026-07-10-goto-fallthrough-terminator-hazard-design.md).
* **Known residual gap, not fixed here**: returns no hazard when
  `_source_ordered_paragraphs` can't establish strict source order — the
  same pre-existing blind spot that already limits `_expand_thru_range` to
  refusing only the specific THRU range it was asked about, not extended
  by this change.
* **Unrelated, pre-existing, still open**: `tests/unit/test_terminators.py::test_looping_perform_is_excluded_from_the_safe_chain`
  still fails on this branch exactly as it does on `main` (confirmed via a
  temporary stash-and-rerun before this fix touched anything) — the
  2026-07-10 regression noted in prior session memory, deliberately not
  investigated as part of this work.

## 2026-07-10 (Examples: CUSTINQ (CICS) + RATERTE (dynamic CALL routing))
* **What shipped**: two new hand-written worked examples under `examples/`,
  each with a README and its own `tests/integration/` suite, proven
  end-to-end against real GnuCOBOL in the `mockymock-cobc` container.
  - `examples/custinq/` — the first `EXEC CICS` worked example. Closes the
    real-world-readiness audit's Finding 5 row that CICS was "classified
    but never proven — no example, absent from corpus." No engine change
    was needed: `EXEC CICS` already splices out the same way `EXEC
    SQL`/`EXEC DLI` do, so this only needed a program that exercises it.
    The audit doc's "what closing it takes" note that CICS needed "a CICS
    translation/stub layer" was corrected as wrong — see
    `docs/2026-07-06-real-world-readiness-audit.md` Finding 5.
  - `examples/raterte/` — a business-flavored dynamic-`CALL` routing
    example (account tier → one of three rate subprograms), complementing
    the bare `tests/integration/fixtures/dynamic_call.cbl` regression
    fixture with a polished, documented worked example.
* **Investigated and deliberately not pursued: expanding the corpus-driven
  example sets.** Before hand-writing new examples, `mockymock generate`
  was run against all 14 not-yet-exampled `legacy-application/cobol`
  real-world programs and 6 sampled NIST CCVS85 programs beyond the 4
  already in `examples/nist-cobol85/` — **all 20 refuse with
  `PARSE_WARNING`** against the currently pinned cobolparser commit
  (`8c3c881d`), on two distinct bugs: a multi-operand `STRING ... DELIMITED
  BY SIZE ...` continuation-line bug (real-world corpus) and a `FILLER PIC
  IS X(...) VALUE IS ...` clause-ordering bug in the shared CCVS85
  boilerplate (NIST corpus beyond the 4 already used). Neither is a
  mockymock gap — both are upstream cobolparser parsing bugs. This also
  reproduces on already-*committed* examples: `test_realworld_deptmqc_example.py`,
  `test_realworld_deptmqp_example.py`, and two of the four
  `test_nist_cobol85_examples.py` cases (`IC101A`, `IC116M`) now fail
  against this same pin, confirmed via `direct_url.json` to be installed
  from the exact pinned commit, not a stale/drifted local environment. This
  is broader than the previously-known single regression
  (`test_looping_perform_is_excluded_from_the_safe_chain`, see
  [[project-mockymock-terminator-support]]) — full failing set as of this
  writing: `test_copybook_expansion.py` (2), `test_nist_cobol85_examples.py`
  (`IC101A`, `IC116M`), `test_realworld_deptmqc_example.py`,
  `test_realworld_deptmqp_example.py`, `test_terminator_support.py` (1),
  `test_refusal.py` (2), `test_source_map.py` (1) — 10 failing tests total
  on `main`, unrelated to and unfixed by this change. Fixing this is
  upstream `cobol-parser` work, out of scope here; flagged to the user
  rather than silently worked around.

## 2026-07-09 (Feature: EXEC SQL INCLUDE host-var copybooks + cursor ROWS sugar)
* **What shipped**: `EXEC SQL INCLUDE <member> END-EXEC` (non-SQLCA) now
  resolves via `--copybook-path` — a synthetic `COPY <member>.` snippet
  expanded through cobolparser's public `expand_copybooks`, spliced in and
  re-scanned in place so an embedded DCLGEN `DECLARE ... TABLE` stanza gets
  commented out automatically. Closes the "copybook-style SQL includes
  block the file" row of Finding 5 in the real-world-readiness audit. Also
  added `MOCK SQL "<prefix>" ROWS ( ... ) ( ... ) END-MOCK` DSL sugar,
  codegenning a tally-driven `EVALUATE`/`WHEN` block for cursor FETCH
  loops instead of requiring a hand-written tally/SQLCODE mock body.
* **Deliberate non-goal, verified during design**: `find_copybook_file` /
  `CopybookSearchPath` (`cobolparser.preprocess.path_resolver` /
  `.models`) are **not** in `cobolparser.preprocess`'s `__all__` — reaching
  into them would have added dependency surface `interface-contract.md`
  shouldn't pin. Resolution instead routes through the already-public
  `expand_copybooks` on a synthetic one-line `COPY <member>.` snippet,
  spiked directly (not just reasoned about) to confirm it resolves,
  inlines embedded `EXEC SQL DECLARE TABLE` content verbatim, and raises
  the public `CopybookNotFoundError` on a miss.
* **Scope deliberately deferred**: nested `EXEC SQL INCLUDE` (a resolved
  member containing another live INCLUDE) refuses rather than resolving;
  `ROWS`' exhaustion `SQLCODE` is fixed at 100, not overridable; `ROWS` is
  SQL-only, not generalized to other categories.
* See [docs/2026-07-09-sql-v1-include-cursor-rows-design.md](../docs/2026-07-09-sql-v1-include-cursor-rows-design.md).

## 2026-07-09 (Fix: `mockymock setup` FileNotFoundError under `uv tool install`)
* **Root cause**: `de6ad0d` (uv-installable CLI) made `uv tool install`
  a real, non-editable package install, but `docker_toolchain.py`'s
  `_DOCKER_CONTEXT` still resolved the Docker build context as
  `Path(__file__).resolve().parents[2] / "docker"` — repo-root `docker/`,
  outside the `mockymock` package tree. `pyproject.toml`'s
  `[tool.setuptools.packages.find]` only ships `mockymock*`, so that
  directory was never in the wheel; `_image_tag()` crashed with
  `FileNotFoundError` reading `docker/Dockerfile` the moment any installed
  (non-sibling-checkout) `mockymock` ran `setup` or `run`. The stale
  docstring on `_DOCKER_CONTEXT` said as much: "the only supported install
  mode" was editable — an assumption `de6ad0d` had already invalidated
  without updating this file.
* **Fix**: moved the Dockerfile into the package itself,
  `mockymock/runtime/docker/Dockerfile` (was repo-root `docker/Dockerfile`),
  changed `_DOCKER_CONTEXT` to `Path(__file__).resolve().parent / "docker"`,
  and added `"mockymock.runtime" = ["docker/Dockerfile"]` to
  `[tool.setuptools.package-data]` so it's actually bundled in the wheel.
  Added `test_docker_context_dockerfile_is_bundled_under_the_package`
  ([runtime](runtime.md)) asserting the file exists on disk under
  `_DOCKER_CONTEXT`, so this exact regression fails a unit test next time.
* **Verified live**, not just unit-tested: `uv tool uninstall mockymock` +
  `uv tool install --from . mockymock --force`, confirmed the built wheel's
  installed `site-packages/mockymock/runtime/docker/Dockerfile` exists, then
  ran `mockymock setup` from `/c/tmp` and from the filesystem root `/c` (no
  mocky-mock repo checkout anywhere on either path) — both printed
  `container mockymock-cobc ready (cobc (GnuCOBOL) 3.2.0)` instead of
  crashing. Full unit suite re-run clean aside from 3 pre-existing failures
  in `test_refusal.py`/`test_source_map.py` unrelated to this change
  (confirmed identical on a `git stash` of this fix).

## 2026-07-09 (release-please automation added)
* **Added `googleapis/release-please-action@v4`** (`.github/workflows/release-please.yml`,
  `release-please-config.json`, `.release-please-manifest.json`), mirroring
  the sibling `cobol-parser` repo's setup: `release-type: "python"`,
  `package-name: "mockymock"`, `include-component-in-tag: false`. On every
  push to `main`, release-please maintains a "chore(main): release X.Y.Z" PR
  driven by Conventional Commits since the last release; merging it bumps
  `__version__` in `pyproject.toml` and `mockymock/__init__.py`, updates
  `CHANGELOG.md`, and tags/creates a GitHub Release.
* **Scaled down from cobol-parser's version, deliberately**: cobol-parser's
  workflow also builds sdist + cibuildwheel binary wheels and attaches them
  to the GitHub Release, because it ships compiled Cython extensions and is
  consumed as a pinned git dependency by wheel-preferring installers.
  mockymock has no compiled extensions and its documented install path
  ([README "Install"](../README.md)) is `uv tool install git+https://...`
  straight from the repo — there is no wheel/sdist artifact for anything to
  consume, so the build/publish jobs were omitted rather than carried over
  unused.
* **Bootstrap**: manifest starts at `.`: `"0.0.0"` with
  `release-as: "0.1.0"` in the config (matching the version already in
  `pyproject.toml`/`__init__.py`) so the first release-please PR proposes
  `0.1.0` instead of inventing a version. Drop `release-as` once that first
  release lands, same as cobol-parser did (`chore: drop release-as now that
  v1.0.0 is released`).

## 2026-07-09 (uv-installable CLI: pinned cobolparser git dependency)
* **Made `mockymock` installable via `uv tool install` from any directory**,
  not just inside the LegacyLens monorepo. Root cause: `pyproject.toml` had
  `dependencies = []` — cobolparser was only ever wired in via
  `requirements-dev.txt`'s `-e ../cobol-parser` sibling-checkout install, so
  a `uv tool install` from outside the workspace produced a `mockymock`
  binary that `ImportError`ed on `cobolparser` the moment any real command
  ran.
* **Fix**: added `cobolparser @ git+https://github.com/Landparty/cobol-parser.git@8c3c881dbc1368cf764f28df21eb33ae1470fcf4`
  to `dependencies` — the same commit `.github/workflows/ci.yml` pins, kept
  in sync deliberately (see that workflow's own pin-bump comments). Verified
  live: `uv tool install --from . mockymock`, then ran `mockymock --help` /
  `mockymock generate --help` from `/c/tmp` (no sibling `cobol-parser`
  checkout on that path) — resolved, built, and ran correctly, pulling
  cobolparser straight from the private GitHub repo via the caller's
  existing git credentials.
* **Found and fixed a real fallout, not assumed away**: the initial version
  of this fix (an unqualified `-e .[dev]` line in `requirements-dev.txt`)
  broke the contributor workflow — verified by actually running `pip
  install -r requirements-dev.txt` in a scratch venv, which failed with
  `ResolutionImpossible` because pip cannot reconcile a local-path
  requirement (`-e ../cobol-parser`) against a URL-pinned requirement for
  the *same* package name pulled in transitively by `-e .[dev]`'s new
  `dependencies` entry. Fixed by dropping `-e .[dev]` from
  `requirements-dev.txt` in favor of listing the `[dev]` extra's packages
  explicitly (pytest/pytest-cov/ruff/black/mypy — kept in sync with
  `pyproject.toml`'s `[project.optional-dependencies].dev`) and installing
  mockymock itself in a second step, `pip install --no-deps -e .`, which
  skips dependency resolution entirely for that one requirement so the git
  pin never enters the graph. Re-verified in a fresh scratch venv: both
  `cobolparser` and `mockymock` resolve to their editable sibling-checkout
  paths, and pytest/pytest-cov/ruff/black/mypy all install with their own
  transitive deps intact.
* README gained an "Install" section (`uv tool install`) ahead of the
  renamed "Setup (contributing)" section, which now documents the two-step
  `pip install -r requirements-dev.txt` + `pip install --no-deps -e .`
  sequence; [integration](integration.md)'s claim of "no dependency pin"
  corrected.

## 2026-07-09 (Final branch review: GOBACK/STOP RUN terminator support)
* **Independent Opus-model review of the whole `feature/goback-stop-run-support`
  branch** (all 10 tasks + the looping-PERFORM fix below), specifically asked
  to hunt for siblings of that fix's bug class. Found one Important,
  currently-dormant gap and three Minor items; verified the Important one
  directly (not just trusted the report) before acting on it.
* **Important (verified, addressed):** the out-of-line form of
  `PERFORM para VARYING ...` isn't parsed by `cobolparser` at all -- the
  clause is silently dropped, leaving `PerformStatement.perform_type`
  mistagged as `"SIMPLE"` (confirmed directly: `parse_cobol` on this shape
  returns `target_paragraph` set, `thru_paragraph=None`,
  `perform_type='SIMPLE'` -- indistinguishable from a genuine plain PERFORM
  to `_plain_perform_edges_from`). What actually keeps this out of
  `find_terminator_plans` today is unrelated: cobolparser also emits an
  "Unparsed tokens starting at 'VARYING' ... dropped from the AST" warning,
  and `check_whole_program`'s `PARSE_WARNING` gate refuses the whole program
  before the terminator logic ever runs (confirmed end-to-end via
  `mockymock run`: exit 1, refused on `PARSE_WARNING`). This is a real but
  *accidental* safety net -- if cobolparser is ever fixed to parse this
  shape without also correctly tagging `perform_type`, the hole reopens
  silently. Corrected the design doc's inaccurate claim that `perform_type`
  itself covers this shape, and added pinning regression tests (unit:
  `test_refusal.py`; integration: `test_terminator_support.py`) that assert
  the refusal happens via `PARSE_WARNING` specifically, so a future
  cobolparser change turns this into a loud test failure instead of a
  silent regression.
* **Minor, addressed:** two new orchestrator regression fixtures (two
  terminators sharing one paragraph, deduped chain-check; a `PERFORM`
  immediately followed by a terminator) -- both manually spiked by the
  reviewer and found correct but previously unguarded by any test, added to
  `test_orchestrator.py` given splice line-arithmetic is exactly what
  produced the two-pass ordering bug documented below.
* **Minor, documented (no code change):** (1) a terminator reachable only
  via a `GO TO` that escapes its `PERFORM` range and falls through is
  unmodeled and, once a DIFFERENT case has neutralized that same
  terminator, could produce a subtler failure than the pre-branch clean
  crash (documented in `refusal.py`'s module docstring); (2) the
  whole-chain GO-TO/SECTION checks are over-inclusive and fail-*safe* but
  can over-refuse a genuinely-safe terminator on large paragraphs
  (documented in `find_terminator_plans`'s docstring).
* Full unit+integration suite after remediation: 462 passed, 3 known
  pre-existing failures unrelated to this branch (confirmed via git
  stash/prior investigation), ruff/black/mypy clean on all touched files.
  See `docs/2026-07-08-goback-stop-run-support-design.md`'s "Out of scope"
  section and [splicer.md](splicer.md#terminator-neutralization-gobackstop-run-approach-b)
  for the full technical writeup.

## 2026-07-09 (Fix: looping PERFORM safety gap in terminator neutralization)
* **Fixed a silent correctness bug** in the GOBACK/STOP RUN terminator
  support shipped 2026-07-08 (below): `refusal._plain_perform_edges_from`
  treated `PERFORM ... UNTIL`/`VARYING`/`TIMES` (a looping, out-of-line
  PERFORM) identically to a plain single-shot `PERFORM`, so a terminator
  reachable only through such a loop's target paragraph was wrongly
  accepted as safe by `find_terminator_plans`. `EXIT PARAGRAPH` only ends
  the current loop iteration, not the loop construct itself -- the loop
  re-checks its own unrelated condition and may iterate again, so the
  neutralized program silently ran extra unwanted iterations instead of
  stopping where the real terminator would have. Confirmed empirically:
  a synthetic program with `STOP RUN` inside a looped paragraph (natural
  exit at iteration 5, terminator at iteration 2) ran all 5 iterations
  under the un-fixed neutralization instead of stopping at 2. Fixed by
  excluding `perform_type != "SIMPLE"` edges from the BFS/edge set in
  `_plain_perform_edges_from`; such a terminator's paragraph now never
  enters the safe-reachable set, so it refuses via the existing "reachable
  but not via a plain chain" `UNSUPPORTED_TERMINATOR_LAYOUT` check -- no
  new refusal branch needed. Discovered while qualifying the real-world
  `ACCTPRG` example for a re-target at its `0000-MAIN-PROCESS` entry
  point (which itself uses `PERFORM ... UNTIL` as an intermediate chain
  link, with its `GOBACK` sitting outside the loop -- confirmed still
  safe and unaffected by this fix). See
  [splicer.md#terminator-neutralization-gobackstop-run-approach-b](splicer.md#terminator-neutralization-gobackstop-run-approach-b).

## 2026-07-08 (GOBACK/STOP RUN terminator support, Approach B)
* **Closed Finding 3 of `docs/2026-07-06-real-world-readiness-audit.md`**
  for the plain-PERFORM-chain shape: a `.cut` test case's `PERFORM`
  target reaching `STOP RUN`/`GOBACK` through a chain of plain,
  unconditional `PERFORM` calls no longer kills the whole compiled
  suite. An earlier design (redirect via `GO TO` into a `PERFORM ...
  THRU ...` range) was disproven by its own verification spike and
  never shipped -- see
  [docs/2026-07-08-goback-stop-run-support-design.md](../docs/2026-07-08-goback-stop-run-support-design.md)
  for the concrete crash evidence and the chosen replacement.
  `mock_surface.py` detects `StopStatement`(RUN-form)/`GobackStatement`
  (category `None`, like `CANCEL`/SORT-MERGE); `refusal.py`'s
  `find_terminator_plans` walks backward from each reachable terminator
  through the chain of paragraphs that plainly `PERFORM` it, refusing
  (`UNSUPPORTED_TERMINATOR_LAYOUT`) if any link is a `SECTION` member,
  a `GO TO` target anywhere in the program, or not reached via a plain
  top-level `PERFORM`. Safe terminators get `MOVE "Y" TO UT-EARLY-EXIT`
  + `EXIT PARAGRAPH` in place of the real statement
  (`injector.build_terminator_neutralization`); every intermediate
  `PERFORM` on the chain gets `IF UT-EARLY-EXIT = "Y" EXIT PARAGRAPH
  END-IF` inserted after it (`injector.build_chain_check`, via the new
  `stub_writer.insert_lines_after` primitive). No `driver.py`
  restructuring needed -- `UT-TESTCASE-NNN`'s existing checks, right
  after `PERFORM {target}`, run once the flag has propagated back via
  ordinary `PERFORM` returns.

## 2026-07-08 (IMS DL/I ENTRY/LINKAGE support: neutralize instead of crash or refuse)
* **Closed the corpus sweep's flagged unknown**: "the 5 CBLTDLI-calling
  programs (`ACCTPRG`, `DEPTBMP`, `DEPTIMSM`, `FNDTXFR`, `LNRECOV`) parse
  and `generate` clean" (per the corpus-sweep report) turned out to mask a
  runtime-only crash the sweep explicitly said it didn't test: each has a
  named `ENTRY 'DLITCBL' USING <linkage-group>` alongside a bare default
  entry, and mockymock's PERFORM-only driver never binds the LINKAGE
  storage that ENTRY's `USING` would — verified live against the real
  GnuCOBOL toolchain, this is a SIGSEGV (exit 139), not a hypothetical.
* **Fix, also verified live**: `mockymock/analysis/linkage.py` +
  `mockymock/splicer/linkage.py` comment out the ENTRY statement(s) and the
  `LINKAGE SECTION.` header line (no data relocation — GnuCOBOL folds the
  items into the preceding WORKING-STORAGE SECTION once the header's gone).
  Gated by `refusal.check_linkage_layout` (`UNSUPPORTED_LINKAGE_LAYOUT`)
  behind three guardrails (default entry has no `USING` of its own; LINKAGE
  is the last DATA DIVISION section; the header line textually verifies)
  before ever being applied. No new mocking primitive needed: `CALL
  'CBLTDLI'` was already an ordinary `MockCategory.CALL` boundary, so a
  `.cut` author can `MOCK CALL "CBLTDLI"` and `MOVE` a value into what is
  now real WORKING-STORAGE (e.g. `CUST-STATUS`) to simulate a DL/I outcome.
* Added `examples/real-world/ACCTPRG/` (mirrors the DEPTMQP/DEPTMQC
  convention) with 5 test cases targeting sub-paragraphs (avoiding
  `0000-MAIN-PROCESS`'s `GOBACK`, the existing Finding-3 terminator
  limitation) — proves the fix end-to-end, not just non-crashing.
* Design: [docs/2026-07-08-ims-linkage-support-design.md](../docs/2026-07-08-ims-linkage-support-design.md).
  This narrows Milestone B's scope in the real-world-readiness plan: the
  IMS named-ENTRY subset is solved here; general CALL-based subprogram
  driving (`PROCEDURE DIVISION USING` on a program's own default entry, no
  named ENTRY — zero corpus evidence today) remains future work.

## 2026-07-07 (cobol-parser pin re-bumped to merged commit)
* **Follow-up to the corpus-sweep refresh below:** cobol-parser PR #80
  (the SUBTRACT-GIVING / DISPLAY-subscript / WRITE-FROM-literal fixes, plus
  the two review-driven follow-on fixes for nested-paren subscripts and
  `consume_keyword_and_operand`'s continuation-token handling) has merged
  to `Landparty/cobol-parser` `main`. `.github/workflows/ci.yml`'s pin
  bumped from the feature-branch commit to the actual merge commit
  (`8c3c881`), closing out the "re-pin once it lands" note from the prior
  entry. Full cobolparser suite (6691 passed) and this repo's own suite
  (370 passed, 24 skipped) run green against it; `scripts/corpus_sweep.py`
  still reports 26/26 clean.

## 2026-07-07 (corpus sweep refreshed: 26/26 clean)
* **Re-ran `scripts/corpus_sweep.py`** against `legacy-application` now that
  the `EVALUATE`/`WHEN`-selector cobolparser bug (which blocked 5/17
  real-world programs on the original sweep) is fixed and pinned. The
  re-sweep surfaced three further, different cobolparser content-drop bugs
  (`PARSE_WARNING` on `ACCTMNT.cbl`, `GLRECON.cbl`, `LOANPMT.cbl`): a
  subscripted `DISPLAY` operand, `WRITE ... FROM` with a string-literal
  source, and `SUBTRACT ... FROM ... GIVING` dropping its `GIVING` clause
  (root cause: a shared newline-skipping helper only looked for optional
  clause keywords after skipping newlines *between* the keyword and its
  operand, not before checking for the keyword itself — so a clause on its
  own continuation line was missed). All three fixed upstream (cobol-parser
  PR #80); this repo's own code needed no changes. `docs/corpus-sweep-
  report.md` rewritten with the refreshed results (26/26 programs parse and
  `generate` clean, zero refusals, zero unmockable-boundary categories);
  the original findings are kept below it for history.
  `.github/workflows/ci.yml`'s cobol-parser pin bumped to the fix commit
  (full cobolparser suite run green before bumping); re-pin to PR #80's
  merge commit on `main` once it lands.
* **Found, not fixed (out of scope here):** running this repo's own test
  suite without a Docker daemon available surfaced that
  `test_run_refuses_program_with_parse_errors` and two tests in
  `test_copybook_expansion.py` aren't `@requires_docker`-gated but still
  fail without Docker — `_cmd_run` (`mockymock/cli/main.py`) calls
  `docker_toolchain.ensure_toolchain()` before `check_whole_program()`, so
  a program that would refuse before ever touching Docker (parse error,
  unresolved copybook) still hits the Docker-unavailable path first in a
  Docker-less environment. Pre-existing, unrelated to the corpus-sweep
  fixes above (no mockymock source was touched by this pass) — flagging
  for a future task rather than fixing here.

## 2026-07-07 (PARSE_WARNING refusal gate + misleading [PASS] fix)
* **Refuse on cobolparser's new dropped-content warnings**
  ([analysis](analysis.md), [cli](cli.md), [integration](integration.md)):
  cobolparser's 2026-07-07 silent-drop remediation (upstream PR #77) made
  `ParseResult.warnings` the signal for content dropped from an otherwise
  clean parse — unsupported verbs (INVOKE, EXHIBIT, ...), unparsed clause
  leftovers, and multi-program compilation units (extra programs land in
  `ast.contained_programs`, which the splicer and reachability BFS never
  look at). `check_whole_program` now emits a `PARSE_WARNING` refusal per
  warning, and both `generate` and `run` gate on the returned reasons
  instead of `result.success` alone. New `check_expansion_warnings` refuses
  (`EXPANSION_WARNING`) on lossy copybook decodes surfaced via
  `CopybookExpansion.statistics.warnings` — but only the `"Lossy decode of"`
  class: the same channel carries advisory lint heuristics ("may be missing
  terminating period") that false-positive on valid copybooks (verified
  against `tests/integration/fixtures/copybook_example`). Tests:
  `test_refusal.py` (PARSE_WARNING for INVOKE and multi-program units,
  EXPANSION_WARNING for lossy decode, advisory-lint pass-through),
  `test_cli.py` (generate + run refuse INVOKER programs),
  `test_copybook_expansion.py` (generate refuses lossy copybook).
* **Verified mockymock against cobolparser main after its audit-fix wave**
  (PRs #68–#77: OPEN multi-mode capture, IO clause bodies, EVALUATE WHEN
  children, IF-condition precedence, statement-swallow fixes,
  numeric-literal continuation, C1–C8/H3/H6b silent-drop fixes): full suite
  green (unit + Docker integration). The `task_c5e3b268` dropped-EXEC-SQL
  bug no longer reproduces (COMPUTE/statement-boundary fixes); the DEPTMQP
  xfail was already removed. Stale contract note updated: the
  `fix/open-multi-mode-file-capture` branch requirement is now "cobol-parser
  at or after PR #68 on main". Known upstream residual documented in
  [integration](integration.md): an unknown verb directly after a
  period-less statement can still be swallowed silently by the preceding
  statement's parser (no warning) — period-terminated layouts are covered.

## 2026-07-06
* **Initialization**: Established the OKF bundle for mocky-mock, matching the
  pattern used by sibling LegacyLens repos (`cobol-parser`, `backend`, etc.).
  Authored from the current source tree (`mockymock/dsl`, `splicer`,
  `runtime`, `analysis`, `report`, `cli`) plus `interface-contract.md` and the
  `docs/*-design.md` history (MVP, Docker toolchain, mock-all-boundaries,
  nested-mock-targets, dynamic-call-mocks, PERFORM THRU): [dsl](dsl.md),
  [analysis](analysis.md), [splicer](splicer.md), [runtime](runtime.md),
  [report](report.md), [cli](cli.md), [integration](integration.md),
  [testing](testing.md).
* **Fixed misleading `[PASS]` on a crashed test case** ([report](report.md)):
  a `.cut` case whose `PERFORM` target reaches `STOP RUN` (directly or
  transitively) kills the compiled test binary before that case's END marker
  (or any FAIL marker) prints, and `TestResult.passed` was defined purely as
  `not failure_reasons` — absence of a FAIL marker read as a pass even
  though the case's checks never ran. `TestResult` now tracks `ended` (set
  when `CASE <id> END` is matched) and exposes `crashed = not ended`;
  `passed` requires both no failure reasons and `not crashed`.
  `format_console`/`format_junit_xml` render crashed cases as `[CRASH]` /
  `<error>` instead of `[PASS]`. The aggregate summary line/`tests=`
  attribute also fixed: run count, `tests=`, and (console) failed count all
  fall back to values reconstructed from `suite.results` when the
  SUMMARY-derived field is 0 (SUMMARY line never printed), so the report no
  longer says "0 run"/"0 failed" underneath visibly-rendered PASS/FAIL/CRASH
  case lines. CLI exit code behavior (`all_passed`) was already correct and
  is unchanged — this fixes the human-facing console/JUnit report only.
  Found while wiring up the real-world COBOL e2e examples (see
  `docs/2026-07-06-realworld-cobol-examples-design.md`) with a DEPTMQP-based
  repro. README gained a "Known limitation" note.
* **Recognized WORKING-STORAGE `DECLARE ... CURSOR FOR SELECT` in
  `transform_data_division_exec`** ([splicer](splicer.md)):
  `mockymock/splicer/sqlca.py`'s `_handle_block` commented out `DECLARE ...
  TABLE` but not `DECLARE <cursor> CURSOR FOR SELECT ... END-EXEC`, so any
  program using the standard embedded-SQL batch idiom (cursor declared in
  WORKING-STORAGE ahead of a `PERFORM ... UNTIL SQLCODE = 100` fetch loop —
  e.g. `legacy-application/cobol/ACCTMNT.cbl`'s `ACCT_CURSOR`, and the same
  pattern in `LOANPMT.cbl`/`GLRECON.cbl`/`CTRRPT.cbl`/`DORMACCT.cbl`/
  `STMTGEN.cbl`/`INTCALC.cbl`) fell through to the fail-closed
  "unrecognized" branch and the whole program was refused with
  `UNSUPPORTED_DATA_DIVISION_EXEC` before any test case ran. Fixed by
  extending the DECLARE regex's alternation from `TABLE` to `(TABLE|CURSOR)`
  — a cursor declaration is equally purely-declarative; the actual
  OPEN/FETCH/CLOSE statements are separate PROCEDURE DIVISION EXEC SQL
  statements already handled by the existing boundary-mocking machinery.
  Added `test_declare_cursor_is_commented_out` and
  `test_declare_cursor_for_update_is_commented_out` to
  `tests/unit/test_sqlca.py`. This alone does not yet unblock an
  `ACCTMNT`-based example: a separate cobol-parser bug (task_c5e3b268) drops
  some of `ACCTMNT.cbl`'s own EXEC SQL UPDATE/INSERT statements from the
  AST, causing a different, harder compile failure upstream of this fix.
