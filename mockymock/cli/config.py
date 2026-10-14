"""Project-level configuration.

Two files, layered:

1. **`cobol.yml`** (or `cobol.yaml`) -- the *universal* project config the
   whole COBOL tool family reads: `cobol-parser`, this CLI, and the COBOL
   Analyzer VS Code extension. Its `project:` section holds the settings
   every tool shares (copybook paths, seed); its `mockymock:` section holds
   the ones only this CLI understands. See `docs/project-config.md` in the
   cobol-parser repo for the full schema.
2. **`mockymock.toml`**, or `pyproject.toml`'s `[tool.mockymock]` table --
   the tool-specific file, which predates the universal one and keeps
   working unchanged.

Both are searched for independently, each walking from `start_dir` up
through its parents the way `git` walks up looking for `.git`; the nearest
of each wins its own search. When both exist, the **tool-specific file
overrides the universal one key by key** -- more specific beats more
general -- and `MockymockConfig.sources` lists both, base first. The
alternative, first-match-wins across the two, would mean a `mockymock.toml`
setting one key silently discarded a `cobol.yml` that set the other three.

Every recognized key is optional; precedence at the call site is always
explicit CLI flag > config file > built-in default. This module never
overrides a flag the user actually passed.

See docs/2026-09-15-cli-ergonomics-design.md for the original tool-specific
design, and docs/2026-09-16-universal-yaml-config-design.md for the
universal layer.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mockymock.cli.ai_mode import _UNIVERSAL_SECTION as UNIVERSAL_SECTION
from mockymock.cli.ai_mode import CONFIG_KEY as _AI_MODE_KEY
from mockymock.cli.ai_mode import MODES as _AI_MODES

# A config file could in principle sit at the root of a deeply nested
# monorepo checkout; this bounds the walk so a detached or networked
# filesystem can't turn "no config file" into an unbounded stat loop.
_MAX_WALK_LEVELS = 32

# The universal config file, tried in this order within each directory.
UNIVERSAL_FILE_NAMES = ("cobol.yml", "cobol.yaml")

# `UNIVERSAL_SECTION` (imported above) is the section of the universal file
# this tool owns. Keys there mean the same thing as in `mockymock.toml`, and
# override anything `project:` said.

_STRING_LIST_KEY = "copybook_path"
_INT_KEYS = ("seed",)
_STRING_KEYS = ("test_root", "source_root", _AI_MODE_KEY)
# Every key a config file may carry. Anything else is rejected rather
# than ignored: a typo'd `copybook-path` (hyphen) or a `timeout` key
# (deliberately not config-overridable -- see `_apply_config_to_args` in
# cli/main.py) that quietly did nothing would be a config the user
# believes is in effect and isn't.
_KNOWN_KEYS = frozenset({_STRING_LIST_KEY, *_INT_KEYS, *_STRING_KEYS})


class ConfigError(Exception):
    """A config file exists but could not be parsed, or has a bad shape.
    Deliberately not silently ignored/defaulted -- a malformed config is
    a fail-closed error naming the file, same posture as the rest of
    this CLI's input validation."""


@dataclass(frozen=True)
class MockymockConfig:
    # The file that had the last word. When both a universal and a
    # tool-specific file are in play this is the tool-specific one, since
    # that is where `skills mode --set` would write.
    source: Path | None = None
    copybook_path: tuple[str, ...] = field(default_factory=tuple)
    seed: int | None = None
    # How much the packaged AI assistant checks in while it builds a
    # suite (mockymock/cli/ai_mode.py). None means "no ai_mode key
    # anywhere", which is distinct from the default mode being written
    # out explicitly -- `mockymock skills mode` reports the provenance,
    # so the two must stay distinguishable.
    ai_mode: str | None = None
    # Relative to the config file that declared it (like copybook_path),
    # so `mockymock run` from a subdirectory still finds the same suites
    # as from the project root. "." with no config file means cwd.
    test_root: str = "."
    # Where the programs live, for mirroring tests/ (cli/discovery.py).
    # Absolute once read, like test_root; None means the project root.
    source_root: str | None = None
    # Every file that contributed, base (universal) first. `source` alone
    # cannot express "a cobol.yml supplied the copybook paths and a
    # mockymock.toml the seed", which is what `doctor` needs to report.
    sources: tuple[Path, ...] = field(default_factory=tuple)
    # The file whose `ai_mode` is in effect -- not necessarily `source`: a
    # cobol.yml's `mockymock: ai_mode:` under a mockymock.toml that only
    # sets a seed was reported as coming from the mockymock.toml.
    ai_mode_source: Path | None = None


