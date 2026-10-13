"""Tests for the DAP adapter's request/response/event plumbing. Drives a
real DapAdapter over io.BytesIO streams with hand-framed DAP JSON, exactly
as a real client would send it -- no Docker/gdb involved, via a fake
DebugSession built from fake gdb responses."""

import io
import json

from mockymock.debug.adapter import (
    DapAdapter,
    DebugSession,
    read_dap_message,
)
from mockymock.debug.call_stack import ParagraphIndex
from mockymock.debug.gdb_session import GdbSessionClosedError, ResultRecord, StopEvent
from mockymock.debug.line_map import LineMap


def _frame(message: dict) -> bytes:
    body = json.dumps(message).encode("utf-8")
    return f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body


def _request(seq: int, command: str, arguments: dict | None = None) -> dict:
    message = {"seq": seq, "type": "request", "command": command}
    if arguments is not None:
        message["arguments"] = arguments
    return message


class _FakeGdb:
    """A minimal stand-in for GdbSession, covering only what the adapter's
    request handlers call directly. Breakpoints/run-control/variable
    reads are exercised for real in test_gdb_session.py/test_variable_map.py
    /test_call_stack.py -- this test is about the DAP plumbing around them."""

    def __init__(self):
        self.breakpoints: dict[int, tuple[str, int]] = {}
        self.deleted: list[int] = []
        self._next_number = 0
        self.closed = False
        self._output_handler = None

    def set_output_handler(self, on_output):
        self._output_handler = on_output

    def set_breakpoint(self, file, line):
        # Monotonic numbering (never reused), like real gdb -- so a replace
        # deletes old numbers and hands out fresh ones.
        self._next_number += 1
        self.breakpoints[self._next_number] = (file, line)
        return {"number": str(self._next_number)}

    def delete_breakpoint(self, number):
        self.deleted.append(number)
        self.breakpoints.pop(number, None)

    def run(self) -> StopEvent:
        if self._output_handler:
            self._output_handler("LOOP ITER +0001")
        return StopEvent(reason="breakpoint", file="/work/x/fixture.cbl", line=20)

    def continue_(self) -> StopEvent:
        return StopEvent(reason="exited", exit_code=0)

    def step(self, original_file_hint, is_visible_line=None):
        return StopEvent(reason="step", file="/work/x/fixture.cbl", line=21)

    def close(self):
        self.closed = True

    # Used by call_stack.synthesize_stack and variable_map.read_variable,
    # both via gdb_session.evaluate().
    def send(self, command):
        if command == "-data-evaluate-expression frame_ptr-frame_stack":
            return [ResultRecord("done", {"value": "0"})]
        if command == "-data-evaluate-expression (int)(b_17).attr->type":
            # b_17 is a plain PIC X buffer with no cob_field wrapper --
            # confirmed empirically (variable_map.py's module docstring).
            return [ResultRecord("error", {"msg": "There is no member named attr."})]
        if command == "-data-evaluate-expression b_17":
            return [ResultRecord("done", {"value": '"CUST00001 "'})]
        raise AssertionError(f"unexpected command: {command!r}")


def _identity_line_map(max_line: int = 30) -> LineMap:
    identity = {i: i for i in range(1, max_line + 1)}
    return LineMap(_to_original=identity, _to_instrumented=identity)


def _fake_launch_session(arguments: dict) -> DebugSession:
    return DebugSession(
        gdb=_FakeGdb(),
        line_map=_identity_line_map(),
        variable_table={"WS-CUSTOMER-ID": "b_17"},
        generated_c_lines=[],
        paragraph_index=ParagraphIndex(
            paragraph_starts=[(9, "MAIN-PARA")], section_starts=[]
        ),
        instrumented_file="fixture.cbl",
    )


def _drain(output_stream: io.BytesIO) -> list[dict]:
    output_stream.seek(0)
    messages = []
    while True:
        message = read_dap_message(output_stream)
        if message is None:
            break
        messages.append(message)
    return messages


def _run_adapter(requests: list[dict]) -> list[dict]:
    input_stream = io.BytesIO(b"".join(_frame(r) for r in requests))
    output_stream = io.BytesIO()
    adapter = DapAdapter(input_stream, output_stream, _fake_launch_session)
    adapter.run()
    return _drain(output_stream)


