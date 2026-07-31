"""End-to-end proof for `mockymock debug --dap-stdio` against real
GnuCOBOL + gdb.

The unit tests (test_gdb_session.py, test_variable_map.py,
test_call_stack.py, test_adapter.py) all mock Docker/gdb away via canned
MI transcripts captured from a real session -- this is the only place the
full stack is proven to compose against a live container: compiling with
`-g`, starting a real `docker exec -i gdb --interpreter=mi2` session,
setting a breakpoint on an ORIGINAL `.cbl` line (through the splicer's
real line map, not an identity stand-in), stopping there, reading back
COBOL-named variables with correctly decoded values, and stepping.

See docs/2026-07-22-dap-debugger-design.md and
docs/superpowers/plans/2026-07-22-dap-debugger-cli.md (Task 9).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from tests.integration._docker import requires_docker

FIXTURE_DIR = Path(__file__).parent / "fixtures"
CASE = "runs the loop"


class _DapClient:
    """Hand-frames DAP JSON over a real subprocess's stdio -- no VS Code
    involved, exactly what `DebugAdapterDescriptorFactory` on the
    extension side would drive."""

    def __init__(self, process: subprocess.Popen):
        self._process = process
        self._seq = 0

    def send(self, command: str, arguments: dict | None = None) -> int:
        self._seq += 1
        message = {"seq": self._seq, "type": "request", "command": command}
        if arguments is not None:
            message["arguments"] = arguments
        body = json.dumps(message).encode("utf-8")
        assert self._process.stdin is not None
        self._process.stdin.write(
            f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body
        )
        self._process.stdin.flush()
        return self._seq

    def read_one(self) -> dict | None:
        assert self._process.stdout is not None
        headers: dict[str, str] = {}
        while True:
            line = self._process.stdout.readline()
            if line == b"":
                return None
            line = line.decode("ascii").rstrip("\r\n")
            if line == "":
                break
            name, _, value = line.partition(":")
            headers[name.strip().lower()] = value.strip()
        length = int(headers.get("content-length", "0"))
        body = self._process.stdout.read(length)
        return json.loads(body.decode("utf-8"))

    def read_until(self, predicate, limit: int = 60) -> list[dict]:
        messages = []
        for _ in range(limit):
            message = self.read_one()
            if message is None:
                stderr = (
                    self._process.stderr.read().decode() if self._process.stderr else ""
                )
                raise AssertionError(
                    f"DAP stream closed unexpectedly; stderr:\n{stderr}"
                )
            messages.append(message)
            if predicate(message):
                return messages
        raise AssertionError(
            f"predicate never matched within {limit} messages: {messages}"
        )


@requires_docker
def test_debug_session_breaks_steps_and_reports_variables():
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "mockymock.cli.main",
            "debug",
            str(FIXTURE_DIR / "debug_spike.cbl"),
            "--cut",
            str(FIXTURE_DIR / "debug_spike.cut"),
            "--case",
            CASE,
            "--dap-stdio",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    client = _DapClient(process)
    try:
        client.send("initialize", {})
        client.read_until(lambda m: m.get("event") == "initialized")

        client.send("launch", {})
        launch_responses = client.read_until(lambda m: m.get("command") == "launch")
        assert launch_responses[-1]["success"] is True

        client.send(
            "setBreakpoints",
            {"source": {"path": "debug_spike.cbl"}, "breakpoints": [{"line": 17}]},
        )
        bp_responses = client.read_until(lambda m: m.get("command") == "setBreakpoints")
        assert bp_responses[-1]["body"]["breakpoints"] == [
            {"verified": True, "line": 17, "id": 1}
        ]

        client.send("configurationDone", {})
        run_messages = client.read_until(lambda m: m.get("event") == "stopped")
        stopped = run_messages[-1]
        assert stopped["body"]["reason"] == "breakpoint"

        # The suite driver's own protocol markers must have been forwarded
        # live as DAP output events, proving program stdout genuinely
        # interleaves with MI records rather than getting lost or corrupting
        # the parser (Empirical basis, question 6).
        output_text = "".join(
            m["body"]["output"] for m in run_messages if m.get("event") == "output"
        )
        assert "__MOCKYMOCK__ TESTSUITE: debug spike" in output_text
        assert "LOOP ITER +0001" in output_text
        assert "LOOP ITER +0003" in output_text

        client.send("stackTrace", {"threadId": 1})
        stack_responses = client.read_until(lambda m: m.get("command") == "stackTrace")
        frames = stack_responses[-1]["body"]["stackFrames"]
        assert frames[0]["line"] == 17
        assert frames[0]["name"] == "MAIN-PARA"

        client.send("variables", {"variablesReference": 1})
        var_responses = client.read_until(lambda m: m.get("command") == "variables")
        variables = {
            v["name"]: v["value"] for v in var_responses[-1]["body"]["variables"]
        }
        assert variables["WS-CUSTOMER-ID"] == "CUST00001 "
        # 123.45 + three ADD 1s inside the loop.
        assert variables["WS-BALANCE"] == "00126.45"
        assert variables["WS-COUNTER"] == "4"

        # Step over the DISPLAY. The fixture keeps one more ordinary
        # statement (MOVE 0 TO WS-COUNTER, line 18) between this line and
        # STOP RUN on purpose: the splicer replaces the STOP RUN
        # terminator with driver bookkeeping that has no original-line
        # counterpart, so a step-over from the *last* visible statement
        # of the case has nothing visible left to land on -- GdbSession.step
        # then (correctly) coalesces through the driver to program exit
        # and reports `terminated` instead of a step stop. Line 18 gives
        # the step a real, mapped landing line, which is exactly what
        # this assertion exists to prove.
        client.send("next", {"threadId": 1})
        step_messages = client.read_until(
            lambda m: m.get("event") in ("stopped", "terminated")
        )
        assert step_messages[-1]["event"] == "stopped"
        assert step_messages[-1]["body"]["reason"] == "step"
        step_output = "".join(
            m["body"]["output"] for m in step_messages if m.get("event") == "output"
        )
        assert "FINAL BALANCE 00126.45" in step_output

        client.send("disconnect", {})
        client.read_until(lambda m: m.get("command") == "disconnect")
    finally:
        process.wait(timeout=15)

    assert process.returncode == 0
