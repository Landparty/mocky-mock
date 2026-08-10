"""Tests for the Docker-backed GnuCOBOL toolchain.

All tests here mock subprocess -- they must pass on a machine without
Docker installed. Real-daemon coverage lives in tests/integration/.
"""

import subprocess
from pathlib import Path
from unittest import mock

import pytest

from mockymock.runtime.docker_toolchain import (
    CONTAINER,
    IMAGE,
    WORK_ROOT,
    DockerNotAvailableError,
    ensure_toolchain,
    to_container_path,
)


def test_constants_have_the_agreed_names():
    assert IMAGE.startswith("mockymock-gnucobol:")
    assert CONTAINER == "mockymock-cobc"
    assert WORK_ROOT == Path.home() / ".mockymock" / "work"
    assert issubclass(DockerNotAvailableError, RuntimeError)


def test_image_tag_changes_with_dockerfile():
    from mockymock.runtime import docker_toolchain as dt

    tag_a = dt._image_tag(dockerfile_text="FROM debian:trixie-slim\n")
    tag_b = dt._image_tag(dockerfile_text="FROM debian:trixie-slim\nRUN true\n")
    assert tag_a != tag_b
    assert dt.IMAGE.startswith("mockymock-gnucobol:")


def test_docker_context_dockerfile_is_bundled_under_the_package():
    """Regression test for a real bug: the Dockerfile must live under
    mockymock/runtime/docker/, not repo-root docker/, so it ships inside the
    wheel and `mockymock setup` doesn't FileNotFoundError under a real `uv
    tool install` (no sibling checkout, no editable install)."""
    from mockymock.runtime import docker_toolchain as dt

    assert (dt._DOCKER_CONTEXT / "Dockerfile").is_file()
    assert dt._DOCKER_CONTEXT == Path(dt.__file__).resolve().parent / "docker"


def test_to_container_path_maps_work_root_child_to_slash_work(tmp_path: Path):
    host = tmp_path / "mockymock-abc" / "PROG.cbl"
    assert to_container_path(host, work_root=tmp_path) == "/work/mockymock-abc/PROG.cbl"


def test_to_container_path_uses_posix_separators_on_windows_paths(tmp_path: Path):
    host = tmp_path / "a" / "b" / "PROG"
    assert to_container_path(host, work_root=tmp_path) == "/work/a/b/PROG"


def test_to_container_path_rejects_paths_outside_work_root(tmp_path: Path):
    outside = tmp_path.parent / "elsewhere" / "PROG.cbl"
    with pytest.raises(ValueError, match="not under the Docker work root"):
        to_container_path(outside, work_root=tmp_path / "work")


