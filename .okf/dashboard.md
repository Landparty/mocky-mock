---
type: Module
title: Web Dashboard
description: mockymock dashboard — a loopback-only static page that polls a read-only Docker toolchain health probe, plus the runtime.status probe behind it.
tags: [cli, web, docker, runtime]
timestamp: 2026-09-15T00:00:00Z
---

# Overview

`mockymock dashboard` serves a small static web page on loopback that
answers one question live: **is Docker running, and is the GnuCOBOL
toolchain ready?** It is the eyes-version of what `mockymock setup`
already prints as text, minus the side effects.

**`mockymock doctor` (2026-09-15, `cli/doctor.py`)** is the terminal-native
equivalent: same `runtime.status.probe()`, no browser or HTTP server, plus
two checks of its own (cobol-parser importability, which project config
file this invocation would load). `--json` for scripting; exits 0 when
ready, 1 otherwise -- where doctor's `ready` is "no check is `DOWN`" (a
`WARN` such as a stopped container or a malformed config file still
exits 0, since `setup`/the next `run` sorts it out; this is looser than
`probe()`'s own `ready`, which is `all(state == ok)`). Never builds or
starts anything, same as this page.
See docs/2026-09-15-doctor-command-design.md.

```
mockymock dashboard [--port N] [--no-browser]
   │
   └─ web/server.py   ThreadingHTTPServer bound to 127.0.0.1
         ├─ GET /            -> web/static/index.html  (+ /app.js, /style.css)
         └─ GET /api/status  -> runtime/status.py probe() -> JSON
                                   docker info
                                   docker image inspect <IMAGE>
                                   docker inspect <CONTAINER>
                                   docker exec <CONTAINER> cobc --version
```

The page polls `/api/status` every 5s and renders a verdict banner, one
row per check, and the image/container/compiler details. It holds no state
of its own — every render is a function of the last payload — so a future
panel is a new render function plus a new key in the payload.

# Two constraints that shaped it

**The probe is read-only, and that is load-bearing.**
`runtime/status.py` deliberately does *not* call
`docker_toolchain.ensure_toolchain()`, even though the checks mirror its
lifecycle table 1:1 (see [runtime](runtime.md)). `ensure_toolchain` builds
images, `docker rm -f`s stale containers, and creates containers; a page
polling it every five seconds would kick off image rebuilds from a browser
refresh. The probe only reports what `ensure_toolchain` *would* find,
using `docker info` / `docker image inspect` / `docker inspect`, all pure
reads. `tests/unit/test_web_dashboard.py::test_probe_never_mutates_the_toolchain`
pins this.

**The bind address is 127.0.0.1 and is not configurable.** The endpoint
has no authentication and reports local Docker state; `0.0.0.0` would hand
that to the network for nothing. No CORS headers are sent, so the browser's
same-origin policy also keeps other pages from reading it. `--port` is
configurable (`0` picks a free one, which is what the tests use); the host
is not.

# Check states

`probe()` returns a `ToolchainStatus` whose `checks` are four `Check`
records — `daemon`, `image`, `container`, `cobc` — each with a state:

| State | Meaning |
|-------|---------|
| `ok` | the step would succeed |
| `warn` | the container exists but is stopped, or was created from a stale image tag — `mockymock setup` fixes it |
| `down` | the step would fail outright (daemon unreachable, image never built, container absent, cobc broken inside the image) |
| `unknown` | an earlier step failed, so this one was never reached |

`ready` is `all(state == ok)`. Checks **short-circuit**: if the daemon is
down, the remaining three report `unknown`, not `down` — reporting
"container missing" when Docker itself isn't running is noise, not
information.

The `warn` states map exactly onto the two conditions `ensure_toolchain`
step 3 repairs (stopped container -> `docker start`; container created
from a different image tag -> `rm -f` + recreate), which is why the page
tells the user to run `mockymock setup` rather than offering a button.

# JSON contract

`/api/status` returns `ToolchainStatus.to_dict()`, written out explicitly
rather than via `asdict(self)` because the page depends on the shape:

```json
{
  "ready": false,
  "checked_at": "2026-08-03T14:43:18+00:00",
  "image": "mockymock-gnucobol:f5a524ee",
  "container": "mockymock-cobc",
  "cobc_version": null,
  "checks": [{"id": "daemon", "label": "Docker daemon",
              "state": "down", "detail": "failed to connect ..."}]
}
```

New fields are additive; existing ones don't move.

# Asset packaging

`web/static/` lives **inside the package** and is resolved via
`Path(__file__).resolve().parent / "static"`, with
`"mockymock.web" = ["static/*"]` in pyproject's
`[tool.setuptools.package-data]`. This is the same constraint the
Dockerfile is under (see [runtime](runtime.md)): setuptools packages
nothing outside `mockymock/`, so a repo-root `web/` directory would ship
in an editable install and 404 under a real `uv tool install`.
`test_static_assets_are_bundled_under_the_package` guards it — but only in
a source checkout, which is where that test always passes. **Three
distribution modes, three separate mechanisms:**

| Mode | Mechanism | Verified by |
|------|-----------|-------------|
| editable / source | files sit next to `server.py` | `test_static_assets_are_bundled_under_the_package` |
| wheel (`pip`/`uv tool install`) | `[tool.setuptools.package-data]` `"mockymock.web" = ["static/**/*"]` | confirmed present in a built wheel (2026-08-03) |
| Nuitka onefile binary | `--include-data-dir=mockymock/web/static=...` in `scripts/build_executable.sh` | the `Dashboard serves its bundled static assets` step in the sibling `mocky-mock-vscode` repo's `build-and-release.yml` |

The third is the one that bites: **Nuitka does not read
`package-data`**, so an asset can ship correctly in the wheel and still be
absent from the released executables — the primary artifact — while every
unit test passes. Any future non-`.py` file resolved via `Path(__file__)`
needs its own `--include-data-*` flag in `build_executable.sh`, and the CI
step above (now in the sibling `mocky-mock-vscode` repo's
`build-and-release.yml`, since this repo's own reusable build workflow
that used to run it is deleted) is what proves it (it curls `/`,
`/style.css`, `/app.js`, and `/api/status` out of the freshly built binary
on all three platforms).

# Gotchas

**`PROBE_TIMEOUT` is 15s, not the toolchain's 600s.** A dashboard poll
that hangs for ten minutes is worse than one that reports "unreachable" —
but it also means a genuinely slow-but-alive daemon can be reported `down`.
The detail text carries the underlying error either way.

**`protocol_version = "HTTP/1.1"` obliges every response to set
`Content-Length`.** All of them do, via the single `_send` helper. A future
handler branch that writes to `self.wfile` directly would make the browser
hang on that poll rather than error.

**Static paths are checked for containment after `resolve()`, not by
string inspection.** `..` traversal and (on Windows) an absolute drive path
smuggled in as `/C:/...` both survive the `STATIC_DIR / relative` join;
`is_relative_to(STATIC_DIR)` is what actually rejects them.

**Polling pauses on a hidden tab.** Each poll shells out to `docker` three
or four times; a background tab left open overnight would otherwise keep
doing that. Re-showing the tab triggers an immediate refresh.

# See Also

- [runtime](runtime.md) — the `ensure_toolchain` lifecycle these checks
  mirror, and the image/container constants the probe reports.
- [cli](cli.md) — subcommand wiring.
- [testing](testing.md) — the unit/integration split this feature's tests
  sit in (all docker-mocked, so they run without a daemon).
