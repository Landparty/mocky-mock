"""`mockymock report`: one document saying what a test suite proves.

Every other subcommand answers one question (does it lint, does it pass,
which mutants survive). This one runs or reads all of them for one
program/`.cut` pair and joins the answers into a single report, step by
step, ending in a verdict per test case:

1. environment   -- toolchain, versions, AI assistant mode
2. understand    -- paragraphs, entry points, dead code, complexity
3. rules         -- business rules (cobol-parser's BusinessRuleExtractor)
3b. analysis     -- every other cobol-parser analyzer: health, complexity,
                    call graph, lint, duplicates, interface, data xref
                    (report/program_analysis.py)
4. inventory     -- test cases, their PERFORM targets, assertion labels
5. lint          -- the static refusal gate (`mockymock lint`)
6. scenarios     -- branch-arm coverage the fixture generator can reach
7. run           -- pass/fail per case (`run --json-report`)
8. coverage      -- executed lines of the original .cbl
9. mutation      -- which changes the suite would catch (`mutate`)
10. dialect      -- GnuCOBOL vs IBM Enterprise COBOL risks per case
11. verdict      -- verification level per case + findings

Steps 7-9 are read from JSON a previous run wrote (`--run-json`,
`--coverage-json`, `--mutation-json`) or produced on the spot
(`--execute`, `--mutate`), so an assistant that already ran the suite does
not pay for it twice. A step that could not run says so and why; it is
never silently left out, and nothing downstream claims more than the steps
that actually ran support.

Verification levels (per test case, the highest one reached in order):

* L0 static   -- the suite passes the refusal gate: nothing escapes
* L1 executed -- the case passed in a real GnuCOBOL run
* L2 strong   -- it asserts something, and the suite's mutation score is
                 at or above the threshold
* L3 dialect-checked -- no high/medium dialect risk is reachable from its
                 PERFORM target
* L4 mainframe-confirmed -- never computed here: it needs the same test
                 run on z/OS (`mockymock export`), which is outside what
                 this machine can observe
"""

from __future__ import annotations

import json
import math
import re
import subprocess
import sys
import tempfile
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from fractions import Fraction
from pathlib import Path
from typing import Any

from mockymock import __version__

REPORT_VERSION = 1
LEVELS = ("L0", "L1", "L2", "L3")
LEVEL_TITLES = {
    "L0": "Static",
    "L1": "Executed",
    "L2": "Strong",
    "L3": "Dialect-checked",
    "L4": "Mainframe-confirmed",
}
DEFAULT_MUTATION_THRESHOLD = 80.0
_NON_FLOW_EDGES = frozenset(
    {"FALL_THROUGH", "CALL", "CALL_DYNAMIC", "DYNAMIC_CALL", "CANCEL"}
)
_SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2, "info": 3}


@dataclass
class ReportOptions:
    program: Path
    cut: Path
    copybook_paths: list[str] = field(default_factory=list)
    run_json: Path | None = None
    coverage_json: Path | None = None
    mutation_json: Path | None = None
    journal: Path | None = None
    execute: bool = False
    mutate: bool = False
    scenarios: str = "branches"  # happy | branches | all | none
    seed: int | None = None
    timeout: int | None = None
    mutation_threshold: float = DEFAULT_MUTATION_THRESHOLD
    probe_toolchain: bool = True


@dataclass
class Step:
    id: str
    title: str
    status: str = "ok"  # ok | warn | fail | skipped
    summary: str = ""
    command: str | None = None
    duration_ms: int = 0
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "status": self.status,
            "summary": self.summary,
            "command": self.command,
            "durationMs": self.duration_ms,
            "details": self.details,
        }


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _cobolparser_version() -> str:
    try:
        from importlib.metadata import version

        return version("cobol-parser")
    except Exception:  # noqa: BLE001 -- best-effort metadata
        return "unknown"


def _copybook_flags(paths: list[str]) -> str:
    return "".join(f" --copybook-path {p}" for p in paths)


