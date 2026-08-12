# mockymock — Framework Audit — 2026-08-12

Date: 2026-08-12
Remediation status: **19 of 20 findings fixed same day** (TDD, full suite
green at the pinned cobolparser commit; Finding 11 deliberately deferred —
see its entry). The per-finding sections below are preserved as written
during the audit; a status line has been added to each heading.
Scope: whole-framework read-through audit, six parallel deep dives (core
engine, DSL, CLI, runtime/dashboard, report/coverage, debugger/mutation)
Verification tier: **static** — no live Docker daemon and no `cobolparser`
install were available in this environment (the private sibling dependency
could not be cloned: `fatal: could not read Username for 'github.com'`), so
this pass is in the same position as the 2026-08-01 follow-up, not the
2026-08-10 execution-verified pass. Every CONFIRMED finding below was either
traced through the exact code path by hand or reproduced by calling the
relevant pure-Python function directly (no cobolparser/Docker needed for
those particular functions); SUSPECTED findings are flagged as needing the
cobolparser-backed check the next session with that access should run.

This is the sixth audit of this repo (see
[2026-07-06](2026-07-06-real-world-readiness-audit.md),
[2026-07-07](2026-07-07-audit-report.md),
[2026-08-01](2026-08-01-silent-gaps-audit-followup.md),
[2026-08-10](2026-08-10-framework-audit-and-roadmap.md), and `.okf/log.md`).
Rather than re-reading everything top to bottom (which would mostly
rediscover the already-tracked carried-over items — see that list at the
bottom, re-verified but not re-argued), this pass split the ~14,600-line
`mockymock/` package into six areas and read each one specifically hunting
for defects no prior audit had surfaced, with extra attention on the
CAPTURE ARG feature (shipped 2026-08-11, the newest and least-audited
surface) and on the same *bug class* as the 2026-08-10 Finding 1 (a nested
COBOL clause silently invisible to the analysis layer) in case it recurs
elsewhere.

---

## Finding 1 — `all_passed` (the CLI's exit-code source) and the rendered report can disagree (HIGH, confirmed)

**FIXED 2026-08-12** — `all_passed` now also requires `all(result.passed ...)`; regression tests in `tests/unit/test_report.py`.

`mockymock/cli/main.py:864` gates the process exit code on
`suite_result.all_passed`, and `TestSuiteResult.all_passed`
(`mockymock/report/results.py:92-99`) is:

```python
return (
    self.failures == 0
    and self.tests_run > 0
    and not self.orphan_failures
    and not self.duplicate_case_starts
)
```

`self.failures` is set **only** from the `__MOCKYMOCK__ SUMMARY:
RUN=n FAILURES=n` line the driver itself prints
(`results.py:138-140`) — it is never cross-checked against how many
`CASE ... FAIL:` lines were actually parsed. But the console formatter
(`mockymock/report/formatters.py:42`) and the JSON formatter
(`mockymock/report/json_report.py:104`) both render each case's status from
`TestResult.passed`, which *is* driven by `failure_reasons`
(`results.py:56-57`), populated purely by regex-matching
`__MOCKYMOCK__ CASE <id> FAIL: <reason>` against raw stdout
(`results.py:12,121-124`) with no delimiter or escaping scheme distinguishing
a driver-emitted marker from a COBOL program's own `DISPLAY` output that
happens to start a line with the same text.

