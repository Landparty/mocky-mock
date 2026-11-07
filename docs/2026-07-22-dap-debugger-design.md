# Interactive debugger (Debug Adapter Protocol) — design

**Date:** 2026-07-22 (revised 2026-07-22 after the spike)
**Status:** spiked — empirical questions 1-6 verified against a real
container; one additional finding (call stack synthesis, not anticipated in
the original doc) also verified. See "Empirical basis" for what changed.
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

## Empirical basis — **VERIFIED 2026-07-22**

The trace design doc earned its confidence by running real commands against
the live `mockymock-cobc` container before writing a line of the contract.
This doc originally could not do the same because the Docker daemon was
unreachable when it was drafted. The daemon is reachable now; every claim
below was checked directly against a hardened container running the
production `_HARDENING_FLAGS`, GnuCOBOL 3.2.0, gdb 16.3, against a small
fixture (`SPIKE` program with a `PIC X(10)`, a `PIC 9(5)V99 COMP-3`, and a
`PIC S9(4) COMP` item, a `PERFORM VARYING` loop, and a performed paragraph).

1. **Does the image have a debugger in it? YES, once added.** Debian
   `trixie-slim`'s `gnucobol` package does not pull in gdb. Adding `gdb
   gdbserver` to the Dockerfile's `apt-get install` line installs both
   cleanly (`which gdb gdbserver` resolves) with no dependency conflicts
   against `gnucobol`. Done in this revision — see "Toolchain changes".
   `gdbserver` was installed for completeness but nothing below ended up
   needing it; the MI-over-stdio transport (question 4) works directly.
2. **Does `cobc -g` map breakpoints back to `.cbl` lines? YES, but the
   stepping model is more specific than "several C lines per statement."**
   `gdb break fixture.cbl:N` and `list fixture.cbl:N` both work directly
   against the file `cobc` compiled (the splicer's instrumented file, in
   production — see "Line mapping"). Inspecting the generated `.c` confirms
   why: each COBOL statement compiles to an alternating pair — a `#line N
   "fixture.cbl"` directive attached to a `cob_nop()` marker call, followed
   immediately by a `#line M "fixture.c"` directive covering the real work
   (`memcpy`, `cob_move`, `cob_add`, …) for that same statement. A single MI
   `-exec-next` from the marker steps forward exactly one line — landing on
   the **generated-C body line for the same statement**, not the next
   statement's marker. The next `-exec-next` from there lands on the *next*
   statement's `.cbl` marker. So stepping one COBOL statement is a fixed
   2-step sequence for a simple non-branching MOVE/ADD (`marker → body →
   next marker`), confirmed by direct observation; statements with internal
   control flow (loops, conditionals, PERFORM dispatch) are expected to
   insert more generated-C lines between markers, not verified here.
   **Conclusion for `gdb_session.py`:** coalesce by continuing to issue
   `-exec-next`/`-exec-step` while the current frame's `file` is anything
   other than the original `.cbl` (or the spliced-source path in
   production), stopping on the first frame that reports a `.cbl` file
   again — not by comparing line numbers, and not by counting a fixed
   number of steps.
