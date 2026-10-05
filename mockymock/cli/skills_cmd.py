"""Copies the packaged end-user Claude Code skills to a target directory.

mockymock ships three skills under mockymock/cli/skills/ as package data:
`mockymock` (a SKILL.md plus reference/ files teaching an AI assistant how
to scaffold and run .cut tests), `cobol-test` (the end-to-end job:
understand, plan, intent assertions, report) and `cobol-analysis` (a copy
of cobol-parser's analysis skill). They ride along under mockymock.cli -- setuptools only applies
package-data globs under an already-discovered package, and this
directory has no __init__.py of its own, so it rides along with
mockymock.cli the same way mockymock/runtime/docker/ and
mockymock/web/static/ ride along with their own parent packages. This
module is the implementation behind `mockymock skills install`; kept
separate from cli/main.py so that module's _cmd_skills_install can
defer-import it like every other subcommand's dependencies.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

SKILLS_ROOT = Path(__file__).resolve().parent / "skills"
SOURCE_DIR = SKILLS_ROOT / "mockymock"
# Install order: the orchestrator's two dependencies first, so a partial
# install (an unexpected copy error) never leaves cobol-test pointing at
# skills that are not there.
SKILL_NAMES = ("mockymock", "cobol-analysis", "cobol-test")


class SkillTargetExistsError(Exception):
    """Raised when the install target exists and --force wasn't given."""

    def __init__(self, target: Path) -> None:
        self.target = target
        super().__init__(f"{target} already exists; use --force to overwrite")


# Which assistant a skill install is for. The skills are plain Agent Skills
# (a directory holding SKILL.md with `name`/`description` frontmatter plus
# reference files -- the open format at github.com/agentskills/agentskills),
# so the same files serve both; only the directory each assistant scans
# differs. GitHub Copilot (cloud agent, CLI, VS Code and JetBrains agent
# mode) reads personal skills from ~/.copilot/skills and project skills
# from .github/skills, .claude/skills or .agents/skills (GitHub Docs,
# "About agent skills", checked 2026-10-04).
CLAUDE = "claude"
COPILOT = "copilot"
TARGETS = (CLAUDE, COPILOT)
TARGET_LABELS = {CLAUDE: "Claude Code", COPILOT: "GitHub Copilot"}
# (user-level directory under ~, project-level directory under cwd)
_TARGET_DIRS = {
    CLAUDE: (".claude", ".claude"),
    COPILOT: (".copilot", ".github"),
}


def skills_dir(project: bool, target: str = CLAUDE) -> Path:
    """The directory `target` scans for skills: under the home directory,
    or under the current directory for --project."""
    user_dir, project_dir = _TARGET_DIRS[target]
    if project:
        return Path.cwd() / project_dir / "skills"
    return Path.home() / user_dir / "skills"


def resolve_target(
    project: bool, name: str = "mockymock", target: str = CLAUDE
) -> Path:
    """Where `mockymock skills install` writes skill `name` to: the user's
    home directory by default (the skill's content isn't project-specific,
    so a global install works across every COBOL repo tested with
    mockymock), the current directory with --project. `target` picks the
    assistant: ~/.claude/skills (./.claude/skills) for Claude Code,
    ~/.copilot/skills (./.github/skills) for GitHub Copilot."""
    return skills_dir(project, target) / name


def install_skill(
    target: Path, *, force: bool = False, name: str = "mockymock"
) -> None:
    """Copy the packaged skill directory `name` to `target`.

    Fail-closed: refuses (raises SkillTargetExistsError, leaving `target`
    untouched) if it already exists and `force` is False, so a user's
    local edits to a previously installed copy are never silently
    clobbered.
    """
    # is_symlink() is checked alongside exists() because exists() follows
    # symlinks: a dangling symlink target (its referent gone) is still an
    # occupied directory entry that copytree would crash on, and still the
    # user's setup to protect (2026-08-12 audit Finding 5).
    occupied = target.exists() or target.is_symlink()
    if occupied and not force:
        raise SkillTargetExistsError(target)
    if occupied:
        # rmtree refuses a non-directory (a plain file, or a symlink even
        # when it points at a directory) -- unlink removes just the path
        # entry in both cases, without following a symlink into deleting
        # whatever it points at.
        if target.is_dir() and not target.is_symlink():
            shutil.rmtree(target)
        else:
            target.unlink()
    shutil.copytree(SKILLS_ROOT / name, target)


