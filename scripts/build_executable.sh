#!/usr/bin/env bash
# Builds a single-file, source-free mockymock executable with Nuitka.
#
# Compiles mockymock AND its cobolparser dependency straight to machine
# code in one pass (Nuitka follows the import graph), so the end user gets
# one binary and never runs pip/uv against the private cobolparser repo
# themselves. See PUBLISHING.md.
#
# Every non-.py file the package resolves via Path(__file__) needs its own
# --include-data-* flag here: Nuitka does not read pyproject's
# [tool.setuptools.package-data], so a file can ship correctly in the wheel
# and still be missing from these binaries. Currently the GnuCOBOL
# Dockerfile and the dashboard's static assets.
#
# Usage: scripts/build_executable.sh <output-filename>
# Run from the repo root, with mockymock and nuitka already installed into
# the active Python environment (see the release workflow for the exact
# install steps, including patchelf on Linux and the cobolparser auth
# needed to resolve the git-pinned dependency).
#
# No automated workflow in this repo calls this script anymore -- its
# sole CI caller is now the sibling `mocky-mock-vscode` repo's
# `build-and-release.yml` workflow (cross-repo), which checks out this
# repo at a release tag and runs it. Do not delete this as apparent dead
# code (see PUBLISHING.md's "Local build" section for the other caller:
# a human running it by hand).
set -euo pipefail

OUTPUT_NAME="${1:?usage: build_executable.sh <output-filename>}"

# Without --onefile-tempdir-spec, Nuitka's onefile bootstrap re-unpacks the
# whole payload (mockymock + compiled cobolparser + data files) into a fresh
# temp dir on EVERY launch and deletes it on exit -- a multi-second tax paid
# by each of the several `mockymock`/`mockymock analyze` invocations the VS
# Code extension fires per editor switch (fixtures, analyze program-flow x2,
# etc). Pointing the spec at a stable, version-scoped directory under the
# platform cache dir lets the bootstrap's own payload-hash check skip
# re-extraction on the common case (same build, already unpacked), while
# still safely detecting and re-extracting for a genuinely different build
# that happens to reuse the path (e.g. mockymock's own version string
# unchanged but cobolparser force-reinstalled to a newer tag in CI -- see
# build-and-release.yml's "Force-install cobol-parser's latest release"
# step). {VERSION} comes from --product-version below; Nuitka embeds it and
# substitutes it into the spec.
MOCKYMOCK_VERSION="$(python -c 'from mockymock import __version__; print(__version__)')"

python -m nuitka \
  --onefile \
  --onefile-tempdir-spec="{CACHE_DIR}/mockymock/{VERSION}" \
  --product-version="$MOCKYMOCK_VERSION" \
  --output-dir=build \
  --output-filename="$OUTPUT_NAME" \
  --assume-yes-for-downloads \
  --lto=no \
  --include-data-files=mockymock/runtime/docker/Dockerfile=mockymock/runtime/docker/Dockerfile \
  --include-data-dir=mockymock/web/static=mockymock/web/static \
  packaging/nuitka_entry.py