3. **What do COBOL data items look like to gdb? Neither of the doc's two
   predicted outcomes — a third, cheaper path exists.** `print
   WS_CUSTOMER_ID` (and every other COBOL-name spelling tried) resolves to
   "No symbol in current context": confirmed, gdb does not expose COBOL
   names as symbols, matching the pessimistic case. But the *fully mangled,
   byte-offset-decode* fallback the doc treated as the likely consequence is
   not what's needed. `cobc -g` (with no extra flags) always emits a sibling
   `<name>.c.l.h` header — already included via `#include` inside the
   generated function body — that declares every working-storage/linkage
   item as its own named C local, **with the original COBOL name as a
   trailing comment**:
   ```c
   static cob_u8_t b_17[10] __attribute__((aligned));  /* WS-CUSTOMER-ID */
   static cob_u8_t b_18[4]  __attribute__((aligned));  /* WS-BALANCE */
   static cob_field f_18 = {4, b_18, &a_2};             /* WS-BALANCE */
   ```
   That comment is a free, mechanical symbol table: `variable_map.py` parses
   `<compiled-name>.c.l.h` (a small regex over `b_NN`/`f_NN` declarations and
   their trailing `/* NAME */` comment, not a general C parser) to build
   `COBOL name -> gdb expression` once per compiled program, then reads each
   item with MI `-data-evaluate-expression f_NN` or `b_NN`. Better still,
   GnuCOBOL's own `cob_field_attr` struct (referenced from each `f_NN`, e.g.
   `a_2`) carries the PICTURE metadata gdb can read directly —
   `f_18.attr->type` / `->digits` / `->scale` evaluated to `18` (packed
   decimal), `7`, `2` for the `PIC 9(5)V99 COMP-3` item, an exact match.
   `variable_map.py` therefore does not need to reimplement
   `cobol-parser`'s COMP-3/COMP byte-layout math from scratch to find *where*
   a value lives — GnuCOBOL already hands back a correctly-scoped
   `(bytes, type, digits, scale)` tuple per item via MI — it only needs a
   decoder from that tuple to a display value, which can reuse or mirror the
   existing `PictureClause` decode logic for the *type→string* half. This
   still needs proving out for group items, `OCCURS` tables, and
   `REDEFINES` (not covered by this fixture) before it's assumed universal,
   but the flat-item case — the common one — is confirmed cheap.
4. **Does MI work over `docker exec -i`? YES, cleanly.** `docker exec -i -w
   <dir> mockymock-cobc gdb --interpreter=mi2 ./binary` accepts MI commands
   on stdin and emits well-formed `^done`/`*stopped`/`~"..."` records on
   stdout with no TTY required. `gdbserver` and a `target remote` transport
   are unnecessary; this closes the question in favor of the simpler
   stdio-MI design already sketched below.
5. **Does ptrace work under the hardening flags? YES.** `gdb run` inside a
   container started with the production `--cap-drop ALL --cap-add
   DAC_OVERRIDE --security-opt no-new-privileges` flags hits the intended
   breakpoint and steps normally — gdb tracing its own forked child does not
   need `CAP_SYS_PTRACE`. The only symptom was a benign warning (`Error
   disabling address space randomization: Operation not permitted`, from
   `personality()` being blocked — cosmetic, does not affect debugging) that
   the adapter should suppress from user-facing output rather than surface
   as an error. **No `--cap-add SYS_PTRACE` weakening is needed**; the
   sandbox trade-off flagged as a risk in the original doc's Limitations
   does not materialize.
6. **How does the debuggee's stdout interleave with MI records? Exactly as
   predicted.** Program `DISPLAY` output (e.g. `LOOP ITER +0001`) appears as
   bare untagged lines directly in the stream between MI records, not
   wrapped in any MI record type. `gdb_session.py`'s MI reader must treat
   any line not matching `^done`/`*stopped`/`~`/`=`/`&`/`^error`/`(gdb)` as
   raw program output and forward it as a DAP `output` event.

**New finding, not anticipated by the original six questions — call stack
synthesis:** goal #3 ("a call stack in terms of COBOL paragraphs/sections")
cannot come from gdb's native `bt`/`-stack-list-frames` at all. GnuCOBOL
compiles the entire PROCEDURE DIVISION into one C function (`SPIKE_`); a
`PERFORM` of another paragraph is a computed-goto plus a push onto
GnuCOBOL's own internal `frame_stack[255]` array of return addresses — never
a real C call. Breaking inside a performed paragraph and running `bt` shows
exactly one program frame (`SPIKE_`), regardless of PERFORM nesting depth;
`frame_ptr`/`frame_stack` (visible via `info locals`, sized for 255 levels)
are the *actual* COBOL call stack, address-only, address (`return_address_ptr`
values are labels inside `SPIKE_`). **Consequence:** a DAP `stackTrace`
response cannot be a thin translation of MI's frame list; the adapter must
walk `frame_ptr` back through `frame_stack` itself, resolve each
`return_address_ptr` to a source line via the same line-table gdb uses for
breakpoints (MI `-symbol-info-line`-style lookup on the raw address), and
present *that* as the synthesized COBOL call stack. This is new work not
scoped anywhere in the original architecture sketch below and needs its own
module — see "Call stack synthesis".

