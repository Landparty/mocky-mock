# mocky-mock OKF Bundle — Update Log

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