def _completed(argv, returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(argv, returncode, stdout, stderr)


def test_ensure_toolchain_raises_when_docker_cli_is_missing():
    with mock.patch(
        "mockymock.runtime.docker_toolchain.subprocess.run",
        side_effect=FileNotFoundError("docker"),
    ):
        with pytest.raises(DockerNotAvailableError, match="Docker is required"):
            ensure_toolchain()


def test_ensure_toolchain_raises_when_daemon_is_unreachable():
    with mock.patch(
        "mockymock.runtime.docker_toolchain.subprocess.run",
        return_value=_completed(
            ["docker", "info"],
            returncode=1,
            stderr="Cannot connect to the Docker daemon",
        ),
    ):
        with pytest.raises(DockerNotAvailableError, match="Docker is required"):
            ensure_toolchain()


def test_ensure_toolchain_builds_image_when_missing():
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        if argv[:3] == ["docker", "image", "inspect"]:
            return _completed(argv, returncode=1)  # image missing
        if argv[:2] == ["docker", "inspect"]:
            # container running, created from the current image
            return _completed(argv, stdout=f"true {IMAGE}\n")
        return _completed(argv)  # info, build succeed

    with mock.patch(
        "mockymock.runtime.docker_toolchain.subprocess.run", side_effect=fake_run
    ):
        ensure_toolchain()

    build_calls = [c for c in calls if c[:2] == ["docker", "build"]]
    assert len(build_calls) == 1
    assert "-t" in build_calls[0] and IMAGE in build_calls[0]


def test_ensure_toolchain_raises_when_image_build_fails():
    def fake_run(argv, **kwargs):
        if argv[:3] == ["docker", "image", "inspect"]:
            return _completed(argv, returncode=1)
        if argv[:2] == ["docker", "build"]:
            return _completed(argv, returncode=1, stderr="build boom")
        return _completed(argv)

    with mock.patch(
        "mockymock.runtime.docker_toolchain.subprocess.run", side_effect=fake_run
    ):
        with pytest.raises(DockerNotAvailableError, match="build boom"):
            ensure_toolchain()


def test_ensure_toolchain_creates_container_when_absent(tmp_path):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        if argv[:2] == ["docker", "inspect"]:
            return _completed(argv, returncode=1)  # no such container
        return _completed(argv, stdout="")

    with (
        mock.patch(
            "mockymock.runtime.docker_toolchain.subprocess.run", side_effect=fake_run
        ),
        mock.patch("mockymock.runtime.docker_toolchain.WORK_ROOT", tmp_path / "work"),
    ):
        ensure_toolchain()

    run_calls = [c for c in calls if c[:2] == ["docker", "run"]]
    assert len(run_calls) == 1
    joined = " ".join(run_calls[0])
    assert "--name mockymock-cobc" in joined
    assert f"{(tmp_path / 'work').as_posix()}:/work" in joined
    assert joined.endswith("sleep infinity")
    assert (tmp_path / "work").is_dir()  # created before mounting


def test_created_container_is_hardened(tmp_path):
    """The container runs untrusted COBOL (audit finding 4.3), so `docker run`
    must isolate it: no network, bounded pids/memory, every capability dropped
    except the DAC_OVERRIDE root needs for the bind mount, and no privilege
    escalation."""
    from mockymock.runtime.docker_toolchain import (
        MEMORY_LIMIT,
        PIDS_LIMIT,
    )

    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        if argv[:2] == ["docker", "inspect"]:
            return _completed(argv, returncode=1)  # no such container
        return _completed(argv, stdout="")

    with (
        mock.patch(
            "mockymock.runtime.docker_toolchain.subprocess.run", side_effect=fake_run
        ),
        mock.patch("mockymock.runtime.docker_toolchain.WORK_ROOT", tmp_path / "work"),
    ):
        ensure_toolchain()

    (run_call,) = [c for c in calls if c[:2] == ["docker", "run"]]

    def flag_value(flag):
        return run_call[run_call.index(flag) + 1]

    assert flag_value("--network") == "none"
    assert flag_value("--pids-limit") == str(PIDS_LIMIT)
    assert flag_value("--memory") == MEMORY_LIMIT
    # swap pinned to the memory limit so the ceiling actually bites
    assert flag_value("--memory-swap") == MEMORY_LIMIT
    assert flag_value("--cap-drop") == "ALL"
    # DAC_OVERRIDE is the one cap kept back: container-root needs it to read
    # and write the host-uid-owned sandbox through the bind mount, or cobc
    # fails "Permission denied". The escape-relevant caps stay dropped.
    assert flag_value("--cap-add") == "DAC_OVERRIDE"
    assert flag_value("--security-opt") == "no-new-privileges"
    # hardening must not disturb the mount or the entrypoint
    assert " ".join(run_call).endswith("sleep infinity")
    assert f"{(tmp_path / 'work').as_posix()}:/work" in run_call


def test_ensure_toolchain_starts_container_when_stopped():
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        if argv[:2] == ["docker", "inspect"]:
            # exists but stopped, created from the current image
            return _completed(argv, stdout=f"false {IMAGE}\n")
        return _completed(argv)

    with mock.patch(
        "mockymock.runtime.docker_toolchain.subprocess.run", side_effect=fake_run
    ):
        ensure_toolchain()

    assert ["docker", "start", CONTAINER] in calls


def test_ensure_toolchain_is_a_noop_when_everything_is_up():
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        if argv[:2] == ["docker", "inspect"]:
            return _completed(argv, stdout=f"true {IMAGE}\n")
        return _completed(argv)

    with mock.patch(
        "mockymock.runtime.docker_toolchain.subprocess.run", side_effect=fake_run
    ):
        ensure_toolchain()

    assert not any(
        c[:2] in (["docker", "build"], ["docker", "run"], ["docker", "start"])
        for c in calls
    )


def test_ensure_toolchain_recreates_container_when_image_tag_is_stale(tmp_path):
    """A running container created from an older Dockerfile's image tag must
    be removed and recreated -- silently reusing it would defeat the
    content-hash tag entirely (every compile would keep using the stale
    toolchain forever)."""
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        if argv[:2] == ["docker", "inspect"]:
            # running, but created from a superseded image tag
            return _completed(argv, stdout="true mockymock-gnucobol:00000000\n")
        return _completed(argv)

    with (
        mock.patch(
            "mockymock.runtime.docker_toolchain.subprocess.run", side_effect=fake_run
        ),
        mock.patch("mockymock.runtime.docker_toolchain.WORK_ROOT", tmp_path / "work"),
    ):
        ensure_toolchain()

    assert ["docker", "rm", "-f", CONTAINER] in calls
    run_calls = [c for c in calls if c[:2] == ["docker", "run"]]
    assert len(run_calls) == 1
    assert IMAGE in run_calls[0]
    # rm must happen before the replacement container is created
    assert calls.index(["docker", "rm", "-f", CONTAINER]) < calls.index(run_calls[0])


def test_ensure_toolchain_raises_when_stale_container_cannot_be_removed():
    def fake_run(argv, **kwargs):
        if argv[:2] == ["docker", "inspect"]:
            return _completed(argv, stdout="true mockymock-gnucobol:00000000\n")
        if argv[:2] == ["docker", "rm"]:
            return _completed(argv, returncode=1, stderr="rm boom")
        return _completed(argv)

    with mock.patch(
        "mockymock.runtime.docker_toolchain.subprocess.run", side_effect=fake_run
    ):
        with pytest.raises(DockerNotAvailableError, match="rm boom"):
            ensure_toolchain()


def test_ensure_toolchain_adopts_container_created_by_concurrent_invocation(tmp_path):
    """Two first-ever invocations race on `docker run --name`: the loser's
    run fails with "name already in use", but the winner's container is
    usable -- re-check and adopt it instead of exiting 1."""
    inspects = []

    def fake_run(argv, **kwargs):
        if argv[:2] == ["docker", "inspect"]:
            inspects.append(argv)
            if len(inspects) == 1:
                return _completed(argv, returncode=1)  # not there yet
            # the concurrent winner created and started it meanwhile
            return _completed(argv, stdout=f"true {IMAGE}\n")
        if argv[:2] == ["docker", "run"]:
            return _completed(
                argv,
                returncode=125,
                stderr='the container name "/mockymock-cobc" is already in use',
            )
        return _completed(argv)

    with (
        mock.patch(
            "mockymock.runtime.docker_toolchain.subprocess.run", side_effect=fake_run
        ),
        mock.patch("mockymock.runtime.docker_toolchain.WORK_ROOT", tmp_path / "work"),
    ):
        ensure_toolchain()  # must not raise

    assert len(inspects) == 2


def test_ensure_toolchain_starts_concurrently_created_but_stopped_container(tmp_path):
    calls = []
    inspects = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        if argv[:2] == ["docker", "inspect"]:
            inspects.append(argv)
            if len(inspects) == 1:
                return _completed(argv, returncode=1)
            return _completed(argv, stdout=f"false {IMAGE}\n")
        if argv[:2] == ["docker", "run"]:
            return _completed(argv, returncode=125, stderr="name already in use")
        return _completed(argv)

    with (
        mock.patch(
            "mockymock.runtime.docker_toolchain.subprocess.run", side_effect=fake_run
        ),
        mock.patch("mockymock.runtime.docker_toolchain.WORK_ROOT", tmp_path / "work"),
    ):
        ensure_toolchain()

    assert ["docker", "start", CONTAINER] in calls


def test_ensure_toolchain_still_fails_on_unrelated_docker_run_error(tmp_path):
    def fake_run(argv, **kwargs):
        if argv[:2] == ["docker", "inspect"]:
            return _completed(argv, returncode=1)
        if argv[:2] == ["docker", "run"]:
            return _completed(argv, returncode=125, stderr="no space left on device")
        return _completed(argv)

    with (
        mock.patch(
            "mockymock.runtime.docker_toolchain.subprocess.run", side_effect=fake_run
        ),
        mock.patch("mockymock.runtime.docker_toolchain.WORK_ROOT", tmp_path / "work"),
    ):
        with pytest.raises(DockerNotAvailableError, match="no space left"):
            ensure_toolchain()


from mockymock.runtime.compiler import CompileResult
from mockymock.runtime.docker_toolchain import compile_source


def _work(tmp_path):
    """A fake work root with a sandbox and source file inside it."""
    work = tmp_path / "work"
    sandbox = work / "mockymock-x"
    sandbox.mkdir(parents=True)
    source = sandbox / "PROG.cbl"
    source.write_text("dummy\n")
    return work, source


def test_compile_source_execs_cobc_with_container_paths(tmp_path):
    work, source = _work(tmp_path)
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        (source.parent / "PROG").write_text("")  # cobc writes via the mount
        return _completed(argv)

    with (
        mock.patch(
            "mockymock.runtime.docker_toolchain.subprocess.run", side_effect=fake_run
        ),
        mock.patch("mockymock.runtime.docker_toolchain.WORK_ROOT", work),
    ):
        result = compile_source(source)

    assert calls == [
        [
            "docker",
            "exec",
            "-w",
            "/work/mockymock-x",
            CONTAINER,
            "cobc",
            "-free",
            "-x",
            "/work/mockymock-x/PROG.cbl",
            "-o",
            "/work/mockymock-x/PROG",
        ]
    ]
    assert result.success
    assert result.binary_path == source.parent / "PROG"


def test_compile_source_failure_carries_cobc_stderr(tmp_path):
    work, source = _work(tmp_path)
    with (
        mock.patch(
            "mockymock.runtime.docker_toolchain.subprocess.run",
            return_value=_completed(
                [], returncode=1, stderr="PROG.cbl:7: syntax error"
            ),
        ),
        mock.patch("mockymock.runtime.docker_toolchain.WORK_ROOT", work),
    ):
        result = compile_source(source)
    assert result == CompileResult(
        success=False, binary_path=None, stdout="", stderr="PROG.cbl:7: syntax error"
    )


def test_compile_source_fails_cleanly_when_binary_never_appears(tmp_path):
    """docker exec exiting 0 without the binary on the host side (e.g. a
    stale mount) must be a failure, not a phantom success."""
    work, source = _work(tmp_path)
    with (
        mock.patch(
            "mockymock.runtime.docker_toolchain.subprocess.run",
            return_value=_completed([], returncode=0),
        ),
        mock.patch("mockymock.runtime.docker_toolchain.WORK_ROOT", work),
    ):
        result = compile_source(source)
    assert not result.success
    assert result.binary_path is None


def test_compile_source_wraps_docker_oserror_cleanly(tmp_path):
    work, source = _work(tmp_path)
    with (
        mock.patch(
            "mockymock.runtime.docker_toolchain.subprocess.run",
            side_effect=OSError("docker went away"),
        ),
        mock.patch("mockymock.runtime.docker_toolchain.WORK_ROOT", work),
    ):
        result = compile_source(source)
    assert not result.success
    assert "docker went away" in result.stderr


def test_compile_source_times_out_cleanly_when_docker_exec_hangs(tmp_path):
    work, source = _work(tmp_path)
    with (
        mock.patch(
            "mockymock.runtime.docker_toolchain.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd=["docker"], timeout=600),
        ),
        mock.patch("mockymock.runtime.docker_toolchain.WORK_ROOT", work),
    ):
        result = compile_source(source)
    assert not result.success
    assert result.binary_path is None
    assert "timed out" in result.stderr


def test_compile_source_with_coverage_passes_flag_to_cobc(tmp_path):
    work, source = _work(tmp_path)
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        (source.parent / "PROG").write_text("")
        return _completed(argv)

    with (
        mock.patch(
            "mockymock.runtime.docker_toolchain.subprocess.run", side_effect=fake_run
        ),
        mock.patch("mockymock.runtime.docker_toolchain.WORK_ROOT", work),
    ):
        result = compile_source(source, coverage=True)

    assert calls == [
        [
            "docker",
            "exec",
            "-w",
            "/work/mockymock-x",
            CONTAINER,
            "cobc",
            "-free",
            "--coverage",
            "-x",
            "/work/mockymock-x/PROG.cbl",
            "-o",
            "/work/mockymock-x/PROG",
        ]
    ]
    assert result.success


def test_compile_source_without_coverage_omits_the_flag(tmp_path):
    """Default behavior (coverage=False, or the parameter omitted entirely)
    must produce the exact same argv as before this feature existed --
    this pins that the existing test_compile_source_execs_cobc_with_container_paths
    behavior is unchanged."""
    work, source = _work(tmp_path)
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        (source.parent / "PROG").write_text("")
        return _completed(argv)

    with (
        mock.patch(
            "mockymock.runtime.docker_toolchain.subprocess.run", side_effect=fake_run
        ),
        mock.patch("mockymock.runtime.docker_toolchain.WORK_ROOT", work),
    ):
        result = compile_source(source)

    assert "--coverage" not in calls[0]
    assert result.success


from mockymock.runtime.docker_toolchain import run_binary
from mockymock.runtime.executor import NOT_FOUND_EXIT_CODE, TIMEOUT_EXIT_CODE


def test_run_binary_execs_via_container_timeout(tmp_path):
    work, source = _work(tmp_path)
    binary = source.parent / "PROG"
    binary.write_text("")
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs.get("timeout")))
        return _completed(argv, stdout="__MOCKYMOCK__ SUMMARY: RUN=1 FAILURES=0\n")

    with (
        mock.patch(
            "mockymock.runtime.docker_toolchain.subprocess.run", side_effect=fake_run
        ),
        mock.patch("mockymock.runtime.docker_toolchain.WORK_ROOT", work),
    ):
        result = run_binary(binary, timeout_seconds=30)

    argv, host_timeout = calls[0]
    assert argv == [
        "docker",
        "exec",
        "-w",
        "/work/mockymock-x",
        CONTAINER,
        "timeout",
        "-k",
        "5",
        "30",
        "/work/mockymock-x/PROG",
    ]
    assert host_timeout > 30  # belt-and-suspenders guard above container timeout
    assert result.exit_code == 0
    assert "SUMMARY" in result.stdout