def _run_adapter_capturing_session(requests, launch=None):
    """Like _run_adapter but returns (messages, session) so a test can
    inspect the fake gdb's post-run state."""
    input_stream = io.BytesIO(b"".join(_frame(r) for r in requests))
    output_stream = io.BytesIO()
    sessions = []

    def _launch(arguments):
        session = (launch or _fake_launch_session)(arguments)
        sessions.append(session)
        return session

    adapter = DapAdapter(input_stream, output_stream, _launch)
    adapter.run()
    return _drain(output_stream), sessions[0]


def test_initialize_responds_with_capabilities_and_initialized_event():
    messages = _run_adapter([_request(1, "initialize", {})])

    response = messages[0]
    assert response["type"] == "response"
    assert response["success"] is True
    assert response["command"] == "initialize"
    assert response["body"]["supportsConfigurationDoneRequest"] is True
    assert messages[1] == {"seq": 2, "type": "event", "event": "initialized"}


def test_launch_then_set_breakpoints_resolves_via_line_map():
    messages = _run_adapter(
        [
            _request(1, "launch", {}),
            _request(
                2,
                "setBreakpoints",
                {"source": {"path": "fixture.cbl"}, "breakpoints": [{"line": 14}]},
            ),
        ]
    )

    launch_response, set_bp_response = messages
    assert launch_response["success"] is True
    assert set_bp_response["success"] is True
    assert set_bp_response["body"]["breakpoints"] == [
        {"verified": True, "line": 14, "id": 1}
    ]


def test_configuration_done_runs_and_emits_stopped_event():
    messages = _run_adapter(
        [
            _request(1, "launch", {}),
            _request(2, "configurationDone", {}),
        ]
    )

    events = [m for m in messages if m["type"] == "event"]
    output_events = [e for e in events if e["event"] == "output"]
    stopped_events = [e for e in events if e["event"] == "stopped"]

    assert output_events == [
        {
            "seq": output_events[0]["seq"],
            "type": "event",
            "event": "output",
            "body": {"category": "stdout", "output": "LOOP ITER +0001\n"},
        }
    ]
    assert stopped_events[0]["body"]["reason"] == "breakpoint"
    assert stopped_events[0]["body"]["threadId"] == 1


def test_continue_reports_exited_and_terminated():
    messages = _run_adapter(
        [
            _request(1, "launch", {}),
            _request(2, "continue", {"threadId": 1}),
        ]
    )

    events = [m["event"] for m in messages if m["type"] == "event"]
    assert "exited" in events
    assert "terminated" in events


def test_stack_trace_after_a_stop_reports_the_current_frame():
    messages = _run_adapter(
        [
            _request(1, "launch", {}),
            _request(2, "configurationDone", {}),
            _request(3, "stackTrace", {"threadId": 1}),
        ]
    )

    stack_response = messages[-1]
    assert stack_response["command"] == "stackTrace"
    assert stack_response["success"] is True
    frames = stack_response["body"]["stackFrames"]
    assert len(frames) == 1
    assert frames[0]["line"] == 20
    assert frames[0]["name"] == "MAIN-PARA"


def test_variables_reports_decoded_values():
    messages = _run_adapter(
        [
            _request(1, "launch", {}),
            _request(2, "variables", {"variablesReference": 1}),
        ]
    )

    variables_response = messages[-1]
    assert variables_response["body"]["variables"] == [
        {"name": "WS-CUSTOMER-ID", "value": "CUST00001 ", "variablesReference": 0}
    ]


def test_evaluate_reports_the_decoded_value_for_a_known_variable():
    """VS Code sends `evaluate` for the Watch panel, hover-inspect, and the
    Debug Console -- all three share this one handler in v1."""
    messages = _run_adapter(
        [
            _request(1, "launch", {}),
            _request(
                2,
                "evaluate",
                {"expression": "WS-CUSTOMER-ID", "context": "watch"},
            ),
        ]
    )

    evaluate_response = messages[-1]
    assert evaluate_response["success"] is True
    assert evaluate_response["body"]["result"] == "CUST00001 "
    assert evaluate_response["body"]["variablesReference"] == 0


