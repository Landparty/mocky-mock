"""docs/2026-09-15-doctor-command-design.md: mockymock doctor. Mocks
runtime.status.probe() so these never touch Docker."""

import json

from mockymock.cli import doctor as doctor_mod
from mockymock.cli.main import main
from mockymock.runtime import status


def _fake_toolchain(ready: bool, checks=None):
    return status.ToolchainStatus(
        ready=ready,
        checked_at="2026-09-15T00:00:00+00:00",
        image="mockymock-gnucobol:abc123",
        container="mockymock-cobc",
        cobc_version="cobc 3.2.0" if ready else None,
        checks=checks
        or (
            status.Check(
                "daemon",
                "Docker daemon",
                status.OK if ready else status.DOWN,
                "reachable" if ready else "unreachable",
            ),
        ),
    )


def test_gather_full_status_all_ok(monkeypatch):
    monkeypatch.setattr(status, "probe", lambda: _fake_toolchain(ready=True))
    report = doctor_mod.gather_full_status()
    assert report.ready is True
    ids = {c.id for c in report.all_checks()}
    assert {"daemon", "cobol_parser", "config_file"} <= ids


def test_gather_full_status_daemon_down_marks_not_ready(monkeypatch):
    monkeypatch.setattr(status, "probe", lambda: _fake_toolchain(ready=False))
    report = doctor_mod.gather_full_status()
    assert report.ready is False


def test_gather_full_status_runs_extra_checks_regardless_of_toolchain_state(
    monkeypatch,
):
    """cobol-parser/config checks don't depend on Docker at all."""
    monkeypatch.setattr(status, "probe", lambda: _fake_toolchain(ready=False))
    report = doctor_mod.gather_full_status()
    cobol_parser_check = next(c for c in report.all_checks() if c.id == "cobol_parser")
    assert cobol_parser_check.state == status.OK


def test_cobol_parser_check_down_when_not_importable(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "cobolparser":
            raise ImportError("no module named cobolparser")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    check = doctor_mod._check_cobol_parser()
    assert check.state == status.DOWN
    assert "not importable" in check.detail


def test_config_file_check_reports_none_found(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    check = doctor_mod._check_config_file()
    assert check.state == status.OK
    assert "none found" in check.detail


def test_config_file_check_reports_the_found_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "mockymock.toml").write_text("seed = 1\n")
    check = doctor_mod._check_config_file()
    assert check.state == status.OK
    assert str(tmp_path / "mockymock.toml") in check.detail


def test_config_file_check_downgrades_parse_error_to_warn(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "mockymock.toml").write_text("seed = [\n")
    check = doctor_mod._check_config_file()
    assert check.state == status.WARN


def test_all_checks_sorts_worst_first(monkeypatch):
    monkeypatch.setattr(status, "probe", lambda: _fake_toolchain(ready=False))
    report = doctor_mod.gather_full_status()
    states = [c.state for c in report.all_checks()]
    ranks = [doctor_mod._SEVERITY_RANK.get(s, 0) for s in states]
    assert ranks == sorted(ranks, reverse=True)


def test_format_doctor_text_reports_ready(monkeypatch):
    monkeypatch.setattr(status, "probe", lambda: _fake_toolchain(ready=True))
    report = doctor_mod.gather_full_status()
    text = doctor_mod.format_doctor_text(report)
    assert "mockymock doctor: ready." in text


def test_format_doctor_text_reports_not_ready(monkeypatch):
    monkeypatch.setattr(status, "probe", lambda: _fake_toolchain(ready=False))
    report = doctor_mod.gather_full_status()
    text = doctor_mod.format_doctor_text(report)
    assert "not ready" in text


def test_format_doctor_json_round_trips(monkeypatch):
    monkeypatch.setattr(status, "probe", lambda: _fake_toolchain(ready=True))
    report = doctor_mod.gather_full_status()
    payload = doctor_mod.format_doctor_json(report)
    round_tripped = json.loads(json.dumps(payload))
    assert round_tripped["ready"] is True
    assert any(c["id"] == "cobol_parser" for c in round_tripped["checks"])


def test_cli_doctor_exit_code_matches_readiness(monkeypatch, capsys):
    monkeypatch.setattr(status, "probe", lambda: _fake_toolchain(ready=True))
    exit_code = main(["doctor"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "ready." in out


def test_cli_doctor_json_flag(monkeypatch, capsys):
    monkeypatch.setattr(status, "probe", lambda: _fake_toolchain(ready=False))
    exit_code = main(["doctor", "--json"])
    out = capsys.readouterr().out
    assert exit_code == 1
    payload = json.loads(out)
    assert payload["ready"] is False


def test_doctor_works_when_docker_binary_is_entirely_absent(monkeypatch):
    """doctor must degrade to a clean DOWN check, never a raised
    exception or a hang, when the docker CLI itself can't even be
    found (not just an unreachable daemon) -- exactly the environment
    this repo's own CI/sandbox runs in."""
    import subprocess

    def fake_run(*args, **kwargs):
        raise FileNotFoundError("docker: command not found")

    monkeypatch.setattr(subprocess, "run", fake_run)
    report = doctor_mod.gather_full_status()
    assert report.ready is False
    daemon_check = next(c for c in report.all_checks() if c.id == "daemon")
    assert daemon_check.state == status.DOWN


def test_gather_full_status_warn_only_is_still_ready(monkeypatch):
    """A stopped container is a WARN `mockymock setup` / the next `run`
    sorts out on its own -- not a failure (design doc: WARN -> exit 0)."""
    checks = (
        status.Check("daemon", "Docker daemon", status.OK, "reachable"),
        status.Check("container", "Toolchain container", status.WARN, "stopped"),
    )
    monkeypatch.setattr(
        status, "probe", lambda: _fake_toolchain(ready=False, checks=checks)
    )
    report = doctor_mod.gather_full_status()
    assert report.ready is True
    text = doctor_mod.format_doctor_text(report)
    assert "ready (with warnings" in text
    assert "not ready" not in text


def test_cli_doctor_reports_a_malformed_config_file_as_warn(
    tmp_path, monkeypatch, capsys
):
    """`doctor` must never die on the environment it exists to explain:
    a broken config file is a WARN line in the report, not an exit
    before the report."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "mockymock.toml").write_text("seed = [\n")
    monkeypatch.setattr(status, "probe", lambda: _fake_toolchain(ready=True))
    exit_code = main(["doctor", "--json"])
    out = capsys.readouterr().out
    payload = json.loads(out)
    config_check = next(c for c in payload["checks"] if c["id"] == "config_file")
    assert config_check["state"] == status.WARN
    assert exit_code == 0
