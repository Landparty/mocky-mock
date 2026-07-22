# Interactive debugger (Debug Adapter Protocol) — design

**Date:** 2026-07-22
**Status:** proposed — core empirical question (variable mapping) not yet
verified, see "Empirical basis"
**Spans two repos:** `mocky-mock` (CLI/DAP server, implemented first) and
`mocky-mock-vscode-extension` (consumer).

## Relationship to the execution-trace feature

`docs/2026-07-21-debug-trace-design.md` shipped a **"Debug (Execution
Trace)"** action the day before this doc: executed path + mock firing order,
read-only, after the fact. It explicitly scoped this out:

> No breakpoints, no stepping, no live variable inspection. This is not a
> Debug Adapter Protocol implementation. A real DAP would need `gdb` (or
> `cobc -g`) wired into the container plus bidirectional line mapping, and is
> a separate, much larger project.

This doc is that separate, much larger project. It does not replace the
trace feature — trace stays the fast, always-available answer to "what ran";
this is for the slower, heavier case of "why did line 88 do the wrong
thing," where the user needs to stop execution and look.

## Repo placement

Per `2026-07-22-debugger-repo-structure` (chat decision, not a separate doc):
this lives in the existing two repos, not a new one. The DAP server sits in
`mocky-mock` because it needs the same Docker toolchain, splicer line-mapping,
and sandbox machinery `runtime/docker_toolchain.py` and `splicer/source_map.py`
already own; a third repo would either duplicate that or require extracting a
shared library neither repo currently has. The extension side is a new
consumer module in `mocky-mock-vscode`, following the same shape as the trace
feature's `traceReport.ts` + third test-run profile.

## Goal

A **"Debug"** launch configuration in VS Code for a `.cut` case that gives:

1. Breakpoints on original `.cbl` lines.
2. Step over / step into / continue, mapped through `PERFORM` boundaries.
3. A call stack in terms of COBOL paragraphs/sections, not generated C.
4. Variable inspection of COBOL data items (working-storage, linkage) by
   their COBOL names, with COBOL-shaped values (e.g. a `PIC 9(5)V99 COMP-3`
   item rendered as a decimal, not raw bytes).

## Non-goals (this version)

- **Multi-program / dynamic CALL stepping into a mocked boundary.** A mocked
  `CALL` never reaches real callee code (that is the entire point of
  mockymock) — stepping "into" one should skip straight past it, the same way
  the trace feature only reports paths through the caller's own lines. Making
  step-into behave correctly across an *unmocked* nested program is future
  work.
- **Conditional/data breakpoints, watchpoints.** Line breakpoints only, v1.
- **Multi-case debug sessions.** Same constraint as `--trace`: exactly one
  `--case` selected, for the same reason (one binary, one execution stream,
  no cross-case segmentation marker).
- **Editing variables while stopped.** Read-only inspection first; write
  support (DAP `setVariable`) is a straightforward follow-on once read
  mapping works, not bundled into v1 scope.

## Empirical basis — **NOT YET VERIFIED**

The trace design doc earned its confidence by running real commands against
the live `mockymock-cobc` container before writing a line of the contract
(`COB_SET_TRACE`, `COB_TRACE_FORMAT`, etc. were all confirmed empirically,
not from documentation). This doc could not do the same: **the Docker daemon
is unreachable in the environment this doc was drafted in** (`docker info`
fails), so nothing below is verified against a running container. Treat
every claim in this section as a hypothesis to confirm in the spike this doc
recommends before any implementation plan is written.

Open questions the spike must answer, each with the concrete way to check it:

1. **Does the `mockymock-gnucobol` image even have a debugger in it?**
   `runtime/docker/Dockerfile` currently installs only the `gnucobol` apt
   package. Debian's `gnucobol` package does not pull in `gdb` as a
   dependency. *Check:* `docker exec mockymock-cobc which gdb gdbserver` —
   almost certainly both need adding to the Dockerfile (`apt-get install -y
   gdb gdbserver`), which bumps the image content hash and forces
   `ensure_toolchain` to rebuild (existing mechanism, no new code needed for
   that part).
