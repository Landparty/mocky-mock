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


def test_skill_md_points_at_both_reference_files():
    text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    assert "reference/cut-dsl.md" in text
    assert "reference/cli-flags.md" in text


def test_reference_files_exist_and_are_non_empty():
    for name in ("cut-dsl.md", "cli-flags.md"):
        path = SKILL_DIR / "reference" / name
        assert path.is_file()
        assert len(path.read_text(encoding="utf-8")) > 500
