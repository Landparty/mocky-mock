"""mockymock reading the universal `cobol.yml` project config.

The tool-specific `mockymock.toml` / `[tool.mockymock]` path is covered by
tests/unit/test_cli_config.py; this file covers the universal layer added
alongside it.

Covers:
- `project:` supplies the settings shared with every other tool
  (copybook_path, seed); `mockymock:` supplies and overrides this tool's own
- The two layers MERGE key by key, tool-specific winning -- a mockymock.toml
  setting one key must not silently discard a cobol.yml that set the others
- Paths anchored to the file that declared them, not to the cwd
- `cobol.yml` beats `cobol.yaml`; both are found by walking up
- A malformed universal file is a fail-closed error naming it
- `skills mode --set` refuses to rewrite a cobol.yml, and says what to paste
- On a cobol-parser too old to read the file, the degradation path: an error
  naming the version to install rather than the file being skipped in silence

Reading a `cobol.yml` needs `cobolparser.config`, which lands in cobol-parser
1.10, and this project's dependency floor is deliberately lower (see
pyproject.toml). So the feature tests are gated on the INSTALLED parser
actually having that module -- the same capability-probe pattern
test_verb_coverage_fail_closed.py uses for Report Writer and structured XML
PARSE nodes. `cobol-parser-compat` (CI installs the published package, not a
sibling checkout) therefore runs the degradation test below instead of
skipping this file's subject matter silently.
"""

from __future__ import annotations

import pytest

from mockymock.cli.ai_mode import ModeError, resolve_mode, write_mode
from mockymock.cli.config import (
    ConfigError,
    MockymockConfig,
    find_universal_config,
    load_config,
)

try:
    import cobolparser.config  # noqa: F401

    UNIVERSAL_READABLE = True
except ImportError:  # cobol-parser < 1.10
    UNIVERSAL_READABLE = False

requires_universal_config = pytest.mark.skipif(
    not UNIVERSAL_READABLE,
    reason="installed cobol-parser predates cobolparser.config (< 1.10)",
)


@requires_universal_config
def test_project_section_supplies_shared_settings(tmp_path):
    (tmp_path / "cobol.yml").write_text(
        "project:\n  copybook_path: [copybooks]\n  seed: 7\n"
    )
    config = load_config(tmp_path)
    assert config.copybook_path == (str(tmp_path / "copybooks"),)
    assert config.seed == 7
    assert config.source == tmp_path / "cobol.yml"
    assert config.sources == (tmp_path / "cobol.yml",)


@requires_universal_config
def test_mockymock_section_supplies_this_tools_own_settings(tmp_path):
    (tmp_path / "cobol.yml").write_text(
        "mockymock:\n  test_root: tests\n  ai_mode: hands-off\n"
    )
    config = load_config(tmp_path)
    assert config.test_root == str(tmp_path / "tests")
    assert config.ai_mode == "hands-off"


@requires_universal_config
def test_mockymock_section_overrides_the_project_section(tmp_path):
    # A project can share a seed for parsing and pin a different one for
    # test generation.
    (tmp_path / "cobol.yml").write_text(
        "project:\n  seed: 1\n  copybook_path: [shared]\n" "mockymock:\n  seed: 2\n"
    )
    config = load_config(tmp_path)
    assert config.seed == 2
    # The key it did NOT override survives.
    assert config.copybook_path == (str(tmp_path / "shared"),)


@requires_universal_config
def test_yaml_extension_is_read_too(tmp_path):
    (tmp_path / "cobol.yaml").write_text("project:\n  seed: 3\n")
    assert load_config(tmp_path).seed == 3


@requires_universal_config
def test_yml_beats_yaml_in_the_same_directory(tmp_path):
    (tmp_path / "cobol.yaml").write_text("project:\n  seed: 1\n")
    (tmp_path / "cobol.yml").write_text("project:\n  seed: 2\n")
    assert load_config(tmp_path).seed == 2


