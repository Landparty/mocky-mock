"""docs/2026-09-15-init-command-design.md: mockymock init."""

from pathlib import Path

import mockymock.cli.commands.init as init_mod
import mockymock.cli.doctor as doctor_mod
from mockymock.cli.main import main
from mockymock.runtime import status

_EXAMPLE_DIR = Path(__file__).resolve().parents[2] / "examples" / "ordrproc"
_ORDRPROC_CBL = _EXAMPLE_DIR / "ORDRPROC.cbl"


def _fake_ready_report(ready: bool):
    return doctor_mod.DoctorReport(
        toolchain=status.ToolchainStatus(
            ready=ready,
            checked_at="2026-09-15T00:00:00+00:00",
            image="img",
            container="ctr",
            cobc_version="cobc 3.2.0" if ready else None,
            checks=(),
        ),
        extra_checks=(),
        ready=ready,
    )


def test_init_without_docker_scaffolds_but_does_not_attempt_run(
    tmp_path, capsys, monkeypatch
):
    monkeypatch.setattr(
        doctor_mod, "gather_full_status", lambda: _fake_ready_report(False)
    )
    out_cut = tmp_path / "o.cut"

    run_calls = []
    monkeypatch.setattr(init_mod, "_cmd_run", lambda args: run_calls.append(args) or 0)

    exit_code = main(["init", str(_ORDRPROC_CBL), "-o", str(out_cut)])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert out_cut.is_file()
    assert "*> STUB EXPECT" in out_cut.read_text()  # --with-data, not filled in
    assert "Docker isn't available" in out
    assert "mockymock doctor" in out
    assert run_calls == []  # run was never attempted


