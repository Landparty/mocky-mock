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
