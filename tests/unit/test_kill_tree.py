"""`native_toolchain.kill_tree` on Windows: `taskkill /T` for the tree,
then always `proc.kill()` for the process itself. Callers (`_run`,
`_run_capped`, `runner.jobs._stop`) wait on the process with no timeout,
so a taskkill that is missing, denied or stuck must not leave it alive."""

from __future__ import annotations

import subprocess

import pytest

from mockymock.runtime import native_toolchain


class _FakeProc:
    pid = 4242

    def __init__(self) -> None:
        self.killed = False

    def kill(self) -> None:
        self.killed = True


@pytest.fixture
def windows(monkeypatch):
    monkeypatch.setattr(native_toolchain.sys, "platform", "win32")


@pytest.mark.parametrize(
    "failure",
    [
        FileNotFoundError("taskkill"),
        subprocess.TimeoutExpired("taskkill", 10),
        None,  # taskkill ran (exit code ignored)
    ],
)
def test_the_process_is_killed_whatever_taskkill_did(monkeypatch, windows, failure):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        if failure is not None:
            raise failure
        return subprocess.CompletedProcess(cmd, 128)

    monkeypatch.setattr(native_toolchain.subprocess, "run", fake_run)
    proc = _FakeProc()
    native_toolchain.kill_tree(proc)  # type: ignore[arg-type]

    assert calls[0][0] == ["taskkill", "/F", "/T", "/PID", "4242"]
    assert calls[0][1]["timeout"] == native_toolchain._TASKKILL_TIMEOUT
    assert proc.killed


def test_an_already_exited_process_is_not_an_error(monkeypatch, windows):
    monkeypatch.setattr(
        native_toolchain.subprocess,
        "run",
        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 128),
    )

    class _Gone(_FakeProc):
        def kill(self) -> None:
            raise OSError("access denied: process has exited")

    native_toolchain.kill_tree(_Gone())  # type: ignore[arg-type]
