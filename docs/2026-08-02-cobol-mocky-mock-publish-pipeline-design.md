# mockymock — Public Binary Publish Pipeline Design

Date: 2026-08-02
Status: proposed

## Motivation

`mocky-mock` and its `cobolparser` dependency are both private repos.
`PUBLISHING.md` already documents that `release-please.yml`'s existing
`build-nuitka-executables` job — which compiles a single-file, source-free
`mockymock` executable per OS (bundling the pinned `cobolparser` dependency
straight into machine code via Nuitka) — only solves *what* a collaborator
gets, not *who* can reach it: "A GitHub Release on a private repo is only
downloadable by people who already have read access to the repo... If the
actual goal is reaching people who have no access to this repo at all...
that needs a distribution point whose access isn't tied to this repo's
permissions... Someone with repo-admin context needs to decide that part."

`samdion1994/cobol-mocky-mock` now exists — public, currently empty, no
releases. This is that distribution point. This design wires up how it gets
populated.

**Confirmed during design: the compiled `mockymock` binary already carries
mockymock's complete feature set** (`setup`/`generate`/`run`/`debug`/`lint`/
`mutate`/`collect`) with no external access needed at runtime —
`cobolparser` is consumed as an internal library, fully compiled in, and the
bundled `mockymock/runtime/docker/Dockerfile` (`FROM debian:trixie-slim`, a
public base image) needs no private registry auth either. The one confirmed
gap — `cobolparser`'s own separate standalone CLI (its `cobol-parser`
console script: `parse`/`batch`/`tokenize`/`preprocess`/`expand`/
`gen-data`/`program-flow`/coverage tooling) is not part of this build and
stays unavailable to a binary-only user — is accepted as out of scope (see
Scope).

## Scope

**In scope:**
- Extract the existing `build-nuitka-executables` job (matrix build + smoke
  test, currently inlined in `release-please.yml`) into a reusable
  workflow, `.github/workflows/build-executables.yml`
  (`on: workflow_call`), so both the existing automatic path and the new
  manual path build from one definition.
- A new workflow, `.github/workflows/publish-public.yml`, triggered
  **only** by `workflow_dispatch` (no automatic push trigger) — launched
  manually, building whichever ref/tag is selected at dispatch time.
- That workflow calls the reusable build, then publishes **only** the 3
  resulting binaries plus `LICENSE` to a GitHub Release on
  `samdion1994/cobol-mocky-mock`, tagged to match the source ref's
  `.release-please-manifest.json` version.
- A new repo secret, `PUBLISH_REPO_PAT` (fine-grained PAT, `contents: write`
  scoped to just `cobol-mocky-mock`), mirroring the existing
  `COBOL_PARSER_PAT` cross-repo-auth pattern. **User-provisioned** —
  generating a PAT and adding a repo secret are both explicit-permission
  account actions; not something to automate here. Unlike
  `COBOL_PARSER_PAT` (which falls back to `secrets.GITHUB_TOKEN`),
  `PUBLISH_REPO_PAT` has no fallback — `GITHUB_TOKEN` is scoped to the repo
  the workflow runs in and cannot write to a different repo at all. If the
  secret is unset, the `gh release`/`gh release upload` calls fail with a
  visible auth error; that's the intended signal, not something to swallow
  with a conditional skip.
- A one-time `README.md` scaffold for `cobol-mocky-mock` itself (it's
  currently completely empty): what it is, that it's binary-only with no
  source, that Docker is still required at runtime, and a pointer to the
  latest release.
- Updating `PUBLISHING.md`'s "part this workflow does not solve" section
  once this ships, so it stops describing a now-solved gap as open.
- A new `.okf/publishing.md` concept (linked from `.okf/index.md`, logged
  in `.okf/log.md`), per this workspace's standing OKF-maintenance
  instruction — there's currently no concept covering the release/publish
  pipeline at all.