def test_init_with_docker_ready_scaffolds_and_records(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(
        doctor_mod, "gather_full_status", lambda: _fake_ready_report(True)
    )
    out_cut = tmp_path / "o.cut"

    run_calls = []

    def fake_run(args):
        run_calls.append(args)
        return 0

    monkeypatch.setattr(init_mod, "_cmd_run", fake_run)

    exit_code = main(["init", str(_ORDRPROC_CBL), "-o", str(out_cut)])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert len(run_calls) == 1
    assert run_calls[0].program == str(_ORDRPROC_CBL)
    assert run_calls[0].cut == str(out_cut)
    assert run_calls[0].record_expectations is True
    assert "Docker isn't available" not in out
    assert f"run 'mockymock run {_ORDRPROC_CBL} --cut {out_cut}'" in out


def test_init_propagates_run_failure_exit_code(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        doctor_mod, "gather_full_status", lambda: _fake_ready_report(True)
    )
    out_cut = tmp_path / "o.cut"
    monkeypatch.setattr(init_mod, "_cmd_run", lambda args: 1)

    exit_code = main(["init", str(_ORDRPROC_CBL), "-o", str(out_cut)])
    assert exit_code == 1
    assert out_cut.is_file()  # the scaffold is kept even though run failed


def test_init_refuses_to_overwrite_existing_output_without_force(
    tmp_path, capsys, monkeypatch
):
    out_cut = tmp_path / "o.cut"
    out_cut.write_text("EXISTING")
    exit_code = main(["init", str(_ORDRPROC_CBL), "-o", str(out_cut)])
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "already exists" in out
    assert "--force" in out
    assert out_cut.read_text() == "EXISTING"


def test_init_force_overwrites_existing_output(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        doctor_mod, "gather_full_status", lambda: _fake_ready_report(False)
    )
    out_cut = tmp_path / "o.cut"
    out_cut.write_text("EXISTING")
    exit_code = main(["init", str(_ORDRPROC_CBL), "-o", str(out_cut), "--force"])
    assert exit_code == 0
    assert out_cut.read_text() != "EXISTING"


def test_init_missing_program_reports_cleanly(tmp_path, capsys):
    exit_code = main(["init", str(tmp_path / "MISSING.cbl")])
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "no such file" in out


def test_init_prints_branch_verification_caveat_for_non_happy_scenarios(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(
        doctor_mod, "gather_full_status", lambda: _fake_ready_report(False)
    )
    monkeypatch.setattr(init_mod, "_cmd_generate", lambda args: 0)
    out_cut = tmp_path / "o.cut"
    out_cut.parent.mkdir(parents=True, exist_ok=True)

    exit_code = main(
        ["init", str(_ORDRPROC_CBL), "-o", str(out_cut), "--scenarios", "branches"]
    )
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "branch-targeted scenarios are not yet verified" in out


def test_init_does_not_print_caveat_for_happy_path(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        doctor_mod, "gather_full_status", lambda: _fake_ready_report(False)
    )
    out_cut = tmp_path / "o.cut"
    exit_code = main(["init", str(_ORDRPROC_CBL), "-o", str(out_cut)])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "branch-targeted scenarios" not in out


def test_init_stops_before_run_when_generate_fails(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(init_mod, "_cmd_generate", lambda args: 1)
    run_calls = []
    monkeypatch.setattr(init_mod, "_cmd_run", lambda args: run_calls.append(args) or 0)
    monkeypatch.setattr(
        doctor_mod, "gather_full_status", lambda: _fake_ready_report(True)
    )

    out_cut = tmp_path / "o.cut"
    exit_code = main(["init", str(_ORDRPROC_CBL), "-o", str(out_cut)])
    assert exit_code == 1
    assert run_calls == []


def test_init_refuses_a_cut_file_passed_as_the_program(tmp_path, capsys):
    cut = tmp_path / "P.cut"
    cut.write_text('TESTSUITE "s"\n')
    exit_code = main(["init", str(cut)])
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "is the .cut file, not the COBOL program" in out
    assert "--force" not in out
    assert cut.read_text() == 'TESTSUITE "s"\n'


def test_init_records_when_only_the_toolchain_image_is_missing(
    tmp_path, capsys, monkeypatch
):
    # mocky-mock-vscode#103: a fresh install with Docker running has no
    # toolchain image yet. `run` builds it on demand, so init must not
    # report "Docker isn't available" and skip recording.
    report = doctor_mod.DoctorReport(
        toolchain=status.ToolchainStatus(
            ready=False,
            checked_at="2026-10-21T00:00:00+00:00",
            image="img",
            container="ctr",
            cobc_version=None,
            checks=(
                status.Check("daemon", "Docker daemon", status.OK, "reachable"),
                status.Check("image", "Toolchain image", status.DOWN, "not built"),
                status.Check("container", "Toolchain container", status.DOWN, "none"),
                status.Check("cobc", "GnuCOBOL compiler", status.UNKNOWN, "-"),
            ),
        ),
        extra_checks=(),
        ready=False,
    )
    monkeypatch.setattr(doctor_mod, "gather_full_status", lambda: report)
    run_calls = []
    monkeypatch.setattr(init_mod, "_cmd_run", lambda args: run_calls.append(args) or 0)
    out_cut = tmp_path / "o.cut"

    assert main(["init", str(_ORDRPROC_CBL), "-o", str(out_cut)]) == 0
    out = capsys.readouterr().out
    assert len(run_calls) == 1
    assert "Docker isn't available" not in out
    assert "building it first" in out


def test_init_without_the_docker_daemon_still_skips_recording(
    tmp_path, capsys, monkeypatch
):
    report = doctor_mod.DoctorReport(
        toolchain=status.ToolchainStatus(
            ready=False,
            checked_at="2026-10-21T00:00:00+00:00",
            image="img",
            container="ctr",
            cobc_version=None,
            checks=(status.Check("daemon", "Docker daemon", status.DOWN, "no"),),
        ),
        extra_checks=(),
        ready=False,
    )
    monkeypatch.setattr(doctor_mod, "gather_full_status", lambda: report)
    run_calls = []
    monkeypatch.setattr(init_mod, "_cmd_run", lambda args: run_calls.append(args) or 0)

    assert main(["init", str(_ORDRPROC_CBL), "-o", str(tmp_path / "o.cut")]) == 0
    assert run_calls == []
    assert "Docker isn't available" in capsys.readouterr().out
