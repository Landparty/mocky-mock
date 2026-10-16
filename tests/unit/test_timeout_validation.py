"""Issue #306: `--timeout` below 1 is refused on run / mutate / report,
and run_binary never passes `timeout 0` (which disables the
container-side kill) or a negative duration to the container."""

from __future__ import annotations

from unittest import mock

import pytest

from mockymock.cli.main import main
from mockymock.runtime.docker_toolchain import run_binary
from tests.unit.test_docker_toolchain import _completed, _work


@pytest.mark.parametrize("command", ["run", "mutate", "report"])
@pytest.mark.parametrize("value", ["0", "-1"])
def test_timeout_below_one_is_refused(command, value, capsys) -> None:
    try:
        code = main([command, "PROG.cbl", "--timeout", value])
    except SystemExit as exc:  # argparse exits; main may also return it
        code = exc.code
    assert code == 2
    assert "--timeout must be at least 1 second" in capsys.readouterr().err


@pytest.mark.parametrize("value", [0, -3])
def test_run_binary_never_disables_the_container_kill(tmp_path, value) -> None:
    work, source = _work(tmp_path)
    binary = source.parent / "PROG"
    binary.write_text("")
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return _completed(argv, stdout="__MOCKYMOCK__ SUMMARY: RUN=1 FAILURES=0\n")

    with (
        mock.patch(
            "mockymock.runtime.docker_toolchain.subprocess.run", side_effect=fake_run
        ),
        mock.patch("mockymock.runtime.docker_toolchain.WORK_ROOT", work),
    ):
        run_binary(binary, timeout_seconds=value)

    argv = calls[0]
    assert argv[argv.index("timeout") + 3] == "1"
