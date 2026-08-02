# cobol-mocky-mock Publish Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a manually-dispatched CI pipeline that rebuilds mockymock's 3 Nuitka executables and publishes only the binaries plus `LICENSE` to the public `samdion1994/cobol-mocky-mock` repo, without disturbing the existing automatic private-repo release.

**Architecture:** Extract the existing `build-nuitka-executables` job out of `release-please.yml` into a reusable `workflow_call` workflow (`build-executables.yml`), so it can be called from both the existing automatic path and a new `workflow_dispatch`-only workflow (`publish-public.yml`) that publishes to the public repo, without duplicating the build definition.

**Tech Stack:** GitHub Actions (YAML), `gh` CLI, `jq`. No application code changes.

**Full design:** [`docs/2026-08-02-cobol-mocky-mock-publish-pipeline-design.md`](../../2026-08-02-cobol-mocky-mock-publish-pipeline-design.md)

## Global Constraints

- Only these assets ever get uploaded to a `cobol-mocky-mock` release:
  `mockymock-linux-x86_64`, `mockymock-macos-arm64`,
  `mockymock-windows-amd64.exe`, and `LICENSE`. Nothing else — no
  changelog, no source, no repo-root `LICENSE` file added to
  `cobol-mocky-mock` itself (it ships only as a release asset).
- `publish-public.yml`'s only trigger is `workflow_dispatch`. No `push` or
  `pull_request` trigger is added to it.
- Any job that calls `build-executables.yml` via `uses:` must also pass
  `secrets: inherit` — a reusable workflow does not see the caller's
  secrets otherwise.
- Release tag format is `v<version>`, read from
  `.release-please-manifest.json`'s `"."` key at the dispatched ref —
  identical to the resolution `release-please.yml`'s existing `publish`
  job already uses.
- Auth to the public repo uses a new secret, `PUBLISH_REPO_PAT`. It is
  **user-provisioned** (fine-grained PAT, `contents: write` scoped to only
  `cobol-mocky-mock`) — do not attempt to create a PAT or set a repo secret
  in this plan. Unlike `COBOL_PARSER_PAT`, it has **no `GITHUB_TOKEN`
  fallback**: `GITHUB_TOKEN` cannot write to a different repo at all.
- Commit message prefixes follow this repo's existing convention: `ci:`
  for workflow changes (Tasks 1–2), `docs:` for documentation-only changes
  (Task 4). Neither triggers a release-please version bump.
- Out of scope — do not implement: publishing `cobolparser`'s wheels or its
  standalone CLI to `cobol-mocky-mock`; tying the public publish to
  `release-please`'s automatic flow; updating `mocky-mock-vscode` (separate
  repo).
- **Every commit in this plan is local, on a feature branch.** Do not push
  `mocky-mock`'s branch, and do not run Task 3's actual publish step,
  without first stopping and getting explicit confirmation in chat — both
  are "modify public content" actions per standing safety rules, not
  implied by having a plan to execute.
- Do not actually run `workflow_dispatch` for real (i.e., do not trigger
  `publish-public.yml`) as part of this plan — that creates a real public
  release and is the user's call to make separately, when ready.

---

### Task 1: Extract the Nuitka build into a reusable workflow

**Files:**
- Create: `.github/workflows/build-executables.yml`
- Modify: `.github/workflows/release-please.yml` (the `build-nuitka-executables` job, currently lines 32–104)

**Interfaces:**
- Produces: a `workflow_call`-triggered reusable workflow with one job
  (`build`) that uploads 3 artifacts via the existing
  `dist-exe-${{ matrix.os }}` naming (`dist-exe-ubuntu-latest`,
  `dist-exe-macos-latest`, `dist-exe-windows-latest`), each containing one
  file at `build/<artifact>` — consumed later by Task 2's
  `publish-public.yml` and by `release-please.yml`'s existing `publish`
  job, both via `actions/download-artifact@v4` with `pattern: dist-exe-*`.

