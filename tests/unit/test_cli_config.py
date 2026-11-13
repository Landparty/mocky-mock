"""mockymock/project/config.py: mockymock.toml / pyproject.toml
[tool.mockymock] project configuration. See
docs/2026-09-15-cli-ergonomics-design.md."""

import pytest

from mockymock.project.config import (
    ConfigError,
    MockymockConfig,
    load_config,
    resolve,
    resolve_copybook_paths,
)


def test_load_config_returns_all_defaults_when_nothing_found(tmp_path):
    config = load_config(tmp_path)
    assert config == MockymockConfig()
    assert config.source is None
    assert config.copybook_path == ()
    assert config.seed is None
    # No `ai_mode` key anywhere is distinct from one set to the default
    # mode -- `skills mode`/`doctor` report where the mode came from.
    assert config.ai_mode is None


def test_load_config_finds_mockymock_toml_in_start_dir(tmp_path):
    (tmp_path / "mockymock.toml").write_text('seed = 7\ntest_root = "tests"\n')
    config = load_config(tmp_path)
    assert config.seed == 7
    # Anchored to the config file, not to whatever cwd happens to be.
    assert config.test_root == str(tmp_path / "tests")
    assert config.source == tmp_path / "mockymock.toml"


def test_load_config_test_root_resolved_relative_to_config_file(tmp_path):
    (tmp_path / "mockymock.toml").write_text('test_root = "tests"\n')
    nested = tmp_path / "src" / "deep"
    nested.mkdir(parents=True)
    config = load_config(nested)
    assert config.test_root == str(tmp_path / "tests")


@pytest.mark.parametrize("prefix", ["~", "${HOME}"])
def test_load_config_expands_home_in_test_and_source_roots(
    tmp_path, monkeypatch, prefix
):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))  # expanduser on Windows
    project = tmp_path / "app"
    project.mkdir()
    (project / "mockymock.toml").write_text(
        f'test_root = "{prefix}/tests"\nsource_root = "{prefix}/src"\n'
    )
    config = load_config(project)
    assert config.test_root == str(home / "tests")
    assert config.source_root == str(home / "src")


def test_load_config_absolute_test_root_left_as_is(tmp_path):
    absolute = tmp_path / "elsewhere"
    (tmp_path / "mockymock.toml").write_text(f'test_root = "{absolute.as_posix()}"\n')
    config = load_config(tmp_path)
    assert config.test_root == str(absolute)


def test_load_config_unknown_key_raises_config_error(tmp_path):
    # `timeout` is deliberately not config-overridable, and a typo'd key
    # must not be silently ignored either -- both name the file.
    (tmp_path / "mockymock.toml").write_text("timeout = 120\ncopybook-path = []\n")
    with pytest.raises(ConfigError, match="unknown key") as exc_info:
        load_config(tmp_path)
    assert "timeout" in str(exc_info.value)
    assert "copybook-path" in str(exc_info.value)


def test_load_config_bool_seed_raises_config_error(tmp_path):
    (tmp_path / "mockymock.toml").write_text("seed = true\n")
    with pytest.raises(ConfigError, match="seed"):
        load_config(tmp_path)


def test_load_config_finds_pyproject_tool_mockymock_table(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[tool.mockymock]\nseed = 3\ncopybook_path = "copybooks"\n'
    )
    config = load_config(tmp_path)
    assert config.seed == 3
    assert config.copybook_path == (str(tmp_path / "copybooks"),)


def test_load_config_ignores_pyproject_with_no_tool_mockymock_table(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "whatever"\n')
    config = load_config(tmp_path)
    assert config == MockymockConfig()


def test_load_config_prefers_mockymock_toml_over_pyproject_in_same_dir(tmp_path):
    (tmp_path / "mockymock.toml").write_text("seed = 1\n")
    (tmp_path / "pyproject.toml").write_text("[tool.mockymock]\nseed = 2\n")
    config = load_config(tmp_path)
    assert config.seed == 1


def test_load_config_walks_up_to_a_parent_directory(tmp_path):
    (tmp_path / "mockymock.toml").write_text("seed = 9\n")
    nested = tmp_path / "a" / "b" / "c"
    nested.mkdir(parents=True)
    config = load_config(nested)
    assert config.seed == 9


def test_load_config_copybook_path_list_resolved_relative_to_config_file(tmp_path):
    (tmp_path / "mockymock.toml").write_text('copybook_path = ["cpy1", "cpy2"]\n')
    config = load_config(tmp_path)
    assert config.copybook_path == (
        str(tmp_path / "cpy1"),
        str(tmp_path / "cpy2"),
    )


def test_load_config_copybook_path_absolute_entry_left_unresolved(tmp_path):
    (tmp_path / "mockymock.toml").write_text(
        f'copybook_path = ["{tmp_path.as_posix()}"]\n'
    )
    config = load_config(tmp_path)
    assert config.copybook_path == (str(tmp_path),)


def test_load_config_bad_toml_syntax_raises_config_error_naming_the_file(tmp_path):
    bad = tmp_path / "mockymock.toml"
    bad.write_text("copybook_path = [\n")
    with pytest.raises(ConfigError) as exc_info:
        load_config(tmp_path)
    assert str(bad) in str(exc_info.value)


def test_load_config_wrong_type_for_copybook_path_raises_config_error(tmp_path):
    (tmp_path / "mockymock.toml").write_text("copybook_path = 5\n")
    with pytest.raises(ConfigError, match="copybook_path"):
        load_config(tmp_path)


def test_load_config_wrong_type_for_seed_raises_config_error(tmp_path):
    (tmp_path / "mockymock.toml").write_text('seed = "seven"\n')
    with pytest.raises(ConfigError, match="seed"):
        load_config(tmp_path)


def test_load_config_non_table_tool_mockymock_raises_config_error(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[tool]\nmockymock = 5\n")
    with pytest.raises(ConfigError, match=r"\[tool\.mockymock\]"):
        load_config(tmp_path)


def test_resolve_cli_value_always_wins():
    assert resolve("cli", "config", "default") == "cli"


def test_resolve_falls_back_to_config_then_default():
    assert resolve(None, "config", "default") == "config"
    assert resolve(None, None, "default") == "default"


def test_resolve_copybook_paths_explicit_flag_wins_outright():
    config = MockymockConfig(copybook_path=("from-config",))
    assert resolve_copybook_paths(["from-cli"], config) == ["from-cli"]


def test_resolve_copybook_paths_falls_back_to_config_list():
    config = MockymockConfig(copybook_path=("from-config",))
    assert resolve_copybook_paths(None, config) == ["from-config"]


def test_resolve_copybook_paths_empty_list_when_no_config():
    assert resolve_copybook_paths(None, MockymockConfig()) == []


def test_load_config_reads_ims_call_names_upper_cased(tmp_path):
    (tmp_path / "mockymock.toml").write_text(
        'ims_call_names = ["cbltbnc2", "CBLTBNC3"]\n'
    )
    assert load_config(tmp_path).ims_call_names == ("CBLTBNC2", "CBLTBNC3")


@pytest.mark.parametrize(
    "body", ['ims_call_names = "CBLTBNC3"\n', 'ims_call_names = ["../X"]\n']
)
def test_load_config_validates_ims_call_names(tmp_path, body):
    (tmp_path / "mockymock.toml").write_text(body)
    with pytest.raises(ConfigError, match="ims_call_names"):
        load_config(tmp_path)