def test_evaluate_matches_a_variable_name_case_insensitively():
    """COBOL names are case-insensitive, but the variable table keeps the
    declaration's own spelling (cobc copies it verbatim into the .c.l.h
    comment). Hovering `ws-customer-id` where the program declared
    `WS-CUSTOMER-ID` -- or the reverse -- answered "unknown variable"."""
    messages = _run_adapter(
        [
            _request(1, "launch", {}),
            _request(
                2,
                "evaluate",
                {"expression": "ws-customer-id", "context": "hover"},
            ),
        ]
    )

    evaluate_response = messages[-1]
    assert evaluate_response["success"] is True
    assert evaluate_response["body"]["result"] == "CUST00001 "


def test_evaluate_of_unknown_expression_fails_cleanly():
    """v1 only resolves plain COBOL identifiers already in the variable
    table -- no arithmetic/member-access expression evaluation (see
    design doc Non-goals)."""
    messages = _run_adapter(
        [
            _request(1, "launch", {}),
            _request(
                2,
                "evaluate",
                {"expression": "WS-CUSTOMER-ID + 1", "context": "watch"},
            ),
        ]
    )

    evaluate_response = messages[-1]
    assert evaluate_response["success"] is False


def test_requests_before_launch_fail_cleanly():
    messages = _run_adapter(
        [_request(1, "setBreakpoints", {"source": {"path": "x"}, "breakpoints": []})]
    )

    assert messages[0]["success"] is False
    assert "no active debug session" in messages[0]["message"]


def test_disconnect_closes_the_gdb_session():
    _messages, session = _run_adapter_capturing_session(
        [_request(1, "launch", {}), _request(2, "disconnect", {})]
    )
    assert session.gdb.closed is True


def test_second_launch_closes_the_first_session_and_resets_breakpoints():
    """Audit finding F16: a second `launch` used to unconditionally
    overwrite self._session without closing the first GdbSession --
    leaking its docker exec/gdb subprocess -- and left
    self._breakpoint_numbers stale, pointing at IDs from the now-orphaned
    session."""
    requests = [
        _request(1, "launch", {}),
        _request(
            2,
            "setBreakpoints",
            {"source": {"path": "fixture.cbl"}, "breakpoints": [{"line": 14}]},
        ),
        _request(3, "launch", {}),
        _request(
            4,
            "setBreakpoints",
            {"source": {"path": "fixture.cbl"}, "breakpoints": [{"line": 20}]},
        ),
    ]
    input_stream = io.BytesIO(b"".join(_frame(r) for r in requests))
    output_stream = io.BytesIO()
    sessions = []

    def _launch(arguments):
        session = _fake_launch_session(arguments)
        sessions.append(session)
        return session

    adapter = DapAdapter(input_stream, output_stream, _launch)
    adapter.run()
    messages = _drain(output_stream)

    assert len(sessions) == 2
    assert sessions[0].gdb.closed is True
    # The second session's setBreakpoints must not try to delete a
    # breakpoint number left over from the first (now-closed) session.
    assert sessions[1].gdb.deleted == []
    assert list(sessions[1].gdb.breakpoints.values()) == [("fixture.cbl", 20)]
    assert all(m["success"] for m in messages)


def test_malformed_content_length_header_shuts_down_cleanly():
    """Audit finding F17: a garbled Content-Length must not raise an
    unhandled ValueError straight out of run()'s top-level loop and kill
    the adapter process -- every other framing problem (EOF, an
    unsupported command) degrades gracefully; this must too."""
    input_stream = io.BytesIO(b"Content-Length: not-a-number\r\n\r\n")
    output_stream = io.BytesIO()
    adapter = DapAdapter(input_stream, output_stream, _fake_launch_session)

    adapter.run()  # must not raise

    messages = _drain(output_stream)
    assert any(m.get("event") == "output" for m in messages)


def test_missing_content_length_header_shuts_down_cleanly():
    """Code review on the F17 fix, PR #57: a missing header used to default
    to length 0 -- not caught as DapFramingError at all, `json.loads(b"")`
    raised an unrelated JSONDecodeError that escaped run()'s handling."""
    input_stream = io.BytesIO(b"\r\n")  # blank headers section, no length
    output_stream = io.BytesIO()
    adapter = DapAdapter(input_stream, output_stream, _fake_launch_session)

    adapter.run()  # must not raise

    messages = _drain(output_stream)
    assert any(m.get("event") == "output" for m in messages)


