"""The contributor-facing Claude Code skill (.claude/skills/mockymock-dev/)
is auto-discovered by Claude Code from its frontmatter -- a malformed or
missing frontmatter field silently breaks discovery with no import error
to catch it, so pin the shape here."""

from pathlib import Path

SKILL_PATH = (
    Path(__file__).resolve().parents[2]
    / ".claude"
    / "skills"
    / "mockymock-dev"
    / "SKILL.md"
)


def test_contributor_skill_file_exists():
    assert SKILL_PATH.is_file()


def test_contributor_skill_has_required_frontmatter():
    text = SKILL_PATH.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    end = text.index("\n---\n", 4)
    frontmatter = text[4:end]
    assert "name: mockymock-dev" in frontmatter
    assert "description:" in frontmatter


def test_contributor_skill_points_at_the_okf_index():
    text = SKILL_PATH.read_text(encoding="utf-8")
    assert ".okf/index.md" in text
