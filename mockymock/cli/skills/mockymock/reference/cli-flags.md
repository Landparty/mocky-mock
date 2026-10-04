# mockymock CLI: subcommand and flag reference

`mockymock <subcommand> [options]`. Fifteen subcommands: `setup`,
`init`, `generate`, `fixtures`, `run`, `debug`, `lint`, `mutate`,
`collect`, `explain`, `dashboard`, `doctor`, `export`, `analyze`,
`skills`. Running `mockymock` with no subcommand prints help and exits 1.

Only `setup`, `run`, `init`, `debug`, and `mutate` need a running
Docker daemon (COBOL is compiled and executed inside a GnuCOBOL
container).
Everything else is pure parse-and-analyze -- which is what makes `lint`
the fast inner loop while writing a `.cut` file.

## Argument inference and the project config file

Most subcommands can work out their own arguments:

- Pass only `--cut PROGRAM.cut` and the program is inferred from the
  sibling file with the same stem (`.cbl`, `.cob`, `.CBL`, `.COB`, in
  that order); pass only `PROGRAM.cbl` and `--cut` is inferred the same
  way. Either explicit path always wins.
- `run` and `lint` with **neither** argument discover and process every
  `.cut` file under the current directory (or the config file's
  `test_root`), skipping `.git`, `node_modules`, `.venv`, `dist`,
  `build`, and the other usual suspects.
- A `mockymock.toml`, or a `[tool.mockymock]` table in `pyproject.toml`,
  found by walking up from the source file, supplies defaults for
  `copybook_path`, `seed`, and `test_root`. Precedence is always
  explicit flag > config file > built-in default, and an unrecognized
  key is an error rather than silently ignored. `mockymock doctor`
  reports which config file (if any) is in effect.

## `mockymock setup`

```bash
mockymock setup [--rebuild]
```

Builds the GnuCOBOL Docker image (if needed) and starts the
`mockymock-cobc` container, then prints the compiler version.
`--rebuild` forces a fresh image build even when a current one is
cached. Optional in normal use -- `mockymock run` does this
automatically -- but useful as a fast up-front check or CI warm-up so
the first real `run` isn't the one paying for the image build.

## `mockymock init`

```bash
mockymock init <program.cbl> [options]
```

One command from a COBOL program to a `.cut` file with real, recorded
assertions: `generate --with-data` followed by `run
--record-expectations`, so the first scaffold has generated mock data
and recorded expected values instead of empty bodies. Needs Docker for
the recording half; without it, degrades to a plain data-driven scaffold
and prints the next step.

| Option | Default | Description |
|---|---|---|
| `program` (positional) | required | The `.cbl` source file. |
| `-o`, `--output PATH` | `<program>.cut` | Where to write the `.cut` file. |
| `--seed N` | random | Seed for the fixture bundle's generated data. |
| `--scenarios {happy,branches,all}` | `happy` | Same meaning as `generate --scenarios`. |
| `--copybook-path DIR` (repeatable) | none | Same meaning as `generate --copybook-path`. |
| `--force` | off | Overwrite the output `.cut` file if it already exists. |

Unlike `generate`, `init` **refuses to overwrite** an existing `.cut`
without `--force`. Recorded expectations are characterization values
(what the program does today), not verified intent -- read them back
before treating them as assertions.

## `mockymock generate`

```bash
mockymock generate <program.cbl> [options]
```

Scaffolds a starter `.cut` file by statically analyzing which boundaries
each paragraph touches. Never touches Docker.

