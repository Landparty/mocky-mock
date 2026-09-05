# Project deep audit — 2026-09-05

Seventh framework audit. Scope: the whole repository as it stands at
`b0d5235` (tip of `main`) — packaging and release plumbing, CI, the
dependency seam, the analysis/splicer/runtime pipeline, the example
corpus, security posture, and docs/code consistency.

Method: every finding below was reproduced in this environment, not
inferred from reading. Where a claim is about history, it was bisected
against real checkouts. Where a claim is about CI, it was read off the
actual workflow run. Commands and outputs are quoted inline so each
finding can be re-checked in one step.

Environment: Linux, Python 3.11.15, `cobol-parser` 1.8.4 from PyPI, **no
Docker daemon** — so `tests/integration/` (36 files, all
`@requires_docker`) could not be exercised. Everything below is from the
Docker-free tier.

**Headline:** the project's engineering substance is in good shape — 1,478
unit tests, 88.36% coverage, clean `ruff`/`black`, a genuinely careful
security posture, and unusually good internal documentation. What is
broken is almost entirely the *verification layer around* that substance.
CI stopped running tests on 2026-08-15 for a stated reason that is
measurably false, and in the three weeks since, four defects landed on
`main` that the disabled tests would each have caught immediately —
including one that shipped to PyPI.

---

## Finding 1 — The published 0.8.0 wheel reports `--version` as `0.7.0` (HIGH, confirmed, shipped)

`mockymock/__init__.py` says `0.7.0`; `pyproject.toml` and
`.release-please-manifest.json` say `0.8.0`. `mockymock --version` reads
the former, so every user of the released package is told the wrong
version:

```console
$ python -m mockymock.cli.main --version
0.7.0
```

### Root cause (bisected)

release-please's `python` strategy locates the package's `__init__.py`
from the distribution name. On 2026-08-15, `e26373b "fix: correct project
name in pyproject.toml"` renamed `[project].name` from `mockymock` to
`mocky-mock`. From that point the updater looked for `mocky_mock/__init__.py`,
which does not exist, and silently skipped the file. The evidence is in
which release commits touched it:

| release | commit | touched `mockymock/__init__.py`? |
|---|---|---|
| 0.6.3 | `737d767` | yes |
| 0.6.4 | `04a848a` | yes (last one before the rename) |
| 0.7.0 | `cf135ef` | **no** |
| 0.8.0 | `51d826d` | **no** |