def test_run_binary_container_timeout_gets_explanatory_stderr(tmp_path):
    work, source = _work(tmp_path)
    binary = source.parent / "PROG"
    with (
        mock.patch(
            "mockymock.runtime.docker_toolchain.subprocess.run",
            return_value=_completed([], returncode=TIMEOUT_EXIT_CODE),
        ),
        mock.patch("mockymock.runtime.docker_toolchain.WORK_ROOT", work),
    ):
        result = run_binary(binary)
    assert result.exit_code == TIMEOUT_EXIT_CODE
    assert "timed out" in result.stderr


def test_run_binary_host_side_hang_maps_to_timeout_exit_code(tmp_path):
    work, source = _work(tmp_path)
    binary = source.parent / "PROG"
    with (
        mock.patch(
            "mockymock.runtime.docker_toolchain.subprocess.run",
            side_effect=subprocess.TimeoutExpired(
                cmd=["docker"], timeout=40, output=None
            ),
        ),
        mock.patch("mockymock.runtime.docker_toolchain.WORK_ROOT", work),
    ):
        result = run_binary(binary)
    assert result.exit_code == TIMEOUT_EXIT_CODE
    assert result.stdout == ""  # None coerced, never propagated


def test_run_binary_docker_oserror_maps_to_not_found(tmp_path):
    work, source = _work(tmp_path)
    binary = source.parent / "PROG"
    with (
        mock.patch(
            "mockymock.runtime.docker_toolchain.subprocess.run",
            side_effect=OSError("docker went away"),
        ),
        mock.patch("mockymock.runtime.docker_toolchain.WORK_ROOT", work),
    ):
        result = run_binary(binary)
    assert result.exit_code == NOT_FOUND_EXIT_CODE
    assert "docker went away" in result.stderr