| Option | Default | Description |
|---|---|---|
| `program` (positional) | required | The `.cbl` source file to scaffold from. |
| `-o`, `--output PATH` | `<program>.cut` | Where to write the generated `.cut` file. **Overwritten without asking** -- see `--fill` for an existing file. |
| `--fill CUT_FILE` | none | Insert only the `MOCK` blocks `CUT_FILE`'s existing test cases are missing (from the same `UNMOCKED_*` analysis `lint` runs), writing back in place. Every existing directive, `EXPECT`, `VERIFY`, and comment is preserved byte for byte; an existing `MOCK` block is never edited, even if its body is empty. Mutually exclusive with `-o/--output`, `--with-data`, and `--fixtures`. |
| `--copybook-path DIR` (repeatable) | none | A directory to search for `COPY`-referenced copybooks. |
| `--with-data` | off | Data-driven mode: one `TESTCASE` per scenario, with real generated mock data and `EXPECT`/`VERIFY` assertions, instead of placeholder bodies. |
| `--fixtures PATH` | none | Use an already-generated fixture bundle JSON file instead of generating one on the fly. Implies `--with-data`. Mutually exclusive with `--rows`. |
| `--seed N` | random | Integer seed for reproducible generated data (`--with-data` only). |
| `--scenarios {happy,branches,all}` | `happy` | `happy` = one "everything succeeds" scenario. `branches` = one scenario per reachable branch arm. `all` = branches plus fixed families (empty input, error status, boundary values). `--with-data` only. |
| `--rows N` | generator default | Rows to generate per data table (`--rows 0` is honored, e.g. to force an immediate-EOF scenario). Mutually exclusive with `--fixtures`. |
| `--placeholder CATEGORY:KEY` (repeatable) | none | Downgrade one boundary's generated mock body back to a plain placeholder, e.g. `--placeholder READ:INV-FILE`. |

Examples:

```bash
mockymock generate ORDRPROC.cbl
mockymock generate ORDRPROC.cbl --fill ORDRPROC.cut
mockymock generate ORDRPROC.cbl -o tests/ORDRPROC.cut --copybook-path copybooks/
mockymock generate ORDRPROC.cbl --with-data --seed 7 --scenarios branches
mockymock generate ORDRPROC.cbl --with-data --rows 5 --placeholder READ:ORDER-FILE
mockymock fixtures ORDRPROC.cbl --seed 7 --scenarios all > bundle.json
mockymock generate ORDRPROC.cbl --fixtures bundle.json
```

After scaffolding, `generate` also prints a list of any boundaries it
could **not** mock -- this doesn't block the scaffold, but `run` will
refuse a test case reaching one of those sites until you resolve it.

## `mockymock fixtures`

```bash
mockymock fixtures <program.cbl> [options]
```

Prints a fixture bundle (generated mock data, scenarios, expectations) as
JSON on stdout -- the same generation `generate --with-data` uses
internally. **stdout is always exactly the JSON document**; every
diagnostic goes to stderr, so `mockymock fixtures ... | jq .` is always
safe on success.

| Option | Default | Description |
|---|---|---|
| `program` (positional) | required | The `.cbl` source file. |
| `--scenarios {happy,branches,all}` | `happy` | Same meaning as `generate --scenarios`. |
| `--seed N` | random | Same meaning as `generate --seed`. |
| `--rows N` | generator default | Same meaning as `generate --rows`. |
| `--copybook-path DIR` (repeatable) | none | Same meaning as `generate --copybook-path`. |

```bash
mockymock fixtures ORDRPROC.cbl --seed 7 --scenarios all --rows 10 > bundle.json
```

## `mockymock run`

```bash
mockymock run <program.cbl> --cut <program.cut> [options]
```

The full pipeline and the command you'll use most: parse, statically check
the `.cut` file, splice in the mocks, compile with real GnuCOBOL inside
Docker, execute, and report pass/fail.

