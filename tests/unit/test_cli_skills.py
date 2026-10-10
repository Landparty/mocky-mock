# tests/unit/test_cli_skills.py
"""Tests for the `mockymock skills` subcommands' CLI wiring:
`install` (copies the packaged skill out) and `mode` (reads back and
sets how much that skill checks in with the developer)."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from mockymock.cli import ai_mode
from mockymock.cli.main import build_parser, main


def test_skills_install_writes_to_home_by_default(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    exit_code = main(["skills", "install"])
    assert exit_code == 0
    out = capsys.readouterr().out
    for name in ("mockymock", "cobol-analysis", "cobol-test"):
        target = tmp_path / ".claude" / "skills" / name
        assert (target / "SKILL.md").is_file()
        assert f"installed -> {target}" in out


def test_skills_install_skill_flag_installs_only_the_named_one(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert main(["skills", "install", "--skill", "cobol-test"]) == 0
    skills = tmp_path / ".claude" / "skills"
    assert (skills / "cobol-test" / "reference" / "report.md").is_file()
    assert not (skills / "mockymock").exists()


def test_skills_install_rejects_an_unknown_skill(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert main(["skills", "install", "--skill", "nope"]) == 1
    assert "unknown skill" in capsys.readouterr().out
    assert not (tmp_path / ".claude").exists()


def test_skills_install_writes_nothing_when_any_target_exists(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    (tmp_path / ".claude" / "skills" / "cobol-test").mkdir(parents=True)
    assert main(["skills", "install"]) == 1
    assert not (tmp_path / ".claude" / "skills" / "mockymock").exists()


def test_skills_install_target_copilot_writes_to_copilot_home(
    monkeypatch, tmp_path, capsys
):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert main(["skills", "install", "--target", "copilot"]) == 0
    for name in ("mockymock", "cobol-analysis", "cobol-test"):
        assert (tmp_path / ".copilot" / "skills" / name / "SKILL.md").is_file()
    assert not (tmp_path / ".claude").exists()
    assert "GitHub Copilot session" in capsys.readouterr().out


def test_skills_install_target_all_writes_both(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert main(["skills", "install", "--target", "all"]) == 0
    for base in (".claude", ".copilot"):
        assert (tmp_path / base / "skills" / "cobol-test" / "SKILL.md").is_file()


def test_skills_install_target_copilot_project_writes_to_github_dir(
    monkeypatch, tmp_path
):
    monkeypatch.chdir(tmp_path)
    assert main(["skills", "install", "--project", "--target", "copilot"]) == 0
    assert (tmp_path / ".github" / "skills" / "mockymock" / "SKILL.md").is_file()


def test_skills_install_target_choices_match_skills_cmd():
    """--target's choices are a literal (deferred-import rule); pin them."""
    from mockymock.cli.skills_cmd import TARGETS

    parser = build_parser()
    skills = next(
        a
        for a in parser._subparsers._group_actions[0].choices["skills"]._actions
        if a.dest == "skills_command"
    )
    install = skills.choices["install"]
    target = next(a for a in install._actions if a.dest == "target")
    assert target.choices == [*TARGETS, "all"]


