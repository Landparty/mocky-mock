# Reducing repeated CLI ceremony (2026-09-15)

## Problem

Every subcommand takes three pieces of boilerplate a user re-types on
every invocation, with no way to stop:

1. **`--cut` is `required=True` on every subcommand that takes one**
   (`run_parser.add_argument("--cut", required=True)` and identically for
   `debug`/`lint`/`mutate`/`collect` -- `mockymock/cli/main.py:1794`,
   `:1923`, `:1949`, `:1966`, `:2029`), even though the VS Code extension
   already derives the `.cut` path from the `.cbl` path by same-basename
   convention (`resolveCblPath`/`resolveCutPath`,
   `mocky-mock-vscode/src/discovery/cutDiscovery.ts:169-182`). A CLI user
   gets none of that convenience.
2. **`--copybook-path` is a repeatable flag with no persistent home.**
   `examples/real-world/README.md` tells every reader to type
   `--copybook-path examples/real-world/<PROGRAM>/copybooks` on every
   command by hand; there is no project-level place to say this once.
3. **`run`/`lint`/`mutate`/`debug` take exactly one `program` positional**
   (`mockymock/cli/main.py:1793`, `:1948`, `:1965`, `:1922`). Testing a
   directory of programs means a shell loop the user writes themselves;
   `.github/workflows` in downstream repos would have to do the same.

None of this is a correctness bug -- lint/run/mutate all work today -- it
is pure repeated typing that a config file and a same-name convention
remove.

## Goals

- A `.cut` file's sibling `.cbl`/`.cob` is found automatically; `program`
  becomes optional wherever `--cut` (or a discovered `.cut`) already
  names one file uniquely.
- A per-project config file supplies `copybook_path`, `seed`, and
  `timeout` so they don't need repeating on every invocation, with CLI
  flags always overriding the file.
- `mockymock run`/`lint` with no `program` argument discover and run
  every `.cut` file under the current directory (or a configured test
  root), reporting one aggregate result.
- `mockymock setup --help` and the top-level `--help` explain what they
  do and group commands by how often they're used.

## Non-goals

- No change to the one-`.cut`-per-`TESTSUITE` model, and no multi-cut
  merging semantics beyond "run each independently, aggregate the
  report."
- No auto-detection of Docker/GnuCOBOL settings beyond what already
  exists in `runtime/status.py` -- that is `doctor`'s job (see
  `2026-09-15-doctor-command-design.md`).

## Design

### 1. Sibling-file inference

Add `mockymock/cli/discovery.py`:

```python
COBOL_SOURCE_EXTENSIONS = (".cbl", ".cob", ".CBL", ".COB")

def resolve_program_path(explicit: str | None, cut_path: Path) -> Path:
    """Mirrors mocky-mock-vscode's resolveCblPath: same directory, same
    stem, first extension in COBOL_SOURCE_EXTENSIONS that exists on disk.
    Raises CliUsageError with the candidates tried if none exist and
    `explicit` was not given."""
```

Wire it into each `_cmd_*` that currently requires `program`: change
`program` from a required positional to `nargs="?"`, and when omitted,
resolve it from `--cut`'s sibling. When `--cut` is *also* omitted (see
directory-discovery below), resolution happens per discovered `.cut`.

Symmetrically, if `program` is given but `--cut` is not, look for
`<program-stem>.cut` next to it before falling back to the existing "cut
is required" error -- this makes `mockymock run ORDRPROC.cbl` alone work
when `ORDRPROC.cut` sits beside it, matching the extension's other
direction (`resolveCutPath`, `cutDiscovery.ts:181`).

Both directions are opt-in sugar: an explicit `--cut`/`program` always
wins, so no existing invocation changes behavior.

### 2. Project config file

New module `mockymock/cli/config.py`:

- Search order, first match wins: `./mockymock.toml`, then a
  `[tool.mockymock]` table in `./pyproject.toml`, walking up parent
  directories the same way `git` finds `.git` (stop at the filesystem
  root or after 32 levels, whichever first -- avoids a runaway walk on a
  detached/networked filesystem).
- Recognized keys, all optional: `copybook_path` (string or list of
  strings, resolved relative to the config file's own directory, not the
  cwd), `seed` (int), `timeout` (int, seconds), `test_root` (string,
  default `"."`, used by directory discovery below).
- `tomllib` (stdlib, Python >= 3.11 -- matches this repo's floor per
  `pyproject.toml`) parses both file shapes; no new dependency.
- Precedence, highest first: explicit CLI flag > config file > built-in
  default. Implemented by defaulting each `add_argument(..., default=None)`
  and filling `None`s from the loaded config after `parse_args()`, in one
  place (`_apply_config_defaults(args, config)`) called from `main()`
  before dispatch -- so every `_cmd_*` keeps reading `args.copybook_path`
  etc. unchanged.
- A malformed config file is a hard error naming the file and the parse
  exception, not a silent fallback to defaults -- consistent with this
  repo's fail-closed posture (`.okf/dsl.md`'s own framing).

### 3. Directory discovery for `run`/`lint`

When `program` and `--cut` are both omitted:

- Walk `test_root` (default `.`) for `**/*.cut`, excluding the same
  directories the VS Code extension already excludes
  (`CUT_DISCOVERY_EXCLUDE_GLOB` in `cutDiscovery.ts` -- mirror that glob
  literally so behavior matches between CLI and editor).
- For each discovered `.cut`, resolve its sibling program (step 1); a
  `.cut` with no resolvable sibling is a per-file error collected into
  the final report, not a hard stop (one broken pair should not block
  the rest of the suite from running).
- Run each pair through the *existing* single-pair `_cmd_run`/`_cmd_lint`
  body (refactored into a `_run_one(program, cut, args) -> TestSuiteResult`
  helper first, so the multi-file path is a thin loop over it, not a
  parallel implementation).
- Aggregate console output as one summary per file, then a grand total;
  `--junit-xml`/`--json-report` become directories (one file per
  `.cut`, plus a merged top-level file) when more than one pair ran, and
  stay single-file when exactly one did -- so today's single-pair
  invocations produce byte-identical output.
- `mutate`/`debug` are explicitly out of scope for directory mode:
  mutation testing is already slow per-program (`--jobs` exists for that
  reason) and `debug` is inherently single-case; multiplying either
  across a directory silently is more likely to hang a terminal than help.

### 4. Help text and `setup --help`

- `setup_parser.add_argument(...)` currently has none (`mockymock setup
  --help` prints only `-h`). Add `--rebuild` (force image rebuild even if
  cached) and document the two things `setup` actually does today
  (`docker_toolchain.ensure_toolchain`'s build + container-start steps)
  in the subparser's `help=`/`description=`, even if no new flags land --
  the missing documentation is the actual bug, not missing functionality.
- Group the top-level subcommand list in `build_parser()`'s epilog (argparse
  doesn't support subparser groups natively, so this is a formatted
  `epilog=` block, consistent with how `mockymock --help` already reads):
  **Everyday**: `run`, `generate`, `lint`, `collect`. **Diagnosing a
  failure**: `debug`, `analyze`, `dashboard`. **Advanced**: `mutate`,
  `export`, `fixtures`, `skills`, `setup`.

## Implementation steps

1. `mockymock/cli/discovery.py` -- new module, `resolve_program_path`,
   `resolve_cut_path`, `discover_cut_files`; unit tests with a tmp_path
   fixture covering: exact match, no match (error names candidates tried),
   both `.cbl` and `.cob` present (deterministic order, `.cbl` first),
   case-insensitive extension on a case-insensitive filesystem (skip the
   assertion on Linux CI, matching existing `sys.platform` guards elsewhere
   in the test suite).
2. `mockymock/cli/config.py` -- new module, `load_config(start_dir) ->
   MockymockConfig` dataclass; unit tests: no config found (all-None),
   `mockymock.toml` found, `pyproject.toml` `[tool.mockymock]` found (and
   preferred correctly when both exist... actually per the search order
   above `mockymock.toml` wins if present in the same directory -- test
   that), malformed TOML raises with file name in the message, relative
   `copybook_path` resolved against the config file's directory not cwd.
3. `mockymock/cli/main.py`: change `program` to `nargs="?"` on `run`,
   `lint`, `debug`, `mutate`; change `--cut` to `required=False` on the
   same four plus `collect`; call `_apply_config_defaults` in `main()`
   right after `parse_args()`; extract `_run_one`/`_lint_one` helpers from
   the current `_cmd_run`/`_cmd_lint` bodies; add the directory-discovery
   branch to `_cmd_run`/`_cmd_lint` when both `program` and `cut` end up
   `None` after inference.
4. Update `docs/options-reference.md` and `.okf/cli.md` with the new
   resolution order (explicit flag > config file > sibling-file
   inference > directory discovery) and the config file schema.
5. `.okf/log.md`: dated entry.

## Testing plan

- Unit: `discovery.py`, `config.py` as above (Docker-free, `tests/unit/`).
- Unit: `_apply_config_defaults` precedence (flag beats config beats
  default) with a fake `argparse.Namespace`.
- Integration (Docker-gated, `tests/integration/`): `mockymock run` with
  no `--cut` against `examples/ordrproc/` (sibling inference), and
  against a tmp copy of `examples/real-world/` with a `mockymock.toml`
  supplying `copybook_path` (config file replaces the flag from the
  README's manual instructions) -- this test doubles as the regression
  guard for Finding 5 in `docs/2026-09-05-project-deep-audit.md` (shipped
  examples the gate currently refuses only because the flag was never
  passed).
- Full corpus sweep: `mockymock lint` with directory discovery over
  `examples/` should produce the same pass/fail set as looping the
  existing single-pair invocation over every example by hand.

## Backward compatibility

Every change here is additive: explicit `program`/`--cut`/`--copybook-path`
flags keep behaving exactly as today, byte-identical output included.
Existing CI pipelines that pass everything explicitly are unaffected.

## Open questions

- Should `mockymock.toml` support per-program overrides (a table keyed by
  program name) for repos where different programs need different
  copybook paths? Deferred: start with one global `copybook_path` list
  the way `--copybook-path` already lets it be repeated, and revisit if
  directory discovery in practice needs finer grain.
