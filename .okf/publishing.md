---
type: Runbook
title: Publishing
description: How mockymock's compiled executables reach users with no repo access — the build-executables.yml reusable workflow, the automatic release-please.yml path, and the manual publish-public.yml path to the public cobol-mocky-mock repo.
tags: [ci, release, publishing]
timestamp: 2026-08-03T00:00:00Z
---

# Overview

`mockymock` and its `cobolparser` dependency are both private repos (see
`LICENSE`, `PUBLISHING.md`). Nuitka compiles a single-file, source-free
`mockymock` executable per OS, bundling the pinned `cobolparser` dependency
straight into machine code in one pass — the binary embeds no `.py` source
for either package. Non-`.py` data files are bundled in explicitly by
`scripts/build_executable.sh` — `mockymock/runtime/docker/Dockerfile` via
`--include-data-files`, the dashboard's `mockymock/web/static/` via
`--include-data-dir` (see [dashboard](dashboard.md)). Docker itself (a
public `debian:trixie-slim` base image, no private registry) is still
required at runtime, same as always.

Three workflows share this build via one reusable definition:

- **`build-executables.yml`** (`workflow_call` only, not directly
  dispatchable) — the actual matrix build (`ubuntu-latest`/`macos-latest`/
  `windows-latest`), `scripts/build_executable.sh`, `--help` smoke test,
  and a Linux-only Docker end-to-end smoke test against
  `examples/custinq/`. Uploads 3 artifacts (`dist-exe-<os>`).
- **`release-please.yml`** (automatic, push to `main`) — cuts a release on
  *this* (private) repo via `release-please`, calls `build-executables.yml`,
  then attaches the 3 binaries to that private release. Unchanged by the
  public-publish addition below except for the reusable-workflow call.
- **`publish-public.yml`** (manual, `workflow_dispatch` only) — calls
  `build-executables.yml` against whichever ref is dispatched, then
  publishes **only** the 3 binaries plus `LICENSE` to a GitHub Release on
  the separate public repo
  [`samdion1994/cobol-mocky-mock`](https://github.com/samdion1994/cobol-mocky-mock),
  tagged from `.release-please-manifest.json` at that ref. Idempotent:
  reuses the release if the tag already exists, `--clobber`s assets. Auth:
  `PUBLISH_REPO_PAT` (fine-grained PAT, `contents: write` scoped to just
  `cobol-mocky-mock`) — no `GITHUB_TOKEN` fallback, unlike
  `COBOL_PARSER_PAT`; a missing secret fails the `gh` calls loudly.

`cobol-mocky-mock` itself carries only a `README.md` plus whatever releases
`publish-public.yml` has published — no source, no other files.

# Gotchas

- **Nuitka ignores `[tool.setuptools.package-data]`.** A non-`.py` file
  resolved via `Path(__file__)` can be correctly listed there, appear in a
  built wheel, pass every unit test, and still be missing from the three
  released executables — the primary artifact for users with no repo
  access. Each such file needs its own `--include-data-files` /
  `--include-data-dir` flag in `scripts/build_executable.sh`. The
  `Dockerfile` and `mockymock/web/static/` are the two current cases; both
  have a CI step in `build-executables.yml` that exercises them *through
  the built binary*, which is the only place this class of bug is visible.

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
