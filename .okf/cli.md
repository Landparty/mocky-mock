---
type: Module
title: CLI
description: argparse entry point (setup, init, generate, fixtures, run, debug, lint, mutate, collect, suites, explain, dashboard, doctor, export, analyze, skills, report, journal, clean) that orchestrates the splicer, GnuCOBOL runtime, and report formatters.
tags: [cli, entrypoint]
timestamp: 2026-10-16T20:00:00Z
---

# Overview

`mockymock/cli/main.py` is the single argparse-based entry point (`prog="mockymock"`,
`--version` from `mockymock.__version__`). It defines eighteen subcommands —
`setup`, `init`, `generate`, `fixtures`, `run`, `debug`, `lint`, `mutate`, `collect`, `suites`, `explain`, `dashboard`, `doctor`, `export`, `analyze`, `skills`, `report`, `journal`, `clean` — each wired via `set_defaults(func=...)` and
dispatched from `main()`. All heavy imports (`cobolparser`, `mockymock.analysis`,
`mockymock.splicer`, `mockymock.runtime`, `mockymock.dsl`, `mockymock.report`,
`mockymock.debug`, `mockymock.web`) are
deferred into each `_cmd_*` function body rather than imported at module top —
so `mockymock --version` / `--help` stay fast and don't require Docker or a
parser install to resolve.