from mockymock.runtime.docker_toolchain import run_gcov


def _work_with_gcda(tmp_path, write_gcda: bool = True):
    work = tmp_path / "work"
    sandbox = work / "mockymock-x"
    sandbox.mkdir(parents=True)
    source = sandbox / "PROG.cbl"
    source.write_text("dummy\n")
    if write_gcda:
        (sandbox / "PROG.gcda").write_text("")
    return work, source


def test_run_gcov_execs_gcov_with_container_dir_and_gcda_name(tmp_path):
    work, source = _work_with_gcda(tmp_path)
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        (source.parent / "PROG.cbl.gcov").write_text(
            "        -:    0:Source:PROG.cbl\n" "       1*:    1:DISPLAY 'X'.\n"
        )
        return _completed(argv)

    with (
        mock.patch(
            "mockymock.runtime.docker_toolchain.subprocess.run", side_effect=fake_run
        ),
        mock.patch("mockymock.runtime.docker_toolchain.WORK_ROOT", work),
    ):
        result = run_gcov(source)

    assert calls == [
        [
            "docker",
            "exec",
            "-w",
            "/work/mockymock-x",
            CONTAINER,
            "gcov",
            "PROG.gcda",
        ]
    ]
    assert result.success
    assert "DISPLAY 'X'." in result.gcov_text


