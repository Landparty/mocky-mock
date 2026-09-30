"""Debug Adapter Protocol server on stdio for `mockymock debug --dap-stdio`.

Speaks the standard DAP wire format (`Content-Length: N\\r\\n\\r\\n<json>`)
over whatever input/output streams it is given -- real stdio in
production, `io.BytesIO` in tests. Scope is deliberately minimal, matching
docs/2026-07-22-dap-debugger-design.md's Goal/Non-goals: line breakpoints,
run/continue/next (no real step-into across a mocked CALL boundary),
read-only variable inspection, a synthesized COBOL call stack. No
conditional/data breakpoints, no `setVariable`, one thread.

`DapAdapter` does not know how to compile a COBOL program or splice a
`.cut` file -- that pipeline (identical to `_cmd_run`'s, up to the point
where a normal run would call `run_binary`) is injected as
`launch_session`, a callable the CLI wires up. This keeps the DAP request
plumbing testable with a fake session, independent of Docker/gdb.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import IO

from mockymock.debug.call_stack import CallFrame, ParagraphIndex, synthesize_stack
from mockymock.debug.gdb_session import GdbSession, GdbSessionClosedError, StopEvent
from mockymock.debug.line_map import LineMap
from mockymock.debug.variable_map import VariableValue, read_variable

# The DAP capability surface this adapter actually implements. Everything
# else (conditional breakpoints, setVariable, multiple threads, ...) is
# out of scope for v1 -- see the design doc's Non-goals.
_CAPABILITIES = {
    "supportsConfigurationDoneRequest": True,
}

_MAIN_THREAD_ID = 1


@dataclass
class DebugSession:
    """Everything a running debug session needs, assembled by
    `launch_session` before the adapter's `launch` handler returns."""

    gdb: GdbSession
    line_map: LineMap
    variable_table: dict[str, str]  # COBOL name -> gdb expression
    generated_c_lines: list[tuple[int, int]]
    paragraph_index: ParagraphIndex
    instrumented_file: str
    """The file path gdb itself knows about (the spliced/instrumented
    source cobc actually compiled)."""


LaunchSession = Callable[..., DebugSession]


class DapFramingError(RuntimeError):
    """The `Content-Length` framing itself was unparseable. Unlike a
    request-handler exception, there is no request to fail and no way to
    know how many bytes the corrupted message's body would have been --
    the stream is unrecoverable, so this always means the adapter shuts
    down, never a per-request failure to report."""


def read_dap_message(stream: IO[bytes]) -> dict | None:
    """Reads one `Content-Length`-framed DAP JSON message. Returns None at
    EOF (the client closed its side, e.g. VS Code exiting). Raises
    DapFramingError if the Content-Length header is missing or is not a
    positive integer -- a missing/zero length used to default to 0 and
    reach `json.loads(b"")` (a JSONDecodeError, not a DapFramingError, so
    it escaped run()'s clean-shutdown handling entirely), and a negative
    length made `stream.read(n)` block reading the rest of the stream
    instead of raising anything at all (code review on the F17 fix,
    PR #57 -- neither case is a real DAP message: the smallest valid body,
    `{}`, is never fewer than 2 bytes)."""
    headers: dict[str, str] = {}
    while True:
        raw_line = stream.readline()
        if raw_line == b"":
            return None
        try:
            line = raw_line.decode("ascii").rstrip("\r\n")
        except UnicodeDecodeError as exc:
            # Same unrecoverable-stream semantics as a bad Content-Length:
            # a non-ASCII header byte means the framing can't be trusted
            # (2026-08-12 audit Finding 6 -- this used to escape run()'s
            # DapFramingError-only handling and kill the process).
            raise DapFramingError(f"non-ASCII header line: {raw_line!r}") from exc
        if line == "":
            break
        name, _, value = line.partition(":")
        headers[name.strip().lower()] = value.strip()
    raw_length = headers.get("content-length")
    length = None
    if raw_length is not None:
        try:
            length = int(raw_length)
        except ValueError:
            length = None
    if length is None or length <= 0:
        raise DapFramingError(f"malformed Content-Length header: {raw_length!r}")
    body = stream.read(length)
    if len(body) < length:
        # The client died mid-send: read() returned the short remainder
        # without raising, and json.loads on the truncated prefix used to
        # raise a JSONDecodeError past run()'s handling (Finding 6).
        raise DapFramingError(
            f"truncated body: expected {length} bytes, got {len(body)}"
        )
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DapFramingError(f"unparseable message body: {exc}") from exc