```
mockymock setup     -> runtime.docker_toolchain only (build image, start container)
mockymock init      -> _cmd_generate(--with-data) then _cmd_run(--record-expectations), reentrant  (records iff the Docker daemon is up; run builds a missing toolchain image -- vscode#103)
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
mockymock report    -> report.test_report.build_report (parse + cobolparser analyzers + cli.checks; --execute/--mutate re-invoke run/mutate as subprocesses) -> report.html_report
mockymock journal   -> report.journal.append_entry only  (no Docker, no parsing)
mockymock clean     -> report.artifacts (removes .mockymock/ reports and saved results)
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
in cobol-parser 1.10 (on its `main`; no tagged release through v1.9.0
carries it as of 2026-10-04), the dependency floor here is deliberately not raised
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
byte-for-byte unaffected. A `.cut` whose program cannot be resolved is
skipped and listed; the command exits 1 when nothing ran, or (issue #303,
option (b)) when a skipped `.cut` declares a `PROGRAM "..."` line, since
that explicit claim is now broken (`_report_broken_claims`). A `.cut`
whose program was only guessed is still just skipped. `run` also writes a
failing per-pair `--junit-xml` / `--json-report` entry for every skipped
suite (`_write_skipped_suite_reports`, via `_write_failure_reports`).

`_apply_config_to_args()` fills `args.copybook_path`/`args.seed` from the
loaded config when the CLI flag was left at its argparse default; an
explicit flag always wins. `--timeout` (run/mutate) is deliberately not
config-overridable — see the docstring on `_apply_config_to_args` for why.

See `docs/2026-09-15-cli-ergonomics-design.md`.

**Several suites per program, and `tests/` (2026-10-14):** the sibling
rule above is now step 2 of `discovery.resolve_program()`'s lookup:
(1) the suite's `PROGRAM "<path>"` line, relative to the .cut -- an
explicit claim that never falls through to a guess when the file is
missing; (2) sibling `<base>.cbl`/`.cob`; (3) a suite under the tests
folder mirrors to the same relative folder under the source root; (4) the
only `<base>.cbl` under the source root (two is a `DiscoveryError` asking
for a PROGRAM line). `<base>` is the .cut name up to its first dot, so
`PROG.errors.cut` is a second suite of PROG. Rules (2)-(4) all try the
.cut's whole stem before `<base>` (issue #289: `generate` names a suite
after the program's full stem, and `tests/pay/PAY.V2.cut` only paired
with a `PAY.cbl` under the mirror and unique rules). `ProjectLayout`
(`project_layout(config)`) supplies root (the deciding config file's
folder, else cwd), `tests_dir` (`test_root` if a file set it, else
`<root>/tests`) and `source_root` (new config key, default `<root>/src` when it exists, else root).
`find_suites(program)` is the reverse direction (scans the root, plus the
tests folder when `test_root` points outside the root -- `project_cut_files`,
shared with `mockymock suites`, issue #294: `generate` writes new suites
there -- plus the program's own folder when it lies outside the root); `resolve_cut_path` errors
naming the suites when there are several, except that `run`/`lint
PROG.cbl` hand several suites to `_run_directory`/`_lint_directory`
(`_several_suites`); their per-suite report files are named relative to
`_report_tag_root()` -- the test root when every suite lies under it,
else the deepest folder holding them all -- so a sibling `src/pay/PROG.cut`
and a mirrored `tests/pay/PROG.cut` get `report-src-pay-PROG.json` and
`report-tests-pay-PROG.json` instead of one shared `report-PROG.json`
the second suite overwrote. `generate`/`init` write to
`discovery.default_suite_path()` -- `<tests>/<folder>/PROG[.<name>].cut`,
or beside the program when it already has a `PROG.cut` there or lies
outside the source root -- and `--name` picks the topic. `--name`
(generate, init, suites) is validated by the argparse `type=`
`_suite_name` (#336): one word of `[A-Za-z0-9_-]+`, so a `/`, `\`, `..`,
`.` or empty NAME exits 2 before any path is built.
`mockymock suites [PROGRAM] [--name] [--json]` (`_cmd_suites`) prints the
pairing with the rule that matched, or for one program its suites and
`newSuitePath`; Docker-free and parse-free, it is what the VS Code
extension pairs files with. `_programs_by_stem` is `lru_cache`d per
process. Design: docs/2026-10-14-multi-suite-layout-design.md.

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
   whether to attempt a run at all, from its Docker *daemon* check alone
   (vscode#103, 2026-10-21): a missing toolchain image/container is what
   `run`'s `ensure_toolchain()` builds, so init says it is building it and
   goes on. Daemon down: prints a fallback message
   naming the exact `run --cut ... --record-expectations` command to run
   later, and returns 0 (the scaffold with real data is still a
   strictly better outcome than plain `generate`, even unrecorded).
   Ready: builds a `run --cut <output> --record-expectations
   [--copybook-path <...>]*` argv the same way and calls `_cmd_run` on
   it, returning its own exit code.

See `docs/2026-09-15-init-command-design.md`.

## `mockymock generate <program> [-o/--output PATH] [--copybook-path DIR ...] [--with-data | --per-paragraph] [--fixtures PATH] [--seed N] [--scenarios happy|branches|all] [--rows N] [--placeholder CATEGORY:KEY ...] [--fill CUT_FILE] [--force]`

Scaffolds a starter `.cut` test file from a COBOL program. Does **not** touch
Docker/GnuCOBOL — pure parse-and-analyze.

**Refuses an existing output file without `--force` (2026-10-16, issue
#201)**, checked right after the `--fill` dispatch and before any parsing,
explicit `-o` included -- the same contract as `init`, which passes
`--force` through to the `generate` it runs. Before, the default path (the
program's existing sibling `PROG.cut`) was silently replaced by a bare
scaffold.

**A subprogram's USING parameters are its interface (2026-10-21, issue
#275).** `dsl/entry_parameters.py`: `fixture_generator()` builds
`ProgramFixtureGenerator(entry_parameters=True)` when the installed
cobol-parser knows the keyword (it then also targets branches on the
parameters); otherwise `add_entry_parameters()` gives every scenario of the
bundle dict the same `entry_parameters` fixture (category `ENTRY`, one
PICTURE-valid row over the USING items' elementary fields) plus a `stub`
expectation per LINKAGE field xref says the program writes, without the
branch targeting. DFHEIBLK/DFHCOMMAREA are dropped (`without_cics_parameters`;
CICS supplies them, #245 handles the commarea). The scaffold MOVEs the row
before the PERFORM (`generator._entry_parameter_lines`), so `run
--record-expectations` fills the stubs. After writing, `generate` warns on
every case with no EXPECT/VERIFY/STUB EXPECT
(`checks.cases_asserting_nothing`), refuses to write a `--per-paragraph`
suite with zero cases (exit 1), and `init` exits 1 when recording left no
case asserting anything. `run_static_checks` refuses a `.cut` with no
TESTCASE, so `lint` fails it and `run` says why instead of "0 run, 0
failed".

**Default unit is the scenario (2026-10-14).** With neither `--with-data`
nor `--per-paragraph`, `generate` takes the `--with-data` path (one TESTCASE
per scenario through the entry point; 17 cases for the 17
`examples/real-world/` programs, against 112 per-paragraph ones). Implicit
mode degrades instead of failing: a generator exception (other than a
missing copybook), a zero-scenario bundle, or a scaffold with no TESTCASE
prints a `falling back to one test case per paragraph (--per-paragraph)`
line and writes the bundle-less scaffold. An explicit `--with-data` keeps
the hard failures. `--per-paragraph` selects the bundle-less scaffold
directly and is refused (exit 1, stderr) with `--with-data`/`--fixtures`.
In the steps below, "`--with-data`" means "scenario mode, explicit or
implicit" and "neither flag" means `--per-paragraph`.

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
reason with no mechanical fix, a `BEFORE-EACH`/`BEFORE-ALL` hook PERFORM's
`UNMOCKED_*` refusal -- `--fill` inserts into TESTCASEs only, and only the
per-case reason lines it read from `unmocked_reasons` count as handled,
issue #208) is printed and exits 1, so `--fill` exiting 0
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
12. When a bundle drove the scaffold (`--with-data`, `--scenarios`, and
    plain `generate`, which builds a happy-path bundle by default),
    `_refuse_unusable_scaffold` runs `run_static_checks` on the file just
    written. Any refusal that is not `UNMOCKED_*` (e.g.
    `UNSUPPORTED_TERMINATOR_LAYOUT`, `UNSUPPORTED_NESTED_MOCK_TARGET`) is
    printed as `mockymock generate: .cut line N: TESTCASE "..." refused
    (<code>): <message>` (or the program-level `refused (<code>)` line),
    followed by a stderr note that the file was written but `lint` refuses
    it, and generate exits 1 (#231 — it used to exit 0 on a case its own
    lint rejects). The `.cut` is still written. `UNMOCKED_*` refusals are
    left alone, since a MOCK block fixes those -- except one with no
    `suggested_fix`: `check_test_case` gives none (and says why in the
    message) when the site cannot be spliced where it stands (nested, no
    span), because the MOCK would be refused in turn (#258). `--per-paragraph`
    (`bundle=None`) is exempt: one case per paragraph is a starting point
    to prune, and some of those cases are expected to be refused.

`_report_unsupported_boundaries` is the only non-trivial logic in this module:
it walks `surface.boundary_sites` and names every site that stays unmockable —
either `site.category is None` (uncategorized boundary, e.g. a SORT/MERGE
mixing a USING/GIVING file with an INPUT/OUTPUT PROCEDURE on the other
side, or an identifier-less dynamic CALL — a plain-file-form SORT/MERGE, a
pure-procedure-form SORT [never even recorded as a site], and RELEASE/
RETURN all have a category and never appear here, see `analysis.md`) or
`site.nested and site.span is
None` (a nested site the splicer couldn't isolate, printed with
`site.unspliceable_reason`). This list covers the program, not one case, so it is informational —
the scaffold is emitted regardless (step 12 is what judges the cases
generate wrote itself) — but it documents exactly which
test cases `run` will later refuse if a case's PERFORM reaches one of these
sites. Comment in the source explicitly frames this as "so the scaffold is
never mistaken for complete coverage of the program's outputs."

**Empty scaffold (2026-10-05, #150).** `generate --with-data` exits 1
when the bundle had scenarios but none became a TESTCASE. A plain
`generate` on a program with nothing to mock still writes an empty suite
and exits 0.

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
Copybooks are expanded with `preserve_source_locations=True`
(`StaticCheckResult.source_location_map`), and every `refused (...)`
problem and note has its `line N` rewritten by
`checks.source_line_relabeler` to the line of the `.cbl` the user has
open, or `line M of CPY.CPY` for a statement a copybook brought in
(issue #241: a WORKING-STORAGE COPY shifted every refusal's line).
`.cut line N` is left alone. `generate`/`export`'s STOP RUN/GOBACK and
unmockable-site warnings (`_report_unsupported_boundaries`) are relabeled
the same way.

Flags beyond the pipeline inputs:

- Every output-file flag (`--junit-xml`, `--json-report`,
  `--coverage-json`, `--coverage-out`, `--trace-json`, and `export`/
  `generate`/`mutate`'s output) is written by `_write_report_file`, which
  creates missing parent directories first (issue #257: `--junit-xml
  reports/junit.xml` in a fresh checkout wrote nothing) and prints a write
  that still fails on stderr. The exit code still follows the test
  outcome, not the report write.
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
  could shorten or lengthen the bound a hung mocked CALL is killed by. The
  help text now points at the fix for that hang: `MOCK CALL "X" ROWS (
  ... ) TERMINAL ( ... )`, so the calls after the last row end the loop.
  Values below 1 are refused on run / mutate / report (`_timeout_seconds`,
  issue #306): coreutils `timeout 0` turns the container-side kill off, so
  a hung binary outlived its `docker exec` as an orphan. `run_binary`
  also clamps to at least 1 second for any other caller.
- `--case NAME` (repeatable) / `--tag TAG` (repeatable) — run only the named
  or tagged TESTCASEs (union when both given). Selection happens in
  `run_static_checks` before any per-case refusal check, so a refused
  sibling case no longer blocks running a clean one. An unknown name is a
  static problem listing what is available; tags are a union, so a suite
  is refused for `--tag` only when it carries none of the requested tags
  (`--tag a --tag b` on a suite with only `a` runs its `a` cases). The
  suite still runs as ONE compile + binary — just with only the selected
  cases spliced in. In directory mode (no program/--cut, or a program with
  several suites) `_directory_selections` parses every suite first, like
  `pytest -m`: a suite with no selected case is skipped (`skipped: no
  selected TESTCASE`, no report file written, exit code untouched), each
  run suite is passed only the selectors it matches, and only a selector
  that matches nothing in ANY suite is an error (exit 1). A suite that
  does not parse is left in, so its run reports the parse error. Before
  (issue #254) every suite got the selectors unchanged, a suite without
  the tag was refused, the run exited 1 and its JUnit file got a
  synthetic failure.
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
  Value rendering is PICTURE-aware for plain numeric items (2026-09-27,
  `report.record_rewrite.field_pictures` / `numeric_scale`): under
  `-std=mvs` GnuCOBOL DISPLAYs a signed item with a separate sign
  (`005+`, `00350-`, `+00007` for COMP/COMP-3) and drops an implied
  decimal point (`00350` for 2.50 in `9(3)V99`). Rendered by text shape
  alone those became `"005+"` or a bare, 100x-too-large `00350` -- goldens
  that failed the very next run, so `init`'s scaffold failed out of the box
  on `invupdt`/`ordrproc`/`raterte`. The PICTURE comes from the program's
  own data items (subscripts stripped) and, for a synthesized `UT-CAP-`
  target, from its capture source; anything without one (alphanumeric,
  numeric-edited, unresolved) keeps the old text-shape rule. A group item
  renders as alphanumeric and a stub on a `P`-scaled item is skipped
  (issue #194). The file is read without newline translation and written
  with `newline=""`, `rewrite_cut_text` joining with the file's own
  newline, so a CRLF `.cut` stays CRLF (issue #199, the same fix
  `generate --fill` already had).
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
   Under `SOURCE-COMPUTER ... WITH DEBUGGING MODE` (a non-comment line),
   `debugging_lines.activate_debugging_lines` then turns every column-7
   `D` line into a code line (indicator -> space, no line moves), as the
   compiler reads them: the AST, the gates and the compiled sandbox all see
   them (issue #274; before it cobc compiled them as comments and a D-line
   boundary went ungated). `generate`/`fixtures`/`collect --boundaries`
   and `report` do the same before their own `parse_cobol`. cobol.yml's
   `project.debug_lines` is not read.
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
    problems>, cut_suite=..., cut_file=..., program_file=...)` before
    returning 1 — see the `--junit-xml`/`--json-report` bullets above. The
    three keyword arguments (issue #204, 2026-10-16; also passed on the
    compile-failure exit) keep the JSON report's `cutFile`, `programFile`
    and `suite.line` populated, and list the suite's cases as `not_run`.
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
    When the first code line after the PROCEDURE DIVISION header is a
    statement rather than a paragraph/SECTION header (an unnamed main
    line), `_starts_unnamed_code` has a `UT-ORIGINAL-ENTRY.` header
    inserted before it, so that code is a paragraph nothing performs
    instead of more sentences of the last `UT-TESTCASE-<n>` paragraph
    (issue #264: it ran after the last case and its STOP RUN hid
    SUMMARY). A header line with no period (a `USING` list running on)
    gets no synthetic header.
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
    <n>"`; exit 0 with a crashed case -> `CLEAN_EXIT_CRASH_DETAIL` (the
    STOP RUN hypothesis plus a GO TO out of the PERFORMed range, issue
    #238); exit 0 otherwise -> `None`.
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
    run. When every case passed but no SUMMARY line was printed
    (`tests_run == 0`), `run` says so before exiting 1, rather than
    failing silently under an all-PASS report (issue #264). **Unaffected by `--record-expectations`** — recording outcomes
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
  type/digits/scale/flags, read live via MI. Round 6 (2026-09-28, checked
  against a real `-std=mvs` compile): an even-digit COMP-3 has its pad
  nibble in FRONT (`S9(4)` 1234 = `01 23 4C`, was shown `0123`); a signed
  DISPLAY item's sign is overpunched (`-123` = `12s`, was shown `12`) or
  separate (`SIGN ... SEPARATE`); COMP-5 is host (little-endian) order,
  told apart from big-endian COMP by `COB_FLAG_BINARY_SWAP` (was `-257`
  for `-2`). Issue #207: a numeric-edited item (type 0x24) shows its
  storage as text (`-  5.50`), like alphanumeric; COMP-1/COMP-2 (0x13/
  0x14, and a `b_NN`-only one through `BufferLayout`) unpack as host-order
  IEEE 754, a single at its shortest round-tripping precision (`0.1`, not
  `0.100000001`); any other type code shows `<unsupported type 0xNN>`
  instead of gdb's whole `cob_field` struct with its pointers. The table keeps the declaration's own spelling, so
  `evaluate` (hover/watch) falls back to a case-insensitive match. `_unquote_c_string` shares
  `gdb_session.py`'s `decode_c_escape` (see F15 above).
- `call_stack.py` — synthesizes the COBOL paragraph/section call stack
  from GnuCOBOL's internal `frame_stack`, since gdb's own backtrace is
  always exactly one frame (`PERFORM` is a computed-goto, not a real C
  call). `frame_stack[0]` is a sentinel, not a real caller — see the
  design doc's Empirical basis for why. `ParagraphIndex.build(ast,
  to_original)` maps each paragraph/section start from the AST's
  (copybook-expanded) lines to the original `.cbl`'s, the coordinates it is
  queried in; `_cmd_debug` passes `build_original_line_map(normalized,
  normalized, original)` (issue #256: a WORKING-STORAGE COPY shifted every
  frame's paragraph name). `synthesize_stack`'s per-frame
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
  Data items the program declares but cobc gave no C local in the
  `.c.l.h` (`DebugSession.unavailable`, from `variable_map.
  declared_data_names` / `unavailable_names`) are listed after the
  readable ones with the value `<unavailable: not materialized by cobc>`,
  and `evaluate` answers the same for them (issue #156). Items cobc
  declared only as a `b_NN` buffer are still read (issue #168 covers how).
  An item gdb cannot read at this stop no longer fails the whole
  `variables`/`evaluate` response (issue #318, `_read_display_value`): it
  shows `UNREADABLE_VALUE` (`<unavailable: storage not bound at this
  point>`), which is also what a field with a NULL `.data` (a
  LOCAL-STORAGE item before cobc binds it) reads as. LOCAL-STORAGE is not
  yet read through `cob_local_ptr`. An EXTERNAL item's `b_NN` is a
  pointer; gdb's `0x... "text"` printing is reduced to the text.
  The numeric decoders place the decimal point through `_place_point`,
  which honours P scaling (issue #295): a negative cobc scale multiplies
  (`9(3)PPP` storing 637 is 637000), and a scale larger than the stored
  digits left-pads (`VPP99` storing 12 is 0.0012).
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
  `setBreakpoints` is matched by source path (2026-10-09):
  `DebugSession.original_file` (set by `_cmd_debug` to the program path)
  is the only file `line_map` covers, so a request for any other source —
  a copybook, a same-named file elsewhere — answers every breakpoint
  `verified: false` with a message and inserts nothing in gdb.
  `_is_same_source` compares resolved absolute paths, or a relative
  client path against the program path's trailing components. Before,
  line N of a copybook became a live breakpoint on line N of the
  program. `stackTrace` frames fall back to `original_file` when no
  breakpoint has been set in the program.

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

`DIVIDE..INTO -> MULTIPLY..BY` is skipped when the statement (this line
or a later line of it, `_statement_tail`) has a `REMAINDER` phrase:
`MULTIPLY ... REMAINDER` is a cobc syntax error, so that mutant was a
stillborn every time (2026-09-28).

The swap also carries the statement's own scope terminator (#234):
`_scope_terminator` finds the `END-<verb>` that closes it (a nested
same-verb statement opens a level its own terminator closes; a period ends
the search). On the mutated line it is rewritten with the verb
(`SUBTRACT ... END-SUBTRACT`); on a later line the site is skipped, since a
single-line mutant cannot touch it and `SUBTRACT ... END-ADD` never compiles.

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
through the pipeline's own `normalize_fixed_format`), none after. **`stmt-delete` reads columns 8-72**
(the verb check, the follower check, and the rewrite, which keeps
columns 1-7 verbatim): with a sequence number in columns 1-6 it used to
generate no deletion mutants at all. A bare `NAME.` follower counts as a
paragraph header only in Area A (columns 8-11): in Area B it is the
statement's last operand (`MOVE 1 TO WS-A` / `WS-B.`), and deleting the
head used to strand it -- a compile stillborn (2026-10-10). A compile
stillborn's detail is cobc's first `error:` message
(`runner._compile_error_detail`), not its `<path>: in paragraph 'X':`
context line. Still open: `stmt-delete` on a line holding two
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

**Toolchain failures are never scored (issue #347, 2026-10-22).** A
container that died mid-run used to leave its mutants classified by
whatever the dead `docker exec` happened to return (a compile failure read
as `stillborn`, an empty run as a kill or a survivor), so the score moved
by a number that was Docker's, not the suite's. `_run_suite_once` now
returns status `error` when a compile fails or a run ends in anything but
a green run or a case's own assertion failure
(`_verdict_is_the_programs`) AND the toolchain is at fault: docker CLI
error text on stderr (`docker_toolchain.docker_failure_line`), or a
read-only `docker inspect` saying the container is gone or stopped
(`docker_toolchain.toolchain_failure`). `_run_one_mutant` restarts the
toolchain (`ensure_toolchain`) and retries such a mutant once; a second
`error` becomes `MutantResult.status == "error"`: excluded from the score,
listed in the console, `totals.errors` and `complete: false` in the JSON,
and `mutate` exits 1 on an incomplete outcome whatever `--fail-under` says.
`report` never passes the threshold on an incomplete score and says so in
the step summary and the summary tile. A baseline `error` aborts with a
message blaming Docker, not the suite. Two faults leave the container up
afterwards, so the inspect alone missed them and scored a kill
(2026-10-25): `_run_suite_once` reads `docker_toolchain.container_identity()`
(ID + StartedAt) before the compile and `_run_fault` compares it after a
run with no verdict of its own -- a change means another `--jobs` worker
restarted the container mid-run; and exit 137 (`SIGKILL_EXIT_CODE`) before
the deadline is the out-of-memory killer in the shared `--memory 1g`
container, whose INCOMPLETE line then says to re-run with `--jobs 1`. A 137
after the deadline is `timeout -k` escalating, classified `timeout`.

**Equivalent mutants (issue #349, 2026-10-22).** `mutation/equivalence.py`'s
`equivalence_reason(mutant, original_lines, ast)` proves two shapes
cannot change the program, and `runner._equivalent_mutants` (one extra
`run_static_checks` pass, for the data-item facts) marks them
`status == "equivalent"`, `ran=False`, before anything is built: a
`stmt-delete` of a MOVE / `SET <88> TO TRUE` / INITIALIZE whose every
target (or an enclosing group) the next code line overwrites in full with
a literal MOVE or a `SET <88> TO TRUE` (88 owners resolved from the
parent's `ConditionNameItem` children), and an `arith-verb-swap` of
`ADD/SUBTRACT n` on an unsigned, non-edited numeric field the previous
code line zeroes (`MOVE ZERO/0 TO f`, `INITIALIZE f`). Both statements
must be single-line and complete, operands plain names or literals, and a
statement ending a sentence it did not start (its period may close an IF)
disqualifies. Excluded from the score like stillborns, listed in the
console with the reason, `totals.equivalent` in the JSON, and named in the
report's mutation step. This complements the zero-baseline hint below,
which covers the swap when the zero comes from the test data rather than
the program.

**Declared equivalent mutants (2026-10-25).** For what no static proof
covers, `mutation/declared.py` reads `<cut stem>.equivalent.json` beside
the `.cut` (committed with the suite, deliberately not under
`.mockymock/`, which `clean` empties): entries name a mutant by `operator`
plus `original` statement text (columns 8-72, whitespace and case
collapsed, so a moved line keeps its entry) and/or `line`, optionally
`mutated`, and require a `reason`. `runner._declared_equivalents` marks
each match `equivalent` with detail `declared equivalent: <reason>`
before anything is built; ignored entries (no reason, no target, bad
JSON) and entries matching no mutant come back as `notes`. The file's
hash is part of `report/artifacts.fingerprint`, so a saved mutation
result is not reused across an edit to it.

**Zero-baseline hints (2026-10-04).** An `ADD..TO <-> SUBTRACT..FROM`
swap on an unsigned numeric field that every case starts at zero is
indistinguishable from the original (0 + n and 0 - n both store n), so it
survives however good the assertions are. After the kill loop,
`runner._attach_zero_baseline_hints` re-runs `run_static_checks` once and
`mutation.zero_baseline.zero_baseline_hint` sets `MutantResult.hint` on
each *built* survivor where every receiving name on the mutated line is an
unsigned, non-edited, non-OCCURS WORKING-STORAGE/LOCAL-STORAGE item whose
reset value is zero (VALUE zero, or no VALUE -- `splicer/reset.py`'s
default) and no test case writes it (setup MOVE, mock ROWS/TERMINAL, `TO
<name>` in a mock body). GIVING forms are skipped. Since 2026-10-09 at
least one receiving name must also be *observed* (`_is_observed`): an
EXPECT names it or a group holding it, or `cobolparser.analysis.xref`
finds it read by a statement other than its own ADD/SUBTRACT update and
DISPLAY (MOVE, condition, CALL argument, ...). A counter that is only
incremented and DISPLAYed is a missing assertion first -- seeding alone
would not kill it -- so it gets no hint and `mockymock report` files it as
`missing-assertion`; it used to be labelled untestable. xref is new in
cobol-parser 1.10 (floor 1.7.7): without it, or on any xref error, the
field counts as observed and the hint stays. The statement must also run
at most once per case (`_may_run_more_than_once`, issue #203): an
ADD/SUBTRACT in a paragraph a looping PERFORM (UNTIL/VARYING/TIMES)
reaches, or in a looping inline PERFORM body (`analysis/loops.py`), gets
no hint -- a counter bumped n times ends at n while the swap alternates
1, 0, 1, ..., so a plain EXPECT kills it. The AST is copybook-expanded
and `mutant.line` is a line of the program itself, so the mutant's line
is first mapped through `StaticCheckResult.source_location_map` (issue
#342: a WORKING-STORAGE COPY shifted every PROCEDURE DIVISION line and
the loop check never matched). The verdict and score
are unchanged -- seeding the field is how the author kills it -- but the
console prints a `!` line under the diff plus a count, `--json-report`
carries a per-mutant `hint`, and `mockymock report` files it as
`untestable-mutant` instead of `missing-assertion`. Coverage-gated
survivors never get one (no test reaches them).

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
percentage, compared exactly (`MutationOutcome.score_below`, as fractions:
`score * 100` would put 29/50 at 57.99999999999999, printed `58.0%` yet
under `--fail-under 58`). Every baseline/mutant run's `StaticCheckResult.notes` (a
paragraph-scoped `PARSE_WARNING`/`UNRESOLVED_COPYBOOK` waived rather than
refused — [analysis](analysis.md)) is collected (union, first-seen order,
deduped) and printed as `mockymock mutate: <note>` lines before the
outcome — this path compiles doctored source (a waived COPY's line
commented out) exactly like `run` does, so it keeps the same
never-silent guarantee. Boundary statements (mocked) and terminators (rewritten by
terminator plans) are never mutated — mutating them would test the
harness, not the program. For a multi-line `EXEC ... END-EXEC` that covers
every line of the block, not just the `EXEC` line (`generate_mutants`
tracks the open block): an SQL `WHEN BALANCE > 1000` or a CICS
`SET(ADDRESS OF X)` inside it would otherwise be an unkillable survivor.

## `mockymock lint <program> --cut PATH [--copybook-path DIR ...]`

Runs `run_static_checks` and nothing else: every refusal `run` would print,
with zero Docker dependency. `_cmd_lint` never imports
`mockymock.runtime.docker_toolchain` (structural guarantee, tested by
`tests/unit/test_checks.py`). Output: one `mockymock lint: <problem>` line
per problem plus a `N problem(s) found.` summary, exit 1; or
`mockymock lint: no problems found.`, exit 0. Built for editors (the VS Code
extension publishes these as diagnostics), pre-commit hooks, and CI lanes
without a daemon.

**Warnings (2026-10-14).** `checks.no_assertion_warnings(suite)` adds one
`mockymock lint: warning (NO_ASSERTION): .cut line N: TESTCASE "X" asserts
nothing ...` line per TESTCASE with no EXPECT/VERIFY
(`MockTestCase.assertion_count == 0`; PROVIDER rows sharing a header line
report once), then `N warning(s).`. Warnings never change the exit code.
They print even when a refusal stopped `run_static_checks` before it parsed
the `.cut` (`_cmd_lint` re-parses it quietly), since the check is
`.cut`-only. The `.cut line N` wording is what lets the extension place the
diagnostic on the TESTCASE header.

**Untestable omitted-argument branch (issue #288, 2026-10-16).**
`StaticCheckResult.warnings` carries program-side warnings, which lint
prints (and counts) ahead of the NO_ASSERTION ones and `run` prints with
its notes. The one producer so far: `warning (OMITTED_ARGUMENT_UNTESTABLE):
paragraph P, line N: ...` for each `ADDRESS OF <folded LINKAGE item>`
compared with `NULL`/`NULLS` (either side, `IS`/`NOT`/`EQUAL TO` allowed;
a receiving `SET ADDRESS OF X TO NULL` is not a test) and each
`NUMBER-OF-CALL-PARAMETERS`, in a paragraph the selected cases' reachability
union (`union_executed_paragraphs`; None reports every one) can execute.
The fold gives every parameter storage and the driver PERFORMs rather than
CALLs, so the omitted-argument branch can never run. Items the program
rebinds itself (BASED, issue #226) are skipped. Detection is
`analysis.linkage.omitted_argument_tests`, the text is
`omitted_argument_warnings`. A warning, not a refusal: the passed-argument
branch is still testable. Issue #288's option 2; its option 1 (an `OMIT
<item>` statement folding the item BASED and setting its address to NULL
per case) is not built and shares the BASED work with #226.

**Unknown data-names (issue #204, 2026-10-16).** `run_static_checks` step
7b (`analysis.cut_names.check_cut_data_names`, cumulative with step 8)
refuses `UNKNOWN_DATA_NAME` at the `.cut` line of every setup/hook MOVE
target, EXPECT data-name and non-`UT-CAP-` `CAPTURE ... INTO` target, and
every bare-word MOVE/EXPECT value (`TO BE Y`), that appears nowhere in the
transformed program text (literals and `*>` comments stripped; generated
SQLCA and `EXEC SQL INCLUDE` members count), is not a harness item this
suite's driver declares (its fixed `UT-` fields, every tally with its
`-BASE`/`-START` twin, every `UT-CAP-` target a CAPTURE line declares --
not any `UT-` word, issue #296), DFHEIBLK/DLIDIB field, special register
or figurative constant. The AST's own data-item and condition names
(`cut_names.data_item_levels`) are known too: a name built through
`REPLACE` pseudo-text appears in no word of the pre-REPLACE text the
splicer compiles (issue #273). Loose on
purpose: it only catches names cobc would certainly reject.
`MockTestCase.setup_move_lines` / `MockDirective.capture_lines` carry the
line numbers the model did not record before. ROWS rows and the `TERMINAL`
group are checked the same way, field and value (issue #299), at
`MockDirective.row_lines` / `terminal_line`. A MOCK body is otherwise
spliced unchecked, but each one-line `MOVE <value> TO <target>...` in it has
its targets and bare-word value checked the same way, at its own line
(`MockDirective.body_line_numbers`, issue #243 -- the lint half of that
issue; cobc errors are still reported against the sandbox copy, not
remapped to the `.cut`). The same step refuses
`CONDITION_NAME_MISMATCH` when an EXPECT's kind does not match its item's
level in the AST (issue #307): `TO BE TRUE|FALSE` on an item that is not a
level 88 (the driver would emit `IF NOT X`), or any other value on an 88
(`IF X NOT = v`, "condition-name not allowed here"). A name declared at both
kinds, or not in the AST, is left alone. The same code covers a setup/hook
MOVE or a ROWS/TERMINAL field assigned the wrong kind (issue #251, which
splices TRUE/FALSE as `SET`): TRUE/FALSE to a non-88, any other value to
an 88, FALSE to an 88 with no `WHEN SET TO FALSE`
(`cut_names.conditions_without_false`).

## `mockymock collect [program] --cut PATH [--json] [--boundaries] [--copybook-path DIR ...]`

Parses the `.cut` file only (no `.cbl`, no Docker) and lists the suite and
test cases with 1-based line numbers and tags. `--json` emits the
machine-readable form (`{"version": 1, "cutFile", "suite": {name, line},
"cases": [{name, line, tags}]}`) the VS Code extension uses for
authoritative test discovery; a `CutParseError` yields `{"version": 1,
"error": "..."}` and exit 1. So does every other `--json` failure: a
missing `.cut` or program file, and `--boundaries` without a program, go
through `_print_command_error` too (issue #309; they printed plain text).

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
directly, expanding COPY through the same copybook lookup lint/run use
(`--copybook-path`, else the config file's `copybook_path`, plus the
program's `copybooks/` folder via `_apply_config_to_args`; issue #200 --
before, only an explicit flag expanded, so a site inside a copybook
vanished from the list with exit 0) -- it does not go
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
table never drifts from what the codebase can actually produce). The scan
reads `code="X"`, flow_mocks.py's positional `_refusal("X", ...)` and a
printed `refused (X)` problem string; before 2026-10-10 it read only the
first, so `UNRESOLVED_FLOW_MOCK_TARGET`, `UNRESOLVED_CAPTURE_TARGET` and
`COLUMN_OVERFLOW` were emitted but `explain` called them uncatalogued. Bare
`explain` or `explain --list` prints every catalogued code; `explain
<CODE>` (case-insensitive) prints its explanation, or -- if uncatalogued
-- a `not catalogued` message naming every code that is (never a silent
empty result, same "partial and reported" posture cobol-parser's
`le_signatures.py` uses). Backs `mocky-mock-vscode`'s planned
refusal-code hover via `explain --json`. See
docs/2026-09-15-cut-editor-intelligence-design.md.

## `mockymock dashboard [--port N] [--no-browser] [--reports-dir DIR]`

Serves the static status page on `127.0.0.1` (host not configurable) until
Ctrl-C, opening a browser unless `--no-browser`. Unlike `setup`, it is
**read-only** — it calls `runtime.status.probe()`, never
`ensure_toolchain()`, so a polling page can't trigger image builds. A taken
port yields `mockymock dashboard: could not serve on ...` and exit 1.
`--reports-dir` (default: cwd) is where the test-results panel looks for
`*.report.html`; it is passed to `serve(reports_root=...)` as a `Path`, or
`None`. Full details in [dashboard](dashboard.md).

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
The prefix is applied *before* splicing, so `splice_program(..., column_offset=SEQUENCE_AREA_WIDTH)`
tells the one column-sensitive step, the clause-body lift, about the shift (issue #325): without it
`lift_clause_bodies` found no word at its AST offsets and every mocked statement's AT END / NOT AT
END / INVALID KEY / ON EXCEPTION body (and the `UT-MOCK-STATUS` bookkeeping) was dropped from the
export while `run` kept them -- a read-until-EOF loop hung.
`export` also passes `run_static_checks(..., model_rebinds=False)` (issue #321): a folded LINKAGE
item `run` keeps as a real rebind (`mark_based`, #226) would put `BASED` and `SET ADDRESS OF` on a
WORKING-STORAGE item into the output, both GnuCOBOL / Micro Focus only. Export keeps the IBM-legal
`UT-ADDR-SINK` redirect instead, lists the items in `StaticCheckResult.unmodelled_rebinds`, prints a
warning, and names them in the provenance header (`build_provenance_header(..., unmodelled_rebinds)`):
a case that relies on the rebind may fail in the export although it passes under `run`.
A provenance/disclaimer header is inserted directly before `IDENTIFICATION DIVISION` (or the IBM
abbreviation `ID DIVISION`; with neither, after any leading `CBL`/`PROCESS` cards — IBM requires
those before any comment line, #276), documenting that this is a
mock-only build (every boundary is either mocked or fails loudly; no real I/O executes) and listing
known GnuCOBOL-vs-IBM-COBOL gaps that a clean compile here does not rule out. Output path defaults
to `<program-stem>.mainframe.cbl` next to the input `.cbl`, matching `generate`'s suffix-swap convention.

Every width in that module is measured in **UTF-8 bytes** (`_width()`), the unit a fixed-format
compiler counts columns in, not characters: measured with `len()`, a non-ASCII TESTCASE name, EXPECT
or MOVE literal (`é` is 2 bytes, `’` 3) shipped lines past column 72 that every check said fit (#298).
Splits still fall only between characters, so a multibyte character is never cut in half.

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

## `mockymock skills install [--project] [--force] [--skill NAME ...] [--target claude|copilot|all]`

Copies the packaged agent skills (`SKILL_NAMES`: `mockymock`,
`cobol-analysis`, `cobol-test`, each under `mockymock/cli/skills/<name>/`)
to `~/.claude/skills/<name>` (default) or `./.claude/skills/<name>`
(`--project`). `--skill` (repeatable) narrows the set; without it all
three are installed. `--target` (2026-10-04) picks the assistant:
`claude` (default, paths above), `copilot` (`~/.copilot/skills/<name>`,
`--project`: `./.github/skills/<name>`, the directories GitHub Docs'
"About agent skills" lists for personal/project skills) or `all`. The
skills are standard Agent Skills, so the files are identical per target;
`tests/unit/test_agent_skills_format.py` pins the spec's frontmatter rules
(name = directory, lowercase-hyphen, <= 64; description <= 1024). Fail-closed as a set (2026-10-04): every target is
checked before anything is copied, so one existing directory without
`--force` installs none of them. Implementation lives in `mockymock/cli/skills_cmd.py`,
imported lazily inside `_cmd_skills_install` for the same deferred-import
reason every other subcommand uses, even though nothing here is actually
heavy (`shutil`/`pathlib` only) -- consistency with the rest of this
module.

`resolve_target(project: bool, name="mockymock", target="claude") -> Path` picks the base directory
(`Path.cwd()` or `Path.home()`) and, via `skills_dir`, the assistant's directory; `install_skill(target, force=False, name="mockymock")`
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

## `mockymock report <program> [--cut PATH] [-o/--output PATH] [--json PATH] [--copybook-path DIR ...] [--execute] [--mutate] [--run-json PATH] [--coverage-json PATH] [--mutation-json PATH] [--journal PATH] [--scenarios happy|branches|all|none] [--seed N] [--timeout S] [--mutation-threshold PCT]` (2026-10-04)

One self-contained HTML page (default `.mockymock/<cut stem>.report.html`
next to the `.cut`, one per suite -- issues #192, #353;
`--json` also writes the underlying dict) of every step of testing a
program and what each test proves. Backs the `cobol-test` skill's final
step. Builder is `report/test_report.py` (`ReportOptions` ->
`build_report() -> dict`), renderer `report/html_report.py`; see
[report](report.md). Prints one line per step; exit 1 when a case failed
or the suite was refused, else 0.

`--execute` / `--mutate` re-invoke `python -m mockymock.cli.main run`
(`--json-report --coverage-json`) and `mutate --json-report` as
subprocesses into a temp dir rather than calling `_cmd_run` in-process,
so a toolchain failure is one step's `fail`, not a crashed report.
Passing `--run-json` / `--coverage-json` / `--mutation-json` reuses
reports from an earlier run instead. Without them, `--execute` / `--mutate`
first look for results `run` (whole suite, no `--case`/`--tag`) and
`mutate` (complete outcomes only) saved in `.mockymock/` and reuse them
while `report.artifacts.fresh_result` says they were computed from the same
program, `.cut`, copybook directories (name/size/mtime of each file) and
mockymock version (issue #352); the step summary says it reused them.
`--rerun` (`ReportOptions.reuse=False`) always runs. A reused run with no
saved coverage leaves the coverage step `skipped` with that reason. Without any of them the report is
static: lint (`cli.checks.run_static_checks`), flow, rules, scenarios,
dialect risks, and a verification level no higher than L0.

`--cut` defaults to `<program stem>.cut`; `--journal` to
`.mockymock/<cut stem>.journal.jsonl` (`report.journal.default_journal_path`
-> `report.artifacts.journal_path`, which keeps using a pre-#353
`<cut stem>.journal.jsonl` next to the `.cut` when one exists and the new
one does not).
`--scenarios none` skips the cobol-parser `ProgramFixtureGenerator`
step (slow on large programs).

## `mockymock journal --step NAME --summary TEXT [--cut PATH | --file PATH] [--status ok|warn|fail|skipped|info] [--command TEXT] [--decision TEXT]` (2026-10-04)

Appends one JSON line to the assistant's step journal
(`report/journal.py`): what the `cobol-test` skill did, why, and what came
of it -- the half of the story `report` cannot recompute. `--file` wins
over `--cut`'s default path. `--command` is stored as `command` (argparse
dest `command_text`, since `command` is the subparser dest). Unknown
status or empty step/summary -> exit 2 with a message, nothing written.
`read_journal` splits the file on `\n` only: entries are written with
`ensure_ascii=False`, which leaves U+2028/U+2029/NEL raw inside a string,
and `str.splitlines()` broke such an entry into unparseable pieces (#283).
`--from FILE|-` (issue #353) appends a batch in one process: a JSON array
or JSON lines, each object with `step`/`summary` and optional
`status`/`command`/`decision` (`journal.parse_batch` validates every entry
before any is written; unknown keys are refused); it cannot be combined
with the single-entry flags, which are no longer `required=True` so the
check is `_cmd_journal`'s own.

## `mockymock clean [PROGRAM.cbl | PROGRAM.cut | DIR] [--all] [--dry-run]` (2026-10-22)

Issue #353. Every artifact mockymock writes for a suite lives in one
folder, `.mockymock/` next to the `.cut`, named `<cut stem>.<kind>`
(`report/artifacts.py`'s `KINDS`: `report.html`, `report.json`,
`run.json`, `coverage.json`, `mutation.json`, `journal.jsonl`, and
`inputs.json`, the fingerprints `fresh_result` checks). Keyed by the
`.cut` stem, not the program's, since a program can have several suites.
`clean` removes them for one suite, every `PROG*.cut` suite of a program,
or everything under a directory (`os.walk`, entering `.mockymock` but no
other hidden or dependency folder), plus the pre-#353 files
(`<stem>.report.html` / `.report.json` / `.mutation.json` beside a
same-stem `.cbl`/`.cut`). Journals are kept unless `--all`; an emptied
`.mockymock/` is removed.

## `mockymock skills plugin [DIRECTORY] [--force]` (2026-10-04)

Writes the `cobol-testing` plugin as a self-contained **local
marketplace** (`skills_cmd.export_plugin`), default
`~/.mockymock/claude-plugin`: `.claude-plugin/marketplace.json` (name
`LOCAL_MARKETPLACE_NAME` = `mocky-mock-local`, so it never collides with
the GitHub/clone marketplace `mocky-mock`) plus `cobol-testing/` holding
`.claude-plugin/plugin.json` and `skills/<SKILL_NAMES>`. Exists because a
wheel carries only `mockymock/cli/skills/`, not the repo-root
`.claude-plugin/`. The exported manifest is `PLUGIN_MANIFEST` with
`version = mockymock.__version__` and no `skills` key (the default
`skills/` folder is used); `tests/unit/test_cobol_testing_plugin.py`
pins `PLUGIN_MANIFEST` to the repo manifest minus `skills`/`version`.
Fail-closed: a non-empty directory is replaced only with `--force` AND
only when its marketplace.json names `mocky-mock-local` -- a mistyped path
is never `rmtree`d. From a clone, `/plugin marketplace add <repo>` works
directly off the repo-root manifests.

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

**Every `.cbl`/`.cut` read goes through `_lines.read_utf8_source` (2026-09-30, bug hunt round 12).** A non-UTF-8 source (cp1252 etc.) raises `SourceEncodingError` (a `ValueError` naming the file, the byte offset and an `iconv` fix) instead of a `UnicodeDecodeError` traceback; `run_static_checks` reports it as a problem and `main()` prints it in each command's own error convention (JSON for `collect --json`, stderr otherwise). Policy is refuse, never guess a code page: the spliced copy is compiled as UTF-8, so a guessed cp1252 `PIC X` literal would silently change length. `keep_newlines=True` (used by `generate --fill`, which writes back with `newline=""`) skips universal-newline translation so a CRLF `.cut` stays CRLF. A leading UTF-8 BOM is dropped (`utf-8-sig`) except under `keep_newlines`, whose rewriting callers keep it to round-trip it; `parse_cut` ignores a leading BOM itself (issue #198, 2026-10-16). New file reads should use it, not `Path.read_text()`.

**`transform_data_division_exec` is called twice, and the first call's return value is intentionally thrown away** (`_cmd_run`, step 9 vs 11). The first pass exists purely to surface `EXEC SQL INCLUDE SQLCA` refusal reasons *before* any splicing happens; running the real transform that early would shift line numbers/spans that `splice_program` and the boundary/nested-site analysis depend on. Any future edit that tries to "simplify" this into one call will silently break splice-target alignment.

**Refusal checks are cumulative, not fail-fast, within a single gate.** `check_test_case` loops over every test case and only returns/exits after checking all of them, so users get every refusal reason in one invocation. But *between* gates (`check_whole_program` -> parse success -> `check_unresolved_copybooks` -> `check_nested_exec` -> `transform_data_division_exec` precheck -> `check_test_case`), the command exits at the first gate that fires — later gates never run if an earlier one refuses.

**`annotate_nested_sites` ordering is load-bearing in both `generate` and `run`.** It must run before anything inspects `surface.boundary_sites` for nested spliceability (`_report_unsupported_boundaries` in `generate`; every refusal check and `splice_program` in `run`). An unannotated nested site is indistinguishable from an unspliceable one, so calling this late produces false-positive refusals.

**`_insert_driver` matches section/division headers with whitespace-tolerant regexes** (`_WS_HEADER_RE`, `_DATA_DIVISION_RE`, `_PROCEDURE_DIVISION_RE`: `^\s*WORD\s+WORD\b`, case-insensitive) and inserts only at the first match. They were literal single-space prefix checks until #305, so `WORKING-STORAGE  SECTION` (lint-clean, cobc-clean) got no driver fields while `has_ws` said the section existed, and `PROCEDURE  DIVISION` got no driver paragraphs (every case NOT RUN); the presence check and the insertion point now share one regex. A program with unusual formatting where these headers aren't isolated on their own line (unlikely post `normalize_fixed_format`, but not structurally prevented) would silently fail to get the driver inserted.

# See Also

- [runtime](runtime.md)
- [report](report.md)
- [dsl](dsl.md)
- [coverage](coverage.md)
- [dashboard](dashboard.md)