def test_zero_content_length_header_shuts_down_cleanly():
    """Same gap as the missing-header case: the smallest real DAP body is
    `{}` (2 bytes), so Content-Length: 0 can only be a corrupted frame."""
    input_stream = io.BytesIO(b"Content-Length: 0\r\n\r\n")
    output_stream = io.BytesIO()
    adapter = DapAdapter(input_stream, output_stream, _fake_launch_session)

    adapter.run()  # must not raise

    messages = _drain(output_stream)
    assert any(m.get("event") == "output" for m in messages)


def test_negative_content_length_header_shuts_down_cleanly():
    """A negative length used to reach `stream.read(n)` with n < 0, which
    reads-to-EOF instead of raising -- on a live stdin pipe that blocks
    forever rather than a bounded BytesIO, so this only reproduces the
    *acceptance* half here (no crash, no hang) rather than the hang
    itself."""
    input_stream = io.BytesIO(b"Content-Length: -5\r\n\r\ngarbage-trailer")
    output_stream = io.BytesIO()
    adapter = DapAdapter(input_stream, output_stream, _fake_launch_session)

    adapter.run()  # must not raise

    messages = _drain(output_stream)
    assert any(m.get("event") == "output" for m in messages)


def test_unsupported_command_gets_a_clean_failure_response():
    messages = _run_adapter([_request(1, "notARealDapCommand", {})])
    assert messages[0]["success"] is False
    assert "unsupported request" in messages[0]["message"]


def test_truncated_body_shuts_down_cleanly():
    """2026-08-12 audit Finding 6: a client dying mid-send leaves a valid
    Content-Length header but a short body -- stream.read() returns the
    short read without raising, then json.loads on the truncated JSON
    raised a JSONDecodeError that run() (catching only DapFramingError)
    let kill the whole adapter process instead of the documented
    fail-closed shutdown."""
    input_stream = io.BytesIO(b'Content-Length: 500\r\n\r\n{"type": "requ')
    output_stream = io.BytesIO()
    adapter = DapAdapter(input_stream, output_stream, _fake_launch_session)

    adapter.run()  # must not raise

    messages = _drain(output_stream)
    assert any(m.get("event") == "output" for m in messages)


def test_non_utf8_body_shuts_down_cleanly():
    """Companion to the truncated-body case: a body that is not valid
    UTF-8 raised a UnicodeDecodeError out of run()'s loop."""
    body = b"\xff\xfe{}"
    frame = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body
    input_stream = io.BytesIO(frame)
    output_stream = io.BytesIO()
    adapter = DapAdapter(input_stream, output_stream, _fake_launch_session)

    adapter.run()  # must not raise

    messages = _drain(output_stream)
    assert any(m.get("event") == "output" for m in messages)


def test_non_ascii_header_shuts_down_cleanly():
    """A header line that is not ASCII raised a UnicodeDecodeError from
    read_dap_message's header decode, same escape path as the body cases."""
    input_stream = io.BytesIO(b"Content-Length: 2\r\nX-Junk: caf\xc3\xa9\r\n\r\n{}")
    output_stream = io.BytesIO()
    adapter = DapAdapter(input_stream, output_stream, _fake_launch_session)

    adapter.run()  # must not raise

    messages = _drain(output_stream)
    assert any(m.get("event") == "output" for m in messages)


def test_request_missing_command_gets_a_clean_failure_response():
    """2026-08-12 audit Finding 7: _dispatch indexed request["command"]
    before its try/except, so a request without one raised an uncaught
    KeyError out of the loop."""
    messages = _run_adapter([{"seq": 1, "type": "request"}])
    assert messages[0]["type"] == "response"
    assert messages[0]["success"] is False


def test_request_missing_seq_gets_a_clean_failure_response():
    """Finding 7's worse half: a failing handler's recovery path itself
    indexed request["seq"] inside _send_response -- the code meant to
    keep a malformed request from killing the session was what killed it."""
    # No arguments -> _handle_setBreakpoints raises KeyError; the failure
    # response must still be written even with no seq to echo.
    messages = _run_adapter(
        [
            _request(1, "launch", {}),
            {"type": "request", "command": "setBreakpoints"},
        ]
    )
    failure = messages[-1]
    assert failure["type"] == "response"
    assert failure["success"] is False


