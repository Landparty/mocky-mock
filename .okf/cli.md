---
type: Module
title: CLI
description: argparse entry point (setup, init, generate, fixtures, run, debug, lint, mutate, collect, explain, dashboard, doctor, export, analyze, skills) that orchestrates the splicer, GnuCOBOL runtime, and report formatters.
tags: [cli, entrypoint]
timestamp: 2026-09-16T00:00:00Z
---

# Overview

`mockymock/cli/main.py` is the single argparse-based entry point (`prog="mockymock"`,
`--version` from `mockymock.__version__`). It defines fifteen subcommands —
`setup`, `init`, `generate`, `fixtures`, `run`, `debug`, `lint`, `mutate`, `collect`, `explain`, `dashboard`, `doctor`, `export`, `analyze`, `skills` — each wired via `set_defaults(func=...)` and
dispatched from `main()`. All heavy imports (`cobolparser`, `mockymock.analysis`,
`mockymock.splicer`, `mockymock.runtime`, `mockymock.dsl`, `mockymock.report`,
`mockymock.debug`, `mockymock.web`) are
deferred into each `_cmd_*` function body rather than imported at module top —
so `mockymock --version` / `--help` stay fast and don't require Docker or a
parser install to resolve.

```
mockymock setup     -> runtime.docker_toolchain only (build image, start container)
mockymock init      -> _cmd_generate(--with-data) then _cmd_run(--record-expectations), reentrant  (Docker iff doctor reports ready)
mockymock generate  -> parse -> analysis.mock_surface -> dsl.generator  (no Docker)
mockymock fixtures  -> parse -> cobolparser.ProgramFixtureGenerator -> JSON on stdout  (no Docker, no mockymock analysis at all)
mockymock run       -> cli.checks (static) -> splicer -> runtime -> report
mockymock debug     -> cli.checks (static) -> splicer -> runtime (debug=True) -> debug.adapter (DAP over stdio)
mockymock mutate    -> mutation.operators (no Docker with --list) -> mutation.runner (per-mutant: cli.checks -> splicer -> runtime) -> mutation.report
mockymock lint      -> cli.checks only  (no Docker, structural guarantee)
mockymock collect   -> dsl.parser only  (no Docker, no .cbl needed; --boundaries also parses program via analysis.mock_surface)
mockymock explain   -> analysis.refusal.REFUSAL_EXPLANATIONS only  (no Docker, no parsing at all)
mockymock dashboard -> web.server (loopback HTTP) -> runtime.status.probe()  (read-only Docker)
mockymock doctor    -> cli.doctor -> runtime.status.probe() + cobol-parser/config/ai_mode checks  (no Docker mutation, no HTTP)
mockymock analyze   -> sys.argv monkeypatch -> cobolparser.cli.parse.main() (no Docker, pure pass-through)
mockymock export    -> cli.checks (static) -> splicer -> cli.mainframe_export (no Docker)
mockymock skills    -> skills_cmd (install: no Docker, no parsing -- a copytree)
                       cli.ai_mode (mode: reads/writes the config file's ai_mode key)
```

If no subcommand is given, `main()` prints help and returns 1 (`args` has no
`func` attribute).

## The universal `cobol.yml` project config (2026-09-16)

`load_config()` now reads **two** files, layered. Design:
`docs/2026-09-16-universal-yaml-config-design.md`.

1. **`cobol.yml`** / **`cobol.yaml`** -- the universal project config the
   whole tool family reads (this CLI, `cobol-parser`, the COBOL Analyzer
   extension). Its `project:` section supplies the settings shared with every
   other tool (`copybook_path`, `seed`); its `mockymock:` section supplies
   this CLI's own (`test_root`, `ai_mode`) and overrides anything `project:`
   said. Schema reference: `docs/project-config.md` in the cobol-parser repo.
2. **`mockymock.toml`** / `pyproject.toml`'s `[tool.mockymock]` -- the
   tool-specific file, unchanged.

Each is found by its **own** upward walk (nearest wins per file), so a
`cobol.yml` at a repo root and a `mockymock.toml` in a subproject both apply.
When both exist the tool-specific file **overrides the universal one key by
key** -- `_validated_values()` returns only the keys a file actually sets,
which is what makes that merge possible. First-match-wins across the two was
rejected: a `mockymock.toml` setting only `seed` would silently discard a
`cobol.yml` that set the other three.

`MockymockConfig.sources` lists every contributing file, base first;
`.source` stays the one that had the last word (where `skills mode --set`
would write), and `doctor` reports the whole chain rather than just the
winner.

The YAML parsing and the `project:` schema are **cobol-parser's**
(`cobolparser.config.load_project_config`), soft-imported: that module lands
in cobol-parser 1.10, the dependency floor here is deliberately not raised
for it, and a project with a `cobol.yml` on an older parser gets a
`ConfigError` naming the version to install. The discovery walk itself is
implemented here (`find_universal_config()`) precisely so that case produces
that message instead of silently skipping the file.

`skills mode --set` **refuses** to rewrite a `cobol.yml`, printing the two
lines to paste under its `mockymock:` section -- unlike the `pyproject.toml`
refusal (where a new `mockymock.toml` would shadow the whole table), a new
file here would layer correctly, but splitting a project's settings across
two files when the point of the universal one is a single place is not a
decision to make for the user.

## Argument resolution (2026-09-15)

Before dispatch, `main()` loads the project config file
(`mockymock/cli/config.py`'s `load_config()`: the `cobol.yml` and
`mockymock.toml` / `[tool.mockymock]` layers above, searched from cwd upward)
and stashes it on `args._config`; a malformed file is `ConfigError`, caught in
`main()`. Only a subcommand that would read the config (one whose
subparser defines `copybook_path` or `seed`) fails on it -- printed as a
clean error, exit 1, as JSON for `collect --json` and on stderr for
`fixtures` so their machine-readable stdout contracts hold; `collect`
without `--json`, `setup`, `dashboard`, `explain`, `skills`, `analyze` run
on with `args._config = None`, and `doctor` reloads the file itself to
report the error as a `WARN` check. Unknown keys are a `ConfigError` too
(a typo'd `copybook-path`, or `timeout`, which is deliberately not
config-overridable); `seed = true` is rejected (bool is an int subclass),
and an `ai_mode` outside `ai_mode.MODES` is rejected naming the valid set
rather than falling back to the default.
`test_root` is resolved relative to the config file that declares it, like
`copybook_path`, so `mockymock run` from a subdirectory scans the same
suites as from the project root.

`run`/`debug`/`lint`/`mutate`/`export` no longer require both `program` and
`--cut`: `_resolve_program_and_cut()` (`cli/main.py`) fills in whichever one
is missing from its same-stem sibling file via
`mockymock/cli/discovery.py`'s `resolve_program_path`/`resolve_cut_path`
(mirrors mocky-mock-vscode's `resolveCblPath`/`resolveCutPath`). `run`/`lint`
with *neither* given fall into `_run_directory`/`_lint_directory`:
`discover_cut_files()` walks the test root (config's `test_root`, default
`.`; the exclude list applies to directories *below* the root only, so an
absolute test root under `build/` is still scanned) and each command's own
single-pair `_cmd_run`/`_cmd_lint` is called
once per discovered `(program, .cut)` pair via a shallow `copy.copy(args)`
(every output-file flag -- `--junit-xml`, `--json-report`,
`--coverage-json`, `--coverage-out`, `--trace-json` -- gets a per-pair name
from `_per_pair_report_path`, which folds the `.cut`'s path *relative to the
test root* into the file name so `svc1/PROG.cut` and `svc2/PROG.cut` never
share one report)
— not a parallel implementation, so an explicit single-pair invocation is
byte-for-byte unaffected.

`_apply_config_to_args()` fills `args.copybook_path`/`args.seed` from the
loaded config when the CLI flag was left at its argparse default; an
explicit flag always wins. `--timeout` (run/mutate) is deliberately not
config-overridable — see the docstring on `_apply_config_to_args` for why.

See `docs/2026-09-15-cli-ergonomics-design.md`.

**Default copybook search directories (2026-09-15):** once a
single-pair `program`/`.cut` is resolved, `_apply_config_to_args(args,
source_path)` additionally runs `discovery.effective_copybook_paths()`,
which appends `source_path`'s own `copybooks/` subdirectory to
`args.copybook_path` when it exists and isn't already present — the
layout every `examples/real-world/` program uses. This is additive
after the explicit-flag/config resolution, never a replacement, and a
program with no `copybooks/` subdirectory pays no cost. Deliberately
does **not** also default to the program's own directory (that always
exists trivially and would turn every COPY-bearing program into an
implicit copybook search even with nothing configured — see the
docstring on `effective_copybook_paths` for the regression this would
cause). A `CopybookNotFoundError` raised by `expand_copybooks` (in
`cli/checks.py`'s shared `run_static_checks`, and in `_cmd_generate`/
`_cmd_fixtures`'s own separate `expand_copybooks` calls) gets one
appended continuation line from `discovery.copybook_not_found_hint()`
naming both remedies (`--copybook-path`, the config file). See
`docs/2026-09-15-copybook-discovery-defaults-design.md`; the upstream
half (cobol-parser's `suggest_similar_copybooks` no longer suggesting a
non-copybook file) is `Landparty/cobol-parser`'s own change.

# Subcommands

## `mockymock setup [--rebuild]`

Orchestrates only `mockymock.runtime.docker_toolchain`:

1. `docker_toolchain.ensure_toolchain(force_rebuild=args.rebuild)` — builds the
   GnuCOBOL image and starts the `mockymock-cobc` container if not already
   running.
2. `docker_toolchain.cobc_version()` — printed for confirmation.

On `DockerNotAvailableError`, prints `mockymock setup: <exc>` and exits 1.
Optional in normal workflows: `mockymock run` calls `ensure_toolchain()` itself,
so `setup` exists mainly for a fast up-front check / CI warm-up.

`--rebuild` is the only way to force a fresh image build when the
content-hash tag hasn't changed (an edited base image, a poisoned layer
cache). It also recreates the container, because the rebuilt image re-uses
the same tag and the stale-container check compares tags — see
[runtime](runtime.md)'s **Forced rebuild** section for why skipping that
removal left every later compile in the old toolchain. To *inspect*
readiness without building or starting anything, use `doctor` instead.