@requires_universal_config
def test_found_by_walking_up_and_anchored_to_the_file(tmp_path):
    (tmp_path / "cobol.yml").write_text(
        "project:\n  copybook_path: [copybooks]\nmockymock:\n  test_root: tests\n"
    )
    nested = tmp_path / "src" / "deep"
    nested.mkdir(parents=True)
    config = load_config(nested)
    # Anchored to the config file, not to whatever cwd happens to be.
    assert config.copybook_path == (str(tmp_path / "copybooks"),)
    assert config.test_root == str(tmp_path / "tests")


@requires_universal_config
def test_find_universal_config_returns_none_when_nothing_found(tmp_path):
    assert find_universal_config(tmp_path) is None


@requires_universal_config
def test_no_config_of_either_kind_is_still_all_defaults(tmp_path):
    assert load_config(tmp_path) == MockymockConfig()


# -- layering with the tool-specific file -------------------------------------


@requires_universal_config
def test_tool_specific_file_overrides_the_universal_one_key_by_key(tmp_path):
    (tmp_path / "cobol.yml").write_text(
        "project:\n  copybook_path: [shared]\n  seed: 1\n"
    )
    (tmp_path / "mockymock.toml").write_text("seed = 99\n")
    config = load_config(tmp_path)
    assert config.seed == 99
    # The whole point of merging rather than first-match-wins: a
    # mockymock.toml that sets one key must not discard the rest.
    assert config.copybook_path == (str(tmp_path / "shared"),)


@requires_universal_config
def test_sources_lists_both_files_base_first(tmp_path):
    (tmp_path / "cobol.yml").write_text("project:\n  seed: 1\n")
    (tmp_path / "mockymock.toml").write_text("seed = 2\n")
    config = load_config(tmp_path)
    assert config.sources == (tmp_path / "cobol.yml", tmp_path / "mockymock.toml")
    # `source` stays the file that had the last word -- where `skills mode
    # --set` would write.
    assert config.source == tmp_path / "mockymock.toml"


@requires_universal_config
def test_pyproject_tool_table_also_layers_over_the_universal_file(tmp_path):
    (tmp_path / "cobol.yml").write_text("project:\n  seed: 1\n")
    (tmp_path / "pyproject.toml").write_text('[tool.mockymock]\ntest_root = "t"\n')
    config = load_config(tmp_path)
    assert config.seed == 1
    assert config.test_root == str(tmp_path / "t")


@requires_universal_config
def test_each_file_is_found_by_its_own_walk(tmp_path):
    # A cobol.yml at the repo root and a mockymock.toml in a subproject is a
    # normal monorepo shape; both must apply.
    (tmp_path / "cobol.yml").write_text("project:\n  copybook_path: [shared]\n")
    sub = tmp_path / "subproject"
    sub.mkdir()
    (sub / "mockymock.toml").write_text("seed = 5\n")
    config = load_config(sub)
    assert config.copybook_path == (str(tmp_path / "shared"),)
    assert config.seed == 5


# -- rejections ---------------------------------------------------------------


@requires_universal_config
def test_unknown_key_in_the_mockymock_section_is_rejected(tmp_path):
    (tmp_path / "cobol.yml").write_text("mockymock:\n  timeout: 120\n")
    with pytest.raises(ConfigError, match="unknown key.*timeout"):
        load_config(tmp_path)


@requires_universal_config
def test_bad_ai_mode_in_the_mockymock_section_is_rejected(tmp_path):
    (tmp_path / "cobol.yml").write_text("mockymock:\n  ai_mode: whatever\n")
    with pytest.raises(ConfigError, match="ai_mode"):
        load_config(tmp_path)


@requires_universal_config
def test_malformed_universal_file_is_an_error_naming_it(tmp_path):
    (tmp_path / "cobol.yml").write_text("project:\n\tseed: 1\n")
    with pytest.raises(ConfigError) as exc_info:
        load_config(tmp_path)
    assert "cobol.yml" in str(exc_info.value)