def test_run_gcov_reports_missing_coverage_data_cleanly(tmp_path):
    """No .gcda means the binary never exited normally (e.g. a timeout's
    SIGKILL preempted the gcov atexit dump handler) -- this must be a
    clean, explanatory failure, not a gcov error about a missing file, and
    must never call docker exec at all."""
    work, source = _work_with_gcda(tmp_path, write_gcda=False)
    with (
        mock.patch("mockymock.runtime.docker_toolchain.subprocess.run") as run_mock,
        mock.patch("mockymock.runtime.docker_toolchain.WORK_ROOT", work),
    ):
        result = run_gcov(source)
    run_mock.assert_not_called()
    assert not result.success
    assert "did not exit normally" in result.stderr


def test_run_gcov_surfaces_gcov_command_failure(tmp_path):
    work, source = _work_with_gcda(tmp_path)
    with (
        mock.patch(
            "mockymock.runtime.docker_toolchain.subprocess.run",
            return_value=_completed([], returncode=1, stderr="gcov: boom"),
        ),
        mock.patch("mockymock.runtime.docker_toolchain.WORK_ROOT", work),
    ):
        result = run_gcov(source)
    assert not result.success
    assert "gcov: boom" in result.stderr


def test_run_gcov_reports_cleanly_when_gcov_produces_no_output_file(tmp_path):
    work, source = _work_with_gcda(tmp_path)
    with (
        mock.patch(
            "mockymock.runtime.docker_toolchain.subprocess.run",
            return_value=_completed([], returncode=0),  # exits 0 but writes nothing
        ),
        mock.patch("mockymock.runtime.docker_toolchain.WORK_ROOT", work),
    ):
        result = run_gcov(source)
    assert not result.success
    assert "PROG.cbl.gcov" in result.stderr