2. **Does `cobc -g` (GnuCOBOL's debug flag) emit DWARF that maps back to
   COBOL source lines, or only to the generated C?** GnuCOBOL transpiles
   COBOL → C → native via gcc, so `-g` debug info is fundamentally *C* debug
   info. GnuCOBOL is known (from public docs, not verified here) to emit
   `#line` directives in the generated C mapping back to COBOL source lines,
   which is what makes `gdb --cd` breakpoints on the `.cbl` file work at all
   for line-level stepping. *Check:* compile a small fixture with `cobc -g
   -free -x`, run under `gdb`, `list <file>.cbl:N`, `break <file>.cbl:N`,
   confirm gdb accepts COBOL-file:line breakpoints directly (this would mean
   the line-mapping problem is *partially* solved by gdb itself, changing
   the scope of `debug/line_map.py` from "translate all line numbers" to
   "translate only splicer-inserted-line edge cases").
3. **What do COBOL data items look like to gdb?** This is the actual open
   risk. GnuCOBOL's generated C represents working-storage as a byte buffer
   (`cob_field` structures) with generated field names — `gdb print
   b_1.WS_CUSTOMER_ID` or similar, not guaranteed. *Check:* compile a
   fixture with a few data items of different PICTURE clauses (`PIC
   X(10)`, `PIC 9(5)V99 COMP-3`, `PIC S9(4) COMP`), stop at a breakpoint
   after they're populated, `info locals` / `info variables`, and inspect
   whether generated symbol names have any COBOL-name correspondence or are
   fully mangled (`b_1`, `f_3`, positional only). If fully mangled, the
   mapping has to come from GnuCOBOL's own `.lst`/listing output or a
   `cob_field` layout table cobc can be asked to emit — not from symbol
   names at all. This determines whether `debug/variable_map.py` is a
   symbol-name lookup (cheap) or a byte-offset-into-buffer decoder using the
   `PictureClause` info `cobol-parser`'s AST already carries for each
   `CobolDataItem` (much more work, but buildable — the picture-to-byte-layout
   math already exists for COMP-3/COMP encoding in DATA DIVISION handling).
4. **Can gdb run non-interactively via MI (`--interpreter=mi2`) over `docker
   exec -i`, or does the container's lack of a TTY / gdbserver's networking
   model force a different transport (exposed port + `target remote`)?**
   *Check:* both spellings against the running container; the hardening
   flags (`--network none`) in `_HARDENING_FLAGS` block any TCP-based
   approach (`gdbserver :PORT`) from being reachable from the host at all,
   which likely forces the MI-over-stdio approach regardless of preference.

**This doc's recommendation: do not write the CLI implementation plan until
questions 1-3 are answered against a real container.** Question 3 in
particular could change the shape of `variable_map.py` enough to be worth
gating the whole architecture below on the answer.

## Architecture (provisional, pending the spike above)

### Session model — the shape change from trace

Every existing Docker-toolchain function (`compile_source`, `run_binary`,
`run_gcov`) is synchronous: invoke `docker exec`, wait, return a result. A
debug session is not — it is a long-lived conversation (set breakpoints,
continue, stop, inspect, continue again) that must stay alive across many
DAP requests. This is the one genuinely new shape in the codebase, not a
new flag on an existing function:

```
mockymock/debug/
  adapter.py        # DAP server: reads/writes DAP JSON over stdio
  gdb_session.py     # owns the long-lived `docker exec -i ... gdb --interpreter=mi2`
                      # subprocess; translates DAP requests <-> GDB/MI commands
  line_map.py        # bidirectional original <-> instrumented line mapping,
                      # built on splicer/source_map.py + report/coverage.py's
                      # existing (one-directional) machinery
  variable_map.py     # COBOL data item <-> gdb-visible symbol/offset,
                      # shape TBD per empirical question 3 above
```

`gdb_session.py` is the direct analogue of `docker_toolchain.run_binary`,
but stateful: it owns one `subprocess.Popen` for the container's gdb process
for the lifetime of the debug session, writes GDB/MI commands to its stdin,
and reads/parses `^done`/`*stopped`/`~"..."` records from stdout — the same
container, same `mockymock-cobc`, same `_HARDENING_FLAGS`, just a different
interaction pattern than the "run and collect the final result" style every
other function here uses.

### Toolchain changes

| Location | Change |
| --- | --- |
| `runtime/docker/Dockerfile` | add `gdb` (and `gdbserver` if question 4 needs it) to the `apt-get install` line. Bumps the image content hash automatically (existing mechanism). |
| `runtime/docker_toolchain.py::compile_source` | add `debug: bool = False` → appends `-g`, same pattern as `coverage`/`trace`. Orthogonal to `trace`; a debug session does not also need `-ftraceall`. |
| `runtime/docker_toolchain.py` | new `start_gdb_session(binary_path) -> GdbSession` (or similar), returning a live handle instead of a completed result — the first function in this module that does not follow the "run to completion" pattern. |

### Line mapping

`splicer/source_map.py` and `report/coverage.py::map_coverage_to_original`
already solve "instrumented line → original line, dropping splicer-inserted
lines," one-directional, for after-the-fact reports. A debug session needs
the same mapping used **live** and in the **reverse direction**:

- Setting a breakpoint: DAP gives an original `.cbl` line; must resolve to
  the corresponding instrumented line before it can be given to gdb (or, if
  empirical question 2 confirms gdb accepts COBOL-file:line breakpoints
  directly against the *original* filename embedded in `#line` directives,
  this step may not be needed at all — one of the biggest open unknowns).
- A breakpoint on a line the splicer touched (e.g. a mocked boundary's
  dispatch block) has no single sensible original-line answer; the existing
  span/boundary data in `splicer/source_map.py::statement_span` and
  `ScopeMap` already models exactly this "does this line own its own
  statement" question and should be reused to reject or relocate such
  breakpoints rather than inventing new logic.
- Reporting a stack frame: instrumented line → original line, reusing
  `map_coverage_to_original` as-is (same function the trace feature reuses).

### Variable mapping

Deliberately left unspecified pending empirical question 3. Two candidate
designs bracket the range:

- **If gdb exposes COBOL-ish symbol names directly** (optimistic case):
  `variable_map.py` is a thin name-normalization lookup, comparable in
  complexity to `line_map.py`.
- **If gdb only exposes raw C buffers** (pessimistic case): `variable_map.py`
  must decode each `CobolDataItem`'s `PictureClause` (already parsed by
  cobol-parser and available on the AST) into a byte offset and
  COMP/COMP-3/display decoding, and DAP `variables` responses are
  synthesized from raw memory reads (`gdb -x memory` / MI `-data-read-memory`)
  rather than symbol lookups. This is materially more work and would likely
  become its own implementation plan rather than a subsection of the CLI
  plan.