@requires_universal_config
def test_unknown_project_key_rejected_by_the_parsers_own_schema(tmp_path):
    # The `project:` section is cobol-parser's schema, validated there and
    # surfaced here rather than duplicated.
    (tmp_path / "cobol.yml").write_text("project:\n  copybook-path: [x]\n")
    with pytest.raises(ConfigError, match="unknown key"):
        load_config(tmp_path)


# -- ai_mode round trip -------------------------------------------------------


@requires_universal_config
def test_resolve_mode_reports_the_universal_file_as_its_source(tmp_path):
    (tmp_path / "cobol.yml").write_text("mockymock:\n  ai_mode: hands-off\n")
    resolved = resolve_mode(load_config(tmp_path))
    assert resolved.mode == "hands-off"
    assert resolved.source == tmp_path / "cobol.yml"


@requires_universal_config
def test_write_mode_refuses_to_rewrite_a_cobol_yml_and_says_what_to_paste(tmp_path):
    # Silently writing a mockymock.toml beside it would split a project's
    # settings across two files when the point of the universal one is to
    # have a single place.
    (tmp_path / "cobol.yml").write_text("mockymock:\n  ai_mode: guided\n")
    config = load_config(tmp_path)
    with pytest.raises(ModeError) as exc_info:
        write_mode("hands-off", config, start_dir=tmp_path)
    message = str(exc_info.value)
    assert "cobol.yml" in message
    assert "mockymock:" in message
    assert "ai_mode: hands-off" in message
    assert not (tmp_path / "mockymock.toml").exists()


@requires_universal_config
def test_write_mode_still_edits_a_mockymock_toml_layered_over_a_cobol_yml(tmp_path):
    (tmp_path / "cobol.yml").write_text("project:\n  seed: 1\n")
    (tmp_path / "mockymock.toml").write_text('ai_mode = "guided"\n')
    config = load_config(tmp_path)
    written = write_mode("hands-off", config, start_dir=tmp_path)
    assert written == tmp_path / "mockymock.toml"
    assert 'ai_mode = "hands-off"' in written.read_text()


# -- the older-cobol-parser degradation path ----------------------------------
#
# The mirror image of every test above: this one runs ONLY when the installed
# cobol-parser cannot read a cobol.yml, which is exactly the situation the
# `cobol-parser-compat` CI job creates. Without it, that job would go quiet on
# this whole feature the moment the tests above are skipped -- and a silently
# skipped file is indistinguishable from a passing one.


@pytest.mark.skipif(
    UNIVERSAL_READABLE,
    reason="installed cobol-parser can read cobol.yml; nothing to degrade",
)
def test_older_cobol_parser_names_the_version_rather_than_skipping_the_file(
    tmp_path,
):
    # Fail-closed: a project that wrote a cobol.yml must never be left running
    # as though it had not, which is what silently skipping the file would do.
    (tmp_path / "cobol.yml").write_text("project:\n  copybook_path: [copybooks]\n")
    with pytest.raises(ConfigError) as exc_info:
        load_config(tmp_path)
    message = str(exc_info.value)
    assert "cobol.yml" in message
    assert "1.10" in message
    # And the way out that does not require upgrading.
    assert "mockymock.toml" in message


@pytest.mark.skipif(
    UNIVERSAL_READABLE,
    reason="installed cobol-parser can read cobol.yml; nothing to degrade",
)
def test_older_cobol_parser_leaves_a_project_without_a_cobol_yml_working(tmp_path):
    # The floor is not raised precisely so that this keeps working: only a
    # project that actually writes a cobol.yml is asked to upgrade.
    (tmp_path / "mockymock.toml").write_text('seed = 7\ntest_root = "tests"\n')
    config = load_config(tmp_path)
    assert config.seed == 7
    assert config.sources == (tmp_path / "mockymock.toml",)
