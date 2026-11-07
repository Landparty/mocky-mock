"""The cobol-parser analysis section of `mockymock report`.

`build_report` already parses the program once (step 2) and uses a few
analyzers for its own verdict. This module runs the rest of what the
`cobol-analysis` skill would run on the same AST -- health score,
per-paragraph complexity, the call graph, every lint rule, duplicate
code, the program's external interface, and a data cross-reference --
so the report shows what the program *is* next to what its tests prove.

Each analyzer is imported and run in isolation: an analyzer that cannot
be loaded is listed in `unavailable` with the reason, and one that raises
costs only its own section. A section that could not be
produced is `None`, never an empty list that would read as "nothing
found".

Every line number is mapped back to the original .cbl through the
caller's `orig` function (copybook expansion shifts them), and every
list that grows with program size is capped, with the cap reported.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from typing import Any

# A program of a few thousand lines can have thousands of data items and
# references; the report is one HTML page, so lists are capped and the
# cap is reported as `truncated` rather than silently applied.
MAX_DATA_ITEMS = 300
MAX_LINT_FINDINGS = 300
MAX_EDGES = 400
MAX_GRAPH_NODES = 120

_NEWER = "needs a newer cobol-parser (1.9.0 or later)"

# Analyzer id -> (module, class, title). The order is the order of the
# sections in the report.
ANALYZERS: dict[str, tuple[str, str, str]] = {
    "health": ("cobolparser", "TechnicalDebtAnalyzer", "Health score"),
    "complexity": ("cobolparser", "ComplexityAnalyzer", "Complexity"),
    "lint": ("cobolparser", "LintAnalyzer", "Lint"),
    "redundancy": ("cobolparser", "RedundancyAnalyzer", "Duplicate code"),
    "signature": (
        "cobolparser.analysis.program_signature",
        "ProgramSignatureExtractor",
        "Calling interface",
    ),
    "boundaries": (
        "cobolparser.analysis.boundary_inventory",
        "BoundaryInventoryAnalyzer",
        "External touchpoints",
    ),
    "crud": ("cobolparser.analysis.crud_matrix", "CRUDMatrixGenerator", "CRUD"),
    "sqlCics": (
        "cobolparser.analysis.sql_cics_lint",
        "SqlCicsAnalyzer",
        "SQL / CICS checks",
    ),
    "xref": ("cobolparser.analysis.xref", "XrefAnalyzer", "Data cross-reference"),
}

_PARAGRAPH_EDGES = frozenset(
    {
        "PERFORM",
        "PERFORM_THRU",
        "GOTO",
        "GOTO_DEPENDING",
        "SORT_INPUT_PROCEDURE",
        "SORT_INPUT_PROCEDURE_THRU",
        "SORT_OUTPUT_PROCEDURE",
        "SORT_OUTPUT_PROCEDURE_THRU",
        "MERGE_OUTPUT_PROCEDURE",
        "MERGE_OUTPUT_PROCEDURE_THRU",
        "XML_PROCESSING_PROCEDURE",
        "XML_PROCESSING_PROCEDURE_THRU",
        "CICS_HANDLE",
        "ALTER",
    }
)
_WRITE_ROLES = frozenset({"write"})
_READ_ROLES = frozenset(
    {"read", "condition", "subscript", "call-argument", "host-variable"}
)


def _line(location: Any) -> int | None:
    if isinstance(location, dict):
        line = location.get("line")
        return line if isinstance(line, int) else None
    return None


def _load(analyzer_id: str) -> tuple[Any | None, str | None]:
    module_name, class_name, _ = ANALYZERS[analyzer_id]
    try:
        module = importlib.import_module(module_name)
        return getattr(module, class_name), None
    except (ImportError, AttributeError):
        return None, f"{class_name} {_NEWER}"


def analyze_program(
    ast: Any,
    flow: dict[str, Any],
    orig: Callable[[int | None], int | None],
    tested: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Run every available analyzer over `ast` and return the report's
    `analysis` block. `flow` is the ProgramFlowAnalyzer dict the caller
    already computed; `tested` maps paragraph name -> the test cases
    that reach it, so the call graph can show what the suite covers."""
    out: dict[str, Any] = {
        "available": True,
        "ran": [],
        "unavailable": [],
        "failed": [],
        "callGraph": _call_graph(flow, orig, tested or {}),
    }

    def run(analyzer_id: str, call: Callable[[Any], Any]) -> Any | None:
        cls, reason = _load(analyzer_id)
        title = ANALYZERS[analyzer_id][2]
        if cls is None:
            out["unavailable"].append(
                {"id": analyzer_id, "title": title, "reason": reason}
            )
            return None
        try:
            result = call(cls)
        except Exception as exc:  # noqa: BLE001 -- costs only this section
            out["failed"].append(
                {"id": analyzer_id, "title": title, "reason": f"{exc}"}
            )
            return None
        out["ran"].append(analyzer_id)
        return result

    health = run("health", lambda c: c().analyze(ast).to_dict())
    out["health"] = _health(health, orig) if health else None

    complexity = run("complexity", lambda c: c().analyze(ast).to_dict())
    out["complexity"] = _complexity(complexity, orig) if complexity else None

    lint = run("lint", lambda c: c().analyze(ast).to_dict())
    out["lint"] = _lint(lint, orig) if lint else None

    redundancy = run("redundancy", lambda c: c().analyze(ast).to_dict())
    out["redundancy"] = _redundancy(redundancy, orig) if redundancy else None

    signature = run("signature", lambda c: c().analyze(ast).to_dict())
    out["signature"] = _signature(signature, orig) if signature else None

    def _boundaries(cls: Any) -> Any:
        from cobolparser.generators.data.program_layout import ProgramLayoutIndex

        return cls().analyze(ast, ProgramLayoutIndex.build(ast)).to_dict()

    boundaries = run("boundaries", _boundaries)
    out["boundaries"] = _boundary_list(boundaries, orig) if boundaries else None

    crud = run("crud", lambda c: c().analyze(ast).to_dict())
    out["crud"] = _crud(crud) if crud else None

    sql_cics = run("sqlCics", lambda c: c().analyze(ast).to_dict())
    out["sqlCics"] = _sql_cics(sql_cics, orig) if sql_cics else None

    xref = run("xref", lambda c: c().analyze(ast).to_dict())
    out["dataItems"] = _data_items(xref, orig) if xref else None

    return out


