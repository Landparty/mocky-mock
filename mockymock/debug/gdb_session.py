"""Long-lived GDB/MI session for the interactive debugger.

Wraps the `docker exec -i ... gdb --interpreter=mi2 <binary>` subprocess
`runtime.docker_toolchain.start_gdb_session` spawns. Every behavior this
module relies on was verified against a real hardened container (see
docs/2026-07-22-dap-debugger-design.md's Empirical basis) before being
written, not assumed from GDB/MI documentation:

- MI works over `docker exec -i` with no TTY; no `gdbserver`/`target
  remote` transport is needed.
- The debuggee's own stdout (including every `__MOCKYMOCK__` protocol
  line) arrives as bare, untagged lines interleaved with MI records on the
  same pipe -- never wrapped in an MI record of its own. Anything that
  does not parse as a recognized MI record is program output.
- An exec command (`-exec-run`/`-exec-continue`/`-exec-next`) returns its
  own `^running` result record immediately, before the program actually
  stops; the real stop arrives later as an asynchronous `*stopped` record
  (with `reason="exited-normally"` covering normal program exit too, not
  only breakpoints/steps) -- confirmed empirically, not assumed.
- `gdb run` always prints a benign `Error disabling address space
  randomization: Operation not permitted` warning under the container's
  hardening flags (personality() blocked by seccomp; does not affect
  debugging) -- filtered here rather than surfaced.
- One COBOL statement compiles to an alternating `#line <N> "<file>.cbl"`
  marker / `#line <M> "<file>.c"` body pair. Stepping "one COBOL line"
  means issuing `-exec-next` until the stopped frame's file is the `.cbl`
  (or spliced-source) file again, not until the line number changes -- the
  line always changes every single step.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

# Emitted by gdb under the container's --security-opt no-new-privileges:
# personality() (ASLR disable) is blocked by seccomp. Cosmetic -- debugging
# still works -- so it is filtered rather than forwarded as program output
# or surfaced as an adapter error.
_BENIGN_WARNING_SUBSTRING = "Error disabling address space randomization"

# A single COBOL statement's marker/body pair was observed to coalesce in
# exactly 2 steps for simple MOVE/ADD statements; this is a safety bound in
# case a construct with heavier control flow (loops, IF/EVALUATE dispatch,
# not covered by the spike fixture) never lands back on the original file.
_MAX_COALESCE_STEPS = 500


@dataclass
class ResultRecord:
    """A `^done`/`^error`/`^running`/`^exit`/`^connected` record -- ends the
    read for whichever command produced it."""

    kind: str
    payload: dict


@dataclass
class AsyncRecord:
    """A `*xxx` (exec-async, e.g. `*stopped`) or `=xxx` (notify-async, e.g.
    `=library-loaded`) record."""

    kind: str
    payload: dict


@dataclass
class StreamRecord:
    """A `~"..."` (console), `@"..."` (target), or `&"..."` (log) record."""

    kind: str
    text: str


@dataclass
class ProgramOutput:
    """A line that is not a recognizable MI record at all -- the
    debuggee's own stdout, arriving raw and untagged on the same pipe."""

    text: str


MIRecord = ResultRecord | AsyncRecord | StreamRecord | ProgramOutput


class MalformedMIRecordError(ValueError):
    """A line looked like it started an MI record (`^`/`*`/`=`/`~`/`@`/`&`)
    but did not parse as one. Distinct from a line simply being program
    output, which is not an error at all -- see module docstring."""


class GdbSessionClosedError(RuntimeError):
    """The gdb subprocess's stdout closed (process exited) while a caller
    was still waiting for a record."""


class GdbCommandError(RuntimeError):
    """An MI command returned `^error`."""


def _require(condition: bool, message: str) -> None:
    """Raise MalformedMIRecordError unless `condition` holds. Used instead
    of `assert` so the parser's structural checks survive `python -O`
    (which strips asserts) -- an unchecked parser would then crash the
    whole session on the first line of program output that happens to look
    like an MI record (see parse_mi_line's fallback)."""
    if not condition:
        raise MalformedMIRecordError(message)


def _parse_c_string(text: str, i: int) -> tuple[str, int]:
    _require(i < len(text) and text[i] == '"', "expected opening quote")
    i += 1
    out: list[str] = []
    while i < len(text) and text[i] != '"':
        if text[i] == "\\":
            i += 1
            _require(i < len(text), "dangling escape in MI string")
            escape = text[i]
            out.append({"n": "\n", "t": "\t", "\\": "\\", '"': '"'}.get(escape, escape))
        else:
            out.append(text[i])
        i += 1
    _require(i < len(text), "unterminated MI string")
    return "".join(out), i + 1


