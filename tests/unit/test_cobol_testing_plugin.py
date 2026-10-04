"""The cobol-testing plugin: the three packaged skills, the plugin and
marketplace manifests that expose them, and the CLI reference the
`mockymock` skill hand-maintains (pinned against argparse here so a new
flag cannot ship undocumented to the assistant)."""

import argparse
import json
from pathlib import Path

from mockymock.cli.main import build_parser
from mockymock.cli.skills_cmd import SKILL_NAMES, SKILLS_ROOT

REPO = Path(__file__).resolve().parents[2]


def _frontmatter(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), path
    return text[4 : text.index("\n---\n", 4)]


def test_every_packaged_skill_has_matching_frontmatter():
    on_disk = sorted(p.name for p in SKILLS_ROOT.iterdir() if p.is_dir())
    assert on_disk == sorted(SKILL_NAMES)
    for name in SKILL_NAMES:
        frontmatter = _frontmatter(SKILLS_ROOT / name / "SKILL.md")
        assert f"name: {name}\n" in frontmatter + "\n"
        assert "description:" in frontmatter


COBOL_TEST_REFERENCES = ("intent-assertions.md", "verification-levels.md", "report.md")


def test_cobol_test_points_at_every_reference_file():
    text = (SKILLS_ROOT / "cobol-test" / "SKILL.md").read_text(encoding="utf-8")
    for name in COBOL_TEST_REFERENCES:
        assert f"reference/{name}" in text
        assert (SKILLS_ROOT / "cobol-test" / "reference" / name).stat().st_size > 0


def test_cobol_test_teaches_the_contract():
    text = (SKILLS_ROOT / "cobol-test" / "SKILL.md").read_text(encoding="utf-8")
    for phrase in (
        "*> INTENT:",
        "*> CHARACTERIZATION:",
        "Never edit the program under test",
        "mockymock journal",
        "mockymock report",
        "--execute",
        "--mutate",
    ):
        assert phrase in text


def test_skills_reference_the_real_label_and_level_vocabulary():
    from mockymock.analysis.assertion_labels import RECORDED_LABEL
    from mockymock.analysis.dialect_risk import MESSAGES

    intent = (
        SKILLS_ROOT / "cobol-test" / "reference" / "intent-assertions.md"
    ).read_text(encoding="utf-8")
    assert RECORDED_LABEL in intent
    levels = (
        SKILLS_ROOT / "cobol-test" / "reference" / "verification-levels.md"
    ).read_text(encoding="utf-8")
    for code in MESSAGES:
        assert f"`{code}`" in levels, code


def test_report_reference_lists_every_finding_category():
    text = (SKILLS_ROOT / "cobol-test" / "reference" / "report.md").read_text(
        encoding="utf-8"
    )
    source = (REPO / "mockymock" / "report" / "test_report.py").read_text(
        encoding="utf-8"
    )
    import re

    categories = set(
        re.findall(r'add\(\s*"(?:high|medium|low|info)",\s*"([a-z-]+)"', source)
    )
    categories |= set(re.findall(r'risk\["severity"\],\s*"([a-z-]+)"', source))
    assert categories
    for category in categories:
        assert f"`{category}`" in text, category


def test_plugin_manifest_exposes_the_packaged_skills():
    manifest = json.loads(
        (REPO / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
    )
    assert manifest["name"] == "cobol-testing"
    (skills_path,) = manifest["skills"]
    assert (REPO / skills_path).resolve() == SKILLS_ROOT.resolve()


def test_plugin_version_tracks_the_package_version():
    from mockymock import __version__

    manifest = json.loads(
        (REPO / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
    )
    assert manifest["version"] == __version__
    config = json.loads(
        (REPO / "release-please-config.json").read_text(encoding="utf-8")
    )
    extra = config["packages"]["."]["extra-files"]
    assert {
        "type": "json",
        "path": ".claude-plugin/plugin.json",
        "jsonpath": "$.version",
    } in extra


def test_marketplace_lists_the_plugin_at_the_repo_root():
    marketplace = json.loads(
        (REPO / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8")
    )
    (plugin,) = marketplace["plugins"]
    assert plugin["name"] == "cobol-testing"
    assert plugin["source"] == "./"


def _option_strings(parser: argparse.ArgumentParser, prefix: str):
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for name, sub in action.choices.items():
                yield from _option_strings(sub, f"{prefix} {name}".strip())
        for option in action.option_strings:
            if option.startswith("--") and option != "--help":
                yield prefix, option


def test_every_cli_flag_is_in_the_skill_reference():
    text = (SKILLS_ROOT / "mockymock" / "reference" / "cli-flags.md").read_text(
        encoding="utf-8"
    )
    parser = build_parser()
    subparsers = next(
        a for a in parser._actions if isinstance(a, argparse._SubParsersAction)
    )
    missing = [name for name in subparsers.choices if f"mockymock {name}" not in text]
    missing += [
        f"{command} {option}"
        for command, option in _option_strings(parser, "")
        if option not in text and command
    ]
    assert not missing, (
        "mockymock/cli/skills/mockymock/reference/cli-flags.md does not mention: "
        + ", ".join(missing)
    )