## Architecture (scoped by the spike above; group items/OCCURS/REDEFINES still need a follow-up fixture pass)

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
  variable_map.py  # COBOL data item <-> gdb-visible symbol, built by parsing
                   # the compiler-generated `<name>.c.l.h` comment table
                   # (confirmed by spike; see "Variable mapping")
  call_stack.py    # synthesizes the COBOL paragraph/section call stack from
                   # GnuCOBOL's internal frame_stack, since gdb's own bt is
                   # always exactly one frame deep (confirmed by spike; see
                   # "Call stack synthesis")
```

`gdb_session.py` is the direct analogue of `docker_toolchain.run_binary`,
but stateful: it owns one `subprocess.Popen` for the container's gdb process
for the lifetime of the debug session, writes GDB/MI commands to its stdin,
and reads/parses `^done`/`*stopped`/`~"..."` records from stdout — the same
container, same `mockymock-cobc`, same `_HARDENING_FLAGS`, just a different
interaction pattern than the "run and collect the final result" style every
other function here uses. Two design constraints on it, both from the
empirical questions above:

- **The MI reader must tolerate untagged lines.** Confirmed by spike question
  6: the inferior's stdout arrives interleaved with MI records on the same
  pipe; any line that is not a recognizable MI record (`^`/`*`/`~`/`=`/`&`
  prefix or the `(gdb)` prompt) is program output and gets forwarded as a DAP
  `output` event, never treated as a parse error.
- **Stepping is coalesced by file, not by line.** Confirmed by spike question
  2: a DAP "next" issues MI `-exec-next`/`-exec-step` repeatedly while the
  current frame's `file` is the generated `.c` file, stopping on the first
  frame whose file is the `.cbl` (spliced-source, in production) again. This
  is a cleaner predicate than "until the line changes" — the marker/body
  alternation means the line *always* changes every step; what has to
  converge is landing back on a `.cbl`-file frame.
- **The call stack is not gdb's backtrace.** Confirmed by the new
  call-stack-synthesis finding: `-stack-list-frames` always reports one
  program frame. `stackTrace` responses come from `call_stack.py` walking
  GnuCOBOL's `frame_stack` (see "Call stack synthesis"), not from MI's frame
  list.

### Toolchain changes

| Location | Change |
| --- | --- |
| `runtime/docker/Dockerfile` | add `gdb gdbserver` to the `apt-get install` line. **Done in this revision** — verified to install cleanly alongside `gnucobol`. Bumps the image content hash automatically (existing mechanism), so `ensure_toolchain` rebuilds on next run. `gdbserver` is installed but unused; MI-over-`docker exec -i` (question 4) is the transport, not `target remote`. |
| `runtime/docker_toolchain.py::compile_source` | add `debug: bool = False` → appends `-g`, same pattern as `coverage`/`trace`. Orthogonal to `trace`; a debug session does not also need `-ftraceall`. Verified: `-g` alone (no `-t`/`-X` listing flags) is sufficient to produce the `<name>.c.l.h` file `variable_map.py` depends on. |
| `runtime/docker_toolchain.py` | new `start_gdb_session(binary_path) -> GdbSession` (or similar), returning a live handle instead of a completed result — the first function in this module that does not follow the "run to completion" pattern. Verified viable: `docker exec -i -w <dir> mockymock-cobc gdb --interpreter=mi2 <binary>` runs cleanly under the production hardening flags with no TTY. |

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

### Call stack synthesis

New section, added after the spike — not scoped in the original doc because
the assumption going in was that MI's native frame list would do most of the
work. It doesn't: confirmed by the spike, GnuCOBOL compiles the whole
PROCEDURE DIVISION into one C function, and `PERFORM` is a computed-goto
plus a push onto GnuCOBOL's own `frame_stack[255]` array (visible via `info
locals` as `frame_ptr`/`frame_stack`/`frame_overflow`), never a real C call.
`-stack-list-frames` therefore always reports exactly one program frame
(plus the `SPIKE`/`main` wrapper frames) no matter how deep the COBOL
PERFORM nesting is.

`call_stack.py` must reconstruct the COBOL-level call stack itself for every
`stackTrace` request:

1. Read `frame_ptr` and walk backward through `frame_stack` via MI
   `-data-evaluate-expression` (the array is small and fixed-size — 255
   entries — so this is a bounded, cheap read). **Correction, found only
   once this was actually implemented and driven against a real
   container:** `frame_stack[0]` is a sentinel, not a real caller —
   GnuCOBOL initializes it to `{perform_through: 0, return_address_ptr:
   &&P_cgerror}` at function entry, before any PERFORM runs, and always
   increments `frame_ptr` *before* writing a new PERFORM's real return
   address. So `frame_ptr - frame_stack` (the depth) is correct, but the
   real, populated caller frames are `frame_stack[1..depth]`, innermost
   first — resolving `frame_stack[0]` lands on the internal error label,
   not any real call site, and produces a nonsensical frame if not
   excluded.
2. Each populated entry's `return_address_ptr` is a code address inside
   `SPIKE_`; resolve it via a temporary `-break-insert *<address>` /
   `-break-delete` pair (confirmed to work) to get its `file`/`line`. **This
   is *not* simply "the generated-C line, run through `line_map.py`"** as
   originally sketched here: `line_map.py` only ever relates two
   COBOL-shaped texts (original ↔ instrumented), never the generated `.c`
   file, and a resolved return address typically lands on a bare
   generated-C plumbing line (e.g. the line right after the internal
   `goto` that entered the performed paragraph) with no `#line ...cbl`
   marker of its own. The actual mechanism needed — and confirmed
   empirically — is a *separate* lookup: scan the compiled `.c` file's own
   `#line N "<file>.cbl"` directives into a sorted table, and take the
   **nearest preceding** entry for the resolved generated-C line number.
   That preceding entry is exactly the calling statement's own instrumented
   line (e.g. the `PERFORM CALC-INTEREST` statement's line) — confirmed
   against a real fixture — which is *then* run through `line_map.py` to
   the original line, same as any other instrumented-line lookup.
3. The resolved line falls inside a specific paragraph/section — reuse
   `splicer/source_map.py`'s existing span/boundary data (the same data
   "Line mapping" above already reuses) to name the enclosing
   paragraph/section rather than inventing a second lookup.
