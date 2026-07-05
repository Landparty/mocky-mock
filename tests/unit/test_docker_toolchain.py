"""Tests for the Docker-backed GnuCOBOL toolchain.

All tests here mock subprocess -- they must pass on a machine without
Docker installed. Real-daemon coverage lives in tests/integration/.
"""

from pathlib import Path

import pytest

from mockymock.runtime.docker_toolchain import (
    CONTAINER,
    IMAGE,
    WORK_ROOT,
    DockerNotAvailableError,
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
