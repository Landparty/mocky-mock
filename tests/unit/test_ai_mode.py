"""mockymock/cli/ai_mode.py: the AI assistant modes the packaged skill
operates under. See docs/2026-09-16-ai-assistant-modes-design.md."""

import pytest

from mockymock.cli import ai_mode
from mockymock.cli.config import ConfigError, load_config


def test_every_mode_has_a_full_contract():
    """A mode with a missing field would print a blank line in `skills
    mode` and leave an assistant guessing that half of the contract."""
    assert set(ai_mode.CONTRACTS) == set(ai_mode.MODES)
    for name in ai_mode.MODES:
        contract = ai_mode.CONTRACTS[name]
        assert contract.name == name
        for field in (
            contract.summary,
            contract.narration,
            contract.decides,
            contract.asks,
        ):
            assert field and not field.isspace()


def test_default_mode_is_guided():
    """The behavior the skill described before modes existed. A project
    with no `ai_mode` key must not silently become more (or less)
    autonomous than it was."""
    assert ai_mode.DEFAULT_MODE == ai_mode.GUIDED
    assert ai_mode.resolve_mode(None).mode == ai_mode.GUIDED
    assert ai_mode.resolve_mode(None).source is None


def test_validate_rejects_an_unknown_mode_naming_the_valid_set():
    with pytest.raises(ai_mode.ModeError) as exc_info:
        ai_mode.validate("yolo")
    message = str(exc_info.value)
    for name in ai_mode.MODES:
        assert name in message


def test_resolve_mode_reports_the_config_file_it_came_from(tmp_path):
    (tmp_path / "mockymock.toml").write_text('ai_mode = "hands-off"\n')
    resolved = ai_mode.resolve_mode(load_config(tmp_path))
    assert resolved.mode == "hands-off"
    assert resolved.source == tmp_path / "mockymock.toml"
    assert str(tmp_path / "mockymock.toml") in resolved.origin


def test_resolve_mode_without_the_key_is_the_default_with_no_source(tmp_path):
    """A config file that sets other keys but not `ai_mode` must resolve
    with `source=None` -- the mode came from the built-in default, not
    from that file, and `skills mode`/`doctor` report provenance."""
    (tmp_path / "mockymock.toml").write_text("seed = 7\n")
    resolved = ai_mode.resolve_mode(load_config(tmp_path))
    assert resolved.mode == ai_mode.DEFAULT_MODE
    assert resolved.source is None
    assert "built-in default" in resolved.origin


def test_write_mode_creates_a_config_file_when_there_is_none(tmp_path):
    written = ai_mode.write_mode("hands-off", load_config(tmp_path), start_dir=tmp_path)
    assert written == tmp_path / "mockymock.toml"
    assert written.read_text(encoding="utf-8") == 'ai_mode = "hands-off"\n'
    assert load_config(tmp_path).ai_mode == "hands-off"


def test_write_mode_appends_to_an_existing_file_preserving_everything_else(tmp_path):
    config_path = tmp_path / "mockymock.toml"
    config_path.write_text('# keep me\nseed = 7\ncopybook_path = ["cpy"]\n')
    ai_mode.write_mode("hands-on", load_config(tmp_path), start_dir=tmp_path)
    text = config_path.read_text(encoding="utf-8")
    assert "# keep me" in text
    assert "seed = 7" in text
    assert 'copybook_path = ["cpy"]' in text
    assert text.endswith('ai_mode = "hands-on"\n')
    config = load_config(tmp_path)
    assert config.ai_mode == "hands-on"
    assert config.seed == 7


def test_write_mode_replaces_an_existing_assignment_rather_than_duplicating_it(
    tmp_path,
):
    config_path = tmp_path / "mockymock.toml"
    config_path.write_text('ai_mode = "hands-on"\nseed = 7\n')
    ai_mode.write_mode("hands-off", load_config(tmp_path), start_dir=tmp_path)
    text = config_path.read_text(encoding="utf-8")
    assert text.count("ai_mode") == 1
    assert 'ai_mode = "hands-off"' in text
    # Replaced in place: the key keeps its position, `seed` keeps its own.
    assert text.splitlines()[1] == "seed = 7"