- [ ] **Step 1: Create `build-executables.yml` with the extracted job**

This is the current `build-nuitka-executables` job body, verbatim, moved
into its own reusable workflow (only the trigger and job name change):

```yaml
name: build-executables

# Reusable workflow: builds the 3 Nuitka mockymock executables. Called by
# release-please.yml (automatic, on a release-please release) and by
# publish-public.yml (manual, via workflow_dispatch) so both paths share
# one build definition instead of two that can drift. See PUBLISHING.md.

on:
  workflow_call:

jobs:
  build:
    strategy:
      fail-fast: false
      matrix:
        include:
          - os: ubuntu-latest
            artifact: mockymock-linux-x86_64
          - os: macos-latest
            artifact: mockymock-macos-arm64
          - os: windows-latest
            artifact: mockymock-windows-amd64.exe
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4

      # cobolparser is a private repo; the pyproject.toml dependency line
      # pins it via git+https, which pip/git can only resolve here if
      # COBOL_PARSER_PAT (a PAT/deploy key with read access) is configured
      # as a secret, or cobol-parser is public. Same documented gap/fallback
      # as ci.yml's "Check out cobol-parser (sibling editable dependency)"
      # step -- if neither holds, this fails loudly at the install step
      # below rather than silently producing a broken build.
      - name: Configure git credentials for the private cobolparser dependency
        run: |
          git config --global url."https://x-access-token:${TOKEN}@github.com/".insteadOf "https://github.com/"
        env:
          TOKEN: ${{ secrets.COBOL_PARSER_PAT || secrets.GITHUB_TOKEN }}

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install patchelf (required by Nuitka onefile mode on Linux)
        if: runner.os == 'Linux'
        run: sudo apt-get update && sudo apt-get install -y patchelf
      - name: Install mockymock (pulls in the pinned cobolparser dependency)
        run: pip install .
      - name: Install Nuitka
        run: pip install nuitka
      - name: Build onefile executable
        shell: bash
        run: scripts/build_executable.sh "${{ matrix.artifact }}"
      - name: Smoke-test the executable
        shell: bash
        run: |
          BIN="build/${{ matrix.artifact }}"
          chmod +x "$BIN" || true
          "$BIN" --help
      - name: End-to-end smoke test against a real example (Docker required)
        # GitHub-hosted ubuntu-latest runners have a working Docker daemon;
        # macos-latest/windows-latest don't reliably, and mockymock is
        # Docker-only by design (see docker_toolchain.py), so this step is
        # Linux-only. `setup` also exercises the bundled Dockerfile data
        # file (mockymock.runtime.docker_toolchain reads it at import time,
        # before touching Docker at all -- see PUBLISHING.md), so a clean
        # "Docker not available"-style failure here would still mean the
        # bundling worked; an unhandled Python traceback would mean it didn't.
        if: runner.os == 'Linux'
        shell: bash
        run: |
          BIN="build/${{ matrix.artifact }}"
          "$BIN" setup
          "$BIN" run examples/custinq/CUSTINQ.cbl --cut examples/custinq/CUSTINQ.cut
      - uses: actions/upload-artifact@v4
        with:
          name: dist-exe-${{ matrix.os }}
          path: build/${{ matrix.artifact }}
```

- [ ] **Step 2: Validate YAML syntax**

Run:
```bash
python -c "import yaml" 2>/dev/null || pip install --quiet pyyaml
python -c "import yaml; yaml.safe_load(open('.github/workflows/build-executables.yml')); print('valid YAML')"
```
Expected: `valid YAML`

- [ ] **Step 3: Replace the job body in `release-please.yml`**

Find this block (the current `build-nuitka-executables` job, including its
leading comment):