## `mockymock init <program> [-o/--output PATH] [--seed N] [--scenarios happy|branches|all] [--copybook-path DIR ...] [--force]` (2026-09-15)

Composes `generate --with-data` + `run --record-expectations` into one
step, so a first scaffold has real generated data and recorded expected
values instead of empty mock bodies. `_cmd_init` (`cli/main.py`):

1. `_check_input_files` on `program`; refuses if the resolved output
   `.cut` path already exists and `--force` wasn't given (a check `init`
   owns itself -- plain `generate` has no such guard at all, and adding
   one there was out of scope for this design).
2. Builds a real `generate --with-data --scenarios <...> [--seed <...>]
   [--copybook-path <...>]*` argv list and parses it with this module's
   own `build_parser()`, then calls `_cmd_generate` on the result --
   reentrant rather than a refactor of `_cmd_generate`'s internals (a
   deliberate departure from the original design doc's proposed
   plain-function-returning-a-result-object refactor: lower risk for the
   same external behavior). Stops here, propagating the exit code, if
   `generate` itself failed (e.g. a zero-scenario bundle).
3. `--scenarios branches|all` prints the scenario branch-verification
   caveat (`docs/2026-09-04-scenario-branch-verification.md`) -- a
   scenario named for an arm is not yet verified to reach it.
4. `doctor.gather_full_status()` (read-only, mutates nothing) decides
   whether to attempt a run at all. Not ready: prints a fallback message
   naming the exact `run --cut ... --record-expectations` command to run
   later, and returns 0 (the scaffold with real data is still a
   strictly better outcome than plain `generate`, even unrecorded).
   Ready: builds a `run --cut <output> --record-expectations
   [--copybook-path <...>]*` argv the same way and calls `_cmd_run` on
   it, returning its own exit code.

See `docs/2026-09-15-init-command-design.md`.

## `mockymock generate <program> [-o/--output PATH] [--copybook-path DIR ...] [--with-data] [--fixtures PATH] [--seed N] [--scenarios happy|branches|all] [--rows N] [--placeholder CATEGORY:KEY ...] [--fill CUT_FILE]`

Scaffolds a starter `.cut` test file from a COBOL program. Does **not** touch
Docker/GnuCOBOL — pure parse-and-analyze.

**`--fill CUT_FILE` (2026-09-15)** is a separate mode, dispatched (after
`_apply_config_to_args`, so config-file copybook paths apply) before any
of the flags below: inserts only the `MOCK ... END-MOCK` blocks `CUT_FILE`'s
own test cases are missing (per `checks.run_static_checks`'s
`unmocked_reasons`, keyed by the case's index in `suite.test_cases` since
duplicate TESTCASE names are legal), writing back to `CUT_FILE` in place.
One block per distinct header per case (two reachable READs of one file
are one `MOCK READ`, never a duplicate the parser rejects); the anchor
PERFORM is the case's own, skipping any PERFORM inside a `MOCK ... END-MOCK`
body; `directive_snippet` declines the sites the scaffold itself skips (a
nested site with no span, an unspliceable top-level site). Every problem
`--fill` cannot fix (a flow-mock target that does not exist, an `UNMOCKED_*`
reason with no mechanical fix) is printed and exits 1, so `--fill` exiting 0
means the next `lint` exits 0. Reported `file:line` is where each block
landed in the written file. Every existing directive, `EXPECT`/`VERIFY`, and
comment is left byte-for-byte untouched — insertion happens at known line
numbers (found via `dsl.parser._PERFORM_RE` locating each case's own
`PERFORM` line), never by re-serializing the parsed model, and an existing
`MOCK` block is never edited even if empty or wrong. `_reindent_snippet`
re-renders `dsl.generator.directive_snippet`'s hardcoded-4-space output to
match the target file's own sniffed indentation. Mutually exclusive with
`-o`/`--output`, `--with-data`, `--fixtures` (checked at the top of
`_cmd_generate`, printed as a plain error). See
docs/2026-09-15-actionable-refusals-and-fill-design.md.

Flow (`_cmd_generate`):

1. Check `program` exists (`_check_input_files` -- clean `no such file`
   message, exit 1, no traceback).
2. Flag-only validation, before any file is read (unify-with-data Task 4):
   every `--placeholder` value must contain a `:` (`CATEGORY:KEY`) or exit
   1 with `mockymock generate: --placeholder must be CATEGORY:KEY, got
   <repr>` on stderr; the category half is uppercased, the key half kept
   exactly as given (`category.upper(), key` — matches a bundle fixture's
   own case-sensitive key, since the bundle's `category` string is always
   uppercase already). `--rows N` combined with `--fixtures PATH` exits 1
   with `mockymock generate: --rows is not valid together with
   --fixtures -- that bundle's row count is already baked in; use --rows
   with --with-data's self-generating path instead` on stderr — that
   bundle's row counts are already fixed by whoever generated the JSON.
3. Resolve the fixture bundle (Phase 8 of the gen-fixtures initiative;
   `bundle` stays `None` if neither flag is given, giving the original
   bundle-less scaffold below): `--fixtures PATH` loads a pre-generated
   bundle JSON via `load_fixture_bundle_file` (fails closed with a printed
   message on an unsupported `bundle_version` or malformed JSON);
   `--with-data` instead calls cobol-parser's
   `ProgramFixtureGenerator(DataGeneratorOptions(rows=args.rows))` when
   `args.rows is not None` (else the plain, default-options
   `ProgramFixtureGenerator()` — `is not None` deliberately, so `--rows 0`
   is honored rather than treated as falsy), then
   `.generate_with_scenarios_from_file(program, mode=args.scenarios,
   seed=args.seed, copybook_paths=...)` on it directly (no subprocess —
   mockymock calls the Python API) and loads its `.to_dict()` output the
   same way. A bundle with zero
   scenarios (possible for `--scenarios branches|all` on a program with no
   branch arms; `happy` always produces exactly one) refuses with a
   printed message and exit 1 — nothing to scaffold a TESTCASE from.
4. If any `--placeholder` pairs were given, warn (not refuse) on stderr
   for each one that matched no fixture anywhere in the resolved bundle's
   scenarios: `mockymock generate: warning: --placeholder CATEGORY:KEY
   matched no fixture` — command still exits 0 for this alone; a
   deliberate improvement over the parked `feature/generate-with-data`
   branch's own silent no-op on the same case.
5. Read `program`; if `--copybook-path` given (repeatable), run
   `expand_copybooks` first (wrapped in try/except since 2026-08-10, audit
   finding F6 — a genuinely circular/oversized/mis-encoded copybook chain
   raises `CircularReferenceError`/`NestingDepthError`/
   `TotalExpansionSizeExceededError`/`EncodingError` for realistic inputs,
   and this call site was the one of six sharing this pattern that still
   let it traceback instead of exiting 1 cleanly — `_cmd_fixtures` below
   already had the same guard). Each command prints the exception under
   its own prefix, not a shared one: `generate` prints
   `mockymock generate: {exc}` (this step); `fixtures` prints
   `mockymock fixtures: {exc}` to stderr (see below); `run`/`lint`/
   `debug`/`export`/`mutate`, sharing `run_static_checks`, print
   `copybook expansion failed: {exc}` (see that step under `run` below).
   Then use the expanded source from then on. `check_expansion_warnings(expansion)`
   refuses (EXPANSION_WARNING, exit 1) on a lossy copybook decode before the
   corrupted text is ever parsed.
