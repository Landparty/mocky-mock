# Every setting the setup may write

Four places, in the order to prefer them. Precedence everywhere: an
explicit CLI flag (or a VS Code setting the extension turns into one) beats
a config file, which beats the built-in default.

## 1. `cobol.yml` at the repository root

Found by walking up from the current folder (from the `.cut` file's folder
when the extension runs the CLI); `cobol.yml` before `cobol.yaml`, nearest
wins. Paths resolve against the file's own folder; `~`, `$VAR` and `${VAR}`
are expanded. Unknown keys are an **error**, not ignored. Full schema:
`docs/project-config.md` in the cobol-parser repository.

### `version`

`1`. Any other value is refused.

### `project:` (shared with cobol-parser and the COBOL Analyzer extension)

mockymock reads two of these keys; the others are cobol-parser's and are
safe to keep.

| Key | Shape | mockymock uses it for |
|---|---|---|
| `copybook_path` | list of folders (or one string) | Where `COPY` and `EXEC SQL INCLUDE` members are searched, in order. Fills `--copybook-path`. |
| `seed` | integer | Seed for generated test data, so `generate`/`fixtures` give the same values on every machine. Fills `--seed`. |

cobol-parser-only keys you may meet: `callee_path`, `proc_path`,
`source_format` (`auto`/`fixed`/`free`), `debug_lines`, `dialect`,
`error_recovery`, `extensions`, `define`. Sections `data:`, `lint:` and
`analyzer:` belong to the other tools; leave them alone.

### `mockymock:` (this CLI's own; overrides `project:`)

| Key | Shape | Default | Meaning |
|---|---|---|---|
| `test_root` | folder | `tests` under the project root | Where new suites go and where `mockymock run`/`lint` with no arguments look for `.cut` files. New suites mirror the program's folder under the source root. |
| `source_root` | folder | `src` if it exists, else the project root | Where the programs live, for that mirroring. |
| `ai_mode` | `hands-on` \| `guided` \| `hands-off` | `guided` | How often an AI assistant checks in while building a suite (`mockymock skills mode`). |
| `copybook_path` | list of folders | from `project:` | Same as `project.copybook_path`, for mockymock only. Prefer `project:`, which every tool reads. |
| `seed` | integer | from `project:` | Same as `project.seed`, for mockymock only. |
| `copybook_aliases` | mapping `MEMBER: file` | none | A member whose file name the search can never match (`GTTLBI0A: export/m0042.txt`). The file must exist; relative to the config file. |
| `copybook_extensions` | list of extensions | `.cpy .cbl .cob .copy .cblcpy .dcl .dclgen .inc .txt` and none | Which differently named files in a copybook folder are matched to a member automatically, in any case (`gttlbi0a.copy` -> `GTTLBI0A`). `[]` turns the automatic matching off. |

Not configurable, on purpose: `--timeout`, and every per-run choice
(`--case`, `--tag`, report paths).

Without any copybook setting, mockymock still looks in folders named
`copybooks`, `copybook`, `copylib`, `copy`, `cpy`, `dclgen` or `include`
under the program's folder and beside it. A repository laid out that way
needs no `copybook_path` for mockymock, but the other tools do not have
that default, so writing it down in `cobol.yml` is still worth it.

## 2. `mockymock.toml` (or `[tool.mockymock]` in `pyproject.toml`)

The same keys as the `mockymock:` section, at the top level, in TOML. Found
by its own upward walk and layered over `cobol.yml` key by key. Use it only
when the repository already has one; otherwise `cobol.yml` is the one
place.

```toml
copybook_path = ["copylib"]
test_root = "tests"
ai_mode = "guided"
```

## 3. `.vscode/settings.json` (the mockymock VS Code extension)

Extension id `lanparty.mockymock-vscode`. All defaults work; write only
what the developer chose.

| Setting | Type | Default | Meaning |
|---|---|---|---|
| `mockymock.copybookPaths` | array of folders | unset | Copybook folders for this editor. **Replaces** the config file's `copybook_path` (it is passed as `--copybook-path`). `~`, `${userHome}`, `${workspaceFolder}`, `${workspaceFolder:name}` expanded; relative to the workspace folder. `[]` turns off everything the extension adds (see below). |
| `mockymock.toolchain` | `auto` \| `bundled` \| `docker` | `auto` | Where tests compile and run. `auto`: the GnuCOBOL bundled with the extension when there is one for the platform (Linux, Windows), otherwise Docker. `bundled`: always the bundled one (Docker on a platform without it). `docker`: always the locked-down container. |
| `mockymock.lintOnSave` | boolean | `true` | Lint `.cut` files on open and save. Offline, no Docker. |
| `mockymock.newTestSuite.casePerParagraph` | boolean | `false` | **New Test Suite** writes one case per paragraph that touches a boundary instead of one per scenario through the entry point. |
| `mockymock.maxParallelRuns` | number | `1` | `.cut` files run at once. Window-scoped (user settings, not per folder). |
| `mockymock.executablePath` | string | `""` | A `mockymock` CLI to use instead of the bundled one. Leave empty unless the developer already uses another build (e.g. `.venv/bin/mockymock`). |

### How the copybook lists combine

The extension finds copybook folders in up to four places and passes them
to the CLI like this:

1. `mockymock.copybookPaths`, when set, goes on `--copybook-path` and
   **replaces** the config file's list.
2. When it is unset, `cobolAnalyzer.copybookPaths` (the COBOL Analyzer
   extension's setting) and the `local` library locations of a
   `zapp.yml`/`zapp.yaml` at the workspace root go on
   `--extra-copybook-path`, which **adds** them after the config file's
   list.
3. `"mockymock.copybookPaths": []` passes nothing from the extension:
   only the config file decides.

So the clean setup is `cobol.yml` alone. If the repository keeps a
`zapp.yml` (IBM Z Open Editor), its locations are added on top
automatically; there is no need to repeat them anywhere.

## 4. Environment variables (terminal and CI)

The extension sets these itself for the CLI it spawns. Outside VS Code they
are the developer's choice; tell them, do not set them.

| Variable | Meaning |
|---|---|
| `MOCKYMOCK_TOOLCHAIN` | `auto` \| `docker` \| `native`. `native` compiles with the GnuCOBOL tree in `MOCKYMOCK_GNUCOBOL_HOME`. |
| `MOCKYMOCK_GNUCOBOL_HOME` | A GnuCOBOL tree (`bin/`, `lib/`, `include/`, `share/gnucobol/{config,copy}`), e.g. the extension's own `<extension dir>/gnucobol`. Unset: Docker. |
| `MOCKYMOCK_GCOV` | The `gcov` to use for coverage with the native toolchain, when the one on PATH does not match the compiler. |
| `MOCKYMOCK_CURRENT_DATE` | The clock test programs see (`FUNCTION CURRENT-DATE`, `ACCEPT ... FROM DATE/TIME`). Fixed at `2026/01/15 10:30:00.00` by default so recorded expectations stay stable; `real` uses the wall clock. |

## Not part of an editor setup: the LegacyLens runner

`mockymock runner` claims test jobs from a LegacyLens backend. It takes
flags, not config: `--url` (default `$LEGACYLENS_URL`), `--token-env`
(the variable holding the runner token, default `RUNNER_TOKEN`), `--name`,
`--work-dir`, `--poll-interval`, `--suite-timeout`, `--log-file`. Set it up
only when asked, and never write the token to a file in the repository.