def test_stack_trace_before_new_session_stops_reports_no_frames():
    """2026-08-12 audit Finding 9: a relaunch reset the session and
    breakpoint numbers (F16) but not _current_stop, so a stackTrace sent
    after the second launch and before the new session's first stop
    synthesized a stack from the PREVIOUS session's stale stop location
    instead of reporting no frames."""
    messages = _run_adapter(
        [
            _request(1, "launch", {}),
            _request(2, "configurationDone", {}),  # first session stops
            _request(3, "launch", {}),  # relaunch: no stop yet
            _request(4, "stackTrace", {"threadId": 1}),
        ]
    )
    stack_response = next(m for m in messages if m.get("command") == "stackTrace")
    assert stack_response["success"] is True
    assert stack_response["body"]["stackFrames"] == []


def test_set_breakpoints_replaces_the_previous_set_for_that_source():
    """DAP setBreakpoints replaces ALL breakpoints for a source. gdb has
    no per-file clear, so the adapter must delete the numbers it inserted
    before inserting the new set -- otherwise an un-checked breakpoint
    stays live in gdb and the program keeps stopping at it."""
    _messages, session = _run_adapter_capturing_session(
        [
            _request(1, "launch", {}),
            _request(
                2,
                "setBreakpoints",
                {"source": {"path": "fixture.cbl"}, "breakpoints": [{"line": 14}]},
            ),
            # The user un-checks line 14 and checks line 20 instead.
            _request(
                3,
                "setBreakpoints",
                {"source": {"path": "fixture.cbl"}, "breakpoints": [{"line": 20}]},
            ),
        ]
    )

    # The first breakpoint (gdb number 1) was deleted before the second set.
    assert session.gdb.deleted == [1]
    # Only the second breakpoint (a fresh number, line 20) is now live.
    assert list(session.gdb.breakpoints.values()) == [("fixture.cbl", 20)]


def test_set_breakpoints_with_empty_list_clears_the_source():
    _messages, session = _run_adapter_capturing_session(
        [
            _request(1, "launch", {}),
            _request(
                2,
                "setBreakpoints",
                {"source": {"path": "fixture.cbl"}, "breakpoints": [{"line": 14}]},
            ),
            _request(
                3,
                "setBreakpoints",
                {"source": {"path": "fixture.cbl"}, "breakpoints": []},
            ),
        ]
    )
    assert session.gdb.deleted == [1]
    assert session.gdb.breakpoints == {}


def test_handler_exception_before_responding_becomes_a_failed_response():
    """A malformed request (here, setBreakpoints with no source) must not
    kill the adapter loop -- it becomes a failed DAP response, and the
    adapter keeps serving subsequent requests."""
    messages = _run_adapter(
        [
            _request(1, "launch", {}),
            _request(2, "setBreakpoints", {"breakpoints": []}),  # missing source
            _request(3, "threads", {}),  # must still be served afterward
        ]
    )
    by_command = {m.get("command"): m for m in messages if m["type"] == "response"}
    assert by_command["setBreakpoints"]["success"] is False
    # The adapter survived and answered the next request.
    assert by_command["threads"]["success"] is True


def test_resume_failure_after_responding_terminates_cleanly():
    """The run-control handlers answer BEFORE resuming, so a broken gdb
    session mid-resume can't become a second response for the same request
    (a protocol violation) -- it terminates the session instead."""

    class _DyingGdb(_FakeGdb):
        def run(self):
            raise RuntimeError("gdb died")

    def launch(arguments):
        session = _fake_launch_session(arguments)
        session.gdb = _DyingGdb()
        return session

    messages, _session = _run_adapter_capturing_session(
        [_request(1, "launch", {}), _request(2, "configurationDone", {})],
        launch=launch,
    )
    # configurationDone got exactly one (successful) response...
    config_responses = [m for m in messages if m.get("command") == "configurationDone"]
    assert len(config_responses) == 1
    assert config_responses[0]["success"] is True
    # ...and the broken resume terminated the session rather than crashing.
    assert any(m.get("event") == "terminated" for m in messages)


# --- code review on the F4 fix (PR #57): GdbSessionClosedError specifically
# means the gdb subprocess is confirmed dead, unlike a GdbCommandError or a
# malformed-request exception -- _dispatch must tear the session down (not
# just fail the request or set _done) so nothing tries to reuse it -------