def unavailable(reason: str) -> dict[str, Any]:
    """The `analysis` block when the program could not be analyzed at all."""
    return {"available": False, "reason": reason}


def summarize(analysis: dict[str, Any]) -> str:
    """One sentence for the report's step list."""
    if not analysis.get("available"):
        return f"Skipped: {analysis.get('reason')}"
    parts: list[str] = []
    health = analysis.get("health")
    if health:
        parts.append(f"health grade {health['grade']} (debt {health['score']:g}/100)")
    complexity = analysis.get("complexity")
    if complexity and complexity["summary"].get("max_complexity") is not None:
        parts.append(f"max complexity {complexity['summary']['max_complexity']}")
    lint = analysis.get("lint")
    if lint:
        parts.append(f"{lint['summary'].get('total', 0)} lint finding(s)")
    graph = analysis["callGraph"]
    parts.append(f"{len(graph['externalCalls'])} external CALL(s)")
    ran = len(analysis["ran"])
    total = ran + len(analysis["unavailable"]) + len(analysis["failed"])
    head = f"{ran} of {total} analyzers ran"
    return f"{head}: {', '.join(parts)}." if parts else f"{head}."


# --- Section builders ---------------------------------------------------


def _health(d: dict[str, Any], orig: Callable[..., int | None]) -> dict[str, Any]:
    return {
        "score": d.get("score", 0.0),
        "grade": d.get("grade"),
        "components": [
            {
                "name": c.get("name"),
                "score": c.get("score"),
                "weight": c.get("weight"),
                "findings": list(c.get("findings") or []),
            }
            for c in d.get("components") or []
        ],
        "topOffenders": [
            {
                "name": o.get("name"),
                "line": orig(_line(o.get("location"))),
                "reasons": list(o.get("reasons") or []),
                "severity": o.get("severity"),
            }
            for o in (d.get("top_offenders") or [])[:10]
        ],
        "redundancySummary": d.get("redundancy_summary") or {},
    }


