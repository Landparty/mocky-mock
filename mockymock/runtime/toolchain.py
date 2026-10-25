"""Which GnuCOBOL toolchain a command compiles and runs with.

Two backends share one module-level interface (`ensure_toolchain`,
`compile_source`, `run_binary`, `run_gcov`, `start_gdb_session`,
`cobc_version`, `toolchain_failure`, `container_identity`,
`docker_failure_line`, `WORK_ROOT`, `CONTAINER`,
`ToolchainNotAvailableError`):

* `docker_toolchain` -- the hardened `mockymock-cobc` container, the
  default;
* `native_toolchain` -- a self-contained GnuCOBOL tree on the host, named
  by `MOCKYMOCK_GNUCOBOL_HOME` (the VS Code extension bundles one).

`MOCKYMOCK_TOOLCHAIN` picks one: `docker`, `native`, or `auto` (the
default), which means native when `MOCKYMOCK_GNUCOBOL_HOME` is set and
Docker otherwise. Commands call `active()` at run time and use the module
it returns, so a test that monkeypatches `docker_toolchain.compile_source`
still reaches the patched function.
"""

from __future__ import annotations

import os
from types import ModuleType

from mockymock.runtime.docker_toolchain import DockerNotAvailableError

TOOLCHAIN_ENV = "MOCKYMOCK_TOOLCHAIN"
CHOICES = ("auto", "docker", "native")

#: Both backends raise this one class.
ToolchainNotAvailableError = DockerNotAvailableError


def selected() -> str:
    """`docker` or `native`, resolved from the environment."""
    from mockymock.runtime import native_toolchain

    choice = os.environ.get(TOOLCHAIN_ENV, "auto").strip().lower() or "auto"
    if choice not in CHOICES:
        raise ToolchainNotAvailableError(
            f"{TOOLCHAIN_ENV}={choice!r} is not one of {', '.join(CHOICES)}"
        )
    if choice == "auto":
        return "native" if native_toolchain.gnucobol_home() is not None else "docker"
    return choice


def active() -> ModuleType:
    """The backend module the current environment selects."""
    if selected() == "native":
        from mockymock.runtime import native_toolchain

        return native_toolchain
    from mockymock.runtime import docker_toolchain

    return docker_toolchain