```yaml
  # Build a single-file, source-free mockymock executable with Nuitka. It
  # compiles mockymock AND the private cobolparser dependency straight to
  # machine code in one pass, so the end user never needs pip/uv/git access
  # to either private repo -- just this one binary. See PUBLISHING.md.
  build-nuitka-executables:
    needs: release-please
    if: ${{ needs.release-please.outputs.releases_created == 'true' }}
    strategy:
      fail-fast: false
      matrix:
        include:
          - os: ubuntu-latest
            artifact: mockymock-linux-x86_64
          - os: macos-latest
            artifact: mockymock-macos-arm64
          - os: windows-latest
            artifact: mockymock-windows-amd64.exe
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4

      # cobolparser is a private repo; the pyproject.toml dependency line
      # pins it via git+https, which pip/git can only resolve here if
      # COBOL_PARSER_PAT (a PAT/deploy key with read access) is configured
      # as a secret, or cobol-parser is public. Same documented gap/fallback
      # as ci.yml's "Check out cobol-parser (sibling editable dependency)"
      # step -- if neither holds, this fails loudly at the install step
      # below rather than silently producing a broken build.
      - name: Configure git credentials for the private cobolparser dependency
        run: |
          git config --global url."https://x-access-token:${TOKEN}@github.com/".insteadOf "https://github.com/"
        env:
          TOKEN: ${{ secrets.COBOL_PARSER_PAT || secrets.GITHUB_TOKEN }}

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install patchelf (required by Nuitka onefile mode on Linux)
        if: runner.os == 'Linux'
        run: sudo apt-get update && sudo apt-get install -y patchelf
      - name: Install mockymock (pulls in the pinned cobolparser dependency)
        run: pip install .
      - name: Install Nuitka
        run: pip install nuitka
      - name: Build onefile executable
        shell: bash
        run: scripts/build_executable.sh "${{ matrix.artifact }}"
      - name: Smoke-test the executable
        shell: bash
        run: |
          BIN="build/${{ matrix.artifact }}"
          chmod +x "$BIN" || true
          "$BIN" --help
      - name: End-to-end smoke test against a real example (Docker required)
        # GitHub-hosted ubuntu-latest runners have a working Docker daemon;
        # macos-latest/windows-latest don't reliably, and mockymock is
        # Docker-only by design (see docker_toolchain.py), so this step is
        # Linux-only. `setup` also exercises the bundled Dockerfile data
        # file (mockymock.runtime.docker_toolchain reads it at import time,
        # before touching Docker at all -- see PUBLISHING.md), so a clean
        # "Docker not available"-style failure here would still mean the
        # bundling worked; an unhandled Python traceback would mean it didn't.
        if: runner.os == 'Linux'
        shell: bash
        run: |
          BIN="build/${{ matrix.artifact }}"
          "$BIN" setup
          "$BIN" run examples/custinq/CUSTINQ.cbl --cut examples/custinq/CUSTINQ.cut
      - uses: actions/upload-artifact@v4
        with:
          name: dist-exe-${{ matrix.os }}
          path: build/${{ matrix.artifact }}
```

Replace it with:

```yaml
  # Builds the 3 Nuitka executables. Extracted into a reusable workflow
  # (build-executables.yml) so this automatic path and publish-public.yml's
  # manual-dispatch path share one build definition instead of two that can
  # drift. See PUBLISHING.md.
  build-nuitka-executables:
    needs: release-please
    if: ${{ needs.release-please.outputs.releases_created == 'true' }}
    uses: ./.github/workflows/build-executables.yml
    secrets: inherit
```

- [ ] **Step 4: Validate YAML syntax of the modified file**

Run:
```bash
python -c "import yaml; yaml.safe_load(open('.github/workflows/release-please.yml')); print('valid YAML')"
```
Expected: `valid YAML`

- [ ] **Step 5: Diff review**

Run:
```bash
git diff .github/workflows/release-please.yml
```
Confirm: only the `build-nuitka-executables` job body changed. The
`release-please` job and the `publish` job (including its
`needs: [release-please, build-nuitka-executables]` line) are untouched —
the job key name didn't change, only its body.