**Explicitly out of scope** (considered and deferred, not forgotten):
- Publishing `cobolparser`'s wheels (sdist/binary wheels) to the new repo —
  that serves a different audience (using `cobolparser` as a standalone
  Python library), stays on the private `Landparty/cobol-parser` repo only.
  Confirmed with the user during design.
- Publishing `cobolparser`'s own standalone CLI (the separate
  `cobol-parser` console-script entry point, distinct from anything
  `mockymock` calls internally) as its own compiled binary. Confirmed
  accepted as a known gap, not a goal, during design.
- Automatic triggering tied to `release-please` cutting a release — the
  user explicitly wants manual control over when the public repo gets a
  new version, decoupled from the private repo's own release cadence.
- Changing `mocky-mock-vscode`'s bootstrap to fetch from the new public
  repo (`PUBLISHING.md` flags this as a followup in that *other* repo) —
  separate repo, separate change.
- Actually triggering a real `workflow_dispatch` run against the public
  repo as part of this work — that creates a real, publicly-visible GitHub
  Release. That's the user's call to make when ready, not something to do
  as a side effect of implementing the pipeline.

## Design

### Architecture

```
release-please.yml (unchanged trigger: push to main)
  release-please job      -> cuts a release on THIS (private) repo when due
  build-nuitka-executables -> uses: ./.github/workflows/build-executables.yml
  publish job              -> unchanged: attaches binaries to the private
                               repo's own release

publish-public.yml (NEW, trigger: workflow_dispatch only)
  build job         -> uses: ./.github/workflows/build-executables.yml
  publish-public job -> downloads build artifacts + LICENSE,
                         creates/reuses a release on cobol-mocky-mock,
                         uploads binaries + LICENSE there, nothing else
```

### `build-executables.yml` (new, reusable)

Verbatim extraction of the current `build-nuitka-executables` job body
(matrix over `ubuntu-latest`/`macos-latest`/`windows-latest`, cobolparser
git-credential setup, Nuitka build via `scripts/build_executable.sh`,
`--help` smoke test, Linux-only Docker end-to-end smoke test,
`upload-artifact`). Behavior does not change — this is a pure refactor, not
a rewrite. Only the `on:` trigger changes, to `workflow_call`.

Callers must pass `secrets: inherit` — a reusable workflow does not
automatically see the caller's secrets otherwise:

```yaml
build-nuitka-executables:
  needs: release-please
  if: ${{ needs.release-please.outputs.releases_created == 'true' }}
  uses: ./.github/workflows/build-executables.yml
  secrets: inherit
```

### `publish-public.yml` (new)

```yaml
name: publish-public

on:
  workflow_dispatch:

permissions:
  contents: read

jobs:
  build:
    uses: ./.github/workflows/build-executables.yml
    secrets: inherit

  publish-public:
    needs: build
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/download-artifact@v4
        with:
          pattern: dist-exe-*
          path: dist/
          merge-multiple: true
      - name: Resolve the release tag from the manifest
        id: tag
        run: echo "tag=v$(jq -r '.["."]' .release-please-manifest.json)" >> "$GITHUB_OUTPUT"
      - name: Create the release on cobol-mocky-mock if it doesn't exist yet
        env:
          GH_TOKEN: ${{ secrets.PUBLISH_REPO_PAT }}
        run: |
          TAG="${{ steps.tag.outputs.tag }}"
          gh release view "$TAG" --repo samdion1994/cobol-mocky-mock >/dev/null 2>&1 || \
            gh release create "$TAG" --repo samdion1994/cobol-mocky-mock \
              --title "mockymock $TAG" \
              --notes "mockymock $TAG. Download the binary for your platform below. Requires Docker at runtime. See README for usage."
      - name: Upload binaries and license (clobber lets a re-dispatch replace a bad build)
        env:
          GH_TOKEN: ${{ secrets.PUBLISH_REPO_PAT }}
        run: |
          gh release upload "${{ steps.tag.outputs.tag }}" dist/* LICENSE \
            --repo samdion1994/cobol-mocky-mock --clobber
```

