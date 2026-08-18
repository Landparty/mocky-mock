---
type: Runbook
title: Publishing
description: mockymock publishes a plain (source-visible) sdist+wheel to PyPI on every release-please release, mirroring cobol-parser's PyPI pipeline; the Nuitka executable path for mocky-mock-vscode is separate and unaffected.
tags: [ci, release, publishing, pypi]
timestamp: 2026-08-18T00:00:00Z
---

# Overview

`mockymock` and its `cobolparser` dependency are both private *repos* (see
`LICENSE`, `PUBLISHING.md`), but as of 2026-08-18 mockymock's package is
published to PyPI as `mocky-mock` — reversing the 2026-08-14
"no longer independently distributed" decision this concept used to
describe. `cobol-parser` was published to PyPI first (as closed-source
Cython wheels — see that repo's own `.github/workflows/release-please.yml`
and `docs/superpowers/specs/2026-08-14-pypi-closed-source-release-design.md`);
mockymock's own release pipeline now mirrors that shape, with one
deliberate difference: **mockymock ships a plain wheel, source visible**.
It's pure Python with no compiled extension (no `.pyx`/`build_ext` anywhere
in this repo), so matching cobol-parser's closed-source cibuildwheel matrix
would mean introducing a whole new Cython build system, not just copying
CI — that was explicitly scoped out when this reversal was decided.

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

**One-time manual step, not yet done as of this writing:** a PyPI Trusted
Publisher must be registered for the `mocky-mock` project
(pypi.org → publishing settings → add a pending publisher, or on the
existing project's page once it has a first release) pointing at this
repo's `release-please.yml` workflow, before `publish-pypi` can succeed.
Same requirement cobol-parser's own publish-pypi job notes for
`cobol-parser`.

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
  "Force-install cobol-parser's latest release" step overrides the pinned
  `cobolparser` commit — two builds a day apart can share the same
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
- `build-executables.yml`'s `run:` steps default to `pwsh` on
  `windows-latest`; only `bash`/`sh`-family shells expand `${TOKEN}`-style
  env vars the way Linux/macOS's default `bash` does. Any step that builds
  a shell string from a secret needs an explicit `shell: bash` on every OS,
  not just the ones where it happens to already default to bash — pwsh
  silently treats `${TOKEN}` as an unset variable rather than erroring,
  so the failure surfaces downstream (git auth) instead of at the
  substitution site.

# See Also

- [cli.md](cli.md) — the 7 subcommands (`setup`/`generate`/`run`/`debug`/`lint`/
  `mutate`/`collect`) the published binary fully exposes; `cobolparser`'s
  own separate standalone CLI (`parse`/`tokenize`/`program-flow`/etc.) is
  not part of this build and stays unavailable to a binary-only user.
- [runtime.md](runtime.md) — the Docker toolchain the binary still depends on at
  runtime.
- [../PUBLISHING.md](../PUBLISHING.md) — the full narrative (why Nuitka, what "source-free"
  means concretely, local build instructions).
