# Project audit — 2026-09-16

Eighth framework audit. Scope: the whole repository as it stands at
`f78d7e8` (tip of `main`) — the nine findings of the 2026-09-05 audit
re-checked one by one, then the ~3,500 lines of CLI surface shipped since
it (`init`, `doctor`, `explain`, `collect --boundaries`, AI assistant
modes, copybook-discovery defaults, actionable refusals, and the universal
`cobol.yml` config layer).

Method: as before, every finding below was reproduced in this environment,
not inferred from reading. Where a claim is about history it was checked
against a real worktree at the prior audit's commit; where it is about CI
it was read off the actual job steps. Commands and outputs are quoted
inline so each finding can be re-checked in one step.

Environment: Linux, Python 3.11.15, `cobol-parser` **1.8.4** from PyPI
(the newest that exists there), **no Docker daemon** — so
`tests/integration/` (38 files, 36 of them `@requires_docker`) could not be
exercised. Everything below is from the Docker-free tier.

**Headline:** the last audit's two shipped-to-users defects are fixed —
`--version` is correct and `main` is green again. What replaced them is a
subtler version of the same failure: the project now depends, in shipped
code and in 42 of its own tests, on a `cobol-parser` release that has
never been published. One consequence is live for every user of the
released package — **placing a `cobol.yml` anywhere above the working
directory makes every `mockymock` command exit 1**, and the remedy the
error names cannot be followed, because the version it asks for does not
exist on PyPI.

---

## Finding 1 — A `cobol.yml` anywhere up the tree makes every command fail, with a remedy that cannot be followed (HIGH, confirmed, live for released users)

`cli/config.py` reads the universal `cobol.yml` through `cobolparser.config`,
and raises when that import fails:

```python
try:
    from cobolparser.config import ConfigError as ParserConfigError
    from cobolparser.config import load_project_config
except ImportError as exc:  # pragma: no cover - depends on installed version
    raise ConfigError(
        f"mockymock: {path} needs a cobol-parser that can read it "
        f"(>= 1.10). Upgrade with 'pip install -U cobol-parser', or "
        f"move these settings into a mockymock.toml."
    ) from exc
```

`cobolparser.config` does not exist in any published release. It landed in
the sibling repo **today** (`90d5b76`, 2026-09-16), after `1.9.0` was cut,
so it will first appear in `1.10.0`. PyPI's newest is `1.8.4`:

```console
$ python -c "import json,urllib.request; d=json.load(urllib.request.urlopen('https://pypi.org/pypi/cobol-parser/json')); print(d['info']['version'])"
1.8.4
```

The failure is not confined to projects that opted into the new file. The
config search walks *up* from the working directory, so a `cobol.yml`
written for one of the other two tools in the family — the `cobol-parser`
CLI, or the COBOL Analyzer extension, which is the entire point of a
*universal* config — takes the whole CLI down from any subdirectory:

```console
$ ls
cobol.yml  mockymock.toml  sub/
$ cd sub

# with a valid mockymock.toml and no cobol.yml above it
$ mockymock lint INVUPDT.cbl
mockymock lint: no problems found.
$ echo $?
0

# identical, except a cobol.yml now sits in the parent
$ mockymock lint INVUPDT.cbl
mockymock: /tmp/cfgtest/cobol.yml needs a cobol-parser that can read it
(>= 1.10). Upgrade with 'pip install -U cobol-parser', or move these
settings into a mockymock.toml.
$ echo $?
1
```

Three things compound here:

1. **The remedy is impossible.** `pip install -U cobol-parser` resolves to
   `1.8.4` and always will until a `1.10.0` is published. A user who
   follows the instruction exactly sees nothing change.
2. **There is no escape hatch.** The sibling `cobol-parser` CLI takes
   `--config FILE` and `--no-config` on either side of the subcommand;
   `mockymock` has neither, at top level or per subcommand. There is no
   way to tell it to ignore a `cobol.yml` it cannot read.
3. **A working `mockymock.toml` does not rescue it.** The tool-specific
   file is supposed to override the universal one key by key, and the
   module docstring says exactly that — but `_universal_values()` raises
   while building the base layer, before any override is applied. So the
   settings are all present, in a file the tool fully understands, and it
   still refuses.

`mockymock doctor` does not warn about this either; on the same tree it
reports `[ OK] config file — none found (using built-in defaults)`, because
the probe runs before the read that throws.

### Fix

