# The LegacyLens change-impact oracle runner: `mockymock runner` with a
# native GnuCOBOL 3.2 toolchain, no Docker-in-Docker. It claims baseline and
# compare jobs from the backend's runner API and runs them; the backend
# itself never compiles COBOL. See docs/2026-11-01-runner-design.md.
#
#   docker build -f docker/runner/Dockerfile -t mockymock-runner .
#   docker run --rm -e LEGACYLENS_URL=http://backend:9999 \
#       -e RUNNER_TOKEN=... mockymock-runner
#
# The jobs run COBOL the backend received in uploads: run the container
# without privileges, with memory and pid limits, and on a network that
# only reaches the backend.
FROM debian:trixie-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        gnucobol gcc libc6-dev python3 python3-venv ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# mockymock's native toolchain wants one GnuCOBOL tree
# (bin/, lib/, include/, share/gnucobol/{config,copy}); Debian spreads the
# package over /usr and /etc, so point a tree of links at it.
RUN set -eu; \
    home=/opt/gnucobol; arch="$(gcc -print-multiarch)"; \
    config="$(dirname "$(find /usr/share /etc -name default.conf -path '*gnucobol*' | head -n 1)")"; \
    mkdir -p "$home/share/gnucobol"; \
    ln -s /usr/bin "$home/bin"; \
    ln -s "/usr/lib/$arch" "$home/lib"; \
    ln -s /usr/include "$home/include"; \
    ln -s "$config" "$home/share/gnucobol/config"; \
    ln -s /usr/share/gnucobol/copy "$home/share/gnucobol/copy"; \
    "$home/bin/cobc" --version | head -n 1

COPY pyproject.toml README.md LICENSE /build/mockymock/
COPY mockymock /build/mockymock/mockymock
RUN python3 -m venv /opt/mockymock \
    && /opt/mockymock/bin/pip install --no-cache-dir /build/mockymock \
    && rm -rf /build

RUN useradd --create-home --uid 10001 runner
USER runner
WORKDIR /home/runner

ENV PATH=/opt/mockymock/bin:$PATH \
    MOCKYMOCK_TOOLCHAIN=native \
    MOCKYMOCK_GNUCOBOL_HOME=/opt/gnucobol \
    PYTHONUNBUFFERED=1

ENTRYPOINT ["mockymock", "runner"]