# --- Local plugin export (`mockymock skills plugin`) ----------------------
#
# The repository root is itself a plugin marketplace (.claude-plugin/), but
# a pip install has no repository: the wheel only carries the skills. This
# writes a self-contained local marketplace from the packaged copy, so
# `/plugin marketplace add <dir>` works with no clone and no network.

PLUGIN_NAME = "cobol-testing"
LOCAL_MARKETPLACE_NAME = "mocky-mock-local"
# The same fields as the repository's .claude-plugin/plugin.json, minus
# `skills` (the export puts them in the plugin's default skills/ folder)
# and `version` (taken from the installed package).
# tests/unit/test_cobol_testing_plugin.py keeps the two in step.
PLUGIN_MANIFEST: dict[str, Any] = {
    "name": PLUGIN_NAME,
    "description": (
        "Test COBOL programs with AI: understand a program with cobol-parser, "
        "build and run a mockymock suite under GnuCOBOL with assertions "
        "grounded in its business rules, and get an HTML report of every "
        "step and what each test proves."
    ),
    "author": {"name": "Samuel Dion"},
    "homepage": "https://github.com/Landparty/mocky-mock",
    "license": "AGPL-3.0-or-later",
    "keywords": ["cobol", "mainframe", "testing", "gnucobol", "mocking"],
}


MARKETPLACE_DESCRIPTION = (
    "mocky-mock's Claude Code plugins: AI-assisted COBOL testing with "
    "cobol-parser and GnuCOBOL."
)


class PluginTargetError(Exception):
    """The export directory exists and may not be replaced."""


def default_plugin_dir() -> Path:
    return Path.home() / ".mockymock" / "claude-plugin"


def _is_previous_export(target: Path) -> bool:
    manifest = target / ".claude-plugin" / "marketplace.json"
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(data, dict) and data.get("name") == LOCAL_MARKETPLACE_NAME


def export_plugin(target: Path, *, version: str, force: bool = False) -> Path:
    """Write a local marketplace holding the cobol-testing plugin to `target`
    and return the plugin's own directory.

    Layout::

        target/.claude-plugin/marketplace.json
        target/cobol-testing/.claude-plugin/plugin.json
        target/cobol-testing/skills/<each of SKILL_NAMES>/

    Fail-closed: an existing `target` is replaced only with `force`, and
    only when it is an earlier export (its marketplace.json names
    LOCAL_MARKETPLACE_NAME). An empty directory is fine. Anything else is
    refused even with `force`, so a mistyped path never deletes a
    user's directory.
    """
    if target.exists() and not target.is_dir():
        raise PluginTargetError(f"{target} exists and is not a directory")
    occupied = target.is_symlink() or (target.exists() and any(target.iterdir()))
    if occupied:
        if not _is_previous_export(target):
            raise PluginTargetError(
                f"{target} is not empty and is not an earlier mockymock plugin "
                "export; choose another directory"
            )
        if not force:
            raise PluginTargetError(
                f"{target} already holds a plugin export; use --force to replace it"
            )
        shutil.rmtree(target)

    plugin_dir = target / PLUGIN_NAME
    (target / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    (plugin_dir / ".claude-plugin").mkdir(parents=True)
    for name in SKILL_NAMES:
        shutil.copytree(SKILLS_ROOT / name, plugin_dir / "skills" / name)
    manifest = {**PLUGIN_MANIFEST, "version": version}
    (plugin_dir / ".claude-plugin" / "plugin.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    marketplace = {
        "name": LOCAL_MARKETPLACE_NAME,
        "owner": PLUGIN_MANIFEST["author"],
        "metadata": {"description": MARKETPLACE_DESCRIPTION},
        "plugins": [
            {
                "name": PLUGIN_NAME,
                "source": f"./{PLUGIN_NAME}",
                "description": PLUGIN_MANIFEST["description"],
                "version": version,
            }
        ],
    }
    (target / ".claude-plugin" / "marketplace.json").write_text(
        json.dumps(marketplace, indent=2) + "\n", encoding="utf-8"
    )
    return plugin_dir