- [ ] **Step 6: Commit**

```bash
git add .github/workflows/build-executables.yml .github/workflows/release-please.yml
git commit -m "ci: extract Nuitka build into a reusable workflow"
```

---

### Task 2: Add the manual publish-to-public-repo workflow

**Files:**
- Create: `.github/workflows/publish-public.yml`

**Interfaces:**
- Consumes: `.github/workflows/build-executables.yml` from Task 1 (via
  `uses: ./.github/workflows/build-executables.yml`) and its `dist-exe-*`
  artifacts; repo secret `PUBLISH_REPO_PAT` (assumed present at runtime,
  not created by this task).
- Produces: a `workflow_dispatch`-only workflow that publishes a GitHub
  Release on `samdion1994/cobol-mocky-mock`.

- [ ] **Step 1: Create `publish-public.yml`**

```yaml
name: publish-public

# Manually-triggered only. Rebuilds the 3 Nuitka executables via the
# shared build-executables.yml and publishes only the binaries + LICENSE
# to the separate public samdion1994/cobol-mocky-mock repo. Decoupled from
# release-please.yml's automatic private-repo release on purpose -- see
# docs/2026-08-02-cobol-mocky-mock-publish-pipeline-design.md.

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

- [ ] **Step 2: Validate YAML syntax**

Run:
```bash
python -c "import yaml; yaml.safe_load(open('.github/workflows/publish-public.yml')); print('valid YAML')"
```
Expected: `valid YAML`

- [ ] **Step 3: Review against Global Constraints**

Confirm by inspection:
- Trigger block contains only `workflow_dispatch:` — no `push`/`pull_request`.
- The `build` job has `secrets: inherit`.
- The upload step's file list is exactly `dist/* LICENSE` — nothing else.
- `GH_TOKEN` in both `gh` steps is `secrets.PUBLISH_REPO_PAT`, with no
  `|| secrets.GITHUB_TOKEN` fallback (unlike the cobolparser-checkout
  pattern elsewhere in this repo — deliberate, per Global Constraints).

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/publish-public.yml
git commit -m "ci: add manual workflow to publish binaries to cobol-mocky-mock"
```

---

### Task 3: Scaffold the cobol-mocky-mock repo's README

**Files:**
- Create (locally, staging only): `<scratchpad>/cobol-mocky-mock-README.md`
- Create (remote, on publish): `README.md` in `samdion1994/cobol-mocky-mock`

**Interfaces:**
- Produces: the first file in the previously-empty `samdion1994/cobol-mocky-mock` repo, establishing its default branch.

**⚠️ This task ends with an action on a public, external repo. Do not run
Step 3 without first stopping and getting explicit confirmation in chat —
per standing safety rules, "publishing/modifying public content" is always
confirmed at the moment it happens, regardless of earlier plan approval. If
executing via a subagent, the subagent should stop after Step 2 and report
back rather than running Step 3 itself.**

- [ ] **Step 1: Write the README content to the scratchpad**

Write this exact content to
`<scratchpad>/cobol-mocky-mock-README.md`:

```markdown
# cobol-mocky-mock

Compiled, source-free `mockymock` executables — nothing else lives here.

`mockymock` mocks a COBOL program's external boundaries (subprogram
`CALL`s, file I/O, `EXEC SQL`/`CICS`/`DLI`, console `ACCEPT`), compiles the
instrumented copy with GnuCOBOL, runs it, and reports pass/fail. Its source
and its `cobolparser` dependency are both private; this repo exists so
anyone can run the tool without needing access to either.

## Install

Download the binary for your platform from the
[latest release](https://github.com/samdion1994/cobol-mocky-mock/releases/latest):

- `mockymock-linux-x86_64`
- `mockymock-macos-arm64`
- `mockymock-windows-amd64.exe`

Each release also includes the `LICENSE` under which the binary is
distributed.

## Requirements

[Docker](https://docs.docker.com/get-docker/) must be installed and
running — `mockymock` compiles and executes COBOL inside a Docker
container. On first run, `mockymock setup` builds the required image.

## Usage

```
mockymock setup
mockymock run <program.cbl> --cut <file.cut>
```

See the binary's own `--help` for the full command reference.
```

- [ ] **Step 2: Show the prepared content to the user for confirmation**

Display the file's content and ask explicitly: "Ready to publish this
README as the first commit to the public `samdion1994/cobol-mocky-mock`
repo — confirm?"

- [ ] **Step 3: Publish (only after explicit confirmation)**

```bash
CONTENT=$(base64 -w0 "<scratchpad>/cobol-mocky-mock-README.md")
gh api repos/samdion1994/cobol-mocky-mock/contents/README.md \
  --method PUT \
  -f message="docs: add README" \
  -f content="$CONTENT"
```
Expected: JSON response containing the new commit SHA and `content.path`
of `README.md`.

- [ ] **Step 4: Verify**

```bash
gh api repos/samdion1994/cobol-mocky-mock/contents/README.md --jq '.path'
```
Expected: `README.md`

---

### Task 4: Update documentation

**Files:**
- Modify: `PUBLISHING.md`
- Create: `.okf/publishing.md`
- Modify: `.okf/index.md`
- Modify: `.okf/log.md`

**Interfaces:**
- Consumes: the file paths and behavior established by Tasks 1–3 (this
  task documents them; do not start it before Tasks 1–3 are done).

- [ ] **Step 1: Update `PUBLISHING.md`**

Find this section (note: this file uses em-dash `—`, not `--`):

```markdown
## The part this workflow does *not* solve

A GitHub Release on a **private** repo is only downloadable by people who
already have read access to the repo — the same access that lets them
`git clone` the source. Attaching a source-free binary here doesn't change
who can reach it; it changes what they get once they're already a
collaborator (a working executable instead of "clone and build it
yourself"). If the actual goal is reaching people who have *no* access to
this repo at all — customers, non-technical users, anyone outside the
collaborator list — that needs a distribution point whose access isn't
tied to this repo's permissions: a separate public "releases only" repo
that's never given the source, a company website, or object storage with a
shareable link. Someone with repo-admin context needs to decide that part;
it isn't something a build workflow can resolve on its own.

See also the companion VS Code extension's own `PUBLISHING.md`
(`mocky-mock-vscode`) — its CLI auto-bootstrap currently runs
`uv tool install git+https://github.com/samdion1994/mocky-mock.git`, which
hits this exact private-repo-auth wall for anyone without collaborator
access. That's being changed to fetch this repo's Nuitka executable
instead.
```

Replace it with:

```markdown
## Reaching people with no repo access at all

A GitHub Release on a **private** repo is only downloadable by people who
already have read access to the repo — the same access that lets them
`git clone` the source. Attaching a source-free binary here doesn't change
who can reach it; it changes what they get once they're already a
collaborator (a working executable instead of "clone and build it
yourself").

Reaching people who have *no* access to this repo at all — customers,
non-technical users, anyone outside the collaborator list — needs a
distribution point whose access isn't tied to this repo's permissions.
That's what [`samdion1994/cobol-mocky-mock`](https://github.com/samdion1994/cobol-mocky-mock)
is: a separate, public, binary-only repo that's never given the source.
`.github/workflows/publish-public.yml` (`workflow_dispatch`-triggered —
launched manually, not tied to `release-please` cutting a release here)
builds the same 3 executables via the shared `build-executables.yml`
reusable workflow, then publishes only the binaries and `LICENSE` there.
Auth uses a separate `PUBLISH_REPO_PAT` secret (`contents: write` scoped to
just that repo) — `GITHUB_TOKEN` can't write to a different repo, and
unlike `COBOL_PARSER_PAT` this has no `GITHUB_TOKEN` fallback.

See also the companion VS Code extension's own `PUBLISHING.md`
(`mocky-mock-vscode`) — its CLI auto-bootstrap currently runs
`uv tool install git+https://github.com/samdion1994/mocky-mock.git`, which
hits this exact private-repo-auth wall for anyone without collaborator
access. That's being changed to fetch `cobol-mocky-mock`'s Nuitka
executable instead.
```

- [ ] **Step 2: Create `.okf/publishing.md`**

```markdown
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
```

- [ ] **Step 3: Link it from `.okf/index.md`**

Find:

```markdown
## Integration & Testing

* [Integration Contract](integration.md) — the cobolparser AST surface mockymock depends on (distills the repo-root [interface-contract.md](../interface-contract.md))
* [Testing](testing.md) — unit/integration split, Docker-availability skip gate, `tests/integration/fixtures/` corpus, and the two worked examples (INVUPDT, ORDRPROC)
* [Coverage](coverage.md) — `mockymock run --coverage`: GnuCOBOL/gcov-based per-line coverage reporting

## Change History
```

Replace with:

```markdown
## Integration & Testing

* [Integration Contract](integration.md) — the cobolparser AST surface mockymock depends on (distills the repo-root [interface-contract.md](../interface-contract.md))
* [Testing](testing.md) — unit/integration split, Docker-availability skip gate, `tests/integration/fixtures/` corpus, and the two worked examples (INVUPDT, ORDRPROC)
* [Coverage](coverage.md) — `mockymock run --coverage`: GnuCOBOL/gcov-based per-line coverage reporting

## Publishing

* [Publishing](publishing.md) — the shared `build-executables.yml` reusable workflow, the automatic `release-please.yml` path, and the manual `publish-public.yml` path to the public `cobol-mocky-mock` repo

## Change History
```

- [ ] **Step 4: Append a dated entry to `.okf/log.md`**

Insert this new section directly after the `# mockymock OKF Bundle —
Update Log` title line, above the existing `## 2026-07-29` entry (newest
entry first, matching existing order):

```markdown
## 2026-08-02 — Manual publish pipeline to the public cobol-mocky-mock repo

New concept: [publishing.md](publishing.md). The existing
`build-nuitka-executables` job in `release-please.yml` (matrix Nuitka
build, 3 OS executables bundling the pinned `cobolparser` dependency) was
extracted into a reusable workflow, `build-executables.yml`
(`workflow_call`), so a new manually-triggered workflow,
`publish-public.yml` (`workflow_dispatch` only), can share the same build
without duplicating it. `publish-public.yml` publishes only the 3 binaries
plus `LICENSE` to a GitHub Release on the separate public repo
`samdion1994/cobol-mocky-mock` (its own new `README.md` documents
install/requirements for that audience) — closing the gap `PUBLISHING.md`
had flagged as unsolved ("a separate public releases-only repo... someone
with repo-admin context needs to decide that part"). `release-please.yml`'s
existing automatic private-repo release is unchanged apart from calling the
same reusable workflow.

Confirmed during design, not just assumed: the compiled binary already
exposes mockymock's full CLI surface (`setup`/`generate`/`run`/`debug`/
`lint`/`mutate`/`collect`) with no external access needed —
`cobolparser` is consumed as an internal library, fully compiled in by
Nuitka, and the bundled Docker base image (`debian:trixie-slim`) is public.
`cobolparser`'s own separate standalone CLI (`cobol-parser` console script:
`parse`/`tokenize`/`program-flow`/etc.) is not part of this build and stays
unavailable to a binary-only user — a known, accepted gap, not an
oversight.
```

- [ ] **Step 5: Commit**

```bash
git add PUBLISHING.md .okf/publishing.md .okf/index.md .okf/log.md
git commit -m "docs: document the public binary publish pipeline"
```