4. Present frames outermost-to-innermost as the DAP `stackTrace` response;
   frame 0 is the current stopped location (from the ordinary line-mapped
   breakpoint/step position, not from `frame_stack` — the *current* line
   is not itself a `frame_stack` entry, only the return points above it
   are).

This needs its own fixture-driven verification pass (nested PERFORMs, a
PERFORM THRU, a GO TO) before the CLI implementation plan finalizes its
shape, but the mechanism — walk `frame_stack`, resolve addresses through the
existing line-table and span data — is confirmed sound in principle.

### Variable mapping

Resolved by the spike to a third path, cheaper than either candidate the
original doc bracketed:

- Not the optimistic case: gdb does not expose COBOL names as symbols
  (`print WS-BALANCE`-style expressions fail).
- Not the full pessimistic case either: no manual byte-offset-into-a-shared-buffer
  decode is needed, because GnuCOBOL already scopes each item to its own
  named C local and hands back its own `cob_field`.

**The actual mechanism:** `cobc -g` always emits `<compiled-name>.c.l.h`
(included into the generated function body) declaring every working-storage
and linkage item as a named local — `b_NN` for a raw buffer, `f_NN` for a
`cob_field` wrapping one — **with the original COBOL name as a trailing
comment on the same line** (`static cob_u8_t b_18[4] ...; /* WS-BALANCE */`).
`variable_map.py`:

