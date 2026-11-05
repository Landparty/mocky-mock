"""The `mockymock-setup` skill writes a project's config for it, so its
settings reference must name every key the CLI accepts. A key added to
config.py, a new AI mode, or a new MOCKYMOCK_* environment variable fails
here until reference/settings.md documents it. (The VS Code extension's
own `mockymock.*` settings live in the mocky-mock-vscode repository; the
skill's maintainer note says to check those by hand.)"""

import re
from pathlib import Path

from mockymock.cli import ai_mode, config
from mockymock.cli.skills_cmd import SKILL_NAMES, SKILLS_ROOT

SKILL = SKILLS_ROOT / "mockymock-setup"
SETTINGS = (SKILL / "reference" / "settings.md").read_text(encoding="utf-8")
PACKAGE = Path(config.__file__).resolve().parents[1]


def test_setup_skill_is_packaged_and_installed_with_the_others():
    assert "mockymock-setup" in SKILL_NAMES
    assert (SKILL / "SKILL.md").is_file()


def test_every_config_key_is_documented():
    for key in sorted(config._KNOWN_KEYS):
        assert f"| `{key}` |" in SETTINGS, key


def test_every_ai_mode_is_documented():
    for mode in ai_mode.MODES:
        assert f"`{mode}`" in SETTINGS, mode


def test_every_environment_variable_the_cli_reads_is_documented():
    names = set()
    for path in PACKAGE.rglob("*.py"):
        names |= set(
            re.findall(r"MOCKYMOCK_[A-Z][A-Z_]*[A-Z]", path.read_text("utf-8"))
        )
    assert names, "expected the CLI to read at least one MOCKYMOCK_* variable"
    for name in sorted(names):
        assert f"`{name}`" in SETTINGS, name


def test_skill_names_the_files_it_writes_and_the_checks_it_runs():
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    for needle in (
        "cobol.yml",
        ".vscode/settings.json",
        "mockymock.toolchain",
        "UNRESOLVED_COPYBOOK",
        "mockymock fixtures",
        "mockymock suites",
        "reference/settings.md",
    ):
        assert needle in text, needle
