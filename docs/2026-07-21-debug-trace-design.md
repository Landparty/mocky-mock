# Debug / execution-trace support — design

**Date:** 2026-07-21
**Status:** approved, not yet implemented
**Spans two repos:** `mocky-mock` (CLI, implemented first) and
`mocky-mock-vscode-extension` (consumer).

## Goal

Give a `.cut` test case a **"Debug Test"** action in VS Code that answers the
two questions you actually have when a case fails unexpectedly:

1. **Which of my lines ran, in what order?** — the executed path through the
   original `.cbl`.
2. **Which mocks fired, in what order?** — the mock timeline, with labels.

## Non-goals

- **No breakpoints, no stepping, no live variable inspection.** This is not a
  Debug Adapter Protocol implementation. A real DAP would need `gdb` (or
  `cobc -g`) wired into the container plus bidirectional line mapping, and is
  a separate, much larger project.
- No new `debug` subcommand (see "CLI surface" for why).

## Empirical basis

Everything below rests on behaviour verified directly in the running
`mockymock-cobc` container (GnuCOBOL 3.2.0), not on documentation:

- `cobc -ftraceall` compiles clean but emits **nothing** on its own. GnuCOBOL
  3.x gates trace at *runtime*: `COB_SET_TRACE=yes` is required.
- `COB_TRACE_FILE=<path>` sends trace to its own file. This is the load-bearing
  fact for the whole design: **trace never touches stdout**, so the
  `__MOCKYMOCK__` protocol that `report/results.py` parses stays clean.
  `COB_TRACE_FILE` must always be set explicitly — left unset, trace can leak
  to stderr.
- `COB_TRACE_FORMAT` is templatable. With `%P|%S|%L` the output is:

  ```
  Source: 'spike.cbl'
  Program-Id:  SPIKE
  Program-Id:  SPIKE           |    Entry: SPIKE          |     8
  Program-Id:  SPIKE           |Paragraph: MAIN-PARA      |     8
  Program-Id:  SPIKE           |           MOVE           |     9
  Program-Id:  SPIKE           |           PERFORM        |    10
  ```

  Fields stay space-padded, but the `|` delimiters make parsing unambiguous.
  Two header lines (`Source:`, bare `Program-Id:`) precede the entries and are
  skipped. `%S` carries either `Paragraph: NAME`, `Entry: NAME`, or a bare
  statement verb.
- Line numbers in the trace are **instrumented-source** lines, not original
  `.cbl` lines.

## Architecture: two channels

The two goals above look like one dataset but are not, and conflating them
would fail:

### Channel 1 — executed path (trace file)

Trace-file line numbers are instrumented-source lines and must be remapped.
`mockymock/report/coverage.py::map_coverage_to_original` already does exactly
this (difflib alignment: instrumented → normalized → original) and
**deliberately drops splicer-inserted lines** so the result answers "which of
MY lines ran." That is precisely the semantics wanted here, so this function is
reused as-is.

### Channel 2 — mock firing order (stdout protocol)

Mock firing order **cannot** come from the trace file, because the mock
dispatch blocks *are* splicer-inserted lines and Channel 1's mapper drops them
by design. It is also not available from `--json-report` today:
`report/results.py::parse_stdout` recognizes only `TESTSUITE`, `CASE START`,
`CASE FAIL`, `CASE END`, and `SUMMARY` — no mock or tally events at all.
(The `__MOCKYMOCK__ ERROR:` line `injector.py` emits for an unmocked boundary
is *not* a parsed event; it reaches the user only as raw stdout text plus its
`ADD 1 TO UT-FAIL-COUNT` contribution to the SUMMARY counts.) Adding the mock
timeline therefore means adding a new `_MOCK_RE` to that parser.

Instead, `splicer/injector.py::build_site_dispatch` emits one extra line next
to its existing `ADD 1 TO <tally>`:

```cobol
DISPLAY "__MOCKYMOCK__ MOCK: <site.label>"
```

`site.label` is already in scope there, and the same function already emits a
`__MOCKYMOCK__ ERROR:` DISPLAY a few lines below — so this is a small, local
change on a well-trodden path. Because these land on stdout between the
driver's `CASE START` / `CASE END` markers, per-case attribution is free rather
than something that has to be reconstructed by correlation.

Tally *counts* are not reported separately: they are the number of `MOCK`
events for a label, derived by the consumer.

**Why trace-mode only.** The extra DISPLAY is emitted only when tracing is
requested, so a normal `mockymock run` produces byte-identical spliced output
and stdout to today. This requires threading a `trace: bool` through
`splice_program` → `build_site_dispatch`.

## Design decision: `--trace` requires exactly one selected case

The suite compiles and executes as **one binary across all cases**, so an
unscoped trace file interleaves every case's statements with no marker to
segment them (the trace file and stdout are separate streams with no shared
timestamps).

Therefore `--trace` **refuses unless exactly one case is selected** (via
`--case NAME`), with a message naming the available cases. Attribution then
holds by construction rather than by correlation, and the JSON contract stays
single-case.

*Future extension, deliberately not built now:* the driver's
`DISPLAY "__MOCKYMOCK__ CASE nnn START"` is itself a statement that appears in
the trace at a splice-time-known instrumented line, so the trace could be
segmented by case. YAGNI — the debug action is inherently single-case.

## CLI surface (mocky-mock)

`--trace` / `--trace-json PATH` on `run`, mirroring the existing
`--coverage` / `--coverage-json` pair — including its semantics, verified in
`cli/main.py`: **`--trace-json` implies `--trace`** (exactly as
`args.coverage_json` sets `args.coverage`). `--trace` alone prints a
human-readable executed-path + mock-timeline summary to the console;
`--trace-json PATH` additionally writes the machine-readable contract below.