def test_run_gcov_wraps_docker_oserror_cleanly(tmp_path):
    work, source = _work_with_gcda(tmp_path)
    with (
        mock.patch(
            "mockymock.runtime.docker_toolchain.subprocess.run",
            side_effect=OSError("docker went away"),
        ),
        mock.patch("mockymock.runtime.docker_toolchain.WORK_ROOT", work),
    ):
        result = run_gcov(source)
    assert not result.success
    assert "docker went away" in result.stderr


# --- execution trace (docs/2026-07-21-debug-trace-design.md) ---------------


def test_compile_source_traceall_appears_in_argv(tmp_path):
    """-ftraceall generates the trace hooks; without it the runtime env
    switches below produce nothing at all."""
    work, source = _work(tmp_path)
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        (source.parent / "PROG").write_text("")
        return _completed(argv)

    with (
        mock.patch(
            "mockymock.runtime.docker_toolchain.subprocess.run", side_effect=fake_run
        ),
        mock.patch("mockymock.runtime.docker_toolchain.WORK_ROOT", work),
    ):
        compile_source(source, trace=True)

    assert "-ftraceall" in calls[0]


def test_compile_source_omits_traceall_by_default(tmp_path):
    work, source = _work(tmp_path)
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        (source.parent / "PROG").write_text("")
        return _completed(argv)

    with (
        mock.patch(
            "mockymock.runtime.docker_toolchain.subprocess.run", side_effect=fake_run
        ),
        mock.patch("mockymock.runtime.docker_toolchain.WORK_ROOT", work),
    ):
        compile_source(source)

    assert "-ftraceall" not in calls[0]