def test_skills_install_project_flag_writes_to_cwd(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    exit_code = main(["skills", "install", "--project"])
    assert exit_code == 0
    assert (tmp_path / ".claude" / "skills" / "mockymock" / "SKILL.md").is_file()


def test_skills_install_refuses_existing_target(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    target = tmp_path / ".claude" / "skills" / "mockymock"
    target.mkdir(parents=True)
    exit_code = main(["skills", "install"])
    assert exit_code == 1
    out = capsys.readouterr().out
    assert "already exists" in out
    assert "use --force" in out


def test_skills_install_force_overwrites(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    target = tmp_path / ".claude" / "skills" / "mockymock"
    target.mkdir(parents=True)
    (target / "stray.txt").write_text("local edit", encoding="utf-8")
    exit_code = main(["skills", "install", "--force"])
    assert exit_code == 0
    assert (target / "SKILL.md").is_file()
    assert not (target / "stray.txt").exists()


def test_bare_skills_command_prints_help_and_exits_1(capsys):
    # No leaf subcommand given -- same "print help, exit 1" contract as a
    # bare `mockymock` with no subcommand at all (main.py's own fallback).
    exit_code = main(["skills"])
    assert exit_code == 1


# --- `mockymock skills mode` (docs/2026-09-16-ai-assistant-modes-design.md) ---


def test_skills_mode_reports_the_default_when_no_config_sets_one(
    monkeypatch, tmp_path, capsys
):
    monkeypatch.chdir(tmp_path)
    exit_code = main(["skills", "mode"])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "mockymock skills mode: guided" in out
    assert "built-in default" in out
    # The whole dial, with the floor -- not just the active notch.
    for name in ai_mode.MODES:
        assert name in out
    assert "Always asked, in every mode:" in out


def test_skills_mode_reads_the_mode_out_of_the_config_file(
    monkeypatch, tmp_path, capsys
):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "mockymock.toml").write_text('ai_mode = "hands-off"\n')
    assert main(["skills", "mode"]) == 0
    out = capsys.readouterr().out
    assert "mockymock skills mode: hands-off" in out
    assert str(tmp_path / "mockymock.toml") in out


def test_skills_mode_json_is_machine_readable(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "mockymock.toml").write_text('ai_mode = "hands-on"\n')
    assert main(["skills", "mode", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "hands-on"
    assert payload["source"] == str(tmp_path / "mockymock.toml")
    assert [m["name"] for m in payload["modes"]] == list(ai_mode.MODES)


def test_skills_mode_set_persists_and_reports_the_new_mode(
    monkeypatch, tmp_path, capsys
):
    monkeypatch.chdir(tmp_path)
    assert main(["skills", "mode", "--set", "hands-off"]) == 0
    out = capsys.readouterr().out
    config_path = tmp_path / "mockymock.toml"
    assert f"hands-off -> {config_path}" in out
    assert 'ai_mode = "hands-off"' in config_path.read_text(encoding="utf-8")
    # The report that follows the write reflects the new mode, not the
    # one that was in effect when the command started.
    assert "mockymock skills mode: hands-off" in out


def test_skills_mode_set_rejects_an_unknown_mode_without_writing(
    monkeypatch, tmp_path, capsys
):
    monkeypatch.chdir(tmp_path)
    assert main(["skills", "mode", "--set", "autopilot"]) == 1
    out = capsys.readouterr().out
    assert "unknown AI mode" in out
    for name in ai_mode.MODES:
        assert name in out
    assert not (tmp_path / "mockymock.toml").exists()


def test_skills_mode_reports_a_malformed_config_file_instead_of_crashing(
    monkeypatch, tmp_path, capsys
):
    """`skills` is one of the subcommands main() lets run with a broken
    config (it declares neither copybook_path nor seed), so this leaf
    reports the parse error itself rather than dying in load_config."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "mockymock.toml").write_text("ai_mode = [\n")
    assert main(["skills", "mode"]) == 1
    assert "could not parse" in capsys.readouterr().out


def test_skills_mode_help_lists_the_known_modes(capsys):
    """`--set` deliberately doesn't use `choices=MODES`: that would need
    ai_mode imported at parser-build time, which build_parser() must stay
    free of. This pins the hand-written help text against the real set so
    the duplication can't drift."""
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["skills", "mode", "--help"])
    help_text = capsys.readouterr().out
    for name in ai_mode.MODES:
        assert name in help_text


def test_building_the_parser_does_not_import_the_ai_mode_module():
    """The other half of that trade: the modes are spelled out in help
    text precisely so `mockymock --help` still imports nothing a command
    body owns. Same structural guarantee `test_cli_dashboard.py` pins for
    the Docker toolchain."""
    probe = (
        "import sys; from mockymock.cli.main import build_parser; "
        "build_parser(); "
        "print('mockymock.cli.ai_mode' in sys.modules)"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "False"
