# mockymock — Framework Audit & Roadmap — 2026-08-10

Date: 2026-08-10
Scope: whole-framework audit + prioritized recommendations + proposed add-ons
Verification tier: **executed**, not read (see Method)

---

## Method, and why this audit is different from the previous four

This repo already carries four overlapping audits:

| Doc | Nature | Verification available at the time |
|---|---|---|
| [`2026-07-06-real-world-readiness-audit.md`](2026-07-06-real-world-readiness-audit.md) | 10 strategic findings | partial |
| [`2026-07-07-audit-report.md`](2026-07-07-audit-report.md) | 48 line-level findings | full |
| [`2026-08-01-silent-gaps-audit-followup.md`](2026-08-01-silent-gaps-audit-followup.md) | re-verification of all 48 | **none** — no Docker, no `cobolparser` |
| `.okf/log.md` 2026-08-10 entries | 41-finding remediation (20 fixed) | full |

A fifth static read-through would mostly rediscover known-open items. What
this pass adds instead is **execution**: this session had both a live Docker
daemon (`29.4.0`, linux containers) *and* the private `cobolparser`
dependency, installed into an isolated venv pinned to the exact commit
`pyproject.toml` and CI resolve (`83478ba7`) — not the locally-drifted
sibling checkout, which sits at `8197d5e`. Every finding below was
reproduced by running code at that pin, and the two headline findings were
reproduced end-to-end through `mockymock run` against real GnuCOBOL in
Docker.

That matters because the 2026-08-01 pass explicitly deferred one suspected
gap for "whoever has `cobolparser` access — a five-minute check." **It was
real.** It is Finding 1 below, and it is worse than that document predicted.

### Health snapshot

| Check | Result |
|---|---|
| `pytest tests/unit -q` | **1052 passed**, 1 skipped, 1 xfailed (8s) |
| `pytest tests/integration -q` (real Docker) | **124 passed**, 12 skipped (117s) |
| `ruff check .` | clean |
| `black --check .` | clean, 150 files |
| `mypy mockymock/` | clean, 51 source files |
| CI on `main` | **RED** — see Finding 3 |
| `release-please` | green (this closes a long-standing gap noted 2026-07-21) |

The local engineering hygiene here is genuinely strong: 1176 passing tests,
three clean static gates, an OKF bundle that tracks the code, and a
remediation discipline (failing test first, confirmed via `git stash`,
then fix) visible throughout `.okf/log.md`. The findings below are not a
verdict on care taken; two of the three are precisely the kind of gap that
survives careful review and only falls out of execution.

---

## Finding 1 — `ON SIZE ERROR` hides boundaries from the refusal gate (HIGH, silent, confirmed) — **FIXED same day**

**Status: confirmed at the pinned commit, reproduced end-to-end, and fixed.
This was a false-clean PASS — the exact failure class the refusal gate
exists to prevent.**

`on_size_error`/`not_on_size_error` were added to
`_NESTED_STATEMENT_ATTRS`, following TDD (regression tests in
`tests/unit/test_mock_surface.py` and `tests/unit/test_refusal.py`,
confirmed failing before the fix via `git stash`). The `SILENT` fixture
below now refuses `UNMOCKED_CALL` end-to-end against real GnuCOBOL, same as
the `CONTROL` fixture always did. One nuance surfaced by the fix: *mocking*
the now-visible nested `CALL` correctly falls back to
`UNSUPPORTED_NESTED_MOCK_TARGET` — the same fail-closed treatment every
other unsplicable nested clause body (`IF`/`EVALUATE`/...) already gets,
since cobolparser gives no location data to safely splice inside an
`ON SIZE ERROR` body. That is the intended, existing contract, not a new
gap. Full unit (1058 passed) and integration (124 passed, real Docker)
suites pass with no regressions; see `.okf/log.md`'s 2026-08-10 entry.

**The rest of this section is preserved as originally written** — the
investigation and reproduction that led to the fix above, describing the
code as it stood *before* that fix. Table entries, code excerpts, and the
closing recommendation below are all pre-fix state, not current state.

