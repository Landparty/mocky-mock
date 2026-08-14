---
type: Runbook
title: Publishing
description: mockymock is no longer independently distributed. It's built from source on demand by mocky-mock-vscode's build-and-release.yml dispatch workflow, which lives in that sibling repo.
tags: [ci, release, publishing]
timestamp: 2026-08-14T00:00:00Z
---

# Overview

`mockymock` and its `cobolparser` dependency are both private repos (see
`LICENSE`, `PUBLISHING.md`). This repo no longer builds or publishes
standalone executables — `build-executables.yml` and `publish-public.yml`
are deleted, and the public `cobol-mocky-mock` distribution repo they fed
is unused.

Building the Nuitka executable now happens in the sibling
`mocky-mock-vscode` repo's `build-and-release.yml` (`workflow_dispatch`
only): it checks out this repo at its latest release tag, runs the same
Nuitka build (`scripts/build_executable.sh`) this concept used to
describe running here, packages the result into the VS Code extension's
`.vsix`, and publishes that. See that repo's own `PUBLISHING.md` and the
workflow itself for the full pipeline.

`release-please.yml` still cuts this repo's own version-bump PRs and a
GitHub Release with generated changelog notes on merge to `main` — it just
no longer attaches any binaries to that release.

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