def _load_json(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, f"{path} does not exist"
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"{path} could not be read as JSON ({exc})"
    if not isinstance(value, dict):
        return None, f"{path} is not a JSON object"
    return value, None


class _Timer:
    def __init__(self, step: Step) -> None:
        self.step = step

    def __enter__(self) -> Step:
        self.start = time.perf_counter()
        return self.step

    def __exit__(self, *exc: object) -> None:
        self.step.duration_ms = int((time.perf_counter() - self.start) * 1000)


@dataclass
class _Program:
    """The parsed program plus the line map back to the original .cbl."""

    ast: Any
    original_lines: list[str]
    line_map: dict[int, int] | None  # parsed line -> original line (1-based)
    expanded: bool


def _parse_program(options: ReportOptions) -> tuple[_Program | None, str | None]:
    from cobolparser import parse_cobol

    from mockymock._lines import read_utf8_source, split_source_lines
    from mockymock.analysis.flow_targets import normalize_flow_targets
    from mockymock.report.coverage import _matching_index_map

    raw = read_utf8_source(options.program)
    original_lines = split_source_lines(raw)
    source = raw
    expanded = False
    if options.copybook_paths and re.search(r"\bCOPY\b", raw, re.IGNORECASE):
        try:
            from cobolparser.preprocess import expand_copybooks

            source = expand_copybooks(
                raw, copybook_paths=options.copybook_paths
            ).expanded_source
            expanded = True
        except Exception as exc:  # noqa: BLE001 -- reported as the step's reason
            return None, f"copybook expansion failed: {exc}"
    result = parse_cobol(source, filename=options.program.name)
    normalize_flow_targets(result.ast)
    if result.ast is None or not result.success:
        errors = "; ".join(str(e) for e in result.errors[:3])
        return None, f"parse failed: {errors or 'no AST'}"
    line_map: dict[int, int] | None = None
    if expanded:
        index = _matching_index_map(original_lines, split_source_lines(source))
        line_map = {b + 1: a + 1 for b, a in index.items()}
    return _Program(result.ast, original_lines, line_map, expanded), None


def _orig(program: _Program, line: int | None) -> int | None:
    if line is None or line <= 0:
        return None
    if program.line_map is None:
        return line
    return program.line_map.get(line)


#: cobol-parser rejoins EXEC tokens with spaces the source never had:
#: `SEGMENT ( CLAIM-SEG )` reads back as `SEGMENT (CLAIM-SEG)`.
_EXEC_PAREN_SPACING_RE = re.compile(r"(?<=\()\s+|\s+(?=\))")


def _boundaries(
    program: _Program, test_cases: list[Any], cases: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Every boundary statement mockymock's splicer knows (one row per
    statement, in source order), with the cases whose MOCKs match it and
    the cases whose PERFORM reaches its paragraph without mocking it.
    Matching is `directive_matches_site`, the rule `run` itself uses, so a
    row's "mocked by" is exactly what a run would splice."""
    from mockymock.analysis.mock_surface import _TERMINATOR_LABELS, analyze
    from mockymock.analysis.refusal._gates import directive_matches_site

    surface = analyze(program.ast)
    mocks = {tc.name: tc.mocks for tc in test_cases}
    rows = []
    for site in sorted(surface.boundary_sites, key=lambda s: s.line):
        if site.category is None and site.label in _TERMINATOR_LABELS:
            continue
        mocked_by = [
            c["name"]
            for c in cases
            if any(directive_matches_site(m, site) for m in mocks.get(c["name"], []))
        ]
        reached_by = [
            c["name"]
            for c in cases
            if site.paragraph_name in c["reach"] and c["name"] not in mocked_by
        ]
        rows.append(
            {
                "kind": site.label,
                "category": site.category.keyword if site.category else None,
                "target": _EXEC_PAREN_SPACING_RE.sub(
                    "", (site.match_text or ", ".join(site.keys)).strip()
                ),
                "paragraph": site.paragraph_name,
                "line": _orig(program, site.line),
                "mockable": site.category is not None,
                "mq": site.is_mq,
                "mockedBy": mocked_by,
                "reachedUnmockedBy": reached_by,
            }
        )
    return rows


def _paragraph_of(node: str) -> str:
    """Program-flow synthesizes branch nodes like `1000-X__IF_1`; they belong
    to the paragraph they sit in."""
    return node.split("__", 1)[0]


def _section_members(ast: Any) -> dict[str, list[str]]:
    """SECTION name -> its named paragraphs, from the AST."""
    procedure = ast.get_division("PROCEDURE") if ast is not None else None
    if procedure is None:
        return {}
    return {
        name: [p.paragraph_name for p in section.paragraphs if p.paragraph_name]
        for name, section in getattr(procedure, "_sections", {}).items()
    }


def _reach(
    start: str,
    thru: str | None,
    order: list[str],
    edges: dict[str, set[str]],
    sections: dict[str, list[str]] | None = None,
) -> set[str]:
    """Paragraphs a `PERFORM start [THRU thru]` can execute: the range
    itself plus everything reachable from it over PERFORM/GO TO/branch
    edges (fall-through is excluded -- a PERFORMed paragraph returns at its
    end instead of falling into the next one). A reached SECTION also
    reaches every paragraph in it (`sections`, name -> member paragraphs):
    the flow graph links those only by FALL_THROUGH edges, so `PERFORM S2`
    reached `S2` alone (issue #292)."""
    seeds = [start]
    if thru and start in order and thru in order:
        i, j = order.index(start), order.index(thru)
        if i <= j:
            seeds = order[i : j + 1]
    seen: set[str] = set()
    stack = list(seeds)
    while stack:
        node = stack.pop()
        if node in seen:
            continue
        seen.add(node)
        stack.extend(edges.get(node, ()))
        stack.extend((sections or {}).get(node, ()))
    return seen


def _run_cli(args: list[str], timeout: int | None) -> tuple[int, str]:
    command = [sys.executable, "-m", "mockymock.cli.main", *args]
    try:
        completed = subprocess.run(  # noqa: S603 -- argv list, no shell
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {timeout}s"
    return completed.returncode, (completed.stdout + completed.stderr)


def _tail(text: str, lines: int = 40) -> str:
    return "\n".join(text.rstrip().splitlines()[-lines:])


def _failure_messages(entry: dict[str, Any]) -> list[str]:
    return [
        str(f.get("message"))
        for f in entry.get("failures") or []
        if isinstance(f, dict) and f.get("message")
    ]


def _first_line(text: str) -> str:
    """The first line that names an error, else the first non-blank one:
    cobc puts an "in paragraph 'X':" context line ahead of the error."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in lines:
        if "error" in line.lower():
            return line
    return lines[0] if lines else text


def _exact_mutation_percent(totals: dict[str, Any], raw_score: Any) -> Fraction | None:
    """The mutation score as an exact percentage: from the killed /
    timeout / survived counts when the report carries them (what
    `MutationOutcome.score_below` compares), else from the 0..1 `score`
    read as its decimal text. None when there is no score at all."""
    counts = [totals.get(k) for k in ("killed", "timeouts", "survived")]
    if all(type(c) is int for c in counts):
        killed, timeouts, survived = (int(str(c)) for c in counts)
        scored = killed + timeouts + survived
        if scored > 0:
            return Fraction(100 * (killed + timeouts), scored)
    if isinstance(raw_score, (int, float)) and not isinstance(raw_score, bool):
        return Fraction(str(raw_score)) * 100
    return None


def build_report(options: ReportOptions) -> dict[str, Any]:  # noqa: C901
    steps: list[Step] = []
    program_rel = options.program.name
    cut_rel = options.cut.name
    cb = _copybook_flags(options.copybook_paths)

    # 1. Environment ------------------------------------------------------
    env = Step("environment", "Check the environment")
    toolchain: dict[str, Any] | None = None
    with _Timer(env):
        details: dict[str, Any] = {
            "mockymock": __version__,
            "cobolParser": _cobolparser_version(),
            "python": sys.version.split()[0],
        }
        if options.probe_toolchain:
            try:
                from mockymock.runtime.status import probe

                toolchain = probe().to_dict()
            except Exception as exc:  # noqa: BLE001 -- reported, not fatal
                toolchain = {"ready": False, "error": str(exc), "checks": []}
            details["toolchain"] = toolchain
        try:
            from mockymock.cli.ai_mode import resolve_mode
            from mockymock.cli.config import load_config

            details["aiMode"] = resolve_mode(load_config()).to_dict()
        except Exception as exc:  # noqa: BLE001 -- a malformed config is reported
            details["aiMode"] = {"error": str(exc)}
        env.details = details
        if toolchain is None:
            env.summary = "Toolchain probe skipped."
        elif toolchain.get("ready"):
            env.summary = (
                f"GnuCOBOL toolchain ready ({toolchain.get('cobc_version')}); "
                f"mockymock {__version__}, cobol-parser {details['cobolParser']}."
            )
        else:
            env.status = "warn"
            env.summary = (
                "GnuCOBOL toolchain not ready: only static steps can run "
                "here. `mockymock doctor` says what is missing."
            )
        env.command = "mockymock doctor"
    steps.append(env)

    # 2. Understand -------------------------------------------------------
    understand = Step(
        "understand",
        "Understand the program",
        command=f"mockymock analyze program-flow {program_rel}",
    )
    program: _Program | None = None
    flow: dict[str, Any] = {}
    paragraphs: list[dict[str, Any]] = []
    order: list[str] = []
    edges: dict[str, set[str]] = {}
    with _Timer(understand):
        program, reason = _parse_program(options)
        if program is None:
            understand.status = "fail"
            understand.summary = f"Could not parse {program_rel}: {reason}"
        else:
            from cobolparser import ProgramFlowAnalyzer

            try:
                from cobolparser.analysis.program_flow import LEADING_SENTENCES_NODE
            except ImportError:  # cobol-parser < 1.9.0: same node, not exported
                LEADING_SENTENCES_NODE = "PROCEDURE DIVISION"

            flow = ProgramFlowAnalyzer().analyze(program.ast).to_dict()
            complexity: dict[str, dict[str, Any]] = {}
            try:
                from cobolparser import ComplexityAnalyzer

                for proc in (
                    ComplexityAnalyzer().analyze(program.ast).to_dict()["procedures"]
                ):
                    complexity[proc["name"]] = proc
            except Exception:  # noqa: BLE001 -- older cobol-parser: no complexity
                complexity = {}
            unreachable = set(flow.get("unreachable_nodes") or [])
            for node in flow.get("nodes") or []:
                name = node["name"]
                order.append(name)
                c = complexity.get(name, {})
                paragraphs.append(
                    {
                        "name": name,
                        "type": node.get("type"),
                        "line": _orig(
                            program, (node.get("location") or {}).get("line")
                        ),
                        "statements": node.get("statement_count"),
                        "entry": bool(node.get("is_entry_point")),
                        # The holder for any sentences written before the
                        # PROCEDURE DIVISION's first paragraph name (an ENTRY
                        # statement, typically) -- not a real paragraph, so
                        # no TESTCASE can ever PERFORM it. Flagging it
                        # "untested" would be a permanent false positive for
                        # every program shaped this way.
                        "isLeadingSentences": name == LEADING_SENTENCES_NODE,
                        "unreachable": name in unreachable,
                        "complexity": c.get("cyclomatic_complexity"),
                        "rating": c.get("rating"),
                        "testedBy": [],
                        "reachedBy": [],
                        "risks": 0,
                    }
                )
            for edge in flow.get("edges") or []:
                if edge.get("type") in _NON_FLOW_EDGES:
                    continue
                source = _paragraph_of(str(edge.get("source", "")))
                target = _paragraph_of(str(edge.get("target", "")))
                if source and target and source != target:
                    edges.setdefault(source, set()).add(target)
            understand.details = {
                "programName": flow.get("program_name"),
                "entryPoints": flow.get("entry_points") or [],
                "unreachable": sorted(unreachable),
                "copybooksExpanded": program.expanded,
                "complexityAvailable": bool(complexity),
            }
            understand.summary = (
                f"{len(paragraphs)} paragraph(s), entry point "
                f"{', '.join(flow.get('entry_points') or ['(none)'])}, "
                f"{len(unreachable)} unreachable."
            )
            if unreachable:
                understand.status = "warn"
    steps.append(understand)

    # 3. Business rules ---------------------------------------------------
    rules_step = Step(
        "rules",
        "Extract business rules",
        command=f"cobol-parser business-rules {program_rel}",
    )
    rules: list[dict[str, Any]] = []
    rules_available = False
    with _Timer(rules_step):
        if program is None:
            rules_step.status = "skipped"
            rules_step.summary = "Skipped: the program did not parse."
        else:
            try:
                from cobolparser import BusinessRuleExtractor
            except ImportError:
                rules_step.status = "skipped"
                rules_step.summary = (
                    "Skipped: this cobol-parser has no BusinessRuleExtractor "
                    "(upgrade cobol-parser to get rule-cited assertions)."
                )
            else:
                rules_available = True
                extracted = BusinessRuleExtractor().analyze(program.ast).to_dict()
                for rule in extracted.get("rules") or []:
                    if rule.get("technical") or rule.get("in_dead_code"):
                        continue
                    branches = rule.get("branches") or []
                    rules.append(
                        {
                            "id": rule.get("rule_id"),
                            "kind": rule.get("kind"),
                            "procedure": rule.get("procedure"),
                            "line": _orig(
                                program, (rule.get("location") or {}).get("line")
                            ),
                            "statement": rule.get("statement"),
                            "condition": rule.get("formula") or rule.get("condition"),
                            "branches": [
                                {
                                    "label": b.get("label"),
                                    "condition": b.get("condition"),
                                }
                                for b in branches
                            ],
                            "outputs": rule.get("outputs") or [],
                            "citedBy": [],
                        }
                    )
                rules_step.summary = f"{len(rules)} business rule(s) found."
                rules_step.details = {
                    "technicalExcluded": (extracted.get("summary") or {}).get(
                        "technical_rules_excluded"
                    )
                }
    steps.append(rules_step)

    # 3b. Program analysis ------------------------------------------------
    analysis_step = Step(
        "analysis",
        "Analyze the program",
        command=f"cobol-parser health {program_rel}; cobol-parser lint {program_rel}",
    )
    with _Timer(analysis_step):
        from mockymock.report import program_analysis

        if program is None:
            analysis = program_analysis.unavailable("the program did not parse.")
            analysis_step.status = "skipped"
        else:
            parsed = program
            analysis = program_analysis.analyze_program(
                parsed.ast, flow, lambda line: _orig(parsed, line)
            )
            if analysis["unavailable"] or analysis["failed"]:
                analysis_step.status = "warn"
            analysis_step.details = {
                "ran": list(analysis["ran"]),
                "unavailable": list(analysis["unavailable"]),
                "failed": list(analysis["failed"]),
            }
        analysis_step.summary = program_analysis.summarize(analysis)
    steps.append(analysis_step)

    # 4. Inventory --------------------------------------------------------
    inventory = Step("inventory", "Inventory the test suite")
    cut_text = ""
    suite = None
    cases: list[dict[str, Any]] = []
    assertions: list[dict[str, Any]] = []
    with _Timer(inventory):
        from mockymock.analysis.assertion_labels import (
            scan_assertion_labels,
            summarize_labels,
        )
        from mockymock.dsl.parser import CutParseError, parse_cut

        cut_text = options.cut.read_text(encoding="utf-8")
        labelled = scan_assertion_labels(cut_text)
        assertions = [a.to_dict() for a in labelled]
        try:
            suite = parse_cut(cut_text)
        except CutParseError as exc:
            inventory.status = "fail"
            inventory.summary = f"{cut_rel} does not parse: {exc}"
        if suite is not None:
            by_case: dict[str, list[dict[str, Any]]] = {}
            for a in assertions:
                by_case.setdefault(a["case"], []).append(a)
            for test_case in suite.test_cases:
                own = by_case.get(test_case.name, [])
                cases.append(
                    {
                        "name": test_case.name,
                        "line": test_case.line or None,
                        "tags": list(test_case.tags),
                        "perform": test_case.perform_target,
                        "performThru": test_case.perform_thru,
                        "mocks": len(test_case.mocks),
                        "assertions": {
                            "total": len(own),
                            "intent": sum(1 for a in own if a["label"] == "intent"),
                            "characterization": sum(
                                1 for a in own if a["label"] == "characterization"
                            ),
                            "unlabelled": sum(1 for a in own if a["label"] is None),
                        },
                        "status": "not_run",
                        "failures": [],
                        "reach": [],
                        "risks": [],
                        "level": None,
                        "levelReason": "",
                    }
                )
            counts = summarize_labels(labelled)
            inventory.details = {"labels": counts}
            inventory.summary = (
                f"{len(cases)} test case(s), {counts['total']} assertion(s): "
                f"{counts['intent']} intent, {counts['characterization']} "
                f"characterization, {counts['unlabelled']} unlabelled."
            )
            if counts["unlabelled"]:
                inventory.status = "warn"
    inventory.command = f"mockymock collect {program_rel} --cut {cut_rel} --json"
    steps.append(inventory)

    # Case reach, paragraph test mapping, rule citations.
    section_members = _section_members(program.ast) if program is not None else {}
    by_name = {p["name"]: p for p in paragraphs}
    for case in cases:
        if not case["perform"]:
            continue
        reach = _reach(
            case["perform"], case["performThru"], order, edges, section_members
        )
        case["reach"] = sorted(reach)
        performed = by_name.get(case["perform"])
        if performed is not None:
            performed["testedBy"].append(case["name"])
        for name in reach:
            if name in by_name and case["name"] not in by_name[name]["reachedBy"]:
                by_name[name]["reachedBy"].append(case["name"])
    boundaries = (
        _boundaries(program, suite.test_cases if suite else [], cases)
        if program is not None
        else []
    )
    for node in (analysis.get("callGraph") or {}).get("nodes") or []:
        paragraph = by_name.get(node["name"])
        if paragraph is not None:
            node["testedBy"] = list(paragraph["reachedBy"])
    rules_by_id = {r["id"].upper(): r for r in rules if r.get("id")}
    for a in assertions:
        if a["label"] != "intent":
            continue
        for rule_id in a["ruleIds"]:
            rule = rules_by_id.get(rule_id)
            if rule is not None and a["case"] not in rule["citedBy"]:
                rule["citedBy"].append(a["case"])

    # 5. Lint -------------------------------------------------------------
    lint = Step(
        "lint",
        "Check the suite statically",
        command=f"mockymock lint {program_rel} --cut {cut_rel}{cb}",
    )
    lint_problems: list[str] = []
    with _Timer(lint):
        from mockymock.cli.checks import run_static_checks

        try:
            checked = run_static_checks(
                options.program, options.cut, options.copybook_paths or None
            )
            lint_problems = list(checked.problems)
            lint.details = {"problems": lint_problems, "notes": list(checked.notes)}
        except Exception as exc:  # noqa: BLE001 -- reported as the failure
            lint_problems = [f"static checks crashed: {exc}"]
            lint.details = {"problems": lint_problems}
        headline = [p for p in lint_problems if not p.startswith("  ")]
        if headline:
            lint.status = "fail"
            lint.summary = f"{len(headline)} problem(s): the suite cannot run as is."
        else:
            lint.summary = "No problems: every reachable boundary is mocked."
    steps.append(lint)

    # 6. Scenario coverage ------------------------------------------------
    # This step asks the *automatic* data generator (ProgramFixtureGenerator)
    # whether it alone can construct boundary data that selects each branch
    # arm -- it says nothing about whether the test suite itself reaches
    # that arm. A case written by hand (a MOVE before the PERFORM, or a mock
    # body) routinely covers an arm this step calls "missed"; see the
    # "generated-data gap" finding below and the "Measure line coverage"
    # step for what the suite actually ran.
    scenarios = Step(
        "scenarios",
        "Check which branch arms the automatic generator alone can reach",
        command=f"mockymock fixtures {program_rel} --scenarios {options.scenarios}{cb}",
    )
    scenario_coverage: dict[str, Any] | None = None
    with _Timer(scenarios):
        if options.scenarios == "none":
            scenarios.status = "skipped"
            scenarios.summary = "Skipped (--scenarios none)."
        elif program is None:
            scenarios.status = "skipped"
            scenarios.summary = "Skipped: the program did not parse."
        else:
            try:
                from cobolparser.generators import ProgramFixtureGenerator

                bundle = ProgramFixtureGenerator().generate_with_scenarios_from_file(
                    str(options.program),
                    copybook_paths=options.copybook_paths or None,
                    mode=options.scenarios,
                    seed=options.seed,
                )
                scenario_coverage = getattr(bundle, "scenario_coverage", None)
                boundary = bundle.coverage.to_dict() if bundle.coverage else None
                scenarios.details = {
                    "scenarioCoverage": scenario_coverage,
                    "boundaries": boundary,
                    "scenarios": len(bundle.scenarios),
                }
                if scenario_coverage:
                    total = scenario_coverage.get("total_arms", 0)
                    missed = scenario_coverage.get("missed", 0)
                    scenarios.summary = (
                        f"The automatic generator alone can reach {total - missed} "
                        f"of {total} branch arm(s); {missed} need a hand-written "
                        "case instead (each with a reason) -- this is not the "
                        "suite's own coverage, see 'Measure line coverage' for that."
                    )
                    if missed:
                        scenarios.status = "warn"
                else:
                    scenarios.summary = (
                        f"{len(bundle.scenarios)} scenario(s) generated (happy path)."
                    )
            except Exception as exc:  # noqa: BLE001 -- reported as the reason
                scenarios.status = "skipped"
                scenarios.summary = f"Skipped: fixture generation failed ({exc})."
    steps.append(scenarios)

    # 7/8. Run + coverage -------------------------------------------------
    run_step = Step(
        "run",
        "Run the suite under GnuCOBOL",
        command=(
            f"mockymock run {program_rel} --cut {cut_rel}{cb} "
            f"--json-report RUN.json --coverage-json COVERAGE.json"
        ),
    )
    coverage_step = Step("coverage", "Measure line coverage")
    run_errors: list[str] = []
    run_report: dict[str, Any] | None = None
    coverage_report: dict[str, Any] | None = None
    workdir = Path(tempfile.mkdtemp(prefix="mockymock-report-"))
    run_json, coverage_json = options.run_json, options.coverage_json
    with _Timer(run_step):
        if options.execute:
            if lint_problems:
                run_step.status = "skipped"
                run_step.summary = "Skipped: lint problems would refuse the run."
            else:
                run_json = workdir / "run.json"
                coverage_json = workdir / "coverage.json"
                args = [
                    "run",
                    str(options.program),
                    "--cut",
                    str(options.cut),
                    "--json-report",
                    str(run_json),
                    "--coverage-json",
                    str(coverage_json),
                ]
                for path in options.copybook_paths:
                    args += ["--copybook-path", path]
                if options.timeout:
                    args += ["--timeout", str(options.timeout)]
                code, output = _run_cli(args, None)
                run_step.details["output"] = _tail(output)
                run_step.details["exitCode"] = code
        if run_json is not None and run_step.status != "skipped":
            run_report, error = _load_json(run_json)
            if run_report is None:
                run_step.status = "fail"
                run_step.summary = (
                    f"No run report: {error}. "
                    + ("See the output below." if options.execute else "")
                ).strip()
        elif run_step.status != "skipped":
            run_step.status = "skipped"
            run_step.summary = (
                "Not run: pass --execute (needs Docker) or --run-json "
                "from an earlier `mockymock run --json-report`."
            )
        if run_report is not None:
            cases_by_name = {c["name"]: c for c in cases}
            for entry in run_report.get("cases") or []:
                matched = cases_by_name.get(entry.get("name"))
                if matched is None:
                    # No TESTCASE of that name: `run`'s synthetic
                    # "mockymock run" entry for a failure before any case
                    # started (a compile error). Dropping it read a suite
                    # that never compiled as an ok run (issue #260).
                    if entry.get("status") in ("failed", "crashed"):
                        run_errors.extend(
                            _failure_messages(entry)
                            or [f"{entry.get('name')} {entry.get('status')}"]
                        )
                    continue
                matched["status"] = entry.get("status", "not_run")
                matched["failures"] = entry.get("failures") or []
            for orphan in run_report.get("orphanFailures") or []:
                run_errors.append(
                    f"case id {orphan.get('caseId')}: {orphan.get('message', '')}"
                )
            summary = run_report.get("summary") or {}
            passed = sum(1 for c in cases if c["status"] == "passed")
            failed = sum(1 for c in cases if c["status"] in ("failed", "crashed"))
            reported = sum(
                n
                for n in (summary.get("casesFailed"), summary.get("casesCrashed"))
                if isinstance(n, int)
            )
            if not run_errors and reported > failed:
                run_errors.append(
                    f"the run reports {reported} failed or crashed case(s) that "
                    f"match no TESTCASE in {cut_rel}"
                )
            run_step.summary = (
                f"{passed} passed, {failed} failed or crashed, "
                f"{sum(1 for c in cases if c['status'] == 'not_run')} not run."
            )
            run_step.details["summary"] = summary
            if run_errors:
                run_step.details["runErrors"] = run_errors
                run_step.summary += (
                    f" The run itself failed: {_first_line(run_errors[0])}"
                )
            run_step.status = "ok" if failed == 0 and not run_errors else "fail"
    steps.append(run_step)

    with _Timer(coverage_step):
        coverage_step.command = run_step.command
        if coverage_json is not None:
            coverage_report, error = _load_json(coverage_json)
            if coverage_report is None:
                coverage_step.status = "skipped"
                coverage_step.summary = f"No coverage data: {error}."
        else:
            coverage_step.status = "skipped"
            coverage_step.summary = "Not measured (needs a run with --coverage-json)."
        if coverage_report is not None:
            original = coverage_report.get("original") or {}
            uncovered = [
                entry["line"]
                for entry in original.get("lines") or []
                if not entry.get("covered")
            ]
            coverage_step.details = {
                "percentage": original.get("percentage"),
                "covered": original.get("totalCovered"),
                "executable": original.get("totalExecutable"),
                "uncoveredLines": uncovered,
            }
            coverage_step.summary = (
                f"{original.get('percentage', 0):.2f}% of {program_rel}'s executable "
                f"lines ran ({original.get('totalCovered')}/"
                f"{original.get('totalExecutable')})."
            )
            if uncovered:
                coverage_step.status = "warn"
    steps.append(coverage_step)

    # 9. Mutation ---------------------------------------------------------
    mutation_step = Step(
        "mutation",
        "Test the tests with mutation",
        command=f"mockymock mutate {program_rel} --cut {cut_rel}{cb} --json-report MUTATION.json",
    )
    mutation_report: dict[str, Any] | None = None
    mutation_passes = False
    mutation_json = options.mutation_json
    with _Timer(mutation_step):
        if options.mutate:
            if lint_problems:
                mutation_step.status = "skipped"
                mutation_step.summary = "Skipped: lint problems."
            else:
                mutation_json = workdir / "mutation.json"
                args = [
                    "mutate",
                    str(options.program),
                    "--cut",
                    str(options.cut),
                    "--json-report",
                    str(mutation_json),
                ]
                for path in options.copybook_paths:
                    args += ["--copybook-path", path]
                code, output = _run_cli(args, None)
                mutation_step.details["output"] = _tail(output)
                mutation_step.details["exitCode"] = code
        if mutation_json is not None and mutation_step.status != "skipped":
            mutation_report, error = _load_json(mutation_json)
            if mutation_report is None and options.mutate:
                # `mutate` exits early without a report for a reason it
                # prints (no mutable statements, a red baseline run):
                # surface that reason instead of a missing-file message.
                output = str(mutation_step.details.get("output", "")).strip()
                reason = output.splitlines()[-1] if output else error
                mutation_step.status = "skipped"
                mutation_step.summary = f"No mutation score: {reason}"
            elif mutation_report is None:
                mutation_step.status = "fail"
                mutation_step.summary = f"No mutation report: {error}."
        elif mutation_step.status != "skipped":
            mutation_step.status = "skipped"
            mutation_step.summary = (
                "Not run: pass --mutate (needs Docker) or --mutation-json."
            )
        if mutation_report is not None:
            totals = mutation_report.get("totals") or {}
            # `mutate --json-report` writes the score as a 0..1 fraction;
            # the report (and --mutation-threshold) speaks percent.
            raw_score = mutation_report.get("score")
            exact = _exact_mutation_percent(totals, raw_score)
            # Truncated, not rounded, for display: 79.96% must never read
            # as 80.0% next to a threshold of 80 (issue #282).
            score = None if exact is None else math.floor(exact * 10) / 10.0
            mutation_report["scorePercent"] = score
            # Compared exactly, the way `mutate --fail-under` compares
            # (`MutationOutcome.score_below`), so the report and the CI
            # gate never disagree about the same mutants.
            mutation_passes = exact is not None and exact >= Fraction(
                str(options.mutation_threshold)
            )
            survivors = [
                m
                for m in mutation_report.get("mutants") or []
                if m.get("status") == "survived"
            ]
            mutation_step.details = {
                "score": score,
                "totals": totals,
                "survivors": survivors,
                "threshold": options.mutation_threshold,
            }
            score_text = "n/a" if score is None else f"{score:.1f}%"
            mutation_step.summary = (
                f"Mutation score {score_text}: {totals.get('killed', 0)} killed, "
                f"{totals.get('survived', 0)} survived of {totals.get('generated', 0)}."
            )
            if not mutation_passes:
                mutation_step.status = "warn"
    steps.append(mutation_step)

    # 10. Dialect risk ----------------------------------------------------
    dialect = Step("dialect", "Flag GnuCOBOL vs IBM COBOL differences")
    risks: list[dict[str, Any]] = []
    with _Timer(dialect):
        if program is None:
            dialect.status = "skipped"
            dialect.summary = "Skipped: the program did not parse."
        else:
            from mockymock.analysis.dialect_risk import (
                BLOCKING_SEVERITIES,
                find_dialect_risks,
            )

            found = find_dialect_risks(
                program.ast, program.original_lines, program.line_map
            )
            risks = [r.to_dict() for r in found]
            blocking = [r for r in risks if r["severity"] in BLOCKING_SEVERITIES]
            for case in cases:
                reach = set(case["reach"])
                case["risks"] = [r for r in risks if r["paragraph"] in reach]
            for paragraph in paragraphs:
                paragraph["risks"] = sum(
                    1 for r in risks if r["paragraph"] == paragraph["name"]
                )
            dialect.summary = (
                f"{len(risks)} risk(s): {len(blocking)} high/medium, "
                f"{len(risks) - len(blocking)} low."
            )
            dialect.details = {"heuristic": True}
            if blocking:
                dialect.status = "warn"
    steps.append(dialect)

    # 11. Verdict ---------------------------------------------------------
    verdict = Step("verdict", "Decide what each test proves")
    mutation_ok = mutation_report is not None and mutation_passes
    with _Timer(verdict):
        for case in cases:
            if lint_problems:
                case["level"] = None
                case["levelReason"] = "The suite does not pass the static gate."
                continue
            case["level"] = "L0"
            case["levelReason"] = "Passes the static gate; not proven by a run."
            if case["status"] != "passed":
                if case["status"] in ("failed", "crashed"):
                    case["levelReason"] = "Failed in the GnuCOBOL run."
                continue
            case["level"] = "L1"
            case["levelReason"] = "Passed under GnuCOBOL."
            if case["assertions"]["total"] == 0:
                case[
                    "levelReason"
                ] += " It asserts nothing, so it only proves the paragraph runs."
                continue
            if not mutation_ok:
                case[
                    "levelReason"
                ] += " Mutation score below threshold or not measured."
                continue
            case["level"] = "L2"
            case["levelReason"] = "Passed and the suite kills mutants."
            blocking = [r for r in case["risks"] if r["severity"] in ("high", "medium")]
            if program is None or blocking:
                if blocking:
                    case["levelReason"] += (
                        f" Reaches {len(blocking)} dialect risk(s), so it is "
                        f"proven on GnuCOBOL only."
                    )
                continue
            case["level"] = "L3"
            case["levelReason"] = (
                "Passed, suite kills mutants, and no dialect risk is reachable. "
                "L4 needs the same test on z/OS."
            )
        counts = {
            level: sum(1 for c in cases if c["level"] == level) for level in LEVELS
        }
        counts["none"] = sum(1 for c in cases if c["level"] is None)
        verdict.details = {"levels": counts}
        verdict.summary = ", ".join(
            f"{level} {LEVEL_TITLES[level]}: {counts[level]}" for level in LEVELS
        )
    steps.append(verdict)

    findings = _findings(
        cases=cases,
        assertions=assertions,
        paragraphs=paragraphs,
        rules=rules,
        rules_available=rules_available,
        lint_problems=lint_problems,
        run_errors=run_errors,
        risks=risks,
        coverage=coverage_step.details if coverage_report else None,
        mutation=mutation_step.details if mutation_report else None,
        scenario_coverage=scenario_coverage,
        program_lines=program.original_lines if program else [],
    )
    verdict.summary += f". {len(findings)} finding(s)."

    journal_entries: list[dict[str, Any]] = []
    journal_problems: list[str] = []
    if options.journal is not None:
        from mockymock.report.journal import read_journal

        journal_entries, journal_problems = read_journal(options.journal)

    total_assertions = len(assertions)
    intent = sum(1 for a in assertions if a["label"] == "intent")
    return {
        "version": REPORT_VERSION,
        "generatedAt": _now(),
        "program": {
            "file": str(options.program),
            "name": flow.get("program_name") or options.program.stem,
            "lines": len(program.original_lines) if program else None,
            "copybookPaths": list(options.copybook_paths),
        },
        "cut": {
            "file": str(options.cut),
            "suite": suite.name if suite else None,
        },
        "steps": [s.to_dict() for s in steps],
        "paragraphs": paragraphs,
        "rules": rules,
        "rulesAvailable": rules_available,
        "analysis": analysis,
        "boundaries": boundaries,
        "cases": cases,
        "assertions": assertions,
        "dialectRisks": risks,
        "findings": findings,
        "journal": journal_entries,
        "journalProblems": journal_problems,
        "summary": {
            "cases": len(cases),
            "passed": sum(1 for c in cases if c["status"] == "passed"),
            "failed": sum(1 for c in cases if c["status"] in ("failed", "crashed")),
            "notRun": sum(1 for c in cases if c["status"] == "not_run"),
            # The run failed before its cases started (issue #260).
            "runFailed": bool(run_errors),
            "levels": verdict.details["levels"],
            "assertions": total_assertions,
            "intentShare": (
                round(100.0 * intent / total_assertions, 1)
                if total_assertions
                else None
            ),
            "coverage": (
                (coverage_step.details or {}).get("percentage")
                if coverage_report
                else None
            ),
            "mutationScore": (
                mutation_report.get("scorePercent") if mutation_report else None
            ),
            "mutationThreshold": options.mutation_threshold,
            "findings": {
                sev: sum(1 for f in findings if f["severity"] == sev)
                for sev in ("high", "medium", "low", "info")
            },
        },
    }


def _count(n: int, noun: str) -> str:
    """`1 branch`, `3 branches` -- instead of `branch(es)`."""
    if n == 1:
        return f"1 {noun}"
    plural = noun + ("es" if noun.endswith(("s", "sh", "ch", "x")) else "s")
    return f"{n} {plural}"


_ARM_PREFIX_RE = re.compile(r"^[A-Z-]+@\d+(?::\d+)?(?:/[A-Z0-9_#-]+)?:\s*")
# The scenario planner's miss reasons, as (pattern, plain sentence).
_ARM_REASONS = (
    (
        re.compile(r"field not boundary-fed:\s*(.+)$"),
        "it tests {0}, which no mocked file, call or database read sets",
    ),
    (
        re.compile(r"unresolvable EVALUATE subject:\s*(.+)$"),
        "it evaluates {0}, which the generator cannot set",
    ),
    (
        re.compile(r"unresolvable operand\(s\) in comparison:\s*(.+?)\s*/\s*(.+)$"),
        "it compares {0} with {1}, which the generator cannot set",
    ),
    (
        re.compile(
            r"comparison between two resolved fields not supported[^:]*:\s*(.+?)\s+vs\s+(.+)$"
        ),
        "it compares two fields ({0} and {1}), which the generator cannot pair up",
    ),
)


def _plain_arm_reason(reason: str | None) -> str:
    """The scenario planner's miss reason, minus its internal arm key
    (`IF@24/ELSE: `), with its one cryptic phrase spelled out."""
    if not reason:
        return "no reason given"
    text = _ARM_PREFIX_RE.sub("", reason)
    for pattern, sentence in _ARM_REASONS:
        match = pattern.match(text)
        if match:
            return sentence.format(*match.groups())
    return text


def _findings(  # noqa: C901
    *,
    cases: list[dict[str, Any]],
    assertions: list[dict[str, Any]],
    paragraphs: list[dict[str, Any]],
    rules: list[dict[str, Any]],
    rules_available: bool,
    lint_problems: list[str],
    run_errors: Sequence[str] = (),
    risks: list[dict[str, Any]],
    coverage: dict[str, Any] | None,
    mutation: dict[str, Any] | None,
    scenario_coverage: dict[str, Any] | None,
    program_lines: list[str],
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []

    def add(
        severity: str, category: str, title: str, detail: str = "", **extra: Any
    ) -> None:
        findings.append(
            {
                "severity": severity,
                "category": category,
                "title": title,
                "detail": detail,
                **extra,
            }
        )

    for problem in lint_problems:
        if not problem.startswith("  "):
            add("high", "refused", "The suite is refused before it can run", problem)

    for error in run_errors[:1]:
        add(
            "high",
            "run-failure",
            "The suite did not run: it failed before its test cases started",
            error.strip(),
        )

    label_by_line = {a["line"]: a for a in assertions}
    for case in cases:
        if case["status"] == "crashed":
            add(
                "high",
                "test-failure",
                f"“{case['name']}” crashed",
                case=case["name"],
                line=case["line"],
            )
        for failure in case["failures"]:
            assertion = label_by_line.get(failure.get("line"))
            expected, actual = failure.get("expected"), failure.get("actual")
            values = (
                f"expected {expected}, the program produced {actual}"
                if expected is not None
                else failure.get("message", "")
            )
            if assertion is not None and assertion["label"] == "intent":
                add(
                    "high",
                    "suspected-bug",
                    f"Possible program bug in “{case['name']}”",
                    f"{values}. The expected value comes from the program's intent "
                    f"({assertion['note'] or 'labelled INTENT'}), so the program, "
                    f"not the test, is the likelier culprit.",
                    case=case["name"],
                    line=failure.get("line"),
                )
            else:
                add(
                    "high",
                    "test-failure",
                    f"“{case['name']}” fails",
                    values,
                    case=case["name"],
                    line=failure.get("line"),
                )
        if case["status"] == "passed" and case["assertions"]["total"] == 0:
            add(
                "medium",
                "no-assertion",
                f"“{case['name']}” asserts nothing",
                "It passes as long as the paragraph runs. Add an EXPECT on what "
                "it writes or a VERIFY on what it calls.",
                case=case["name"],
                line=case["line"],
            )

    if mutation:
        for mutant in mutation.get("survivors") or []:
            line = mutant.get("line")
            if mutant.get("hint"):
                add(
                    "medium",
                    "untestable-mutant",
                    f"The test data cannot expose a change at line {line}",
                    f"{mutant.get('description') or mutant.get('operator')}: "
                    f"{mutant['hint']}",
                    line=line,
                )
                continue
            add(
                "medium",
                "missing-assertion",
                f"No test notices a change at line {line}",
                f"{mutant.get('description') or mutant.get('operator')}: "
                f"`{(mutant.get('original') or '').strip()}` became "
                f"`{(mutant.get('mutated') or '').strip()}` and every test still "
                f"passed.",
                line=line,
            )

    for p in paragraphs:
        if p["unreachable"]:
            add(
                "low",
                "dead-code",
                f"{p['name']} is never performed",
                "No test is needed; it is likely dead code worth removing.",
                line=p["line"],
            )
        elif not p["reachedBy"] and cases and not p.get("isLeadingSentences"):
            add(
                "medium",
                "untested-paragraph",
                f"No test reaches {p['name']}",
                "Add a TESTCASE that PERFORMs it (or a paragraph that performs it).",
                line=p["line"],
            )

    if rules_available:
        for rule in rules:
            if not rule["citedBy"]:
                add(
                    "low",
                    "rule-without-intent",
                    f"{rule['id']} ({rule['kind']} in {rule['procedure']}) has no intent assertion",
                    f"{rule['condition'] or ''}. Cite it in an `*> INTENT: {rule['id']} ...` "
                    f"label above the EXPECT that checks it.",
                    line=rule["line"],
                )

    unlabelled = [a for a in assertions if a["label"] is None]
    if unlabelled:
        add(
            "low",
            "unlabelled",
            (
                f"{_count(len(unlabelled), 'check')} "
                f"{'does' if len(unlabelled) == 1 else 'do'} not say where "
                "the expected value came from"
            ),
            "Label each with `*> INTENT: ...` (derived from a rule or the "
            "developer) or `*> CHARACTERIZATION: ...` (recorded from a run).",
        )

    for risk in risks:
        if risk["severity"] in ("high", "medium"):
            add(
                risk["severity"],
                "dialect",
                f"{risk['code'].replace('_', ' ').title()} at line {risk['line'] or '(copybook)'}",
                f"{risk['message']} ({risk['detail']})",
                line=risk["line"],
            )

    if coverage and coverage.get("uncoveredLines"):
        lines = coverage["uncoveredLines"]
        shown = ", ".join(str(n) for n in lines[:12])
        add(
            "low",
            "coverage",
            f"{len(lines)} executable line(s) never ran",
            f"Lines {shown}{'…' if len(lines) > 12 else ''}.",
        )

    if scenario_coverage:
        # "missed" here means the *automatic* generator alone could not
        # construct data for the arm -- not that no test reaches it. Cross
        # check each arm's real line against the suite's own line coverage
        # (when available) before calling it a gap: a hand-written case
        # (a MOVE before the PERFORM, or a mock body) routinely reaches an
        # arm this generator cannot drive on its own, and that is not
        # something to flag as unfinished.
        def _arm_line(arm: dict[str, Any]) -> int | None:
            origin = arm.get("origin") or {}
            if origin.get("line") is not None:
                return origin["line"]
            # No copybook expansion happened, so the arm_key's own line
            # already counts lines in this file -- see stamp_arm_origins.
            match = re.match(r".*@(\d+):", arm.get("arm_key") or "")
            return int(match.group(1)) if match else None

        def _describe_arm(arm: dict[str, Any], line: int | None) -> str:
            # "<PARAGRAPH> line N (ELSE arm)" instead of the raw
            # "PARAGRAPH@expanded-line:col/ARM" key, which is internal
            # bookkeeping syntax, not something to read off a line.
            arm_id = (arm.get("arm_key") or "").rsplit("/", 1)[-1] or "?"
            where = f"line {line}" if line is not None else "an unknown line"
            return f"{arm.get('parent_proc') or '?'} {where} ({arm_id} branch)"

        uncovered_lines = set((coverage or {}).get("uncoveredLines") or [])
        still_gap: list[tuple[dict[str, Any], int | None]] = []
        hand_covered: list[tuple[dict[str, Any], int | None]] = []
        for arm in scenario_coverage.get("details") or []:
            if arm.get("status") != "missed":
                continue
            arm_line = _arm_line(arm)
            if coverage and arm_line is not None and arm_line not in uncovered_lines:
                hand_covered.append((arm, arm_line))
            else:
                still_gap.append((arm, arm_line))

        # One finding for the whole suite: each listed arm is one line of
        # its detail, so a program with dozens of unreachable arms does
        # not bury the findings that need action.
        if still_gap:
            total = scenario_coverage.get("total_arms") or len(still_gap)
            items = [
                f"{_describe_arm(arm, line)}: {_plain_arm_reason(arm.get('reason'))}"
                for arm, line in still_gap
            ]
            shown = "; ".join(items[:8])
            more = f"; and {len(still_gap) - 8} more" if len(still_gap) > 8 else ""
            if coverage:
                title = (
                    f"{_count(len(still_gap), 'branch')} of {total} never ran: "
                    "no test reaches them and the automatic generator cannot either"
                )
            else:
                # Without a coverage run there is no telling whether the
                # suite's own cases reach these arms -- say so instead of
                # claiming they are untested.
                title = (
                    f"The automatic generator cannot reach "
                    f"{_count(len(still_gap), 'branch')} of {total}; "
                    "run with coverage to see whether your tests do"
                )
            add(
                "info",
                "scenario-gap",
                title,
                f"{shown}{more}. Set these branches up by hand in the test case "
                "(MOVE before the PERFORM, or a mock body).",
                items=items,
            )
        if hand_covered and coverage:
            items = [_describe_arm(arm, line) for arm, line in hand_covered]
            shown = "; ".join(items[:8])
            more = (
                f"; and {len(hand_covered) - 8} more" if len(hand_covered) > 8 else ""
            )
            add(
                "info",
                "scenario-gap-covered-by-hand",
                f"{_count(len(hand_covered), 'branch')} the automatic generator "
                "can't reach are covered by your own test cases",
                f"{shown}{more}. Nothing to do here -- listed so the count "
                "above doesn't read as unfinished work.",
                items=items,
            )

    findings.sort(key=lambda f: (_SEVERITY_RANK[f["severity"]], f.get("line") or 0))
    return findings