### CLI surface

`mockymock debug --case NAME [--dap-stdio]` — a real subcommand this time
(unlike trace's deliberate non-subcommand choice), because a DAP server is
not "the same pipeline plus an artifact," it's a fundamentally different,
long-running mode that doesn't share `run`'s flag surface at all. `--case`
is mandatory for the same single-case reason as `--trace`.

`--dap-stdio` runs the adapter directly on stdio (the mode
`DebugAdapterDescriptorFactory` on the extension side spawns); without it,
`mockymock debug` could still print a human-readable "session started, DAP
server listening on stdio" message for manual/non-VS Code use, mirroring how
`--trace` (no `-json`) has a plain-text mode today.

### Extension design (mocky-mock-vscode)

- New `src/debug/` module: a `vscode.DebugAdapterDescriptorFactory` returning
  an `Executable` that runs `mockymock debug --case <name> --dap-stdio`, and
  a minimal `DebugConfigurationProvider` for a `mockymock-cobol` launch type.
- This is **additive** to the existing `Debug (Execution Trace)` test-run
  profile (`testController.ts:656`), not a replacement — trace stays the
  fast default; true DAP debugging is reached via a launch config or a
  distinct command, consistent with how VS Code users expect `Run and
  Debug` to work versus the Test Explorer's inline debug icon. Exact UX
  entry point (a 4th test profile invoking `vscode.debug.startDebugging`,
  vs. a command-palette action, vs. a `launch.json` snippet) is a decision
  for the extension implementation plan, not this doc.
- Reuses the version-gate pattern from `environment/checks.ts`
  (`supportsTraceFlag`) — add `supportsDebugCommand` — for graceful
  degradation against a `mockymock` install that predates `debug`.

### Error handling

| Condition | Behaviour |
| --- | --- |
| `debug` with 0 or 2+ cases selected | Refuse before Docker, list available cases (same as `--trace`). |
| Breakpoint on a splicer-owned/unspliceable-adjacent line | Reject with a specific reason, reusing `unspliceable_reason`-style messaging from `source_map.py`, not a silent no-op. |
| gdb/gdbserver missing from the image | Clear "toolchain needs rebuilding" error from `ensure_toolchain`-equivalent logic, not a raw `docker exec` failure. |
| Session dies mid-debug (container killed, gdb crashes) | DAP `terminated`/`exited` events sent to the client; no hang. |
| CLI too old (extension) | Same clear-message pattern as trace's degradation path. |

### Testing

- **Spike first** (see Empirical basis) — not automated tests, a throwaway
  script/session against the live container, whose findings get folded back
  into this doc before an implementation plan is written.
- **Unit:** GDB/MI response parsing in `gdb_session.py`; line-map
  bidirectional round-trip; variable-map decoding (shape depends on spike
  outcome).
- **Integration (Docker-gated):** a fixture program, set a breakpoint, step
  through a few statements, assert stack/variable values match known state —
  the debugger equivalent of the trace feature's fixture-run assertion.
- **Regression:** a normal `run` and `--trace` must stay byte-identical;
  `debug` is fully additive (new subcommand, new Dockerfile packages, no
  changes to existing compile/run paths when `debug=False`).

### Limitations (accepted up front)

- **GnuCOBOL semantics, not IBM** — same standing fidelity ceiling as every
  other mockymock feature (readiness-audit Finding 1).
- **No stepping into unmocked nested programs** in v1 (see Non-goals).
- **Single-case only**, same structural reason as `--trace`.
- **Startup latency.** A gdb-attached debug session is materially slower to
  start than a plain `run` (compile with `-g`, launch gdb, wait for the
  first stop) — acceptable for an interactive debugging action the user
  chose to invoke, not something to optimize for in v1.

## Sequencing

1. **This doc** (architecture, scoped, empirical questions enumerated).
2. **Spike** — a throwaway session against the real `mockymock-cobc`
   container answering empirical questions 1-4. Not shipped code; its
   findings get folded back into this doc (a revision, not a new doc) before
   step 3.
3. **CLI implementation plan** (`docs/superpowers/plans/`), scoped by what
   the spike found — variable mapping in particular may split into its own
   plan if the pessimistic case holds.
4. **Extension implementation plan**, same split as the trace feature
   (CLI lands first, extension consumes the DAP contract — which here is
   just the DAP spec itself plus the `mockymock debug` launch shape, not a
   bespoke JSON contract like `TRACE_JSON_VERSION`).