def _complexity(d: dict[str, Any], orig: Callable[..., int | None]) -> dict[str, Any]:
    return {
        "thresholds": d.get("thresholds") or {},
        "summary": d.get("summary") or {},
        "procedures": [
            {
                "name": p.get("name"),
                "type": p.get("type"),
                "line": orig(_line(p.get("location"))),
                "cyclomatic": p.get("cyclomatic_complexity"),
                "extended": p.get("extended_complexity"),
                "nesting": p.get("max_nesting_depth"),
                "statements": p.get("statement_count"),
                "gotos": p.get("goto_count"),
                "fanIn": p.get("fan_in"),
                "fanOut": p.get("fan_out"),
                "rating": p.get("rating"),
            }
            for p in d.get("procedures") or []
        ],
    }


def _lint(d: dict[str, Any], orig: Callable[..., int | None]) -> dict[str, Any]:
    findings = d.get("findings") or []
    return {
        "rulesRun": list(d.get("rules_run") or []),
        "failedRules": list(d.get("failed_rules") or []),
        "caveats": [str(c) for c in d.get("caveats") or []],
        "summary": d.get("summary") or {},
        "findings": [
            {
                "rule": f.get("rule"),
                "severity": f.get("severity"),
                "message": f.get("message"),
                "line": orig(_line(f.get("location"))),
                "symbol": f.get("symbol"),
            }
            for f in findings[:MAX_LINT_FINDINGS]
        ],
        "truncated": len(findings) > MAX_LINT_FINDINGS,
    }


def _redundancy(d: dict[str, Any], orig: Callable[..., int | None]) -> dict[str, Any]:
    return {
        "summary": d.get("summary") or {},
        "cloneGroups": [
            {
                "type": g.get("clone_type"),
                "statements": g.get("statement_count"),
                "members": [
                    {"name": m.get("name"), "line": orig(_line(m.get("location")))}
                    for m in g.get("members") or []
                ],
            }
            for g in d.get("clone_groups") or []
        ],
    }


def _signature(d: dict[str, Any], orig: Callable[..., int | None]) -> dict[str, Any]:
    return {
        "programId": d.get("program_id"),
        "entryPoints": [
            {
                "name": e.get("name"),
                "kind": e.get("kind"),
                "returning": e.get("returning"),
                "callExample": e.get("call_example"),
                "parameters": [
                    {
                        "position": p.get("position"),
                        "name": p.get("name"),
                        "direction": p.get("direction"),
                        "by": p.get("by_clause"),
                        "declaration": p.get("declaration"),
                        "bytes": p.get("byte_length"),
                        "line": orig(_line(p.get("location"))),
                    }
                    for p in e.get("parameters") or []
                ],
            }
            for e in d.get("entry_points") or []
        ],
        "unchecked": [str(u) for u in d.get("unchecked") or []],
    }


def _boundary_list(
    d: dict[str, Any], orig: Callable[..., int | None]
) -> list[dict[str, Any]]:
    return [
        {
            "category": b.get("category"),
            "key": b.get("key"),
            "paragraph": b.get("paragraph"),
            "line": orig(b.get("line") if isinstance(b.get("line"), int) else None),
            "direction": b.get("direction"),
            "records": list(b.get("record_names") or []),
            "statusField": b.get("status_field"),
        }
        for b in d.get("boundaries") or []
    ]