Make the missing-parser case **degrade, not fail**. A `cobol.yml` that
cannot be read is a reason to fall back to `mockymock.toml` plus built-in
defaults with a one-line warning naming the file and the version — not a
reason to refuse to run. That preserves the fail-closed posture where it
belongs (a config that *is* readable but malformed stays an error) without
letting another tool's file brick this one. Two things are worth adding
alongside it:

- `--config` / `--no-config`, matching the sibling CLI, so the fallback is
  also steerable by hand.
- Name the real floor. The message says `>= 1.10`, which is right in
  intent, but see Finding 4 — today no published release satisfies it, so
  the text should say so rather than implying an upgrade will help.

---

## Finding 2 — 42 of 51 skipped unit tests are gated on an unpublished dependency, and CI can never run them (HIGH, confirmed)

The unit tier is green here — 1,629 passed, 88.19% coverage — but the skip
count has grown from 9 at the last audit to 51:

```console
$ python -m pytest tests/unit -q
1629 passed, 51 skipped, 1 xfailed in 14.42s
Required test coverage of 83% reached. Total coverage: 88.19%
```

Broken down by reason:

| tests | skip reason | waiting on |
|---:|---|---|
| 23 | `CobolProgram.program_attributes` absent | unreleased (landed 2026-09-15, after 1.9.0) |
| 19 | installed cobol-parser predates `cobolparser.config` | unreleased (landed 2026-09-16) |
| 4 | no Report Writer nodes | `1.9.0` — cut, never published (Finding 4) |
| 2 | no structured XML PARSE clauses | `1.9.0` — cut, never published |
| 1 | no Communication nodes | `1.9.0` — cut, never published |
| 1 | no `ChainStatement` | `1.9.0` — cut, never published |
| 1 | sibling legacy-application repo absent | environmental, fine |

So **42 tests are gated on cobol-parser releases that do not exist**, and
8 more on a release that exists as a git tag but never reached PyPI.

The gates themselves are honest — each names what it needs and why, and
`test_enterprise_corpus.py` even says "bump the pin in pyproject.toml once
it is published". The problem is what they interact with. The **only** CI
job that runs tests is `cobol-parser-compat`, and by design it installs the
*published* parser:

```yaml
- name: Install dependencies (published cobol-parser from PyPI)
  run: pip install -r requirements-dev.txt
- name: Run unit tests against the published cobol-parser
  run: python -m pytest tests/unit -v
```

That is the right thing for that job to do. But with `test` and
`test-cross-platform` still `if: false` (Finding 6), it is also the only
configuration that ever runs — so those 42 tests run in no CI job, on no
schedule, on no Python version. They are not slow or flaky; they are
simply unreachable.

Two shipped features rest entirely on them: the universal `cobol.yml`
layer (19 tests, merged two days ago) and the Enterprise program-type
refusal pinning (23 tests). Both are in `main`, both are in the released
package's code path, and neither has ever been verified by an automated
run in any environment that CI can reach.

### Fix

Add one CI job that installs cobol-parser from the sibling repo's `main`
(or the newest pre-release) and runs the same unit tier. It costs ~11s and
turns 42 dormant tests into a real gate — and it is the job that would
have caught Finding 1 before the merge, since the `cobol.yml` path is
exercised there and nowhere else. Keep `cobol-parser-compat` exactly as it
is: the two jobs answer different questions, and both are worth asking.

Separately, `pytest --strict-markers` already guards marker typos; consider
failing the build when the skip count *rises* without a corresponding
entry in a known-gates list, so "temporarily gated" cannot quietly become
permanent.

---

## Finding 3 — `doctor` reports the wrong cobol-parser version (MEDIUM, confirmed)

`mockymock doctor` is the command a user runs to find out why something
does not work. On a clean install of the newest published parser it
reports a version that is two patch releases stale:

```console
$ pip show cobol-parser | head -2
Name: cobol-parser
Version: 1.8.4

$ mockymock doctor
...
[  OK] cobol-parser         importable, 1.8.0
```

`cli/doctor.py:58` reads the module attribute:

```python
version = getattr(cobolparser, "__version__", None)
```

and the published `1.8.4` wheel carries `__version__ = "1.8.0"`:

```console
$ python -c "import cobolparser, importlib.metadata as md; \
  print(cobolparser.__version__, md.version('cobol-parser'))"
1.8.0 1.8.4
```

This is the sibling repo's own version-drift bug — the same class of
defect as this project's Finding 1 last month — and it was fixed upstream
on 2026-09-10 (`10bbc5c`, which added the `x-release-please-version`
marker). But that fix landed *after* `1.8.4` was published, and no release
has been published since (Finding 4), so **every installable version of
cobol-parser misreports itself**, and `doctor` repeats it.

