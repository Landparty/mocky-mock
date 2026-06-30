"""Detect and bootstrap a GnuCOBOL (cobc) installation.

Package name on choco/brew/apt is `gnucobol` on all three platforms
(verified against community.chocolatey.org/packages/gnucobol,
formulae.brew.sh/formula/gnucobol, and Ubuntu/Debian package listings).
"""

from __future__ import annotations

import platform
import shutil
import subprocess
from dataclasses import dataclass


class GnuCobolNotFoundError(RuntimeError):
    """Raised when cobc cannot be found, or installed, on this machine."""


@dataclass
class GnuCobolInfo:
    path: str
    version: str


def find_cobc() -> GnuCobolInfo | None:
    """Return GnuCobolInfo if `cobc` is on PATH, else None."""
    path = shutil.which("cobc")
    if path is None:
        return None
    result = subprocess.run(
        [path, "--version"], capture_output=True, text=True, check=False
    )
    first_line = result.stdout.splitlines()[0] if result.stdout else "unknown"
    return GnuCobolInfo(path=path, version=first_line)


_INSTALL_COMMANDS: dict[str, list[str]] = {
    "Windows": ["choco", "install", "gnucobol", "-y"],
    "Darwin": ["brew", "install", "gnucobol"],
    "Linux": ["sudo", "apt-get", "install", "-y", "gnucobol"],
}

_MANUAL_INSTALL_URL = "https://gnucobol.sourceforge.io/"


def bootstrap(install: bool = True) -> GnuCobolInfo:
    """Find cobc, installing it via the platform package manager if missing.

    Raises GnuCobolNotFoundError if cobc is still unavailable after an
    install attempt, or immediately if install=False and cobc is missing.
    """
    found = find_cobc()
    if found is not None:
        return found

    system = platform.system()
    command = _INSTALL_COMMANDS.get(system)
    if not install or command is None:
        raise GnuCobolNotFoundError(
            f"cobc not found on PATH and no install command for platform "
            f"'{system}'. Install GnuCOBOL manually: {_MANUAL_INSTALL_URL}"
        )

    print(f"mockymock: cobc not found, attempting: {' '.join(command)}")
    subprocess.run(command, check=False)

    found = find_cobc()
    if found is None:
        raise GnuCobolNotFoundError(
            f"cobc still not found on PATH after running "
            f"'{' '.join(command)}'. Install GnuCOBOL manually: "
            f"{_MANUAL_INSTALL_URL}"
        )
    return found