`mockymock/analysis/mock_surface.py`'s `_NESTED_STATEMENT_ATTRS`
([mock_surface.py:239](../mockymock/analysis/mock_surface.py#L239)) was the
single list every boundary detector, the GO TO/PERFORM reachability BFS,
ALTER detection, and the splicer's span computation consult to see inside
nested statement bodies. It had **no entry for `on_size_error` /
`not_on_size_error`**.

`cobolparser` at the pinned commit exposes both as ordinary nested
statement lists:

```
ADD ON SIZE ERROR        AddStatement      {'on_size_error':     ['CallStatement']}
ADD NOT ON SIZE ERROR    AddStatement      {'not_on_size_error': ['CallStatement']}
```

So a `CALL`, file op, `EXEC SQL/CICS/DLI`, `ACCEPT`, `PERFORM`, or `GO TO`
inside an arithmetic statement's size-error branch is invisible to the
entire analysis layer.

### The controlled experiment

Two programs, identical but for the clause wrapping the unmocked `CALL`,
each run through `mockymock run` against real GnuCOBOL:

```cobol
*> CONTROL — CALL inside IF
           IF WS-X > 9000
               CALL "AUDITPGM" USING WS-RESULT
           END-IF.
```
```
mockymock run: refused (UNMOCKED_CALL): CALL boundary at line 11
(paragraph 'MAIN-PARA', keys AUDITPGM) is reachable from 'MAIN-PARA'
but no MOCK directive in this test case matches it
```

```cobol
*> SILENT — same CALL inside ON SIZE ERROR
           ADD 1 TO WS-X
               ON SIZE ERROR
                   CALL "AUDITPGM" USING WS-RESULT.
```
```
TESTSUITE: SILENT
  [PASS] no mock declared for the CALL hidden in ON SIZE ERROR
1 run, 0 failed
```

The second program contains a live, unmocked, external subprogram call and
mockymock reports a clean pass — no refusal, no warning, no diagnostic. A
user reading that output concludes the program's boundaries are fully
mocked. They are not.

Direct confirmation at the analysis layer, same pin:

```
EXPECTED: VISIBLE, HIDDENPG, INIFPGM
ACTUAL  : ['INIFPGM', 'VISIBLE']        # HIDDENPG absent from call_sites
```

### Blast radius — also confirmed, not inferred

Larger than a missed mock. The reachability BFS reuses
`_nested_statement_lists`, so a `PERFORM` inside a size-error branch makes
an entire downstream paragraph subgraph invisible. Reproduced directly:

```cobol
       MAIN-PARA.
           MOVE "START" TO WS-RESULT.
           ADD 1 TO WS-X
               ON SIZE ERROR
                   PERFORM ERR-PARA.
           MOVE "DONE" TO WS-RESULT.
       ERR-PARA.
           CALL "AUDITPGM" USING WS-RESULT.
```
```
TESTSUITE: BFSCASE
  [PASS] ERR-PARA reachable only via ON SIZE ERROR; its CALL is unmocked
1 run, 0 failed
```

`ERR-PARA` is reachable *only* through the size-error branch, and its
unmocked `CALL` is a second-order miss — the boundary is not merely
nested inside an unread clause, it lives in a paragraph the BFS never
visits. Terminator neutralization, paragraph mocks, and coverage
attribution all inherit this truncated view.

### The fix was two lines

I enumerated every sibling clause type at the same pin to check whether the
gap was broader. It was not — it was exactly two attributes wide:

| Clause | Parser attribute | In `_NESTED_STATEMENT_ATTRS` (pre-fix)? |
|---|---|---|
| `IF` / `ELSE` | `then_statements`, `else_statements` | yes |
| `READ ... AT END` | `at_end_clause` | yes |
| `CALL ... ON EXCEPTION` | `on_exception` | yes |
| `STRING ... ON OVERFLOW` | `on_overflow` | yes |
| `SEARCH ... WHEN` | (dedicated `isinstance` branch) | yes |
| **`... ON SIZE ERROR`** | **`on_size_error`** | **NO — fixed 2026-08-10** |
| **`... NOT ON SIZE ERROR`** | **`not_on_size_error`** | **NO — fixed 2026-08-10** |

Adding both names to the tuple was the whole fix; no other function needed
touching, since refusal, splicer, and source-map all consume this one
function. Landed with a regression test per statement type
(`ADD`/`SUBTRACT`/`MULTIPLY`/`DIVIDE`/`COMPUTE` — each verified individually
to expose the same two attribute names at the pinned commit, see
[analysis.md](../.okf/analysis.md)), plus the end-to-end case confirming the
`SILENT` fixture above now refuses.

Fixed first, as recommended: small, surgical, closed a silent-wrongness
hole in the tool's core safety property.

---

## Finding 2 — Arithmetic scope terminators create phantom paragraphs (HIGH, silent, upstream) — **defense-in-depth guard shipped same day**

**Status: confirmed at the pinned commit. Root cause is in `cobolparser`,
not mockymock, and remains open there — but the fail-closed guard proposed
below (track 2) has been implemented in mockymock.**

`refusal.py`'s `_check_unsupported_control_flow` (the same whole-program
check that already refuses `UNSUPPORTED_DECLARATIVES`/`UNSUPPORTED_ALTER`)
now also refuses `UNSUPPORTED_PHANTOM_PARAGRAPH` when a paragraph is named
exactly one of the five reserved terminators — **not** the broader
`^END-[A-Z]+$` pattern this document originally floated, which would also
have refused legitimate paragraphs like `END-OF-JOB`/`END-RUN`. A
regression test (`test_whole_program_check_allows_legitimate_end_prefixed_paragraph`)
guards against that false positive; the full example/test corpus (1058
unit tests) has zero collisions with the exact-name form. The `SIZEPROB`
fixture that previously produced an unexplained `[CRASH]` now produces:

```
mockymock run: refused (UNSUPPORTED_PHANTOM_PARAGRAPH): paragraph
'END-ADD' (line 13) is named after a reserved arithmetic scope terminator
-- cobolparser failed to consume it as the preceding ADD/SUBTRACT/
MULTIPLY/DIVIDE/COMPUTE's own terminator and parsed it as a paragraph
instead, silently reparenting every statement after it; drop the
explicit terminator and end the statement with a period instead (moving
it to the same line does not avoid this)
```

The upstream `cobol-parser` fix (track 1 below) is still open — this
guard converts the silent-wrong outcome into a loud one, it doesn't
restore the ability to use an explicit `END-ADD` terminator.

An explicit arithmetic scope terminator written on its own line in Area B
and followed by a period is parsed as a **paragraph name**, silently
reparenting every following statement:

```
END-IF           paragraphs=['MAIN-PARA']
END-EVALUATE     paragraphs=['MAIN-PARA']
END-PERFORM      paragraphs=['MAIN-PARA']
END-CALL         paragraphs=['MAIN-PARA']
END-STRING       paragraphs=['MAIN-PARA']
END-ADD          paragraphs=['MAIN-PARA', 'END-ADD']        <-- PHANTOM
END-SUBTRACT     paragraphs=['MAIN-PARA', 'END-SUBTRACT']   <-- PHANTOM
END-MULTIPLY     paragraphs=['MAIN-PARA', 'END-MULTIPLY']   <-- PHANTOM
END-DIVIDE       paragraphs=['MAIN-PARA', 'END-DIVIDE']     <-- PHANTOM
END-COMPUTE      paragraphs=['MAIN-PARA', 'END-COMPUTE']    <-- PHANTOM
```

`warnings=[]` in every case. The five arithmetic terminators are affected;
the control-flow and string terminators are handled correctly. It occurs
with or without an `ON SIZE ERROR` clause present, so it is independent of
Finding 1.

This is the same bug class as the `ROUNDED`-after-`GIVING` phantom
paragraph fixed 2026-07-21 (`.okf/log.md`) — and it was found the same way:
by running a fixture rather than reading the grammar.

### Why it matters to mockymock

Every paragraph-scoped guarantee is computed against a program shape that
does not match what GnuCOBOL compiles. Observed directly:

```
boundary_sites: [('CALL', ('VISIBLE',),  'MAIN-PARA', 9),
                 ('CALL', ('INIFPGM',),  'END-ADD',  15),   # wrong paragraph
                 ('STOP RUN', (),        'END-ADD',  17)]   # wrong paragraph
```

`PERFORM MAIN-PARA` in a `.cut` file therefore scopes reachability to a
fraction of the paragraph the compiler will actually execute. Running the
`END-ADD` fixture end-to-end produced:

```
TESTSUITE: SIZEPROB
  [CRASH] reaches DONE
1 run, 0 failed, 1 crashed
```

— a `STOP RUN` that terminator neutralization skipped because it believed
the statement lived in an unreachable paragraph. The user sees `[CRASH]`
with no explanation; the actual cause is invisible.

### Recommendation

Two tracks, both worth doing:

1. **Upstream (`cobol-parser`)** — the real fix: the arithmetic statement
   parsers must consume their own `END-xxx` terminator the way the control-flow
   parsers do. This is the same neighbourhood as the `ROUNDED` fix.
2. **Defense-in-depth here (mockymock)** — regardless of upstream, mockymock
   should not silently accept a paragraph whose name is a COBOL scope
   terminator. A fail-closed guard in the refusal gate — refuse with a new
   code (e.g. `PARSE_PHANTOM_PARAGRAPH`) when a paragraph name matches one
   of the five affected terminators — converts a silent-wrong result into a
   loud refusal, and would have caught both this bug and the `ROUNDED` one
   at the moment they appeared.

   **Match the exact five names, not a pattern.** The tempting form is
   `^END-[A-Z]+$`, and it is wrong: it also matches `END-RUN`, `END-JOB`,
   `END-PROCESS` and similar, which are perfectly legal (and, in the wild,
   common) paragraph names. The current corpus happens to contain no
   `END-*` paragraph at all —

   ```bash
   grep -rniE "^ {7}END-[A-Z0-9-]+\." examples/ tests/   # 0 matches
   ```

   — but a 24-program corpus is not evidence that real customer code
   never names a paragraph `END-OF-JOB`. A guard that refuses valid
   programs is a worse regression than the bug it catches. Restrict it to
   `END-ADD`, `END-SUBTRACT`, `END-MULTIPLY`, `END-DIVIDE`, `END-COMPUTE`,
   which are reserved words and can never be legal paragraph names, giving
   a zero-false-positive guard. Revisit only if upstream fixes are found to
   affect other terminators.

   Given that mockymock's value proposition is
   fail-closed-under-*uncertainty*, this guard belongs in the product, not
   just in the upstream fix.

---

## Finding 3 — CI has had no test signal since 2026-08-09 (HIGH, process)

Every `CI` run on `main` since **2026-08-09T16:14Z** has failed. Only the
`lint` job passes; all five test jobs (`test` × Python 3.11/3.12/3.13,
`test-cross-platform` × macOS/Windows) die at the same step:

```
Check out cobol-parser (sibling editable dependency)
##[error]fatal: could not read Username for 'https://github.com':
terminal prompts disabled
```

`.github/workflows/ci.yml` falls back to `secrets.GITHUB_TOKEN` when
`secrets.COBOL_PARSER_PAT` is absent, and `GITHUB_TOKEN` cannot read a
different private repo. The workflow's own comment predicted this failure
mode verbatim as a "KNOWN GAP" — the prediction has now come true, most
likely because the PAT expired or was rotated.

Two merges landed on `main` today (#55, #57) with CI red. The 20-finding
remediation in #57 was validated only on the maintainer's laptop.

**Recommendation:** rotate `COBOL_PARSER_PAT` (or switch to a
fine-grained deploy key / GitHub App token with a documented expiry
reminder). Then consider making this failure *impossible to merge through*
rather than merely visible — a required status check on `test`, or a
`workflow_run` alert.

To be precise about what this did and did not cause: green CI would **not**
have caught Findings 1 or 2 — both predate the outage by weeks, and no
existing test asserts anything about `on_size_error`, so there was nothing
to fail. The gap that would have caught them is add-on #6 (parser-agreement
contract suite), not CI uptime. What the outage does mean is narrower and
still serious: the single most load-bearing dependency here is a pinned
private parser, and for two days the mechanism that proves mockymock still
agrees with it has been off — including across two merges to `main`.

---

## Carried-over open items (verified still open, not re-argued)

Re-checked against current `HEAD`; each is documented in a prior audit and
remains genuinely open. No new analysis, listed so the roadmap is complete.

| Item | Source | Verified state |
|---|---|---|
| README has no "what a passing run proves" section | Readiness F1 | **Still absent** — README headers are Installation / Example & usage / Design goals / Credits. Recommended by every prior audit; ~5 weeks open. See below. |
| `EXPECT` is equality-only (`TO BE`) | Readiness F6 | Confirmed — no comparison/range/substring forms in `dsl/parser.py` |
| No argument capture / spies on mocked `CALL`s | Readiness F6 | Confirmed — tallies only |
| No cross-mock ordering assertions | Readiness F6 | Confirmed |
| CSV-sourced `ROW`s | [design doc 2026-07-31](2026-07-31-csv-sourced-rows-design.md) | Designed, **not implemented** — no CSV handling in `dsl/parser.py` |
| `SORT`/`MERGE`/`RELEASE`/`RETURN` refused | Readiness F5 | Confirmed — `UNSUPPORTED_SORT_MERGE` in `refusal.py` |
| No large-program (1000s of lines) corpus test | Readiness F8 | Confirmed |
| No timing data in JUnit/JSON reports | Audit 5.3 | Confirmed |
| No report written on refusal/compile-failure exit | Audit 4.9 | Confirmed |
| Unbounded subprocess output capture | Audit 4.7 | Confirmed — `subprocess.run(capture_output=True)` throughout `docker_toolchain.py` |
| `run` has no `--timeout` (only `mutate` does) | Audit 4.10 | Confirmed |
| Fidelity ceiling: GnuCOBOL ≠ IBM Enterprise COBOL | Readiness F1 | Structural, permanent by design |

### On the README gap specifically

This is the cheapest high-value item in the whole backlog and it has
outlived four audits. mockymock's honest claim is narrow and defensible: *a
passing run proves the program's own logic behaves correctly under
GnuCOBOL semantics, with its external boundaries replaced by declared
mocks.* It does **not** prove EBCDIC collation, COMP-3 sign edges, IBM
intermediate-arithmetic precision, numeric-edited PICTURE behavior, or IBM
intrinsic semantics. Stating that plainly costs one short section and
converts the framework's biggest structural limitation from a latent
surprise into a documented boundary. Recommend writing it as part of the
Finding 1 fix.

---

## Structural observations

The prior audits were correctness-focused and underweighted shape. Two
things stand out:

- **`refusal.py` is 2084 lines** and is the safety-critical heart of the
  tool — every fail-closed guarantee routes through it. It is well
  commented, but at this size the cost of verifying a change is high and
  rising. Worth splitting along its natural seams (reachability BFS /
  terminator analysis / boundary-coverage checks / scoped refusals) before
  it grows further. Not urgent; do it the next time a change there feels
  risky.
- **`cli/main.py` is 1739 lines** with eleven inline `_cmd_*` handlers, and
  the 2026-08-01 audit had to leave three findings open specifically
  because `cli/main.py` was untestable in isolation. That is the real cost:
  the module's shape is now blocking remediation of other findings.
  Extracting each `_cmd_*` into `mockymock/cli/commands/<name>.py` with the
  pure logic separated from argparse/IO wiring would unblock 4.9, 5.3, and
  4.10 at once. **Recommend doing this before, not after, those three
  fixes.**

An observation in the other direction: the boundary-category coverage here
(`CALL` incl. MQ, all file I/O verbs, `EXEC SQL`/`CICS`/`DLI`, `ACCEPT`,
flow/paragraph mocks) with 12 distinct refusal codes, plus the DAP debugger,
coverage reporting, mutation testing, and mainframe export, is an unusually
complete surface for a tool this young. The gaps found here are narrow
seams in a broad, well-built structure.

---

## Prioritized recommendations

### Do now
1. **Rotate `COBOL_PARSER_PAT`** (Finding 3). Nothing else can be trusted
   until CI runs again. Minutes. **Still open** — needs GitHub secrets
   access this session doesn't have.
2. ~~Add `on_size_error`/`not_on_size_error` to `_NESTED_STATEMENT_ATTRS`~~
   (Finding 1) — **DONE 2026-08-10**, TDD, verified end-to-end.
3. ~~Add the phantom-paragraph fail-closed guard~~ (Finding 2, track 2) —
   **DONE 2026-08-10**, TDD, verified end-to-end. The upstream
   `cobol-parser` fix (track 1) is still open — worth filing there.
4. **Write the README "what a passing run proves" section.** Under an hour,
   open since 2026-07-06. Still open.

### Do next
5. Split `cli/main.py` into per-command modules — unblocks three
   carried-over findings.
6. Then close 4.9 (report on refusal/compile-failure), 5.3 (timing data),
   4.10 (`run --timeout`, richer exit codes).
7. Make `test` a required status check so a red CI cannot be merged through.

### Do when convenient
8. Bounded/streaming subprocess capture (4.7) — now verifiable, since
   Docker works in this environment.
9. Split `refusal.py` along its seams.
10. Add one genuinely large program (1000s of lines) to the corpus and
    measure the refusal rate at scale (Readiness F8) — the untested
    assumption is that whole-file all-or-nothing compilation degrades
    gracefully with size. It probably does not.

---

## Proposed add-ons

Sourced from the documented backlog and from gaps this audit surfaced.
Ordered by (value ÷ effort). Items 1–4 are backlog items with designs or
prior recommendations behind them; 5–8 are new proposals.

**1. Richer `EXPECT` assertions.** `TO BE GREATER THAN` / `LESS THAN` /
`BETWEEN x AND y` / `CONTAINS` / `NOT TO BE`. Equality-only forces
contortions for anything computed. Highest ergonomic return per line of
code in the DSL, and purely additive to the grammar.

**2. Argument capture / spies on mocked `CALL`s.** Today you can assert a
call happened *n* times but not *what it was called with*. `VERIFY CALL
"SUBPGM" WAS CALLED WITH WS-ACCT-ID` closes the single largest hole in the
assertion model — a test can currently pass while passing garbage across a
boundary.

**3. CSV-sourced `ROW`s.** Already designed
([2026-07-31](2026-07-31-csv-sourced-rows-design.md)), never built. Inline
`ROW` lines cap `PROVIDER` at toy table sizes; real regression corpora live
in files.

**4. Cross-mock ordering assertions.** `VERIFY OPEN INV-FILE BEFORE READ
INV-FILE`. Sequencing bugs are a real COBOL failure mode and are currently
unassertable.

**5. `mockymock doctor`.** One command that checks Docker reachability and
container health, the resolved `cobolparser` version *against the pin*, the
GnuCOBOL image, and PATH sanity — printing a diagnosis rather than a
downstream error. Two of this project's recurring time sinks are
drifted-checkout-vs-pin (recorded twice in project memory) and Docker
availability. A `doctor` command turns both into a one-line answer, and
would have flagged this very session's `8197d5e` vs `83478ba7` drift
immediately.

**6. A parser-agreement contract suite.** Findings 1 and 2 are both
mockymock silently disagreeing with `cobolparser` about program shape.
`tests/unit/test_bundle_surface.py` already pins part of the bundle
surface; extend that idea to a table of small fixtures asserting *every*
nested-clause attribute name mockymock relies on still exists and still
holds statements at the pinned commit. A pin bump that changes AST shape
then fails loudly in CI instead of silently narrowing the refusal gate.
**This is the systemic fix behind Finding 1** — worth more than the
two-line fix itself.

**7. A refusal-rate report.** `mockymock analyze --refusal-report` over a
directory: how many programs refuse, by code, ranked. Turns "will this work
on our codebase?" — the first question any real adopter asks — into a
number produced in one command, and directly serves Readiness F8. Most of
the machinery exists in `analyze` and `scripts/corpus_sweep.py`; this is
mostly aggregation and presentation.

**8. Boundary-coverage reporting.** Line coverage exists; the more
meaningful metric for this tool is *boundary* coverage — of the N mockable
boundaries in this program, how many did the suite exercise? That is the
number that tells a team whether their `.cut` files actually pin the
program's external behavior, and it is a metric no general-purpose coverage
tool can produce. Strong differentiator, moderate effort, builds on
`mock_surface` which already enumerates exactly the denominator.

---

## Appendix — reproduction

All fixtures below were run at `cobolparser@83478ba7` in an isolated venv
with a live Docker daemon.

```bash
uv venv pinvenv --python 3.13
VIRTUAL_ENV=pinvenv uv pip install \
  "cobolparser @ git+https://github.com/Landparty/cobol-parser.git@83478ba735402f88f3005af529c0fed633632096"
VIRTUAL_ENV=pinvenv uv pip install --no-deps -e .
```

Finding 1 — silent PASS with an unmocked boundary:

```cobol
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SILENT.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-X      PIC 9(4) VALUE 1.
       01 WS-RESULT PIC X(10) VALUE "UNSET".
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE "START" TO WS-RESULT.
           ADD 1 TO WS-X
               ON SIZE ERROR
                   CALL "AUDITPGM" USING WS-RESULT.
           MOVE "DONE" TO WS-RESULT.
```
```
TESTSUITE "SILENT"

TESTCASE "no mock declared for the CALL hidden in ON SIZE ERROR"
    PERFORM MAIN-PARA
    EXPECT WS-RESULT TO BE "DONE"
```

Swap the `ADD ... ON SIZE ERROR` for `IF WS-X > 9000 ... END-IF` to get the
correct `UNMOCKED_CALL` refusal. Replace the nested `CALL` with
`PERFORM ERR-PARA`, and put the unmocked `CALL` in `ERR-PARA`, for the
reachability-BFS variant.

Finding 2 — phantom paragraph:

```python
from cobolparser import parse_cobol
r = parse_cobol(src_with("           ADD 1 TO WS-X\n           END-ADD.\n"))
[p.paragraph_name for p in r.ast.procedure_division.paragraphs]
# ['MAIN-PARA', 'END-ADD']   -- and r.warnings == []
```
