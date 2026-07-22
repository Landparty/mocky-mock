"""Tests for the GDB/MI session wrapper.

Every record shape asserted here is a literal line captured from a real
`docker exec -i mockymock-cobc gdb --interpreter=mi2` session during the
design spike (see docs/2026-07-22-dap-debugger-design.md's Empirical
basis) -- not hand-invented MI syntax.
"""

from unittest import mock

import pytest

from mockymock.debug.gdb_session import (
    AsyncRecord,
    GdbCommandError,
    GdbSession,
    GdbSessionClosedError,
    ProgramOutput,
    ResultRecord,
    StreamRecord,
    parse_mi_line,
)


# -- parse_mi_line ---------------------------------------------------------


def test_parse_mi_line_returns_none_for_prompt():
    assert parse_mi_line("(gdb) \n") is None
    assert parse_mi_line("(gdb)\n") is None


def test_parse_mi_line_returns_none_for_blank_line():
    assert parse_mi_line("\n") is None


def test_parse_mi_line_filters_benign_aslr_warning():
    line = '&"warning: Error disabling address space randomization: Operation not permitted\\n"\n'
    assert parse_mi_line(line) is None


def test_parse_mi_line_parses_done_bkpt_result():
    line = (
        '^done,bkpt={number="1",type="breakpoint",disp="keep",enabled="y",'
        'addr="0x0000000000001499",func="SPIKE_",file="/work/fixture.cbl",'
        'fullname="/work/fixture.cbl",line="14",thread-groups=["i1"],'
        'times="0",original-location="fixture.cbl:14"}\n'
    )
    record = parse_mi_line(line)
    assert isinstance(record, ResultRecord)
    assert record.kind == "done"
    assert record.payload["bkpt"]["file"] == "/work/fixture.cbl"
    assert record.payload["bkpt"]["line"] == "14"
    assert record.payload["bkpt"]["thread-groups"] == ["i1"]


def test_parse_mi_line_parses_stopped_breakpoint_hit():
    line = (
        '*stopped,reason="breakpoint-hit",disp="keep",bkptno="1",'
        'frame={addr="0x00005566a83cf499",func="SPIKE_",'
        'args=[{name="entry",value="0"}],file="/work/fixture.cbl",'
        'fullname="/work/fixture.cbl",line="14",arch="i386:x86-64"},'
        'thread-id="1",stopped-threads="all",core="3"\n'
    )
    record = parse_mi_line(line)
    assert isinstance(record, AsyncRecord)
    assert record.kind == "stopped"
    assert record.payload["reason"] == "breakpoint-hit"
    assert record.payload["frame"]["line"] == "14"
    assert record.payload["frame"]["args"] == [{"name": "entry", "value": "0"}]


def test_parse_mi_line_parses_exited_normally():
    record = parse_mi_line('*stopped,reason="exited-normally"\n')
    assert isinstance(record, AsyncRecord)
    assert record.payload["reason"] == "exited-normally"


def test_parse_mi_line_parses_stream_record():
    record = parse_mi_line('~"Breakpoint 1, SPIKE_ (entry=0) at /work/fixture.cbl:14\\n"\n')
    assert isinstance(record, StreamRecord)
    assert record.kind == "~"
    assert "fixture.cbl:14" in record.text


def test_parse_mi_line_treats_untagged_line_as_program_output():
    """The debuggee's own DISPLAY output arrives raw, with no wrapping MI
    record -- confirmed empirically (Empirical basis, question 6)."""
    record = parse_mi_line("LOOP ITER +0001\n")
    assert isinstance(record, ProgramOutput)
    assert record.text == "LOOP ITER +0001"


def test_parse_mi_line_parses_error_result():
    record = parse_mi_line('^error,msg="The program is not being run."\n')
    assert isinstance(record, ResultRecord)
    assert record.kind == "error"
    assert record.payload["msg"] == "The program is not being run."


# -- GdbSession -------------------------------------------------------------


class _FakeStdin:
    def __init__(self):
        self.written: list[str] = []

    def write(self, text):
        self.written.append(text)

    def flush(self):
        pass


class _FakeStdout:
    def __init__(self, lines):
        self._iter = iter(lines)

    def readline(self):
        return next(self._iter, "")


class _FakeProcess:
    def __init__(self, lines):
        self.stdin = _FakeStdin()
        self.stdout = _FakeStdout(lines)
        self.returncode = None

    def poll(self):
        return self.returncode

    def terminate(self):
        self.returncode = -15

    def kill(self):
        self.returncode = -9

    def wait(self, timeout=None):
        return self.returncode


def test_send_reads_through_to_result_record():
    process = _FakeProcess(
        [
            '^done,bkpt={number="1",file="/work/fixture.cbl",line="9"}\n',
            "(gdb)\n",
        ]
    )
    session = GdbSession(process)
    records = session.send("-break-insert fixture.cbl:9")

    assert process.stdin.written == ["-break-insert fixture.cbl:9\n"]
    assert len(records) == 1
    assert isinstance(records[0], ResultRecord)


def test_set_breakpoint_returns_bkpt_dict():
    process = _FakeProcess(
        [
            '^done,bkpt={number="1",file="/work/fixture.cbl",line="9"}\n',
            "(gdb)\n",
        ]
    )
    session = GdbSession(process)
    bkpt = session.set_breakpoint("fixture.cbl", 9)
    assert bkpt == {"number": "1", "file": "/work/fixture.cbl", "line": "9"}


