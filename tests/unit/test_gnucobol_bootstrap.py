from unittest.mock import MagicMock, patch

import pytest

from mockymock.runtime.gnucobol_bootstrap import (
    GnuCobolInfo,
    GnuCobolNotFoundError,
    bootstrap,
    find_cobc,
)


def test_find_cobc_returns_none_when_not_on_path():
    with patch("shutil.which", return_value=None):
        assert find_cobc() is None


def test_find_cobc_returns_info_when_present():
    with patch("shutil.which", return_value="/usr/bin/cobc"):
        with patch(
            "subprocess.run",
            return_value=MagicMock(stdout="cobc (GnuCOBOL) 3.2.0\n"),
        ):
            info = find_cobc()
    assert info == GnuCobolInfo(
        path="/usr/bin/cobc", version="cobc (GnuCOBOL) 3.2.0"
    )


def test_bootstrap_skips_install_when_already_found():
    with patch("shutil.which", return_value="/usr/bin/cobc"):
        with patch(
            "subprocess.run",
            return_value=MagicMock(stdout="cobc (GnuCOBOL) 3.2.0\n"),
        ) as run:
            info = bootstrap()
    run.assert_called_once()
    assert info.path == "/usr/bin/cobc"


def test_bootstrap_installs_via_apt_on_linux_when_missing():
    with patch("shutil.which", side_effect=[None, "/usr/bin/cobc"]):
        with patch("platform.system", return_value="Linux"):
            with patch("subprocess.run") as run:
                run.return_value = MagicMock(stdout="cobc (GnuCOBOL) 3.2.0\n")
                info = bootstrap()
    install_call = run.call_args_list[0]
    assert install_call.args[0] == ["sudo", "apt-get", "install", "-y", "gnucobol"]
    assert info.path == "/usr/bin/cobc"


def test_bootstrap_raises_when_still_missing_after_install_attempt():
    with patch("shutil.which", return_value=None):
        with patch("platform.system", return_value="Linux"):
            with patch("subprocess.run") as run:
                run.return_value = MagicMock(stdout="", returncode=1)
                with pytest.raises(GnuCobolNotFoundError):
                    bootstrap()
    run.assert_called_once_with(
        ["sudo", "apt-get", "install", "-y", "gnucobol"], check=False
    )


def test_bootstrap_raises_immediately_when_install_false_and_missing():
    with patch("shutil.which", return_value=None):
        with pytest.raises(GnuCobolNotFoundError):
            bootstrap(install=False)
