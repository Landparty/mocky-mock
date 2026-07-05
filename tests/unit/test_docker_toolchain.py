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
    assert IMAGE == "mockymock-gnucobol"
    assert CONTAINER == "mockymock-cobc"
    assert WORK_ROOT == Path.home() / ".mockymock" / "work"
    assert issubclass(DockerNotAvailableError, RuntimeError)


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
        return_value=_completed(["docker", "info"], returncode=1,
                                stderr="Cannot connect to the Docker daemon"),
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
            return _completed(argv, stdout="true\n")  # container running
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

    with mock.patch(
        "mockymock.runtime.docker_toolchain.subprocess.run", side_effect=fake_run
    ), mock.patch(
        "mockymock.runtime.docker_toolchain.WORK_ROOT", tmp_path / "work"
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
            return _completed(argv, stdout="false\n")  # exists but stopped
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
            return _completed(argv, stdout="true\n")
        return _completed(argv)

    with mock.patch(
        "mockymock.runtime.docker_toolchain.subprocess.run", side_effect=fake_run
    ):
        ensure_toolchain()

    assert not any(
        c[:2] in (["docker", "build"], ["docker", "run"], ["docker", "start"])
        for c in calls
    )