def _read_toml(path: Path) -> dict:
    try:
        with path.open("rb") as fh:
            return tomllib.load(fh)
    except OSError as exc:
        raise ConfigError(f"mockymock: could not read {path}: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"mockymock: could not parse {path}: {exc}") from exc


def _normalize_copybook_path(value: object, source: Path) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ConfigError(
            f"mockymock: {source}: 'copybook_path' must be a string or a "
            f"list of strings"
        )
    base = source.parent
    resolved = []
    for entry in value:
        entry_path = Path(entry)
        resolved.append(
            str(entry_path if entry_path.is_absolute() else base / entry_path)
        )
    return tuple(resolved)


def _validated_values(data: dict, source: Path) -> dict[str, Any]:
    """Validate one config table and return only the keys it actually sets.

    Returning present-keys-only (rather than a fully defaulted config) is
    what lets the two layers merge without a defaulted key in the
    tool-specific file silently erasing a real value from the universal one.
    """
    unknown = sorted(set(data) - _KNOWN_KEYS)
    if unknown:
        raise ConfigError(
            f"mockymock: {source}: unknown key(s) {', '.join(unknown)} "
            f"(recognized: {', '.join(sorted(_KNOWN_KEYS))})"
        )
    for key in _INT_KEYS:
        # bool is an int subclass; `seed = true` is a mistake, not seed 1.
        if key in data and (
            isinstance(data[key], bool) or not isinstance(data[key], int)
        ):
            raise ConfigError(f"mockymock: {source}: '{key}' must be an integer")
    for key in _STRING_KEYS:
        if key in data and not isinstance(data[key], str):
            raise ConfigError(f"mockymock: {source}: '{key}' must be a string")

    values: dict[str, Any] = {}
    if _STRING_LIST_KEY in data:
        values["copybook_path"] = _normalize_copybook_path(
            data[_STRING_LIST_KEY], source
        )
    if "seed" in data:
        values["seed"] = data["seed"]
    if _AI_MODE_KEY in data:
        ai_mode = data[_AI_MODE_KEY]
        if ai_mode not in _AI_MODES:
            raise ConfigError(
                f"mockymock: {source}: '{_AI_MODE_KEY}' must be one of "
                f"{', '.join(_AI_MODES)} (got {ai_mode!r})"
            )
        values["ai_mode"] = ai_mode
    if "test_root" in data:
        test_root = Path(data["test_root"])
        if not test_root.is_absolute():
            test_root = source.parent / test_root
        values["test_root"] = str(test_root)
    if "source_root" in data:
        source_root = Path(data["source_root"])
        if not source_root.is_absolute():
            source_root = source.parent / source_root
        values["source_root"] = str(source_root)
    return values


# -- the universal cobol.yml layer -------------------------------------------


def find_universal_config(start_dir: Path | None = None) -> Path | None:
    """The nearest `cobol.yml`/`cobol.yaml` at or above `start_dir`.

    Done here rather than delegated to cobolparser so that a project with a
    `cobol.yml` and a cobol-parser too old to read one gets told exactly
    that, instead of the file being silently skipped.
    """
    directory = (start_dir or Path.cwd()).resolve()
    for _ in range(_MAX_WALK_LEVELS):
        for name in UNIVERSAL_FILE_NAMES:
            candidate = directory / name
            if candidate.is_file():
                return candidate
        parent = directory.parent
        if parent == directory:
            break
        directory = parent
    return None


def _universal_values(path: Path) -> dict[str, Any]:
    """Read a `cobol.yml` into this tool's key set.

    `project:` supplies the settings shared with every other tool;
    `mockymock:` then overrides them with anything stated specifically for
    this CLI, so a project can share a seed and still pin a different one
    for test generation.

    The YAML parsing and `project:` validation are cobol-parser's --
    duplicating them here would be a second schema to keep in step with the
    first, and the two drifting is exactly the failure a single universal
    file exists to prevent.
    """
    try:
        from cobolparser.config import ConfigError as ParserConfigError
        from cobolparser.config import load_project_config
    except ImportError as exc:  # pragma: no cover - depends on installed version
        raise ConfigError(
            f"mockymock: {path} needs a cobol-parser that can read it "
            f"(>= 1.10). Upgrade with 'pip install -U cobol-parser', or "
            f"move these settings into a mockymock.toml."
        ) from exc

    try:
        project = load_project_config(path=path)
    except ParserConfigError as exc:
        raise ConfigError(f"mockymock: {exc}") from exc

    values: dict[str, Any] = {}
    if project.copybook_path:
        values["copybook_path"] = tuple(project.copybook_path)
    if project.seed is not None:
        values["seed"] = project.seed
    values.update(_validated_values(project.tool_section(UNIVERSAL_SECTION), path))
    return values


# -- the tool-specific mockymock.toml layer -----------------------------------


def find_tool_config(start_dir: Path | None = None) -> tuple[Path, dict] | None:
    """The nearest `mockymock.toml`, or `pyproject.toml` `[tool.mockymock]`.

    A `mockymock.toml` in a directory beats a `pyproject.toml` in that same
    directory (both are tried per directory before moving up).
    """
    directory = (start_dir or Path.cwd()).resolve()
    for _ in range(_MAX_WALK_LEVELS):
        toml_path = directory / "mockymock.toml"
        if toml_path.is_file():
            return toml_path, _read_toml(toml_path)

        pyproject_path = directory / "pyproject.toml"
        if pyproject_path.is_file():
            data = _read_toml(pyproject_path)
            tool_table = data.get("tool")
            if isinstance(tool_table, dict) and "mockymock" in tool_table:
                mm_table = tool_table["mockymock"]
                if not isinstance(mm_table, dict):
                    raise ConfigError(
                        f"mockymock: {pyproject_path}: [tool.mockymock] "
                        f"must be a table"
                    )
                return pyproject_path, mm_table

        parent = directory.parent
        if parent == directory:
            break
        directory = parent
    return None


def load_config(start_dir: Path | None = None) -> MockymockConfig:
    """Search `start_dir` (default: cwd) and its parents for config files.

    Returns an all-default `MockymockConfig` (source=None) if neither a
    universal nor a tool-specific file is found anywhere in the walk -- this
    is the common case and is not an error.
    """
    directory = start_dir or Path.cwd()

    values: dict[str, Any] = {}
    sources: list[Path] = []

    universal_path = find_universal_config(directory)
    if universal_path is not None:
        universal = _universal_values(universal_path)
        values.update(universal)
        sources.append(universal_path)
        if "ai_mode" in universal:
            values["ai_mode_source"] = universal_path

    tool_config = find_tool_config(directory)
    if tool_config is not None:
        tool_path, tool_data = tool_config
        tool_values = _validated_values(tool_data, tool_path)
        values.update(tool_values)
        sources.append(tool_path)
        if "ai_mode" in tool_values:
            values["ai_mode_source"] = tool_path

    if not sources:
        return MockymockConfig()
    return MockymockConfig(source=sources[-1], sources=tuple(sources), **values)


def resolve(cli_value, config_value, hardcoded_default=None):
    """Precedence helper: an explicit CLI value (not None) always wins,
    then the config file's value (not None), then the hardcoded
    default. Used for every flag that can come from either a CLI flag
    or the config file (copybook_path, seed)."""
    if cli_value is not None:
        return cli_value
    if config_value is not None:
        return config_value
    return hardcoded_default


def resolve_copybook_paths(
    cli_value: list[str] | None, config: MockymockConfig
) -> list[str]:
    """`--copybook-path` is `action="append"`, so an explicit flag list
    always wins outright (it is not merged with the config's list --
    the user asked for exactly these directories). With no flag at all,
    the config's list is used, in the order it was written."""
    if cli_value is not None:
        return cli_value
    return list(config.copybook_path)