def _parse_ident(text: str, i: int) -> tuple[str, int]:
    start = i
    while i < len(text) and (text[i].isalnum() or text[i] in "-_"):
        i += 1
    return text[start:i], i


def _parse_mi_value(text: str, i: int) -> tuple[object, int]:
    if text[i] == '"':
        return _parse_c_string(text, i)
    if text[i] == "{":
        return _parse_mi_tuple(text, i)
    if text[i] == "[":
        return _parse_mi_list(text, i)
    raise MalformedMIRecordError(f"unexpected MI value at {i}: {text[i:i + 20]!r}")


def _parse_mi_tuple(text: str, i: int) -> tuple[dict, int]:
    _require(i < len(text) and text[i] == "{", "expected opening brace")
    i += 1
    result: dict = {}
    _require(i < len(text), "unterminated MI tuple")
    if text[i] == "}":
        return result, i + 1
    while True:
        key, i = _parse_ident(text, i)
        _require(i < len(text) and text[i] == "=", "expected '=' in MI tuple")
        i += 1
        value, i = _parse_mi_value(text, i)
        result[key] = value
        _require(i < len(text), "unterminated MI tuple")
        if text[i] == ",":
            i += 1
            continue
        _require(text[i] == "}", "expected ',' or '}' in MI tuple")
        return result, i + 1


def _parse_mi_list(text: str, i: int) -> tuple[list, int]:
    _require(i < len(text) and text[i] == "[", "expected opening bracket")
    i += 1
    items: list = []
    _require(i < len(text), "unterminated MI list")
    if text[i] == "]":
        return items, i + 1
    while True:
        # A list element is either a bare value or an "ident=value" result
        # (e.g. `thread-groups=["i1"]` vs `ranges=[{from="...",to="..."}]`).
        _, after_ident = _parse_ident(text, i)
        if after_ident > i and after_ident < len(text) and text[after_ident] == "=":
            key, i = _parse_ident(text, i)
            i += 1
            value, i = _parse_mi_value(text, i)
            items.append((key, value))
        else:
            value, i = _parse_mi_value(text, i)
            items.append(value)
        _require(i < len(text), "unterminated MI list")
        if text[i] == ",":
            i += 1
            continue
        _require(text[i] == "]", "expected ',' or ']' in MI list")
        return items, i + 1


# The complete, closed set of GDB/MI `^`-result classes. A `^`-prefixed
# line whose class is NOT one of these is program output that merely starts
# with a caret, not a result record -- treating it as one would prematurely
# satisfy `send`'s read loop and desync every subsequent command from its
# response.
_RESULT_CLASSES = frozenset({"done", "running", "connected", "error", "exit"})


def parse_mi_line(raw_line: str) -> MIRecord | None:
    """Parse one line of GDB/MI output. Returns None for the bare `(gdb)`
    prompt marker and for the benign ASLR warning (both are noise, not
    program output or a record the caller needs).

    The debuggee's own stdout shares this pipe and can begin with ANY
    character, including the MI marker characters `^*=~@&` (a COBOL DISPLAY
    of "*** ERROR ***", say). So a line that merely *starts* like a record
    but does not *parse* as one -- or, for `^`, whose class is not a real
    result class -- is treated as program output rather than crashing the
    session or being silently swallowed. This is the load-bearing
    robustness rule from the design doc's empirical question 6."""
    line = raw_line.rstrip("\n").rstrip("\r")
    if not line.strip() or line.strip() == "(gdb)":
        return None

    marker = line[0]
    try:
        if marker in "^*=":
            record = _parse_result_or_async(marker, line)
            if record is not None:
                return record
            # Fall through: looked like a record, wasn't one -> program output.
        elif marker in "~@&":
            text, _ = _parse_c_string(line, 1)
            if marker == "&" and _BENIGN_WARNING_SUBSTRING in text:
                return None
            return StreamRecord(marker, text)
    except MalformedMIRecordError:
        pass  # not a real record after all -> program output, below

    # Anything else is the debuggee's own raw stdout, interleaved on the
    # same pipe with no wrapping record of its own (verified empirically --
    # see module docstring).
    return ProgramOutput(line)


