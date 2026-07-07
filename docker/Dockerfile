# GnuCOBOL 3.2 toolchain image for mockymock. Built once by
# `mockymock setup` (or implicitly by `mockymock run`) and kept running as
# the long-lived `mockymock-cobc` container with ~/.mockymock/work mounted
# at /work.
#
# The container is launched with runtime hardening flags (--network none,
# --pids-limit, --memory/--memory-swap, --cap-drop ALL --cap-add DAC_OVERRIDE,
# --security-opt no-new-privileges) because it runs untrusted COBOL; see
# `_HARDENING_FLAGS` in mockymock/runtime/docker_toolchain.py and
# `.okf/runtime.md`. Those flags live on `docker run`, not in this image, but
# bumping this file's content hash (which tags the image) forces
# `ensure_toolchain` to rm+recreate any pre-hardening container instead of
# silently reusing it.
FROM debian:trixie-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends gnucobol \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /work
