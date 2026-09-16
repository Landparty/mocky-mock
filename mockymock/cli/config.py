"""Project-level configuration: `mockymock.toml` or `pyproject.toml`'s
`[tool.mockymock]` table.

See docs/2026-09-15-cli-ergonomics-design.md. Search order, first match
wins, walking from `start_dir` up through parent directories: a
`mockymock.toml` in a directory beats a `pyproject.toml` in that same
directory (both are tried per directory before moving up), mirroring how
`git` walks up looking for `.git`. Every recognized key is optional;
precedence at the call site is always explicit CLI flag > config file >
built-in default -- this module never overrides a flag the user actually
passed.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from mockymock.cli.ai_mode import CONFIG_KEY as _AI_MODE_KEY
from mockymock.cli.ai_mode import MODES as _AI_MODES

# A config file could in principle sit at the root of a deeply nested
# monorepo checkout; this bounds the walk so a detached or networked
# filesystem can't turn "no config file" into an unbounded stat loop.
_MAX_WALK_LEVELS = 32

_STRING_LIST_KEY = "copybook_path"
_INT_KEYS = ("seed",)
_STRING_KEYS = ("test_root", _AI_MODE_KEY)
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


def _build_config(data: dict, source: Path) -> MockymockConfig:
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
    ai_mode = data.get(_AI_MODE_KEY)
    if ai_mode is not None and ai_mode not in _AI_MODES:
        raise ConfigError(
            f"mockymock: {source}: '{_AI_MODE_KEY}' must be one of "
            f"{', '.join(_AI_MODES)} (got {ai_mode!r})"
        )
    test_root = Path(data.get("test_root", "."))
    if not test_root.is_absolute():
        test_root = source.parent / test_root
    return MockymockConfig(
        source=source,
        copybook_path=_normalize_copybook_path(data.get(_STRING_LIST_KEY), source),
        seed=data.get("seed"),
        ai_mode=ai_mode,
        test_root=str(test_root),
    )


def load_config(start_dir: Path | None = None) -> MockymockConfig:
    """Search `start_dir` (default: cwd) and its parents for a config
    file. Returns an all-default `MockymockConfig` (source=None) if none
    is found anywhere in the walk -- this is the common case and is not
    an error."""
    directory = (start_dir or Path.cwd()).resolve()
    for _ in range(_MAX_WALK_LEVELS):
        toml_path = directory / "mockymock.toml"
        if toml_path.is_file():
            return _build_config(_read_toml(toml_path), toml_path)

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
                return _build_config(mm_table, pyproject_path)

        parent = directory.parent
        if parent == directory:
            break
        directory = parent
    return MockymockConfig()


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