The consequence is not cosmetic given Findings 1 and 2: a user is told to
upgrade to `>= 1.10`, checks `doctor` to see where they stand, and is told
`1.8.0` when they are on `1.8.4`. Both numbers are below the floor, so the
conclusion happens to survive — but the diagnostic is wrong, and it will
stay wrong for any release cut before the upstream fix.

### Fix

Read the distribution metadata, which is authoritative and cannot drift
from what `pip` installed:

```python
import importlib.metadata as md
version = md.version("cobol-parser")   # falls back to __version__ if absent
```

Keep the `__version__` read as a fallback for a source checkout that is
not pip-installed, but prefer the metadata. This is worth doing regardless
of the upstream fix: it makes `doctor` correct against every release
already in the wild.

---

## Finding 4 — cobol-parser 1.9.0 was released on GitHub but never published to PyPI (MEDIUM, confirmed; root cause upstream)

`v1.9.0` is tagged and has a GitHub Release dated 2026-09-05. PyPI's
newest is `1.8.4`, dated 2026-09-01:

```console
$ # GitHub releases
v1.9.0  published 2026-09-05T11:40:21Z
v1.8.4  published 2026-09-01T21:15:45Z

$ # PyPI
1.8.4   (all: 1.7.7, 1.7.8, 1.8.0, 1.8.2, 1.8.4)
```

Eleven days later the wheels have still not landed. This is what the 8
"no Report Writer nodes" / XML PARSE / Communication / `ChainStatement`
skips in Finding 2 are waiting for, and `pyproject.toml`'s dependency
comment describes the same gap in prose:

> The Report Writer categories (INITIATE/GENERATE/TERMINATE), the
> INVOKE/CHAIN/Communication-Module refusals and the XML PARSE flow edge
> need the cobol-parser release carrying its 2026-09-02 statement-coverage
> and REPORT SECTION work

That release exists. It just is not installable, so the floor cannot be
raised to it and the features stay dark.

The root cause is in the sibling repo, not this one, so this audit does
not claim to have diagnosed it — but the likely candidate is visible in
`release-please.yml`: `publish-pypi` is gated on a deployment
`environment: pypi` whose own comment notes it has "deployment
gate/reviewers". A job waiting on an unapproved deployment leaves exactly
this signature — tag and GitHub Release created, wheels never uploaded.

### Fix

Upstream: confirm whether the `1.9.0` `publish-pypi` job is waiting on
deployment approval, was cancelled, or failed, and re-run it —
`skip-existing: true` is already set, so a re-run is safe. Then publish a
`1.10.0` carrying `cobolparser.config` and `program_attributes`.

Here: once `1.10.0` is on PyPI, raise the floor, drop the gates that
Finding 2 lists, and confirm all 42 tests pass. Until then, Finding 1's
degrade-don't-fail change is what keeps the released package usable.

---

## Status of the 2026-09-05 findings

Re-checked individually. Two fixed, seven open.

| # | 2026-09-05 finding | status today |
|---|---|---|
| 1 | `--version` reports `0.7.0` | **fixed** — `__init__.py`, `pyproject.toml` and the manifest all say `0.8.0`, and `release-please-config.json` now pins `extra-files` to the file, so it cannot drift on the distribution-name rename again |
| 2 | `GO TO` into a `PERFORM ... THRU` terminus falsely refused | **open** — unchanged; see below |
| 3 | CI does not run the test suite | **partly** — `main` is green again, and `cobol-parser-compat` does run `tests/unit`. But `test` and `test-cross-platform` are still `if: false`, so the Docker/integration tier and all of 3.11/3.12/Windows/macOS remain ungated |
| 4 | lint job type-checks against a fiction | **open** — unchanged, and re-confirmed below |
| 5 | shipped examples refused by the gate | **open** — and the true count is 5, not 4 |
| 6 | dependency floor `1.7.7` segfaults | **open** — floor is still `>=1.7.7,<2` |
| 7 | `--cov-fail-under=83` in `addopts` fails partial runs | **open** — confirmed below |
| 8 | `uv.lock` is stale | **open, worse** — the lock still declares `version = "0.6.4"`, now two minor releases behind `0.8.0` |
| 9 | binary editor cache committed | **open** — `_superbol/lsp-cache` is still tracked |

### Finding 4 (lint job) re-confirmed verbatim

The job still installs only the tools, so the seam it exists to protect is
still stubbed to `Any`. The divergence is exactly as reported:

```console
$ mypy mockymock/     # no cobolparser installed — what CI does
Success: no issues found in 64 source files

$ mypy mockymock/     # cobol-parser 1.8.4 installed — what a contributor does
mockymock/cli/main.py:136: error: "object" not callable  [operator]
mockymock/cli/main.py:138: error: "object" not callable  [operator]
mockymock/cli/main.py:809: error: "object" not callable  [operator]
mockymock/cli/main.py:811: error: "object" not callable  [operator]
Found 4 errors in 1 file (checked 64 source files)
```

Same four errors, same single file; the line numbers moved with the 1,139
lines `main.py` gained since. A clean checkout still fails its own
documented type check on day one.

### Finding 5 (refused examples) re-confirmed, and the count corrected

A sweep of all 33 example `.cbl`/`.cut` pairs — invoking `lint` correctly,
with the program as the positional argument and the copybook directory
passed — refuses **five**, not four:

```
lint pass=28 fail=5
  REFUSED IC101A  :: UNMOCKED_FILE_OP — CLOSE PRINT-FILE in 'CLOSE-FILES',
                     reachable from 'CALL-TEST-1'
  REFUSED ACCTMNT :: UNMOCKED_FILE_OP — CLOSE PARMFILE in '3000-FINALIZE',
                     reachable from '2000-PROCESS-PARM-CARDS'
  REFUSED ACHPROC :: UNMOCKED_SQL     — UPDATE in '2300-VERIFY-BATCH-CONTROL',
                     reachable from '2200-PROCESS-ENTRY-DETAIL'
  REFUSED CHKCLR  :: UNMOCKED_FILE_OP — four files in '3000-FINALIZE',
                     reachable from '2000-PROCESS-CHECKS'
  REFUSED INTCALC :: UNMOCKED_SQL     — CLOSE INT_CURSOR in '3000-FINALIZE',
                     reachable from '2100-FETCH-ACCOUNT'
```

Every one has the Finding 2 shape: a boundary in a *finalize/cleanup*
paragraph reported reachable from a *processing* paragraph — the gate
walking past the end of a `PERFORM` range into the next paragraph in
source order.

`IC101A` is **not** a new regression. A worktree at `b0d5235`, the prior
audit's commit, refuses the same five identically:

```console
$ git worktree add /tmp/wt-audit b0d5235
$ cd /tmp/wt-audit && for n in IC101A ACCTMNT ACHPROC CHKCLR INTCALC; ...
REFUSED IC101A  :: (UNMOCKED_FILE_OP): CLOSE boundary at line 199 ...
REFUSED ACCTMNT :: (UNMOCKED_FILE_OP): CLOSE boundary at line 565 ...
REFUSED ACHPROC :: (UNMOCKED_SQL): SQL boundary at line 623 ...
REFUSED CHKCLR  :: (UNMOCKED_FILE_OP): CLOSE boundary at line 442 ...
REFUSED INTCALC :: (UNMOCKED_SQL): SQL boundary at line 447 ...
```

All 33 pairs already existed at that commit and none has been added since,
so the earlier report's "29 pairs … refuses four" undercounted the corpus
by four pairs and the refusals by one. The `examples/real-world/README.md`
claim of "238 test cases total, 0 failing" remains wrong for the same
reason it was wrong then.

### Finding 7 re-confirmed

Any partial run still exits non-zero on coverage even when every selected
test passes:

```console
$ python -m pytest tests/unit/test_smoke.py -q
FAIL Required test coverage of 83% not reached. Total coverage: 0.01%
2 passed in 1.56s
```

---

## Finding 5 — `test` and `test-cross-platform` are still disabled, and the stated reason is still measurably false (MEDIUM, confirmed)

Carried forward from Finding 3 and re-measured, because the evidence is
now inside the workflow's own job log. On the most recent `main` run
(`35117257949`, 2026-09-16), the job steps report:

| job | conclusion | test step duration |
|---|---|---|
| `lint` | success | — |
| `cobol-parser-compat` | success | 15:43:41 → 15:43:52 = **11s** |
| `test` | **skipped** | — |
| `test-cross-platform` | **skipped** | — |

The rationale on both disabled jobs is `# test suite removed from CI (too
long)`. The same suite, on a GitHub runner, in the same workflow, took
**11 seconds**. It was 9.07s at the last audit and 12.33s locally; it is
14.42s locally now. Nothing about this tier is slow.

What stays uncovered is the part that matters most: `tests/integration/`
is 38 files, 36 of them `@requires_docker`, and `test` was its only home.
The framework's central claim — that it compiles and runs real COBOL under
GnuCOBOL — has now had no automated verification for a month.

