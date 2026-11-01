"""`mockymock skills plugin`: the cobol-testing plugin written out as a
local marketplace, for installs with no clone and no network."""

import json

from mockymock import __version__
from mockymock.cli.main import main
from mockymock.cli.skills_cmd import (
    LOCAL_MARKETPLACE_NAME,
    SKILL_NAMES,
    export_plugin,
)


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_export_writes_a_marketplace_and_a_plugin_with_every_skill(tmp_path):
    target = tmp_path / "plugin"
    plugin_dir = export_plugin(target, version="9.9.9")

    marketplace = _read(target / ".claude-plugin" / "marketplace.json")
    assert marketplace["name"] == LOCAL_MARKETPLACE_NAME
    (entry,) = marketplace["plugins"]
    assert entry["name"] == "cobol-testing"
    assert (target / entry["source"]).resolve() == plugin_dir.resolve()

    manifest = _read(plugin_dir / ".claude-plugin" / "plugin.json")
    assert manifest["name"] == "cobol-testing"
    assert manifest["version"] == "9.9.9"
    assert "skills" not in manifest  # the default skills/ folder is used
    for name in SKILL_NAMES:
        assert (plugin_dir / "skills" / name / "SKILL.md").is_file()


def test_export_into_an_empty_existing_directory_is_fine(tmp_path):
    target = tmp_path / "plugin"
    target.mkdir()
    export_plugin(target, version="1.0.0")
    assert (target / ".claude-plugin" / "marketplace.json").is_file()


def test_cli_writes_to_the_given_directory_and_prints_the_install_steps(
    tmp_path, capsys
):
    target = tmp_path / "out"
    assert main(["skills", "plugin", str(target)]) == 0
    out = capsys.readouterr().out
    assert f"/plugin marketplace add {target.resolve()}" in out
    assert f"/plugin install cobol-testing@{LOCAL_MARKETPLACE_NAME}" in out
    manifest = _read(target / "cobol-testing" / ".claude-plugin" / "plugin.json")
    assert manifest["version"] == __version__


def test_cli_defaults_to_the_home_directory(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))  # Path.home() on Windows
    assert main(["skills", "plugin"]) == 0
    assert (
        tmp_path
        / ".mockymock"
        / "claude-plugin"
        / ".claude-plugin"
        / "marketplace.json"
    ).is_file()


def test_a_second_export_needs_force(tmp_path, capsys):
    target = tmp_path / "out"
    assert main(["skills", "plugin", str(target)]) == 0
    (target / "cobol-testing" / "stale.txt").write_text("old")
    assert main(["skills", "plugin", str(target)]) == 1
    assert "--force" in capsys.readouterr().out
    assert main(["skills", "plugin", str(target), "--force"]) == 0
    assert not (target / "cobol-testing" / "stale.txt").exists()


def test_force_never_deletes_a_directory_that_is_not_an_export(tmp_path, capsys):
    target = tmp_path / "mine"
    target.mkdir()
    (target / "notes.txt").write_text("keep me")
    assert main(["skills", "plugin", str(target), "--force"]) == 1
    assert "not an earlier mockymock plugin export" in capsys.readouterr().out
    assert (target / "notes.txt").read_text() == "keep me"


def test_a_file_at_the_target_is_refused(tmp_path, capsys):
    target = tmp_path / "file"
    target.write_text("x")
    assert main(["skills", "plugin", str(target), "--force"]) == 1
    assert target.read_text() == "x"


def test_both_marketplaces_carry_the_same_description(tmp_path):
    from pathlib import Path

    from mockymock.cli.skills_cmd import MARKETPLACE_DESCRIPTION

    repo = Path(__file__).resolve().parents[2]
    export_plugin(tmp_path / "p", version="1.0.0")
    for path in (
        repo / ".claude-plugin" / "marketplace.json",
        tmp_path / "p" / ".claude-plugin" / "marketplace.json",
    ):
        assert _read(path)["metadata"]["description"] == MARKETPLACE_DESCRIPTION