def test_before_response_session_death_shuts_down_the_gdb_session():
    """A GdbSessionClosedError from a before-response handler (evaluate,
    variables, stackTrace, setBreakpoints) used to just fail that one
    request and leave the dead session in self._session -- the next
    request would try it again and hang for another read deadline instead
    of failing fast with 'no active debug session'."""

    class _DeadGdb(_FakeGdb):
        def send(self, command):
            raise GdbSessionClosedError("gdb produced no output for 30s")

    def launch(arguments):
        session = _fake_launch_session(arguments)
        session.gdb = _DeadGdb()
        return session

    messages, session = _run_adapter_capturing_session(
        [
            _request(1, "launch", {}),
            _request(2, "evaluate", {"expression": "WS-CUSTOMER-ID"}),
            _request(3, "evaluate", {"expression": "WS-CUSTOMER-ID"}),
        ],
        launch=launch,
    )
    by_seq = {m.get("request_seq"): m for m in messages if m["type"] == "response"}
    assert by_seq[2]["success"] is False
    assert session.gdb.closed is True
    assert by_seq[3]["success"] is False
    assert "no active debug session" in by_seq[3]["message"]


def test_resume_session_death_shuts_down_the_gdb_session():
    """The run-control path (test_resume_failure_after_responding_
    terminates_cleanly above) reports 'terminated' and stops the adapter
    loop, but never actually called _shutdown() -- the dead gdb subprocess
    was never closed/terminated, leaking it into the shared container."""

    class _DyingGdb(_FakeGdb):
        def run(self):
            raise GdbSessionClosedError("gdb produced no output for 30s")

    def launch(arguments):
        session = _fake_launch_session(arguments)
        session.gdb = _DyingGdb()
        return session

    messages, session = _run_adapter_capturing_session(
        [_request(1, "launch", {}), _request(2, "configurationDone", {})],
        launch=launch,
    )
    assert any(m.get("event") == "terminated" for m in messages)
    assert session.gdb.closed is True


def _launch_with_original_file(arguments: dict) -> DebugSession:
    session = _fake_launch_session(arguments)
    session.original_file = "/proj/cobol/PROG.cbl"
    return session


def test_set_breakpoints_in_another_source_is_unverified_not_set_in_the_program():
    """A breakpoint in a copybook (or any source other than the program
    under test) used to be keyed only by line number and inserted at that
    line of the instrumented main program -- line 14 of CUSTREC.cpy became
    a live gdb breakpoint at line 14 of PROG.cbl. The line map only covers
    the program's own source, so every other source must come back
    unverified with nothing inserted in gdb."""
    messages, session = _run_adapter_capturing_session(
        [
            _request(1, "launch", {}),
            _request(
                2,
                "setBreakpoints",
                {
                    "source": {"path": "/proj/copybook/CUSTREC.cpy"},
                    "breakpoints": [{"line": 14}],
                },
            ),
        ],
        launch=_launch_with_original_file,
    )

    response = messages[-1]
    assert response["success"] is True
    [bp] = response["body"]["breakpoints"]
    assert bp["verified"] is False
    assert bp["line"] == 14
    assert "CUSTREC.cpy" in bp["message"]
    assert session.gdb.breakpoints == {}


def test_set_breakpoints_in_a_same_named_file_elsewhere_is_unverified():
    messages, session = _run_adapter_capturing_session(
        [
            _request(1, "launch", {}),
            _request(
                2,
                "setBreakpoints",
                {
                    "source": {"path": "/other/checkout/PROG.cbl"},
                    "breakpoints": [{"line": 14}],
                },
            ),
        ],
        launch=_launch_with_original_file,
    )

    assert messages[-1]["body"]["breakpoints"][0]["verified"] is False
    assert session.gdb.breakpoints == {}


def test_set_breakpoints_in_the_program_source_still_resolves():
    messages, session = _run_adapter_capturing_session(
        [
            _request(1, "launch", {}),
            _request(
                2,
                "setBreakpoints",
                {
                    "source": {"path": "/proj/cobol/../cobol/PROG.cbl"},
                    "breakpoints": [{"line": 14}],
                },
            ),
            # A relative path (as tests/integration/test_debug.py sends)
            # matches by trailing path components.
            _request(
                3,
                "setBreakpoints",
                {"source": {"path": "PROG.cbl"}, "breakpoints": [{"line": 20}]},
            ),
        ],
        launch=_launch_with_original_file,
    )

    responses = [m for m in messages if m.get("command") == "setBreakpoints"]
    assert responses[0]["body"]["breakpoints"] == [
        {"verified": True, "line": 14, "id": 1}
    ]
    assert responses[1]["body"]["breakpoints"] == [
        {"verified": True, "line": 20, "id": 2}
    ]


