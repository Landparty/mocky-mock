"""The packaged end-user skill (mockymock/cli/skills/mockymock/) ships as
package data and is copied out by `mockymock skills install`. Pin its
shape here so a future edit can't silently drop a file that
`mockymock.cli.skills_cmd.SOURCE_DIR` (Task 3) and the packaging
declaration in pyproject.toml both assume exists."""

from pathlib import Path

SKILL_DIR = (
    Path(__file__).resolve().parents[2] / "mockymock" / "cli" / "skills" / "mockymock"
)


def test_skill_md_exists_with_required_frontmatter():
    text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---\n")
    end = text.index("\n---\n", 4)
    frontmatter = text[4:end]
    assert "name: mockymock" in frontmatter
    assert "description:" in frontmatter


REFERENCE_FILES = (
    "cut-dsl.md",
    "cli-flags.md",
    "scenario-generation.md",
    "paragraph-first-workflow.md",
    "modes.md",
)


def test_skill_md_points_at_every_reference_file():
    text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    for name in REFERENCE_FILES:
        assert f"reference/{name}" in text


def test_reference_files_exist_and_are_non_empty():
    for name in REFERENCE_FILES:
        path = SKILL_DIR / "reference" / name
        assert path.is_file()
        assert len(path.read_text(encoding="utf-8")) > 500


def test_skill_md_teaches_the_paragraph_first_order():
    """The packaged skill's whole point is that an agent builds a suite
    one paragraph at a time and only then writes whole-program cases,
    narrating each step. Pin both halves: a rewrite that drops the order,
    or drops the instruction to keep the developer informed, changes what
    every installed copy of this skill tells an assistant to do."""
    text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    assert "one paragraph at a time" in text
    assert "--case" in text  # running that one paragraph's case alone
    assert "Keep the developer in the loop" in text


def test_skill_md_teaches_the_three_modes_and_the_floor():
    """The modes are the skill's other axis: the same workflow, with a
    different amount of it coming back to the developer. Pin all three
    names, the command that reads the active one, and the floor -- a
    rewrite that keeps "hands-off" but drops what it still asks about
    would turn a delegated run into an unsupervised one."""
    text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    for mode in ("hands-on", "guided", "hands-off"):
        assert mode in text
    assert "mockymock skills mode" in text
    assert "floor holds in every mode" in text


def test_modes_reference_covers_every_mode_and_the_floor():
    text = (SKILL_DIR / "reference" / "modes.md").read_text(encoding="utf-8")
    for mode in ("hands-on", "guided", "hands-off"):
        assert f"### `{mode}`" in text
    # The four floor items, by the thing each one protects.
    assert ".cbl` program under test" in text
    assert "generate --fill" in text
    assert "passing assertion" in text


def test_skill_modes_match_the_cli_vocabulary():
    """The skill's three modes are the CLI's three modes. A mode added to
    ai_mode.MODES that the packaged skill never explains would be a
    setting with no behavior behind it."""
    from mockymock.project.ai_mode import MODES

    text = (SKILL_DIR / "reference" / "modes.md").read_text(encoding="utf-8")
    for mode in MODES:
        assert f"`{mode}`" in text
