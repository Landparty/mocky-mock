"""Verify and install the cobol-testing skills from the dashboard.

The cobol-testing plugin is four agent skills (`skills_cmd.SKILL_NAMES`)
in the open Agent Skills format, which both Claude Code and GitHub Copilot
read. The dashboard installs them the way `mockymock skills install
--target <claude|copilot>` does -- a copy of the packaged skills into
`~/.claude/skills/<name>` or `~/.copilot/skills/<name>` -- because that
route needs no `/plugin` command and works in every setup of either tool.

**Verified means byte-identical.** A skill is `ok` only when every packaged
file exists in the installed copy with the same bytes and the installed
copy holds nothing extra. Anything else is reported per skill, with the
files that differ, so "installed" never means "a directory of that name
exists".

**Install is fail-closed like the CLI.** Without `force`, only `missing`
skills are written; an `outdated` copy (which may carry the user's own
edits) is left alone and reported. With `force`, every skill that is not
`ok` is replaced. An `ok` skill is never touched.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mockymock.cli.skills_cmd import (
    CLAUDE,
    PLUGIN_NAME,
    SKILL_NAMES,
    SKILLS_ROOT,
    TARGET_LABELS,
    TARGETS,
    install_skill,
    resolve_target,
    skills_dir,
)

OK = "ok"
OUTDATED = "outdated"  # present, but not the packaged bytes
MISSING = "missing"
BROKEN = "broken"  # a file or dangling symlink where the directory should be

# Two install requests at once (a double click, two tabs) would race on
# the same rmtree/copytree; the second waits and then finds the skills ok.
_install_lock = threading.Lock()

# How many differing paths one skill reports; the count is always exact.
_MAX_LISTED = 10


@dataclass(frozen=True)
class SkillCheck:
    name: str
    state: str
    path: str
    detail: str
    files: int
    differing: tuple[str, ...] = field(default=())

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "state": self.state,
            "path": self.path,
            "detail": self.detail,
            "files": self.files,
            "differing": list(self.differing),
        }


def _files(root: Path) -> dict[str, Path]:
    return {
        path.relative_to(root).as_posix(): path
        for path in sorted(root.rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts
    }


def check_skill(name: str, target: Path) -> SkillCheck:
    packaged = _files(SKILLS_ROOT / name)
    where = str(target)
    if target.is_symlink() and not target.exists():
        return SkillCheck(name, BROKEN, where, "dangling symlink", len(packaged), ())
    if not target.exists():
        return SkillCheck(name, MISSING, where, "not installed", len(packaged))
    if not target.is_dir():
        return SkillCheck(
            name, BROKEN, where, "a file, not a skill directory", len(packaged)
        )
    installed = _files(target)
    missing = [rel for rel in packaged if rel not in installed]
    changed = [
        rel
        for rel, source in packaged.items()
        if rel in installed and installed[rel].read_bytes() != source.read_bytes()
    ]
    extra = [rel for rel in installed if rel not in packaged]
    if not (missing or changed or extra):
        return SkillCheck(
            name,
            OK,
            where,
            f"{len(packaged)} file{'' if len(packaged) == 1 else 's'} match{'es' if len(packaged) == 1 else ''} this mockymock",
            len(packaged),
        )
    parts = []
    if changed:
        parts.append(f"{len(changed)} changed")
    if missing:
        parts.append(f"{len(missing)} missing")
    if extra:
        parts.append(f"{len(extra)} extra")
    differing = tuple(
        [f"changed: {p}" for p in changed]
        + [f"missing: {p}" for p in missing]
        + [f"extra: {p}" for p in extra]
    )[:_MAX_LISTED]
    return SkillCheck(
        name,
        OUTDATED,
        where,
        ", ".join(parts) + " -- differs from this mockymock's copy",
        len(packaged),
        differing,
    )


def verify_target(target: str) -> dict[str, Any]:
    """One assistant's skills directory: one check per skill."""
    checks = [
        check_skill(name, resolve_target(False, name, target)) for name in SKILL_NAMES
    ]
    return {
        "id": target,
        "label": TARGET_LABELS[target],
        "location": str(skills_dir(False, target)),
        "installed": all(check.state == OK for check in checks),
        "skills": [check.to_dict() for check in checks],
    }


def verify() -> dict[str, Any]:
    """`/api/plugin`: every assistant's user-level skills directory."""
    return {
        "plugin": PLUGIN_NAME,
        "targets": [verify_target(target) for target in TARGETS],
    }


def install(target: str = CLAUDE, force: bool = False) -> dict[str, Any]:
    """`POST /api/plugin/install`: write the skills `target` needs, then
    re-verify. Returns the verification plus what was written and what was
    left alone (and why). Raises ValueError for an unknown target."""
    if target not in TARGETS:
        raise ValueError(f"unknown target {target!r}")
    with _install_lock:
        return _install(target, force)


def _install(assistant: str, force: bool) -> dict[str, Any]:
    installed: list[str] = []
    skipped: list[dict[str, str]] = []
    errors: list[dict[str, str]] = []
    for name in SKILL_NAMES:
        target = resolve_target(False, name, assistant)
        state = check_skill(name, target).state
        if state == OK:
            continue
        if state != MISSING and not force:
            skipped.append(
                {"name": name, "reason": f"{state}; replacing it needs force"}
            )
            continue
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            install_skill(target, force=state != MISSING, name=name)
        except Exception as exc:  # noqa: BLE001 -- reported per skill
            errors.append({"name": name, "error": str(exc)})
            continue
        installed.append(name)
    return {
        **verify(),
        "target": assistant,
        "written": installed,
        "skipped": skipped,
        "errors": errors,
    }
