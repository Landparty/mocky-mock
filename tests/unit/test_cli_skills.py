# tests/unit/test_cli_skills.py
"""Tests for `mockymock skills install`'s CLI wiring."""

from pathlib import Path

from mockymock.cli.main import main


def test_skills_install_writes_to_home_by_default(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    exit_code = main(["skills", "install"])
    assert exit_code == 0
    target = tmp_path / ".claude" / "skills" / "mockymock"
    assert (target / "SKILL.md").is_file()
    out = capsys.readouterr().out
    assert f"installed -> {target}" in out


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