def test_write_mode_handles_a_file_with_no_trailing_newline(tmp_path):
    config_path = tmp_path / "mockymock.toml"
    config_path.write_text("seed = 7")
    ai_mode.write_mode("hands-off", load_config(tmp_path), start_dir=tmp_path)
    assert load_config(tmp_path).seed == 7
    assert load_config(tmp_path).ai_mode == "hands-off"


def test_write_mode_refuses_a_pyproject_sourced_config(tmp_path):
    """Writing a mockymock.toml beside it would not merge -- it would
    shadow [tool.mockymock] wholesale (mockymock.toml wins per directory),
    silently dropping that project's copybook_path/seed/test_root."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("[tool.mockymock]\nseed = 7\n")
    with pytest.raises(ai_mode.ModeError) as exc_info:
        ai_mode.write_mode("hands-off", load_config(tmp_path), start_dir=tmp_path)
    message = str(exc_info.value)
    assert str(pyproject) in message
    assert 'ai_mode = "hands-off"' in message  # the line to paste
    assert not (tmp_path / "mockymock.toml").exists()
    assert pyproject.read_text(encoding="utf-8") == "[tool.mockymock]\nseed = 7\n"


def test_write_mode_validates_before_touching_the_file(tmp_path):
    with pytest.raises(ai_mode.ModeError):
        ai_mode.write_mode("yolo", load_config(tmp_path), start_dir=tmp_path)
    assert not (tmp_path / "mockymock.toml").exists()


def test_format_mode_report_marks_the_active_mode_and_lists_the_floor():
    report = ai_mode.format_mode_report(ai_mode.ResolvedMode("hands-off", None))
    assert "-> hands-off" in report
    assert "-> guided" not in report
    for name in ai_mode.MODES:
        assert name in report
    assert "Always asked, in every mode:" in report
    # The floor is what keeps hands-off safe; it is never mode-specific.
    assert ".cbl program under test" in report


def test_format_mode_json_carries_every_mode_not_just_the_active_one():
    payload = ai_mode.format_mode_json(ai_mode.ResolvedMode("guided", None))
    assert payload["version"] == 1
    assert payload["mode"] == "guided"
    assert payload["source"] is None
    assert payload["config_key"] == "ai_mode"
    assert [m["name"] for m in payload["modes"]] == list(ai_mode.MODES)
    assert payload["always_ask"] == list(ai_mode.ALWAYS_ASK)


def test_config_rejects_an_unknown_ai_mode_value(tmp_path):
    (tmp_path / "mockymock.toml").write_text('ai_mode = "autopilot"\n')
    with pytest.raises(ConfigError, match="ai_mode") as exc_info:
        load_config(tmp_path)
    assert "hands-off" in str(exc_info.value)


def test_config_rejects_a_non_string_ai_mode(tmp_path):
    (tmp_path / "mockymock.toml").write_text("ai_mode = true\n")
    with pytest.raises(ConfigError, match="ai_mode"):
        load_config(tmp_path)


def test_write_mode_never_clobbers_a_config_file_it_did_not_load(tmp_path):
    """The defensive branch: a `mockymock.toml` that exists at the write
    target but wasn't the loaded config (it appeared after the load, or
    the walk started elsewhere) is edited, not overwritten -- the whole
    point of this module is that a mode change costs nothing else."""
    config = load_config(tmp_path)
    assert config.source is None
    (tmp_path / "mockymock.toml").write_text("seed = 7\n", encoding="utf-8")
    written = ai_mode.write_mode("hands-off", config, start_dir=tmp_path)
    assert written == tmp_path / "mockymock.toml"
    reloaded = load_config(tmp_path)
    assert reloaded.seed == 7
    assert reloaded.ai_mode == "hands-off"
