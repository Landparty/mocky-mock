"""Sibling `.cut`/`.cbl` inference and directory-wide `.cut` discovery.

See docs/2026-09-15-cli-ergonomics-design.md. Mirrors
mocky-mock-vscode's `resolveCblPath`/`resolveCutPath`
(`src/discovery/cutDiscovery.ts`) on the CLI side: same directory, same
stem, first matching extension that exists on disk.
"""

from __future__ import annotations

from pathlib import Path

# Order matters: .cbl is tried before .cob when both would exist (they
# never should for the same stem, but the order is deterministic either
# way). Matches mocky-mock-vscode's COBOL_SOURCE_EXTENSIONS list.
COBOL_SOURCE_EXTENSIONS = (".cbl", ".cob", ".CBL", ".COB")

# Directories a directory-wide `.cut` scan skips. Mirrors
# mocky-mock-vscode's CUT_DISCOVERY_EXCLUDE_GLOB so CLI and editor
# discovery agree on what "the project's own test suites" means.
CUT_DISCOVERY_EXCLUDE_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        ".venv",
        "venv",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "dist",
        "build",
    }
)


class DiscoveryError(Exception):
    """A program or `.cut` path could not be inferred from its sibling."""


def resolve_program_path(explicit: str | None, cut_path: Path) -> Path:
    """`explicit` wins unconditionally. Otherwise, look for a COBOL
    source file with the same stem as `cut_path`, in the same directory,
    trying `COBOL_SOURCE_EXTENSIONS` in order. Raises `DiscoveryError`
    (naming every candidate tried) if none exists."""
    if explicit is not None:
        return Path(explicit)
    candidates = [cut_path.with_suffix(ext) for ext in COBOL_SOURCE_EXTENSIONS]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    tried = ", ".join(str(c) for c in candidates)
    raise DiscoveryError(
        f"no COBOL source found beside {cut_path} (tried: {tried}); "
        f"pass the program path explicitly"
    )


def resolve_cut_path(explicit: str | None, program_path: Path) -> Path:
    """Same idea, the other direction: a `.cut` file with the same stem
    as `program_path`."""
    if explicit is not None:
        return Path(explicit)
    candidate = program_path.with_suffix(".cut")
    if candidate.is_file():
        return candidate
    raise DiscoveryError(
        f"no .cut file found beside {program_path} (tried: {candidate}); "
        f"pass --cut explicitly"
    )


def effective_copybook_paths(
    program_path: Path, resolved_paths: list[str]
) -> list[str]:
    """Append `program_path`'s own `copybooks/` subdirectory -- the
    layout every example under `examples/real-world/` uses -- to
    `resolved_paths` (already resolved from an explicit `--copybook-path`
    flag or the project config file, see `config.resolve_copybook_paths`),
    when it exists and isn't already present. Never reorders or removes
    anything the caller already resolved -- this is an additive fallback,
    tried after everything explicit, so a program with copybooks
    somewhere else entirely is unaffected and a program with none at all
    pays no cost. See docs/2026-09-15-copybook-discovery-defaults-design.md.

    Deliberately does NOT also default to `program_path`'s own directory
    (the design doc's original second fallback): that directory always
    exists trivially, so adding it unconditionally would turn every
    COPY-bearing program into an implicit copybook search even when none
    was ever configured -- observed in practice as
    test_fixtures_copy_bearing_program_without_copybook_path_refuses
    breaking, because a program with an unresolvable COPY and truly no
    copybook path configured is supposed to fall through unexpanded and
    be caught by the structural UNRESOLVED_COPYBOOK gate, not attempt
    (and fail) expansion against its own source directory."""
    result = list(resolved_paths)
    seen: set[Path] = set()
    for entry in result:
        try:
            seen.add(Path(entry).resolve())
        except OSError:  # pragma: no cover - unresolvable path, leave as-is
            continue
    default_dir = program_path.parent / "copybooks"
    if default_dir.is_dir():
        resolved_default = default_dir.resolve()
        if resolved_default not in seen:
            result.append(str(default_dir))
    return result


def copybook_not_found_hint() -> str:
    """The actionable follow-up line appended after a
    cobolparser.preprocess.CopybookNotFoundError's own message (which
    already names every path it searched). Formatted as a 4-space
    continuation line, matching how the rest of this CLI already renders
    a multi-line problem (see `_cmd_lint`'s "  " prefix convention)."""
    return (
        "    Pass its location with --copybook-path <dir> (repeatable), "
        "or add a [tool.mockymock] copybook_path entry -- see "
        "docs/2026-09-15-cli-ergonomics-design.md's config file."
    )


def discover_cut_files(root: Path) -> list[Path]:
    """Every `.cut` file under `root`, sorted for deterministic output,
    skipping `CUT_DISCOVERY_EXCLUDE_DIRS`. Returns an empty list (never
    raises) when `root` has no `.cut` files or doesn't exist."""
    if not root.is_dir():
        return []
    results = []
    for path in root.rglob("*.cut"):
        if any(part in CUT_DISCOVERY_EXCLUDE_DIRS for part in path.parts):
            continue
        results.append(path)
    return sorted(results)