def _parse_result_or_async(marker: str, line: str) -> MIRecord | None:
    """Parse a `^`/`*`/`=` record, or return None if `line` is program
    output that only looks like one. Raises MalformedMIRecordError if it
    starts as a record but the payload is malformed (caught by the caller
    and likewise treated as program output)."""
    i = 1
    class_name, i = _parse_ident(line, i)
    # A real record always has a non-empty class name; `*** ERROR ***` and
    # `=== TOTALS ===` do not (the second char is not an identifier char).
    if not class_name:
        return None
    if marker == "^" and class_name not in _RESULT_CLASSES:
        return None

    payload: dict = {}
    if i < len(line) and line[i] == ",":
        i += 1
        while True:
            key, i = _parse_ident(line, i)
            _require(i < len(line) and line[i] == "=", "expected '=' in MI record")
            i += 1
            value, i = _parse_mi_value(line, i)
            payload[key] = value
            if i < len(line) and line[i] == ",":
                i += 1
                continue
            break
    if marker == "^":
        return ResultRecord(class_name, payload)
    return AsyncRecord(class_name, payload)


@dataclass
class StopEvent:
    reason: Literal["breakpoint", "step", "exited", "crashed"]
    file: str | None = None
    line: int | None = None
    exit_code: int | None = None
    frame: dict = field(default_factory=dict)


def _classify_stop_reason(
    reason: str,
) -> Literal["breakpoint", "step", "exited", "crashed"]:
    if reason.startswith("exited"):
        return "exited"
    if reason == "signal-received":
        return "crashed"
    if reason == "breakpoint-hit":
        return "breakpoint"
    # "end-stepping-range", "function-finished", or any other MI reason
    # for a completed -exec-next/-exec-step: a plain step stop.
    return "step"


def _stop_event_from_payload(payload: dict) -> StopEvent:
    reason = payload.get("reason", "")
    kind = _classify_stop_reason(reason)
    if kind == "exited":
        exit_code = payload.get("exit-code")
        return StopEvent(
            reason="exited",
            exit_code=int(exit_code, 0) if exit_code is not None else 0,
        )
    frame = payload.get("frame", {})
    line = frame.get("line")
    return StopEvent(
        reason=kind,
        file=frame.get("fullname") or frame.get("file"),
        line=int(line) if line is not None else None,
        frame=frame,
    )


