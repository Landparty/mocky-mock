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
   which is what makes breakpoints on a `.cbl` file work at all for
   line-level stepping. One thing is settled *without* the spike, though:
   whatever file gdb knows about is the **spliced/instrumented** source,
   because that is the file cobc compiles — any `#line` directives name the
   instrumented file and instrumented line numbers, never the user's
   original `.cbl`. So `debug/line_map.py`'s bidirectional
   original ↔ instrumented mapping is needed in every outcome; the genuinely
   open question is narrower: does gdb accept COBOL-file:line breakpoints at
   all (against the instrumented file), or only generated-C locations?
   *Check:* compile a small fixture with `cobc -g -free -x`, run under
   `gdb`, `list <file>.cbl:N`, `break <file>.cbl:N`. While there, also
   observe **step granularity**: one COBOL statement becomes several
   generated-C lines, so a single `next` may stop more than once "inside"
   one COBOL line — if so, the adapter must coalesce steps (keep stepping
   until the mapped line changes), which shapes `gdb_session.py`'s
   DAP-to-MI translation.
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
5. **Will the kernel let gdb trace anything in this container at all?**
   Installing gdb (question 1) and reaching it (question 4) are not enough:
   `ptrace` itself must be permitted. The container runs with `--cap-drop
   ALL` and `no-new-privileges` under Docker's default seccomp profile.
   gdb tracing its *own child* usually works without `CAP_SYS_PTRACE`, but
   the outcome depends on the host's Yama `ptrace_scope` setting and the
   Docker/kernel seccomp vintage — and if it fails, the fix (`--cap-add
   SYS_PTRACE`) deliberately weakens a sandbox the toolchain comments
   describe as load-bearing for running untrusted COBOL. That would be a
   security trade-off decision (see Limitations), not a Dockerfile tweak.
   *Check:* `docker exec -i mockymock-cobc gdb ./binary -ex run` and watch
   for `ptrace: Operation not permitted`.
6. **How does the debuggee's stdout interleave with GDB/MI records?** Over
   `docker exec -i` with no TTY, the inferior's output — including every
   `__MOCKYMOCK__` protocol DISPLAY — is written raw to gdb's stdout, *not*
   reliably wrapped in MI `@`-records, and MI's usual escape hatch
   (`-inferior-tty-set`) needs a tty the container doesn't have. The MI
   parser in `gdb_session.py` must therefore tolerate arbitrary untagged
   lines mid-stream, and the adapter needs a story for routing program
   output as DAP `output` events (or redirecting the inferior's stdout to a
   sandbox file and tailing it). *Check:* run a fixture that DISPLAYs while
   stopped-and-continued under MI, and inspect exactly how the output lands
   between records — this can corrupt MI parsing in ways that would later
   look like flaky bugs.

**This doc's recommendation: do not write the CLI implementation plan until
questions 1-3 and 5 are answered against a real container.** Question 3
could change the shape of `variable_map.py` enough to be worth gating the
whole architecture below on the answer, and question 5 gates the feature's
viability outright.

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
  adapter.py       # DAP server: reads/writes DAP JSON over stdio
  gdb_session.py   # owns the long-lived `docker exec -i ... gdb --interpreter=mi2`
                   # subprocess; translates DAP requests <-> GDB/MI commands
  line_map.py      # bidirectional original <-> instrumented line mapping,
                   # built on splicer/source_map.py + report/coverage.py's
                   # existing (one-directional) machinery
  variable_map.py  # COBOL data item <-> gdb-visible symbol/offset,
                   # shape TBD per empirical question 3 above
