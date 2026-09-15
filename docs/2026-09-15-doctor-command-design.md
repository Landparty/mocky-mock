# `mockymock doctor`: one command for "is my setup okay?" (2026-09-15)

## Problem

Checking whether mockymock is ready to run is currently spread across
three places that don't talk to each other:

1. `mockymock setup` builds the image and starts the container, but has
   no `--check`/dry-run mode and no flags at all
   (`mockymock/cli/main.py:13-26`, `setup --help` prints only `-h`)
   -- it mutates (build/start) rather than reports.
2. `mockymock dashboard` serves a loopback web page backed by
   `runtime/status.py`'s `probe() -> ToolchainStatus`, which is read-only
   by design (`status.py`'s own docstring: "nothing here mutates
   anything") and checks Docker daemon reachability, image presence,
   container state, and `cobc --version`
   (`_probe_daemon`/`_probe_image`/`_probe_container`/`_probe_cobc`,
   `status.py:75-166`). This is exactly the right data, but only
   reachable through a browser.
3. `mocky-mock-vscode` has its own, separate "Check Setup" walkthrough
   step and command (`mockymock.checkEnvironment`,
   `src/environment/checks.ts`) that re-implements capability probing by
   shelling out to `mockymock ... --help`/`--version` per subcommand
   (`checks.ts:58-116,238`) -- a third, independent implementation of
   "is this usable right now."

A terminal user with a broken setup has to either start a local web
server and open a browser (`dashboard`) or run `setup` and hope the
build/start logs explain the problem. Neither gives a fast, scriptable,
terminal-native yes/no with fix suggestions.

## Goals

- One command, `mockymock doctor`, gives a terminal-native pass/fail
  report of everything needed to run a suite, reusing the *existing*
  read-only probe rather than a fourth implementation of it.
- Each failing check names the fix (matching this repo's existing
  "actionable error, not a traceback" convention --
  `_check_input_files`/`_check_rows_non_negative` above).
- `doctor` is safe to run anytime, including in CI, with a `--json` mode
  and a meaningful exit code (0 = ready, 1 = not ready) for scripting.
- `init` (see `2026-09-15-init-command-design.md`) and a future "offer to
  build the toolchain on first `run`" both call the same underlying probe
  function `doctor` uses -- one source of truth for "is this ready,"
  reused by three call sites (the CLI command itself, `init`'s
  Docker-available branch, and `dashboard`'s existing consumer).

## Non-goals

- `doctor` never builds an image, starts a container, or otherwise
  mutates state -- that's `setup`'s job, unchanged. `doctor` may
  *suggest* running `mockymock setup`, never run it itself.
- `dashboard` is not removed or deprecated; it stays useful for anyone
  who wants a persistent status page (e.g. left open during a long
  editing session). `doctor` is the one-shot terminal equivalent.
- No change to `mocky-mock-vscode`'s own `checkEnvironment` command in
  this iteration beyond noting the shared-probe opportunity below as a
  fast-follow; the extension's checks also probe subcommand-level
  capability (`--help` per subcommand, useful for version-skew detection
  against an older installed CLI), which is a different, complementary
  concern from "is the toolchain up."

## Design

### What `doctor` checks

Reuses `mockymock.runtime.status.probe()` verbatim -- no new probing
logic. Its four checks already cover the whole `ensure_toolchain`
lifecycle (`.okf/runtime.md`'s table): Docker daemon reachable, image
present/current, container running, `cobc` version detectable.

`doctor` adds two checks `status.probe()` doesn't own, both cheap and
read-only:
- **cobol-parser importable and version-compatible** -- import
  `cobolparser`, read `__version__`, compare against the floor mockymock
  pins (`pyproject.toml`'s dependency spec) -- surfaces the exact failure
  mode `interface-contract.md`'s version-probing fallbacks exist to
  tolerate, but as a clear message instead of a silent capability
  downgrade.
- **Config file found (if any)** -- reports which `mockymock.toml`/
  `pyproject.toml` (from `2026-09-15-cli-ergonomics-design.md`) was
  loaded, if either design lands first the other builds on it; this line
  is silently omitted if that design hasn't landed yet, so the two are
  not a hard sequencing dependency.

### Output

Text mode (default), one line per check, worst-first ordering (matching
`status.py`'s own `OK`/`WARN`/`DOWN`/`UNKNOWN` severity ordering):

```
$ mockymock doctor
[FAIL] Docker daemon        not reachable
       -> Start Docker Desktop (or the docker service), then re-run.
[SKIP] GnuCOBOL image       unknown (daemon unreachable)
[SKIP] mockymock-cobc       unknown (daemon unreachable)
[SKIP] cobc version         unknown (daemon unreachable)
[ OK ] cobol-parser         importable, 2026-09-15 release (>= required 2026-08-01)
[ OK ] config file          ./mockymock.toml

mockymock doctor: not ready -- fix the Docker daemon check above, then
re-run 'mockymock doctor' or 'mockymock setup'.
```

`--json` mode emits `ToolchainStatus.to_dict()` (already a stable,
explicit wire shape per its own docstring) plus the two doctor-only
checks appended to the same `checks` list, so any consumer already
parsing `dashboard`'s JSON (`.okf/dashboard.md`) can add `doctor` as an
equivalent source with no shape change.

Exit code: 0 if every check is `OK` (or `WARN` for something usable but
not ideal, e.g. an older cobol-parser still within a tolerated floor);
1 if anything is `DOWN`/`FAIL` or a hard version-floor violation.

### Reuse, not fork

- `mockymock/runtime/status.py`'s `probe()` stays exactly as-is (it is
  already correctly read-only and fast, per its own docstring's
  rationale for short timeouts).
- New module `mockymock/cli/doctor.py`: `gather_full_status() ->
  DoctorReport` (wraps `status.probe()` and appends the two cobol-parser/
  config checks), `format_doctor_text(report)`, `format_doctor_json(report)`.
  `_cmd_doctor` in `main.py` is a thin wrapper calling these.
- `_cmd_init` (from the `init` design) imports `gather_full_status`
  directly rather than shelling out to `mockymock doctor` as a
  subprocess -- same in-process reuse principle as everywhere else in
  this CLI.

### Fast-follow noted, not built here

`mocky-mock-vscode`'s `checkEnvironment` command could eventually call
`mockymock doctor --json` instead of its own multi-subprocess `--help`
probing for the toolchain-level checks (keeping its own subcommand
`--help` probing for CLI-version/capability skew, which `doctor` doesn't
cover). Left as a follow-up in that repo rather than bundled here, since
it's a net simplification of already-working code with its own review
surface.

## Implementation steps

1. `mockymock/cli/doctor.py`: `DoctorCheck` (reuses `status.Check`'s
   shape), `DoctorReport` (wraps `ToolchainStatus` plus the two extra
   checks), `gather_full_status()`, `format_doctor_text()`,
   `format_doctor_json()`.
2. `mockymock/cli/main.py`: new `doctor` subparser (`--json` flag only,
   no other options -- keep it a zero-config, always-safe command), wired
   to `_cmd_doctor`.
3. Add `doctor` to the "Diagnosing a failure" help group from
   `2026-09-15-cli-ergonomics-design.md`.
4. `.okf/dashboard.md`: cross-reference `doctor` as the CLI-native
   equivalent of the same probe.
5. `docs/options-reference.md`, README's "Beyond pass/fail" section: add
   `doctor` alongside `dashboard`.
6. `.okf/log.md`: dated entry.

## Testing plan

- Unit: `gather_full_status()` with `status.probe` mocked to return each
  of daemon-down / image-missing / container-down / all-ok, asserting
  the doctor-only checks (cobol-parser version, config file) run and
  report correctly regardless of toolchain state (they don't depend on
  Docker).
- Unit: `format_doctor_text`/`format_doctor_json` snapshot tests for the
  worst-first ordering and exit-code derivation.
- Unit: cobol-parser version check against a monkeypatched
  `cobolparser.__version__` below/at/above the pinned floor.
- Integration (Docker-gated): `mockymock doctor` against the real
  toolchain reports all-`OK` after `mockymock setup` has run, matching
  what `mockymock dashboard`'s JSON endpoint reports at the same moment
  (cross-check the two surfaces agree, since they now share the same
  `status.probe()` call).

## Backward compatibility

New subcommand, zero interaction with any existing command's behavior or
output. `status.py`, `dashboard`, and `setup` are unchanged.
