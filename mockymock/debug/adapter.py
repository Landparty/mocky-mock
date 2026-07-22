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
from dataclasses import dataclass
from typing import Callable, IO

from mockymock.debug.call_stack import CallFrame, ParagraphIndex, synthesize_stack
from mockymock.debug.gdb_session import GdbSession, StopEvent
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


def read_dap_message(stream: IO[bytes]) -> dict | None:
    """Reads one `Content-Length`-framed DAP JSON message. Returns None at
    EOF (the client closed its side, e.g. VS Code exiting)."""
    headers: dict[str, str] = {}
    while True:
        line = stream.readline()
        if line == b"":
            return None
        line = line.decode("ascii").rstrip("\r\n")
        if line == "":
            break
        name, _, value = line.partition(":")
        headers[name.strip().lower()] = value.strip()
    length = int(headers.get("content-length", "0"))
    body = stream.read(length)
    return json.loads(body.decode("utf-8"))


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

    def run(self) -> None:
        """The adapter's main loop: read requests until the client
        disconnects or its stdin closes, dispatching each to a handler."""
        while not self._done:
            message = read_dap_message(self._input)
            if message is None:
                self._shutdown()
                return
            if message.get("type") != "request":
                continue
            self._dispatch(message)

    def _dispatch(self, request: dict) -> None:
        command = request["command"]
        handler = getattr(self, f"_handle_{command}", None)
        if handler is None:
            self._send_response(request, success=False, message=f"unsupported request: {command}")
            return
        handler(request)

    # -- Protocol plumbing ------------------------------------------------

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def _send_response(
        self, request: dict, success: bool, body: dict | None = None, message: str | None = None
    ) -> None:
        response = {
            "seq": self._next_seq(),
            "type": "response",
            "request_seq": request["seq"],
            "success": success,
            "command": request["command"],
        }
        if body is not None:
            response["body"] = body
        if message is not None:
            response["message"] = message
        write_dap_message(self._output, response)

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
        try:
            self._session = self._launch_session(arguments)
        except Exception as exc:  # noqa: BLE001 -- surfaced to the client, not swallowed
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
        breakpoints = []
        for source_bp in arguments.get("breakpoints", []):
            original_line = source_bp["line"]
            reason = session.line_map.reject_reason(original_line)
            if reason is not None:
                breakpoints.append({"verified": False, "line": original_line, "message": reason})
                continue
            instrumented_line = session.line_map.to_instrumented(original_line)
            bkpt = session.gdb.set_breakpoint(session.instrumented_file, instrumented_line)
            breakpoints.append({"verified": True, "line": original_line, "id": int(bkpt["number"])})
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
            body={"scopes": [{"name": "Working-Storage", "variablesReference": 1, "expensive": False}]},
        )

    def _handle_variables(self, request: dict) -> None:
        session = self._require_session(request)
        if session is None:
            return
        variables = []
        for name, expr in session.variable_table.items():
            value = read_variable(session.gdb, name, expr)
            variables.append({"name": name, "value": _display_value(value), "variablesReference": 0})
        self._send_response(request, success=True, body={"variables": variables})

    def _handle_continue(self, request: dict) -> None:
        session = self._require_session(request)
        if session is None:
            return
        self._send_response(request, success=True, body={"allThreadsContinued": True})
        self._resume(session.gdb.continue_)

    def _handle_next(self, request: dict) -> None:
        self._step(request, "next")

    def _handle_stepIn(self, request: dict) -> None:
        # v1 does not step across a mocked CALL boundary (see design doc
        # Non-goals) -- aliased to the same coalesced-next behavior.
        self._step(request, "stepIn")

    def _handle_stepOut(self, request: dict) -> None:
        self._step(request, "stepOut")

    def _step(self, request: dict, _dap_command: str) -> None:
        session = self._require_session(request)
        if session is None:
            return
        self._send_response(request, success=True)
        self._resume(lambda: session.gdb.step(session.instrumented_file))

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
            self._send_response(request, success=False, message="no active debug session")
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
        reason = {"breakpoint": "breakpoint", "step": "step", "crashed": "exception"}[event.reason]
        self._send_event(
            "stopped", {"reason": reason, "threadId": _MAIN_THREAD_ID, "allThreadsStopped": True}
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
