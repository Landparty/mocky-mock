---
type: Runbook
title: Publishing
description: How mockymock's compiled executables reach users with no repo access — the build-executables.yml reusable workflow, the automatic release-please.yml path, and the manual publish-public.yml path to the public cobol-mocky-mock repo.
tags: [ci, release, publishing]
timestamp: 2026-08-02T00:00:00Z
---

# Overview

`mockymock` and its `cobolparser` dependency are both private repos (see
`LICENSE`, `PUBLISHING.md`). Nuitka compiles a single-file, source-free
`mockymock` executable per OS, bundling the pinned `cobolparser` dependency
straight into machine code in one pass — the binary embeds no `.py` source
for either package. `mockymock/runtime/docker/Dockerfile` is bundled in via
`--include-data-files`; Docker itself (a public `debian:trixie-slim` base
image, no private registry) is still required at runtime, same as always.

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

# See Also

- `cli.md` — the 7 subcommands (`setup`/`generate`/`run`/`debug`/`lint`/
  `mutate`/`collect`) the published binary fully exposes; `cobolparser`'s
  own separate standalone CLI (`parse`/`tokenize`/`program-flow`/etc.) is
  not part of this build and stays unavailable to a binary-only user.
- `runtime.md` — the Docker toolchain the binary still depends on at
  runtime.
- `../PUBLISHING.md` — the full narrative (why Nuitka, what "source-free"
  means concretely, local build instructions).
