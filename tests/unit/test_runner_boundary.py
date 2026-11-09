"""`mockymock.runner` (the LegacyLens oracle worker) stays a separable
component (tech-debt audit 2026-11-06, item 11).

It runs uploaded, untrusted COBOL and speaks a backend's HTTP protocol --
a different threat model from the local testing CLI. It is kept apart by
two rules, pinned here so the boundary cannot erode silently:

* nothing in the testing CLI imports it, except the `runner` subcommand's
  own lazy import;
* it reaches the rest of mockymock only through the `mockymock` command
  line it runs as a subprocess, plus the few leaf helpers listed below.

Splitting it into its own distribution then needs no untangling.
"""

from __future__ import annotations

import ast
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[2] / "mockymock"
RUNNER = PACKAGE / "runner"

#: Modules outside `mockymock.runner` that may import it.
ALLOWED_IMPORTERS = {"mockymock.cli.main", "mockymock.cli.commands.runner"}

#: mockymock modules (outside the runner) the runner may import.
ALLOWED_DEPENDENCIES = {"mockymock", "mockymock.runtime._proc"}


def _module_name(path: Path) -> str:
    rel = path.relative_to(PACKAGE.parent).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
    return found


def test_only_the_runner_command_imports_the_runner():
    offenders = {
        _module_name(path)
        for path in PACKAGE.rglob("*.py")
        if RUNNER not in path.parents
        and any(
            m == "mockymock.runner" or m.startswith("mockymock.runner.")
            for m in _imported_modules(path)
        )
    }
    assert offenders <= ALLOWED_IMPORTERS, offenders - ALLOWED_IMPORTERS


def test_the_runner_depends_on_no_testing_cli_internals():
    used = {
        m
        for path in RUNNER.rglob("*.py")
        for m in _imported_modules(path)
        if (m == "mockymock" or m.startswith("mockymock."))
        and not (m == "mockymock.runner" or m.startswith("mockymock.runner."))
    }
    assert used <= ALLOWED_DEPENDENCIES, used - ALLOWED_DEPENDENCIES
