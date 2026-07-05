# GnuCOBOL 3.2 toolchain image for mockymock. Built once by
# `mockymock setup` (or implicitly by `mockymock run`) and kept running as
# the long-lived `mockymock-cobc` container with ~/.mockymock/work mounted
# at /work.
FROM debian:trixie-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends gnucobol \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /work
