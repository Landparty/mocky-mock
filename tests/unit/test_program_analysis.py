"""mockymock.report.program_analysis: the cobol-parser analysis section of
`mockymock report` -- health, complexity, call graph, lint, duplicates,
interface and data cross-reference -- and how it degrades when the
installed cobol-parser predates an analyzer."""

import importlib
import shutil
from pathlib import Path

import pytest

from mockymock.report import program_analysis
from mockymock.report.html_report import render_html
from mockymock.report.test_report import ReportOptions, build_report

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


def _has(module: str, name: str) -> bool:
    try:
        return hasattr(importlib.import_module(module), name)
    except ImportError:
        return False


HAS_LINT = _has("cobolparser", "LintAnalyzer")
HAS_XREF = _has("cobolparser.analysis.xref", "XrefAnalyzer")


@pytest.fixture
def ordrproc(tmp_path):
    shutil.copy(EXAMPLES / "ordrproc" / "ORDRPROC.cbl", tmp_path / "ORDRPROC.cbl")
    shutil.copy(EXAMPLES / "ordrproc" / "ORDRPROC.cut", tmp_path / "ORDRPROC.cut")
    return tmp_path


def _report(root: Path, name: str = "ORDRPROC", **kwargs):
    return build_report(
        ReportOptions(
            program=root / f"{name}.cbl",
            cut=root / f"{name}.cut",
            probe_toolchain=False,
            scenarios="none",
            **kwargs,
        )
    )


def _step(report, step_id):
    return next(s for s in report["steps"] if s["id"] == step_id)


def test_analysis_runs_every_available_analyzer(ordrproc):
    report = _report(ordrproc)
    analysis = report["analysis"]
    assert analysis["available"] is True
    assert analysis["failed"] == []
    assert set(analysis["ran"]) | {u["id"] for u in analysis["unavailable"]} == set(
        program_analysis.ANALYZERS
    )
    # Present since the 1.7.7 floor.
    for always in ("health", "complexity", "redundancy", "crud", "boundaries"):
        assert always in analysis["ran"]
    assert analysis["health"]["grade"] in {"A", "B", "C", "D", "F"}
    (proc,) = analysis["complexity"]["procedures"]
    assert proc["name"] == "PROCESS-ORDER"
    assert proc["line"] == 12
    assert proc["cyclomatic"] == 1
    step = _step(report, "analysis")
    assert step["summary"].startswith(f"{len(analysis['ran'])} of 9 analyzers ran")


def test_call_graph_lists_external_calls_and_the_tests_that_reach_each_paragraph(
    ordrproc,
):
    graph = _report(ordrproc)["analysis"]["callGraph"]
    (node,) = graph["nodes"]
    assert node["name"] == "PROCESS-ORDER"
    assert node["entry"] is True
    assert len(node["testedBy"]) == 2
    (call,) = graph["externalCalls"]
    assert call["program"] == "DISCRATE"
    assert call["from"] == "PROCESS-ORDER"
    assert call["line"] == 13
    assert call["dynamic"] is False


def test_call_graph_folds_branch_nodes_into_their_paragraph():
    flow = {
        "nodes": [
            {"name": "A", "location": {"line": 1}, "is_entry_point": True},
            {"name": "A__IF_1", "location": {"line": 2}},
            {"name": "B", "location": {"line": 5}},
            {"name": "C", "location": {"line": 9}},
        ],
        "edges": [
            {"source": "A", "target": "A__IF_1", "type": "IF_BRANCH"},
            {"source": "A__IF_1", "target": "B", "type": "PERFORM"},
            {"source": "A__IF_1", "target": "B", "type": "PERFORM"},
            {"source": "B", "target": "C", "type": "GOTO"},
            {"source": "B", "target": "C", "type": "FALL_THROUGH"},
        ],
        "unreachable_nodes": [],
    }
    graph = program_analysis._call_graph(flow, lambda line: line, {"B": ["t1"]})
    assert [n["name"] for n in graph["nodes"]] == ["A", "B", "C"]
    assert [(e["source"], e["target"], e["type"]) for e in graph["edges"]] == [
        ("A", "B", "PERFORM"),
        ("B", "C", "GOTO"),
    ]
    assert graph["nodes"][1]["testedBy"] == ["t1"]


@pytest.mark.skipif(not HAS_LINT, reason="cobol-parser without LintAnalyzer")
def test_lint_findings_carry_rule_severity_and_original_line(tmp_path):
    program = (EXAMPLES / "ordrproc" / "ORDRPROC.cbl").read_text(encoding="utf-8")
    program = program.replace(
        "       01  WS-CAPTURED-AMOUNT  PIC 9(5)V99.\n",
        "       01  WS-CAPTURED-AMOUNT  PIC 9(5)V99.\n       01  WS-NEVER-USED       PIC X.\n",
    )
    (tmp_path / "ORDRPROC.cbl").write_text(program, encoding="utf-8")
    shutil.copy(EXAMPLES / "ordrproc" / "ORDRPROC.cut", tmp_path / "ORDRPROC.cut")
    lint = _report(tmp_path)["analysis"]["lint"]
    (finding,) = [f for f in lint["findings"] if f["symbol"] == "WS-NEVER-USED"]
    assert finding["rule"] == "unused-variables"
    assert finding["severity"] == "warning"
    assert finding["line"] == 10
    assert "unused-variables" in lint["rulesRun"]