Key decisions embedded above:
- **No custom `workflow_dispatch` inputs.** GitHub's own dispatch
  UI/`gh workflow run --ref` already lets you pick which branch/tag to
  build; a redundant custom input would just be one more thing to keep in
  sync with that choice.
- **Version tag comes from `.release-please-manifest.json` at the
  dispatched ref**, same resolution the existing `publish` job already
  uses — the public repo's tags stay meaningful (`v1.4.2`) instead of a
  dispatch-time free-text field the user has to type correctly.
- **Release notes are a short fixed string, not release-please's
  changelog.** The changelog is generated from commit messages in a private
  repo and may reference internal PRs/issues/file names not meant for
  public consumption.
- **`gh release view ... || gh release create ...` makes re-dispatch
  idempotent.** Re-running against the same version (e.g., to fix a bad
  binary) reuses the existing release and `--clobber`s the assets, rather
  than failing on "tag already exists."
- **Only `dist/*` (the 3 binaries) and `LICENSE` are uploaded** — no
  changelog file, no source, matching "only push the binary and licence."

### `cobol-mocky-mock/README.md` (new, one-time)

Short — what the repo is (binary-only distribution of `mockymock`, no
source), that Docker is required at runtime, and a link to the latest
release. Not a mirror of mocky-mock's own README.

## Testing

GitHub Actions workflow changes can't be dry-run locally in a way that
proves the cross-repo publish step actually works — `gh release
create/upload` against a real repo is the only real test, and running it
for real publishes a real public release. Plan:
1. Validate YAML structure and `gh`/`jq` syntax by careful review (no repo
   secrets needed for this).
2. Confirm the reusable-workflow refactor doesn't change
   `release-please.yml`'s existing behavior by tracing it step-for-step
   against the current inlined job — this part *can* be verified without
   side effects.
3. The actual end-to-end proof — `PUBLISH_REPO_PAT` configured, a real
   `workflow_dispatch` run, a real release landing on `cobol-mocky-mock` —
   happens when the user is ready to trigger it themselves (or explicitly
   asks me to). I'll say so plainly rather than claim this is "tested"
   before that happens.

## Docs to update after implementation

- `PUBLISHING.md` — replace the "part this workflow does not solve"
  section's description of the gap with how it's now closed (link to
  `publish-public.yml`, note the manual-dispatch model).
- `.okf/publishing.md` (new concept) + `.okf/index.md` (link it) +
  `.okf/log.md` (dated entry) — per this workspace's OKF-maintenance
  convention; there's currently no concept covering the release/publish
  pipeline.
- `README.md` — optionally note the public binary as an install path for
  non-collaborators, alongside the existing `uv tool install` path. Small
  addition, not required for the pipeline to work.

## Alternatives considered

- **Tie the public publish to `release-please`'s automatic flow** (extend
  the existing `if: releases_created == 'true'` gate to also publish
  publicly). Simpler — no new workflow file — but removes the manual
  control the user explicitly asked for, and couples "the private repo cut
  a release" to "the public repo gets one," which aren't necessarily the
  same decision.
- **Duplicate the build matrix into `publish-public.yml` instead of
  extracting a reusable workflow.** Avoids learning `workflow_call` syntax,
  but the two build definitions (private-repo path and public-dispatch
  path) would drift the first time either one needs a fix — e.g., a Nuitka
  flag change or a new smoke-test step applied to only one copy. Rejected
  for the same reason `.okf/dsl.md`'s parser/driver sync comment already
  documents as a real, recurring risk pattern in this codebase.
- **Also publish `cobolparser`'s wheels and/or its standalone CLI binary
  now, since the pipeline is already touching this area.** Rejected —
  confirmed out of scope with the user; different audience, real added
  build/maintenance surface for a need that hasn't been established.
