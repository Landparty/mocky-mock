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
