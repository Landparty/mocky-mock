"""Copies the packaged end-user Claude Code skill to a target directory.

mockymock ships mockymock/cli/skills/mockymock/ (a SKILL.md plus
reference/ files teaching an AI assistant how to scaffold and run .cut
tests) as package data under mockymock.cli -- setuptools only applies
package-data globs under an already-discovered package, and this
directory has no __init__.py of its own, so it rides along with
mockymock.cli the same way mockymock/runtime/docker/ and
mockymock/web/static/ ride along with their own parent packages. This
module is the implementation behind `mockymock skills install`; kept
separate from cli/main.py so that module's _cmd_skills_install can
defer-import it like every other subcommand's dependencies.
"""

from __future__ import annotations

import shutil
from pathlib import Path

SOURCE_DIR = Path(__file__).resolve().parent / "skills" / "mockymock"


class SkillTargetExistsError(Exception):
    """Raised when the install target exists and --force wasn't given."""

    def __init__(self, target: Path) -> None:
        self.target = target
        super().__init__(f"{target} already exists; use --force to overwrite")


def resolve_target(project: bool) -> Path:
    """Where `mockymock skills install` writes to: the current directory's
    .claude/skills/mockymock for --project, else the user's home
    directory's -- the skill's content isn't project-specific, so a
    global install is the default and works across every COBOL repo
    tested with mockymock."""
    base = Path.cwd() if project else Path.home()
    return base / ".claude" / "skills" / "mockymock"


def install_skill(target: Path, *, force: bool = False) -> None:
    """Copy the packaged skill directory to `target`.

    Fail-closed: refuses (raises SkillTargetExistsError, leaving `target`
    untouched) if it already exists and `force` is False, so a user's
    local edits to a previously installed copy are never silently
    clobbered.
    """
    if target.exists() and not force:
        raise SkillTargetExistsError(target)
    if target.exists():
        # rmtree refuses a non-directory (a plain file, or a symlink even
        # when it points at a directory) -- unlink removes just the path
        # entry in both cases, without following a symlink into deleting
        # whatever it points at.
        if target.is_dir() and not target.is_symlink():
            shutil.rmtree(target)
        else:
            target.unlink()
    shutil.copytree(SOURCE_DIR, target)
