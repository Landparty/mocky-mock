# Publishing executables without publishing source

> **Superseded (2026-10-04).** mockymock and `cobolparser` are both free
> software under AGPL-3.0-or-later and both publish their source to PyPI,
> so the premise below (private, proprietary repos whose source must stay
> hidden) no longer holds. The rest of this file is kept as history of the
> retired Nuitka pipeline.

mockymock and its `cobolparser` dependency are both private, proprietary
repos (see `LICENSE`). Today, *installing* mockymock at all — even just to
run it, never mind reading it — requires GitHub read access to both: the
README's own install instructions say as much ("Authenticate git/uv to
GitHub — both `Landparty/mocky-mock` and its `cobolparser` dependency are
private repos"). That means every current user of this tool is, by
necessity, someone who *could* just clone and read the full source of both
repos. There is no GitHub permission tier that grants "run mockymock" or
"download the Release" without also granting "read the source."

## What the retired release pipeline built

`.github/workflows/release-please.yml` used to have a
`build-nuitka-executables` job (gated on `release-please` actually cutting
a release) that called the reusable `.github/workflows/build-executables.yml`
workflow (via `uses:`, `secrets: inherit`) to compile a single-file
`mockymock` executable per OS with [Nuitka](https://nuitka.net/):
`mockymock-linux-x86_64`, `mockymock-macos-arm64`,
`mockymock-windows-amd64.exe`, attached to the GitHub Release by the
`publish` job. Both jobs and `build-executables.yml` itself are deleted
(see "Standalone distribution has been retired" below); the description
that follows is kept because the same Nuitka mechanics still apply
wherever the build runs today.

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
  `COBOL_PARSER_PAT` providing the read access to `cobolparser` that an
  end user would otherwise need personally.
- `mockymock/runtime/docker/Dockerfile` is bundled in explicitly via
  Nuitka's `--include-data-files` (see `scripts/build_executable.sh`) — it's
  the one place in the codebase that resolves a resource path off
  `__file__` at runtime, and it's read at **import** time
  (`docker_toolchain.py`'s module-level `IMAGE = f"...{_image_tag()}"`), so
  a bundling mistake surfaces immediately as a Python traceback rather than
  a confusing later Docker error. `build-executables.yml`'s Linux-only
  end-to-end smoke-test step ran `mockymock setup` for exactly this reason.

Docker itself is unaffected by any of this: mockymock is Docker-only by
design (see `docker_toolchain.py`), and the compiled executable still
needs a working Docker install on the machine that runs it, same as today.

## Standalone distribution has been retired

mockymock no longer builds or publishes standalone executables from this
repo. That used to mean two things: `release-please.yml` attaching 3
Nuitka executables to this repo's own private Release, and a separate
`publish-public.yml` relaying the same 3 executables to a public repo
(`cobol-mocky-mock`) so people without access to this repo could download
them.

Both are gone. The only consumer of these executables was
`mocky-mock-vscode`'s packaging step, and that now builds mockymock from
source itself, on demand, in its own `build-and-release.yml` — see that
repo's `PUBLISHING.md` and the workflow itself for the full pipeline. If
you need the standalone CLI outside of VS Code, build it locally (see
"Local build" below) or run `mocky-mock-vscode`'s dispatch workflow and
unzip the resulting `.vsix` — `extension/bin/mockymock` is the same
binary (the Windows package bundles it as `extension/bin/mockymock.exe`
instead; only the linux-x64 and darwin-arm64 packages use the
extensionless name).

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