def _crud(d: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for kind, key in (("file", "files"), ("table", "tables")):
        for entry in d.get(key) or []:
            crud = entry.get("crud") or {}
            rows.append(
                {
                    "kind": kind,
                    "name": entry.get("resource_name"),
                    "create": bool(crud.get("create")),
                    "read": bool(crud.get("read")),
                    "update": bool(crud.get("update")),
                    "delete": bool(crud.get("delete")),
                    "openModes": list(entry.get("open_modes") or []),
                }
            )
    return rows


def _sql_cics(d: dict[str, Any], orig: Callable[..., int | None]) -> dict[str, Any]:
    return {
        "sqlStatements": d.get("sql_statements", 0),
        "cicsStatements": d.get("cics_statements", 0),
        "violations": [
            {
                "severity": v.get("severity"),
                "kind": v.get("kind"),
                "message": v.get("message"),
                "line": orig(_line(v.get("location"))),
            }
            for v in d.get("violations") or []
        ],
        "unchecked": [
            u if isinstance(u, str) else str(u.get("message") or u)
            for u in d.get("unchecked") or []
        ],
    }


def _data_items(d: dict[str, Any], orig: Callable[..., int | None]) -> dict[str, Any]:
    """Data flow per data item: where it is written, where it is read.
    Paragraph-level (the xref `context`), which is what a tester needs to
    pick the paragraph to PERFORM and the field to EXPECT on."""
    items: list[dict[str, Any]] = []
    for entry in d.get("entries") or []:
        if entry.get("kind") not in (None, "data-item", "condition-name"):
            continue
        refs = entry.get("references") or []
        written_in: list[str] = []
        read_in: list[str] = []
        writes = reads = 0
        for ref in refs:
            role = ref.get("role")
            context = ref.get("context")
            if role in _WRITE_ROLES:
                writes += 1
                if context and context not in written_in:
                    written_in.append(context)
            elif role in _READ_ROLES:
                reads += 1
                if context and context not in read_in:
                    read_in.append(context)
        items.append(
            {
                "name": entry.get("name"),
                "kind": entry.get("kind"),
                "section": entry.get("section"),
                "level": entry.get("level"),
                "line": orig(_line(entry.get("definition"))),
                "references": entry.get("reference_count", len(refs)),
                "writes": writes,
                "reads": reads,
                "writtenIn": written_in,
                "readIn": read_in,
            }
        )
    # Most-referenced first: that is where a test's EXPECTs should look.
    items.sort(key=lambda i: (-(i["references"] or 0), str(i["name"])))
    return {
        "items": items[:MAX_DATA_ITEMS],
        "total": len(items),
        "unreferenced": sum(1 for i in items if not i["references"]),
        "truncated": len(items) > MAX_DATA_ITEMS,
    }


def _call_graph(
    flow: dict[str, Any],
    orig: Callable[..., int | None],
    tested: dict[str, list[str]],
) -> dict[str, Any]:
    """Paragraph-to-paragraph control flow (PERFORM / GO TO / SORT
    procedures ...) plus the external programs it CALLs. Branch nodes the
    flow analyzer synthesizes (`X__IF_1`) fold into their paragraph."""
    unreachable = set(flow.get("unreachable_nodes") or [])
    nodes = []
    for node in flow.get("nodes") or []:
        name = node.get("name")
        if not name or "__" in name:
            continue
        nodes.append(
            {
                "name": name,
                "line": orig(_line(node.get("location"))),
                "entry": bool(node.get("is_entry_point")),
                "exit": bool(node.get("is_exit_point")),
                "unreachable": name in unreachable,
                "testedBy": list(tested.get(name, [])),
            }
        )
    known = {n["name"] for n in nodes}
    seen: set[tuple[str, str, str]] = set()
    edges: list[dict[str, Any]] = []
    for edge in flow.get("edges") or []:
        kind = str(edge.get("type", ""))
        if kind not in _PARAGRAPH_EDGES:
            continue
        source = str(edge.get("source", "")).split("__", 1)[0]
        target = str(edge.get("target", "")).split("__", 1)[0]
        if source not in known or target not in known:
            continue
        label = kind.replace("_THRU", "").replace("_", " ")
        key = (source, target, label)
        if key in seen:
            continue
        seen.add(key)
        edges.append(
            {
                "source": source,
                "target": target,
                "type": label,
                "line": orig(_line(edge.get("location"))),
            }
        )
    calls = [
        {
            "program": c.get("program"),
            "dynamic": bool(c.get("is_dynamic")),
            "from": str(c.get("called_from", "")).split("__", 1)[0],
            "line": orig(_line(c.get("location"))),
            "possibleValues": list(c.get("possible_values") or []),
        }
        for c in flow.get("external_calls") or []
    ]
    return {
        "nodes": nodes,
        "edges": edges[:MAX_EDGES],
        "edgesTruncated": len(edges) > MAX_EDGES,
        "externalCalls": calls,
        "cycles": [
            {
                "nodes": [str(n).split("__", 1)[0] for n in c.get("nodes") or []],
                "kind": c.get("kind"),
            }
            for c in flow.get("cycle_details") or []
        ],
        "drawn": len(nodes) <= MAX_GRAPH_NODES,
    }
