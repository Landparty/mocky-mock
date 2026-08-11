"""Tests for mockymock.cli.skills_cmd -- the copy-out logic behind
`mockymock skills install`, kept separate from cli/main.py so that
module's _cmd_skills_install can defer-import it like every other
subcommand's dependencies."""

from pathlib import Path

import pytest

from mockymock.cli.skills_cmd import (
    SkillTargetExistsError,
    install_skill,
    resolve_target,
)


def test_resolve_target_project_uses_cwd(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    assert resolve_target(project=True) == tmp_path / ".claude" / "skills" / "mockymock"


def test_resolve_target_global_uses_home(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert resolve_target(project=False) == tmp_path / ".claude" / "skills" / "mockymock"


def test_install_skill_copies_expected_files(tmp_path):
    target = tmp_path / "dest"
    install_skill(target)
    assert (target / "SKILL.md").is_file()
    assert (target / "reference" / "cut-dsl.md").is_file()
    assert (target / "reference" / "cli-flags.md").is_file()


def test_install_skill_refuses_existing_target_without_force(tmp_path):
    target = tmp_path / "dest"
    target.mkdir()
    (target / "stray.txt").write_text("local edit", encoding="utf-8")
    with pytest.raises(SkillTargetExistsError) as exc_info:
        install_skill(target)
    assert exc_info.value.target == target
    # Fail-closed: the existing directory must be left untouched.
    assert (target / "stray.txt").is_file()
    assert not (target / "SKILL.md").exists()


def test_install_skill_overwrites_with_force(tmp_path):
    target = tmp_path / "dest"
    target.mkdir()
    (target / "stray.txt").write_text("local edit", encoding="utf-8")
    install_skill(target, force=True)
    assert (target / "SKILL.md").is_file()
    assert not (target / "stray.txt").exists()


def test_install_skill_creates_missing_parent_directories(tmp_path):
    # shutil.copytree's destination goes through os.makedirs internally,
    # so a target several directories deeper than anything that exists
    # yet (e.g. a fresh ~/.claude/skills/mockymock with no ~/.claude/
    # at all) must still succeed without a separate mkdir step here.
    target = tmp_path / "does" / "not" / "exist" / "yet"
    install_skill(target)
    assert (target / "SKILL.md").is_file()


def test_install_skill_force_overwrites_a_plain_file_target(tmp_path):
    # shutil.rmtree refuses to operate on a non-directory; a target that
    # already exists as a plain file (not a previous install) must still
    # be replaceable with --force instead of crashing.
    target = tmp_path / "dest"
    target.write_text("not a directory", encoding="utf-8")
    install_skill(target, force=True)
    assert target.is_dir()
    assert (target / "SKILL.md").is_file()
