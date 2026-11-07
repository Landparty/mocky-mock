# Tech debt audit

Date: 2026-11-06
Scope: whole repo at `db546ba` (v0.16.1): `mockymock/` (120 modules, ~61k
lines), `tests/` (360 files, ~68k lines), CI, docs, packaging.

Score: **Priority = (Impact + Risk) × (6 − Effort)**, each on a 1-5 scale.
A higher score means fix it sooner.

## Summary

The code is in good shape: ruff and black pass clean, the code is fully
annotated, and broad `except Exception` handlers are rare (51) and each one
says why it is there. Most of the debt is in the **verification
plumbing**, not the code. Several guards exist but don't check what they
look like they check:

- The unit tier **fails to collect** on the cobol-parser version in the
  lockfile.
- mypy passes in CI only because CI doesn't install the dependency whose
  types it should check.
- The Docker integration tier has had no CI home since before the
  2026-09-05 audit.
- The declared dependency floor (1.7.7) is never installed by anything.

The second cluster is structural. Two modules, `cli/main.py` (6.8k lines)
and `dsl/generator.py` (5.4k lines), take 33% and 26% of the last month's
source commits.

## Prioritized list

| # | Item | Category | I | R | E | Score |
|---|------|----------|---|---|---|-------|
| 1 | Unit tier fails collection on locked cobol-parser 3.1.1 | Test | 4 | 5 | 1 | **45** |
| 2 | cobol-parser floor `>=1.7.7` is never tested; 14 compat shims carried for it | Dependency | 3 | 4 | 1 | **35** |
| 3 | Docker integration and cross-platform tiers have no CI home (4 Windows failures today) | Test / Infra | 3 | 5 | 2 | **32** |
| 4 | CI mypy can't see cobol-parser types: 26 hidden errors | Code / Infra | 3 | 4 | 2 | **28** |
| 5 | Lint tools unpinned in CI; ruff and black both configured | Dependency / Infra | 2 | 2 | 1 | **20** |
| 6 | `cli/main.py`: 6,779 lines, `build_parser` alone is 1,263 | Code / Arch | 5 | 3 | 4 | **16** |
| 7 | `dsl/generator.py`: 5,402 lines, 136 top-level functions | Code / Arch | 5 | 3 | 4 | **16** |
| 8 | Docs sprawl: 70 dated design docs + 23 plans, no status index | Documentation | 2 | 2 | 2 | **16** |
| 9 | Python 3.14 is missing from classifiers and the CI matrix | Dependency | 1 | 2 | 1 | **15** |
| 10 | Tests organized by bug-hunt round/date, not by feature | Test | 2 | 2 | 3 | **12** |
| 11 | `runner/` (LegacyLens oracle worker) lives inside the testing CLI | Architecture | 2 | 3 | 4 | **10** |
| 12 | `_superbol/lsp-cache` editor binary is tracked in git | Code hygiene | 1 | 1 | 1 | **10** |

---

### 1. Unit tier fails collection on the locked cobol-parser (45)

`tests/unit/test_open_modes.py:13` does an unguarded
`from cobolparser.analysis.constraints import StatementSite`. That name
doesn't exist in cobol-parser 3.1.1, the version `uv.lock` resolves and
the latest on PyPI. Line 28 of the file tries to skip when `open_modes` is
missing, but the import fails before the skip can run, so pytest **stops
the whole `tests/unit` run** with one collection error. The file came in
with `d3ff8aa` (generate: mock OPEN per mode).

- **Why it matters:** `cobol-parser-compat` is the only CI job that runs
  tests, and it runs exactly `pytest tests/unit` against PyPI
  cobol-parser. So it should currently be red, and every other unit-test
  signal is hidden until it's fixed. I couldn't confirm the CI status
  because `gh` isn't authenticated here.
- **Fix (≈15 min):** use `pytest.importorskip`, or wrap the import in
  `try/except ImportError` and skip the module. Add a ruff/pytest check,
  or a reviewer rule, that `cobolparser` imports in tests for unreleased
  features must be guarded.

### 2. Untested dependency floor and the shims it requires (35)