6. `parse_cobol(raw_source, filename=...)` — on parse failure, print each error
   and exit 1 (never reaches analysis). On a successful parse,
   `check_whole_program(result)` still refuses (PARSE_WARNING, exit 1) if
   `ParseResult.warnings` reports dropped statements — a scaffold built from
   an incomplete AST would silently miss boundaries.
7. `check_unresolved_copybooks(raw_source)` — a **refusal** check run even
   though the program parsed; any reason printed as
   `mockymock generate: refused (<code>): <message>` and exit 1.
8. `analyze(result.ast)` -> `mock_surface` (the boundary-site inventory).
9. `normalize_fixed_format` the source, then `annotate_nested_sites` +
   `collect_scope_map` to mark which nested boundary statements are
   spliceable — this must run before `scaffold_cut` so the generated `.cut`
   only proposes cases that `run` will actually accept.
10. `scaffold_cut(program_name, surface, bundle, frozenset(placeholder_pairs))`
    builds the `.cut` text (`bundle=None` scaffolds one `TESTCASE` per
    paragraph as before; a real bundle scaffolds one `TESTCASE` per
    scenario with generated data and `EXPECT`/`VERIFY`/stub-comment
    expectations instead of placeholder bodies, with any `--placeholder`-named
    fixture's body downgraded and its tier-1 `call_count` VERIFY
    recomputed where the downgrade changed it — see `dsl.md`'s
    "Bundle-driven scaffold" and "`--rows`/`--placeholder`" sections);
    written to `--output` or `<program>.cut` (suffix-swapped) by default.
11. Prints a `wrote N test case(s) -> path` summary (plus a `data-driven
    from a fixture bundle (seed=N)` line when a bundle was used), then
    `_report_unsupported_boundaries(surface)`. If the bundle's own
    `(category, key)` set disagreed with `mock_surface`'s,
    `_warn_on_key_mismatch` already printed a loud stderr warning during
    step 10 — see `dsl.md`.

`_report_unsupported_boundaries` is the only non-trivial logic in this module:
it walks `surface.boundary_sites` and names every site that stays unmockable —
either `site.category is None` (uncategorized boundary, e.g. a SORT/MERGE
mixing a USING/GIVING file with an INPUT/OUTPUT PROCEDURE on the other
side, or an identifier-less dynamic CALL — a plain-file-form SORT/MERGE, a
pure-procedure-form SORT [never even recorded as a site], and RELEASE/
RETURN all have a category and never appear here, see `analysis.md`) or
`site.nested and site.span is
None` (a nested site the splicer couldn't isolate, printed with
`site.unspliceable_reason`). This list is purely informational at `generate`
time — the scaffold is emitted regardless — but it documents exactly which
test cases `run` will later refuse if a case's PERFORM reaches one of these
sites. Comment in the source explicitly frames this as "so the scaffold is
never mistaken for complete coverage of the program's outputs."

## `mockymock fixtures <program> [--scenarios happy|branches|all] [--seed N] [--rows N] [--copybook-path DIR ...]`

Prints a cobol-parser `FixtureBundle` (scenarios, generated mock data,
expectations) as JSON on stdout, for editor integrations (the VS Code
tree view consumes this) rather than for scaffolding a `.cut` directly —
that is `generate --with-data`'s job. Unlike every other subcommand,
`_cmd_fixtures` does not follow the `_check_input_files` convention: it
has its own `Path.is_file()` gate, and **stdout must be EXACTLY the JSON
document** — every diagnostic, including the plain "no such file" message,
goes to stderr instead, so a caller can always safely `json.loads(stdout)`
on exit 0 without stripping any banner text.

Flow (`_cmd_fixtures`):

1. `program` must exist, or `mockymock fixtures: no such file: <path>` on
   stderr, exit 1.
2. If `--copybook-path` given (repeatable), `expand_copybooks` runs on the
   raw source first (any exception printed verbatim to stderr, exit 1) —
   deliberately mirrors `_cmd_generate`'s own ordering (expand before the
   parse gate below), so this gate sees the same source
   `generate_with_scenarios_from_file` will itself go on to parse
   internally: gating on the raw, unexpanded source would let an
   unresolvable `COPY` slide past as a no-op (cobolparser tolerates
   unexpanded `COPY` under `FAIL_FAST`) instead of being refused here.
   `generate_with_scenarios_from_file` still re-expands and re-parses
   internally — that duplicate work is the price of a correctness gate
   rather than one that merely happens to work.
3. `parse_cobol` the (possibly expanded) source; on failure, print
   `mockymock fixtures: N parse error(s):` plus each error to stderr, exit
   1. Needed because `ProgramFixtureGenerator` itself only raises when the
   AST comes back `None` entirely (missing file, an unresolved copybook
   under strict mode) — a source that merely fails to parse (bad syntax,
   no recognizable division) still yields a placeholder AST, and
   `generate_with_scenarios_from_file` would happily return an empty
   bundle for it instead of failing, which would look like a real (if
   boring) program to a caller.
4. `ProgramFixtureGenerator(DataGeneratorOptions(rows=args.rows))` when
   `args.rows is not None` (else the plain `ProgramFixtureGenerator()` —
   `is not None` deliberately, so `--rows 0` is honored), then
   `.generate_with_scenarios_from_file(program, copybook_paths=...,
   mode=args.scenarios, seed=args.seed)` — any exception printed verbatim
   to stderr as `mockymock fixtures: <exc>`, exit 1.
5. `print(bundle.to_json())` to stdout, exit 0.

## `mockymock run <program> --cut PATH [--junit-xml PATH] [--json-report PATH] [--case NAME ...] [--tag TAG ...] [--copybook-path DIR ...] [--keep-sandbox] [--verbose] [--coverage] [--coverage-out PATH] [--coverage-json PATH] [--coverage-fail-under PERCENT] [--trace] [--trace-json PATH] [--timeout S] [--record-expectations]`

The full pipeline: parse, analyze, refuse-or-splice, compile in Docker, run,
report. This is the only subcommand requiring the GnuCOBOL container.

Since the lint extraction (docs/2026-07-18-cut-lint-command-design.md), every
pre-toolchain check (steps 2-10 below) lives in
`mockymock/cli/checks.py::run_static_checks` and runs **before**
`ensure_toolchain()` — a bad `.cut`/`.cbl` fails fast with the real problem
even when Docker is down. `run` and `lint` share this function so they can
never disagree about what refuses.

Flags beyond the pipeline inputs:

- `--junit-xml PATH` — write `format_junit_xml(...)` there after a run that
  reaches execution. Each `<testcase>` carries `classname="<suite name>"`.
  A refusal or a compile failure (steps 5b/10 and 15 below) also writes
  this file when the flag is given, via `_write_failure_reports`: one
  synthetic `<testcase>` standing in for the whole run, its `<failure>`
  text carrying the refusal reasons or the compiler's stderr. Before this
  (carried-over open item, 2026-08-10 framework audit), those two exit
  paths left the target untouched, so a CI pipeline that always publishes
  whatever the configured path holds saw "no test results found" instead
  of a visible failure.
- `--json-report PATH` — write `report.json_report`'s machine-readable run
  report: per-case status (`passed`/`failed`/`crashed`/`not_run`), `.cut`
  line numbers for cases and failing EXPECT/VERIFY directives,
  expected/actual split into fields, tags. Built for editor integrations
  (the VS Code extension). Same refusal/compile-failure synthesis as
  `--junit-xml` above applies here too.
- `--timeout S` (default 30) — `run_binary`'s execution timeout in
  seconds, mirroring `mutate`'s own `--timeout`; previously only `mutate`
  could shorten or lengthen the bound a hung mocked CALL is killed by.
- `--case NAME` (repeatable) / `--tag TAG` (repeatable) — run only the named
  or tagged TESTCASEs (union when both given). Selection happens in
  `run_static_checks` before any per-case refusal check, so a refused
  sibling case no longer blocks running a clean one. An unknown name/tag is
  a static problem listing what is available. The suite still runs as ONE
  compile + binary — just with only the selected cases spliced in.
