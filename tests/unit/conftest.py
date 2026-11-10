"""Unit tests mock the Docker backend. A GnuCOBOL home in the developer's
own environment (the VS Code extension sets one) would switch
`runtime.toolchain.active()` to the native backend under them, so both
selector variables are cleared for every unit test; the tests of the
native backend set them themselves."""

import pytest


@pytest.fixture(autouse=True)
def _docker_backend_by_default(monkeypatch):
    monkeypatch.delenv("MOCKYMOCK_GNUCOBOL_HOME", raising=False)
    monkeypatch.delenv("MOCKYMOCK_TOOLCHAIN", raising=False)


@pytest.fixture(autouse=True)
def _private_copybook_alias_staging(monkeypatch, tmp_path_factory):
    """Copybook aliases stage into the system temp folder by default
    (project/copybook_aliases.py); keep each test's staging out of it."""
    from mockymock.project import copybook_aliases

    monkeypatch.setattr(
        copybook_aliases,
        "STAGING_ROOT",
        tmp_path_factory.mktemp("alias-staging"),
    )