1. Parses `<compiled-name>.c.l.h` with a small regex over declaration lines
   (not a general C parser) to build `COBOL name -> gdb expression` (prefer
   the `f_NN` field wrapper over the raw `b_NN` buffer when both exist — the
   field carries type metadata the buffer alone doesn't).
2. Reads each item live via MI `-data-evaluate-expression <f_NN or b_NN>`.
3. For `DISPLAY`/alphanumeric items, the value is already the display
   string (`b_17` evaluates to `"CUST00001 "` directly — no decoding).
4. For numeric `COMP`/`COMP-3` items, also evaluates `<f_NN>.attr->type`,
   `->digits`, `->scale` — GnuCOBOL's own `cob_field_attr`, which for a `PIC
   9(5)V99 COMP-3` item read back exactly `18` (packed-decimal),  `7`, `2`.
   That `(raw bytes, type, digits, scale)` tuple is then decoded to a
   display value the same way `cobol-parser`'s `PictureClause` decode logic
   already does for COMP-3/COMP — reusing that decode step, not the
   byte-layout/offset math the pessimistic case would have needed, since
   GnuCOBOL has already found the right bytes for us.

**Not yet verified — flagged for the CLI implementation plan, not blocking
it:** group items, `OCCURS` tables, and `REDEFINES` were not in the spike
fixture. A first guess is that a group item's `f_NN` field spans the whole
group (alphanumeric, no per-elementary breakdown) and its subordinate items
get their own `f_NN`s layered over the same bytes — consistent with how
`REDEFINES` already works in cobc's model — but this needs a fixture with at
least one `OCCURS` table and one `REDEFINES` before `variable_map.py`'s
`variables` (children-of-a-scope) response shape is finalized.

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

- **Spike done** (see Empirical basis) — a throwaway session against the
  live container; findings folded back into this doc above. The one-off
  fixture/scripts used for it were not kept as shipped code.
- **Unit:** GDB/MI response parsing in `gdb_session.py`; line-map
  bidirectional round-trip; variable-map `.c.l.h` comment parsing and
  COMP-3/COMP decoding; call-stack synthesis against a fixture with nested
  PERFORMs.
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
- ~~Possible sandbox trade-off~~ **Resolved: no trade-off needed.** The
  spike confirmed `ptrace` works under the existing `--cap-drop ALL
  --cap-add DAC_OVERRIDE --security-opt no-new-privileges` flags with no
  additional capability grant — gdb tracing its own forked child does not
  require `CAP_SYS_PTRACE`. The sandbox is unchanged by adding debug support.
- **Shared memory cap.** gdb and the debuggee together live under the
  container's existing 1 GB `MEMORY_LIMIT`. Likely fine, but a
  memory-limit kill mid-session would surface as the "session dies"
  error-handling row, which is exactly where it would otherwise be most
  confusing to diagnose.

## Sequencing

1. **This doc** (architecture, scoped, empirical questions enumerated). Done.
2. **Spike** — done 2026-07-22; findings folded back into this doc above
   (this revision). Call stack synthesis emerged as new, previously
   unscoped work; group items/`OCCURS`/`REDEFINES` remain unverified for
   variable mapping and are flagged, not blocking, for step 3.
3. **CLI implementation plan** (`docs/archive/plans/`) — next step.
   `line_map.py`, `variable_map.py`, and `call_stack.py` are all now
   concretely scoped by the spike; the plan should still budget a follow-up
   fixture pass (group items, `OCCURS`, `REDEFINES`, nested PERFORM/PERFORM
   THRU/GO TO) as part of implementation rather than as a further blocking
   spike.
4. **Extension implementation plan**, same split as the trace feature
   (CLI lands first, extension consumes the DAP contract — which here is
   just the DAP spec itself plus the `mockymock debug` launch shape, not a
   bespoke JSON contract like `TRACE_JSON_VERSION`).