Confirmed by direct construction: feeding `parse_stdout` a stdout string
containing a real `SUMMARY: RUN=1 FAILURES=0` alongside an extra line
`__MOCKYMOCK__ CASE 001 FAIL: <program-controlled text>` produces a
`TestSuiteResult` where `all_passed is True` (exit code 0) while
`results[0].passed is False` and the console/JUnit/JSON output all render
that case as failed. A COBOL program under test that legitimately `DISPLAY`s
data derived from external input (a file record, an `ACCEPT`, a mocked
`CALL`'s return value) can produce exactly this shape without any
adversarial intent — a coincidental line-start match is enough. For a tool
whose entire value proposition is "trust the exit code," an exit-0 run that
simultaneously renders a `[FAIL]`/`<failure>` line is a worse failure mode
than a false PASS with no visible trace: it is a **visibly contradictory**
result, and any CI system keying off the exit code alone (the normal case)
never sees the contradiction.

**Recommendation:** derive `all_passed` (or add a new gating field) from
whether any `TestResult.passed` is `False`, not solely from the driver's own
`FAILURES=` counter — or, conversely, have the stdout protocol delimit/escape
markers so program output can never collide with them (e.g. a fixed sentinel
prefix already unlikely to appear in `DISPLAY` output, plus length-prefixing
the way the DAP framing in `debug/adapter.py` does for its own line
protocol). The delimiting fix is more robust; the cross-check is cheaper and
closes today's specific inconsistency immediately.

---

## Finding 2 — `PERFORM <section> THRU <target>` as a test case's own entry point silently drops the THRU range (HIGH, confirmed)

**FIXED 2026-08-12** — a driver-side THRU with a section-named endpoint now refuses `UNSUPPORTED_PERFORM_THRU` loudly (section targets without THRU stay supported); tests in `tests/unit/test_refusal.py`. Unit-verified at the pin; the end-to-end GnuCOBOL run still needs a Docker session.

`mockymock/analysis/refusal.py`'s `_reachable_paragraphs`
(around line 1584) seeds its BFS like this:

```python
stack = [start]
if thru is not None and start in by_name:
    members, problem = _expand_thru_range(...)
    ...
    stack.extend(members)
```

`by_name` (built a few lines above from `_all_paragraphs`) contains only
paragraph names, never section names. If a `.cut` file's `TESTCASE ...
PERFORM <section-name> THRU <other-name>` names a **section** as its start
(legal COBOL — `PERFORM` can target a section, and mockymock's own docstring
for this function says so: "A PERFORM or GO TO naming a SECTION pushes every
paragraph of that section"), then `start in by_name` is `False`, so the
entire `if` block is skipped — both the range expansion *and* the
fail-closed refusal `_expand_thru_range` would otherwise raise for a
bad/missing endpoint. `thru` is silently discarded with **zero** refusal.

The loop then pops `start`, finds it's not in `by_name`, and falls into the
`section_members` branch (line 1624-1629), which pushes only that section's
*own* paragraphs — never continuing on to `thru` or anything between the
section and it in source order. Meanwhile `mockymock/splicer/driver.py`
emits the literal `PERFORM <target> THRU <thru>` into the compiled test
driver regardless of what the refusal gate saw — GnuCOBOL really does
execute the full fall-through range at runtime. So the gate's reachable set
and the compiled program's actual runtime behavior diverge: any boundary
statement (`CALL`, file op, `EXEC SQL/CICS/DLI`, `ACCEPT`) between the
section and the THRU endpoint is left out of the reachable set entirely, and
an unmocked one there produces a silent PASS instead of the intended
`UNMOCKED_CALL`-class refusal — the exact failure mode the 2026-08-10 audit's
Finding 1 was about, in a different corner of the same function.

Every *other* THRU call site in this file is more careful: in-program
`PERFORM ... THRU` (line ~1657) and `flow_mocks.py`'s own THRU-hazard check
both call `_expand_thru_range` unconditionally and let it discover a bad or
section-shaped endpoint and refuse. Only this one seed-path guard adds the
extra `start in by_name` pre-check that silently bypasses that safety net —
and it appears to exist only to avoid calling `_expand_thru_range` with a
section name it can't handle, not as a deliberate design choice to skip THRU
validation for section-seeded cases.

No unit test in `tests/unit/test_refusal.py` or `test_terminator*.py`
exercises a section-named `perform_target` combined with `perform_thru`.

**Repro shape:** a program with `ENTRY-SEC SECTION` → `MIDDLE-SEC SECTION`
(containing an unmocked `CALL "AUDITPGM"`) → `CLEANUP-SEC SECTION` in source
order; a `.cut` case `PERFORM ENTRY-SEC THRU CLEANUP-SEC` with no `MOCK
CALL` for `AUDITPGM`. Expected: `UNMOCKED_CALL` refusal (or, if `CLEANUP-SEC`
doesn't exist, `UNKNOWN_PARAGRAPH`). Actual (traced through the code, not
yet run against real GnuCOBOL — no Docker in this environment): a clean
result, since `MIDDLE-SEC`'s boundary sites are never added to `reachable`.

**Recommendation:** either extend `_expand_thru_range` (or a variant) to
accept a section-named start/end by resolving it to its first/last member
paragraph in source order, or explicitly refuse with a new code (e.g.
`UNSUPPORTED_SECTION_THRU`) when a test case's own seed is a section and
`thru` is set, rather than silently proceeding with a truncated reachable
set. The refuse-loud option is cheaper and matches the project's own stated
philosophy ("fail closed... rather than being mis-parsed").

---

## Finding 3 — Two other nested-clause attributes may share the fixed `ON SIZE ERROR` bug (MEDIUM, suspected — needs cobolparser)

**CONFIRMED AND FIXED 2026-08-12** — the five-minute check ran in the remediation session (cobolparser attached at the pin): both `not_at_eop_clause` and `not_on_overflow` exist, held statements, and were invisible. Added to `_NESTED_STATEMENT_ATTRS`; parametrized tests cover both halves of WRITE/STRING/UNSTRING clauses.

The 2026-08-10 audit's Finding 1 was a two-attribute gap in
`mockymock/analysis/mock_surface.py`'s `_NESTED_STATEMENT_ATTRS`
(`on_size_error`/`not_on_size_error` missing, hiding boundaries inside
arithmetic `ON SIZE ERROR` clauses from the whole analysis layer). That
audit's own table enumerating every sibling clause and whether it was
covered is worth extending — two more pairs look asymmetric and are not
documented as checked anywhere in `.okf/`, `docs/`, or the code:

- **`WRITE ... AT END-OF-PAGE`** — the tuple has `at_eop_clause` but no
  `not_at_eop_clause` counterpart, unlike every other paired clause in the
  same tuple (`at_end_clause`/`not_at_end_clause`,
  `invalid_key_clause`/`not_invalid_key_clause`, `on_exception`/
  `not_on_exception`, `on_size_error`/`not_on_size_error`). If cobolparser
  exposes `WRITE ... NOT AT END-OF-PAGE` under a distinct attribute name,
  it's currently invisible to boundary detection and the reachability BFS.
- **`STRING`/`UNSTRING ... ON OVERFLOW` / `NOT ON OVERFLOW`** — `on_overflow`
  in the tuple is documented (`interface-contract.md:40`) as a
  `CallStatement` attribute (the legacy COBOL-74 `CALL ... ON OVERFLOW`
  form), not `StringStatement`/`UnstringStatement`'s. Whether `STRING`/
  `UNSTRING` share that same attribute name for their own overflow clauses,
  and whether a `NOT ON OVERFLOW` sibling attribute exists, is unconfirmed.

Neither could be verified in this environment (no `cobolparser` install
reachable — the private-repo clone failed with the same auth error the
2026-08-10 CI-outage finding described, and `add_repo` for the
`Landparty/cobol-parser` sibling required an approval this session didn't
have). **Recommendation:** the same five-minute check that resolved the
original Finding 1 — enumerate `IOWriteStatement`/`StringStatement`/
`UnstringStatement`'s actual field names at the pinned commit
(`83478ba7...`) — should be run by the next session with cobolparser access,
ideally as the first cut of proposed add-on #6 from the 2026-08-10 doc (a
parser-agreement contract suite), so this class of gap stops needing a fresh
manual sweep each time.

---

## Finding 4 — DSL parser silently accepts an unbalanced subscript when there's no space before the stray `(` (MEDIUM, confirmed)

**FIXED 2026-08-12** — `_reject_unbalanced_subscript` now refuses at all three `_SUBSCRIPTED_NAME` consumption sites (MOVE/EXPECT/CAPTURE).

`mockymock/dsl/parser.py:112`:

```python
_SUBSCRIPTED_NAME = r"[A-Za-z0-9][A-Za-z0-9-]*(?:\s*\([^)]*\))?|\S+"
```

When a subscript's closing `)` is missing and there is **no space** between
the identifier and the opening `(`, the first alternative fails to match (no
closing paren within `[^)]*`), and the parser falls through to the `\S+`
alternative — which exists only to preserve literal `{Placeholder}` tokens —
silently swallowing the whole malformed token as one opaque, syntactically
invalid name. Reproduced directly against `parse_cut`:

```
MOVE 5 TO WS-TAB(1
```

parses with no error at all, producing `setup_moves = [('5', 'WS-TAB(1')]` —
a target that isn't valid COBOL and isn't caught until (or unless) the
splicer emits it and `cobc` rejects it with a confusing, several-steps-removed
error. `EXPECT WS-X(1 TO BE 5` and `CAPTURE ARG 1 INTO WS-X(1` (both sharing
the same `_SUBSCRIPTED_NAME` fragment) exhibit the identical gap.

The existing regression tests (`test_move_unbalanced_paren_target_raises`,
`test_expect_unbalanced_paren_raises`) only cover the case **with** a space
before the stray `(` (`WS-A (`), where `\S+` also stops at the space and
correctly raises `CutParseError` — they don't cover the no-space form, which
is the actual gap, and `CAPTURE ARG` (new 2026-08-11) has no dedicated
coverage for either form.

**Recommendation:** tighten `_SUBSCRIPTED_NAME` (or add a post-match check)
to reject a token containing an unbalanced `(` before falling back to `\S+`,
consistent with the project's stated fail-closed parsing discipline for
every other malformed-input case in this file.

---

## Finding 5 — `mockymock skills install` crashes with a raw `FileExistsError` on a dangling symlink target (MEDIUM, confirmed)

**FIXED 2026-08-12** — a symlink (dangling or not) now counts as an occupied target: refused without `--force`, replaced with it.

`mockymock/cli/skills_cmd.py:41-60` (`install_skill`) only guards two
target states: doesn't exist, or exists as a real file/dir/symlink-to-something.
A **dangling** symlink (points at a path that doesn't exist) satisfies
neither: `Path.exists()` follows the link and reports `False` for a broken
symlink, so both the `SkillTargetExistsError` refusal (line 49) and the
removal branch (line 51) are skipped regardless of `--force`. Execution
falls through to `shutil.copytree(SOURCE_DIR, target)`, which calls
`os.makedirs`/`os.mkdir` on a path that already has a directory-entry
occupying it — raising `FileExistsError`, uncaught, as a raw Python
traceback instead of a clean `mockymock skills: <error>` message and exit 1.

Reproduced directly:

```python
Path('dangling').symlink_to('/nonexistent/path')
shutil.copytree('/some/src', Path('dangling'))
# FileExistsError: [Errno 17] File exists: 'dangling'
```

This is exactly the class of edge case the 2026-08 "Handle non-directory
--force targets" fix addressed for plain files and symlink-to-directory
targets, but missed for symlink-to-nowhere. A stale/broken
`~/.claude/skills/mockymock` symlink (e.g. left behind by a moved or deleted
install source) is a plausible real-world state, not a contrived one.

**Recommendation:** check `target.is_symlink()` in addition to
`target.exists()` before deciding the target is absent — a symlink (dangling
or not) should route into the existing removal branch rather than the
create-fresh path.

---

## Findings 6–20 — remaining new findings from the six-way review, by area

**Status 2026-08-12: all fixed same day except Finding 11** — 6–9
(DAP adapter/call-stack crash paths), 10 and 12 (record_rewrite ordered
matching + orphan-record surfacing/labeling), 13–16 (CLI write guards,
skills usage, typed `MalformedBundleError`, `mutate --list` flag refusal),
17–19 (race-adoption image check, probe timeout plumbing, dashboard probe
coalescing), and 20 (unrepresentable MOCK keys skipped fail-closed).
Finding 11 (newline-in-value marker truncation) is deliberately deferred:
the real fix is protocol-level escaping in the generated COBOL driver (a
design-doc change, not a parser patch) — documented as a known limitation
in `parse_stdout`'s docstring.

Grouped by module; severity is my judgment after reading each, not the
sub-review's own label. All are newly surfaced by this pass (none overlap
prior audits' carried-over list below).

**Debugger (`mockymock/debug/`) — MEDIUM, mostly confirmed by code trace,
not run against live gdb (unavailable here):**

6. `adapter.py`'s `run()` loop (line ~139) catches only `DapFramingError`;
   a truncated message body (client dies mid-send) raises
   `json.JSONDecodeError` instead, uncaught, killing the whole adapter
   process rather than the documented fail-closed shutdown.
7. `adapter.py:158-159` reads `request["command"]` *before* the
   try/except meant to convert handler failures into DAP error responses —
   a request missing `command` raises an uncaught `KeyError` out of
   `_dispatch`. A request missing `seq` is worse: the recovery path itself
   (`_send_response` at line ~217) indexes `request["seq"]`, so the code
   meant to handle a malformed request is what crashes on it.
8. `call_stack.py:190-199` — `_resolve_frame(..., int(location["line"]),
   ...)` sits outside the try/except that catches `GdbCommandError` for the
   line above it (`location.get("file", "")`, note the telling `.get` vs.
   `[...]` asymmetry). A frame gdb can address but can't attribute a source
   line to (e.g. library/PLT code) raises an uncaught `KeyError`, aborting
   the entire `stackTrace` request — the specific "one bad slot must not
   fail the whole request" guarantee the adjacent F14 comment says was
   already fixed, but wasn't for this path.
9. `adapter.py:243-262` (`_handle_launch`) resets session state on a
   second `launch` but never clears `self._current_stop`/
   `self._breakpoint_original_file`. A relaunch followed by `stackTrace`
   before the new session has stopped even once can synthesize a call
   stack from the *previous* session's stale stop location instead of the
   correct empty-frames response.

**Report/coverage (`mockymock/report/`) — MEDIUM, all confirmed by direct
execution or code trace:**

10. `record_rewrite.py:76-77` collapses a case's recorded values with
    `dict(result.recorded)`; nothing prevents two `*> STUB EXPECT` comments
    for the same data-name in one `TESTCASE` (e.g. before/after a step), and
    both then silently get the *last* recorded value — the earlier one's
    golden gets corrupted with no warning.
11. `results.py:107` splits stdout with `str.splitlines()` before
    regex-matching each line. A `PIC X` field containing a raw newline
    breaks one logical `__MOCKYMOCK__ RECORD/FAIL/...` marker into two
    physical lines; the continuation matches nothing and is silently
    dropped — `--record-expectations` can bake a truncated value into a
    `.cut` file with zero indication anything was cut.
12. `orphan_records` (`results.py:90`) is populated but never read by any
    formatter (console/JUnit/JSON all expose `orphanFailures`,
    `duplicateCaseStarts`, `orphanEnds` in the JSON report, but not this).
    `record_rewrite.py:84-91` compounds it: it mislabels an unattributable
    RECORD line as "case crashed before reaching the record point" even
    when the case ran fine and only the marker's id-attribution failed.

**CLI (`mockymock/cli/`) — LOW/MEDIUM, confirmed by code trace:**

13. `_cmd_mutate`'s `--json-report` write (`main.py:1075-1078`) and
    `_cmd_generate`'s `-o` write (`main.py:394`) both bypass the shared
    `_write_report_file` helper that gives `run`/`export` a clean
    `mockymock <cmd>: could not write ...` message on `OSError` — a bad
    output path raises a raw traceback instead, for `mutate` only after a
    potentially multi-minute run.
14. `mockymock skills` with no subcommand prints the full top-level help
    (all 12 subcommands) instead of `skills`'s own usage, because `func` is
    only set on `skills_install_parser`, not `skills_parser` itself
    (`main.py:1748-1751`).
15. `fixture_bundle.py` (`_load_field_spec`/`_load_fixture`/
    `_load_expectation`/`_load_scenario`/`load_fixture_bundle`) accesses
    required JSON keys with bare `data["key"]` — a bundle missing `seed`, a
    scenario missing `name`, or invalid JSON entirely raises a raw
    `KeyError`/`JSONDecodeError`, with no typed-error contract at all
    (unlike `parser.py`'s `CutParseError` discipline, or even this same
    module's own `UnsupportedBundleVersionError`). Currently masked only by
    the sole call site's blanket `except Exception`.
16. `mutate --list` silently ignores `--timeout`/`--json-report`/
    `--fail-under` with no warning (low severity, UX inconsistency only).

**Runtime/dashboard (`mockymock/runtime/`, `mockymock/web/`) — MEDIUM,
confirmed by code trace, not run against a live daemon (unavailable here):**

17. `docker_toolchain.py:193-202`'s concurrent-container-creation race
    recovery path adopts whatever container won the race without comparing
    its image tag to this invocation's `IMAGE` constant — bypassing the
    stale-image `rm -f`-and-recreate safeguard that `ensure_toolchain()`'s
    main path enforces. Two `mockymock` invocations from different
    installed versions racing to create the container for the first time
    could leave the loser silently running against a container built with
    different (possibly weaker) `_HARDENING_FLAGS`.
18. `status.py`'s documented 15s `PROBE_TIMEOUT` ceiling isn't actually
    enforced for `_probe_container`/`_probe_cobc` — both call
    `docker_toolchain` helpers (`_inspect_container`, `cobc_version`) that
    hardcode `timeout=30` with no override parameter, so a single
    `/api/status` poll can block up to ~90s worst case, six times the
    documented per-check bound the dashboard design explicitly calls out as
    the point of having a separate probe timeout at all.
19. (Suspected, low confidence) `web/server.py`'s `ThreadingHTTPServer` has
    no bound on concurrent handler threads; combined with #18, a browser
    polling every 5s against a slow/degraded daemon could accumulate many
    concurrent `docker` subprocesses rather than the intended
    single-in-flight-probe behavior.

**DSL generator — LOW:**

20. `generator.py` escapes embedded `"` in scaffolded `TESTSUITE`/
    `TESTCASE` names (`_quote_safe`, with a comment explaining why) but not
    in `MOCK <cat> "<key>"` keys (`_directive_for`/`_bundle_directive_for`/
    `_sql_rows_directive`). A boundary key containing a literal `"` (a
    static `CALL` literal or an `EXEC` statement's unique-prefix text) would
    scaffold a `.cut` file `parse_cut` itself can't parse back —
    round-trip breakage of the same kind `_quote_safe` exists to prevent,
    just not extended to keys.

---

## Structural observation, re-checked

The 2026-08-10 audit flagged `cli/main.py` (1739 lines, 11 inline `_cmd_*`
handlers) as worth splitting, blocking remediation of several findings. It's
now ~1790 lines — slightly larger, not smaller; the split hasn't happened
yet. Not re-arguing the recommendation, just noting the trend, and noting
that Finding 13 above (two more unguarded write paths) is exactly the kind
of small duplication-driven bug that recurs while the module stays
monolithic.

---

## Carried-over open items (re-verified by reading current code, not re-argued)

| Item | Source | Verified state |
|---|---|---|
| README has no "what a passing run proves" section | 2026-07-06 F1 | Still absent as of this pass |
| `EXPECT` is equality-only (`TO BE`) | 2026-07-06 F6 | Confirmed, `dsl/parser.py` |
| No cross-mock ordering assertions | 2026-07-06 F6 | Confirmed |
| CSV-sourced `ROW`s | 2026-07-31 design doc | Designed, not implemented |
| `SORT`/`MERGE`/`RELEASE`/`RETURN` refused | 2026-07-06 F5 | Confirmed, `UNSUPPORTED_SORT_MERGE` |
| No large-program corpus test | 2026-07-06 F8 | Confirmed |
| No timing data in JUnit/JSON reports | 2026-08-10 | Confirmed |
| No report written on refusal/compile-failure exit | 2026-08-10 | Confirmed |
| Unbounded subprocess output capture | 2026-08-10 | Confirmed, `docker_toolchain.py` |
| `run` has no `--timeout` (only `mutate` does) | 2026-08-10 | Confirmed |
| `cli/main.py` not yet split into per-command modules | 2026-08-10 | Still open, slightly worse (see above) |
| `refusal.py` not yet split along its seams | 2026-08-10 | Confirmed, still 2084+ lines |
| Upstream `cobolparser` arithmetic-terminator phantom-paragraph bug | 2026-08-10 F2 | Open upstream; mockymock-side guard still shipped |
| CI's `COBOL_PARSER_PAT` gap | 2026-08-10 F3 | Not independently re-checked this pass (no CI/secrets access here) |
| Fidelity ceiling: GnuCOBOL ≠ IBM Enterprise COBOL | 2026-07-06 F1 | Structural, permanent by design |

---

## Prioritized recommendations

### Do now
1. **Finding 1** (`all_passed`/rendered-report disagreement) — the CLI's
   exit code is the tool's entire contract with CI; this can currently lie
   in a visible, non-adversarial way.
2. **Finding 2** (section-seeded `PERFORM ... THRU` in a `.cut` file) —
   same fail-closed-safety bug class as the tool's core value proposition,
   currently silent.
3. **Finding 4** (unbalanced-subscript DSL parse gap) and **Finding 5**
   (`skills install` dangling-symlink crash) — small, well-isolated fixes.

### Do next
4. **Finding 3** — run the cobolparser field-name check on `WRITE ... NOT
   AT END-OF-PAGE` and `STRING`/`UNSTRING ... (NOT) ON OVERFLOW` the moment
   a session has cobolparser access; this is a five-minute check that
   either closes the question or surfaces a Finding-1-class bug.
5. Debugger findings 6–9 — the DAP adapter should never let a malformed
   client message or a corrupted gdb frame kill the session; both are
   currently one bad input away from doing so.
6. Report findings 10–12 — `record_rewrite.py`'s dedup-by-dict silently
   corrupting a golden value is the kind of bug that erodes trust in
   `--record-expectations` specifically because it never surfaces.

### Do when convenient
7. CLI findings 13–16, runtime/dashboard findings 17–19, generator finding
   20 — real but lower-severity/lower-likelihood; batch these into one
   remediation pass.
8. Re-run the CI/`COBOL_PARSER_PAT` check (2026-08-10 Finding 3) — this
   pass had no access to verify whether it was ever rotated.

---

## Appendix — reproductions run in this environment

```python
# Finding 1
from mockymock.report.results import parse_stdout
stdout = (
    "__MOCKYMOCK__ TESTSUITE: S\n"
    "__MOCKYMOCK__ CASE 001 START: case\n"
    "__MOCKYMOCK__ CASE 001 FAIL: program-controlled text\n"
    "__MOCKYMOCK__ CASE 001 END\n"
    "__MOCKYMOCK__ SUMMARY: RUN=1 FAILURES=0\n"
)
r = parse_stdout(stdout)
r.all_passed          # True  -> exit code 0
r.results[0].passed   # False -> console/JUnit/JSON render [FAIL]

# Finding 4
from mockymock.dsl.parser import parse_cut
suite = parse_cut(
    'TESTSUITE "S"\n\nTESTCASE "case"\n'
    '    PERFORM MAIN-PARA\n'
    '    MOVE 5 TO WS-TAB(1\n'
    '    EXPECT WS-X TO BE 5\n'
)
suite.test_cases[0].setup_moves  # [('5', 'WS-TAB(1')] -- no CutParseError

# Finding 5
from pathlib import Path
import shutil
Path('dangling').symlink_to('/nonexistent/path')
shutil.copytree('/some/src', Path('dangling'))
# FileExistsError: [Errno 17] File exists: 'dangling'
```

Findings 2, 3, 6–9, 17–19 were verified by tracing the exact code path (line
numbers cited above) rather than by execution, since this environment had
neither a live Docker daemon nor a usable `cobolparser` install — the same
constraint the 2026-08-01 audit operated under. A session with both should
re-verify Finding 2 end-to-end against real GnuCOBOL and run the Finding 3
field-name check before either is marked fixed.