| Option | Default | Description |
|---|---|---|
| `program` (positional) | inferred | The `.cbl` source file. Omit to infer it from `--cut`'s sibling; omit both to run every `.cut` under the current directory (or the config file's `test_root`). |
| `--cut PATH` | inferred | The `.cut` test file to run against `program`. Omit to infer it from the program's sibling `.cut`. |
| `--junit-xml PATH` | none | Write a JUnit XML report there. |
| `--json-report PATH` | none | Write a machine-readable run report (per-case status, `.cut` line numbers, expected vs. actual, tags). |
| `--case NAME` (repeatable) | all cases | Run only the named `TESTCASE`(s). Unions with `--tag`. |
| `--tag TAG` (repeatable) | all cases | Run only `TESTCASE`s carrying this tag. Unions with `--case`. |
| `--copybook-path DIR` (repeatable) | none | Same meaning as `generate --copybook-path`. |
| `--keep-sandbox` | off | Don't delete the temporary sandbox directory; print its path. |
| `--verbose` | off | On a compile failure, print the path to the instrumented source. |
| `--coverage` | off | Compile with `--coverage`/`gcov` and report per-line coverage, remapped onto your original line numbers. |
| `--coverage-out PATH` | none | Write the full coverage report to a file. Implies `--coverage`. |
| `--coverage-json PATH` | none | Write machine-readable coverage, mapped onto the original `.cbl`'s line numbers. Implies `--coverage`. |
| `--coverage-fail-under PCT` | none | Exit nonzero when the original `.cbl`'s line coverage is below this percentage -- `run`'s counterpart to `mutate --fail-under`. Implies `--coverage`. |
| `--timeout SECONDS` | `30` | Binary execution timeout. A mocked `CALL` that removes a loop's terminating condition would otherwise hang until this kills it. |
| `--trace` | off | Replay one test case's execution path plus the mock timeline, in order. **Requires exactly one `--case` and no `--tag`.** |
| `--trace-json PATH` | none | Write a machine-readable execution trace. Implies `--trace`. |
| `--record-expectations` | off | For every `*> STUB EXPECT <name>` comment, capture the value the program actually produced and rewrite it into a real `EXPECT`, in place. Never overwrites a hand-written `EXPECT`. Never changes the run's exit code. |

Examples:

```bash
mockymock run ORDRPROC.cbl --cut ORDRPROC.cut
mockymock run ORDRPROC.cbl --cut ORDRPROC.cut --junit-xml results.xml --tag happy-path
mockymock run ORDRPROC.cbl --cut ORDRPROC.cut --case "rejects negative quantity" --trace --trace-json trace.json
mockymock run ORDRPROC.cbl --cut ORDRPROC.cut --coverage-json coverage.json
mockymock run ORDRPROC.cbl --cut ORDRPROC.cut --verbose --keep-sandbox
mockymock run ORDRPROC.cbl --cut ORDRPROC.cut --record-expectations
```

`run` exits 0 only if every selected test case passed *and* the compiled
binary itself exited 0 -- a crash after the summary line still fails the
run.

## `mockymock debug`

```bash
mockymock debug <program.cbl> --cut <program.cut> --case <name> --dap-stdio [options]
```

Starts an interactive Debug Adapter Protocol (DAP) session for one test
case -- breakpoints, stepping, read-only variable inspection against your
*original* `.cbl` source. Meant to be launched by an editor (the mocky-mock
VS Code extension does this automatically), not typed by hand -- there is
no useful plain-terminal mode; the command refuses without `--dap-stdio`.

| Option | Default | Description |
|---|---|---|
| `program` (positional) | required | The `.cbl` source file. |
| `--cut PATH` | required | The `.cut` test file. |
| `--case NAME` | required, exactly one | The single test case to debug. |
| `--copybook-path DIR` (repeatable) | none | Same meaning as `generate --copybook-path`. |
| `--dap-stdio` | required | Run the DAP adapter over stdio. |

## `mockymock lint`

```bash
mockymock lint <program.cbl> --cut <program.cut> [options]
```

Runs every static check `run` would run, before compiling anything, with
zero Docker dependency. Good for a fast inner loop, pre-commit hooks, and
CI lanes without a daemon.

| Option | Default | Description |
|---|---|---|
| `program` (positional) | required | The `.cbl` source file. |
| `--cut PATH` | required | The `.cut` test file. |
| `--copybook-path DIR` (repeatable) | none | Same meaning as `generate --copybook-path`. |

Prints `mockymock lint: no problems found.` and exits 0 if clean, or one
`mockymock lint: <problem>` line per problem plus a count, exiting 1.

## `mockymock mutate`

```bash
mockymock mutate <program.cbl> --cut <program.cut> [options]
```

Mutation testing: measures how good a `.cut` suite actually is by
patching small changes into the program and checking whether the suite
notices ("killed") or doesn't ("survived" -- a gap in the assertions).

