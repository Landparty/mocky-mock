---
type: Runbook
title: Publishing
description: mockymock (AGPL-3.0-or-later) publishes a plain (source-visible) sdist+wheel to PyPI on every release-please release, mirroring cobol-parser's PyPI pipeline; the Nuitka executable path for mocky-mock-vscode is separate and unaffected.
tags: [ci, release, publishing, pypi]
timestamp: 2026-11-13T19:00:00Z
---

# Overview

`mockymock` is free software under **AGPL-3.0-or-later**: `LICENSE` is
the GNU AGPL v3 text and `pyproject.toml` declares
`license = "AGPL-3.0-or-later"` (PEP 639 SPDX form, `license-files =
["LICENSE"]`). It was relicensed from a proprietary EULA on 2026-10-04 to
match `cobol-parser`, which it depends on. As of 2026-08-18 its package is
published to PyPI as `mockymock` — reversing the 2026-08-14
"no longer independently distributed" decision this concept used to
describe. `cobol-parser` was published to PyPI first, originally as
closed-source Cython wheels (that repo's
`docs/superpowers/specs/2026-08-14-pypi-closed-source-release-design.md`,
which that repo's `CLAUDE.md` now lists as superseded); on 2026-10-03 it was relicensed
**AGPL-3.0-or-later**, and its wheels now ship every module as plain `.py`
with only three hot-path accelerators compiled. mockymock's own release
pipeline mirrors that repo's release-please → PyPI shape, minus the
cibuildwheel matrix: mockymock is pure Python with no compiled extension
(no `.pyx`/`build_ext` anywhere in this repo), so one `py3-none-any` wheel
plus an sdist is the whole build.

`release-please.yml`'s jobs, in order:
- `release-please` — cuts the version-bump PR / GitHub Release (unchanged).
- `build` — `python -m build` (sdist + wheel, `ubuntu-latest`, single job,
  no matrix — nothing here needs a per-OS/per-Python native build).
- `publish` — attaches the built dist files to the GitHub Release.
- `publish-pypi` — uploads to PyPI via Trusted Publishing (OIDC, no stored
  token), gated the same way as `build`/`publish` (`releases_created` or a
  manual `workflow_dispatch`, with a `testpypi` rehearsal target mirroring
  cobol-parser's).

The Nuitka executable path is untouched by any of this: the sibling
`mocky-mock-vscode` repo's `build-and-release.yml` (`workflow_dispatch`
only) still checks out this repo at its latest release tag, runs
`scripts/build_executable.sh`, and packages the result into the VS Code
extension's `.vsix`. That pipeline builds from source directly — it does
not consume the PyPI wheel — so the two distribution channels (PyPI wheel
for `pip install`/library use, Nuitka binary for the VS Code extension)
coexist without touching each other. See that repo's own `PUBLISHING.md`.

The PyPI Trusted Publisher registration this file used to list as "not yet
done" has since happened: releases through 0.8.0 are on PyPI. If
`publish-pypi` ever starts failing on OIDC, that registration
(pypi.org → the project's publishing settings → the pending/active
publisher pointing at this repo's `release-please.yml`) is the first thing
to re-check — same requirement cobol-parser's own publish-pypi job notes.

**The version-drift bug this pipeline shipped for three releases
(2026-09-05 audit, finding 1 — fixed in `2a58c6c`).** `e26373b` renamed
`[project].name` from `mockymock` to `mocky-mock`, which broke
release-please's path to `mockymock/__init__.py`: from 0.7.0 onward it
bumped `pyproject.toml` and the tag but silently skipped the
`__version__` string, so the published 0.8.0 wheel reported `--version`
as `0.7.0`. The fix is `release-please-config.json`'s explicit
`packages["."].extra-files` entry (`{"type": "python", "path":
"mockymock/__init__.py"}`) plus the `package-name: mockymock` key; the
invariant that the two agree is pinned by `tests/unit/test_smoke.py`,
which was already there and simply never ran in CI (see
[testing.md](testing.md)'s CI section for why). Any future rename of the
distribution or the import package must re-check that `extra-files` path
in the same commit.

**uv.lock follows the version too (2026-11-13).** release-please's python
strategy never touches `uv.lock`, so 0.17.0 shipped with the lock's
`mockymock` entry still at 0.16.1 and `uv sync --locked` failed every CI
job on main. A `toml` `extra-files` entry now bumps
`$.package[?(@.name.value=='mockymock')].version`, and
`test_smoke.test_uv_lock_records_the_pyproject_version` pins the two
together. Release PRs opened with the default token do not trigger CI, so
the test catches a drift only on the next push after the release.

# Python API

The supported Python surface is `mockymock.api` (its `__all__`, pinned by
`tests/unit/test_public_api.py`), plus `mockymock.__version__` and the
`mockymock` command line. Every other module is internal: `py.typed`
makes them type-check downstream, but they may move or change in any
release. Removing or renaming a name in `mockymock.api` is a breaking
change and goes through a deprecation first.

Modules that moved out of `cli/` in the engine refactor (`cli.checks`,
`cli.mainframe_export` → `engine/`; `cli.config`, `cli.discovery`,
`cli.copybook_aliases`, `cli.ai_mode` → `project/`) keep a forwarding
alias at the old path that warns with `DeprecationWarning`; drop the
aliases in the next minor release after the one that ships the move.

# Gotchas

- **`--onefile-tempdir-spec` trades a re-extraction hazard for a
  multi-second-per-launch tax.** Without it, Nuitka's onefile bootstrap
  unpacks the whole payload into a fresh temp dir on every single launch
  and deletes it on exit — a real cost for the VS Code extension, which
  fires several `mockymock`/`mockymock analyze` invocations per editor
  switch. `scripts/build_executable.sh` pins the spec to
  `{CACHE_DIR}/mockymock/{VERSION}` (with `--product-version` set from
  `mockymock.__version__`) so repeated launches of the *same* build reuse
  the extraction — Nuitka's bootstrap re-extracts automatically if the
  payload at that path doesn't match what's expected, so a stale dir left
  by a different build is not silently reused. Caveat: `mockymock`'s own
  version string does not change when `build-and-release.yml`'s
  "Force-install cobol-parser's latest release" step overrides whatever
  `cobol-parser` the `>=3.1.1,<4` range resolved — two builds a day apart can share the same
  `{VERSION}` path. That's still safe (the hash check catches it), just
  worth knowing if you're ever debugging why a "same version" binary
  behaves differently than expected on a machine with a stale cache dir —
  `rm -rf` the platform cache dir's `mockymock/` subfolder rules it out.

- **Nuitka ignores `[tool.setuptools.package-data]`.** A non-`.py` file
  resolved via `Path(__file__)` can be correctly listed there, appear in a
  built wheel, pass every unit test, and still be missing from the
  released executables the sibling `mocky-mock-vscode` repo now bundles
  into its `.vsix` — the primary artifact for users with no repo access.
  Each such file needs its own `--include-data-files` /
  `--include-data-dir` flag in `scripts/build_executable.sh`. The
  `Dockerfile` and `mockymock/web/static/` are the two current cases; both
  have a CI step in that sibling repo's `build-and-release.yml` that
  exercises them *through the built binary*, which is the only place this
  class of bug is visible.

- `release-please-config.json`'s `packages["."].release-as` is a one-time
  version override, not a permanent pin. Left set after the bootstrap
  release it was written for, every subsequent `release-please` run keeps
  proposing that same fixed version forever — including re-proposing a
  release against a tag that already exists, which is a no-op/broken PR,
  not a new release. Remove the key once the version it names has shipped;
  a genuine one-off override (e.g. to skip a version) belongs in a commit's
  `Release-As: X.Y.Z` trailer instead, which `release-please` only applies
  once, to that commit's own version proposal.
- (Retired here: `build-executables.yml` was deleted with the old
  in-repo Nuitka release jobs -- see `PUBLISHING.md`; the lesson applies to
  any Windows CI step, now chiefly mocky-mock-vscode's
  `build-and-release.yml`.) `build-executables.yml`'s `run:` steps defaulted to `pwsh` on
  `windows-latest`; only `bash`/`sh`-family shells expand `${TOKEN}`-style
  env vars the way Linux/macOS's default `bash` does. Any step that builds
  a shell string from a secret needs an explicit `shell: bash` on every OS,
  not just the ones where it happens to already default to bash — pwsh
  silently treats `${TOKEN}` as an unset variable rather than erroring,
  so the failure surfaces downstream (git auth) instead of at the
  substitution site.

# See Also

- [cli.md](cli.md) — the 17 subcommands (`setup`/`init`/`generate`/`fixtures`/
  `run`/`debug`/`lint`/`mutate`/`collect`/`explain`/`dashboard`/`doctor`/
  `export`/`analyze`/`skills`/`report`/`journal`) the published package exposes. All seventeen
  work from the Nuitka binary too: `analyze` delegates **in-process**
  (`from cobolparser.cli.parse import main`, with `sys.argv` patched
  around the call), so it needs no `cobol-parser` executable on `PATH`.
  What a binary-only user does not get is that standalone `cobol-parser`
  command itself for direct use outside `mockymock analyze`.
- [runtime.md](runtime.md) — the Docker toolchain the binary still depends on at
  runtime.
- [../PUBLISHING.md](../PUBLISHING.md) — the full narrative (why Nuitka, what "source-free"
  means concretely, local build instructions).