- `--coverage` — the console report leads with the ORIGINAL `.cbl`'s own
  percentage and lists its own uncovered lines by their original line
  numbers; the instrumented sandbox copy's higher number (it counts
  mockymock's injected dispatch/driver lines) follows on one labelled
  line. Before 2026-09-04 only the instrumented figure was printed and the
  meaningful one lived solely in `--coverage-json`, so the number most
  people read was the less useful one. See [coverage](coverage.md).
- `--coverage-json PATH` (implies `--coverage`) — write machine-readable
  coverage remapped onto the ORIGINAL `.cbl`'s line numbers via
  `report.coverage.map_coverage_to_original` (difflib alignment
  instrumented -> normalized -> original; splicer-inserted lines are
  excluded, so it answers "which of MY lines ran"). Both `original` and
  `instrumented` carry their own `percentage`.
- `--coverage-fail-under PERCENT` (implies `--coverage`) — exit 1 when the
  ORIGINAL program's coverage is below `PERCENT`: the `run` counterpart of
  `mutate --fail-under`, so coverage can be CI-gated the same way mutation
  score already could. Folded into the command's final exit-code decision
  (so `--trace` still prints), and a failed `gcov` pass fails the gate
  rather than silently satisfying it.
- `--trace` / `--trace-json PATH` — replay ONE test case's execution: the
  path it took through the original `.cbl` plus the mocks that fired in
  order. `--trace-json` implies `--trace` (the same relationship
  `--coverage-json` has to `--coverage`). **Refuses unless exactly one
  `--case` is selected and no `--tag`** — the suite runs as a single
  binary and the trace file is a separate stream from stdout carrying no
  case markers, so an unscoped trace cannot be attributed to one case.
  That refusal fires before `run_static_checks` and before
  `ensure_toolchain()`. Composes two channels: the executed path from
  GnuCOBOL's trace file, and the mock timeline from stdout — see
  [report](report.md) and docs/2026-07-21-debug-trace-design.md.
- `--record-expectations` — golden/characterization mode: run the suite,
  capture the real runtime value behind every `*> STUB EXPECT <name>`
  comment in the `.cut` file (see [dsl](dsl.md)), and rewrite the file in
  place with those stubs turned into real `EXPECT` lines. Best-effort and
  cumulative (a `recorded N, skipped M` summary prints, with a reason per
  skip); never touches a line that isn't a stub comment (a hand-written or
  previously-recorded `EXPECT` is never overwritten -- structurally, not by
  a tracked flag); never rewrites the file at all if nothing was recorded;
  does not change the run's exit code. Composes freely with
  `--case`/`--tag` (only stubs inside a selected case can record anything)
  and with every other flag above. See [analysis](analysis.md),
  [splicer](splicer.md), [report](report.md), and
  docs/2026-08-04-record-expectations-design.md for the full design.
- `--keep-sandbox` — never delete the sandbox directory; its path is
  printed at the start of the run for inspection.
- `--verbose` — on compile failure, print the path to the instrumented
  source. Implementation detail: this also forces sandbox retention through
  the context manager (the printed path must still exist when the user
  reads it — deliberately, and covered by an integration test), but the
  CLI explicitly removes the sandbox afterwards when the run got past
  compilation, so plain `--verbose` leaves no cruft on success. Since
  2026-08-10 (audit finding F10) that removal is a `try/finally` around
  just the `run_binary`/`run_gcov` phase, not the compile-failure branch
  above — an exception there prints no path pointing at the sandbox (unlike
  a compile failure), so it used to leak permanently instead of ever being
  found. A bare statement placed after the `with` block only ran on that
  phase's normal completion. See [runtime](runtime.md)'s Sandbox model
  section.