`pyproject.toml` declares `cobol-parser>=1.7.7,!=1.8.2,<4`, which spans
three major versions. Every environment (the lockfile, CI, local) installs
3.1.1. The comment block that justifies the range is 40 lines long and
growing. Supporting the old floor costs 14 `ImportError`/`AttributeError`
fallbacks (`mock_surface._optional_statement_types`,
`config._universal_values`, `doctor`, `test_report`, `main`), plus the 20
tests gated on `requires_universal_config`. Nothing exercises the fallback
paths, so they are dead code in practice and broken code in theory.

- **Why it matters:** users on 1.7.x-2.x get paths nobody has run. Each
  new cobol-parser feature adds another shim and another paragraph to the
  comment.
- **Fix (≈half a day):** raise the floor to the oldest version actually
  tested (3.1), delete the shims and their skip markers, and replace the
  comment with a pointer to `.okf/integration.md`. If old-version support
  is a real requirement, add a `cobol-parser-floor` CI job that pins the
  floor instead. Either way, stop declaring a range nothing tests.

### 3. The Docker integration tier has no CI home (32)

`test` and `test-cross-platform` in `.github/workflows/ci.yml` are
`if: false`, with the note "too long". The 2026-09-16 audit measured the
unit tier at 11s on a runner. That leaves 264 `@requires_docker` tests
across 82 `tests/integration` files, which cover the core claim of
compiling and running real COBOL, with no automated runs. The workflow's
own comments still say "the Docker-backed compile/run path itself stays
covered by `test` above", which is no longer true. This is the third
audit to report it.

