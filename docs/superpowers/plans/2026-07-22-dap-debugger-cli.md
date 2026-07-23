# Interactive DAP Debugger (CLI) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `mockymock debug --case NAME --dap-stdio` — a Debug Adapter
Protocol server on stdio that gives VS Code breakpoints, stepping, a
synthesized COBOL call stack, and read-only variable inspection for a single
`.cut` test case.

**Architecture:** See `docs/2026-07-22-dap-debugger-design.md` (revised
2026-07-22 after a real spike). Five new modules under `mockymock/debug/`:
`adapter.py` (DAP JSON-over-stdio framing and request dispatch),
`gdb_session.py` (the long-lived `docker exec -i gdb --interpreter=mi2`
subprocess and MI parsing), `line_map.py` (bidirectional original ↔
instrumented line mapping), `variable_map.py` (COBOL name ↔ gdb expression,
built from the compiler-generated `.c.l.h` comment table), `call_stack.py`
(synthesizes the COBOL paragraph/section call stack from GnuCOBOL's own
`frame_stack`, since gdb's native backtrace is always exactly one frame).

**Tech Stack:** Python 3.11+, pytest, GnuCOBOL 3.2.0 + gdb 16.3 in the
`mockymock-cobc` Docker container.

## Global Constraints

- **Every claim this plan relies on was verified against a real hardened
  container** (see the design doc's Empirical basis) — this is not a
  speculative architecture. The one exception: group items, `OCCURS`
  tables, `REDEFINES`, and non-trivial control flow (loops, `PERFORM THRU`,
  `GO TO`) inside `call_stack.py`/`variable_map.py` were not in the spike
  fixture. Task 10 budgets a fixture-driven verification pass for exactly
  those; do not treat the shapes below as final until it passes.
- **`gdb`/`gdbserver` are already added to the Dockerfile** (done alongside
  the design doc revision). `ensure_toolchain`'s content-hash tagging
  rebuilds the image automatically; no manual step needed.
- **Stepping coalesces by file, not by line.** A DAP "next"/"step in" issues
  MI `-exec-next`/`-exec-step` repeatedly while the stopped frame's `file`
  is the generated `.c` file, stopping the first time it reports the
  `.cbl`/spliced-source file again. Never compare line numbers to decide
  when to stop.
- **The MI reader must tolerate untagged lines.** Anything on the gdb
  subprocess's stdout not matching `^(done|error|running|exit)`, `*stopped`,
  `~"…"`, `=…`, `&"…"`, or the bare `(gdb)` prompt is the debuggee's raw
  program output (including `__MOCKYMOCK__` protocol lines) and must be
  forwarded as a DAP `output` event, never treated as a parse failure.
- **The call stack is synthesized, never taken from MI's frame list.**
  `-stack-list-frames`/`bt` always reports one program frame regardless of
  COBOL PERFORM nesting depth (GnuCOBOL compiles the whole PROCEDURE
  DIVISION into one C function). `call_stack.py` walks GnuCOBOL's own
  `frame_ptr`/`frame_stack[255]` instead.
- **Variables are read via the `.c.l.h` comment table, not gdb symbol
  names.** `print <COBOL-NAME>` never resolves. `cobc -g` always emits
  `<compiled-name>.c.l.h` with `b_NN`/`f_NN` declarations carrying the
  original COBOL name as a trailing `/* NAME */` comment; `variable_map.py`
  parses that file, not gdb's symbol table.
- **Suppress the benign ASLR warning.** `gdb run` under the hardening flags
  always prints `warning: Error disabling address space randomization:
  Operation not permitted` on startup — cosmetic (personality() is blocked
  by seccomp, doesn't affect debugging). Filter it out of forwarded output
  rather than surfacing it as an error.
- **Single-case only**, same structural reason as `--trace`: one binary, one
  execution stream. `debug` refuses before Docker unless exactly one
  `--case` is selected.
- **`debug` is fully additive.** A normal `run`/`--trace`/`--coverage` must
  stay byte-identical; nothing here touches those code paths.
- Run unit tests with `python -m pytest tests/unit -q`. Docker-gated
  integration tests use the existing skip gate in `tests/integration/_docker.py`.
  This feature's integration tests are the most load-bearing in the repo —
  everything about MI parsing and stepping was learned empirically and
  deserves a real assertion, not just a mock.

---

### Task 1: Compile with `-g`

**Files:**
- Modify: `mockymock/runtime/docker_toolchain.py::compile_source`
- Test: `tests/unit/test_docker_toolchain.py`

**Interfaces:**
- Produces: `compile_source(source_path, coverage=False, trace=False, debug=False) -> CompileResult`. `debug=True` appends `-g`. Orthogonal to `coverage`/`trace` (a debug session doesn't need either, but nothing prevents combining them).

- [ ] Write a test asserting `-g` appears in the captured `docker exec` command when `debug=True`, and is absent by default — mirror `test_compile_source_adds_traceall_flag` in `tests/unit/test_docker_toolchain.py`.
- [ ] Add the `debug: bool = False` parameter and `if debug: cmd.append("-g")`, immediately after the existing `trace` block.
- [ ] Run `python -m pytest tests/unit/test_docker_toolchain.py -q`; expect PASS.
- [ ] Commit: `git commit -m "feat(runtime): compile with -g when debug requested"`.

---

### Task 2: `start_gdb_session` — the long-lived MI subprocess

**Files:**
- Modify: `mockymock/runtime/docker_toolchain.py`
- Create: `mockymock/debug/__init__.py`, `mockymock/debug/gdb_session.py`
- Test: `tests/unit/test_gdb_session.py` (create)

**Interfaces:**
- Produces: `docker_toolchain.start_gdb_session(binary_path: Path) -> subprocess.Popen` — spawns `docker exec -i -w <container_dir> mockymock-cobc gdb --interpreter=mi2 <container_binary>` with `stdin=PIPE, stdout=PIPE, stderr=PIPE, text=True, bufsize=1` (line-buffered — MI is line-oriented). This is the only genuinely new "long-lived handle" function in the module; every other function in `docker_toolchain.py` runs to completion.
- `mockymock/debug/gdb_session.py::GdbSession` wraps the `Popen`:
  - `send(command: str) -> list[MIRecord]` — writes `command\n` to stdin, reads stdout until the matching `^done`/`^error`/`^running`/`^exit` result record for that command, returns every record read (including `*stopped`, `~`, `=`, `&` records and any untagged program-output lines) in order.
  - `MIRecord` is a small tagged union: `ResultRecord(kind, payload)` for `^…`, `AsyncRecord(kind, payload)` for `*…`/`=…`, `StreamRecord(kind, text)` for `~"…"`/`&"…"`, and `ProgramOutput(text)` for anything unrecognized. Parse only what's needed (breakpoint file/line, stopped reason/frame, expression values) — do not build a general MI grammar.
  - `close()` — sends `-gdb-exit` (or kills the process if that hangs) and waits for exit; called on DAP `disconnect` and whenever `adapter.py`'s stdin closes.
- The MI parser must handle the ASLR warning and any interleaved `LOOP ITER`-style raw program output line by classifying it as `ProgramOutput`, per the Global Constraints — this is the single most spike-verified behavior in this plan, get the "what pattern means what" table right:

  | Line starts with | Kind |
  | --- | --- |
  | `^done`, `^error`, `^running`, `^exit`, `^connected` | `ResultRecord` (ends the current command's read) |
  | `*stopped`, `*running`, `*started` (and other `*xxx`) | `AsyncRecord` |
  | `=thread-group-added`, `=library-loaded`, etc. (any `=xxx`) | `AsyncRecord` |
  | `~"..."` | `StreamRecord` (console/log text — includes the ASLR warning, filter it here) |
  | `&"..."` | `StreamRecord` (echoed command / gdb log) |
  | `(gdb)` alone | prompt marker, not a record — skip |
  | anything else | `ProgramOutput` — forward as DAP `output` |

- [ ] Write unit tests against a fake `Popen`-like object (a `io.StringIO`-backed stand-in, or `monkeypatch` on `subprocess.Popen`) feeding canned MI transcripts (use the real transcripts captured during the design spike as fixtures — a `-break-insert`/`-exec-run` sequence with an interleaved `LOOP ITER +0001` line, taken verbatim from the Empirical basis section) and assert: the untagged line becomes `ProgramOutput`, the `^done,bkpt={...}` becomes a `ResultRecord` with parsed `file`/`line`, the ASLR warning is dropped rather than becoming a `StreamRecord` the caller sees.
- [ ] Implement `GdbSession` and `start_gdb_session` per the interfaces above.
- [ ] Run `python -m pytest tests/unit/test_gdb_session.py -q`; expect PASS.
- [ ] Commit: `git commit -m "feat(debug): add long-lived gdb MI session"`.

---

### Task 3: `line_map.py` — bidirectional line mapping

**Files:**
- Create: `mockymock/debug/line_map.py`
- Test: `tests/unit/test_line_map.py` (create)

**Interfaces:**
- Consumes: `report.coverage.build_original_line_map` (existing, instrumented → original).
- Produces:
  - `LineMap` — built once per debug session from `(instrumented_lines, normalized_lines, original_lines)`, same three inputs `_cmd_run` already assembles for trace/coverage.
  - `LineMap.to_instrumented(original_line: int) -> int | None` — the reverse of `build_original_line_map`'s dict (invert once at construction; if two original lines ever map to the same instrumented line, prefer the first — but this should not happen in practice since the forward map is built from a 1:1 diff alignment).
  - `LineMap.to_original(instrumented_line: int) -> int | None` — thin passthrough to the existing forward dict.
  - `LineMap.reject_reason(original_line: int) -> str | None` — `None` if the line has an instrumented counterpart (settable breakpoint); otherwise a message naming the line and stating it has no corresponding executable location in the compiled program (the splicer touched it, it's a comment/blank, or it's a declaration). v1 does not attempt to relocate to the nearest valid statement — reject with a clear reason and let the user pick another line. (A relocation feature reusing `splicer/source_map.py::statement_span`/`ScopeMap` is a reasonable v2, not required here.)

- [ ] Write tests: round-trip `to_instrumented(to_original(N)) == N` for a mapped line; `reject_reason` non-`None` for a splicer-inserted line, `None` for a real statement line. Build fixtures the same way `tests/unit/test_coverage.py`'s existing `build_original_line_map` tests do (three parallel small line lists).
- [ ] Implement `LineMap` as a thin dataclass wrapping the existing dict plus its computed inverse.
- [ ] Run `python -m pytest tests/unit/test_line_map.py -q`; expect PASS.
- [ ] Commit: `git commit -m "feat(debug): add bidirectional line mapping for breakpoints"`.

---

### Task 4: `variable_map.py` — `.c.l.h` comment table + COMP-3/COMP decode

**Files:**
- Create: `mockymock/debug/variable_map.py`
- Test: `tests/unit/test_variable_map.py` (create)

**Interfaces:**
- Produces:
  - `parse_local_header(text: str) -> dict[str, str]` — COBOL name → gdb expression, from a `<compiled-name>.c.l.h` file's text. Regex over lines matching a C declaration ending in a `/* NAME */` comment; prefer `f_NN` over `b_NN` when both exist for the same name (scan `f_NN` declarations first, keep whichever expression a name maps to last — the field wrapper always appears after its buffer in the generated file, so a simple "last write wins" dict-build gets this for free). Example input line: `static cob_u8_t b_18[4] __attribute__((aligned));  /* WS-BALANCE */` and `static cob_field f_18	= {4, b_18, &a_2};	/* WS-BALANCE */` — both should resolve `"WS-BALANCE"` to `"f_18"` (the second, field, declaration wins).
  - `VariableValue` — `name: str`, `kind: Literal["display", "packed-decimal", "binary", ...]`, `raw_repr: str` (the MI expression's raw value string, already decoded to a display string for `display` items since gdb's own char-array printing does that), `decoded: str | None` (for numeric kinds, the human-facing decimal string after applying `digits`/`scale`).
  - `read_variable(session: GdbSession, expr: str) -> VariableValue` — evaluates `<expr>` via MI `-data-evaluate-expression`; for a `cob_field` expression (starts with `f_`), also evaluates `<expr>.attr->type`, `<expr>.attr->digits`, `<expr>.attr->scale` to decide `kind` and, for packed/binary kinds, decode the raw bytes into `decoded`. GnuCOBOL's `cob_field_attr.type` constants: `0x10`/`0x11` alphanumeric/binary-ish family, `0x12` = `COB_TYPE_NUMERIC_PACKED` (COMP-3) — confirmed by spike (`f_18.attr->type` read back `18` for a `PIC 9(5)V99 COMP-3` item). Do not hardcode a partial enum from memory; pull the authoritative type-constant table from GnuCOBOL's own `libcob/common.h` (already available inside the built image — `docker exec mockymock-cobc find / -name common.h -path '*libcob*'`) rather than guessing values, and cross-check any type this plan didn't spike against a real fixture before shipping it.
  - Decoding packed-decimal/binary raw bytes to a decimal string may reuse or mirror `cobol-parser`'s existing COMP-3/COMP decode logic (`cobolparser` is a dependency of this repo already — check `pyproject.toml` for how it's pinned/imported) rather than reimplementing byte-unpacking from scratch; if no public function fits, write the minimal packed-BCD/binary decoder here and note in a comment why cobol-parser's own version wasn't reusable.

- [ ] Write tests for `parse_local_header` against the literal `.c.l.h` content captured in the design doc's Empirical basis section (the `WS-CUSTOMER-ID`/`WS-BALANCE`/`WS-COUNTER` example) — assert the name → expression table matches exactly, including the `f_18` vs `b_18` preference for `WS-BALANCE`.
- [ ] Write a test for the packed-decimal decoder against a known `(bytes, digits, scale)` triple — get the actual packed-BCD encoding for `123.45` under `PIC 9(5)V99 COMP-3` from a real container run (`docker exec ... gdb -batch -ex "break ..." -ex run -ex "next" ... -ex "print/x f_18" ./fixture`, reading the packed bytes back after the MOVE) rather than hand-deriving it, so the test fixture is verified truth, not a guess.
- [ ] Implement `parse_local_header`, `VariableValue`, `read_variable`.
- [ ] Run `python -m pytest tests/unit/test_variable_map.py -q`; expect PASS.
- [ ] Commit: `git commit -m "feat(debug): map COBOL data items to gdb expressions via .c.l.h"`.

**Explicitly deferred to Task 10 (not this task):** group items, `OCCURS` tables, `REDEFINES`. Ship the flat-item case; do not guess the nested shape.

---

### Task 5: `call_stack.py` — synthesize the COBOL call stack

**Files:**
- Create: `mockymock/debug/call_stack.py`
- Test: `tests/unit/test_call_stack.py` (create)

**Interfaces:**
- Produces:
  - `CallFrame` — `paragraph: str | None`, `section: str | None`, `original_line: int`.
  - `synthesize_stack(session: GdbSession, line_map: LineMap, scope_map) -> list[CallFrame]` — reads `frame_ptr`/`frame_stack` via MI (`-data-evaluate-expression frame_ptr - frame_stack` for the current depth, then `frame_stack[i].return_address_ptr` for each populated entry below it), resolves each address to a generated-C line (an MI `-break-insert *<address>` followed immediately by `-break-delete` on the temporary breakpoint's number is the most portable "address → file:line" lookup confirmed available; if MI exposes a direct non-mutating equivalent during implementation, prefer that instead), maps that generated-C line through `line_map.to_original`, and resolves the enclosing paragraph/section via the existing `scope_map` (`splicer/source_map.py::collect_scope_map`/`ScopeMap` — read its actual field names before wiring this up; do not assume a specific attribute name without checking).
  - Frame 0 (innermost/current) comes from the *current* stopped position (the frame `gdb_session.py` already tracks from the last `*stopped` event), not from `frame_stack` — `frame_stack` only holds *return* addresses of callers, per the design doc.

- [ ] Read `mockymock/splicer/source_map.py`'s `ScopeMap`/`collect_scope_map` and `statement_span` in full before writing this task's code — the design doc names them as the reuse target but this plan has not re-verified their exact field/method names.
- [ ] Write a unit test with a fake `GdbSession` (a stub returning canned MI responses for the frame-stack reads) asserting a two-level synthetic stack (current line + one PERFORM-caller return address) resolves to the right paragraph names, using canned data modeled on the spike's own `SPIKE`/`CALC-INTEREST` fixture.
- [ ] Implement `synthesize_stack`.
- [ ] Run `python -m pytest tests/unit/test_call_stack.py -q`; expect PASS.
- [ ] Commit: `git commit -m "feat(debug): synthesize COBOL call stack from GnuCOBOL's frame_stack"`.

**Explicitly deferred to Task 10:** nested PERFORM depth beyond 2 levels, `PERFORM THRU`, `GO TO`. Get the mechanism right for the simple case first; verify the rest with real fixtures before calling this v1-complete.

---

### Task 6: `gdb_session.py` — breakpoints, run control, coalesced stepping

**Files:**
- Modify: `mockymock/debug/gdb_session.py`
- Test: `tests/unit/test_gdb_session.py`

**Interfaces:**
- Extend `GdbSession` with:
  - `set_breakpoint(instrumented_file: str, instrumented_line: int) -> BreakpointResult` — `-break-insert <file>:<line>`, parses the `bkpt={...}` result.
  - `run() -> StopEvent` — `-exec-run`, reads until the first `*stopped` (breakpoint hit, program exited, or crash), draining any `ProgramOutput`/`StreamRecord`s along the way to the adapter's output callback.
  - `continue_() -> StopEvent`, same shape via `-exec-continue`.
  - `step(original_file_hint: str) -> StopEvent` — the coalescing loop: issue `-exec-next`, inspect the resulting frame's `file`; if it's the generated `.c` file (not `original_file_hint`), issue another `-exec-next` and repeat; stop on the first frame reporting the original/spliced file, or on program exit, or on a breakpoint hit mid-step (all valid DAP step-stop reasons). Guard with a hard iteration cap (e.g. 500) that raises a clear internal error rather than looping forever if a statement's C expansion is unexpectedly large or the coalescing predicate is wrong for some construct — this is exactly the kind of case the Task 10 fixture pass exists to find.
  - `step_into`/`step_out` — for v1, treat identically to `step` per the design's Non-goals (no real step-into semantics across mocked CALL boundaries); document this explicitly rather than silently aliasing without comment.
  - `StopEvent` — `reason: Literal["breakpoint", "step", "exited", "crashed"]`, `file: str | None`, `line: int | None` (generated-C or `.cbl`, whichever the frame reported — caller remaps via `line_map`).

- [ ] Write tests for the coalescing loop using canned two-step and (fabricated, since the spike only observed 2-step statements) multi-step transcripts, asserting: it stops on the first `.cbl`-file frame, forwards intermediate `ProgramOutput` untouched, and raises after the iteration cap on a transcript that never returns to the `.cbl` file.
- [ ] Implement the above.
- [ ] Run `python -m pytest tests/unit/test_gdb_session.py -q`; expect PASS.
- [ ] Commit: `git commit -m "feat(debug): breakpoints, run control, and coalesced stepping"`.

---

### Task 7: `adapter.py` — DAP server on stdio

**Files:**
- Create: `mockymock/debug/adapter.py`
- Test: `tests/unit/test_adapter.py` (create)

**Interfaces:**
- `DapAdapter` reads DAP-framed JSON (`Content-Length: N\r\n\r\n<json>`) from a given readable stream and writes framed responses/events to a given writable stream — constructor takes the streams as parameters (not hardcoded to real stdio) so tests can drive it with `io.BytesIO`.
- Handles at minimum: `initialize` (respond with capabilities: `supportsConfigurationDoneRequest: true`, everything else the design's Non-goals exclude left `false`/absent), `launch`/`attach` (compiles with `debug=True`, calls `start_gdb_session`, builds `line_map`/`variable_map` from the compiled artifacts), `setBreakpoints` (per-line, using `line_map.reject_reason`/`to_instrumented` + `gdb_session.set_breakpoint`, responding with each breakpoint's `verified` flag), `configurationDone` (triggers `gdb_session.run()`), `threads` (always one synthetic thread — mockymock has no concept of COBOL threads), `stackTrace` (delegates to `call_stack.synthesize_stack`), `scopes`/`variables` (delegates to `variable_map.read_variable` for each item named in `parse_local_header`'s table), `continue`/`next`/`stepIn`/`stepOut` (delegate to the matching `gdb_session` method, then emit a DAP `stopped` or `terminated`/`exited` event from the resulting `StopEvent`), `disconnect`/`terminate` (calls `gdb_session.close()`).
- Every `ProgramOutput` record surfaced by a `gdb_session` call is forwarded as a DAP `output` event (`category: "stdout"`) as it's produced, not batched.
- On `StopEvent(reason="exited"|"crashed")`, emits DAP `exited` then `terminated` and stops driving further requests other than `disconnect`.

- [ ] Write a test driving `initialize` → `launch` → `setBreakpoints` → `configurationDone` end to end against a fake `GdbSession`/`line_map`/`variable_map` (monkeypatched or constructor-injected — decide during implementation which is cleaner given the existing module's style; do not let real Docker/gdb machinery run inside this unit test), asserting the correct DAP response/event sequence and JSON shapes per the DAP spec's field names (`request_seq`, `success`, `command`, `body`, `event`).
- [ ] Implement `DapAdapter` and its request handlers.
- [ ] Run `python -m pytest tests/unit/test_adapter.py -q`; expect PASS.
- [ ] Commit: `git commit -m "feat(debug): add DAP adapter on stdio"`.

---

### Task 8: Wire the `debug` subcommand into the CLI

**Files:**
- Modify: `mockymock/cli/main.py` (`build_parser`, new `_cmd_debug`)
- Test: `tests/unit/test_cli.py`

**Interfaces:**
- `mockymock debug PROGRAM --cut CUT --case NAME [--dap-stdio] [--copybook-path ...]` — a real subcommand (not a `run` flag), per the design's CLI surface rationale. Reuses `_check_input_files`, `run_static_checks`, and the single-case refusal pattern from `_cmd_run`, but does not run the normal splice→compile→run pipeline to completion — it hands the compiled artifacts to `DapAdapter` and blocks running the adapter loop until the client disconnects.
- Resolve the "no-flag `mockymock debug`" open question from the design doc: refuse with a message pointing at the extension (`mockymock debug: a DAP session has no useful terminal-attached mode; run this from the mocky-mock VS Code extension, or pass --dap-stdio to drive the protocol directly`) unless `--dap-stdio` is given. Do not half-start a session a human cannot drive.

- [ ] Write CLI tests mirroring `test_trace_requires_exactly_one_case`: `debug` with 0 or 2+ `--case` refuses before Docker; `debug` without `--dap-stdio` refuses with the pointed-at-extension message; `debug --dap-stdio` (with a fake adapter/session injected via monkeypatch) reaches the point of constructing `DapAdapter` and running it against real stdio streams.
- [ ] Implement `_cmd_debug` and the `debug` subparser.
- [ ] Run `python -m pytest tests/unit/test_cli.py -q`; expect PASS.
- [ ] Commit: `git commit -m "feat(cli): add debug subcommand with DAP-over-stdio"`.

---

### Task 9: End-to-end integration test against the real container

**Files:**
- Create: `tests/integration/test_debug.py`

**Interfaces:**
- Consumes: the full stack from Tasks 1-8, against a real `mockymock-cobc` container (Docker-gated, `@requires_docker`).

- [ ] Write an integration test that drives a real `mockymock debug` subprocess over stdio with hand-framed DAP JSON messages (no VS Code involved): `initialize` → `launch` (a small fixture `.cbl`/`.cut`, e.g. a trimmed-down version of the spike's `SPIKE` program with a `PIC 9(5)V99 COMP-3` item) → `setBreakpoints` on a known line → `configurationDone` → assert a `stopped` event with `reason: "breakpoint"` on that line → `stackTrace` → assert the frame's line/paragraph → `variables` → assert the COBOL-named item's decoded value matches the value the `.cut` MOVEs into it → `next` a couple of times → assert the reported line advances by real COBOL statements, not generated-C noise → `disconnect`.
- [ ] Run it against the real container (`python -m pytest tests/integration/test_debug.py -q`, Docker must be running); fix whatever the real MI transcript reveals that the unit tests' canned fixtures didn't cover. Expect at least one surprise here — the unit tests are built from a spike transcript, not from running this exact new code end to end.
- [ ] Run the full suite: `python -m pytest tests/unit tests/integration -q`; expect PASS.
- [ ] Commit: `git commit -m "test: prove the DAP debugger end-to-end against real GnuCOBOL+gdb"`.

---

### Task 10: Fixture pass for previously-unverified shapes

**Files:**
- Create: scratch fixtures under a temp/spike directory (not committed) plus whatever `tests/integration/test_debug.py` additions the findings justify.

Per the design doc's Sequencing note, this is "part of implementation," not a further blocking spike — do it against the real container before calling the feature done, but don't gate Tasks 1-9 on it.

- [ ] Compile and debug a fixture with a group item containing at least two elementary subordinate items, one `OCCURS` table, and one `REDEFINES`; confirm or correct `variable_map.py`'s assumption about how `.c.l.h` represents them (see Task 4's deferred note).
- [ ] Compile and debug a fixture with a 3+-level nested `PERFORM`, one `PERFORM ... THRU`, and one `GO TO`; confirm or correct `call_stack.py`'s frame-resolution assumption (see Task 5's deferred note) and `gdb_session.py`'s stepping-coalescing iteration cap against a statement with real internal control flow (a loop condition check, an `IF`) rather than only the simple MOVE/ADD cases the original spike exercised.
- [ ] Fold any corrections back into `docs/2026-07-22-dap-debugger-design.md` (a further revision) and into the affected modules/tests from Tasks 4-6.
- [ ] Commit whatever code changes result, with a message describing what the fixture pass found.

---

## Self-Review

**Spec coverage:** Goal #1 (breakpoints on original lines) → Tasks 3, 6, 8. Goal #2 (stepping through PERFORM boundaries) → Task 6's coalescing loop. Goal #3 (COBOL-shaped call stack) → Task 5. Goal #4 (COBOL-named variable inspection with decoded values) → Task 4. Non-goals are respected by construction: `step_into`/`step_out` explicitly not given real cross-boundary semantics (Task 6), no conditional/data breakpoints in `setBreakpoints` (Task 7), single-case refusal (Task 8), no `setVariable` handler (Task 7 lists only read paths). Error-handling table from the design doc: 0/2+ case refusal and no-flag refusal → Task 8; unspliceable breakpoint line → Task 3's `reject_reason`; missing gdb/toolchain → existing `ensure_toolchain` error path, unchanged; session/client death → `gdb_session.close()` on `disconnect` and on stdin closing (Task 7); CLI-too-old is an extension-side concern (next plan). Testing section: unit coverage per module (Tasks 2-7), Docker-gated integration (Task 9), regression-safety via `debug=False` leaving existing paths untouched (Task 1's orthogonality note) — explicitly not re-tested here since Tasks 1-8 touch no existing `run`/`trace`/`coverage` code path.

**Type consistency:** `LineMap` built from the same three line lists (`instrumented_lines`, `normalized_lines`, `original_lines`) `_cmd_run` already assembles for trace — no new data shape invented for that input. `GdbSession.send`/`run`/`continue_`/`step` all return the same `StopEvent`/`MIRecord` vocabulary threaded from Task 2 through Tasks 6-7. `VariableValue` and `CallFrame` are both consumed only by `adapter.py`'s `variables`/`stackTrace` handlers (Task 7) — no other module needs their shape.

**Known soft spots, called out deliberately rather than glossed over:** (1) `call_stack.py`'s address→line resolution mechanism (temporary breakpoint insert/delete as a stand-in for a direct address lookup) is the least spike-verified piece in this plan — Task 5 explicitly flags it as needing re-confirmation, not blind trust. (2) Every `.c.l.h`/`frame_stack` shape claim about group items, `OCCURS`, `REDEFINES`, and non-trivial control flow is explicitly deferred to Task 10 rather than guessed at in Tasks 4-6 — those tasks ship the flat/simple case only. (3) The DAP capability surface in Task 7 is deliberately minimal (matching the design's Non-goals); expanding it (conditional breakpoints, `setVariable`, multi-thread) is out of scope for this plan, not an oversight.
