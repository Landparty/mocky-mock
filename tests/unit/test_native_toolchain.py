"""The native GnuCOBOL backend and the switch that selects it
(runtime/toolchain.py, runtime/native_toolchain.py). Nothing here runs a
real cobc: the backend's real compile/run/coverage/debug paths are covered
by tests/integration with MOCKYMOCK_GNUCOBOL_HOME set."""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import pytest

from mockymock.runtime import (
    _proc,
    docker_toolchain,
    native_toolchain,
    status,
    toolchain,
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv(toolchain.TOOLCHAIN_ENV, raising=False)
    monkeypatch.delenv(native_toolchain.HOME_ENV, raising=False)
    for name in ("COB_CFLAGS", "COB_LIBS", "COB_LDFLAGS", "COB_CONFIG_DIR", "COB_CC"):
        monkeypatch.delenv(name, raising=False)
    native_toolchain._cobc_info.cache_clear()


def _fake_home(tmp_path: Path, monkeypatch, info: str = "COB_CC : gcc\n") -> Path:
    """A GnuCOBOL tree whose cobc is a script answering --info/--version."""
    home = tmp_path / "gnucobol"
    (home / "bin").mkdir(parents=True)
    (home / "share" / "gnucobol" / "config").mkdir(parents=True)
    (home / "share" / "gnucobol" / "config" / "default.conf").write_text("")
    cobc = home / "bin" / "cobc"
    cobc.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "--info" ]; then printf "%s" "$INFO"; exit 0; fi\n'
        'if [ "$1" = "--version" ]; then echo "cobc (GnuCOBOL) 3.2.0"; exit 0; fi\n'
        "exit 1\n"
    )
    cobc.chmod(cobc.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("INFO", info)
    return home


def test_auto_is_docker_without_a_gnucobol_home():
    assert toolchain.selected() == "docker"
    assert toolchain.active() is docker_toolchain


def test_auto_is_native_once_a_gnucobol_home_is_set(monkeypatch, tmp_path):
    monkeypatch.setenv(native_toolchain.HOME_ENV, str(tmp_path))
    assert toolchain.selected() == "native"
    assert toolchain.active() is native_toolchain


def test_explicit_docker_wins_over_a_gnucobol_home(monkeypatch, tmp_path):
    monkeypatch.setenv(native_toolchain.HOME_ENV, str(tmp_path))
    monkeypatch.setenv(toolchain.TOOLCHAIN_ENV, "docker")
    assert toolchain.active() is docker_toolchain


def test_unknown_choice_is_refused(monkeypatch):
    monkeypatch.setenv(toolchain.TOOLCHAIN_ENV, "podman")
    with pytest.raises(toolchain.ToolchainNotAvailableError, match="podman"):
        toolchain.selected()


def test_both_backends_raise_the_same_class():
    assert native_toolchain.ToolchainNotAvailableError is (
        docker_toolchain.ToolchainNotAvailableError
    )


def test_env_points_every_baked_path_into_the_tree(tmp_path):
    env = native_toolchain._env(tmp_path)
    assert env["COB_CONFIG_DIR"] == str(tmp_path / "share" / "gnucobol" / "config")
    assert env["COB_COPY_DIR"] == str(tmp_path / "share" / "gnucobol" / "copy")
    assert str(tmp_path / "include") in env["COB_CFLAGS"]
    assert str(tmp_path / "lib") in env["COB_LIBS"]
    assert env["PATH"].split(os.pathsep)[0] == str(tmp_path / "bin")
    if sys.platform.startswith("linux"):
        assert env["LD_LIBRARY_PATH"].split(os.pathsep)[0] == str(tmp_path / "lib")


def test_env_keeps_a_value_the_user_set(monkeypatch, tmp_path):
    monkeypatch.setenv("COB_CFLAGS", "-I/mine")
    assert native_toolchain._env(tmp_path)["COB_CFLAGS"] == "-I/mine"


def test_missing_home_is_a_toolchain_error():
    with pytest.raises(native_toolchain.ToolchainNotAvailableError, match="not set"):
        native_toolchain.ensure_toolchain()


def test_home_without_cobc_is_a_toolchain_error(monkeypatch, tmp_path):
    monkeypatch.setenv(native_toolchain.HOME_ENV, str(tmp_path))
    with pytest.raises(native_toolchain.ToolchainNotAvailableError, match="no "):
        native_toolchain.ensure_toolchain()
    assert native_toolchain.toolchain_failure() is not None


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX shell fake cobc")
def test_missing_c_compiler_says_what_to_install(monkeypatch, tmp_path):
    home = _fake_home(tmp_path, monkeypatch, "COB_CC : no-such-cc-mockymock\n")
    monkeypatch.setenv(native_toolchain.HOME_ENV, str(home))
    with pytest.raises(native_toolchain.ToolchainNotAvailableError) as exc:
        native_toolchain.ensure_toolchain()
    assert "no-such-cc-mockymock" in str(exc.value)
    assert "C compiler" in str(exc.value)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX shell fake cobc")
def test_ready_tree_probes_ready(monkeypatch, tmp_path):
    home = _fake_home(tmp_path, monkeypatch, "COB_CC : sh\n")
    monkeypatch.setenv(native_toolchain.HOME_ENV, str(home))
    native_toolchain.ensure_toolchain()
    assert native_toolchain.cobc_version() == "cobc (GnuCOBOL) 3.2.0"
    assert native_toolchain.toolchain_failure() is None
    assert native_toolchain.container_identity() is None
    report = status.probe()
    assert report.ready
    assert report.container == "native"
    assert [check.id for check in report.checks] == ["home", "cc", "cobc"]


def test_probe_reports_a_missing_tree_without_touching_docker(monkeypatch, tmp_path):
    monkeypatch.setenv(native_toolchain.HOME_ENV, str(tmp_path / "nowhere"))
    monkeypatch.setattr(
        docker_toolchain, "_docker", lambda *a, **k: pytest.fail("docker called")
    )
    report = status.probe()
    assert not report.ready
    assert report.checks[0].state == status.DOWN


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process groups")
def test_run_binary_kills_the_process_group_on_timeout(monkeypatch, tmp_path):
    monkeypatch.setenv(
        native_toolchain.HOME_ENV, str(_fake_home(tmp_path, monkeypatch))
    )
    binary = tmp_path / "HANG"
    marker = tmp_path / "child-alive"
    # The child outlives the parent's own kill unless the whole group goes.
    binary.write_text(f"#!/bin/sh\n(sleep 3; touch {marker}) &\nsleep 30\n")
    binary.chmod(binary.stat().st_mode | stat.S_IEXEC)
    result = native_toolchain.run_binary(binary, timeout_seconds=1)
    assert result.exit_code == 124
    assert "timed out" in result.stderr
    import time

    time.sleep(3.5)
    assert not marker.exists()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signals")
def test_signal_exit_reads_like_a_shell_exit_code(monkeypatch, tmp_path):
    monkeypatch.setenv(
        native_toolchain.HOME_ENV, str(_fake_home(tmp_path, monkeypatch))
    )
    binary = tmp_path / "ABEND"
    binary.write_text("#!/bin/sh\nkill -9 $$\n")
    binary.chmod(binary.stat().st_mode | stat.S_IEXEC)
    assert native_toolchain.run_binary(binary).exit_code == 137


def test_failure_line_reads_native_markers():
    stderr = "noise\nmockymock: could not run cobc: [Errno 2]\n"
    assert native_toolchain.docker_failure_line(stderr) == (
        "mockymock: could not run cobc: [Errno 2]"
    )
    assert native_toolchain.docker_failure_line("RNF.cbl:3: error: x") is None


def test_flat_windows_layout_is_found(tmp_path):
    """Arnold Trembley's MinGW trees keep config/, copy/ and extras/ at the
    root rather than under share/gnucobol/."""
    for name in ("config", "copy", "extras"):
        (tmp_path / name).mkdir()
    env = native_toolchain._env(tmp_path)
    assert env["COB_CONFIG_DIR"] == str(tmp_path / "config")
    assert env["COB_COPY_DIR"] == str(tmp_path / "copy")
    assert env["COB_LIBRARY_PATH"] == str(tmp_path / "extras")


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX shell fake cobc")
def test_missing_dialect_files_are_reported(monkeypatch, tmp_path):
    home = _fake_home(tmp_path, monkeypatch, "COB_CC : sh\n")
    (home / "share" / "gnucobol" / "config" / "default.conf").unlink()
    monkeypatch.setenv(native_toolchain.HOME_ENV, str(home))
    with pytest.raises(
        native_toolchain.ToolchainNotAvailableError, match="default.conf"
    ):
        native_toolchain.ensure_toolchain()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX shell fake gcov")
def test_gcov_is_resolved_on_the_trees_path(monkeypatch, tmp_path):
    """Windows looks a bare program name up on the parent's PATH, not the
    child's `env=`, so gcov/gdb are resolved to a full path first."""
    home = _fake_home(tmp_path, monkeypatch)
    gcov = home / "bin" / "gcov"
    gcov.write_text("#!/bin/sh\nexit 0\n")
    gcov.chmod(gcov.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", "/nonexistent")
    assert native_toolchain._gcov_program(native_toolchain._env(home)) == str(gcov)


# Regression: bug hunt of 2026-11-05 (running suites). A case looping over a
# DISPLAY is read in bounded memory.


def test_capped_stdout_keeps_only_marker_lines_past_the_limit() -> None:
    capped = native_toolchain._CappedStdout(limit=10, marker_limit=1000)
    capped.feed(b"0123456789")
    capped.feed(b"noise\n__MOCKYMOCK__ CASE 001 E")
    capped.feed(b"ND\nmore noise\n__MOCKYMOCK__ SUMMARY: RUN=1 FAILURES=0")
    out = capped.result()
    assert out == (
        b"0123456789__MOCKYMOCK__ CASE 001 END\n__MOCKYMOCK__ SUMMARY: RUN=1 FAILURES=0"
    )
    assert capped.dropped == len(b"noise\nmore noise\n")


def test_capped_stdout_bounds_marker_lines_too() -> None:
    capped = native_toolchain._CappedStdout(limit=0, marker_limit=30)
    capped.feed(b"__MOCKYMOCK__ MOCK: CALL X\n" * 5)
    assert capped.result() == b"__MOCKYMOCK__ MOCK: CALL X\n"
    assert capped.dropped == 4 * len(b"__MOCKYMOCK__ MOCK: CALL X\n")


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process groups")
def test_run_capped_keeps_memory_bounded_and_the_markers(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(_proc, "STDOUT_CAPTURE_BYTES", 1000)
    script = (
        "import sys\n"
        "sys.stdout.write('x' * 100 + '\\n')\n"
        "sys.stdout.write(('noise' * 20 + '\\n') * 20000)\n"
        "sys.stdout.write('__MOCKYMOCK__ SUMMARY: RUN=1 FAILURES=0\\n')\n"
    )
    code, stdout, _, dropped = native_toolchain._run_capped(
        [sys.executable, "-c", script], cwd=tmp_path, env={}, timeout=30
    )
    assert code == 0
    assert len(stdout) < 1200
    assert stdout.endswith(b"__MOCKYMOCK__ SUMMARY: RUN=1 FAILURES=0\n")
    assert dropped > 1_000_000
    assert "more bytes of output" in native_toolchain._not_kept_note(dropped)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process groups")
def test_run_capped_times_out_with_what_was_printed(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(_proc, "STDOUT_CAPTURE_BYTES", 100)
    script = (
        "import sys\n"
        "sys.stdout.write('__MOCKYMOCK__ CASE 001 START: loop\\n')\n"
        "while True: sys.stdout.write('spam\\n')\n"
    )
    with pytest.raises(Exception) as caught:
        native_toolchain._run_capped(
            [sys.executable, "-c", script], cwd=tmp_path, env={}, timeout=1
        )
    exc = caught.value
    assert exc.__class__.__name__ == "TimeoutExpired"
    assert exc.stdout.startswith(b"__MOCKYMOCK__ CASE 001 START: loop\n")
    assert len(exc.stdout) <= 100 + 4096
    assert exc.not_kept > 0