def test_stack_trace_source_is_the_program_not_the_last_breakpoint_source():
    """Setting (rejected) breakpoints in a copybook after the program's own
    must not relabel every stack frame as being in that copybook."""
    messages, _session = _run_adapter_capturing_session(
        [
            _request(1, "launch", {}),
            _request(
                2,
                "setBreakpoints",
                {
                    "source": {"path": "/proj/cobol/PROG.cbl"},
                    "breakpoints": [{"line": 20}],
                },
            ),
            _request(
                3,
                "setBreakpoints",
                {
                    "source": {"path": "/proj/copybook/CUSTREC.cpy"},
                    "breakpoints": [{"line": 5}],
                },
            ),
            _request(4, "configurationDone", {}),
            _request(5, "stackTrace", {"threadId": 1}),
        ],
        launch=_launch_with_original_file,
    )

    stack_response = next(m for m in messages if m.get("command") == "stackTrace")
    frames = stack_response["body"]["stackFrames"]
    assert frames[0]["source"]["path"] == "/proj/cobol/PROG.cbl"


class _SteppingGdb(_FakeGdb):
    """Replays a scripted run of line steps, each with the PERFORM depth
    (`frame_ptr-frame_stack`) the program is at after it -- the shape of
    issue #167's STP.cbl: MAIN-PARA (depth 0) performs SUB-PARA (depth 1),
    whose line 15 performs LEAF-PARA (lines 17-18, depth 2)."""

    def __init__(self, start_depth, script):
        super().__init__()
        self.depth = start_depth
        self._script = list(script)
        self.steps = 0
        self.continued = False

    def step(self, original_file_hint, is_visible_line=None):
        self.steps += 1
        reason, line, self.depth = self._script.pop(0)
        return StopEvent(reason=reason, file="/work/x/fixture.cbl", line=line)

    def continue_(self):
        self.continued = True
        return super().continue_()

    def send(self, command):
        if command == "-data-evaluate-expression frame_ptr-frame_stack":
            return [ResultRecord("done", {"value": str(self.depth)})]
        return super().send(command)


_STP_FROM_LINE_15 = [
    ("step", 17, 2),  # into LEAF-PARA
    ("step", 18, 2),
    ("step", 16, 1),  # back in SUB-PARA, after the PERFORM
    ("step", 10, 0),  # SUB-PARA returned to MAIN-PARA
]


def _run_step(command, start_depth, script):
    gdb = _SteppingGdb(start_depth, script)

    def launch(arguments):
        session = _fake_launch_session(arguments)
        session.gdb = gdb
        return session

    messages, _session = _run_adapter_capturing_session(
        [_request(1, "launch", {}), _request(2, command, {"threadId": 1})],
        launch=launch,
    )
    events = [m for m in messages if m["type"] == "event"]
    return events, gdb


def _stopped_line(gdb):
    return gdb.steps and _STP_FROM_LINE_15[gdb.steps - 1][1]


def test_step_over_a_perform_stops_on_the_next_line_of_the_paragraph():
    events, gdb = _run_step("next", 1, _STP_FROM_LINE_15)

    assert [e["body"]["reason"] for e in events if e["event"] == "stopped"] == ["step"]
    assert gdb.steps == 3
    assert _stopped_line(gdb) == 16


def test_step_in_enters_the_performed_paragraph():
    _events, gdb = _run_step("stepIn", 1, _STP_FROM_LINE_15)

    assert gdb.steps == 1
    assert _stopped_line(gdb) == 17


def test_step_out_returns_to_the_performing_paragraph():
    _events, gdb = _run_step("stepOut", 1, _STP_FROM_LINE_15)

    assert gdb.steps == 4
    assert _stopped_line(gdb) == 10


def test_step_over_stops_at_a_breakpoint_inside_the_performed_paragraph():
    events, gdb = _run_step(
        "next", 1, [("step", 17, 2), ("breakpoint", 18, 2), ("step", 16, 1)]
    )

    assert gdb.steps == 2
    stopped = [e for e in events if e["event"] == "stopped"]
    assert stopped[0]["body"]["reason"] == "breakpoint"


def test_step_out_of_the_top_level_runs_on_instead_of_stepping():
    events, gdb = _run_step("stepOut", 0, _STP_FROM_LINE_15)

    assert gdb.steps == 0
    assert gdb.continued
    assert "exited" in [e["event"] for e in events]
