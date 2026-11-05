---
name: mockymock-setup
description: Use when someone wants a COBOL repository or VS Code workspace set up for mockymock and its VS Code extension ("set up mockymock here", "configure the mockymock extension", "where do my copybooks go", "the extension can't find my copybooks", "get this repo ready for COBOL unit tests"). Inspects the repo, asks the developer for what it cannot work out (copybook folders, source and test folders, toolchain, AI mode), writes cobol.yml and .vscode/settings.json, and proves the setup by resolving every program's copybooks.
---

<!--
Maintainer note: reference/settings.md lists every setting this skill may
write. Keep it in step with:
  - mockymock/cli/config.py `_KNOWN_KEYS` (the mockymock: / mockymock.toml keys)
  - mockymock/cli/ai_mode.py `MODES`
  - the MOCKYMOCK_* environment variables the CLI reads
  - mocky-mock-vscode's package.json `contributes.configuration`
    (every `mockymock.*` setting and the `mockymock.toolchain` enum)
  - cobol-parser's docs/project-config.md (the `project:` keys)
tests/unit/test_mockymock_setup_skill.py pins the first three; the
extension's settings live in another repository, so check them by hand
when its package.json changes.
-->

# Setting up a repository for mockymock

The goal: the developer opens the repo in VS Code, clicks **New Test Suite**
on any program, and it works. No `UNRESOLVED_COPYBOOK`, suites land where
they expect, and the toolchain is ready to run them.