| Option | Default | Description |
|---|---|---|
| `program` (positional) | required | The `.cbl` source file. |
| `--cut PATH` | required | The `.cut` test file. |
| `--copybook-path DIR` (repeatable) | none | Same meaning as `generate --copybook-path`. |
| `--list` | off | Only list the mutants that would be generated, no Docker needed. |
| `--timeout SECONDS` | `15` | Per-mutant execution timeout; a mutant that exceeds it counts as killed. |
| `--jobs N` / `-j N` | `1` | Build and run N mutants in parallel, each in its own sandbox and worker process. The ceiling that matters is not the core count but the shared `mockymock-cobc` container's 1 GiB memory limit, which every concurrent `cobc` draws from at once -- raise it gradually and watch for compile failures on a large program. |
| `--no-coverage-gate` | gate on | Build and run every mutant, including ones on lines the baseline proved the suite never executes. By default those are reported as survivors straight from the baseline's own gcov coverage -- the same verdict, without the compile. |
| `--json-report PATH` | none | Write the full machine-readable mutation report. |
| `--fail-under PERCENT` | none | Exit 1 if the mutation score is below this percentage. |

Mock bodies and terminator statements are never mutated.

## `mockymock collect`

```bash
mockymock collect --cut <program.cut> [options]
mockymock collect <program.cbl> --cut <program.cut> --json --boundaries
```

Lists a suite's test cases with `.cut` line numbers and tags. Parses only
the `.cut` file -- no `.cbl`, no Docker -- unless `--boundaries` is
given.

| Option | Default | Description |
|---|---|---|
| `--cut PATH` | required | The `.cut` test file. |
| `--json` | off | Emit machine-readable JSON instead of a human-readable listing. |
| `program` (positional) | none | Required only with `--boundaries`. |
| `--boundaries` | off | Also report every mockable boundary site in `program` (category, key, paragraph, line, and the `MOCK` directive that would cover it). Requires `--json` and `program`. |
| `--copybook-path DIR` (repeatable) | none | Same meaning as `generate --copybook-path` (`--boundaries` only). |

`--boundaries` is the cheapest way to answer "what can I mock here, and
what is this suite already covering?" for a program that already has a
`.cut` file -- no fixture generation, no Docker.

## `mockymock explain`

```bash
mockymock explain <CODE>
mockymock explain --list
```

Prints the catalogued explanation for a refusal code -- one shared
source of truth for what `UNMOCKED_CALL`, `UNSUPPORTED_DECLARATIVES`,
`PARSE_WARNING`, and the rest actually mean, instead of re-deriving it
from the message text.

| Option | Default | Description |
|---|---|---|
| `code` (positional) | none | The refusal code, e.g. `UNSUPPORTED_DECLARATIVES`. Case-insensitive. |
| `--list` | off | List every catalogued code instead of explaining one. |
| `--json` | off | Machine-readable output. |

Exits 1 on an uncatalogued code (and says so, listing the known ones).

## `mockymock doctor`

```bash
mockymock doctor [--json]
```

Terminal-native readiness report: Docker daemon, toolchain image,
`mockymock-cobc` container, GnuCOBOL compiler, `cobol-parser` import,
and which config file is in effect -- each `[ OK]`/`[FAIL]`/`[ N/A]`,
with the fix for anything failing. Read-only; never builds or starts
anything. Exits nonzero when something is not ready. `--json` for
scripting.

## `mockymock dashboard`

```bash
mockymock dashboard [options]
```

Serves a local, read-only, loopback-only status page showing whether
Docker and the GnuCOBOL toolchain are up. Never builds or starts
anything; runs until Ctrl-C. Also lists the `mockymock report` HTML pages
under `--reports-dir` and shows one inline, and verifies the cobol-testing
skills for Claude Code (`~/.claude/skills/`) and GitHub Copilot
(`~/.copilot/skills/`), with an Install button for each (the same copy as
`skills install --target`; the only write the dashboard makes).

| Option | Default | Description |
|---|---|---|
| `--port N` | `8765` | TCP port to serve on; `0` picks a free one. |
| `--no-browser` | off | Don't automatically open a browser window. |
| `--reports-dir DIR` | current directory | Where to look for `*.report.html` reports. |

## `mockymock export`

```bash
mockymock export <program.cbl> --cut <program.cut> [options]
```

Writes the instrumented (mocked) source to a file, adjusted for a real
fixed-format (z/OS) COBOL compile instead of GnuCOBOL -- validates that
the computational core compiles cleanly on the target mainframe compiler.
No Docker needed. Includes a disclaimer header noting this is a mock-only
build (every boundary is mocked or fails loudly; no real I/O executes).