def write_dap_message(stream: IO[bytes], message: dict) -> None:
    body = json.dumps(message).encode("utf-8")
    stream.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii"))
    stream.write(body)
    stream.flush()


class DapAdapter:
    def __init__(
        self,
        input_stream: IO[bytes],
        output_stream: IO[bytes],
        launch_session: LaunchSession,
    ) -> None:
        self._input = input_stream
        self._output = output_stream
        self._launch_session = launch_session
        self._session: DebugSession | None = None
        self._seq = 0
        self._breakpoint_original_file = ""
        self._done = False
        self._current_stop: StopEvent | None = None
        # Set False at the top of each dispatch, True once a response is
        # written -- lets the dispatch guard distinguish "handler failed
        # before answering" (send a failed response) from "handler already
        # answered, then the resume broke" (terminate cleanly).
        self._responded = False
        # DAP `setBreakpoints` replaces ALL breakpoints for a source. gdb
        # has no per-file clear, so we track the gdb breakpoint numbers we
        # inserted per source path and delete them before inserting the new
        # set -- otherwise un-checking a breakpoint in the editor leaves it
        # live in gdb and the program keeps stopping at a breakpoint the UI
        # says is gone.
        self._breakpoint_numbers: dict[str, list[int]] = {}

    def run(self) -> None:
        """The adapter's main loop: read requests until the client
        disconnects or its stdin closes, dispatching each to a handler."""
        while not self._done:
            try:
                message = read_dap_message(self._input)
            except DapFramingError as exc:
                # Fail closed, not crash: a corrupted Content-Length
                # header leaves no way to know where the next message
                # starts, so the stream is unrecoverable -- shut down the
                # same way an EOF does, instead of letting the exception
                # propagate out of the loop and kill the process
                # (audit finding F17).
                self._on_output(f"mockymock debug: {exc}")
                self._shutdown()
                return
            if message is None:
                self._shutdown()
                return
            if message.get("type") != "request":
                continue
            self._dispatch(message)

    def _dispatch(self, request: dict) -> None:
        # .get, not [...]: a request with no command still deserves a
        # failure response, not an uncaught KeyError out of run()'s loop
        # (2026-08-12 audit Finding 7). The empty-string fallback can never
        # collide with a real handler name.
        command = request.get("command", "")
        handler = getattr(self, f"_handle_{command}", None)
        if handler is None:
            self._send_response(
                request, success=False, message=f"unsupported request: {command}"
            )
            return
        self._responded = False
        try:
            handler(request)
        except Exception as exc:  # noqa: BLE001
            # A handler raising -- a malformed request (missing
            # arguments.source.path), a GdbCommandError mid-request, a
            # dead gdb session -- must not kill the adapter loop and leave
            # the client staring at a closed stream. If the handler had not
            # yet answered, turn the exception into a failed response the
            # client can surface. If it had already answered (the
            # run-control handlers respond BEFORE resuming, so a failure is
            # in the resume, not the request), the session is broken:
            # report it as program output and terminate cleanly.
            if not self._responded:
                self._send_response(request, success=False, message=str(exc))
            else:
                self._on_output(f"mockymock debug: session error: {exc}")
                self._send_event("terminated")
                self._done = True
            if isinstance(exc, GdbSessionClosedError):
                # The gdb subprocess is confirmed dead or unreachable (EOF,
                # or GdbSession's own read deadline expired -- see
                # gdb_session.py's `_closed`). Distinct from a
                # GdbCommandError or a malformed-request exception, neither
                # of which means the session itself is broken. Tear it down
                # now instead of leaving self._session pointing at it:
                # before-response handlers (stackTrace/scopes/variables/
                # evaluate) would otherwise just fail this one request and
                # leave the dead session in place for the next request to
                # try again, and run-control handlers (which already set
                # _done above) never actually closed the gdb subprocess at
                # all -- both leaked the process into the shared container
                # (code review on the F4 fix, PR #57).
                self._shutdown()

    # -- Protocol plumbing ------------------------------------------------

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def _send_response(
        self,
        request: dict,
        success: bool,
        body: dict | None = None,
        message: str | None = None,
    ) -> None:
        # .get on both echoed fields: this method is also the recovery path
        # for malformed requests (Finding 7) -- indexing request["seq"] here
        # made the error handler itself the crash site when a request had a
        # command but no seq. 0 is DAP's conventional "unknown seq".
        response = {
            "seq": self._next_seq(),
            "type": "response",
            "request_seq": request.get("seq", 0),
            "success": success,
            "command": request.get("command", ""),
        }
        if body is not None:
            response["body"] = body
        if message is not None:
            response["message"] = message
        write_dap_message(self._output, response)
        self._responded = True

    def _send_event(self, event: str, body: dict | None = None) -> None:
        message = {"seq": self._next_seq(), "type": "event", "event": event}
        if body is not None:
            message["body"] = body
        write_dap_message(self._output, message)

    def _on_output(self, text: str) -> None:
        self._send_event("output", {"category": "stdout", "output": text + "\n"})

    # -- Request handlers --------------------------------------------------

    def _handle_initialize(self, request: dict) -> None:
        self._send_response(request, success=True, body=dict(_CAPABILITIES))
        self._send_event("initialized")

    def _handle_launch(self, request: dict) -> None:
        arguments = request.get("arguments", {})
        if self._session is not None:
            # A second `launch` must not leak the first session's gdb
            # subprocess (the same PIDS_LIMIT risk as a hung debuggee),
            # nor leave breakpoint numbers pointing at the now-orphaned
            # session's gdb (audit finding F16).
            self._session.gdb.close()
            self._session = None
            self._breakpoint_numbers = {}
            # The stale stop position must go too: a stackTrace between
            # this relaunch and the new session's first stop otherwise
            # synthesizes frames from the PREVIOUS session's location
            # against the new gdb (2026-08-12 audit Finding 9).
            self._current_stop = None
            self._breakpoint_original_file = ""
        try:
            self._session = self._launch_session(arguments)
        except (
            Exception
        ) as exc:  # noqa: BLE001 -- surfaced to the client, not swallowed
            self._send_response(request, success=False, message=str(exc))
            return
        assert self._session is not None
        self._session.gdb.set_output_handler(self._on_output)
        self._send_response(request, success=True)

    def _handle_setBreakpoints(self, request: dict) -> None:
        session = self._require_session(request)
        if session is None:
            return
        arguments = request["arguments"]
        source_path = arguments["source"]["path"]

        # Replace semantics: drop the previous set for this source first.
        for number in self._breakpoint_numbers.pop(source_path, []):
            session.gdb.delete_breakpoint(number)

        breakpoints = []
        inserted_numbers: list[int] = []
        # Registered before inserting, not after: when gdb refuses one
        # location part-way through (a GdbCommandError fails the whole
        # request), the breakpoints already inserted for the earlier lines
        # must still be tracked, or no later setBreakpoints can ever delete
        # them and the program keeps stopping where the editor shows none.
        self._breakpoint_numbers[source_path] = inserted_numbers
        for source_bp in arguments.get("breakpoints", []):
            original_line = source_bp["line"]
            reason = session.line_map.reject_reason(original_line)
            if reason is not None:
                breakpoints.append(
                    {"verified": False, "line": original_line, "message": reason}
                )
                continue
            instrumented_line = session.line_map.to_instrumented(original_line)
            assert instrumented_line is not None  # implied by reject_reason being None
            bkpt = session.gdb.set_breakpoint(
                session.instrumented_file, instrumented_line
            )
            number = int(bkpt["number"])
            inserted_numbers.append(number)
            breakpoints.append({"verified": True, "line": original_line, "id": number})
        if not inserted_numbers:
            del self._breakpoint_numbers[source_path]
        self._breakpoint_original_file = source_path
        self._send_response(request, success=True, body={"breakpoints": breakpoints})

    def _handle_configurationDone(self, request: dict) -> None:
        session = self._require_session(request)
        if session is None:
            return
        self._send_response(request, success=True)
        self._resume(session.gdb.run)

    def _handle_threads(self, request: dict) -> None:
        self._send_response(
            request,
            success=True,
            body={"threads": [{"id": _MAIN_THREAD_ID, "name": "main"}]},
        )

    def _handle_stackTrace(self, request: dict) -> None:
        session = self._require_session(request)
        if session is None:
            return
        frames = self._current_frames(session)
        body = {
            "stackFrames": [
                {
                    "id": index,
                    "name": frame.paragraph or "(unknown)",
                    "line": frame.original_line,
                    "column": 1,
                    "source": {"path": self._breakpoint_original_file},
                }
                for index, frame in enumerate(frames)
            ],
            "totalFrames": len(frames),
        }
        self._send_response(request, success=True, body=body)

    def _handle_scopes(self, request: dict) -> None:
        self._send_response(
            request,
            success=True,
            body={
                "scopes": [
                    {
                        "name": "Working-Storage",
                        "variablesReference": 1,
                        "expensive": False,
                    }
                ]
            },
        )

    def _handle_variables(self, request: dict) -> None:
        session = self._require_session(request)
        if session is None:
            return
        variables = []
        for name, expr in session.variable_table.items():
            value = read_variable(session.gdb, name, expr)
            variables.append(
                {"name": name, "value": _display_value(value), "variablesReference": 0}
            )
        self._send_response(request, success=True, body={"variables": variables})

    def _handle_evaluate(self, request: dict) -> None:
        # Backs the Watch panel, hover-inspect, and the Debug Console --
        # DAP funnels all three through `evaluate`. v1 only resolves plain
        # COBOL identifiers already in variable_table (the same lookup
        # _handle_variables uses); arithmetic/member-access expressions are
        # out of scope (see design doc Non-goals).
        session = self._require_session(request)
        if session is None:
            return
        expression = request["arguments"]["expression"]
        expr = session.variable_table.get(expression)
        if expr is None:
            # COBOL names are case-insensitive, but the table is keyed by
            # the spelling of the declaration (cobc keeps it verbatim in
            # the .c.l.h comment): hovering `WS-BAL` on a line of a program
            # that declared `ws-bal` found nothing.
            wanted = expression.strip().upper()
            expr = next(
                (
                    candidate
                    for name, candidate in session.variable_table.items()
                    if name.upper() == wanted
                ),
                None,
            )
        if expr is None:
            self._send_response(
                request, success=False, message=f"unknown variable: {expression}"
            )
            return
        value = read_variable(session.gdb, expression, expr)
        self._send_response(
            request,
            success=True,
            body={"result": _display_value(value), "variablesReference": 0},
        )

    def _handle_continue(self, request: dict) -> None:
        session = self._require_session(request)
        if session is None:
            return
        self._send_response(request, success=True, body={"allThreadsContinued": True})
        self._resume(session.gdb.continue_)

    def _handle_next(self, request: dict) -> None:
        self._step(request)

    def _handle_stepIn(self, request: dict) -> None:
        # v1 does not step across a mocked CALL boundary (see design doc
        # Non-goals) -- aliased to the same coalesced-next behavior.
        self._step(request)

    def _handle_stepOut(self, request: dict) -> None:
        self._step(request)

    def _step(self, request: dict) -> None:
        session = self._require_session(request)
        if session is None:
            return
        self._send_response(request, success=True)

        def is_visible_line(line: int) -> bool:
            return session.line_map.to_original(line) is not None

        self._resume(
            lambda: session.gdb.step(session.instrumented_file, is_visible_line)
        )

    def _handle_disconnect(self, request: dict) -> None:
        self._shutdown()
        self._send_response(request, success=True)
        self._done = True

    def _handle_terminate(self, request: dict) -> None:
        self._shutdown()
        self._send_response(request, success=True)
        self._done = True

    # -- Shared plumbing ---------------------------------------------------

    def _require_session(self, request: dict) -> DebugSession | None:
        if self._session is None:
            self._send_response(
                request, success=False, message="no active debug session"
            )
            return None
        return self._session

    def _resume(self, action: Callable[[], StopEvent]) -> None:
        """Runs a gdb run-control action and translates its StopEvent into
        the matching DAP event. Program output was already forwarded live
        via the GdbSession's on_output callback while `action` ran."""
        event = action()
        self._current_stop = event
        if event.reason == "exited":
            self._send_event("exited", {"exitCode": event.exit_code or 0})
            self._send_event("terminated")
            return
        reason = {"breakpoint": "breakpoint", "step": "step", "crashed": "exception"}[
            event.reason
        ]
        self._send_event(
            "stopped",
            {"reason": reason, "threadId": _MAIN_THREAD_ID, "allThreadsStopped": True},
        )

    def _current_frames(self, session: DebugSession) -> list[CallFrame]:
        """stackTrace is only ever meaningful while stopped; the current
        position comes from the last StopEvent (`_resume` caches it),
        which already carries the exact file/line gdb reported when it
        stopped -- no need to re-derive it via the current PC."""
        if self._current_stop is None or self._current_stop.file is None:
            return []
        return synthesize_stack(
            session.gdb,
            session.line_map,
            session.generated_c_lines,
            session.paragraph_index,
            current_file=self._current_stop.file,
            current_line=self._current_stop.line or 0,
        )

    def _shutdown(self) -> None:
        if self._session is not None:
            self._session.gdb.close()
            self._session = None


def _display_value(value: VariableValue) -> str:
    return value.decoded if value.decoded is not None else value.raw_repr