Almost everything lives in **one file, `cobol.yml` at the repository
root**. The `mockymock` CLI, the mockymock VS Code extension (through the
CLI it spawns), `cobol-parser` and the COBOL Analyzer extension all read it,
so one answer to "where are the copybooks" serves every tool, in the editor,
in a terminal and in CI. `.vscode/settings.json` only holds what is about
this editor (toolchain, lint on save, parallel runs). Do not put copybook
folders in both: `mockymock.copybookPaths` **replaces** the `cobol.yml`
list rather than adding to it (`reference/settings.md`, "How the copybook
lists combine").

## The rules

1. **Detect first, then ask.** Never ask a question the repository or the
   machine already answers: the OS, `gcc`, Docker and the extension are
   all things you can check. Ask about what you found ("I found copybooks
   in `CPY/` and `common/copy/`; use both?"), not open-ended ("where are
   your copybooks?").
2. **Few questions, each one worth asking.** A developer who asked for a
   setup wants it done, and ten questions in a row reads like a form.
   Aim for three to five: only the topics in step 2 that the inventory
   left open, each with your proposed answer so "yes" is a full reply.
   Everything that has a sensible default (AI mode, the optional editor
   settings, a seed, extension recommendations, `.gitignore`) is not a
   question: put it in the plan you show before writing, as "I'll also
   ... -- say if you want any of it different", and accept silence as yes.
3. **Show the plan before writing it, and never overwrite.** Merge into an
   existing `cobol.yml`, `mockymock.toml` or `.vscode/settings.json`,
   keeping every key and comment you did not change. If a key already has
   a different value, ask which one wins. Never rename, move or edit the
   developer's source, copybooks or suites to make them resolve: aliases
   and search paths exist so the export stays as it came from the
   mainframe.
4. **Write paths relative** to the file that holds them (`cobol.yml` paths
   resolve against `cobol.yml`'s folder), so the setup works on every
   clone. Absolute paths only for something outside the repository, and
   then prefer `~/...` or `${VAR}`.
5. **Nothing outside the repository** without a yes: no installs, no
   `docker` commands, no user-level settings, no git commits.
6. **It has to work outside the editor too.** The same suites run from a
   terminal, from CI and from an AI assistant, none of which read
   `.vscode/settings.json`. So the copybook list belongs in a config file
   the CLI reads (`cobol.yml`, or `mockymock.toml`), never only in editor
   settings.
7. **Prove it.** The job ends with the check in step 5 passing from a
   plain terminal, or with a list of exactly what still fails and why.

`mockymock skills mode` changes how often you check in on test-writing
work; this setup always asks, because every answer is a fact about the
developer's repository that you cannot know.

## Step 1: look around (read only)

From the repository root (`git rev-parse --show-toplevel`, else the open
folder):

```bash
mockymock --version && mockymock doctor          # CLI, toolchain, config file in effect, AI mode
ls cobol.yml cobol.yaml mockymock.toml zapp.yml zapp.yaml .vscode/settings.json 2>/dev/null
grep -n "tool.mockymock" pyproject.toml 2>/dev/null
```

**No `mockymock` on PATH?** The VS Code extension bundles one. It is
`<extensions dir>/lanparty.mockymock-vscode-<version>/bin/mockymock`
(`mockymock.exe` on Windows), where the extensions dir is
`~/.vscode/extensions` (`%USERPROFILE%\.vscode\extensions` on Windows,
`~/.vscode-server/extensions` over Remote-SSH/WSL). Use that path for the
commands below. If neither exists, tell the developer to install the
extension (or `pip install mocky-mock`) and stop; installing is their call.

Then inventory the COBOL. Skip `.git`, `node_modules`, `.mockymock`,
build output and anything `.gitignore`d:

- **Programs**: files ending `.cbl`, `.cob`, `.cobol` (any case) that
  contain `PROGRAM-ID`. Note the folders they sit in.
- **Copybook folders**: folders holding `.cpy`, `.copy`, `.cblcpy`, `.dcl`,
  `.dclgen`, `.inc` files, or extension-less members, or named like
  `copybooks`, `copybook`, `copylib`, `copy`, `cpy`, `dclgen`, `include`.
- **Members the programs need**: the names after `COPY` and
  `EXEC SQL INCLUDE` in the programs. Skip `SQLCA` (mockymock
  generates it) and the CICS members `DFHAID`/`DFHBMSCA` (shipped with
  mockymock); `DFHEIBLK`/`DFHCOMMAREA` are not copybooks.
- **Existing suites**: `*.cut` files, and where they live relative to the
  programs.
- **Existing settings**: `cobolAnalyzer.copybookPaths` or `mockymock.*` in
  `.vscode/settings.json` or a `*.code-workspace` file, and the `local`
  library locations in a `zapp.yml`. Each is a copybook list the developer
  already gave once; reuse it.

Tell the developer what you found in a few lines before the first
question, e.g.:

```
Found 42 programs (src/batch, src/online), 310 copybooks in copylib/ and
db2/dclgen/, no cobol.yml, no suites yet. mockymock 0.15.0 (bundled with
the VS Code extension), GnuCOBOL bundled, gcc found, Docker not running.
I'll ask about 4 things, then write cobol.yml and .vscode/settings.json.
```

## Step 2: ask

Only the topics the inventory left open, in this order. Each one names the
setting it fills; `reference/settings.md` has every setting's exact shape.
Topics 1-4 are questions when the repository leaves them open; 5-7 are
defaults you list in the plan (step 3) and change only if the developer
says so.

1. **Copybook folders** -> `project.copybook_path` in `cobol.yml`.
   Propose every folder that holds a member the programs use, in search
   order (first match wins when two folders hold the same member: ask
   which comes first). In the same question, ask whether any copybooks
   live outside the repository (a shared copylib checkout, a network
   drive) -- those are the ones you cannot find. Members you could not
   find anywhere are the strongest hint; name them.
   If member files have odd names (`m0042.txt` holding `GTTLBI0A`), find
   the file whose `01` level or content matches the member, and propose a
   `mockymock.copybook_aliases` entry for it; differently cased files and
   the extensions above are matched automatically.

   **When the config file belongs to someone else** (a build team, a
   shared template): adding one entry to `copybook_path` leaves every
   setting they made as it was, so ask exactly that ("may I add
   `shared/copy` to `project.copybook_path`? Nothing else changes"), not
   "may I change cobol.yml". If the answer is still no, write the full
   list as `copybook_path` in a `mockymock.toml` beside it (it layers over
   `cobol.yml` for mockymock only) and say that cobol-parser will not see
   the extra folder. Do not fall back to editor-only settings (rule 6).
2. **Where the programs live** -> `mockymock.source_root`. Only needed
   when the programs are not under `src/` (or the repository root).
3. **Where suites go** -> `mockymock.test_root`. Default `tests/`,
   mirroring the source folders (`src/pay/PAY.cbl` -> `tests/pay/PAY.cut`).
   Existing suites beside their programs keep working either way; ask
   only whether new ones should go to `tests/` or somewhere else.
4. **How tests run** -> `mockymock.toolchain` in `.vscode/settings.json`.
   Not a question when the machine answers it: check the OS, `gcc` and
   Docker yourself and propose. Leave `auto` unless they have a reason: `auto` uses the GnuCOBOL bundled
   with the extension on Linux and Windows (needs `gcc` on Linux) and Docker
   elsewhere (macOS). `docker` runs every test in a locked-down container.
   For the terminal and CI, the same choice is the `MOCKYMOCK_TOOLCHAIN`
   and `MOCKYMOCK_GNUCOBOL_HOME` environment variables; tell them, do not
   set them.
5. **AI assistant mode** -> `mockymock.ai_mode`: `hands-on`, `guided`
   (default) or `hands-off` (the `mockymock` skill's `reference/modes.md`).
   A default in the plan, unless the developer already said how hands-on
   they want an assistant to be.
6. **Optional editor settings**, one line in the plan: lint `.cut` files on
   save (`mockymock.lintOnSave`, on), one test case per paragraph in New
   Test Suite (`mockymock.newTestSuite.casePerParagraph`, off), runs at once
   (`mockymock.maxParallelRuns`, 1). Write nothing for a default.
7. **Shared seed** -> `project.seed`, and `.vscode/extensions.json` /
   `.gitignore` (step 3): one line each in the plan, off unless the
   developer wants them.

Things you do not ask about: `mockymock.executablePath` (leave it empty so
the bundled CLI matches the extension, unless they already use a
different build), and anything about the LegacyLens `mockymock runner`,
which is not part of an editor setup (see the end of
`reference/settings.md` if they ask).

## Step 3: write

Show the plan in one message: the files with their new content, then the
defaults you are keeping, e.g.

```
I'll write cobol.yml (below) and set mockymock.toolchain to auto. Keeping
the defaults: AI mode guided, lint on save, no shared seed. I'll also add
.mockymock/ to .gitignore. Say if you want any of that different.
```

That one message is also the last question: the seed, the extension
recommendation and `.gitignore` are lines in it, not questions of their
own. A typical result:

```yaml
# cobol.yml -- read by mockymock, cobol-parser and both VS Code extensions
version: 1

project:
  copybook_path:
    - copylib
    - db2/dclgen

mockymock:
  source_root: src
  test_root: tests
  ai_mode: guided
```

```jsonc
// .vscode/settings.json (merged into the existing file)
{
  "mockymock.toolchain": "auto"
}
```

- **Merging into an existing `cobol.yml`**: add keys under the existing
  `project:` / `mockymock:` sections; keep `version`, `data:`, `lint:`,
  `analyzer:` and comments as they are. The file is a strict YAML subset:
  no tabs, no anchors, no `|` blocks, no duplicate keys, and only the keys
  in `reference/settings.md` (an unknown key is an error, not ignored).
- **The repository already uses `mockymock.toml`** (or
  `[tool.mockymock]`): ask whether to move it into `cobol.yml` or keep it.
  If kept, write the mockymock keys there; it overrides `cobol.yml` key by
  key. Never leave the same key with two different values.
- **`.vscode/settings.json` already sets `mockymock.copybookPaths` or
  `cobolAnalyzer.copybookPaths`** to the same list you put in `cobol.yml`:
  offer to remove it, so there is one place to maintain. Keep it if they
  prefer; the result is the same (`reference/settings.md`).
- **Recommend the extensions** in `.vscode/extensions.json` so teammates get
  a prompt (`"recommendations": ["lanparty.mockymock-vscode"]`), only if
  the developer wants it.
- `.mockymock/` holds reports and run artifacts; offer to add it to
  `.gitignore` if it is not there.

## Step 4: toolchain

A terminal `mockymock doctor` checks Docker unless `MOCKYMOCK_GNUCOBOL_HOME`
is set, so on a machine that will use the extension's bundled GnuCOBOL its
Docker lines failing is expected. What the editor will use:

- **Bundled GnuCOBOL, no `gcc`** (Linux): say they need a C compiler
  (`sudo apt install gcc`, or their distribution's equivalent).
- **Docker chosen or needed, daemon down**: say so. In VS Code the status
  bar item starts Docker Desktop for them; `mockymock setup` builds the
  image and starts the container from a terminal. Ask before running
  `mockymock setup` yourself: it builds a Docker image.
- In VS Code, **mockymock: Check Setup (CLI and Docker)** runs the same
  checks and puts the result in the status bar (`✓ mockymock` when ready).

Creating and linting suites need neither, so a toolchain problem does not
block step 5.

## Step 5: prove it

Run from the repository root, so the CLI picks up the new `cobol.yml`:

```bash
mockymock doctor                       # [ OK] config file -> the cobol.yml you wrote
mockymock fixtures src/pay/PAY.cbl     # per program: exit 0, or a refusal naming what is missing
mockymock suites src/pay/PAY.cbl       # where New Test Suite will write its suite
```

Run `fixtures` on every program (up to about 50; beyond that, one per
folder plus every program that uses a member you are unsure of) and
collect the failures:

- **`UNRESOLVED_COPYBOOK` naming member `X`**: find the file
  (`find . -iname 'X*'`, and ask about folders outside the repository),
  add its folder to `copybook_path` or an alias, re-run. A member nobody
  can find is a finding for the developer, not something to guess around.
- **A parse error**: not a setup problem. Note the program and move on;
  the `cobol-analysis` skill can explain it.
- **`suites` pointing somewhere unexpected**: fix `test_root` /
  `source_root`, or the program needs a `PROGRAM` line in its suite.

Finish with a short report:

```
mockymock is set up.
  cobol.yml               copybooks: copylib, db2/dclgen; programs: src; suites: tests
  .vscode/settings.json   toolchain: auto
  copybooks               42 of 42 programs resolve every COPY
  toolchain               bundled GnuCOBOL 3.2 ready (gcc 13)
Next: open src/pay/PAY.cbl and click the beaker (New Test Suite), or ask
me to test a program (cobol-test skill).
```

If anything is left open (a missing member, Docker not installed), list
it with the one thing the developer has to do about it.
