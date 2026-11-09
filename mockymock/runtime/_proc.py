"""Child processes for the toolchains: run one with its output capped,
and make sure none outlives mockymock.

Both toolchains use these (the native one runs cobc and the test binary
directly; the Docker one runs `docker exec`), so they live here rather
than in either: `docker_toolchain` and `native_toolchain` each import
this module and not each other's internals."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
from pathlib import Path

#: Seconds `kill_tree` gives `taskkill /T` before killing the process alone.
_TASKKILL_TIMEOUT = 10

#: Bytes of a test binary's stdout kept as printed. Past it only the
#: lines holding a `__MOCKYMOCK__` marker are kept, up to
#: `MARKER_CAPTURE_BYTES` more: a case looping over a DISPLAY until the
#: timeout printed ~160 MB in 5 seconds, which `communicate` held several
#: times over (730 MB of memory; a GB of output by the default 30-second
#: timeout, enough to take the runner down), 2026-11-05.
STDOUT_CAPTURE_BYTES = 64 * 1024 * 1024
MARKER_CAPTURE_BYTES = 16 * 1024 * 1024
#: Bytes of stderr kept (a DISPLAY UPON SYSERR loop); the rest is dropped.
STDERR_CAPTURE_BYTES = 4 * 1024 * 1024
_MARKER = b"__MOCKYMOCK__ "
_CHUNK = 64 * 1024


class _CappedStdout:
    """A test binary's stdout as `parse_stdout` needs it, in bounded
    memory: everything up to `limit` bytes, then only the marker lines."""

    def __init__(self, limit: int, marker_limit: int) -> None:
        self.limit = limit
        self.marker_limit = marker_limit
        self.kept = bytearray()
        self.markers_kept = 0
        self.dropped = 0
        self._partial = b""

    def feed(self, chunk: bytes) -> None:
        if not self._partial and len(self.kept) + len(chunk) <= self.limit:
            self.kept += chunk
            return
        if not self._partial and len(self.kept) < self.limit:
            room = self.limit - len(self.kept)
            self.kept += chunk[:room]
            chunk = chunk[room:]
            # The cut may fall inside a line: the rest of it is a partial
            # line like any other, kept if it holds a marker.
        data = self._partial + chunk
        lines = data.split(b"\n")
        self._partial = lines.pop()
        for line in lines:
            self._overflow_line(line + b"\n")
        if len(self._partial) > _CHUNK:
            # A "line" that never ends: no marker is that long.
            self.dropped += len(self._partial)
            self._partial = self._partial[-len(_MARKER) :]
            self.dropped -= len(self._partial)

    def _overflow_line(self, line: bytes) -> None:
        if _MARKER in line and self.markers_kept + len(line) <= self.marker_limit:
            self.kept += line
            self.markers_kept += len(line)
        else:
            self.dropped += len(line)

    def result(self) -> bytes:
        if self._partial:
            self._overflow_line(self._partial)
            self._partial = b""
        return bytes(self.kept)


def _drain(stream: object, sink: object) -> None:
    """Read `stream` to its end in chunks, handing each to `sink`."""
    read = stream.read  # type: ignore[attr-defined]
    while True:
        chunk = read(_CHUNK)
        if not chunk:
            return
        sink(chunk)  # type: ignore[operator]


def _run_capped(
    cmd: list[str], *, cwd: Path, env: dict[str, str], timeout: float
) -> tuple[int, bytes, bytes, int]:
    """Run a test binary like `_run` (own session, whole tree killed on
    timeout, `subprocess.TimeoutExpired` raised with what it printed) with
    its output read through `_CappedStdout`. Returns (exit code, stdout,
    stderr, stdout bytes not kept)."""
    kwargs: dict = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        kwargs["start_new_session"] = True
    stdout = _CappedStdout(STDOUT_CAPTURE_BYTES, MARKER_CAPTURE_BYTES)
    stderr = bytearray()

    def keep_stderr(chunk: bytes) -> None:
        room = STDERR_CAPTURE_BYTES - len(stderr)
        if room > 0:
            stderr.extend(chunk[:room])

    with subprocess.Popen(
        cmd,
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        **kwargs,
    ) as proc:
        _ACTIVE.add(proc)
        readers = [
            threading.Thread(target=_drain, args=(proc.stdout, stdout.feed)),
            threading.Thread(target=_drain, args=(proc.stderr, keep_stderr)),
        ]
        for reader in readers:
            reader.daemon = True
            reader.start()
        try:
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                kill_tree(proc)
                proc.wait()
                for reader in readers:
                    reader.join(timeout=5)
                expired = subprocess.TimeoutExpired(
                    cmd, timeout, output=stdout.result(), stderr=bytes(stderr)
                )
                expired.not_kept = stdout.dropped  # type: ignore[attr-defined]
                raise expired from None
            for reader in readers:
                reader.join()
        finally:
            _ACTIVE.discard(proc)
        return proc.returncode, stdout.result(), bytes(stderr), stdout.dropped


def _not_kept_note(dropped: int) -> str:
    if not dropped:
        return ""
    return (
        f"mockymock: the binary printed {dropped} more bytes of output than "
        f"the {STDOUT_CAPTURE_BYTES // (1024 * 1024)} MiB kept; past that "
        f"only the test driver's own lines were kept\n"
    )


def _run(
    cmd: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout: float,
    text: bool,
    stdin: int | None = subprocess.DEVNULL,
) -> subprocess.CompletedProcess:
    """`subprocess.run` that kills the child's whole process group on
    timeout, so a test binary that forked (`CALL "SYSTEM"`) leaves no
    orphan behind -- the job `timeout -k` does inside the container."""
    kwargs: dict = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        kwargs["start_new_session"] = True
    with subprocess.Popen(
        cmd,
        cwd=cwd,
        env=env,
        stdin=stdin,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=text,
        **kwargs,
    ) as proc:
        _ACTIVE.add(proc)
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            kill_tree(proc)
            stdout, stderr = proc.communicate()
            raise subprocess.TimeoutExpired(
                cmd, timeout, output=stdout, stderr=stderr
            ) from None
        finally:
            _ACTIVE.discard(proc)
        return subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)


#: The cobc / test binary children running now. Each runs in its own
#: session (so a timeout can kill its whole tree), which also means a
#: SIGTERM or SIGKILL sent to mockymock never reaches them: when the
#: oracle runner timed a suite out, HUGE01's cobc and gcc kept running for
#: 20 minutes with 9 GB of memory (stress test 2026-11-02).
_ACTIVE: set[subprocess.Popen] = set()


def kill_active_children() -> None:
    """Kill the process tree of every cobc / test binary running now."""
    for proc in list(_ACTIVE):
        if proc.poll() is None:
            kill_tree(proc)


def install_termination_handler() -> None:
    """On SIGTERM (or SIGHUP), kill the running children's trees and exit
    143: the oracle runner terminates a suite that overran its timeout
    this way. Only for the real command line (`mockymock`, `python -m
    mockymock`), never a library caller's process."""
    if sys.platform == "win32":
        return

    def terminate(signum: int, _frame: object) -> None:
        kill_active_children()
        raise SystemExit(128 + signum)

    for signum in (signal.SIGTERM, signal.SIGHUP):
        try:
            signal.signal(signum, terminate)
        except ValueError:  # not the main thread
            return


def kill_tree(proc: subprocess.Popen) -> None:
    """Kill `proc` and every process under it: `taskkill /T` on Windows
    (where a plain kill leaves grandchildren running), its process group
    elsewhere (the caller started it with `start_new_session`)."""
    if sys.platform == "win32":
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True,
                check=False,
                timeout=_TASKKILL_TIMEOUT,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass
        # Whatever taskkill managed (missing, denied, stuck), the process
        # itself must die: callers wait on it without a timeout.
        try:
            proc.kill()
        except OSError:
            pass
        return
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        proc.kill()