Flow (`_cmd_run`), in strict order (each step's ordering is load-bearing):

0. `_check_input_files("mockymock run", program, cut)` — both paths must
   exist; each missing one prints a clean `mockymock run: no such file:`
   line and the command exits 1 **before** `ensure_toolchain()` runs, so a
   typo'd path never pays for (or tracebacks after) a multi-minute image
   build.
1. `docker_toolchain.ensure_toolchain()` — brings the container up if needed
   (so `mockymock setup` is optional before `run`); also recreates the
   container when its image tag is stale (see [runtime](runtime.md)).
   `DockerNotAvailableError` -> print and exit 1.
2. Read `program`, apply `--copybook-path` expansion same as `generate`
   (`run_static_checks` wraps this in try/except too, since 2026-08-10,
   audit finding F6 — shared by `run`/`lint`/`debug`/`export`/`mutate`, so
   this one guard covers all five instead of each needing its own).
   `check_expansion_warnings(expansion)` refuses (EXPANSION_WARNING, exit 1)
   on a lossy copybook decode before the corrupted text is ever parsed.
3. `parse_cobol` -> `check_whole_program_scoped(result)` refusals
   (PARSE_ERROR on a failed parse, PARSE_WARNING per `ParseResult.warnings`
   entry — dropped statements on an otherwise "clean" parse) are printed
   and any of them exits 1. A warning provably confined to one paragraph's
   own body is *held back* here and resolved in step 5b instead (see
   [analysis](analysis.md)).
4. `check_unresolved_copybooks_scoped(raw_source, ast)` — same refusal gate
   as `generate`, except a paragraph-local COPY with a verified own-lines
   span is held back for step 5b too.
5. Parse the `.cut` file: `parse_cut(cut_path.read_text())` -> `suite`.
   `CutParseError` is caught and printed as
   `mockymock run: invalid .cut file <path>: <line-numbered message>`,
   exit 1 — never a raw traceback.
5b. Held-back paragraph-scoped refusals resolve against
   `union_executed_paragraphs(ast, suite)` — the union of every SELECTED
   case's reachable set, GO TO fall-through closed; `None` (untrustable)
   refuses everything held back. Refused -> printed, exit 1. Waived -> one
   `StaticCheckResult.notes` transparency line each (printed with the
   command prefix), and a waived COPY's span is commented out of `lines`
   in step 6 so cobc never sees an unresolvable COPY.
6. `analyze(result.ast)` -> `surface`; normalize source to `lines`.
7. **`annotate_nested_sites` must run before any refusal check or splice looks
   at nested sites** (explicit comment in source) — unannotated nested sites
   are treated as refused by construction, so annotating late would produce
   false refusals.
8. `check_nested_exec(surface)` refusal gate.
9. `transform_data_division_exec(lines)` is called here **only to pre-check**
   refusal reasons (`SQLCA` synthesis issues) — the returned transformed lines
   are discarded (`_, data_exec_reasons = ...`). The actual transform is
   re-run *after* splicing, because it inserts/removes lines, which would
   otherwise shift the AST-derived statement spans the splicer depends on.
   This double-call-with-discard is the key non-obvious sequencing trap in
   this file.
10. `analyze_file_status_fields(result.ast)` -> `file_status_fields` (an
    ENVIRONMENT DIVISION FILE-CONTROL walk, separate from `analyze()`),
    then `check_test_case(surface, result.ast, case, file_status_fields)`
    for every case in the suite — any refusal sets `refused = True`; all
    cases are checked before exiting (so a user sees every problem in one
    run), then exit 1 if any fired. See [analysis](analysis.md). Every
    refusal exit in `_cmd_run` (this step and every earlier one) calls
    `_write_failure_reports(args, "run", <suite name or "">, <joined
    problems>)` before returning 1 — see the `--junit-xml`/`--json-report`
    bullets above.
11. `collect_boundaries(result.ast)`, `TallyRegistry(suite)`,
    `find_terminator_plans(...)`, `find_flow_mock_plans(...)`,
    `splice_program(lines, boundaries, surface, suite, registry,
    terminator_plans, flow_plans, file_status_fields)` — the actual source
    rewrite (`file_status_fields` flows through to
    `injector.build_site_dispatch`'s default-success/override status MOVE,
    see [splicer](splicer.md)). Then `transform_data_division_exec(lines)`
    runs for real (its output is kept this time).
12. `reset_move_lines(result.ast)` + `build_driver(suite, reset_lines,
    registry, record_targets)` build the test-driver artifact
    (WORKING-STORAGE fields + PROCEDURE DIVISION statements for the
    harness). `--record-expectations` only: immediately before this call,
    `cut_path.read_text()` + `analysis.stub_expectations.scan_stub_expectations(cut_text,
    suite)` scan for `*> STUB EXPECT` comments against the POST-filter
    `suite` (`--case`/`--tag` already applied above), grouped into
    `record_targets: dict[case_index, list[data_name]]` and passed through
    here -- omitted (`{}`) entirely when the flag isn't set, so ordinary
    `run` is unaffected. See [analysis](analysis.md), [splicer](splicer.md),
    and docs/2026-08-04-record-expectations-design.md.
13. `_insert_driver(lines, artifact)` splices the driver in: WORKING-STORAGE
    additions go immediately after the `WORKING-STORAGE SECTION` header line;
    procedure lines go immediately after `PROCEDURE DIVISION` (matched via
    `line.strip().upper().startswith(...)`, first occurrence only — both
    insertions are one-shot via `inserted_ws`/`inserted_proc` flags).
14. Write the instrumented source into a fresh `sandbox_dir(root=docker_toolchain.WORK_ROOT)`
    as `<program-stem>.cbl` (LF newlines forced via `newline="\n"`).
15. `docker_toolchain.compile_source(...)` — on failure, print stderr,
    write `--junit-xml`/`--json-report` via `_write_failure_reports` (same
    as a static refusal, `reason=compiled.stderr`), and exit 1.
16. `docker_toolchain.run_binary(compiled.binary_path, timeout_seconds=args.timeout)`
    — executes inside the container.
17. `parse_stdout(executed.stdout)` -> `suite_result`. The binary's exit
    code is translated into `crash_detail` evidence for the formatters:
    exit 124 (TIMEOUT_EXIT_CODE) -> `"binary timed out (exit 124); see
    stderr below"`; any other nonzero exit -> `"binary exited with code
    <n>"`; exit 0 -> `None` (the formatters then fall back to the STOP RUN
    hypothesis for crashed cases — a reached STOP RUN exits 0).
    `format_console(suite_result, crash_detail=...)` is printed always;
    then, if `executed.stderr` is non-empty, it is printed under a
    `mockymock run: binary stderr:` header — this is how run_binary's
    exit-124 infinite-loop hint and libcob runtime aborts reach the user.
    `format_junit_xml(suite_result, crash_detail=...)` is written to
    `--junit-xml` if given. `--record-expectations` only: right after the
    stderr print, `record_rewrite.build_recording_report(stub_scan,
    suite_result)` then `rewrite_cut_text(cut_text, recording)` -- if the
    result isn't `None` (something was actually recorded), it's written
    back to `cut_path` and a `recorded N, skipped M` summary (with a
    reason per skip) is printed. See [report](report.md).
18. Exit 0 only if `suite_result.all_passed` **and** `executed.exit_code
    == 0` — a nonzero binary exit after the SUMMARY line still fails the
    run. **Unaffected by `--record-expectations`** — recording outcomes
    never change this; see the design doc's "Best-effort, cumulative
    reporting" section for why.

## `mockymock debug <program> --cut PATH --case NAME --dap-stdio [--copybook-path DIR ...]`

Starts an interactive Debug Adapter Protocol (DAP) session for a single
test case — breakpoints, stepping, a synthesized COBOL call stack, and
read-only variable inspection. See
docs/2026-07-22-dap-debugger-design.md and
docs/superpowers/plans/2026-07-22-dap-debugger-cli.md for the full design
and empirical basis (both were verified against a real container, not
just planned).

Unlike `run`'s trace/coverage flags, this is a real subcommand: a DAP
server is a fundamentally different, long-running mode, not "the same
pipeline plus an artifact." `--dap-stdio` is required — there is no
useful human-facing terminal mode for a DAP session, so `_cmd_debug`
refuses with a message pointing at the VS Code extension if it's absent.
Exactly one `--case` is required (same structural reason as `--trace`:
the suite compiles and runs as one binary, one execution stream).

`_cmd_debug` runs the same static-checks → splice pipeline as `_cmd_run`
(with `trace=False` always), then diverges: instead of `run_binary`, it
compiles with `compile_source(debug=True)` (`-g`) inside a `launch_session`
closure and hands that closure to a `DapAdapter`
(`mockymock/debug/adapter.py`) that speaks DAP JSON over stdio until the
client disconnects. The sandbox stays alive for the whole session (a
long-lived conversation), torn down only once `adapter.run()` returns.

`mockymock/debug/` modules, each independently unit-tested against real
captured MI transcripts and end-to-end tested against a live container
(`tests/integration/test_debug.py`):

- `gdb_session.py` — owns the long-lived `docker exec -i gdb
  --interpreter=mi2` subprocess; parses MI records (including treating any
  untagged line as the debuggee's own stdout); breakpoints; run/continue/
  step with the coalescing loop one COBOL statement's marker/body `#line`
  pair requires; `resolve_address` (temporary breakpoint insert/delete) for
  resolving a raw code address. `step`'s coalescing predicate requires
  being back in the instrumented `.cbl` file AND (when an
  `is_visible_line` callable is given, as `adapter.py` always does) the
  stopped line having an original-source counterpart — otherwise it keeps
  coalescing through splicer-inserted mock/driver statements (MOCK DLI
  bodies, test-case dispatch, tally/VERIFY checks), which live in the same
  instrumented file but have no original-line mapping. Without this, `next`
  could stop on one of those, and since the DAP layer can't show a line for
  it, the position displayed in the client froze across repeated Step Over
  clicks — indistinguishable from an infinite loop even though the program
  was progressing normally (see `log.md`).
  `send`/`_read_until_stopped`'s `readline()` is bounded to 30s since
  2026-08-10 (audit finding F4) — a debuggee stuck in an infinite loop
  produces no further MI record and gdb itself never reports it, and an
  unbounded blocking read there used to wedge the whole DAP adapter
  forever with no way for the client to even send `disconnect`. Bounded
  with a one-shot daemon thread per read (Windows pipe handles support no
  portable non-blocking/`select()`-based timeout), raising the existing
  `GdbSessionClosedError` on expiry. `decode_c_escape` (shared with
  `variable_map.py` below) handles gdb's octal byte-escape (`\NNN`) as
  well as the named ones (`\n \t \\ \"`) since 2026-08-10 (audit finding
  F15) — a non-printable byte with no named form used to decode as the
  literal digit characters instead of the single byte gdb meant.
  `runtime.start_gdb_session`'s `subprocess.Popen` now sets
  `encoding="utf-8", errors="replace"` (audit finding F5) so a
  garbage/non-UTF-8 byte from the debuggee's own output degrades that one
  line instead of raising `UnicodeDecodeError` and crashing the whole
  session.
- `line_map.py` — bidirectional original ↔ instrumented line mapping,
  built on `report/coverage.py`'s existing (one-directional)
  `build_original_line_map`.
- `variable_map.py` — COBOL name ↔ gdb expression, from the compiler's own
  `<name>.c.l.h` comment table (not gdb symbols, which don't exist for
  COBOL names, and not a byte-offset decoder). Decodes packed-decimal
  (COMP-3) and binary (COMP) values via GnuCOBOL's own `cob_field_attr`
  type/digits/scale, read live via MI. `_unquote_c_string` shares
  `gdb_session.py`'s `decode_c_escape` (see F15 above).
- `call_stack.py` — synthesizes the COBOL paragraph/section call stack
  from GnuCOBOL's internal `frame_stack`, since gdb's own backtrace is
  always exactly one frame (`PERFORM` is a computed-goto, not a real C
  call). `frame_stack[0]` is a sentinel, not a real caller — see the
  design doc's Empirical basis for why. `synthesize_stack`'s per-frame
  walk over `frame_stack[1..depth]` catches `GdbCommandError` on any one
  frame and skips it (`continue`) since 2026-08-10 (audit finding F14) —
  previously one unresolvable frame (gdb refusing the evaluate/
  resolve_address for it) failed the entire `stackTrace` request instead
  of just omitting that frame.
- `adapter.py` — the DAP server: `Content-Length`-framed JSON over
  injectable streams, `initialize`/`launch`/`setBreakpoints`/
  `configurationDone`/`threads`/`stackTrace`/`scopes`/`variables`/
  `evaluate`/`continue`/`next`/`stepIn`/`stepOut`/`disconnect`. `evaluate`
  backs the client's Watch panel, hover-inspect, and Debug Console — all
  three send the same DAP request — but only resolves plain COBOL
  identifiers already in `variable_table` (the same lookup `variables`
  uses); arithmetic/member-access expressions fail cleanly, not silently.
  `_handle_launch` closes any prior `self._session` and resets
  `self._breakpoint_numbers` before creating a new one (audit finding
  F16) — a second `launch` on one adapter (a client retry, or a bug) used
  to leak the first gdb session's process into the shared container and
  hand out breakpoint numbers that pointed at a session already gone.
  `read_dap_message`'s `Content-Length` header parse raises the new
  `DapFramingError` on a non-integer value instead of an unhandled
  `ValueError` (audit finding F17); `run()` catches it, fires
  `_on_output`, and shuts down cleanly, rather than crashing the whole
  adapter process on one malformed frame.

Not yet verified (flagged in the design doc, not blocking v1): group
items, `OCCURS` tables, `REDEFINES` in `variable_map.py`; deeper
`PERFORM`/`PERFORM THRU`/`GO TO` control flow in `call_stack.py`.

## `mockymock mutate <program> --cut PATH [--copybook-path DIR ...] [--list] [--timeout S] [--jobs N] [--no-coverage-gate] [--json-report PATH] [--fail-under PCT]`

Mutation testing (see docs/2026-07-29-mutation-testing-design.md).
`--list` prints the generated mutants and exits — pure
`mutation.operators`, no Docker. `mutation.operators`' verb/scope/
condition/deletable-verb regexes match on COBOL-word boundaries via a
shared `_cobol_word()` helper (negative lookaround treating `-` as part
of the identifier, not a boundary) instead of plain `\b` (audit finding
F8, 2026-08-10) — `\bREAD\b` used to match inside `WS-READ-COUNT` and
generate mutants that were never real READ statements at all. **The same
helper now covers the arithmetic patterns too** (`_ADD_TO`,
`_SUBTRACT_FROM`, `_MULTIPLY_BY`, `_DIVIDE_INTO`, `_MOVE_INT`), which F8
missed: `\bADD\b` matched inside `GRP-FOR-ADD-CORR-R` and rewrote an
ordinary `MOVE` into `MOVE GRP-FOR-SUBTRACT-CORR-R FROM ...`.

Three further stillborn classes closed on 2026-09-04, all in
`mutation.operators` (see
docs/2026-07-29-mutation-testing-design.md's "Column discipline"):
**every rewrite goes through `_rewrite_code`**, which edits strictly
inside columns 1-72 and re-pins the identification area at column 73
rather than letting the edit carry it along — `normalize_fixed_format`
slices columns 8-72, so a growing swap (`ADD..TO` → `SUBTRACT..FROM`,
+7) used to lose its own tail and a shrinking one (−7, or `>=` → `>`)
used to drag `NC1014.2` back into the program text. It buys the columns
a longer verb needs from interior space runs (never the indent — that
decides Area A vs Area B — and never inside a literal) and drops the
mutant when it cannot. **`stmt-delete` now requires the statement to end
on its own line** (trailing period, or a next code line opening
something new; a line trailing off in `TO`/`FROM`/`=` is always
refused): replacing the head of a multi-line statement with `CONTINUE`
strands its own tail, or an `END-ADD` that binds to the deleted verb.
**Continuation lines (indicator `-`) are skipped** and **`PROCEDURE
DIVISION` state resets at `END PROGRAM`** so a second program's DATA
DIVISION is not mutated. Measured over a 542-file corpus: 12.2% of
generated mutants were defective before this (8.9% verified to compile
something other than what their report line described, by running each
through the pipeline's own `normalize_fixed_format`), none after. Still open: `stmt-delete` on a line holding two
statements deletes both (over-strong, not stillborn), and `stillborn`
still lumps refusal-gate rejections in with compile errors.

A real run baseline-checks the suite
(red/empty baseline aborts with exit 1: every verdict would be noise),
then for each mutant patches one original line and re-runs the exact
`run` pipeline (static checks → splice → compile → run) in its own
sandbox, classifying `killed` / `survived` / `timeout` (counts as a
kill; default 15 s) / `stillborn` (refusal or compile error — excluded
from the score) via `mutation.runner._classify_execution` (audit finding
F28, 2026-08-10) — this now checks `suite_result.duplicate_case_starts`,
orphan `CASE FAIL`s, and a zero-cases-run stdout before falling back to a
bare "binary exited N" message, instead of citing the exit code even when
it was 0 and the real cause was one of those three. Console output
streams one line per mutant, then lists
survivors with a `-`/`+` diff, then breaks the stillborn mutants down by
WHY they were stillborn -- `checks` (a mockymock static gate rejected the
mutated program before any compiler ran, often an equivalent mutant) vs
`compile` (GnuCOBOL rejected it, so that line was never probed at all) --
and finally the score (killed+timeouts over scored). That breakdown exists
because stillborns are excluded from the score entirely: without it, a line
whose every mutant failed to compile is indistinguishable from a line with
no mutants, and a real gap the engine could not probe hides behind a
clean-looking number. The two names are `SuiteRun.phase`'s own values,
carried straight onto `MutantResult.stillborn_reason` rather than
re-derived afterwards by pattern-matching the raw `detail` line.

**Two cost levers, both added 2026-09-04, neither changing a verdict.**
`--jobs N` (default 1) spreads the per-mutant pipeline over N worker
*processes* -- processes, because the dominant Docker-free cost,
`run_static_checks`, is CPU-bound pure Python (measured 3.90x on 4 cores).
`pool.map` is consumed in submission order, so the report, the progress
stream and the notes union are byte-identical to a serial run. The
default is 1 because the ceiling is the shared container's `--memory 1g`,
not the core count: an OOM-killed `cobc` would be recorded as a
`stillborn`, a wrong verdict. The **coverage gate** (on by default,
`--no-coverage-gate` to disable) compiles the baseline with `--coverage`,
remaps gcov onto the original source via
`report.coverage.map_coverage_to_original`, and classifies any mutant on
a provably unexecuted line as `survived` without building it -- exact,
since a line no case reaches cannot change what any case observes. A line
*absent* from the remap is unknown and always built. A baseline that
fails at the *compile* step or times out is re-run plain before it is
believed (`SuiteRun.phase` distinguishes "checks"/"compile"/"run"); a red
suite or a refusal-gate stop is not, since gcov changes neither. A failed
gcov pass adds a note and the run builds everything. Gated survivors
score identically, carry `ran: false` (and `totals.not_compiled`) in the
JSON, and print as `uncovered`. `--json-report` writes the full
machine-readable outcome (with `stillbornByReason` totals and a per-mutant
`stillbornReason`); `--fail-under` exits 1 below the given
percentage. Every baseline/mutant run's `StaticCheckResult.notes` (a
paragraph-scoped `PARSE_WARNING`/`UNRESOLVED_COPYBOOK` waived rather than
refused — [analysis](analysis.md)) is collected (union, first-seen order,
deduped) and printed as `mockymock mutate: <note>` lines before the
outcome — this path compiles doctored source (a waived COPY's line
commented out) exactly like `run` does, so it keeps the same
never-silent guarantee. Boundary statements (mocked) and terminators (rewritten by
terminator plans) are never mutated — mutating them would test the
harness, not the program.

## `mockymock lint <program> --cut PATH [--copybook-path DIR ...]`

Runs `run_static_checks` and nothing else: every refusal `run` would print,
with zero Docker dependency. `_cmd_lint` never imports
`mockymock.runtime.docker_toolchain` (structural guarantee, tested by
`tests/unit/test_checks.py`). Output: one `mockymock lint: <problem>` line
per problem plus a `N problem(s) found.` summary, exit 1; or
`mockymock lint: no problems found.`, exit 0. Built for editors (the VS Code
extension publishes these as diagnostics), pre-commit hooks, and CI lanes
without a daemon.

## `mockymock collect [program] --cut PATH [--json] [--boundaries] [--copybook-path DIR ...]`

Parses the `.cut` file only (no `.cbl`, no Docker) and lists the suite and
test cases with 1-based line numbers and tags. `--json` emits the
machine-readable form (`{"version": 1, "cutFile", "suite": {name, line},
"cases": [{name, line, tags}]}`) the VS Code extension uses for
authoritative test discovery; a `CutParseError` yields `{"version": 1,
"error": "..."}` and exit 1.

**`--boundaries` (2026-09-15)** additionally reports `boundaries: [{category,
key, keys, directive, label, paragraph, line, matchText}]` -- every site in
`analysis.mock_surface.analyze(ast).boundary_sites` with `category is not
None`, whole-program and **not** reachability-filtered by any one
TESTCASE's PERFORM target (that's what `lint`'s refusal gate is for; this
feeds editor completion for "every key this program could ever need
mocked"). `key` is `keys[0]` (a multi-key site such as `OPEN INV-FILE
RPT-FILE` lists every key in `keys`; consumers must read `keys`), and is
`null` for SQL/CICS/DLI, whose DSL key is a quoted text prefix: `directive`
is the exact `MOCK <category> <key>` header `dsl.generator.directive_snippet`
would scaffold for the site (quoted where the DSL requires it, the
shortest-unique prefix for SQL/CICS/DLI, `null` when the scaffold skips the
site), so a consumer inserts what the parser accepts instead of re-deriving
the quoting rules. `_collect_boundaries()` (`cli/main.py`) parses `program`
directly (with `--copybook-path` expansion if given) -- it does not go
through `run_static_checks`, since it needs no `.cut`-specific analysis at
all. Requires both `--json` and `program` (checked before any parsing);
requesting it without either is a plain usage error, not a refusal. See
docs/2026-09-15-cut-editor-intelligence-design.md.

## `mockymock explain [CODE] [--list] [--json]` (2026-09-15)

One shared source of truth for what a refusal code means:
`analysis.refusal.REFUSAL_EXPLANATIONS` (`_explanations.py`) is a
hand-written `dict[code, prose]` covering every refusal code string
actually constructed anywhere in `mockymock/` --
`tests/unit/test_refusal_explanations.py` cross-checks the dict against a
regex scan of the whole package in both directions (missing entry fails
CI; a stale entry for a code nothing emits anymore also fails, so the
table never drifts from what the codebase can actually produce). Bare
`explain` or `explain --list` prints every catalogued code; `explain
<CODE>` (case-insensitive) prints its explanation, or -- if uncatalogued
-- a `not catalogued` message naming every code that is (never a silent
empty result, same "partial and reported" posture cobol-parser's
`le_signatures.py` uses). Backs `mocky-mock-vscode`'s planned
refusal-code hover via `explain --json`. See
docs/2026-09-15-cut-editor-intelligence-design.md.

## `mockymock dashboard [--port N] [--no-browser]`

Serves the static status page on `127.0.0.1` (host not configurable) until
Ctrl-C, opening a browser unless `--no-browser`. Unlike `setup`, it is
**read-only** — it calls `runtime.status.probe()`, never
`ensure_toolchain()`, so a polling page can't trigger image builds. A taken
port yields `mockymock dashboard: could not serve on ...` and exit 1. Full
details in [dashboard](dashboard.md).

`--port`'s default is stored as `None` and resolved to
`web.server.DEFAULT_PORT` inside `_cmd_dashboard`, deliberately: reading
the constant at parser-build time would import `web.server` ->
`runtime.status` -> `runtime.docker_toolchain` (which reads the Dockerfile
at import to compute `IMAGE`) on every `mockymock --help`. See the Gotchas
below.

## `mockymock doctor [--json]` (2026-09-15)

The terminal-native counterpart to `dashboard`: one readiness report, no
browser, no HTTP server, no toolchain mutation. `_cmd_doctor` is a thin
shell over `cli/doctor.py`'s `gather_full_status()` ->
`format_doctor_text()` / `format_doctor_json()`.

Its checks are `runtime.status.probe()`'s four (`daemon`, `image`,
`container`, `cobc`) plus three of its own: whether `cobolparser` imports,
which project config file this invocation would load (reported `WARN`
when that file is malformed, rather than taking the whole report down with
it), and (2026-09-16) which AI assistant mode that config puts the
packaged skill in. The `ai_mode` check is always `OK` — every mode is a
valid way to work, so it reports rather than judges and `ready` can never
turn on it; it loads the config a second time rather than sharing
`_check_config_file`'s, whose signature its own tests call directly.

Exit code is `0 if report.ready else 1`, where doctor's `ready` means **no
check is `DOWN`** — a `WARN` such as a stopped container or a broken config
file still exits 0, because `setup` or the next `run` resolves it. That is
deliberately looser than `probe()`'s own `ready`, which requires every
check to be `ok`. Full write-up, including the check-state table it shares
with the dashboard, lives in [dashboard](dashboard.md); the design doc is
docs/2026-09-15-doctor-command-design.md.

## `mockymock analyze [cobolparser-args...]`

The only subcommand that's a pure pass-through: it forwards straight to
cobol-parser's own CLI (`dead-code`, `program-flow`, `io-sequence`,
`move-type-check`, `linkage-check`, `language-env`, `ims-dli`, `analyze`,
`gen-data`, `data-items`), not `mockymock.analysis`. `cobolparser_args` is declared with
`nargs=argparse.REMAINDER`, so every token after `mockymock analyze` —
including anything that looks like a mockymock flag — belongs to
cobol-parser, never to this parser. `_cmd_analyze` monkeypatches
`sys.argv` to `["cobol-parser", *args.cobolparser_args]` (restored in a
`finally`) because `cobolparser.cli.parse.main()` takes no `argv`
parameter and reads `sys.argv[1:]` directly — the standard idiom for
delegating to an argparse CLI that doesn't accept one, safe here because
the CLI is single-threaded and sequential. Its `SystemExit.code` is
returned as-is when it's already an `int`, else 1. No Docker.

This is the route the VS Code extension's **"Generate Data from Copybook"**
action takes (`mockymock analyze gen-data <file> --rows 10`, built in that
repo's `src/generateData/generateDataRunner.ts`). Because the passthrough is
unguarded, every `gen-data` flag is available without a mockymock change —
including cobol-parser's record-image formats added 2026-09-05:

```bash
mockymock analyze gen-data CUSTOMER.cpy --format hex          # annotated bytes
mockymock analyze gen-data CUSTOMER.cpy --format record \
    --charset ebcdic -o CUSTOMER.BIN                           # a z/OS-bound image
```

`--format hex` is the one worth knowing about here: it renders a copybook's
`COMP-3`/`COMP-5`/`COMP-1` fields as the bytes a program would really read,
annotated with each field's offset and length, as *text* — so unlike
`--format record` it survives being opened in an editor, which is what the
extension does with the CLI's stdout. See cobol-parser's `.okf/cli.md` and
`.okf/generators.md`.

## `mockymock export <program> --cut PATH [-o/--output PATH] [--copybook-path DIR ...] [--case NAME ...] [--tag TAG ...]`

Writes the instrumented source to a file after running the same parse → static-checks → splice
pipeline as `run`, but without Docker or any GnuCOBOL step. The output is adjusted for compilation
under a real fixed-format (z/OS) COBOL compiler instead of GnuCOBOL-only: `PROCESS`/`CBL` directives
are preserved (where `run`/`lint` strip them), columns are restored to z/OS fixed-format discipline
(7-space prefix for Area A), and over-column-72 lines are fitted by `mainframe_export.fit_within_columns`.
A provenance/disclaimer header is prepended, documenting that this is a
mock-only build (every boundary is either mocked or fails loudly; no real I/O executes) and listing
known GnuCOBOL-vs-IBM-COBOL gaps that a clean compile here does not rule out. Output path defaults
to `<program-stem>.mainframe.cbl` next to the input `.cbl`, matching `generate`'s suffix-swap convention.

`fit_within_columns` is three passes, in this order:

1. `wrap_long_display_lines` — a generated `DISPLAY` becomes `DISPLAY "<chunk>" WITH NO ADVANCING`
   fragments. First because its byte-identical-stdout equivalence is empirically established and the
   `__MOCKYMOCK__` protocol rides on that text.
2. `wrap_long_literal_lines` — anything still long that carries exactly one quoted literal is split
   across fixed-format continuation lines (`-` in the indicator area, the literal re-opened at column
   12), leaving the statement and the literal's content byte-for-byte unchanged. Two shapes reach this
   routinely and neither is under the `.cut` file's control: `splicer/reset.py` re-serializes every
   WORKING-STORAGE `VALUE` clause into `UT-RESET-WORKING-STORAGE` as a single-line `MOVE` (a program
   declaring a wide storage-dump marker — `DEBUT-WORKING-STORAGE` / `FIN-WORKING-STORAGE`, standard in
   IBM shops — overflows on its own declaration), and cobolparser's `normalize_fixed_format` collapses
   a literal the *original* source already continued onto one long free-form line. Both were flat
   refusals with no in-tool remedy before 2026-09-04.
   **Every continued line is filled to exactly column 72**, and that is not cosmetic: under
   fixed-format rules a continued line's trailing blanks through column 72 are part of the open
   literal, so a short one silently pads the value with spaces (both facts verified against a real
   fixed-format GnuCOBOL compile — see `tests/integration/test_export_literal_continuation.py`).
   The fill padding goes before the opening delimiter, where extra spaces are only separators.

3. `_break_at_whitespace` — the one shape neither of the above covers: a line with *no* literal at
   all (`MOVE WS-A-LONG-SOURCE-NAME TO WS-A-LONG-TARGET-NAME`), which pass 2 can only report as
   "holds no single quoted literal to split". A COBOL statement may span as many fixed-format lines
   as it needs — only a *literal* broken across the boundary needs the column-7 `-` — so this needs
   no continuation machinery at all, just a break at a space with the remainder starting in Area B
   (column 12) so it cannot be read as a new paragraph header or an 01/77 level.

Each earlier pass's problems are discarded: every pass reports the lines it declined, and a later pass
re-examines exactly those. Only a line NO pass can fit is reported — a single word too long for Area B
(61 characters), a second literal on the line (ambiguous), or a `CBL`/`PROCESS` directive (read before
continuation rules apply). Then `export` refuses
(`mockymock export: refused (COLUMN_OVERFLOW): ...`) and writes nothing. A full-line `*>` comment is
exempt in every pass: columns 73+ are the identification field and are never compiled.

**The refusal names where the line came from** (`SourceAttribution`, 2026-09-04). It used to append a
hint asserting the line "typically comes from a `.cut` file's MOCK body text" — true for one of the
three real sources, and actively misleading for the other two, since the same overflow arises from
mockymock's OWN generated driver/reset code, which exists in neither input file and which no `.cut`
edit can shorten. `SourceAttribution` is built from `_insert_driver_with_origins`' inserted-line
indices plus exact stripped-text lookups in the `.cut` and `.cbl`, so an attribution is a fact ("this
text is on line 12 of PROG.cut"), never an inference — and text in neither file is reported as
mockymock-generated instrumentation rather than blamed on either.

Full design, including empirical validation of the wrapping algorithm and the three adjustments, lives in
[docs/2026-08-03-mainframe-export-command-design.md](../docs/2026-08-03-mainframe-export-command-design.md).

## `mockymock skills install [--project] [--force]`

Copies the packaged Claude Code skill
(`mockymock/cli/skills/mockymock/`) to
`~/.claude/skills/mockymock` (default) or `./.claude/skills/mockymock`
(`--project`). Implementation lives in `mockymock/cli/skills_cmd.py`,
imported lazily inside `_cmd_skills_install` for the same deferred-import
reason every other subcommand uses, even though nothing here is actually
heavy (`shutil`/`pathlib` only) -- consistency with the rest of this
module.

`resolve_target(project: bool) -> Path` picks the base directory
(`Path.cwd()` or `Path.home()`); `install_skill(target, force=False)`
refuses (`SkillTargetExistsError`, fail-closed) if `target` already
exists and `force` is `False`, so a user's local edits to a previously
installed copy are never silently clobbered. The skill content itself is
declared in `pyproject.toml`'s `[tool.setuptools.package-data]` under
`"mockymock.cli"` -- it has no `__init__.py` of its own, so it rides
along with the already-discovered `mockymock.cli` package the same way
`mockymock/runtime/docker/` and `mockymock/web/static/` ride along with
theirs.

The packaged skill is not just a copytree of static reference material:
its `SKILL.md` prescribes how an assistant works. Since 2026-08-16 it
teaches the agent to inventory boundaries and recommend a `--scenarios`
mode from a program's own `scenario_coverage` before generating
(`reference/scenario-generation.md`). Since 2026-09-16 it also prescribes
the *order* a suite is built in -- every paragraph green on its own
`PERFORM` first, driven one at a time with `run --case`, and only then
whole-program cases through the program's entry paragraph -- plus a
narration contract for keeping the developer oriented while that
happens (`reference/paragraph-first-workflow.md`). Since 2026-09-16 it
additionally carries the *mode* it operates under (`reference/modes.md`,
and the section `SKILL.md` opens the narration contract with) — the same
workflow, with `hands-on`/`guided`/`hands-off` deciding how much of it
comes back to the developer, and a floor that holds in every mode. All
three halves are
pinned by `tests/unit/test_mockymock_skill_content.py`, which also
requires every `reference/` file to be linked from `SKILL.md`: an added
reference file that nothing points at is a test failure, not a silent
orphan.

## `mockymock skills mode [--set MODE] [--json]` (2026-09-16)

Shows (or persists) the **AI assistant mode** — how much the packaged
skill checks in with the developer while it builds a suite. Three modes
on one axis, most-supervised first: `hands-on` (propose, wait for a yes
before each change), `guided` (the default — narrate every step, stop at
the checkpoints), `hands-off` (run the loop end to end, report once).
`mockymock/cli/ai_mode.py` owns the vocabulary (`MODES`, `DEFAULT_MODE`,
a `ModeContract` per mode, `ALWAYS_ASK`), the `ResolvedMode`
value+provenance pair, both formatters, and the config-file write. Full
rationale in
[docs/2026-09-16-ai-assistant-modes-design.md](../docs/2026-09-16-ai-assistant-modes-design.md).

The mode lives in the project config file as `ai_mode` (validated in
`cli/config.py`, which imports `MODES`/`CONFIG_KEY` from `ai_mode` — the
dependency may not point the other way, and `ai_mode` is stdlib-only for
that reason). `MockymockConfig.ai_mode is None` means *no key anywhere*,
deliberately distinct from a file spelling out the default: `skills mode`
and `doctor`'s `AI assistant mode` check both report provenance, and a
mode inherited from a monorepo root two levels up is otherwise a
surprise.

`--set` has three outcomes: an existing `mockymock.toml` is edited
line-based (comments and key order survive; `tomllib` is read-only and
this repo takes no TOML-writing dependency for one key, which is sound
here only because the file's schema is a flat table); no config file at
all creates one in cwd; a `pyproject.toml`-sourced config is a
**refusal** printing the line to add, because a `mockymock.toml` written
beside it wins the per-directory search and would shadow that project's
`copybook_path`/`seed`/`test_root` wholesale.

The floor (`ALWAYS_ASK`) is the load-bearing half: a mode changes how
often the assistant checks in, never what it may destroy or quietly
decide. Editing the `.cbl`, overwriting a `.cut` it didn't write, turning
a suspected program bug into a passing assertion, and acting outside the
mockymock loop stay asked-about in `hands-off` too. Pinned by
`tests/unit/test_mockymock_skill_content.py` on the packaged skill's side
and `tests/unit/test_ai_mode.py` on the CLI's.

# Gotchas

**Nothing in `build_parser()` may import a `_cmd_*` body's dependencies.**
The deferred-import rule above is about `main()`'s hot path, but
`build_parser` runs on *every* invocation including `--help`/`--version`,
so an import there is strictly worse than one at module top would be for a
single command. `mockymock dashboard` regressed this once by importing
`web.server` for a port default;
`tests/unit/test_cli_dashboard.py::test_building_the_parser_does_not_import_the_docker_toolchain`
now pins it in a subprocess.

**`mockymock skills mode --set` deliberately doesn't use `choices=MODES`.**
`argparse`'s `choices` would need `mockymock.cli.ai_mode` imported inside
`build_parser()`, which the rule above forbids. The valid set is spelled
out in the flag's help text and validated inside `_cmd_skills_mode`
instead; `tests/unit/test_cli_skills.py` pins the help text against
`MODES` and pins (in a subprocess, like the dashboard test above) that
building the parser doesn't import the module. Any future "cleanup" that
restores `choices=` also restores the import.

**`transform_data_division_exec` is called twice, and the first call's return value is intentionally thrown away** (`_cmd_run`, step 9 vs 11). The first pass exists purely to surface `EXEC SQL INCLUDE SQLCA` refusal reasons *before* any splicing happens; running the real transform that early would shift line numbers/spans that `splice_program` and the boundary/nested-site analysis depend on. Any future edit that tries to "simplify" this into one call will silently break splice-target alignment.

**Refusal checks are cumulative, not fail-fast, within a single gate.** `check_test_case` loops over every test case and only returns/exits after checking all of them, so users get every refusal reason in one invocation. But *between* gates (`check_whole_program` -> parse success -> `check_unresolved_copybooks` -> `check_nested_exec` -> `transform_data_division_exec` precheck -> `check_test_case`), the command exits at the first gate that fires — later gates never run if an earlier one refuses.

**`annotate_nested_sites` ordering is load-bearing in both `generate` and `run`.** It must run before anything inspects `surface.boundary_sites` for nested spliceability (`_report_unsupported_boundaries` in `generate`; every refusal check and `splice_program` in `run`). An unannotated nested site is indistinguishable from an unspliceable one, so calling this late produces false-positive refusals.

**`_insert_driver` matches section/division headers by exact-prefix string match on the stripped, uppercased line** (`WORKING-STORAGE SECTION`, `PROCEDURE DIVISION`) and inserts only at the first match. A program with unusual formatting where these headers aren't isolated on their own line (unlikely post `normalize_fixed_format`, but not structurally prevented) would silently fail to get the driver inserted.

# See Also

- [runtime](runtime.md)
- [report](report.md)
- [dsl](dsl.md)
- [coverage](coverage.md)
- [dashboard](dashboard.md)