class GdbSession:
    """Owns one long-lived `gdb --interpreter=mi2` subprocess for the
    lifetime of a debug session. Commands are issued serially -- MI
    interleaves async/stream/program-output records with the eventual
    result record for whichever command is in flight, so `send` simply
    reads until the next result record arrives."""

    def __init__(
        self,
        process: subprocess.Popen,
        on_output: Callable[[str], None] | None = None,
    ) -> None:
        self._process = process
        self._on_output = on_output or (lambda text: None)

    def set_output_handler(self, on_output: Callable[[str], None]) -> None:
        """Rebinds the program-output callback -- used by adapter.py,
        which is what actually knows how to turn output into a DAP
        `output` event, but is not the code that constructs GdbSession
        (that happens inside the CLI's launch_session pipeline, before
        the adapter ever sees the session)."""
        self._on_output = on_output

    def send(self, command: str) -> list[MIRecord]:
        """Issue a command and read until ITS OWN immediate result record
        (`^done`/`^error`/`^running`/`^exit`/`^connected`). For exec
        commands this returns right after `^running` -- the actual stop is
        asynchronous and arrives later; use `run`/`continue_`/`step`
        rather than calling `send` directly for those."""
        assert self._process.stdin is not None
        assert self._process.stdout is not None
        self._process.stdin.write(command + "\n")
        self._process.stdin.flush()

        records: list[MIRecord] = []
        while True:
            raw_line = self._process.stdout.readline()
            if raw_line == "":
                raise GdbSessionClosedError(
                    f"gdb process exited while waiting for a response to {command!r}"
                )
            record = parse_mi_line(raw_line)
            if record is None:
                continue
            records.append(record)
            if isinstance(record, ProgramOutput):
                self._on_output(record.text)
            if isinstance(record, ResultRecord):
                break
        return records

    def close(self) -> None:
        """Ends the gdb process. Called on DAP `disconnect` and whenever
        the adapter's own stdin closes -- a leaked gdb process lives
        inside the shared long-lived container and counts against
        PIDS_LIMIT, degrading every subsequent normal `run`."""
        try:
            if self._process.poll() is None:
                self.send("-gdb-exit")
        except (GdbSessionClosedError, OSError):
            pass
        finally:
            if self._process.poll() is None:
                self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=5)

    # -- Breakpoints and run control -------------------------------------

    def set_breakpoint(self, file: str, line: int) -> dict:
        """`-break-insert <file>:<line>`. Returns the `bkpt` dict from the
        `^done` result (has `number`, `file`, `line`, ...); raises
        GdbCommandError if gdb refuses the location."""
        records = self.send(f"-break-insert {file}:{line}")
        return _require_payload_key(records, "bkpt", f"-break-insert {file}:{line}")

    def delete_breakpoint(self, number: int) -> None:
        """`-break-delete <number>`. Used to honor DAP `setBreakpoints`
        replace semantics -- gdb has no per-file clear, so the adapter
        tracks the numbers it inserted and deletes them by hand."""
        self.send(f"-break-delete {number}")

    def resolve_address(self, address: int) -> dict:
        """Resolves a raw code address to its `{file, fullname, line,
        func, ...}` location by inserting and immediately deleting a
        temporary breakpoint there -- confirmed to work via `-break-insert
        *ADDR` (see docs/2026-07-22-dap-debugger-design.md's Call stack
        synthesis section). Used by call_stack.py to resolve
        `frame_stack[i].return_address_ptr` entries, since gdb's own
        backtrace never reflects COBOL PERFORM nesting."""
        command = f"-break-insert *{address:#x}"
        bkpt = _require_payload_key(self.send(command), "bkpt", command)
        self.send(f"-break-delete {bkpt['number']}")
        return bkpt

    def run(self) -> StopEvent:
        """`-exec-run`, reading through to the first `*stopped` (which
        also covers immediate program exit -- see module docstring)."""
        return self._exec_and_await_stop("-exec-run")

    def continue_(self) -> StopEvent:
        return self._exec_and_await_stop("-exec-continue")

    def step(self, original_file_hint: str) -> StopEvent:
        """Coalesced "step one COBOL line": issue `-exec-next` repeatedly
        while the stopped frame's file is not `original_file_hint`,
        stopping on the first frame that reports it again (or on program
        exit/crash/an intervening breakpoint hit -- all valid DAP
        step-stop reasons). See module docstring for why file, not line,
        is the coalescing predicate."""
        for _ in range(_MAX_COALESCE_STEPS):
            event = self._exec_and_await_stop("-exec-next")
            if event.reason != "step":
                return event  # breakpoint hit, exited, or crashed mid-step
            if event.file is not None and event.file.endswith(original_file_hint):
                return event
        raise RuntimeError(
            f"step did not return to {original_file_hint} within "
            f"{_MAX_COALESCE_STEPS} coalesced steps -- a construct with "
            f"more internal control flow than the spike fixture covered "
            f"(see Task 10 of the CLI implementation plan)"
        )

    # step_into/step_out: v1 does not step across a mocked CALL boundary
    # (see design doc Non-goals) so both alias `step` rather than having
    # distinct semantics.
    step_into = step
    step_out = step

    def _exec_and_await_stop(self, command: str) -> StopEvent:
        records = self.send(command)
        last = records[-1]
        if isinstance(last, ResultRecord) and last.kind == "error":
            raise GdbCommandError(
                f"{command} failed: {last.payload.get('msg', last.payload)}"
            )
        return self._read_until_stopped()

    def _read_until_stopped(self) -> StopEvent:
        """Reads records (forwarding ProgramOutput via `on_output`) until
        an async `*stopped` record appears, and converts it to a
        StopEvent."""
        assert self._process.stdout is not None
        while True:
            raw_line = self._process.stdout.readline()
            if raw_line == "":
                raise GdbSessionClosedError(
                    "gdb process exited before reporting *stopped"
                )
            record = parse_mi_line(raw_line)
            if record is None:
                continue
            if isinstance(record, ProgramOutput):
                self._on_output(record.text)
                continue
            if isinstance(record, AsyncRecord) and record.kind == "stopped":
                return _stop_event_from_payload(record.payload)
            # Everything else (the ^running result, library-loaded/thread
            # notify-async records, console/log stream records) is
            # transport noise for this call -- keep reading.


def _require_payload_key(records: list[MIRecord], key: str, command: str) -> dict:
    for record in records:
        if isinstance(record, ResultRecord):
            if record.kind == "done" and key in record.payload:
                return record.payload[key]
            if record.kind == "error":
                raise GdbCommandError(
                    f"{command} failed: {record.payload.get('msg', record.payload)}"
                )
    raise GdbCommandError(f"{command} produced no result record")


def evaluate(session: GdbSession, expression: str) -> str:
    """`-data-evaluate-expression <expression>` -> its `value` string.
    Shared by variable_map.py and call_stack.py; both only ever need the
    raw value string, decoding it themselves."""
    records = session.send(f"-data-evaluate-expression {expression}")
    value = _require_payload_key(
        records, "value", f"-data-evaluate-expression {expression}"
    )
    assert isinstance(value, str)  # MI's "value" field is always a string
    return value
