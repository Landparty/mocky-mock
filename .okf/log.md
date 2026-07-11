# mocky-mock OKF Bundle — Update Log

<<<<<<< HEAD
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
=======
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
>>>>>>> origin/main

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