| Option | Default | Description |
|---|---|---|
| `program` (positional) | required | The `.cbl` source file. |
| `--cut PATH` | required | Defines which boundaries get mocked into the export. |
| `-o`, `--output PATH` | `<program-stem>.mainframe.cbl` | Where to write the exported source. |
| `--copybook-path DIR` (repeatable) | none | Same meaning as `generate --copybook-path`. |
| `--case NAME` (repeatable) | all cases | Include only the named `TESTCASE`(s)' mocks. Unions with `--tag`. |
| `--tag TAG` (repeatable) | all cases | Include only tagged `TESTCASE`s' mocks. Unions with `--case`. |

A line past column 72 is fitted automatically where it can be: a long generated
`DISPLAY` splits into `WITH NO ADVANCING` fragments, and a long quoted literal
(a `MOVE` restoring a wide `VALUE` clause, a `.cut` MOCK body's own statement)
splits across fixed-format continuation lines with its content unchanged. Only a
line neither rewrite can fit -- one with no literal to split, two literals, or
non-literal text that alone overflows -- makes `export` refuse rather than write
an invalid fixed-format file.

## `mockymock analyze`

```bash
mockymock analyze [cobol-parser-args...]
```

A pass-through to the underlying cobol-parser CLI's own analysis
subcommands (`dead-code`, `program-flow`, `io-sequence`, `move-type-check`,
`linkage-check`, `language-env`, `ims-dli`, `analyze`). Everything after
`mockymock analyze` is forwarded verbatim -- those flags belong to
cobol-parser, not mockymock.

```bash
mockymock analyze dead-code ORDRPROC.cbl --compact
mockymock analyze program-flow ORDRPROC.cbl
```

## `mockymock report`

```bash
mockymock report [PROGRAM.cbl] [--cut PROGRAM.cut] [-o PROGRAM.report.html]
    [--json PATH] [--execute] [--mutate]
    [--run-json PATH] [--coverage-json PATH] [--mutation-json PATH]
    [--journal PATH] [--scenarios happy|branches|all|none] [--seed N]
    [--timeout S] [--mutation-threshold PCT] [--copybook-path DIR ...]
```

One self-contained HTML page (plus JSON with `--json`) for a program and
its suite: eleven steps (environment, understand, rules, inventory, lint,
scenarios, run, coverage, mutation, dialect, verdict), a verification
level per test case (L0 static, L1 executed, L2 strong, L3
dialect-checked), assertion labels (INTENT / CHARACTERIZATION /
unlabelled), and findings ranked by severity.

| Option | Default | Description |
|---|---|---|
| `-o`, `--output` | `<program>.report.html` | HTML path. |
| `--json` | none | Also write the report as JSON. |
| `--execute` | off | Run the suite with coverage now (Docker). |
| `--mutate` | off | Run mutation testing now (Docker, slower). |
| `--run-json` / `--coverage-json` / `--mutation-json` | none | Reuse results an earlier `run --json-report` / `run --coverage-json` / `mutate --json-report` wrote, instead of re-running. |
| `--journal` | `<cut>.journal.jsonl` if present | The assistant's step journal (see `mockymock journal`). |
| `--scenarios` | `branches` | How to measure reachable branch arms; `none` skips the fixture step. |
| `--seed` | none | Seed for that fixture generation. |
| `--timeout` | `run`'s own | Per-run timeout passed to `run`. |
| `--mutation-threshold` | `80` | Mutation score (percent) a suite needs for its cases to reach L2. |
| `--copybook-path` | config / defaults | As everywhere else. |

Exits 1 when a test failed or the suite is refused by the static gate,
else 0. Without `--execute`/`--run-json`, nothing is claimed beyond L0.

## `mockymock journal`

```bash
mockymock journal (--cut PROGRAM.cut | --file PATH) --step NAME --summary TEXT
    [--status ok|warn|fail|skipped|info] [--command TEXT] [--decision TEXT]
```

Appends one JSON line to the suite's journal (`<cut stem>.journal.jsonl`
next to the `.cut`, or `--file`), which `mockymock report` shows as a
timeline: what the assistant did at each step and why.

## `mockymock skills install`

```bash
mockymock skills install [--project] [--force] [--skill NAME ...] [--target claude|copilot|all]
```