- **Why it matters:** splicer, runtime, and toolchain regressions ship
  without notice. That is the class of bug the bug-hunt test files keep
  catching after the fact. The disabled `test-cross-platform` job has a
  cost you can see. On Windows / Python 3.14 (this audit's machine), the
  unit tier is **4 failed, 3425 passed, 21 skipped**:
  - `test_runner_timeout_kills_the_compiler_mockymock_started`: "the
    grandchild outlived the suite timeout". On Windows, a timed-out run
    leaves the compiler process running. This is a real product bug, not
    just a test bug.
  - `test_step_suite_keeps_one_case_and_declares_the_files`: the generated
    `USE REAL FILE ... FROM` path is missing. It looks like a path
    separator problem in `mockymock job`.
  - `test_docker_exec_output_is_read_in_bounded_memory`: the test expects
    `\n` and gets `\r\n`.
  - `test_client_speaks_the_runner_api`: the test expects an HTTP 401 and
    gets WinError 10053.

  The README claims the tool is "OS Independent", and nothing checks that.
- **Fix (≈2h):** run `tests/unit` on push/PR (it's fast). Move
  `tests/integration` onto the nightly `schedule` trigger the workflow
  already has, so the slow tier never blocks a PR. Correct the stale
  comments, including the `<2` cap mentioned in the compat job's comment,
  which is now `<4`.

### 4. CI mypy is blind at the dependency seam (28)

The `lint` job runs `pip install ruff black mypy` without installing the
project. With `ignore_missing_imports = true`, every `cobolparser` type
becomes `Any`, so the job passes. Run locally against the locked
dependency, `mypy mockymock/` reports **26 errors in 12 files**: "not
callable" ×7, `CobolProgram` arg-type mismatches, missing attributes.
`dsl/entry_parameters.py` (5), `report/test_report.py` (4),
`analysis/mock_surface.py` (3) and `runtime/native_toolchain.py` (3) are
the worst.

- **Why it matters:** the boundary with cobol-parser is the most fragile
  edge in the project, as items 1 and 2 show, and it's the one place the
  type checker is switched off. `py.typed` also promises downstream users
  annotations that aren't checked.
- **Fix (≈half a day):** install `-e .[dev]` in the lint job, fix or
  narrowly `# type: ignore[code]` the 26 errors, and keep the job blocking.

### 5. Unpinned lint tools; two formatters (20)

CI installs whatever ruff, black, and mypy are latest, while `uv.lock`
pins its own versions. A new ruff rule or mypy release can turn `main` red
with no code change. Ruff and black are also both configured: `E501` is
ignored "because black handles it", and ruff's formatter could replace
black entirely.

- **Fix (≈1h):** have CI install from the lockfile (`uv sync --extra dev`
  and then `uv run`). Optionally drop black for `ruff format`, which needs
  one reformat commit to check for diffs.

### 6. `cli/main.py` is a 6,779-line god module (16)

It holds 101 functions: `build_parser` (1,263 lines), `_cmd_run_suite`
(799), `_cmd_generate` (437), `_cmd_debug`, `_cmd_export`, and every other
subcommand. It was touched by **119 of the 357 source commits** in the
last month, and 147 test files import from it. The `cli/` package already
has the right shape (`doctor.py`, `checks.py`, `skills_cmd.py`,
`mainframe_export.py`), and main.py simply never got split along it.

- **Why it matters:** every feature touches one file, so parallel branches
  (and parallel Claude sessions) conflict here first. Reviews of a
  1,263-line argparse builder are a skim.
- **Fix (incremental, ≈1 day per slice):** move one subcommand at a time
  into `cli/commands/<name>.py`, each exporting
  `register(subparsers)` and `run(args)`. `build_parser` then becomes a
  loop. Start with `run` and `generate`, the largest and most churned.
  Keep re-exports in `main.py` until the tests stop importing private
  names from it.

### 7. `dsl/generator.py` is 5,402 lines (16)

It holds 136 top-level functions covering AT END replication, IMS/CICS/MQ
loop-end replies, SQL cursors, fixture bundles, and entry parameters, and
it was touched by 94 commits in the last month. Related logic has already
been pulled out (`dsl/entry_parameters.py`, `dsl/real_branches.py`), which
shows the seams.

- **Fix (incremental):** split by boundary family (`generator/files.py`,
  `generator/ims.py`, `generator/cics.py`, `generator/sql.py`,
  `generator/loops.py`) behind the existing public entry points. This is
  a mechanical move with no behaviour change, verified by the unit tier
  once item 1 is fixed.

### 8. Docs sprawl (16)

`docs/` has 70 dated design/plan/audit files, and `docs/superpowers/` has
23 more plans. `.okf/` (13 files) is the real knowledge base, and
`CHANGELOG.md` is 232 KB. Nothing records which designs are implemented,
superseded, or abandoned, and five separate "audit" docs each re-carry
earlier findings.

- **Fix (≈2h):** add a `docs/index.md` table (doc → status → `.okf` page),
  move implemented plans to `docs/archive/`, and make `.okf/` the single
  entry point linked from the README.

### 9. Python 3.14 (15)

3.14 has been out for a year, and `uv` picked it by default on this
machine. It isn't in the classifiers or any matrix.

- **Fix:** add it to classifiers and to the unit-test matrix once item 3
  re-enables one.

### 10. Tests organized by discovery date (12)

There are 13 unit files and several integration files named
`test_bug_hunt_r11.py`, `test_bug_hunt_20261105_runner.py`,
`test_nightly_20261009_*`, `test_open_gaps_2026_11_06.py`, and similar.
They encode *when* a bug was found, not *what* it covers. Tests also import
75 private symbols (`from mockymock... import _x`), which pins internals
and makes items 6 and 7 harder.

- **Fix (alongside items 6 and 7):** when a module is split, move the
  matching bug-hunt cases into the feature's test file. New regression
  tests go next to the feature from now on.

### 11. `runner/` inside the testing CLI (10)

`mockymock/runner/` (~1.3k lines) is the LegacyLens change-impact oracle
worker. It claims jobs from a backend API and runs **uploaded, untrusted
COBOL**. That's a different product, with a different threat model,
shipped inside every `pip install mockymock`, with its own Dockerfile at
`docker/runner/`.

- **Why it matters:** this isn't urgent, because the container hardening
  is documented. But the security surface and the backend protocol now
  version together with a local testing tool.
- **Fix (later):** move it to a `mockymock[runner]` extra or its own
  package once the protocol settles.

### 12. Tracked editor cache (10)

`_superbol/lsp-cache` is a binary SuperBOL LSP cache committed to the
repo.

- **Fix (5 min):** `git rm --cached`, and add `_superbol/` to
  `.gitignore`.

---

## Phased remediation plan

**Phase 1: restore the signal (this week, ≈1 day total).** Items 1, 3, 5,
12, plus fixing the stale CI comments. These are small and they unblock
everything after them: no refactor in phase 3 is safe while the unit tier
doesn't collect and the integration tier never runs.

**Phase 2: close the dependency seam (next 1-2 weeks, ≈1-2 days).** Items
2 and 4. Decide the floor, delete the shims, and turn mypy on against the
real cobol-parser. Add item 9 while the matrix is open.

**Phase 3: split the hotspots (ongoing, one slice per feature PR).** Items
6, 7 and 10. Rule: *a PR that adds a subcommand or a generator family
moves that area out first.* This takes no dedicated sprint and spreads
the cost over the work that already touches those files.

**Phase 4: when convenient.** Items 8 and 11.

## Remediation (2026-11-07)

All four phases are done on branch `claude/tech-debt-repo-4cc261`. Final
state of that branch: ruff check and ruff format are clean, mypy is clean
on 153 files against the real cobol-parser, and `tests/unit` is **3430
passed, 21 skipped, 0 failed**, with 87.43% coverage. The integration tier
collects all 275 tests, but it was not run, because there is no Docker
daemon on the audit machine; it now runs nightly in CI.

| # | Item | Outcome |
|---|------|---------|
| 1 | Unit tier collection error | Fixed. The `StatementSite` probe is guarded, and the one assertion that needs unreleased parser behaviour skips. |
| 2 | Untested floor, version shims | Floor raised to `>=3.1.1,<4`. The shims are deleted from `mock_surface`, `config`, `_lines` and `test_report`, along with the always-true test probes. Probes stay only for behaviour newer than any published release. The nightly `cobol-parser-range` job runs both ends of the range. |
| 3 | No CI home for integration and cross-platform | `unit` runs on every push/PR (ubuntu 3.11-3.14, windows, macos), and `integration` runs nightly. All four Windows failures are fixed. One was a **real bug**: on Windows, a timed-out runner job killed only the direct child, so the compiler kept running. It now uses `taskkill /T`, and the test's liveness check no longer kills the process it probes. |
| 4 | CI mypy blind to cobol-parser | The lint job installs from the lockfile. The 26 errors are fixed with no new `type: ignore`. Three of them were real `None`-AST crash paths, in `generate`, `checks` and `job` steps. |
| 5 | Unpinned lint tools, two formatters | CI installs with `uv sync --locked`. black is replaced by `ruff format` (45 files reformatted). |
| 6 | `cli/main.py` god module | Down from 6,779 to 1,698 lines. Commands now live in `cli/commands/` (18 modules) and shared helpers in `cli/_common.py`. An AST comparison confirmed no definition changed (one deliberate exception: `_cmd_init` imports `build_parser` lazily). `--help` output for all 25 parsers is byte-identical. `build_parser` itself stayed whole. |
| 7 | `dsl/generator.py` | Now the `dsl/generator/` package: 14 modules, the largest 854 lines, no import cycles. All 177 definitions are AST-identical. Existing import paths still work through re-exports. |
| 8 | Docs sprawl | `docs/index.md` gives every design's real status (checked against the code) and names the two gaps still open. 24 shipped plans and one superseded design moved to `docs/archive/`, with links updated. README and `.okf/index.md` link the index. |
| 9 | Python 3.14 | Added to the classifiers and the CI matrix. |
| 10 | Date-named tests | All 18 files are redistributed into feature files, with provenance comments. The collected count is unchanged (3451). The convention is written into `.okf/testing.md`. The `test_issue_<n>` files are kept, since each traces to one issue. |
| 11 | `runner/` in the testing CLI | It was already isolated at the import level. That boundary is now pinned by `tests/unit/test_runner_boundary.py`. **Not done:** splitting it into its own distribution, which needs a decision on packaging and release ownership. |
| 12 | Tracked LSP cache | Untracked, and `_superbol/` is in `.gitignore`. |

**Still open:**

- The integration tier has not run against these changes. The first
  nightly run, or a `workflow_dispatch`, is its first real check.
- The CI workflow itself has not run yet, since nothing is pushed.
- `build_parser`, at 1,263 lines, could become a per-command
  `add_parser()` later, keeping the byte-identical-help check as the guard.

## What's healthy

- Unit-tier line+branch coverage is **87.23%** (floor 83%). With
  `test_open_modes.py` excluded, the tier ran in 6m21s on Windows; the
  2026-09-16 audit measured 11s on Linux CI.
- ruff and black are clean across 485 files, and the code is fully
  annotated.
- Broad exception handlers are justified inline, and none of them silently
  swallow an error.
- The lockfile, release-please, and the nightly compat job are good
  foundations, and phases 1-2 mostly make them check what they look like
  they check.
- `.okf/` gives a strong onboarding base, and the
  `mockymock-dev` skill points at it.
