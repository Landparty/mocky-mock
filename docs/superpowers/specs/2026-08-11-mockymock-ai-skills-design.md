# mockymock AI skills — design

**Date:** 2026-08-11
**Status:** approved for planning

## Problem

mockymock's `.cut` DSL and CLI are documented (README, `docs/options-reference.md`,
`.okf/`), but nothing packages that knowledge for an AI coding assistant to
use directly. Two distinct audiences want this:

1. **End users** — COBOL developers who install mockymock (`uv tool install
   git+https://...`) and want Claude Code to help write `.cut` test files,
   run them, and interpret refusals/failures.
2. **mockymock contributors** — people changing mockymock's own source, who
   want Claude Code oriented into the `.okf/` knowledge bundle and its
   load-bearing gotchas before touching the splicer/DSL/CLI internals.

These have different audiences, different distribution needs, and different
content, so they are two separate Claude Code skills.

## 1. Contributor skill (repo-local, no packaging)

**Location:** `.claude/skills/mockymock-dev/SKILL.md`, committed to this
repo. Claude Code auto-discovers project-scoped skills, so anyone working in
a checkout of `mocky-mock` picks it up automatically — no install step.

**Content:** a thin router, not a duplicate of `.okf/`. It should:

- Point at `.okf/index.md` as the first read for any non-trivial change.
- Summarize the module map in one screen: DSL → analysis → splicer →
  runtime → report, entry via `cli/main.py`.
- Name the load-bearing gotchas that recur across `.okf/cli.md` and sibling
  docs, so Claude doesn't have to rediscover them by reading every module:
  - Deferred imports in `cli/main.py`'s `_cmd_*` bodies — nothing in
    `build_parser()` may import a `_cmd_*` body's dependencies.
  - `annotate_nested_sites` must run before anything inspects
    `surface.boundary_sites` for nested spliceability.
  - `transform_data_division_exec` is called twice in `_cmd_run`
    (precheck, discarded; then for real after splicing) — collapsing this
    into one call silently breaks splice-target alignment.
  - Refusal gates are cumulative within a gate, fail-fast between gates.
  - `tests/integration/` needs a reachable Docker daemon and is
    auto-skipped otherwise; `tests/unit` does not.
- Link to `.okf/testing.md` for how to run the two test tiers.

No packaging, no CLI changes — just a file to write and commit as part of
this work.

## 2. End-user skill (packaged, installed via CLI)

### Package layout

```
mockymock/cli/skills/mockymock/
├── SKILL.md                  # concise: when to use, core workflow
├── reference/
│   ├── cut-dsl.md            # .cut directive reference (MOCK/EXPECT/VERIFY/
│   │                         #   PROVIDER/BEFORE-EACH/FILE-STATUS/ROWS)
│   └── cli-flags.md          # per-subcommand flag reference
```

Nested under `mockymock/cli/` (an existing, already-discovered package)
rather than a new top-level `mockymock/skills/` — setuptools'
`[tool.setuptools.package-data]` only applies glob patterns under a
package it actually discovered (one with `__init__.py`), and a new
directory with no `__init__.py` of its own wouldn't be found by
`packages.find`'s `include = ["mockymock*"]`. This mirrors how the
Dockerfile (`mockymock/runtime/docker/`) and dashboard assets
(`mockymock/web/static/`) are packaged: a plain data subdirectory nested
under a real package.

`SKILL.md` stays short (frontmatter + a task-oriented workflow: scaffold →
fill in mocks → run → read refusals/failures → lint before Docker if
iterating fast). The two reference files are loaded on demand
(progressive disclosure) rather than inlined, mirroring how the
`docx`/`pdf` Anthropic skills structure large reference material.

Content is adapted from `docs/options-reference.md` and the README's
worked example, curated for agent consumption (task-first, not an
exhaustive human-facing table) rather than copied verbatim.

**Known tradeoff:** this is a fourth hand-maintained description of the
same DSL/CLI surface, alongside README, `docs/options-reference.md`, and
`.okf/dsl.md`/`.okf/cli.md`. The repo already accepts this pattern for the
first three. `SKILL.md`'s header will carry a one-line comment flagging
that a DSL directive or CLI flag change should also touch the skill's
reference files.

### Packaging

Add to `pyproject.toml`'s `[tool.setuptools.package-data]`:

```toml
"mockymock.cli" = ["skills/mockymock/SKILL.md", "skills/mockymock/reference/*.md"]
```

Same pattern already used for the Dockerfile and dashboard static assets —
required because a bare `uv tool install` has no sibling checkout to fall
back on.

### CLI subcommand

```
mockymock skills install [--project] [--force]
```

New `mockymock/cli/skills_cmd.py`, wired into `cli/main.py` via the
existing `set_defaults(func=...)` dispatch pattern, deferred-imported like
every other `_cmd_*`.

- **Default target:** `~/.claude/skills/mockymock` (global — the skill's
  content isn't project-specific; a user testing multiple COBOL repos
  shouldn't have to reinstall per repo).
- **`--project`:** write to `./.claude/skills/mockymock` instead, so a team
  can commit it for shared use.
- **`--force`:** required to overwrite an existing target; without it, the
  command refuses with `mockymock skills install: <path> already exists;
  use --force to overwrite` and exits 1 — fail-closed, consistent with
  mockymock's stated design goal, and it won't silently clobber a user's
  local edits to the installed copy.
- Pure file copy (`importlib.resources`/`Path(__file__)`-relative, same
  technique as the Dockerfile/dashboard asset resolution) — no Docker, no
  parsing. Same "always available" tier as `lint`/`collect`.
- On success, prints the destination path and a one-line note to restart
  Claude Code / start a new session to pick it up.
- No Docker dependency: `build_parser()` must not import anything this
  subcommand needs at parse-build time, same rule as every other
  subcommand (see `.okf/cli.md`'s Gotchas section).

### Docs to update

- README: new `## AI assistant skill` section near Installation,
  describing `mockymock skills install`.
- `docs/options-reference.md`: new `skills` entry in the subcommand list
  and table (now twelve subcommands).
- `.okf/cli.md`: new `## mockymock skills` subsection documenting the flow,
  plus a `log.md` entry.

### Testing

Unit test (mirroring `tests/unit/test_cli_dashboard.py`'s style) covering:

- `skills install` (no flags) writes the expected files under a faked
  `~` (patch `Path.home()` or use `tmp_path` + monkeypatched env).
- `--project` writes under `./.claude/skills/mockymock` relative to cwd.
- Refuses without `--force` when the target already exists; succeeds and
  overwrites with `--force`.
- `build_parser()` importing `skills_cmd`'s dependencies is *not* triggered
  at parse-build time (same guard style as the existing dashboard test).

## Out of scope

- No `mockymock skills uninstall`/`list` — a single `install` command is
  enough for v1; removal is `rm -rf` on a path the install command already
  printed.
- No auto-install on first `run`/`generate` — writing outside the project
  directory (global install) should be an explicit, deliberate action.
- No CI/marketplace distribution (e.g. a Claude Code plugin manifest) —
  the packaged-CLI-install approach was chosen specifically to piggyback on
  the existing `uv tool install` distribution path.
