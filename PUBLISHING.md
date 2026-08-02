# Publishing executables without publishing source

mockymock and its `cobolparser` dependency are both private, proprietary
repos (see `LICENSE`). Today, *installing* mockymock at all — even just to
run it, never mind reading it — requires GitHub read access to both: the
README's own install instructions say as much ("Authenticate git/uv to
GitHub — both `samdion1994/mocky-mock` and its `cobolparser` dependency are
private repos"). That means every current user of this tool is, by
necessity, someone who *could* just clone and read the full source of both
repos. There is no GitHub permission tier that grants "run mockymock" or
"download the Release" without also granting "read the source."

## What the release workflow builds

`.github/workflows/release-please.yml` has a `build-nuitka-executables`
job (gated on `release-please` actually cutting a release) that calls the
reusable `.github/workflows/build-executables.yml` workflow (via `uses:`,
`secrets: inherit`) to compile a single-file `mockymock` executable per OS
with [Nuitka](https://nuitka.net/): `mockymock-linux-x86_64`,
`mockymock-macos-arm64`, `mockymock-windows-amd64.exe`, attached to the
GitHub Release by the `publish` job.

Nuitka compiles mockymock **and** the pinned `cobolparser` dependency
straight to machine code in one pass (it follows the whole import graph),
so:

- The binary embeds no `.py` source for either package — only compiled
  code plus module/exception qualified names Nuitka keeps for traceback
  formatting (verified the same way as the sibling cobol-parser repo's
  Nuitka build: `strings` against the compiled binary shows no docstrings,
  comments, or function bodies).
- The end user runs **one binary** and never invokes `pip`/`uv`/`git`
  against either private repo themselves — CI does that once, with
  `COBOL_PARSER_PAT` (or `GITHUB_TOKEN`) providing the read access to
  `cobolparser` that an end user would otherwise need personally.
- `mockymock/runtime/docker/Dockerfile` is bundled in explicitly via
  Nuitka's `--include-data-files` (see `scripts/build_executable.sh`) — it's
  the one place in the codebase that resolves a resource path off
  `__file__` at runtime, and it's read at **import** time
  (`docker_toolchain.py`'s module-level `IMAGE = f"...{_image_tag()}"`), so
  a bundling mistake surfaces immediately as a Python traceback rather than
  a confusing later Docker error. `build-executables.yml`'s Linux-only
  end-to-end smoke-test step runs `mockymock setup` for exactly this reason.

Docker itself is unaffected by any of this: mockymock is Docker-only by
design (see `docker_toolchain.py`), and the compiled executable still
needs a working Docker install on the machine that runs it, same as today.

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

## Local build

```bash
# cobolparser must be installable -- either you have git read access to
# Landparty/cobol-parser, or install it from a local checkout first:
pip install /path/to/cobol-parser
pip install --no-deps .

pip install nuitka
# Linux only:
sudo apt-get install -y patchelf

scripts/build_executable.sh mockymock-dev
./build/mockymock-dev --help
```
