"""CLI behavior around the Docker toolchain, with the toolchain mocked --
these tests must pass without Docker installed."""

from unittest import mock

from mockymock.cli.main import main
from mockymock.runtime.docker_toolchain import DockerNotAvailableError


def test_setup_reports_container_and_cobc_version(capsys):
    with mock.patch(
        "mockymock.runtime.docker_toolchain.ensure_toolchain"
    ) as ensure, mock.patch(
        "mockymock.runtime.docker_toolchain.cobc_version",
        return_value="cobc (GnuCOBOL) 3.2.0",
    ):
        exit_code = main(["setup"])
    assert exit_code == 0
    ensure.assert_called_once()
    out = capsys.readouterr().out
    assert "mockymock-cobc" in out
    assert "cobc (GnuCOBOL) 3.2.0" in out


def test_setup_fails_loudly_when_docker_unavailable(capsys):
    with mock.patch(
        "mockymock.runtime.docker_toolchain.ensure_toolchain",
        side_effect=DockerNotAvailableError("Docker is required: start Docker Desktop"),
    ):
        exit_code = main(["setup"])
    assert exit_code == 1
    assert "Docker is required" in capsys.readouterr().out


def test_run_fails_loudly_before_parsing_when_docker_unavailable(tmp_path, capsys):
    """ensure_toolchain runs first: no parse work, no sandbox, just the
    actionable message. The program/cut paths deliberately don't exist."""
    with mock.patch(
        "mockymock.runtime.docker_toolchain.ensure_toolchain",
        side_effect=DockerNotAvailableError("Docker is required: start Docker Desktop"),
    ):
        exit_code = main(
            ["run", str(tmp_path / "NOPE.cbl"), "--cut", str(tmp_path / "NOPE.cut")]
        )
    assert exit_code == 1
    assert "Docker is required" in capsys.readouterr().out


def test_run_parser_accepts_keep_sandbox_and_verbose():
    from mockymock.cli.main import build_parser

    args = build_parser().parse_args(
        ["run", "P.cbl", "--cut", "P.cut", "--keep-sandbox", "--verbose"]
    )
    assert args.keep_sandbox is True
    assert args.verbose is True