The 0.7.0 drift was noticed and hand-patched inside an unrelated feature
commit (`0fc46f2`, whose message notes "mockymock.__version__ is synced to
0.7.0"). That is a symptom fix: the updater was still misconfigured, so
0.8.0 drifted again — and this time shipped.

### Fix

Point release-please at the file explicitly, so it no longer depends on
the distribution name matching the package directory:

```json
{
  "packages": {
    ".": {
      "package-name": "mockymock",
      "extra-files": [
        { "type": "python", "path": "mockymock/__init__.py" }
      ]
    }
  }
}
```

Then correct `mockymock/__init__.py` to `0.8.0` in the same change.
`tests/unit/test_smoke.py::test_mockymock_has_a_version` already pins the
invariant — it needs no new test, it needs to be *run* (Finding 3).

---

## Finding 2 — Reachability gate falsely refuses a `GO TO` into a `PERFORM ... THRU` terminus (HIGH, confirmed, bisected)

The fail-closed reachability gate treats a `GO TO` target as falling
through into the next paragraph in source order, without accounting for
the target being the **terminus of the `PERFORM ... THRU` range that
contains the `GO TO`**. At that point control returns to the `PERFORM`;
it does not fall through. The gate therefore walks past the range end and
demands mocks for boundaries the program provably cannot reach.

This is the classic COBOL early-exit idiom, and it blocks four shipped
examples (Finding 5).

### Minimal reproduction (37 lines)

```cobol
       PROCEDURE DIVISION.
       0000-MAIN.
           PERFORM 1000-DRIVER
           PERFORM 3000-FINALIZE
           STOP RUN.

       1000-DRIVER.
           PERFORM 2000-WORK THRU 2090-WORK-DONE.

       2000-WORK.
           IF WS-FLAG = 'Y'
               GO TO 2090-WORK-DONE      *> early exit to the range end
           END-IF
           PERFORM 2010-HELPER.

       2090-WORK-DONE.                   *> THRU terminus: PERFORM returns here
           MOVE 'N' TO WS-FLAG.

       2010-HELPER.                      *> NOT reachable by fall-through
           MOVE 'Y' TO WS-FLAG.

       3000-FINALIZE.
           CLOSE OUTFILE.                *> NOT reachable from 1000-DRIVER
```

with a `.cut` whose only case is `PERFORM 1000-DRIVER`:

```console
$ mockymock lint THRUBUG.cbl --cut THRUBUG.cut
mockymock lint: refused (UNMOCKED_FILE_OP): CLOSE boundary at line 37
  (paragraph '3000-FINALIZE', keys OUTFILE) is reachable from '1000-DRIVER'
  but no MOCK directive in this test case matches it
mockymock lint: 1 problem(s) found.
```

Control case — the identical program with the `GO TO` deleted — passes
(`no problems found`), isolating the fall-through closure as the sole
cause.

### Origin

Bisected to `162f205` (2026-08-12) *"fix: close the reachability BFS over
GO TO fall-through"*:

```
5310b46 release 0.6.0                                    -> PASS
a9c7ba6 remediate 19 of the 2026-08-12 audit's findings   -> PASS
dc95c4d key orphan-record skip diagnosis                  -> PASS
162f205 close the reachability BFS over GO TO fall-through -> FAIL
c00c4d2 run reports on refusal/compile failure            -> FAIL
```

That commit fixed a real unsoundness (a fallen-into boundary executing
unmocked) and was right to. The over-approximation is deliberate and
documented in `_reachability.py`:

```python
# `seen & go_to_targets` over-approximates (a paragraph both
# PERFORMed here and GO-TO'd elsewhere still triggers the walk),
# which is the fail-closed direction: at worst an extra required
# mock, never a silently executing unmocked boundary.
hazard_sources = seen & go_to_targets
```

Three follow-ups have since narrowed cascades from this same closure
(`25965c0`, `63b8e69`, `46aa88a`), so the class is known. This case is
not covered by any of them.

### Why "at worst an extra required mock" understates the cost

The mock the gate demands here is one the author *cannot correctly
write*: mocking `CLOSE OUTFILE` to satisfy the gate asserts a boundary
that never executes, and a `VERIFY ... WAS CALLED` on it would be wrong.
The only ways out are to abandon the test case or to mock a fiction. For
four examples in this repo, the answer was to leave them broken.

### Fix

The terminus name is already in hand — `_reachable_paragraphs` calls
`_expand_thru_range` for every `PerformStatement.thru_paragraph`.
Exclude a `GO TO` target from `hazard_sources` when it is the THRU
terminus of a `PERFORM` range that lexically contains the `GO TO`'s own
paragraph; keep the current walk in every other case, including a `GO TO`
reaching that paragraph from outside the range (there the fall-through is
real). Pin it with the reproduction above plus an outside-the-range
negative case, so the fail-closed direction stays covered.

---

## Finding 3 — CI has not run the test suite since 2026-08-15, on a rationale that is measurably false (HIGH, confirmed)

`930b391` (2026-08-15) disabled both test jobs:

```yaml
test:
  if: false # test suite removed from CI (too long); run locally with `python -m pytest tests/ -v`
test-cross-platform:
  if: false # test suite removed from CI (too long); run locally with `python -m pytest tests/unit -v`
```

The unit tier takes **12.33 seconds** here, and **9.07 seconds** on a
GitHub runner — measured from the `cobol-parser-compat` job of CI run
[#333](https://github.com/Landparty/mocky-mock/actions/runs/33980780645),
which runs `pytest tests/unit` in the same workflow that declares the
suite too slow to run:

```
1 failed, 1477 passed, 9 skipped, 1 xfailed in 9.07s
```

Whatever was slow in August, it was not `tests/unit`. Restoring the unit
tier costs ~10s per job.

### Consequences, all currently live

- **`main` is red** and has been since the 0.8.0 release commit. Run #327
  (`a5b3e18`) passed; run #329 (`51d826d`, release 0.8.0) failed and
  every run since has failed. The failure is Finding 1:
  `FAILED tests/unit/test_smoke.py::test_mockymock_has_a_version - AssertionError: assert '0.7.0' == '0.8.0'`.
  A red default branch that nobody is expected to act on is worse than no
  CI, because it also masks the next real failure.
- **The compile/run tier is gated nowhere.** `tests/integration/` is 36
  files, every one `@requires_docker`. The `test` job was its only home,
  and `test-cross-platform` deliberately excluded it. So the framework's
  central claim — that it compiles and runs real COBOL under GnuCOBOL —
  has had no automated verification for three weeks.
- **That gap compounds with features shipped explicitly unverified.**
  `CHANGELOG.md` and the design docs flag CICS EIB/linkage support, the
  `GO TO`→`EXIT PARAGRAPH` simplification, and both `mutate` cost levers
  as *"Not yet verified against real GnuCOBOL"* / *"Neither lever has been
  exercised against a real Docker daemon"*. Those are honest disclosures,
  but they describe features whose only possible gate is the tier that is
  switched off.

### Fix

Re-enable `test` and `test-cross-platform`. If a slow subset is the real
concern, split it rather than dropping everything: run `tests/unit` on
every push/PR (~10s) and keep `tests/integration` on the existing nightly
`schedule` trigger, which already exists in this workflow.

---

## Finding 4 — The CI lint job type-checks against a fiction (HIGH, confirmed)

The `lint` job installs only the tools, never the project's dependencies:

```yaml
- name: Install lint tools
  run: pip install ruff black mypy
- name: mypy
  run: python -m mypy mockymock/
```

With `ignore_missing_imports = true`, an absent `cobolparser` makes every
symbol crossing that seam `Any`, and mypy reports success. Installed, it
does not:

```console
$ mypy mockymock/           # no cobolparser installed (what CI does)
Success: no issues found in 59 source files

$ mypy mockymock/           # cobol-parser 1.8.4 installed (what a dev does)
mockymock/cli/main.py:129: error: "object" not callable  [operator]
mockymock/cli/main.py:131: error: "object" not callable  [operator]
mockymock/cli/main.py:334: error: "object" not callable  [operator]
mockymock/cli/main.py:336: error: "object" not callable  [operator]
Found 4 errors in 1 file (checked 59 source files)
```

Two problems, and the second is the bigger one:

1. **A clean checkout fails its own documented type check.** The four
   errors are real: `cobolparser.generators` exposes its API through
   `def __getattr__(name: str) -> object`, so `ProgramFixtureGenerator`
   and `DataGeneratorOptions` are `object` to mypy, and calling them is an
   error. Present in 1.7.7 through 1.8.4 alike, so this is not new drift —
   it has simply never been visible to CI. A contributor following
   `requirements-dev.txt` hits it on day one.
2. **The seam mypy exists to protect is the one part it never checks.**
   `cobolparser` is a closed-source compiled extension consumed under a
   floor-only pin. Type-checking mockymock with that dependency stubbed to
   `Any` verifies the half that was never at risk.

The `[tool.mypy]` block's own comment — *"settings chosen so the current,
fully-annotated code passes; tighten incrementally rather than
blanket-ignoring whole modules"* — describes an intent this job silently
inverts.

### Fix

Install the real dependency in the lint job (`pip install -r
requirements-dev.txt`), then resolve the four errors at the seam — a
narrow `cast` or a typed local alias at each construction site, not a
module-level ignore. Consider `disallow_untyped_calls` scoped to
`mockymock.cli` once green, and raise the finding upstream in
cobol-parser: a `__getattr__` returning `object` rather than a typed
overload set defeats PEP 561 for every consumer.

---

## Finding 5 — Four shipped real-world examples are refused by mockymock's own gate; the README says they pass (MEDIUM, confirmed)

`examples/real-world/README.md` states:

> Together all 17 give the corpus's entire COBOL program set a real,
> passing `mockymock run` suite (238 test cases total, 0 failing)

A sweep of all 29 example `.cbl`/`.cut` pairs refuses four:

| example | refusal |
|---|---|
| `ACCTMNT` | `UNMOCKED_FILE_OP` — `CLOSE PARMFILE` / `CLOSE ACCTMRPT` in `3000-FINALIZE` |
| `ACHPROC` | `UNMOCKED_SQL` + `UNMOCKED_FILE_OP` in `2300-VERIFY-BATCH-CONTROL` / `3000-FINALIZE` |
| `CHKCLR`  | `UNMOCKED_FILE_OP` — four files in `3000-FINALIZE` |
| `INTCALC` | `UNMOCKED_SQL` (`CLOSE INT_CURSOR`) + `UNMOCKED_FILE_OP` in `3000-FINALIZE` |

The other 25 pass. This affects `run`, not just `lint`: `_cmd_run` calls
the identical `run_static_checks` and returns before any Docker work, so
`mockymock run` refuses these four today.

All four are Finding 2. `ACCTMNT` is the textbook shape — `2000-PROCESS-PARM-CARDS`
does `PERFORM 2200-PROCESS-FEE-POSTING THRU 2290-FEE-DONE`, and
`2200-PROCESS-FEE-POSTING` contains `GO TO 2290-FEE-DONE` on the
cursor-open failure path. `ACCTMNT.cut`'s own header comment shows the
author had already shaped the program around this idiom deliberately:

> failure path used to GO TO 2290-FEE-DONE without ever being PERFORMed
> upstream by adding THRU 2290-FEE-DONE to the PERFORM in
> 2000-PROCESS-PARM-CARDS

Not dependency drift — reproduced identically on cobol-parser 1.8.0 and
1.8.4. Not stale examples either: they **passed** at `251d9e8`, the commit
that added them, and broke at `162f205` five weeks ago. None of the four
has an integration test (only `ACCTPRG`, `DEPTIMSM`, `DEPTMQC`, `DEPTMQP`
do), and the tier that would host one does not run (Finding 3), so
nothing noticed.

`docs/corpus-sweep-report.md` still lists all four as clean, but it
records the parse/generate sweep only — it never claimed to cover the
refusal gate, so it is not wrong, just not load-bearing here.

### Fix

Fix Finding 2 and re-run the sweep; the four should go green without
touching the `.cut` files. Then add a Docker-free corpus gate — lint every
`examples/**` pair as a unit test — so a reachability change that breaks a
shipped example fails a 10-second job instead of surviving five weeks.
That gate is worth having independently of Finding 2, and it needs no
daemon.

---

## Finding 6 — The declared dependency floor segfaults (MEDIUM, confirmed)

`pyproject.toml` declares `cobol-parser>=1.7.7,<2`. Installing exactly
that floor and parsing any real program crashes the interpreter:

```console
$ python -c "from cobolparser import parse_cobol; \
    parse_cobol(open('examples/real-world/ACCTPRG/ACCTPRG.cbl').read(), filename='ACCTPRG.cbl')"
Segmentation fault (exit 139)
```

1.7.7 also returns `success=False` for a trivial, valid program that
1.8.0 parses. 1.8.0 is clean on both. The floor is not a supported
version; it has simply never been resolved to, because a normal `pip
install` picks the newest.

CI's own comment already says the floor should be higher:

> the exact way the pinned floor had to be bumped to **1.8.0** once
> cobol-parser fixed the phantom-arithmetic-terminator-paragraph bug

and `pyproject.toml`'s comment says the Report Writer / INVOKE / CHAIN
work "need the cobol-parser release carrying its 2026-09-02
statement-coverage and REPORT SECTION work" — also above 1.7.7. The pin
was never updated to match either statement.

This is reachable in practice by anything that resolves to a floor: a
lockfile, a `constraints.txt`, a mirror lagging behind, or a downstream
package pinning `cobol-parser==1.7.7`. The failure mode is a segfault, not
a diagnosable error.

### Fix

Raise the floor to `cobol-parser>=1.8.0,<2` (verified working here) and
reconcile the three comments to the pin. Longer term the
`cobol-parser-compat` job should test the floor as well as the ceiling —
today it only ever installs the newest release, which is why a broken
floor is invisible.

---

## Finding 7 — `--cov-fail-under=83` in `addopts` fails every partial test run (LOW, confirmed)

`pyproject.toml` puts the coverage gate in `[tool.pytest.ini_options].addopts`,
so it applies to *every* invocation, including running one file:

```console
$ python -m pytest tests/unit/test_smoke.py -q
TOTAL   7052  7051  2970  0  0.01%
FAIL Required test coverage of 83% not reached. Total coverage: 0.01%
```

The developer loop the disabled-CI comment points people to ("run locally
with `python -m pytest tests/ -v`") is exactly the loop this makes noisy:
any focused run reports a failing coverage bar unrelated to the tests
just run, which trains contributors to ignore red pytest output. Given
Finding 3, that is not a harmless papercut.

### Fix

Move `--cov`/`--cov-fail-under` out of `addopts` into the CI invocation
(or a `make test-ci` / tox target), leaving bare `pytest` clean. Keep the
gate itself — just apply it where a whole-suite number is meaningful.

---

## Finding 8 — `uv.lock` is stale (LOW, confirmed)

`uv.lock` pins `mocky-mock` at `0.6.4` (repo is at `0.8.0`) and
`cobol-parser` at `1.8.2` (1.8.4 is current, and the lock's own floor is
below what Finding 6 shows is required). This has happened before —
`e305e1f "fix: regenerate stale uv.lock pinning cobolparser to a July git
SHA"` — so a one-off regeneration will not hold.

### Fix

Regenerate, and add a CI check that `uv lock --check` is clean, so the
lock cannot drift silently again.

---

## Finding 9 — A binary editor cache is committed (LOW, confirmed)

`_superbol/lsp-cache` is a 172 KB binary SuperBOL LSP cache, committed in
`251d9e8`, referenced nowhere in the repo, and not covered by
`.gitignore` (which does cover `.superpowers/`, `.worktrees/`,
`__pycache__/`, ...).

### Fix

`git rm -r --cached _superbol` and add `_superbol/` to `.gitignore`.

---

## What is healthy

Stated plainly, because the findings above are concentrated in one layer
and should not be read as a verdict on the whole project.

- **Security posture is genuinely good, and deliberate.** No `shell=True`,
  no `os.system`, no `eval`/`exec`/`pickle`/`yaml.load` anywhere in
  `mockymock/`. Every subprocess call is an argv list. The dashboard binds
  loopback-only with the bind address non-configurable, sends no CORS
  headers, serves a read-only probe that cannot trigger image builds, and
  resolves static paths with a post-`resolve()` containment check that
  correctly handles both `..` and Windows `/C:/` smuggling. Container
  paths are validated against the work root before use. Timeouts are
  enforced twice, container-side and host-side, with `-k 5` escalation.
  Several of these carry comments citing the audit finding that prompted
  them — the prior audits stuck.
- **Test suite is substantial**: 1,478 unit tests, 88.36% line/branch
  coverage against an 83% floor, plus 36 integration files. The failures
  in this report are gaps in *running* it, not in having it.
- **`ruff` and `black` are clean** across all 183 files. Only 9
  `TODO`/`FIXME` markers in the package, and every one is a documented
  intentional gap in `dsl/generator.py`, not an abandoned edit. 9 broad
  `except Exception` handlers, each surfacing the error rather than
  swallowing it.
- **Documentation is unusually strong.** The `.okf/` bundle, 50 dated
  design docs, and the density of *why*-comments in the code are well
  above typical. Notably, the project documents its own unverified
  features honestly rather than quietly shipping them.
- **Fail-closed design is the right instinct.** Finding 2 is a bug in an
  over-approximation, not a bug in the choice to over-approximate. The
  gate refusing too much is the failure mode you want to be debugging.

---

## Prioritized recommendations

### Do now

1. **Re-enable `tests/unit` in CI** (Finding 3). ~10s per job, and it is
   the precondition for the rest of this list mattering. Move
   `tests/integration` to the existing nightly `schedule` rather than
   leaving it ungated.
2. **Fix the version drift at the root** (Finding 1): `extra-files` in
   `release-please-config.json`, plus correct `__init__.py` to `0.8.0`.
   This also turns `main` green.
3. **Raise the dependency floor to `>=1.8.0`** (Finding 6) and reconcile
   the comments that already say so.

### Do next

4. **Fix the `PERFORM ... THRU` terminus false refusal** (Finding 2), and
   confirm the four examples go green (Finding 5).
5. **Install real dependencies in the lint job and fix the four seam
   errors** (Finding 4).
6. **Add a Docker-free `examples/**` lint gate** (Finding 5) — the cheapest
   durable guard against the next reachability regression.

### Do when convenient

7. Move the coverage gate out of `addopts` (Finding 7).
8. Regenerate `uv.lock` and add `uv lock --check` to CI (Finding 8).
9. Untrack `_superbol/` (Finding 9).
10. Once the integration tier runs again, work through the features
    currently marked "not yet verified against real GnuCOBOL" and either
    confirm or retract each claim.

### Structural observation

Every high-severity finding here is the same failure, seen four times: a
guard existed, was correct, and was not running. `test_smoke.py` already
pinned the version invariant. `mypy` already covered the seam. The example
corpus already exercised the reachability gate. The `cobol-parser-compat`
job was built specifically to catch dependency drift. None of them was
wrong — three were switched off and one was pointed at a stubbed
dependency. The cheapest durable fix is not more checks; it is making the
existing ones run against what actually ships.
