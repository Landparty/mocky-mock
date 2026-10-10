"""The packaged skills must be valid Agent Skills (the open format at
github.com/agentskills/agentskills), because GitHub Copilot loads them
from ~/.copilot/skills or .github/skills as well as Claude Code from
~/.claude/skills. Copilot documents `name` (lowercase, hyphens) and
`description` as required; the spec adds the limits checked below."""

import re

import pytest

from mockymock.cli.skills_cmd import SKILL_NAMES, SKILLS_ROOT

_NAME = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_ALLOWED_KEYS = {
    "name",
    "description",
    "license",
    "compatibility",
    "metadata",
    "allowed-tools",
}


def _frontmatter(text):
    assert text.startswith("---\n"), "SKILL.md must open with YAML frontmatter"
    block = text[4 : text.index("\n---\n", 4)]
    fields = {}
    for line in block.splitlines():
        key, sep, value = line.partition(":")
        assert sep, f"unexpected frontmatter line: {line!r}"
        fields[key.strip()] = value.strip()
    return fields


@pytest.mark.parametrize("name", SKILL_NAMES)
def test_skill_frontmatter_follows_the_agent_skills_spec(name):
    fields = _frontmatter((SKILLS_ROOT / name / "SKILL.md").read_text("utf-8"))
    assert set(fields) <= _ALLOWED_KEYS
    assert fields["name"] == name  # must match the directory name
    assert len(fields["name"]) <= 64 and _NAME.match(fields["name"])
    assert 0 < len(fields["description"]) <= 1024
