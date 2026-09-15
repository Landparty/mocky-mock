---
type: Test Suite
title: Testing
description: Unit vs. integration split, the Docker-availability skip guard, the fixtures/ corpus, and the worked GnuCOBOL examples (INVUPDT, ORDRPROC, CUSTINQ, RATERTE, CUSTPROG, CLAIMSEG, FLOWMOCK, TAXFILE, STATELKUP, REGNAVG, CPYPROC, plus the real-world/ and nist-cobol85/ example sets covered by their own READMEs).
tags: [testing, ci, examples, fixtures]
timestamp: 2026-09-15T00:00:00Z
---
# Overview

Two-tier split under `tests/`:

| Tier | Path | What it exercises | Docker required? |
|------|------|--------------------|-------------------|
| Unit | `tests/unit/` | DSL parser/generator, splicer, orchestrator, naming, refusal rules, SQLCA, sandbox, source maps, reporting -- all in-process, no compiler | No |
| Integration | `tests/integration/` | Full pipeline: parse -> splice -> compile with real GnuCOBOL (in Docker) -> run -> assert exit code | Yes (skipped otherwise) |

Unit tests (`tests/unit/`, 93 `test_*.py` files against
`tests/integration/`'s 36; 1,595 tests, 7.5s, no Docker) include `test_dsl_parser.py` / `test_dsl_parser_v2.py`,
`test_dsl_generator.py`, `test_injector.py`, `test_mock_surface.py` / `_v2.py`,
`test_orchestrator.py`, `test_refusal.py` / `_v2.py`, `test_dynamic_call.py`,
`test_sqlca.py`, `test_sandbox.py`, `test_source_map.py`, `test_stub_writer.py`,
`test_naming.py`, `test_reset.py`, `test_report.py`, `test_driver.py`,
`test_docker_toolchain.py`, `test_cli_docker.py`, `test_smoke.py`,
`test_stub_expectations.py` (2026-08-04: the `*> STUB EXPECT` raw-text
scanner), `test_record_rewrite.py` (2026-08-04: matching a scan against a
recorded run, value rendering, `.cut` rewriting -- see
docs/2026-08-04-record-expectations-design.md),
`test_malformed_input_sweep.py` (2026-08-13: a standing, parametrized
"garbage input never surfaces an untyped exception" contract check for
`dsl.parser.parse_cut`/`report.results.parse_stdout`, distinct from the
many shape-specific tests already covering each parser elsewhere -- see
[log.md](log.md)'s 2026-08-13 entry). The `_v2` files
track a second generation of the DSL/mock-surface grammar living alongside the
original -- both are still exercised, implying the surface is mid-migration
rather than the v1 files being dead weight.

# Docker-availability skip pattern

Integration tests need a real GnuCOBOL compiler, which mockymock only ships
via a Docker image (`mockymock-gnucobol`) -- there is deliberately no
GnuCOBOL install step in CI (see `.github/workflows/ci.yml` comment: "No
GnuCOBOL install: the toolchain is Docker-only"). Gating lives in one shared
module:

```python
# tests/integration/_docker.py
@functools.lru_cache(maxsize=1)
def docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    return subprocess.run(["docker", "info"], ...).returncode == 0

requires_docker = pytest.mark.skipif(not docker_available(), reason="Docker daemon not reachable")
```

Every integration test file decorates its test functions with
`@requires_docker` (imported from `tests.integration._docker`). The check is
memoized per test process (`lru_cache(maxsize=1)`) so the `docker info`
subprocess only runs once no matter how many integration tests are collected.
This means:

- On a machine/CI runner with no Docker daemon, the entire integration tier
  reports as **skipped**, not failed -- a green run does not by itself prove
  the compile-and-run path works.
- On first use per machine, the `mockymock-gnucobol` image is built
  on-demand (~1 min), which is why CI comments call out the extra latency on
  a cold cache.

# fixtures/ corpus

`tests/integration/fixtures/` holds `.cbl`/`.cut` pairs used directly by the
integration tests (not the polished `examples/` programs -- these are
narrower, purpose-built regression fixtures):

| Fixture | Exercises | Test file |
|---------|-----------|-----------|
| `dynamic_call.cbl` / `.cut` | Dynamic `CALL WS-PGM-NAME` (identifier-valued program name) matched by one bare-key `MOCK CALL` whose body branches on the runtime value -- previously blanket-refused as `DYNAMIC_CALL` | `test_dynamic_call_example.py` |
| `nested_boundaries.cbl` / `.cut` | Mock boundaries nested inside other control structures | `test_nested_boundaries.py` |
| `thru_boundaries.cbl` / `.cut` | `PERFORM ... THRU` range expansion in reachability analysis | `test_thru_boundaries.py` |
| `walking_skeleton.cbl` (no `.cut`) | Minimal smoke-test program for the CLI end to end | `test_walking_skeleton.py` |
| `copybook_example/` (`MAINPGM.cbl`, `MAINPGM.cut`, `copybooks/`) | `COPY` expansion feeding the mock surface / splicer | `test_copybook_expansion.py` |
| `record_expectations_example.cbl` / `.cut` | `run --record-expectations`: a `*> STUB EXPECT` comment becomes a real `EXPECT` after a real run, idempotent on a second pass (the golden re-run drift test), and a case excluded by `--case` is left untouched | `test_record_expectations.py` |

`test_cli.py` covers CLI argument handling generically (not tied to one fixture).

Each fixture pair follows the same shape as the worked examples: a `.cbl`
program plus a `.cut` (mockymock's own DSL file) that both declares `MOCK`
bodies for boundary statements and asserts outcomes with `EXPECT` / `VERIFY`.
The dynamic-call test additionally shows the pattern used to assert
*failure* modes: it round-trips the fixture's own `.cut` text, mutates one
literal (`EXPECT WS-TOTAL TO BE 5` -> `... 6`, or `WAS CALLED 3 TIMES` -> `...
2 TIMES`), writes it to `tmp_path`, and asserts `exit_code == 1` -- proving
the harness actually fails closed on a wrong expectation/verify count, not
just that the happy path returns 0.

# Worked examples (examples/)

Documented, runnable programs under `examples/` -- these are polished
end-to-end demos (with READMEs), distinct from the terser
`tests/integration/fixtures/` corpus, and are also driven by their own
integration tests. Beyond the eight hand-written ones below (INVUPDT,
ORDRPROC, CUSTINQ, RATERTE, CUSTPROG, CLAIMSEG, REGNAVG, FIXTUREDEMO),
`examples/real-world/` (17 programs as of 2026-09-15:
ACCTMNT, ACCTPRG, ACHPROC, CHKCLR, CTRRPT, DEPTBMP, DEPTIMSM, DEPTMQC,
DEPTMQP, DORMACCT, EODPROC, FNDTXFR, GLRECON, INTCALC, LNRECOV, LOANPMT,
STMTGEN -- with its own README) and
`examples/nist-cobol85/` (IC101A, IC116M, IC117M, OBIC1A) hold additional
examples driven from real corpora -- see their own READMEs for provenance
and what each demonstrates. **Four of the real-world programs (`ACCTMNT`,
`ACHPROC`, `CHKCLR`, `INTCALC`) are currently refused by `run`/`lint`**
while that README still claims "238 test cases total, 0 failing" -- the
2026-09-05 audit's finding 2/MEDIUM, a reachability-gate regression
bisected to `162f205` and still open; see [log.md](log.md)'s seventh-audit
entry. `examples/flowmock/`, `examples/taxfile/`,
`examples/statelkup/` (flow-target mocks, `BEFORE-EACH`/`FILE-STATUS IS`,
`PROVIDER`), and `examples/cpyproc/` (a PROCEDURE DIVISION copybook -- a
whole paragraph, not just data -- invoked via `PERFORM` and, in a second
test case, stubbed via `MOCK PARAGRAPH`) are documented by their own
READMEs only -- this concept's per-example write-up section below was
never extended to them; a pre-existing gap, not introduced here.

## INVUPDT (`examples/invupdt/`)

Inventory updater touching **every** boundary category mockymock supports in
one program:

| Boundary | COBOL statement | Mock directive |
|----------|-----------------|-----------------|
| File open (2 files, 1 OPEN) | `OPEN INPUT INV-FILE OUTPUT RPT-FILE` | `MOCK OPEN INV-FILE` |
| Sequential read loop | `READ INV-FILE AT END ...` | `MOCK READ INV-FILE` (tally-driven EOF) |
| Report write | `WRITE RPT-REC` | `MOCK WRITE RPT-REC` |
| File close | `CLOSE INV-FILE RPT-FILE` | `MOCK CLOSE INV-FILE` |
| DB2 update | `EXEC SQL UPDATE INVENTORY ... END-EXEC` | `MOCK SQL "UPDATE INVENTORY"` |
| MQ notification | `CALL "MQPUT" USING MQ-COMPCODE` | `MOCK MQ "MQPUT"` |
| Operator input | `ACCEPT WS-CONFIRM` | `MOCK ACCEPT WS-CONFIRM` |

Notable design points the README calls out explicitly:

- **Tally-driven EOF**: the `READ` mock keeps its own tally field
  (`UT-READ-INV-FILE-TALLY`) to return two records, then signal end-of-file
  on the third call -- no real `INV.DAT` needed in the sandbox.
- **FD record areas without OPEN**: the `READ` mock `MOVE`s into `INV-QTY`
  (a FILE SECTION field) even though `INV-FILE` is never actually opened.
- **Static reachability still requires a mock for unreached code**: test
  case 2 hits EOF on the first read and so never executes the `WRITE`, but
  because `WRITE` is *statically* reachable it still needs a `MOCK WRITE` --
  verified via `VERIFY WRITE RPT-REC WAS PERFORMED NEVER`. This is a direct
  worked demonstration of reachability-driven refusal (see
  [analysis](analysis.md)): mockymock reasons about what a real GnuCOBOL
  compile could execute, not just what one test run happens to hit.
- **Error-path testing**: test case 2 forces `SQLCODE = -911` and asserts
  the program's failure branch actually runs.
- Also demonstrates `EXEC SQL INCLUDE SQLCA END-EXEC` replaced with a
  generated SQLCA so mock bodies can set `SQLCODE` directly (see
  [runtime](runtime.md) for the generated-SQLCA mechanism).

Run: `mockymock run examples/invupdt/INVUPDT.cbl --cut examples/invupdt/INVUPDT.cut`

## ORDRPROC (`examples/ordrproc/`)

Minimal program calling an external `DISCRATE` subprogram for a discount
rate, then computing a net amount. Demonstrates static `CALL` mocking
plus `CAPTURE ARG <n> INTO <target>` — capturing the `ORD-AMOUNT` value
the program passes into `DISCRATE` and asserting it with an ordinary `EXPECT`.
The README frames it as the smallest possible teaching example: flip
`EXPECT WS-CAPTURED-AMOUNT TO BE 100.00` to a wrong value to see a FAIL, or run
`mockymock generate ORDRPROC.cbl` to see what auto-scaffolding produces from
a bare `.cbl` with no `.cut` at all.

Run: `mockymock run ORDRPROC.cbl --cut ORDRPROC.cut`

## CUSTINQ (`examples/custinq/`)

The first `EXEC CICS` worked example -- closes the real-world-readiness
audit's Finding 5 row that CICS was "classified but never proven, no
example, absent from corpus" (see `docs/2026-07-06-real-world-readiness-audit.md`).
A CICS customer-inquiry transaction: `EXEC CICS READ` looks up a customer,
a plain-COBOL paragraph flags a low balance, `EXEC CICS RETURN` ends the
transaction.

| Boundary | COBOL statement | Mock directive |
|----------|-----------------|-----------------|
| CICS file read | `EXEC CICS READ DATASET("CUSTFILE") ... END-EXEC` | `MOCK CICS "READ"` |
| CICS transaction return | `EXEC CICS RETURN END-EXEC` | `MOCK CICS "RETURN"` |

Notable design points the README calls out explicitly:

- **No CICS translator or runtime needed.** `EXEC CICS` blocks are spliced
  out entirely before compilation -- mocked ones become the test case's
  mock body, unmocked-but-reachable ones become a trap stub (same
  mechanism as `EXEC SQL`/`EXEC DLI`, see [splicer](splicer.md)). GnuCOBOL
  never sees a raw `EXEC CICS` block, so this compiles and runs in the
  plain `mockymock-cobc` container.
- The last test case drives `0000-MAIN`, the program's real entry point,
  through its full `PERFORM` chain to `GOBACK` -- the terminator-
  neutralization feature (`docs/2026-07-08-goback-stop-run-support-design.md`)
  applied to a CICS program.

Run: `mockymock run examples/custinq/CUSTINQ.cbl --cut examples/custinq/CUSTINQ.cut`

## RATERTE (`examples/raterte/`)

A business-flavored counterpart to the bare `tests/integration/fixtures/dynamic_call.cbl`
regression fixture: an account-tier code drives which of three interest-rate
subprograms (`STDRATE`/`PRMRATE`/`VIPRATE`) gets called *dynamically*
(through an identifier, not a literal program name) -- the classic COBOL
dispatch-table pattern.

| Boundary | COBOL statement | Mock directive |
|----------|-----------------|-----------------|
| Dynamic subprogram call | `CALL WS-PGM-NAME USING WS-BALANCE WS-RATE` | `MOCK CALL WS-PGM-NAME` |

One bare-identifier `MOCK CALL WS-PGM-NAME` directive covers all three
routing targets; the mock body branches on `WS-PGM-NAME`'s own runtime
value to return a different rate per target, and the whole `CALL`
statement is spliced out so `STDRATE`/`PRMRATE`/`VIPRATE` never need to
exist as real subprograms. A fourth test case exercises the `EVALUATE`'s
`WHEN OTHER` fallback.

Run: `mockymock run examples/raterte/RATERTE.cbl --cut examples/raterte/RATERTE.cut`

## CUSTPROG (`examples/custprog/`)

Elevates `tests/integration/fixtures/sql_cursor_example/` (unchanged
COBOL/`.cut`, plus a README) into a documented example -- the two DSL
features it proves had no polished example before this: `MOCK SQL "..."
ROWS (...)` cursor-fetch sugar (a `FETCH`-loop's rows expressed as data,
with `SQLCODE` auto-set to 0 per row and 100 once exhausted) and a
DCLGEN-style `EXEC SQL INCLUDE <member>` (non-`SQLCA`) resolved via
`--copybook-path` into real WORKING-STORAGE host variables.

Run: `mockymock run examples/custprog/CUSTPROG.cbl --cut examples/custprog/CUSTPROG.cut --copybook-path examples/custprog/copybooks`

## CLAIMSEG (`examples/claimseg/`)

The `MOCK DLI` counterpart to `examples/custinq`'s CICS proof: a raw
`EXEC DLI GU`/`EXEC DLI ISRT` claim-retrieval-and-payment-insert program
(as opposed to `examples/real-world/ACCTPRG`'s/`DEPTIMSM`'s `CALL
'CBLTDLI'` IMS idiom). `MockCategory.DLI` was classified since the v2
all-boundaries design but, before this example, proven only by unit tests
-- the same "classified but never proven" gap CICS had before CUSTINQ
closed it. Also repeats INVUPDT's static-reachability-driven-refusal
lesson: a test case that skips the `ISRT` branch at runtime still must
mock it, because it's statically reachable from the `PERFORM` target.

Run: `mockymock run examples/claimseg/CLAIMSEG.cbl --cut examples/claimseg/CLAIMSEG.cut`

## REGNAVG (`examples/regnavg/`)

Proves four features that, before this example, were checked only by
unit/integration tests, never by a worked `examples/` program: subscripted
`.cut` `MOVE`/`EXPECT` targets (`WS-MONTH-AMT(1, 1)` on a 2-D `OCCURS`
table, all three subscript forms `_SUBSCRIPTED_NAME` accepts), `REDEFINES`
data items (`WS-REGION-AVG-DISPLAY`/`WS-REGION-AVG-NUMERIC`, two siblings
aliasing one `PIC 9(5)V99` field -- the same shape as `test_reset.py`'s
regression fixture), `DIVIDE ... GIVING ... ROUNDED` (a real rounding case,
`151.10 / 3 = 50.3666...` must read back `50.37`, not the truncated
`50.36`), and `run --trace` (its README embeds a real captured trace).
Its three test cases double as a reset-correctness proof, deliberately
made load-bearing: the program is split into two paragraphs (one per
region) specifically so each case's own `PERFORM` target never touches
the *other* region's `WS-REGION-AVG` slot -- so when a case reads that
untouched slot back as zero, it's proof `WS-REGION-AVG-TABLE`'s single
`INITIALIZE` (a group with no `VALUE` clause, containing an
`OCCURS`-of-`REDEFINES-group`) actually reset it between cases, not an
artifact of that run's own arithmetic recomputing it to zero anyway. An
earlier single-paragraph draft (one loop over both regions) had exactly
that flaw -- caught in review, not by a failing test, since the flawed
version still passed -- and was restructured before committing. The
`DIVIDE` targets an *unsubscripted* scratch field, then `MOVE`s it into
the table cell, and `CALL "LOGALERT"` never takes the average as an
argument -- both are workarounds for cobolparser gaps confirmed against
the exact pinned commit (a subscripted `GIVING`/`CALL ... USING` operand
outside a `PERFORM VARYING` body), not stylistic choices. See
[log.md](log.md)'s 2026-07-21 entry for the full account, including a
stale-`cobolparser`-install detour and a second, easy-to-miss gotcha it
surfaced: the sibling checkout's `HEAD` had already raced two commits
past the pin, so an initial "fixed the environment, now it's clean" was
still verified against the wrong commit.

Run: `mockymock run examples/regnavg/REGNAVG.cbl --cut examples/regnavg/REGNAVG.cut`

## FIXTUREDEMO (`examples/fixtures/`)

The odd one out among these eight: not hand-written, and not owned solely
by this repo. `FIXTUREDEMO.cbl` and `FIXTUREDEMO.bundle.json` (a
`FixtureBundle` JSON at a fixed seed, 42) are copied verbatim from the
sibling `Landparty/cobol-parser` repo's own `examples/fixtures/` -- the
`gen-fixtures` program-scoped test-data initiative's Phase 9 worked
example, the cross-repo golden anchor proving the whole pipeline (program
-> bundle -> `.cut` -> green run) end to end with one small program that
touches all four boundary categories the initiative supports (`ACCEPT`,
`OPEN`/`READ`/`CLOSE`, `SQL`, `CALL`) with zero unresolved gaps -- unlike
`examples/custprog/` above, which deliberately keeps one.

`FIXTUREDEMO.cut` is *generated* here, from that exact bundle
(`mockymock generate ... --fixtures FIXTUREDEMO.bundle.json`, deliberately
not `--with-data`, so this golden is pinned against a fixed JSON rather
than whatever cobol-parser commit `pyproject.toml` happens to have pinned
at the moment a contributor re-runs the regeneration command), then
checked in as this repo's own golden. Three regression checks in
[`tests/integration/test_fixturedemo_golden.py`](../tests/integration/test_fixturedemo_golden.py)
run Docker-free on every CI lane: the generated `.cut` is byte-identical
to the checked-in one, regeneration is deterministic (two independent
calls agree), and the checked-in `.cut` still passes `mockymock lint`. A
fourth, `@requires_docker`, proves the real run stays green.

If cobol-parser's own copy of `FIXTUREDEMO.cbl`/`FIXTUREDEMO.bundle.json`
changes, both files must be re-copied here and `FIXTUREDEMO.cut`
regenerated in the same change -- see either repo's own
`examples/fixtures/README.md`.

Run: `mockymock run examples/fixtures/FIXTUREDEMO.cbl --cut examples/fixtures/FIXTUREDEMO.cut`

# Gotchas

**A globally `uv tool install`-ed `mockymock` on `PATH` goes stale silently.**
It is a separate, non-editable install (its own isolated venv) that does
**not** track local checkout changes -- unlike `python -c "import
mockymock"`, which resolves the editable sibling checkout. A worked example
that fails against the `PATH` binary but passes when invoked in-process from
the checkout (`from mockymock.cli.main import main; main([...])`) is a stale
global install, not a regression in the example or a bug to chase in the
engine. Reinstall with `uv tool install --from . mockymock --force` (run
from the `mocky-mock` repo root) before trusting a "some examples fail"
result from that binary. This bit both a fresh `examples/custprog/` addition
(missing the `ROWS` grammar) and, less obviously, `ACCTPRG`/`DEPTIMSM`
(missing unrelated later fixes) in the same sitting -- see
[log.md](log.md)'s 2026-07-18 entries. The `../mocky-mock-vscode-extension/`
extension resolves `mockymock` from `PATH` by default
(`mockymock.executablePath` empty), so this same staleness silently breaks
its Test Explorer results too.

**A non-editable `cobolparser` install can silently shadow the editable
sibling checkout, even for `python -c "import cobolparser"` (not just the
`PATH` binary above).** Recurred 2026-07-21 while building
`examples/regnavg/`: `pip show cobolparser` reported version `1.2.0` but
its `direct_url.json` pinned commit `c9a94999` (2026-07-10) rather than
the same-day `4db8394` DIVIDE/MULTIPLY `ROUNDED` fix `pyproject.toml`
already pins -- eleven days stale, and silent, because `import
cobolparser` still resolved to *something*. Symptom: cobolparser emits a
phantom paragraph literally named `ROUNDED` (see [log.md](log.md)'s
"DIVIDE/MULTIPLY `GIVING ... ROUNDED`" entry), reparenting every statement
after a `DIVIDE ... GIVING ... ROUNDED` into it -- which then surfaces as
a spurious `UNMATCHED_MOCK` for any boundary mock placed after it in the
same paragraph, not as a parse warning. Root cause matches the 2026-07-09
log entry exactly: `pip install --no-deps -e ../cobol-parser` alone isn't
enough after a prior non-editable install -- a stale
`site-packages/cobolparser/` directory (confirmed here: a near-empty
`analysis/` subfolder) survives uninstall and is treated as an implicit
namespace package, shadowing the editable redirect. Fix: delete that
directory by hand, then reinstall editable; confirm with
`python -c "import cobolparser; print(cobolparser.__file__)"` -- it must
print a path inside the sibling `cobol-parser` checkout, not
`site-packages`.

**Fixing the above isn't the same as verifying against the pin.** After
the fix, `import cobolparser` resolves to the *editable sibling
checkout's current `HEAD`* -- which is the normal, correct dev setup
(`requirements-dev.txt`), but `HEAD` routinely races ahead of the commit
`pyproject.toml`/`ci.yml` actually pin (2 commits ahead here, one of
which -- `4917576`, "fix silent data loss in ... arithmetic clauses" --
changed parsing behavior `4db8394`, the pin, doesn't have). A result
that's clean against `HEAD` can still `PARSE_WARNING` for anyone
resolving the pinned commit (CI, `uv tool install`, a fresh clone). To
verify against the pin specifically without touching the shared sibling
checkout (avoid `git checkout` there --
[[feedback-cobolparser-worktree-isolation]]): build a throwaway venv and
`pip install --no-deps "git+file:///<absolute path to
../cobol-parser>@<pinned commit>"` -- pip clones into its own temp build
dir, so the shared working tree is never touched. Confirm with the same
`direct_url.json` check as above.

**Two more pinned-cobolparser landmines, found 2026-08-10 hunting for a
replacement `UNREACHED_INVOKE_CBL` fixture (audit finding F-0b, once
`INVOKE` itself stopped producing a `PARSE_WARNING` — see
[analysis](analysis.md)'s `PARSE_WARNING` row) — both flagged to
cobol-parser separately, not fixed here, but worth knowing before picking
a stand-in "unsupported verb" line for a mockymock fixture:**
- A bare-identifier operand after several unsupported verbs (`EXHIBIT
  NAMED WS-X.`, `PURGE WS-X.`, and others tried) gets misparsed into a
  *spurious paragraph* named after that identifier, reparenting every
  statement after it — the same failure shape as the DIVIDE/`ROUNDED`
  entry above, different trigger. A quoted-literal operand (`TRANSFORM
  "x".`) avoids it; a bare identifier operand does not.
- A bare `RESUME.` (no operand) hangs cobolparser's parse indefinitely —
  confirmed via `timeout 8`. Never use it, even transiently, without a
  wrapping timeout.

# CI (.github/workflows/ci.yml)

Four jobs: `lint`, `test`, `test-cross-platform`, `cobol-parser-compat`.
**Two of them are switched off.** Triggers are push/PR to `main`, a nightly
`schedule` (cron `17 6 * * *`, there for `cobol-parser-compat`), and
`workflow_dispatch`.

**`test` and `test-cross-platform` both carry `if: false`** ("test suite
removed from CI (too long); run locally"), so neither has run since
`930b391` (2026-08-15). What actually gates a PR today is `lint` plus
`cobol-parser-compat`'s unit run -- the Docker compile/run tier is gated
nowhere, and **a green CI run does not mean the test suite passed**. The
2026-09-05 audit reproduced the cost of this (finding 3: `main` was red on
a `test_smoke.py` invariant nothing was running). The "too long" rationale
does not survive measurement: `tests/unit` is **1,595 passed, 32 skipped
in 7.5s** (measured 2026-09-15 at `9108464`, published cobol-parser, cold
venv), and the audit clocked the same tier at 9.07s. Run `python -m pytest
tests/ -v` locally before pushing; treat the two disabled jobs below as
documentation of what CI *would* cover if re-enabled.

## `lint` (the one always-on gate)

`ubuntu-latest`, Python 3.13, `pip install ruff black mypy` -- then `ruff
check .`, `black --check .`, `mypy mockymock/`. It deliberately installs no
project dependencies: `[tool.mypy]`'s `ignore_missing_imports` covers the
absent `cobolparser`. That shortcut is itself an audit finding (2026-09-05,
finding 4): with the real dependency absent, the whole cobolparser seam
degrades to `Any`, and a clean checkout *with* cobol-parser installed
reports 4 mypy errors this job calls success.

## `cobol-parser-compat` (on, and the only job running tests)

`ubuntu-latest`, Python 3.13, `pip install -r requirements-dev.txt`, then
`pytest tests/unit -v`. Added after the 2026-08-26 audit finding that
`pyproject.toml` pins only a floor (`cobol-parser>=1.7.7,<2`), so any
install resolves whatever cobol-parser most recently published inside that
range. This job installs the **published** package -- no sibling checkout,
no local build, exactly what `pip install mocky-mock` gets -- and runs the
Docker-free unit tier against it, so parser drift shows up as a red
scheduled run rather than on a user's first install. Tests that need parser
behavior newer than the floor skip themselves by capability probe rather
than fail (see `tests/unit/test_enterprise_corpus.py` and
`test_fixture_bundle_contract.py`). That is not free: on the declared
floor, 31 unit tests never execute -- the 22 enterprise-corpus cases plus
9 in `test_verb_coverage_fail_closed.py` (Report Writer nodes, XML PARSE
clauses, `ChainStatement`, communication nodes). Bumping the floor is what
turns them back on.

## `test` (Linux, full pipeline) -- DISABLED (`if: false`)

- Push/PR to `main`, `ubuntu-latest`, Python 3.11/3.12/3.13 matrix.
- `pip install -r requirements-dev.txt` only. There is **no** sibling
  `Landparty/cobol-parser` checkout and no `secrets.COBOL_PARSER_PAT` step
  any more: cobol-parser resolves from PyPI as an ordinary pinned
  dependency (see [integration](integration.md) and
  [publishing](publishing.md)).
- No GnuCOBOL install step -- the Docker toolchain builds
  `mockymock-gnucobol` on first use inside the job (~1 min cold).
- Single run step: `python -m pytest tests/ -v` -- unit and integration
  tests run together; integration tests self-skip if `docker info` fails,
  but `ubuntu-latest` ships Docker so this job would exercise both tiers.

## `test-cross-platform` (Windows + macOS, unit tier only) -- DISABLED (`if: false`)

Added 2026-07-21 as part of a cross-OS install audit (see
[log.md](log.md)'s entry of the same date) -- previously CI ran on
`ubuntu-latest` only, despite the 2026-07-04 Docker-only rewrite's whole
premise being to fix chronic *Windows* compile failures (see
[runtime](runtime.md)). Nothing verified that fix held up outside one
developer's machine -- and since this job was switched off, nothing does
again.

- Matrix of `windows-latest` / `macos-latest`, single Python version
  (3.13) -- this job is about catching OS-specific bugs in the Python/DSL
  layer (paths, encoding, newline handling), not Python-version bugs,
  which the Linux `test` job's 3.11-3.13 matrix already covers.
- `pip install -r requirements-dev.txt`, same as `test` -- `mockymock/analysis/`,
  `mockymock/splicer/`, and `mockymock/cli/` all import `cobolparser` at
  module level, so even the no-Docker unit tier can't import `mockymock`
  without it.
- Runs `pytest tests/unit -v` **only** -- deliberately does not attempt
  the Docker/GnuCOBOL integration tier. `macos-latest` GitHub-hosted
  runners have no reachable Docker daemon (the tier's own
  `@requires_docker` gate skips cleanly there, so `pytest tests/` would
  have been safe on macOS specifically), but `windows-latest` runners
  ship a *Windows-container* Docker Engine -- `docker info` can report a
  live daemon while still being structurally unable to build/run the
  Linux `mockymock-gnucobol` image, which would fail the job loudly
  instead of skipping. Restricting both platforms to `tests/unit`
  sidesteps that asymmetry rather than relying on unverified runner
  behavior.
- Verified locally before adding: `tests/unit` (681 tests at the time)
  passed clean on native Windows Python 3.14.

# Enterprise program-type corpus (2026-09-15)

`tests/fixtures/enterprise/*.cbl` + `copybooks/` mirror cobol-parser's
`tests/samples/enterprise/` -- keep them identical (cobol-parser is the
source of truth). `tests/unit/test_enterprise_corpus.py` runs `mockymock
generate` (in-process `cli.main.main`, no Docker) over every program and
asserts the outcome table `EXPECTED`: a scaffold with test cases, a
scaffold with none (no mockable boundary), or a refusal under exactly one
code. Adding a program type means adding it to both corpora and to that
table; the matrix is `cobol-parser/docs/enterprise-program-types.md`.

Because that corpus exercises what cobol-parser's 2026-09-15 release added
(OO units, DECLARATIVES modelling, the 6.x data clauses), the whole module
skips itself on an older pin -- `pytestmark = skipif(not
hasattr(CobolProgram, "program_attributes"))`, the same capability-probe
pattern `test_fixture_bundle_contract.py` uses. On the declared floor
(`cobol-parser>=1.7.7`) those programs parse with warnings and every
outcome would read `PARSE_WARNING`, saying nothing about mockymock. The
skip is a placeholder for a pin bump, not the end state: until
`pyproject.toml`'s floor moves, `cobol-parser-compat` never runs these
assertions.

# See Also

- [analysis](analysis.md) -- static reachability analysis that determines
  which boundary statements *must* be mocked (the INVUPDT `WRITE` case above
  is a direct consequence of this).
- [splicer](splicer.md) -- how `MOCK` bodies from the `.cut` DSL get spliced
  into the `.cbl` source before it's handed to GnuCOBOL.
- [runtime](runtime.md) -- generated SQLCA, tally fields, and other
  runtime-support scaffolding that mock bodies (like INVUPDT's `READ` tally
  and `SQLCODE` sets) depend on.