def test_run_binary_sets_trace_env_pointing_into_the_sandbox(tmp_path):
    """COB_TRACE_FILE must resolve inside the bind mount, or the host can
    never read the trace back after the run."""
    work, source = _work(tmp_path)
    binary = source.parent / "PROG"
    binary.write_text("")
    calls = []

    with (
        mock.patch(
            "mockymock.runtime.docker_toolchain.subprocess.run",
            side_effect=lambda argv, **kw: (calls.append(argv), _completed(argv))[1],
        ),
        mock.patch("mockymock.runtime.docker_toolchain.WORK_ROOT", work),
    ):
        run_binary(binary, trace_path=source.parent / "PROG.trace")

    argv = calls[0]
    assert "COB_SET_TRACE=yes" in argv
    assert "COB_TRACE_FILE=/work/mockymock-x/PROG.trace" in argv
    assert "COB_TRACE_FORMAT=%P|%S|%L" in argv


def test_run_binary_sets_no_trace_env_by_default(tmp_path):
    work, source = _work(tmp_path)
    binary = source.parent / "PROG"
    binary.write_text("")
    calls = []

    with (
        mock.patch(
            "mockymock.runtime.docker_toolchain.subprocess.run",
            side_effect=lambda argv, **kw: (calls.append(argv), _completed(argv))[1],
        ),
        mock.patch("mockymock.runtime.docker_toolchain.WORK_ROOT", work),
    ):
        run_binary(binary)

    assert not any("COB_SET_TRACE" in str(a) for a in calls[0])


def test_compile_source_debug_appends_g_flag(tmp_path):
    """-g is what makes gdb accept breakpoints against the compiled .cbl
    and is what makes cobc emit the <name>.c.l.h header variable_map.py
    depends on -- see docs/2026-07-22-dap-debugger-design.md."""
    work, source = _work(tmp_path)
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        (source.parent / "PROG").write_text("")
        return _completed(argv)

    with (
        mock.patch(
            "mockymock.runtime.docker_toolchain.subprocess.run", side_effect=fake_run
        ),
        mock.patch("mockymock.runtime.docker_toolchain.WORK_ROOT", work),
    ):
        result = compile_source(source, debug=True)

    assert "-g" in calls[0]
    assert result.success


def test_compile_source_omits_g_flag_by_default(tmp_path):
    work, source = _work(tmp_path)
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        (source.parent / "PROG").write_text("")
        return _completed(argv)

    with (
        mock.patch(
            "mockymock.runtime.docker_toolchain.subprocess.run", side_effect=fake_run
        ),
        mock.patch("mockymock.runtime.docker_toolchain.WORK_ROOT", work),
    ):
        result = compile_source(source)

    assert "-g" not in calls[0]
    assert result.success


def test_start_gdb_session_execs_mi_interpreter_against_container_binary(tmp_path):
    from mockymock.runtime.docker_toolchain import start_gdb_session

    work, source = _work(tmp_path)
    binary = source.parent / "PROG"
    binary.write_text("")
    captured = {}

    class FakePopen:
        def __init__(self, argv, **kwargs):
            captured["argv"] = argv
            captured["kwargs"] = kwargs

    with (
        mock.patch("mockymock.runtime.docker_toolchain.subprocess.Popen", FakePopen),
        mock.patch("mockymock.runtime.docker_toolchain.WORK_ROOT", work),
    ):
        start_gdb_session(binary)

    assert captured["argv"] == [
        "docker",
        "exec",
        "-i",
        "-w",
        "/work/mockymock-x",
        CONTAINER,
        "gdb",
        "-q",
        "--interpreter=mi2",
        "/work/mockymock-x/PROG",
    ]
    assert captured["kwargs"]["stdin"] == subprocess.PIPE
    assert captured["kwargs"]["stdout"] == subprocess.PIPE
    assert captured["kwargs"]["text"] is True
    # Audit finding F5: text=True with no encoding=/errors= decodes
    # strictly -- a DISPLAY of an uninitialized/garbage alphanumeric
    # field (exactly what someone chasing a data bug would inspect) can
    # contain a byte that isn't valid there, raising an uncaught
    # UnicodeDecodeError inside GdbSession.readline() and killing the
    # whole session. errors="replace" degrades that one line instead.
    assert captured["kwargs"]["encoding"] == "utf-8"
    assert captured["kwargs"]["errors"] == "replace"
