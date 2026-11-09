"""mockymock's packages are layered, and imports only point down.

    interface   cli, web, debug              thin: flags, output, protocols
    features    mutation, jobstream,         built on the engine
                the report builder
    engine      engine, project              one build, one run; the project
    core        dsl, analysis, splicer,      the pipeline's transforms
                report (the rest)
    infra       runtime, runner              processes and I/O
    root        mockymock                    `__version__`

A module may import its own layer or any layer below it, never one above.
Imports made only for type checking (`if TYPE_CHECKING:`) don't count;
imports inside function bodies do, because they are still dependencies
and are how upward edges used to hide.

The second test pins the import cycles that remain. Each one is listed
whole; a new cycle, or a module joining an existing one, fails. When a
cycle is broken, remove it from `KNOWN_CYCLES` so it cannot come back.

See `.okf/index.md` ("Layering") for why.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[2] / "mockymock"

#: Layers, highest first. A module's layer is the one whose prefix
#: matches it most specifically (`mockymock.report.test_report` is a
#: feature even though the rest of `mockymock.report` is core).
LAYERS: list[tuple[str, tuple[str, ...]]] = [
    (
        "interface",
        ("mockymock.cli", "mockymock.web", "mockymock.debug", "mockymock.__main__"),
    ),
    (
        "features",
        (
            "mockymock.mutation",
            "mockymock.jobstream",
            "mockymock.report.test_report",
            "mockymock.report.html_report",
        ),
    ),
    ("engine", ("mockymock.engine", "mockymock.project", "mockymock.api")),
    (
        "core",
        (
            "mockymock.dsl",
            "mockymock.analysis",
            "mockymock.splicer",
            "mockymock.report",
            "mockymock.copybooks",
            "mockymock._lines",
            "mockymock._decimal",
            "mockymock._qualified",
            "mockymock.debugging_lines",
        ),
    ),
    ("infra", ("mockymock.runtime", "mockymock.runner")),
    ("root", ("mockymock",)),
]

_RANK = {name: len(LAYERS) - i for i, (name, _) in enumerate(LAYERS)}

#: Import cycles still in the code, each as its full set of modules. Only
#: ever shrink this.
KNOWN_CYCLES: list[frozenset[str]] = [
    # The CLI's own: the parser imports each command to register it,
    # `init` reuses `build_parser`, and `job` hands `cli.main.main` to the
    # job runner (a job step IS a `mockymock run`). Both call-time imports.
    frozenset(
        {
            "mockymock.cli.main",
            "mockymock.cli.parser",
            "mockymock.cli.commands.init",
            "mockymock.cli.commands.job",
        }
    ),
    # `mock_surface` and the three scanners that need its site types.
    frozenset(
        {
            "mockymock.analysis.mock_surface",
            "mockymock.analysis.cics_handle",
            "mockymock.analysis.declaratives",
            "mockymock.analysis.sql_whenever",
        }
    ),
]


def _module_name(path: Path) -> str:
    parts = list(path.relative_to(PACKAGE.parent).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


_MODULES = {_module_name(p): p for p in PACKAGE.rglob("*.py")}


def _resolve(name: str) -> str:
    while name and name not in _MODULES:
        name = name.rpartition(".")[0]
    return name


def _type_checking_nodes(tree: ast.AST) -> set[int]:
    nodes: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and "TYPE_CHECKING" in ast.unparse(node.test):
            nodes.update(id(inner) for inner in ast.walk(node))
    return nodes


def _imports(module: str, path: Path) -> set[str]:
    """mockymock modules `module` imports at runtime (top-level or lazy)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    skip = _type_checking_nodes(tree)
    package = module if path.name == "__init__.py" else module.rpartition(".")[0]
    found: set[str] = set()
    for node in ast.walk(tree):
        if id(node) in skip:
            continue
        if isinstance(node, ast.Import):
            found.update(
                _resolve(a.name) for a in node.names if a.name.startswith("mockymock")
            )
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                parts = package.split(".")
                if node.level > 1:
                    parts = parts[: len(parts) - (node.level - 1)]
                base = ".".join(parts + ([node.module] if node.module else []))
            if not base.startswith("mockymock"):
                continue
            for alias in node.names:
                full = f"{base}.{alias.name}"
                found.add(full if full in _MODULES else _resolve(base))
    found.discard(module)
    found.discard("")
    return found


def _graph() -> dict[str, set[str]]:
    return {module: _imports(module, path) for module, path in _MODULES.items()}


def _layer(module: str) -> str:
    best: tuple[str, str] | None = None
    for name, prefixes in LAYERS:
        for prefix in prefixes:
            if (module == prefix or module.startswith(prefix + ".")) and (
                best is None or len(prefix) > len(best[1])
            ):
                best = (name, prefix)
    assert best is not None, f"{module} is in no layer; add it to LAYERS"
    return best[0]


def _cycles(graph: dict[str, set[str]]) -> list[frozenset[str]]:
    """Strongly connected components with more than one module (Tarjan)."""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    found: list[frozenset[str]] = []
    counter = 0

    def visit(node: str) -> None:
        nonlocal counter
        index[node] = low[node] = counter
        counter += 1
        stack.append(node)
        on_stack.add(node)
        for target in graph.get(node, ()):
            if target not in index:
                visit(target)
                low[node] = min(low[node], low[target])
            elif target in on_stack:
                low[node] = min(low[node], index[target])
        if low[node] == index[node]:
            component = set()
            while True:
                member = stack.pop()
                on_stack.discard(member)
                component.add(member)
                if member == node:
                    break
            if len(component) > 1:
                found.append(frozenset(component))

    limit = sys.getrecursionlimit()
    sys.setrecursionlimit(max(limit, 10_000))
    try:
        for node in graph:
            if node not in index:
                visit(node)
    finally:
        sys.setrecursionlimit(limit)
    return found


def test_imports_only_point_down():
    upward = sorted(
        f"{module} ({_layer(module)}) imports {target} ({_layer(target)})"
        for module, targets in _graph().items()
        for target in targets
        if _RANK[_layer(target)] > _RANK[_layer(module)]
    )
    assert not upward, "imports that point up a layer:\n" + "\n".join(upward)


def test_no_import_cycles_beyond_the_known_ones():
    def describe(cycle: frozenset[str]) -> str:
        return "{" + ", ".join(sorted(cycle)) + "}"

    found = set(_cycles(_graph()))
    known = set(KNOWN_CYCLES)
    new = sorted(describe(c) for c in found - known)
    assert not new, "new import cycles:\n" + "\n".join(new)
    gone = sorted(describe(c) for c in known - found)
    assert not gone, (
        "these known cycles are gone; remove them from KNOWN_CYCLES:\n"
        + "\n".join(gone)
    )


def test_every_module_has_a_layer():
    for module in _MODULES:
        _layer(module)