@pytest.mark.skipif(not HAS_XREF, reason="cobol-parser without XrefAnalyzer")
def test_data_items_say_where_each_field_is_written_and_read(ordrproc):
    data = _report(ordrproc)["analysis"]["dataItems"]
    by_name = {i["name"]: i for i in data["items"]}
    net = by_name["WS-NET-AMOUNT"]
    assert net["writes"] >= 1
    assert net["writtenIn"] == ["PROCESS-ORDER"]
    assert by_name["ORD-AMOUNT"]["reads"] >= 1
    assert data["total"] >= 4
    assert data["truncated"] is False


def test_a_missing_analyzer_is_reported_not_silently_dropped(ordrproc, monkeypatch):
    real = program_analysis._load

    def no_lint(analyzer_id):
        if analyzer_id in ("lint", "xref"):
            return None, "LintAnalyzer needs a newer cobol-parser (1.9.0 or later)"
        return real(analyzer_id)

    monkeypatch.setattr(program_analysis, "_load", no_lint)
    report = _report(ordrproc)
    analysis = report["analysis"]
    assert analysis["lint"] is None
    assert analysis["dataItems"] is None
    assert {u["id"] for u in analysis["unavailable"]} >= {"lint", "xref"}
    assert analysis["health"] is not None
    assert _step(report, "analysis")["status"] == "warn"
    page = render_html(report)
    assert "Not shown: " in page
    assert "Upgrade cobol-parser" in page
    assert ">Lint</h3>" not in page
    assert ">Complexity</h3>" in page


def test_an_analyzer_that_raises_costs_only_its_own_section(ordrproc, monkeypatch):
    class Boom:
        def analyze(self, ast):
            raise RuntimeError("kaboom")

    real = program_analysis._load
    monkeypatch.setattr(
        program_analysis,
        "_load",
        lambda i: (Boom, None) if i == "health" else real(i),
    )
    analysis = _report(ordrproc)["analysis"]
    assert analysis["health"] is None
    assert analysis["failed"] == [
        {"id": "health", "title": "Health score", "reason": "kaboom"}
    ]
    assert analysis["complexity"] is not None


def test_an_unparseable_program_skips_the_analysis_with_a_reason(tmp_path):
    (tmp_path / "BAD.cbl").write_text("THIS IS NOT COBOL.\n", encoding="utf-8")
    shutil.copy(EXAMPLES / "ordrproc" / "ORDRPROC.cut", tmp_path / "BAD.cut")
    report = _report(tmp_path, "BAD")
    assert report["analysis"] == {
        "available": False,
        "reason": "the program did not parse.",
    }
    assert _step(report, "analysis")["status"] == "skipped"
    assert "No program analysis: the program did not parse." in render_html(report)


def test_copybook_program_analysis_lines_point_into_the_original_source(tmp_path):
    shutil.copytree(EXAMPLES / "cpyproc", tmp_path / "cpyproc")
    root = tmp_path / "cpyproc"
    report = _report(root, "CPYPROC", copybook_paths=[str(root / "copybooks")])
    original = (root / "CPYPROC.cbl").read_text(encoding="utf-8").splitlines()
    procedures = report["analysis"]["complexity"]["procedures"]
    assert procedures
    for proc in procedures:
        if proc["line"] is not None:
            assert proc["name"] in original[proc["line"] - 1]


def test_page_draws_the_call_graph_and_every_analysis_heading(ordrproc):
    page = render_html(_report(ordrproc))
    assert ">Program analysis</h2>" in page
    for heading in ("Health score", "Call graph", "Complexity", "Interface"):
        assert f">{heading}</h3>" in page
    assert '<svg role="img" aria-label="Paragraph call graph"' in page
    assert ">CALL DISCRATE</text>" in page
    assert ">PROCESS-ORDER</text>" in page
    assert "Code health" in page  # summary tile


def test_a_report_written_before_the_analysis_existed_still_renders(ordrproc):
    report = _report(ordrproc)
    del report["analysis"]
    page = render_html(report)
    assert "written before program analysis was added" in page


def test_large_graphs_are_not_drawn(ordrproc, monkeypatch):
    monkeypatch.setattr(program_analysis, "MAX_GRAPH_NODES", 0)
    page = render_html(_report(ordrproc))
    assert "too many to draw" in page
    assert "<svg" not in page


def test_analysis_values_are_escaped(ordrproc):
    report = _report(ordrproc)
    report["analysis"]["callGraph"]["externalCalls"][0]["program"] = "<b>X</b>"
    page = render_html(report)
    assert "<b>X</b>" not in page
    assert "&lt;b&gt;X&lt;/b&gt;" in page
