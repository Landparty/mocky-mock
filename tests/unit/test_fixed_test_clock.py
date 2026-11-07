"""Test binaries run on a fixed clock (`runtime.executor.fixed_clock_env`)
so FUNCTION CURRENT-DATE is reproducible; the user can move it or turn
it off.

Regression: stress test of the integrated testing stack (backend test
packs + oracle over a synthetic corpus of every program type), 2026-11-02."""

from mockymock.runtime.executor import (
    CURRENT_DATE_ENV,
    DEFAULT_CURRENT_DATE,
    fixed_clock_env,
)

# --- fixed clock -----------------------------------------------------------


def test_test_binaries_run_on_a_fixed_clock(monkeypatch):
    """BNDET01 DISPLAYed FUNCTION CURRENT-DATE: every oracle compare of it
    reported a behaviour change although nothing changed."""
    monkeypatch.delenv("COB_CURRENT_DATE", raising=False)
    monkeypatch.delenv(CURRENT_DATE_ENV, raising=False)
    assert fixed_clock_env() == {"COB_CURRENT_DATE": DEFAULT_CURRENT_DATE}


def test_fixed_clock_can_be_moved_or_turned_off(monkeypatch):
    monkeypatch.delenv("COB_CURRENT_DATE", raising=False)
    monkeypatch.setenv(CURRENT_DATE_ENV, "2030/12/31 23:59:59.00")
    assert fixed_clock_env() == {"COB_CURRENT_DATE": "2030/12/31 23:59:59.00"}
    monkeypatch.setenv(CURRENT_DATE_ENV, "real")
    assert fixed_clock_env() == {}


def test_a_clock_the_user_set_is_kept(monkeypatch):
    monkeypatch.setenv("COB_CURRENT_DATE", "2001/01/01 00:00:00.00")
    assert fixed_clock_env() == {}


def test_native_run_passes_the_clock(monkeypatch, tmp_path):
    from mockymock.runtime import native_toolchain

    seen = {}

    def fake_run(cmd, **kwargs):
        seen.update(kwargs.get("env") or {})
        return 0, b"", b"", 0

    monkeypatch.delenv("COB_CURRENT_DATE", raising=False)
    monkeypatch.delenv(CURRENT_DATE_ENV, raising=False)
    monkeypatch.setattr(native_toolchain, "_run_capped", fake_run)
    monkeypatch.setattr(native_toolchain, "_require_home", lambda: tmp_path)
    binary = tmp_path / "PROG"
    binary.write_text("")
    native_toolchain.run_binary(binary, timeout_seconds=5)
    assert seen.get("COB_CURRENT_DATE") == DEFAULT_CURRENT_DATE