def test_set_breakpoint_raises_on_error():
    process = _FakeProcess(['^error,msg="No source file named fixture.cbl."\n'])
    session = GdbSession(process)
    with pytest.raises(GdbCommandError, match="No source file"):
        session.set_breakpoint("fixture.cbl", 999)


def test_run_reads_past_running_to_stopped_and_forwards_output():
    """Confirms the key empirical finding: ^running is not the stop -- the
    real *stopped arrives later, with debuggee stdout interleaved."""
    process = _FakeProcess(
        [
            "^running\n",
            '*running,thread-id="all"\n',
            "(gdb)\n",
            "LOOP ITER +0001\n",
            '~"Breakpoint 1, SPIKE_ (entry=0) at /work/fixture.cbl:14\\n"\n',
            (
                '*stopped,reason="breakpoint-hit",frame={file="/work/fixture.cbl",'
                'fullname="/work/fixture.cbl",line="14"}\n'
            ),
            "(gdb)\n",
        ]
    )
    forwarded = []
    session = GdbSession(process, on_output=forwarded.append)

    event = session.run()

    assert event.reason == "breakpoint"
    assert event.line == 14
    assert event.file == "/work/fixture.cbl"
    assert forwarded == ["LOOP ITER +0001"]


def test_run_reports_exited_normally():
    process = _FakeProcess(
        [
            "^running\n",
            "FINAL BALANCE 00126.45\n",
            '~"[Inferior 1 (process 147) exited normally]\\n"\n',
            '=thread-exited,id="1",group-id="i1"\n',
            '*stopped,reason="exited-normally"\n',
            "(gdb)\n",
        ]
    )
    forwarded = []
    session = GdbSession(process, on_output=forwarded.append)

    event = session.run()

    assert event.reason == "exited"
    assert event.exit_code == 0
    assert forwarded == ["FINAL BALANCE 00126.45"]


def test_step_coalesces_through_generated_c_body_line():
    """A single COBOL statement compiles to a marker/body pair: one
    -exec-next lands on the generated .c body line (not the .cbl marker
    for the next statement), so `step` must issue -exec-next again before
    returning -- confirmed empirically (Empirical basis, question 2)."""
    process = _FakeProcess(
        [
            # First -exec-next: lands on the generated-C body line.
            "^running\n",
            '*stopped,reason="end-stepping-range",frame={file="fixture.c",'
            'fullname="/work/fixture.c",line="115"}\n',
            "(gdb)\n",
            # Second -exec-next: lands back on the .cbl marker for the
            # next statement.
            "^running\n",
            '*stopped,reason="end-stepping-range",frame={file="fixture.cbl",'
            'fullname="/work/fixture.cbl",line="11"}\n',
            "(gdb)\n",
        ]
    )
    session = GdbSession(process)

    event = session.step("fixture.cbl")

    assert event.reason == "step"
    assert event.file == "/work/fixture.cbl"
    assert event.line == 11
    # Both -exec-next commands were actually issued.
    assert process.stdin.written == ["-exec-next\n", "-exec-next\n"]


def test_step_stops_immediately_on_breakpoint_hit_mid_step():
    process = _FakeProcess(
        [
            "^running\n",
            '*stopped,reason="breakpoint-hit",frame={file="fixture.c",'
            'fullname="/work/fixture.c",line="200"}\n',
            "(gdb)\n",
        ]
    )
    session = GdbSession(process)

    event = session.step("fixture.cbl")

    assert event.reason == "breakpoint"
    assert process.stdin.written == ["-exec-next\n"]


def test_step_raises_after_exceeding_coalesce_cap():
    lines = []
    for _ in range(3):
        lines += [
            "^running\n",
            '*stopped,reason="end-stepping-range",frame={file="fixture.c",'
            'fullname="/work/fixture.c",line="1"}\n',
            "(gdb)\n",
        ]
    process = _FakeProcess(lines)
    session = GdbSession(process)

    with mock.patch("mockymock.debug.gdb_session._MAX_COALESCE_STEPS", 3):
        with pytest.raises(RuntimeError, match="did not return to fixture.cbl"):
            session.step("fixture.cbl")


def test_resolve_address_inserts_and_deletes_a_temporary_breakpoint():
    process = _FakeProcess(
        [
            '^done,bkpt={number="2",type="breakpoint",disp="keep",enabled="y",'
            'addr="0x000055ab3844b69b",func="SPIKE_",file="fixture.c",'
            'fullname="/work/fixture.c",line="212",thread-groups=["i1"],'
            'times="0",original-location="*0x55ab3844b69b"}\n',
            "(gdb)\n",
            "^done\n",
            "(gdb)\n",
        ]
    )
    session = GdbSession(process)

    location = session.resolve_address(0x55AB3844B69B)

    assert location["file"] == "fixture.c"
    assert location["line"] == "212"
    assert process.stdin.written == [
        "-break-insert *0x55ab3844b69b\n",
        "-break-delete 2\n",
    ]


def test_send_raises_when_process_closes_stdout():
    process = _FakeProcess([])  # immediate EOF
    session = GdbSession(process)
    with pytest.raises(GdbSessionClosedError):
        session.send("-exec-run")


def test_close_sends_gdb_exit_and_waits():
    process = _FakeProcess(["^exit\n"])
    session = GdbSession(process)
    session.close()
    assert process.stdin.written == ["-gdb-exit\n"]


def test_close_terminates_process_if_gdb_exit_hangs():
    process = _FakeProcess([])  # send() will raise GdbSessionClosedError
    session = GdbSession(process)
    session.close()
    assert process.returncode == -15