Installs the packaged skills -- this one, `cobol-analysis` and
`cobol-test` -- so a Claude Code or GitHub Copilot session picks them up.
They are plain Agent Skills, so the files are the same for both; only the
directory differs. `--target claude` (default) writes
`~/.claude/skills/<name>`; `--target copilot` writes
`~/.copilot/skills/<name>`; `--target all` writes both. Pass `--project`
to install into the current directory instead (`./.claude/skills/<name>`,
or `./.github/skills/<name>` for Copilot), so a team can commit them for
shared use. `--skill NAME`
(repeatable) installs only the named ones. Refuses to overwrite any
existing install (writing nothing) unless `--force` is given.

## `mockymock skills plugin`

```bash
mockymock skills plugin [DIRECTORY] [--force]
```

Writes the `cobol-testing` plugin (all three skills) as a local plugin
marketplace, default `~/.mockymock/claude-plugin`, and prints the two
Claude Code commands that install it (`/plugin marketplace add <dir>`,
`/plugin install cobol-testing@mocky-mock-local`). For a pip install with
no clone and no GitHub access. `--force` replaces an earlier export
(re-run it after upgrading mockymock); a non-empty directory that is not
an earlier export is always refused.

## `mockymock skills mode`

```bash
mockymock skills mode [--set MODE] [--json]
```

Shows which AI assistant mode this project puts you in -- `hands-on`,
`guided` (the default), or `hands-off` -- where that came from (a config
file, or the built-in default), and the contract for it. Run it once at
the start of a session; `mockymock doctor` reports the same mode on its
`AI assistant mode` line.

`--set MODE` persists the mode as `ai_mode` in the project's
`mockymock.toml`, creating that file if there isn't one. A project
configured through `pyproject.toml`'s `[tool.mockymock]` gets a refusal
naming the one line to add there instead -- a `mockymock.toml` written
beside it would shadow that table wholesale. `--json` prints the active
mode plus every mode's contract.

`reference/modes.md` is what the modes actually mean.

## Options quick-reference table

| Subcommand | Needs Docker? | Key options |
|---|---|---|
| `setup` | yes | `--rebuild` |
| `init` | yes (degrades) | `-o`, `--seed`, `--scenarios`, `--copybook-path`, `--force` |
| `generate` | no | `-o`, `--fill`, `--copybook-path`, `--with-data`, `--fixtures`, `--seed`, `--scenarios`, `--rows`, `--placeholder` |
| `fixtures` | no | `--scenarios`, `--seed`, `--rows`, `--copybook-path` |
| `run` | yes | `--cut`, `--junit-xml`, `--json-report`, `--case`, `--tag`, `--copybook-path`, `--keep-sandbox`, `--verbose`, `--coverage[-out\|-json\|-fail-under]`, `--trace[-json]`, `--timeout`, `--record-expectations` |
| `debug` | yes | `--cut`, `--case`, `--copybook-path`, `--dap-stdio` |
| `lint` | no | `--cut`, `--copybook-path` |
| `mutate` | yes (unless `--list`) | `--cut`, `--copybook-path`, `--list`, `--timeout`, `--json-report`, `--fail-under` |
| `collect` | no | `--cut`, `--json`, `--boundaries`, `--copybook-path` |
| `explain` | no | `--list`, `--json` |
| `dashboard` | read-only probe | `--port`, `--no-browser`, `--reports-dir` |
| `doctor` | read-only probe | `--json` |
| `export` | no | `--cut`, `-o`, `--copybook-path`, `--case`, `--tag` |
| `analyze` | no | *(forwarded to cobol-parser)* |
| `report` | only with `--execute`/`--mutate` | `--cut`, `-o`, `--json`, `--execute`, `--mutate`, `--run-json`, `--coverage-json`, `--mutation-json`, `--journal`, `--scenarios`, `--seed`, `--timeout`, `--mutation-threshold`, `--copybook-path` |
| `journal` | no | `--cut`, `--file`, `--step`, `--summary`, `--status`, `--command`, `--decision` |
| `skills install` | no | `--project`, `--force`, `--skill` |
| `skills plugin` | no | `--force` |
| `skills mode` | no | `--set`, `--json` |