### Fix

Unchanged from last time, and now cheaper to justify: re-enable `test`
restricted to `tests/unit` on every push/PR, and move `tests/integration`
to the `schedule` trigger that already exists in this workflow.

---

## What is healthy

Stated plainly, because the findings above cluster in one layer — the seam
with the sibling parser — and should not be read as a verdict on the whole
project.

- **The last audit's user-visible defects were actually fixed, at the
  root.** `--version` is correct, and `release-please-config.json` now
  names the file explicitly rather than depending on the distribution name
  matching the package directory — the fix addresses the mechanism, not
  the symptom. `main` has been green on every run since.
- **Security posture remains clean.** No `shell=True`, no `eval`, no
  `exec`, no `os.system` anywhere in `mockymock/`. The dashboard still
  binds `127.0.0.1` with the bind address non-configurable and a comment
  explaining why exposing it would hand out an unauthenticated endpoint.
- **`ruff` and `black` are clean** across all 201 files (up from 183). 9
  `TODO`/`FIXME` markers and 10 broad `except Exception` handlers — both
  essentially flat against the last audit despite ~3,500 new lines.
- **Coverage held through a large feature push.** 88.19% against an 83%
  floor, on 1,822 collected tests across 131 files, after adding
  `ai_mode.py`, `config.py`, `discovery.py` and `doctor.py`. New code
  arrived with its tests.
- **The gating is honest, which is why this audit could find it.** Every
  one of the 51 skips names what it needs; `test_enterprise_corpus.py`
  goes as far as telling the reader to bump the pin once the release
  exists. Finding 2 is a problem of *where those gates run*, not of anyone
  hiding a gap — a project that skipped silently would have looked
  healthier and been worse.
- **`doctor` is a good idea, well executed.** It surfaces Docker, the
  toolchain image, the compiler, the parser, the config file and the AI
  mode in one screen, degrades cleanly to `[ N/A]` when the daemon is
  unreachable, and exits non-zero when not ready. Finding 3 is one wrong
  data source inside an otherwise well-built command.

---

## Prioritized recommendations

### Do now

1. **Make an unreadable `cobol.yml` degrade rather than fail** (Finding 1).
   This is the only finding here that is broken for users of the released
   package today, and it is triggered by a file the tool family actively
   encourages people to write. Add `--config`/`--no-config` while in there.
2. **Add a CI job that runs the unit tier against cobol-parser `main`**
   (Finding 2). ~11s, and it is the gate that would have caught Finding 1
   pre-merge. It converts 42 unreachable tests into a live signal.
3. **Chase the `1.9.0` PyPI publish upstream** (Finding 4) — most likely a
   deployment approval never granted. Everything downstream of it (the
   floor bump, 8 skips, the Report Writer / XML PARSE / CHAIN features) is
   blocked on a re-run that `skip-existing: true` already makes safe.

### Do next

4. **Point `doctor` at `importlib.metadata`** (Finding 3) — a two-line fix
   that makes the diagnostic correct against every release in the wild.
5. **Re-enable `test` on `tests/unit`, integration on `schedule`**
   (Finding 5). The "too long" rationale is now contradicted by the
   workflow's own job timings three audits running.
6. **Install real dependencies in the lint job and fix the four seam
   errors** (2026-09-05 Finding 4, untouched). Still four errors, still one
   file.

### Do when convenient

7. Fix the `PERFORM ... THRU` terminus false refusal (2026-09-05 Finding 2)
   and confirm all five examples go green — then add the Docker-free
   `examples/**` lint gate that would have caught the fifth.
8. Correct `examples/real-world/README.md`'s "0 failing" claim, or fix the
   gate first and leave it true.
9. Move the coverage gate out of `addopts` (Finding 7); regenerate
   `uv.lock`, now two minor versions stale (Finding 8); untrack
   `_superbol/lsp-cache` (Finding 9).

### Structural observation

Last audit's pattern was *a guard existed, was correct, and was not
running*. This one is narrower and sharper: **the project's most important
dependency edge is the one thing nothing tests.** `cobol-parser-compat`
verifies mockymock against the published parser; nothing verifies it
against the parser it is actually being written for. So code lands that
cannot work on any installable version (Finding 1), 42 tests go dormant
without anyone noticing (Finding 2), a wrong version string propagates
into the diagnostic tool (Finding 3), and a release that would relieve
several of these sits un-published for eleven days (Finding 4) — four
findings, one missing job.

The fix is not more gates. It is one more CI job on the other side of the
same seam.