```

`gdb_session.py` is the direct analogue of `docker_toolchain.run_binary`,
but stateful: it owns one `subprocess.Popen` for the container's gdb process
for the lifetime of the debug session, writes GDB/MI commands to its stdin,
and reads/parses `^done`/`*stopped`/`~"..."` records from stdout — the same
container, same `mockymock-cobc`, same `_HARDENING_FLAGS`, just a different
interaction pattern than the "run and collect the final result" style every
other function here uses. Two design constraints on it, both from the
empirical questions above:

- **The MI reader must tolerate untagged lines.** Per question 6, the
  inferior's stdout arrives interleaved with MI records on the same pipe;
  any line that is not a recognizable MI record is program output and gets
  forwarded as a DAP `output` event, never treated as a parse error.
- **Stepping is coalesced.** Per question 2, one COBOL statement may span
  several generated-C lines, so a DAP "next" may need to issue multiple MI
  `-exec-next` commands until the mapped original line changes, rather than
  translating one DAP step to one MI step.

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
  the corresponding instrumented line before it can be given to gdb. This
  step is needed in every spike outcome — gdb only ever knows about the
  spliced file cobc actually compiled (see empirical question 2), so there
  is no case where the editor's original-file line numbers can be handed to
  gdb directly. This also means `line_map.py` can be planned and built now,
  independent of the spike; only `variable_map.py` waits on it.
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

**Prior art to check during the spike:** COBOLworx's cbl-gdb (gdb Python
extensions for GnuCOBOL, the machinery behind their VS Code COBOL debugger).
Its existence is itself weak evidence for the pessimistic case — symbol
names alone were evidently not enough for them either — and inspecting how
it recovers COBOL names may answer question 3 faster than probing from
scratch. Not verified here; a spike task, not a dependency.

### CLI surface

`mockymock debug --case NAME [--dap-stdio]` — a real subcommand this time
(unlike trace's deliberate non-subcommand choice), because a DAP server is
not "the same pipeline plus an artifact," it's a fundamentally different,
long-running mode that doesn't share `run`'s flag surface at all. `--case`
is mandatory for the same single-case reason as `--trace`.

`--dap-stdio` runs the adapter directly on stdio (the mode
`DebugAdapterDescriptorFactory` on the extension side spawns). What a
no-flag `mockymock debug` invocation should do is an open question for the
CLI implementation plan: unlike `--trace`'s plain-text mode, there is no
useful human-facing equivalent of a DAP session at a terminal, so the
plausible answers are "DAP-on-stdio is simply the default (drop the flag)"
or "refuse with a message pointing at the extension." It should not
half-start a session a human cannot drive.

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
| *Client* dies mid-debug (VS Code killed, extension crash, stdin closes) | The adapter kills its `docker exec`/gdb subprocess on DAP `disconnect` **and** on its own stdin closing. The gdb process lives inside the shared long-lived `mockymock-cobc` container; a leaked one counts against `PIDS_LIMIT` (512) and can hold sandbox files open, degrading every subsequent normal `run`. |
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
- **Possible sandbox trade-off.** If empirical question 5 finds `ptrace`
  blocked under the current hardening flags, enabling debugging means
  `--cap-add SYS_PTRACE` on the shared container — a deliberate weakening
  of the untrusted-COBOL sandbox that would apply to *all* runs, not just
  debug sessions (the flags live on `docker run`, and the container is
  long-lived). If it comes to that, the decision — and whether it warrants
  a separate debug-only container — gets made explicitly in the CLI plan,
  not absorbed silently as a Dockerfile-adjacent tweak.
- **Shared memory cap.** gdb and the debuggee together live under the
  container's existing 1 GB `MEMORY_LIMIT`. Likely fine, but a
  memory-limit kill mid-session would surface as the "session dies"
  error-handling row, which is exactly where it would otherwise be most
  confusing to diagnose.

## Sequencing

1. **This doc** (architecture, scoped, empirical questions enumerated).
2. **Spike** — a throwaway session against the real `mockymock-cobc`
   container answering empirical questions 1-6. Not shipped code; its
   findings get folded back into this doc (a revision, not a new doc) before
   step 3.
3. **CLI implementation plan** (`docs/superpowers/plans/`), scoped by what
   the spike found — variable mapping in particular may split into its own
   plan if the pessimistic case holds. `line_map.py` does not wait for the
   spike (see Line mapping); it can be specified in full in this plan
   regardless of outcome.
4. **Extension implementation plan**, same split as the trace feature
   (CLI lands first, extension consumes the DAP contract — which here is
   just the DAP spec itself plus the `mockymock debug` launch shape, not a
   bespoke JSON contract like `TRACE_JSON_VERSION`).