**Not** a `debug` subcommand: `debug`
would have to duplicate `run`'s entire flag surface (`--copybook-path`,
`--case`, `--tag`, …), whereas the coverage pair is a proven shape in this
codebase for "same pipeline, extra instrumentation, extra artifact."

Plumbing touched:

| Location | Change |
| --- | --- |
| `runtime/docker_toolchain.py::compile_source` | add `trace: bool = False` → appends `-ftraceall`. Direct precedent: the existing `coverage: bool` param appending `--coverage`. |
| `runtime/docker_toolchain.py::run_binary` | pass `-e COB_SET_TRACE=yes`, `-e COB_TRACE_FILE=<sandbox path>`, `-e COB_TRACE_FORMAT='%P\|%S\|%L'` on the `docker exec`. |
| `splicer/injector.py::build_site_dispatch` | trace-mode `DISPLAY "__MOCKYMOCK__ MOCK: <label>"`. |
| `report/results.py` | parse the new `MOCK` line into the per-case result. |
| new `report/trace.py` | parse the trace file, remap via `map_coverage_to_original`, emit the JSON below. |
| `cli/main.py::_cmd_run` | flags, the single-case refusal, artifact write. |

**The trace file must be written inside the bind-mounted sandbox** (`/work/...`,
i.e. under `sandbox_dir(root=docker_toolchain.WORK_ROOT)`), not `/tmp`, so the
host can read it back after the container run.

## The seam: trace-JSON contract

This is the actual cross-repo deliverable — the CLI produces it, the extension
consumes it, and it is versioned so they can move independently.

```json
{
  "version": 1,
  "cutFile": "tests/acctprg.cut",
  "programFile": "src/ACCTPRG.cbl",
  "case": { "name": "posts a credit", "line": 12 },
  "path": [
    { "line": 45, "statement": "MOVE" },
    { "line": 46, "statement": "PERFORM" },
    { "line": 88, "paragraph": "CALC-INTEREST" }
  ],
  "mocks": [
    { "order": 1, "label": "CALL 'CUSTLOOK'" },
    { "order": 2, "label": "READ ACCT-FILE" }
  ],
  "truncated": false
}
```

- `path` — ordered, one entry per traced statement that maps back to an
  original `.cbl` line. Entries whose instrumented line does not map back
  (splicer-inserted) are omitted, per Channel 1's semantics. Paragraph/section
  entries carry `paragraph` instead of `statement`.
- `mocks` — ordered mock firings for this case. Counts are derived by the
  consumer.
- `truncated` — `true` when `path` hit the entry cap (see Limitations).

## Extension design (mocky-mock-vscode-extension)

- Register a third profile on the existing controller in
  `src/testing/testController.ts`: `vscode.TestRunProfileKind.Debug`
  (Run and Coverage already exist), giving the debug icon on each `TESTCASE`.
- The profile runs `mockymock run … --case <name> --trace-json <tmp>` —
  `--case` is mandatory here, both to satisfy the CLI refusal and because it is
  what makes the trace meaningful.
- New `src/testing/traceReport.ts` parses and validates the contract, mirroring
  the existing `jsonReport.ts` / `coverageReport.ts` modules.
- Rendering: the executed path highlighted against the original `.cbl`, plus
  the mock timeline in order.

**Graceful degradation is required.** An installed `mockymock` predating
`--trace-json` must produce a clear "your mockymock is too old for debug"
message, never a crash or a silent empty view. Precedent:
`discoverSuites` already falls back when the CLI is too old for `collect`.
Stale globally-`uv tool install`-ed CLIs are a known live hazard in this
project, so this path is real, not theoretical.

## Error handling

| Condition | Behaviour |
| --- | --- |
| `--trace` with 0 or 2+ cases selected | Refuse before Docker, list available cases. |
| Trace file missing/empty after run | Report it; do not emit a JSON file implying an empty path. |
| Binary crashed mid-case | Trace up to the crash point is still valid and is reported — this is the highest-value debug case. |
| Trace line unmappable to original | Omitted from `path` (expected: every injected line). |
| CLI too old (extension) | Clear message; no crash, no empty view. |

## Testing

- **Unit:** trace-format parser (including the two header lines, padded fields,
  `Paragraph:`/`Entry:` vs bare verbs); JSON contract shape; the single-case
  refusal; `MOCK` protocol-line parsing.
- **Integration (Docker-gated, per `.okf/testing.md`):** a fixture program run
  with `--trace-json`, asserting the path matches the known execution order and
  the mock timeline matches the `.cut`'s directives.
- **Regression:** a normal `run` (no `--trace`) must produce byte-identical
  spliced source and stdout to today — this is what makes trace-mode-only
  gating worth its complexity.
- **Extension:** unit tests for `traceReport.ts` parsing and for the
  too-old-CLI degradation path.

## Limitations (accepted, flagged, not engineered around)

- **Trace volume.** A `PERFORM UNTIL` with many iterations produces a very
  large trace. Mitigation is a simple entry cap with `truncated: true`, not
  streaming or sampling.
- **Timeout pressure.** Trace writing adds runtime overhead, eating into
  `run_binary`'s 30s default. Acceptable for single-case debugging; revisit
  only if it bites in practice.
- **GnuCOBOL semantics, not IBM.** Unchanged from the standing fidelity ceiling
  (readiness-audit Finding 1) — a trace shows what GnuCOBOL did.

## Sequencing

One spec (this document), two implementation plans. The CLI lands first
because the extension depends on the contract; the extension plan follows.
