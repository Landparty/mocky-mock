"""Render a `mockymock report` document (report/test_report.py) as one
self-contained HTML page: inline CSS, a few lines of inline JS for the
case filter, no network fetches, so it opens from disk, from a CI
artifact, or behind an air gap. Every value from the program, the `.cut`
or a tool's output goes through `html.escape`.
"""

from __future__ import annotations

import html
import json
from typing import Any

from mockymock.report.test_report import LEVEL_TITLES, LEVELS

_STEP_TITLES_NOTE = {
    "ok": "Done",
    "warn": "Needs attention",
    "fail": "Failed",
    "skipped": "Skipped",
    "info": "Note",
}

_CSS = """
/* Layout: one reading column; summary strip, then findings, cases, steps, reference tables. */
:root {
  --bg: #f4f5f8; --surface: #ffffff; --raised: #eceef4; --line: #d9dce6;
  --fg: #1b1f2a; --muted: #5b6273; --accent: #3346b8; --accent-soft: #e3e7fb;
  --ok: #1d7a46; --ok-soft: #e1f3e8; --warn: #9a6100; --warn-soft: #fbefd9;
  --bad: #b3261e; --bad-soft: #fbe3e1; --info: #4b5563; --info-soft: #eceef4;
  --l0: #c7cbe0; --l1: #8f9be0; --l2: #5a6ad0; --l3: #2f3fa8;
  --font-body: "Segoe UI", system-ui, -apple-system, "Helvetica Neue", Arial, sans-serif;
  --font-mono: ui-monospace, "Cascadia Mono", "SFMono-Regular", Menlo, Consolas, monospace;
}
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  --bg: #11141b; --surface: #181c25; --raised: #202532; --line: #2c3242;
  --fg: #e6e8ee; --muted: #9aa1b3; --accent: #93a2ff; --accent-soft: #252c4d;
  --ok: #6fd39a; --ok-soft: #173326; --warn: #f0b860; --warn-soft: #3a2c12;
  --bad: #ff8a80; --bad-soft: #3d1c1a; --info: #aab1c2; --info-soft: #232836;
  --l0: #3a405a; --l1: #56619e; --l2: #7684dc; --l3: #a9b4ff; color-scheme: dark; } }
:root[data-theme="dark"] {
  --bg: #11141b; --surface: #181c25; --raised: #202532; --line: #2c3242;
  --fg: #e6e8ee; --muted: #9aa1b3; --accent: #93a2ff; --accent-soft: #252c4d;
  --ok: #6fd39a; --ok-soft: #173326; --warn: #f0b860; --warn-soft: #3a2c12;
  --bad: #ff8a80; --bad-soft: #3d1c1a; --info: #aab1c2; --info-soft: #232836;
  --l0: #3a405a; --l1: #56619e; --l2: #7684dc; --l3: #a9b4ff; color-scheme: dark; }
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--fg); font: 15px/1.55 var(--font-body); }
.wrap { max-width: 1120px; margin: 0 auto; padding-inline: 16px; padding-block: 28px 64px; display: grid; grid-template-columns: minmax(0, 1fr); gap: 36px; }
.wrap > * { min-width: 0; }
header, .tile, .entry > * { overflow-wrap: anywhere; min-width: 0; }
header { display: grid; gap: 6px; }
.eyebrow { font: 600 12px/1 var(--font-body); letter-spacing: .08em; text-transform: uppercase; color: var(--muted); }
h1 { margin: 0; font-size: 30px; line-height: 1.2; text-wrap: balance; }
h1 code { font-family: var(--font-mono); font-size: 0.92em; }
h2 { margin: 0 0 12px; font-size: 19px; text-wrap: balance; }
.lede { margin: 4px 0 0; color: var(--muted); max-width: 72ch; }
code, .mono { font-family: var(--font-mono); font-size: 0.88em; }
.meta { display: flex; flex-wrap: wrap; gap: 6px 18px; color: var(--muted); font-size: 13px; }
.strip { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(140px, 100%), 1fr)); gap: 12px; }
.tile { background: var(--surface); border: 1px solid var(--line); border-radius: 8px; padding: 14px 16px; display: grid; gap: 4px; align-content: start; }
.tile .label { font-size: 12px; color: var(--muted); letter-spacing: .04em; text-transform: uppercase; }
.tile .value { font-size: 26px; font-weight: 650; font-variant-numeric: tabular-nums; }
.tile .sub { font-size: 13px; color: var(--muted); }
.ladder { display: flex; height: 10px; border-radius: 5px; overflow: hidden; background: var(--raised); margin-top: 6px; }
.ladder span { display: block; height: 100%; }
.legend { display: flex; flex-wrap: wrap; gap: 4px 12px; font-size: 12px; color: var(--muted); }
.legend i { display: inline-block; width: 9px; height: 9px; border-radius: 2px; margin-right: 4px; vertical-align: -1px; }
.findings { display: grid; gap: 8px; }
.finding { display: grid; grid-template-columns: 6px 1fr; background: var(--surface); border: 1px solid var(--line); border-radius: 8px; overflow: hidden; }
.finding .stripe { background: var(--info); }
.finding.high .stripe { background: var(--bad); }
.finding.medium .stripe { background: var(--warn); }
.finding.low .stripe { background: var(--l1); }
.finding .body { padding: 10px 14px; display: grid; gap: 2px; min-width: 0; }
.finding .title { font-weight: 600; }
.finding .detail { color: var(--muted); font-size: 14px; overflow-wrap: anywhere; }
.finding .tags { display: flex; flex-wrap: wrap; gap: 6px; font-size: 12px; color: var(--muted); }
.finding .tags .tag { display: inline-flex; align-items: center; padding: 1px 7px; border-radius: 5px; background: var(--raised); border: 1px solid var(--line); white-space: nowrap; }
.finding .tags code.tag { font-family: var(--font-mono); }
.pill { display: inline-flex; align-items: center; gap: 4px; padding: 1px 8px; border-radius: 999px; font-size: 12px; font-weight: 600; white-space: nowrap; }
.pill.ok { background: var(--ok-soft); color: var(--ok); }
.pill.warn { background: var(--warn-soft); color: var(--warn); }
.pill.fail, .pill.bad, .pill.high { background: var(--bad-soft); color: var(--bad); }
.pill.medium { background: var(--warn-soft); color: var(--warn); }
.pill.skipped, .pill.info, .pill.low, .pill.not_run { background: var(--info-soft); color: var(--info); }
.pill.passed { background: var(--ok-soft); color: var(--ok); }
.pill.failed, .pill.crashed { background: var(--bad-soft); color: var(--bad); }
.level { display: inline-block; min-width: 2.4em; text-align: center; padding: 1px 6px; border-radius: 4px; font: 600 12px/1.6 var(--font-mono); color: #fff; }
.level.L0 { background: var(--l0); color: var(--fg); }
.level.L1 { background: var(--l1); }
.level.L2 { background: var(--l2); }
.level.L3 { background: var(--l3); color: var(--bg); }
.level.none { background: var(--bad-soft); color: var(--bad); }
.table-wrap { overflow-x: auto; background: var(--surface); border: 1px solid var(--line); border-radius: 8px; }
table { width: 100%; min-width: 640px; border-collapse: collapse; font-size: 14px; }
th, td { text-align: left; padding: 9px 12px; border-bottom: 1px solid var(--line); vertical-align: top; }
th { font-size: 12px; font-weight: 600; color: var(--muted); letter-spacing: .04em; text-transform: uppercase; background: var(--raised); }
tr:last-child td { border-bottom: 0; }
td.num { font-variant-numeric: tabular-nums; text-align: right; }
td .why { color: var(--muted); font-size: 13px; }
.filters { display: flex; flex-wrap: wrap; gap: 8px; margin: 0 0 10px; }
.filters button { font: inherit; font-size: 13px; padding: 4px 12px; border-radius: 999px; border: 1px solid var(--line); background: var(--surface); color: var(--fg); cursor: pointer; }
.filters button[aria-pressed="true"] { background: var(--accent-soft); border-color: var(--accent); color: var(--accent); }
.filters button:focus-visible, summary:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
ol.steps { list-style: none; margin: 0; padding: 0; display: grid; gap: 8px; counter-reset: step; }
ol.steps > li { counter-increment: step; }
details { background: var(--surface); border: 1px solid var(--line); border-radius: 8px; }
details > summary { cursor: pointer; list-style: none; display: grid; grid-template-columns: 2.2em 1fr auto; gap: 10px; align-items: baseline; padding: 11px 14px; }
details > summary::-webkit-details-marker { display: none; }
ol.steps summary::before { content: counter(step); font: 600 13px var(--font-mono); color: var(--muted); }
details > summary .s-title { font-weight: 600; }
details > summary .s-sum { display: block; font-weight: 400; color: var(--muted); font-size: 14px; }
details .inner { padding: 0 14px 14px 14px; display: grid; gap: 10px; min-width: 0; }
pre { margin: 0; padding: 10px 12px; background: var(--raised); border-radius: 6px; overflow-x: auto; font: 12.5px/1.5 var(--font-mono); white-space: pre; }
.kv { display: grid; grid-template-columns: max-content 1fr; gap: 4px 14px; font-size: 13px; }
.kv dt { color: var(--muted); }
.kv dd { margin: 0; min-width: 0; overflow-wrap: anywhere; }
.empty { color: var(--muted); font-style: italic; }
.journal { display: grid; gap: 8px; }
.entry { display: grid; grid-template-columns: 9.5em 1fr; gap: 12px; background: var(--surface); border: 1px solid var(--line); border-radius: 8px; padding: 10px 14px; }
.entry time { color: var(--muted); font: 12px/1.6 var(--font-mono); }
.entry .decision { color: var(--muted); font-size: 14px; }
.levels-note { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 10px; font-size: 13px; color: var(--muted); }
.levels-note div { display: grid; gap: 4px; }
footer { color: var(--muted); font-size: 12px; }
.intro { margin: -4px 0 12px; color: var(--muted); font-size: 14px; max-width: 80ch; }
.intro a, .toc a { color: var(--accent); }
.toc { display: flex; flex-wrap: wrap; gap: 4px 14px; margin-top: 8px; font-size: 13px; }
.toc a { text-decoration: none; }
.toc a:hover { text-decoration: underline; }
ol.next { margin: 0; padding: 0; list-style: none; counter-reset: next; display: grid; gap: 8px; }
ol.next li { counter-increment: next; display: grid; grid-template-columns: 2em 1fr; column-gap: 10px; background: var(--surface); border: 1px solid var(--line); border-left: 4px solid var(--accent); border-radius: 8px; padding: 10px 14px; }
ol.next li::before { content: counter(next); grid-row: span 2; font: 700 18px/1.2 var(--font-mono); color: var(--accent); }
ol.next li span { color: var(--muted); font-size: 14px; overflow-wrap: anywhere; }
.next.ok { background: var(--ok-soft); color: var(--fg); border-radius: 8px; padding: 12px 14px; }
ul.names { margin: 0; padding-left: 1.1em; font-size: 13px; }
.muted { color: var(--muted); }
.finding ul.detail { margin: 2px 0; padding-left: 18px; }
.finding .todo { font-size: 14px; }
td.nowrap { white-space: nowrap; }
.warn-text { color: var(--warn); font-weight: 600; }
.bad-text { color: var(--bad); }
dl.glossary { display: grid; grid-template-columns: minmax(10em, max-content) 1fr; gap: 6px 18px; margin: 0; font-size: 14px; }
dl.glossary dt { font-weight: 600; }
dl.glossary dd { margin: 0; color: var(--muted); }
@media (max-width: 560px) { dl.glossary { grid-template-columns: 1fr; } dl.glossary dd { margin-bottom: 6px; } }
h3 { margin: 18px 0 8px; font-size: 15px; }
.inner h3 { margin: 8px 0 6px; }
.analysis { display: grid; gap: 8px; }
details.sub > summary { grid-template-columns: 1fr auto; }
details.sub > summary h3 { display: inline; margin: 0; font-size: 15px; }
details.sub > summary::after { content: "▸"; color: var(--muted); }
details.sub[open] > summary::after { content: "▾"; }
.note { color: var(--muted); font-size: 13px; margin: 6px 0 0; }
.grade { display: inline-flex; align-items: center; justify-content: center; width: 1.6em; height: 1.6em; border-radius: 6px; font-weight: 700; color: var(--bg); }
.grade.A, .grade.B { background: var(--ok); }
.grade.C { background: var(--warn); }
.grade.D, .grade.F { background: var(--bad); }
.health { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(200px, 100%), 1fr)); gap: 10px; }
.bar { height: 6px; border-radius: 3px; background: var(--raised); overflow: hidden; }
.bar span { display: block; height: 100%; background: var(--warn); }
.graph { overflow-x: auto; background: var(--surface); border: 1px solid var(--line); border-radius: 8px; padding: 8px; }
.graph svg { display: block; font: 12px var(--font-mono); }
.graph .n rect { fill: var(--raised); stroke: var(--line); stroke-width: 1.5; }
.graph .n.ok rect { stroke: var(--ok); }
.graph .n.untested rect { stroke: var(--warn); }
.graph .n.dead rect { stroke: var(--muted); stroke-dasharray: 4 3; }
.graph .n.ext rect { fill: var(--accent-soft); stroke: var(--accent); }
.graph .n.entry rect { stroke-width: 3; }
.graph .n text { fill: var(--fg); }
.graph path { fill: none; stroke: var(--muted); stroke-width: 1.3; }
.graph path.goto { stroke: var(--bad); stroke-dasharray: 5 3; }
.graph path.call { stroke: var(--accent); }
.graph marker path { fill: var(--muted); stroke: none; }
@media (max-width: 560px) {
  h1 { font-size: 24px; }
  .entry { grid-template-columns: 1fr; gap: 4px; }
  details > summary { grid-template-columns: 1.6em 1fr; }
  details > summary .pill { grid-column: 2; justify-self: start; }
}
@media (prefers-reduced-motion: reduce) { * { transition: none !important; } }
"""

_JS = """
(function () {
  var buttons = document.querySelectorAll('[data-filter]');
  var rows = document.querySelectorAll('#cases tbody tr');
  buttons.forEach(function (button) {
    button.addEventListener('click', function () {
      var wanted = button.getAttribute('data-filter');
      buttons.forEach(function (b) { b.setAttribute('aria-pressed', String(b === button)); });
      rows.forEach(function (row) {
        var match = wanted === 'all' || row.getAttribute('data-status') === wanted ||
          row.getAttribute('data-level') === wanted;
        row.hidden = !match;
      });
    });
  });
})();
"""

_LEVEL_DESCRIPTIONS = {
    "L0": "Passes the static gate: every reachable CALL, file, SQL, CICS, DL/I and ACCEPT is mocked.",
    "L1": "Passed in a real GnuCOBOL compile and run.",
    "L2": "Asserts something, and the suite's mutation score meets the threshold.",
    "L3": "No high or medium GnuCOBOL vs IBM COBOL risk is reachable from it.",
    "L4": "Not computed here: needs the same test run on z/OS (mockymock export).",
}


_L4_BADGE = '<span class="level L0" title="Mainframe-confirmed">L4</span>'


def _e(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _pill(status: str, text: str | None = None) -> str:
    return (
        f'<span class="pill {_e(status)}">{_e(text or status.replace("_", " "))}</span>'
    )


def _level(level: str | None) -> str:
    if level is None:
        return '<span class="level none" title="Refused">—</span>'
    return f'<span class="level {_e(level)}" title="{_e(LEVEL_TITLES[level])}">{_e(level)}</span>'


def _tile(
    label: str, value: str, sub: str = "", extra: str = "", title: str = ""
) -> str:
    tip = f' title="{_e(title)}"' if title else ""
    return (
        f'<div class="tile"{tip}><span class="label">{_e(label)}</span>'
        f'<span class="value">{value}</span>'
        + (f'<span class="sub">{sub}</span>' if sub else "")
        + extra
        + "</div>"
    )


_SEVERITY_LABEL = {
    "high": "Fix first",
    "medium": "Should fix",
    "low": "Worth a look",
    "info": "For information",
}

# The finding categories in plain words. The machine name stays in the
# JSON and in the tag's tooltip; the reader sees this.
_CATEGORY_LABEL = {
    "refused": "Suite refused",
    "test-failure": "Failing test",
    "suspected-bug": "Possible program bug",
    "no-assertion": "Test checks nothing",
    "missing-assertion": "Change no test notices",
    "untestable-mutant": "Change the test data hides",
    "dead-code": "Code never run",
    "untested-paragraph": "Paragraph no test reaches",
    "rule-without-intent": "Rule no test checks",
    "unlabelled": "Checks without a stated reason",
    "dialect": "Mainframe difference",
    "coverage": "Lines never run",
    "scenario-gap": "Branches to set up by hand",
    "scenario-gap-covered-by-hand": "Branches your tests already cover",
}

# What to do about each category, in one imperative sentence. Shown in the
# "What to do next" box, so the reader does not have to work it out from
# the finding's detail.
_ADVICE = {
    "refused": "Mock the boundary it names, then run `mockymock lint` again.",
    "test-failure": "Open the test case and compare the expected and actual values.",
    "suspected-bug": (
        "Check the program against the business rule: the test follows the "
        "rule, so the program is the likelier culprit."
    ),
    "no-assertion": "Add an EXPECT on a field the paragraph writes.",
    "missing-assertion": "Add an EXPECT that would fail if that line changed.",
    "untestable-mutant": "Start a test case with a non-zero value in that field.",
    "dead-code": "Confirm nothing calls it, then consider removing it.",
    "untested-paragraph": "Add a TESTCASE that PERFORMs it.",
    "rule-without-intent": (
        "Put an `*> INTENT: BR-nnn ...` label above the EXPECT that checks the rule."
    ),
    "unlabelled": (
        "Put `*> INTENT: ...` (from a rule or the developer) or "
        "`*> CHARACTERIZATION: ...` (recorded from a run) above each check."
    ),
    "dialect": "Re-run this test on z/OS before trusting it there.",
    "coverage": "Add test cases that reach those lines.",
    "scenario-gap": (
        "Write a test case that MOVEs the tested value before its PERFORM, "
        "or sets it in a mock body."
    ),
}

_EVIDENCE_DETAIL = frozenset(
    {
        "test-failure",
        "suspected-bug",
        "missing-assertion",
        "untestable-mutant",
        "dialect",
        "coverage",
        "refused",
    }
)

_GLOSSARY = (
    (
        "Test case",
        "One TESTCASE in the .cut file: it PERFORMs a paragraph with mocked inputs and checks the result.",
    ),
    (
        "Check (EXPECT / VERIFY)",
        "EXPECT compares a field with a value; VERIFY counts how often a mocked CALL, file or database statement ran.",
    ),
    (
        "Intent",
        "A check whose expected value comes from a business rule or the developer (`*> INTENT:`). If it fails, the program is probably wrong.",
    ),
    (
        "Recorded (characterization)",
        "A check whose expected value was copied from what the program did on a run (`*> CHARACTERIZATION:`). It pins today's behaviour; it does not prove it right.",
    ),
    (
        "Boundary",
        "A statement where the program reaches outside itself: a CALL, a file operation, SQL, CICS, IMS DL/I or console ACCEPT. Each one a test reaches needs a MOCK.",
    ),
    (
        "Mock",
        "A stand-in for a CALL, file, SQL, CICS or DL/I statement, so the test runs without the real system.",
    ),
    (
        "Line coverage",
        "The share of the program's executable lines that ran during the tests.",
    ),
    (
        "Mutation score",
        "mockymock changes the program one small way at a time (a + becomes -, a MOVE is removed) and re-runs the tests. The score is the share of those changes a test noticed.",
    ),
    (
        "Verification level",
        "L0 to L4: how much a test case proves, from 'passes the static checks' to 'confirmed on the mainframe'. See Verification levels.",
    ),
    (
        "Mainframe difference",
        "Something GnuCOBOL (where these tests run) may do differently from IBM Enterprise COBOL, such as rounding or comparing mixed data.",
    ),
    ("Branch", "One way through an IF or EVALUATE (its THEN, its ELSE, each WHEN)."),
    (
        "Cyclomatic complexity",
        "The number of independent paths through a paragraph. Each path needs its own test case; above 10 is hard to test fully.",
    ),
    (
        "Technical debt",
        "cobol-parser's 0 to 100 estimate of how hard the program is to change safely (0 is best), from complexity, duplicates, dead code, GO TO use and size.",
    ),
    (
        "Lint",
        "Automatic checks for common COBOL problems: unused fields, unreachable code, risky MOVEs, unchecked SQLCODEs and more.",
    ),
)


def _plural(n: int, noun: str, plural: str | None = None) -> str:
    return f"{n} {noun if n == 1 else (plural or noun + 's')}"


def _summary_strip(report: dict[str, Any]) -> str:
    s = report["summary"]
    cases = s["cases"]
    levels = s["levels"]
    ladder = "".join(
        f'<span style="width:{100 * levels.get(level, 0) / cases:.2f}%;background:var(--{level.lower()})" '
        f'title="{_e(level)}: {levels.get(level, 0)}"></span>'
        for level in LEVELS
        if cases
    )
    legend = "".join(
        f'<span><i style="background:var(--{level.lower()})"></i>{level} {levels.get(level, 0)}</span>'
        for level in LEVELS
    )
    if s["notRun"] == cases and cases:
        passed_sub = "not run yet"
    else:
        passed_sub = f"{s['failed']} failed, {s['notRun']} not run"
    coverage = "—" if s["coverage"] is None else f"{s['coverage']:.0f}%"
    mutation = "—" if s["mutationScore"] is None else f"{s['mutationScore']:g}%"
    intent = "—" if s["intentShare"] is None else f"{s['intentShare']:.0f}%"
    f = s["findings"]
    urgent = f["high"] + f["medium"]
    health_tile = ""
    analysis = report.get("analysis") or {}
    health = analysis.get("health") if analysis.get("available") else None
    if health:
        health_tile = _tile(
            "Code health",
            f'<span class="grade {_e(health["grade"])}">{_e(health["grade"])}</span>',
            "A is easy to change safely, F is hard",
            title="cobol-parser's technical-debt grade for the program itself",
        )
    return (
        '<section class="strip" aria-label="Summary">'
        + _tile(
            "Tests passing",
            f"{s['passed']}/{cases}",
            _e(passed_sub),
            title="Test cases that passed in a real GnuCOBOL run",
        )
        + _tile(
            "Strongly verified",
            f"{levels.get('L3', 0) + levels.get('L2', 0)}/{cases}",
            "pass, check something, and catch planted bugs (level L2+)",
            f'<div class="ladder">{ladder}</div><div class="legend">{legend}</div>',
            title="Test cases at verification level L2 or L3",
        )
        + _tile(
            "Checks with a reason",
            intent,
            f"of {_plural(s['assertions'], 'check')} cite a rule or the developer",
            title="Share of EXPECT/VERIFY lines labelled INTENT",
        )
        + _tile(
            "Code run by tests",
            coverage,
            "of the program's executable lines",
            title="Line coverage of the original .cbl",
        )
        + _tile(
            "Planted bugs caught",
            mutation,
            f"aim for {s['mutationThreshold']:.0f}% or more",
            title="Mutation score: small deliberate changes a test noticed",
        )
        + _tile(
            "Issues to fix",
            str(urgent),
            f"{f['low']} worth a look · {f['info']} for information",
            title="Findings marked 'Fix first' or 'Should fix'",
        )
        + health_tile
        + "</section>"
    )


def _verdict_sentence(report: dict[str, Any]) -> str:
    s = report["summary"]
    if s["levels"].get("none"):
        return (
            "The suite is refused by the static checks, so none of its tests can "
            "run yet. Fix the issues marked “Fix first” below."
        )
    if s["notRun"] == s["cases"]:
        return (
            f"The {_plural(s['cases'], 'test')} pass the static checks but "
            "the suite has not been run here, so no test is proven by execution yet."
        )
    parts = [f"{s['passed']} of {s['cases']} tests pass under GnuCOBOL"]
    high = s["findings"]["high"]
    if high:
        parts.append(f"{_plural(high, 'issue')} need fixing first")
    top = max((lvl for lvl in LEVELS if s["levels"].get(lvl)), default=None)
    if top:
        parts.append(
            f"the strongest proof reached is {top} ({LEVEL_TITLES[top].lower()})"
        )
    return "; ".join(parts) + "."


def _next_steps(report: dict[str, Any]) -> str:
    """At most five actions, most important first: the unrun steps that
    would unlock stronger proof, then one line per kind of urgent finding."""
    steps: list[tuple[str, str]] = []
    program = report["program"]["file"]
    cut = report["cut"]["file"]
    by_id = {s["id"]: s for s in report["steps"]}
    seen: set[str] = set()
    for finding in report["findings"]:
        category = finding["category"]
        if finding["severity"] != "high" or category in seen:
            continue
        seen.add(category)
        steps.append(
            (finding["title"], _ADVICE.get(category, finding.get("detail", "")))
        )
    refused = bool(report["summary"]["levels"].get("none"))
    run_skipped = by_id.get("run", {}).get("status") == "skipped" and not refused
    mutation_skipped = (
        by_id.get("mutation", {}).get("status") == "skipped" and not refused
    )
    if run_skipped or mutation_skipped:
        flags = " ".join(
            flag
            for flag, wanted in (
                ("--execute", run_skipped),
                ("--mutate", mutation_skipped),
            )
            if wanted
        )
        steps.append(
            (
                "Run the tests to prove them",
                f"`mockymock report {program} --cut {cut} {flags}` compiles and runs "
                "the suite under GnuCOBOL (needs Docker). Until then every test "
                "stays at L0.",
            )
        )
    for finding in report["findings"]:
        category = finding["category"]
        if finding["severity"] != "medium" or category in seen:
            continue
        seen.add(category)
        count = sum(1 for f in report["findings"] if f["category"] == category)
        title = (
            finding["title"]
            if count == 1
            else (f"{_CATEGORY_LABEL.get(category, category)} ({count})")
        )
        steps.append((title, _ADVICE.get(category, finding.get("detail", ""))))
    for finding in report["findings"]:
        category = finding["category"]
        if finding["severity"] != "low" or category in seen or len(steps) >= 5:
            continue
        seen.add(category)
        steps.append(
            (finding["title"], _ADVICE.get(category, finding.get("detail", "")))
        )
    if not steps:
        return (
            '<div class="next ok"><strong>Nothing urgent.</strong> The suite runs, '
            "checks what it should and catches planted bugs. The remaining step "
            "is running the same tests on z/OS (level L4, <code>mockymock export</code>).</div>"
        )
    items = "".join(
        f"<li><strong>{_e(title)}</strong><span>{_md_code(advice)}</span></li>"
        for title, advice in steps[:5]
    )
    return f'<ol class="next">{items}</ol>'


def _md_code(text: str) -> str:
    """Escape `text`, then turn `backtick` spans into <code>."""
    parts = _e(text).split("`")
    return "".join(
        f"<code>{part}</code>" if i % 2 else part for i, part in enumerate(parts)
    )


def _grouped(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fold findings that share a severity, category and title into one
    card listing each distinct detail -- the static gate reports the same
    unmocked statement once per test case that reaches it, and fourteen
    identical cards bury everything after them."""
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for f in findings:
        groups.setdefault((f["severity"], f["category"], f["title"]), []).append(f)
    out = []
    for members in groups.values():
        if len(members) == 1:
            out.append(members[0])
            continue
        details: list[str] = []
        for m in members:
            for text in m.get("items") or [m.get("detail") or ""]:
                if text and text not in details:
                    details.append(text)
        merged = dict(members[0])
        merged.pop("line", None)
        merged.pop("case", None)
        merged["items"] = details
        if len(details) > 1:
            merged["title"] = f"{merged['title']} ({len(details)} reasons)"
        elif details:
            merged["items"] = []
            merged["detail"] = details[0]
        out.append(merged)
    return out


def _findings(report: dict[str, Any]) -> str:
    items = report["findings"]
    if not items:
        return '<p class="empty">No issues found.</p>'
    out = []
    for f in _grouped(items):
        category = f["category"]
        tags = [
            _pill(f["severity"], _SEVERITY_LABEL.get(f["severity"], f["severity"])),
            f'<span class="tag" title="{_e(category)}">'
            f"{_e(_CATEGORY_LABEL.get(category, category))}</span>",
        ]
        # The title already says "at line N" for every category that sets
        # one (missing-assertion, dialect) -- repeating it as a bare tag
        # reads as a second, disconnected fact instead of the same one.
        if f.get("line") and f"line {f['line']}" not in f.get("title", ""):
            tags.append(f'<span class="tag">line {_e(f["line"])}</span>')
        if f.get("case"):
            tags.append(f'<span class="tag">test “{_e(f["case"])}”</span>')
        if f.get("items"):
            shown = f["items"][:12]
            more = (
                f"<li>… and {len(f['items']) - 12} more</li>"
                if len(f["items"]) > 12
                else ""
            )
            body = (
                '<ul class="detail">'
                + "".join(f"<li>{_e(item)}</li>" for item in shown)
                + more
                + "</ul>"
            )
        elif f.get("detail"):
            body = f'<div class="detail">{_md_code(f["detail"])}</div>'
        else:
            body = ""
        # Some details already end in the advice; only add a "What to do"
        # line where the detail is evidence (values, a mutant, a risk).
        advice = (
            _ADVICE.get(category)
            if category in _EVIDENCE_DETAIL or not f.get("detail")
            else None
        )
        if f["severity"] == "info":
            advice = None
        todo = (
            f'<div class="todo">What to do: {_md_code(advice)}</div>' if advice else ""
        )
        out.append(
            f'<article class="finding {_e(f["severity"])}"><div class="stripe"></div>'
            f'<div class="body"><div class="title">{_e(f["title"])}</div>'
            f'{body}{todo}<div class="tags">{"".join(tags)}</div></div></article>'
        )
    return f'<div class="findings">{"".join(out)}</div>'


def _checks(a: dict[str, int]) -> str:
    if not a["total"]:
        return '<span class="warn-text">none</span>'
    parts = [
        f"{a['intent']} from rules" if a["intent"] else "",
        f"{a['characterization']} recorded" if a["characterization"] else "",
        f"{a['unlabelled']} no reason" if a["unlabelled"] else "",
    ]
    return _e(" · ".join(p for p in parts if p))


def _cases(report: dict[str, Any]) -> str:
    cases = report["cases"]
    if not cases:
        return '<p class="empty">The .cut file holds no test cases.</p>'
    filters = [
        '<button type="button" data-filter="all" aria-pressed="true">All</button>'
    ]
    for status in ("passed", "failed", "not_run"):
        if any(c["status"] == status for c in cases):
            filters.append(
                f'<button type="button" data-filter="{status}" aria-pressed="false">{status.replace("_", " ").capitalize()}</button>'
            )
    for level in LEVELS:
        if any(c["level"] == level for c in cases):
            filters.append(
                f'<button type="button" data-filter="{level}" aria-pressed="false">{level}</button>'
            )
    rows = []
    for c in cases:
        risks = [r for r in c["risks"] if r["severity"] in ("high", "medium")]
        failures = "".join(
            f'<div class="why bad-text">✗ line {_e(fl.get("line"))}: {_e(fl.get("message"))}</div>'
            for fl in c["failures"]
        )
        target = c["perform"] + (
            f" THRU {c['performThru']}" if c["performThru"] else ""
        )
        rows.append(
            f'<tr data-status="{_e(c["status"])}" data-level="{_e(c["level"] or "none")}">'
            f"<td>{_level(c['level'])}</td>"
            f"<td><strong>{_e(c['name'])}</strong>"
            f'<div class="why">{_e(c["levelReason"])}</div>{failures}</td>'
            f"<td>{_pill(c['status'])}</td>"
            f"<td><code>{_e(target)}</code></td>"
            f'<td class="nowrap">{_checks(c["assertions"])}</td>'
            f'<td class="num">{len(risks) or "—"}</td></tr>'
        )
    return (
        '<p class="intro">Each row is one TESTCASE. The level says how much it proves '
        '(<a href="#h-levels">what the levels mean</a>); the line under its name says '
        "why it stopped there.</p>"
        f'<div class="filters" role="group" aria-label="Filter test cases">{"".join(filters)}</div>'
        '<div class="table-wrap"><table id="cases"><thead><tr>'
        "<th>Level</th><th>Test case</th><th>Result</th><th>Runs paragraph</th>"
        '<th>Checks</th><th class="num" title="High or medium GnuCOBOL vs IBM COBOL differences this test reaches">Mainframe risks</th>'
        f'</tr></thead><tbody>{"".join(rows)}</tbody></table></div>'
    )


def _step_details(step: dict[str, Any]) -> str:
    details = step.get("details") or {}
    parts = []
    if step.get("command"):
        parts.append(f"<pre>$ {_e(step['command'])}</pre>")
    simple = {
        k: v
        for k, v in details.items()
        if isinstance(v, (str, int, float, bool)) and k != "output"
    }
    if simple:
        parts.append(
            '<dl class="kv">'
            + "".join(f"<dt>{_e(k)}</dt><dd>{_e(v)}</dd>" for k, v in simple.items())
            + "</dl>"
        )
    problems = details.get("problems")
    if problems:
        parts.append(f"<pre>{_e(chr(10).join(problems))}</pre>")
    if details.get("output"):
        parts.append(f"<pre>{_e(details['output'])}</pre>")
    complex_ = {
        k: v
        for k, v in details.items()
        if not isinstance(v, (str, int, float, bool)) and k not in ("problems",) and v
    }
    if complex_:
        parts.append(
            f"<pre>{_e(json.dumps(complex_, indent=2, ensure_ascii=False, default=str))}</pre>"
        )
    parts.append(f'<div class="why">Took {step.get("durationMs", 0)} ms.</div>')
    return "".join(parts)


def _steps(report: dict[str, Any]) -> str:
    items = []
    for step in report["steps"]:
        status = step["status"]
        items.append(
            f"<li><details><summary><span><span class=\"s-title\">{_e(step['title'])}</span>"
            f"<span class=\"s-sum\">{_e(step['summary'])}</span></span>"
            f"{_pill(status, _STEP_TITLES_NOTE.get(status, status))}</summary>"
            f'<div class="inner">{_step_details(step)}</div></details></li>'
        )
    return f'<ol class="steps">{"".join(items)}</ol>'


def _paragraphs(report: dict[str, Any]) -> str:
    paragraphs = report["paragraphs"]
    if not paragraphs:
        return '<p class="empty">The program did not parse, so no paragraphs are listed.</p>'
    rows = []
    for p in paragraphs:
        if p["unreachable"]:
            state = _pill("info", "never performed")
        elif p["testedBy"]:
            state = _pill("ok", f"tested directly ×{len(p['testedBy'])}")
        elif p["reachedBy"]:
            state = _pill("ok", "reached by a test")
        elif p.get("isLeadingSentences"):
            state = _pill("info", "not a PERFORM target (leading sentences)")
        else:
            state = _pill("warn", "no test reaches it")
        entry = ' <span class="why">entry</span>' if p["entry"] else ""
        rows.append(
            f"<tr><td><code>{_e(p['name'])}</code>{entry}</td>"
            f'<td class="num">{_e(p["line"] or "")}</td>'
            f'<td class="num">{_e(p["statements"] if p["statements"] is not None else "")}</td>'
            f'<td class="num">{_e(p["complexity"] if p["complexity"] is not None else "—")}</td>'
            f"<td>{state}</td>"
            f'<td class="num">{p["risks"]}</td></tr>'
        )
    return (
        '<div class="table-wrap"><table><thead><tr><th>Paragraph</th><th class="num">Line</th>'
        '<th class="num">Statements</th><th class="num">Complexity</th><th>Tested</th>'
        f'<th class="num">Dialect risks</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>'
    )


#: What a boundary statement does, in words, by its mock_surface label.
_BOUNDARY_VERB = {
    "CALL": "Calls program",
    "dynamic CALL": "Calls the program named in",
    "OPEN": "Opens file",
    "CLOSE": "Closes file",
    "READ": "Reads from",
    "WRITE": "Writes to",
    "REWRITE": "Rewrites a record in",
    "DELETE": "Deletes a record from",
    "START": "Positions",
    "UNLOCK": "Unlocks",
    "SORT": "Sorts",
    "MERGE": "Merges",
    "RELEASE": "Releases a record to the sort",
    "RETURN": "Returns a record from the sort",
    "SQL": "Runs SQL",
    "CICS": "Runs CICS",
    "DLI": "Calls IMS DL/I",
    "ACCEPT": "Reads console input into",
}


def _names(names: list[str]) -> str:
    shown = "".join(f"<li>{_e(n)}</li>" for n in names[:8])
    if len(names) > 8:
        shown += f"<li>… and {len(names) - 8} more</li>"
    return f'<ul class="names">{shown}</ul>'


def _boundaries(report: dict[str, Any]) -> str:
    """One row per boundary statement: what it touches, where, and which
    tests mock it. A report written before boundaries were listed has no
    `boundaries` key and gets a note instead of an empty table."""
    if "boundaries" not in report:
        return '<p class="empty">This report was written before boundaries were listed.</p>'
    boundaries = report["boundaries"]
    if not boundaries:
        if not report["paragraphs"]:
            return '<p class="empty">The program did not parse, so no boundaries are listed.</p>'
        return (
            '<p class="empty">The program touches nothing outside itself: no CALL, '
            "file, SQL, CICS, IMS or console input. Its tests need no MOCK.</p>"
        )
    rows = []
    for b in boundaries:
        verb = _BOUNDARY_VERB.get(b["kind"], b["kind"])
        if b.get("mq"):
            verb = "Calls MQ"
        target = f" <code>{_e(b['target'])}</code>" if b["target"] else ""
        if not b["mockable"]:
            state = _pill("warn", "cannot be mocked")
            who = '<span class="muted">mockymock cannot stand in for this statement</span>'
        elif b["mockedBy"]:
            state = _pill("ok", f"mocked by {_plural(len(b['mockedBy']), 'test')}")
            who = _names(b["mockedBy"])
        elif b["reachedUnmockedBy"]:
            state = _pill("bad", "reached but not mocked")
            who = _names(b["reachedUnmockedBy"])
        else:
            state = _pill("warn", "no test reaches it")
            who = '<span class="muted">—</span>'
        rows.append(
            f"<tr><td>{_e(verb)}{target}</td>"
            f"<td><code>{_e(b['paragraph'])}</code></td>{_num(b['line'])}"
            f"<td>{state}</td><td>{who}</td></tr>"
        )
    mocked = sum(1 for b in boundaries if b["mockedBy"])
    summary = (
        f'<p class="note">{mocked} of {_plural(len(boundaries), "boundary", "boundaries")} '
        "mocked by at least one test.</p>"
    )
    return summary + _table(
        ["What it does", "Paragraph", "Line", "Status", "Tests"], rows, frozenset({2})
    )


def _rules(report: dict[str, Any]) -> str:
    if not report["rulesAvailable"]:
        return '<p class="empty">Rule extraction needs a newer cobol-parser (BusinessRuleExtractor).</p>'
    rules = report["rules"]
    if not rules:
        return '<p class="empty">No business rules found.</p>'
    rows = []
    for r in rules:
        branches = "".join(
            f'<div class="why">{_e(b.get("label"))}: {_e(b.get("condition"))}</div>'
            for b in r["branches"][:6]
        )
        cited = (
            _pill("ok", f"cited by {len(r['citedBy'])}")
            if r["citedBy"]
            else _pill("warn", "no intent assertion")
        )
        rows.append(
            f"<tr><td><code>{_e(r['id'])}</code></td><td>{_e(r['kind'])}</td>"
            f"<td><code>{_e(r['procedure'])}</code></td>"
            f'<td class="num">{_e(r["line"] or "")}</td>'
            f"<td><code>{_e(r['condition'])}</code>{branches}</td><td>{cited}</td></tr>"
        )
    return (
        '<div class="table-wrap"><table><thead><tr><th>Rule</th><th>Kind</th><th>Paragraph</th>'
        '<th class="num">Line</th><th>Condition / formula</th><th>Intent</th></tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table></div>'
    )


def _risks(report: dict[str, Any]) -> str:
    risks = report["dialectRisks"]
    if not risks:
        return '<p class="empty">No GnuCOBOL vs IBM COBOL differences detected (the check is heuristic).</p>'
    rows = "".join(
        f"<tr><td>{_pill(r['severity'])}</td><td><code>{_e(r['code'])}</code></td>"
        f'<td class="num">{_e(r["line"] or "copybook")}</td><td><code>{_e(r["paragraph"])}</code></td>'
        f"<td>{_e(r['message'])}<div class=\"why mono\">{_e(r['detail'])}</div></td></tr>"
        for r in risks
    )
    return (
        '<div class="table-wrap"><table><thead><tr><th>Severity</th><th>Risk</th><th class="num">Line</th>'
        f"<th>Paragraph</th><th>Why it matters</th></tr></thead><tbody>{rows}</tbody></table></div>"
    )


def _table(
    head: list[str], rows: list[str], numeric: frozenset[int] = frozenset()
) -> str:
    cells = "".join(
        f'<th class="num">{_e(h)}</th>' if i in numeric else f"<th>{_e(h)}</th>"
        for i, h in enumerate(head)
    )
    return (
        f'<div class="table-wrap"><table><thead><tr>{cells}</tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table></div>'
    )


def _num(value: Any) -> str:
    return f'<td class="num">{_e("—" if value is None else value)}</td>'


def _call_graph_svg(graph: dict[str, Any]) -> str:
    """A left-to-right layered drawing of the paragraph graph: one column
    per PERFORM depth from the entry point, external CALL targets in a last
    column. Border colour says whether a test reaches the paragraph."""
    nodes = graph["nodes"]
    if not nodes:
        return ""
    names = [n["name"] for n in nodes]
    out_edges: dict[str, list[str]] = {}
    for edge in graph["edges"]:
        out_edges.setdefault(edge["source"], []).append(edge["target"])
    depth: dict[str, int] = {}
    queue = [n["name"] for n in nodes if n["entry"]] or names[:1]
    for name in queue:
        depth[name] = 0
    while queue:
        current = queue.pop(0)
        for target in out_edges.get(current, []):
            if target not in depth:
                depth[target] = depth[current] + 1
                queue.append(target)
    last = max(depth.values(), default=0)
    for name in names:
        depth.setdefault(name, last + 1)  # never reached from an entry point
    externals: list[str] = []
    for call in graph["externalCalls"]:
        label = f"CALL {call['program']}"
        if label not in externals:
            externals.append(label)
    ext_col = max(depth.values()) + 1
    columns: dict[int, list[str]] = {}
    for name in names:
        columns.setdefault(depth[name], []).append(name)
    if externals:
        columns[ext_col] = externals
    box_w, box_h, col_w, row_h, pad = 200, 32, 250, 48, 12
    pos: dict[str, tuple[int, int]] = {}
    for col, members in columns.items():
        for row, name in enumerate(members):
            pos[name] = (pad + col * col_w, pad + row * row_h)
    width = pad * 2 + (max(columns) * col_w) + box_w
    height = pad * 2 + max(len(m) for m in columns.values()) * row_h - (row_h - box_h)

    def curve(a: str, b: str, cls: str) -> str:
        (x1, y1), (x2, y2) = pos[a], pos[b]
        sx, sy, ty = x1 + box_w, y1 + box_h / 2, y2 + box_h / 2
        if x2 <= x1:  # same column or backwards: loop around the right side
            tx: float = x2 + box_w
            mid: float = max(x1, x2) + box_w + 30
        else:
            tx = x2
            mid = (sx + tx) / 2
        return (
            f'<path class="{cls}" d="M{sx},{sy} C{mid},{sy} {mid},{ty} {tx},{ty}" '
            'marker-end="url(#mm-arrow)"/>'
        )

    paths = [
        curve(e["source"], e["target"], "goto" if "GO" in e["type"] else "perform")
        for e in graph["edges"]
        if e["source"] in pos and e["target"] in pos
    ]
    seen_calls: set[tuple[str, str]] = set()
    for call in graph["externalCalls"]:
        key = (call["from"], f"CALL {call['program']}")
        if call["from"] in pos and key not in seen_calls:
            seen_calls.add(key)
            paths.append(curve(key[0], key[1], "call"))
    by_name = {n["name"]: n for n in nodes}
    boxes = []
    for name, (x, y) in pos.items():
        node = by_name.get(name)
        if node is None:
            cls, tip = "ext", f"{name} (external program)"
        else:
            if node["unreachable"]:
                cls, state = "dead", "never performed"
            elif node["testedBy"]:
                cls, state = (
                    "ok",
                    f"reached by {_plural(len(node['testedBy']), 'test')}",
                )
            else:
                cls, state = "untested", "no test reaches it"
            if node["entry"]:
                cls += " entry"
            tip = f"{name} (line {node['line'] or '?'}): {state}"
        text = name if len(name) <= 24 else name[:23] + "…"
        boxes.append(
            f'<g class="n {cls}"><title>{_e(tip)}</title>'
            f'<rect x="{x}" y="{y}" width="{box_w}" height="{box_h}" rx="6"/>'
            f'<text x="{x + 10}" y="{y + box_h / 2 + 4}">{_e(text)}</text></g>'
        )
    return (
        f'<div class="graph"><svg role="img" aria-label="Paragraph call graph" '
        f'width="{width}" height="{height}" viewBox="0 0 {width} {height}">'
        '<defs><marker id="mm-arrow" viewBox="0 0 10 10" refX="9" refY="5" '
        'markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
        '<path d="M0,0 L10,5 L0,10 z"/></marker></defs>'
        f'{"".join(paths)}{"".join(boxes)}</svg></div>'
        '<div class="legend" style="margin-top:6px">'
        '<span><i style="background:var(--ok)"></i>reached by a test</span>'
        '<span><i style="background:var(--warn)"></i>no test reaches it</span>'
        '<span><i style="background:var(--muted)"></i>never performed</span>'
        '<span><i style="background:var(--accent)"></i>external CALL</span>'
        '<span><i style="background:var(--bad)"></i>GO TO</span>'
        "<span>thick border: entry point</span></div>"
    )


_GRADE_TEXT = {
    "A": "Easy to change safely.",
    "B": "Mostly easy to change; a few spots need care.",
    "C": "Changes need care: some paragraphs are complex or duplicated.",
    "D": "Risky to change: plan extra tests before touching it.",
    "F": "Very risky to change: test thoroughly before any edit.",
}
_HEALTH_HELP = {
    "complexity": "Paragraphs with many paths through them are hard to test fully.",
    "redundancy": "Dead code, unused fields and copy-pasted paragraphs.",
    "control flow": "GO TO, ALTER, recursion and unreachable code.",
    "size": "Very long paragraphs.",
}


def _analysis_health(health: dict[str, Any]) -> str:
    tiles = []
    for c in health["components"]:
        score = c.get("score") or 0
        findings = "".join(
            f'<div class="why">{_e(f)}</div>' for f in c.get("findings") or []
        )
        name = str(c["name"]).replace("_", " ")
        state = "No problems" if not score else f"{score:g} / 100"
        weight = c.get("weight")
        share = f" · counts for {weight:g}%" if isinstance(weight, (int, float)) else ""
        tiles.append(
            f'<div class="tile" title="{_e(_HEALTH_HELP.get(name, ""))}">'
            f'<span class="label">{_e(name)}</span>'
            f'<span class="sub"><strong>{_e(state)}</strong>{_e(share)}</span>'
            f'<div class="bar"><span style="width:{min(100.0, float(score)):.0f}%"></span></div>'
            f"{findings}</div>"
        )
    offenders = ""
    if health["topOffenders"]:
        offenders = "<h3>Paragraphs that cost the most</h3>" + _table(
            ["Paragraph", "Line", "Cost", "Why"],
            [
                f"<tr><td><code>{_e(o['name'])}</code></td>{_num(o['line'])}"
                f"{_num(o['severity'])}<td>{_e('; '.join(o['reasons']))}</td></tr>"
                for o in health["topOffenders"]
            ],
            frozenset({1, 2}),
        )
    return (
        f'<p><span class="grade {_e(health["grade"])}">{_e(health["grade"])}</span> '
        f"{_e(_GRADE_TEXT.get(str(health['grade']), ''))} Technical-debt score "
        f"<strong>{health['score']:g}</strong> out of 100, where 0 is best; the "
        "four areas below add up to it.</p>"
        f'<div class="health">{"".join(tiles)}</div>{offenders}'
    )


def _analysis_complexity(complexity: dict[str, Any]) -> str:
    t = complexity.get("thresholds") or {}
    s = complexity.get("summary") or {}
    rating_pill = {"LOW": "ok", "MODERATE": "warn", "HIGH": "fail"}
    rows = [
        f"<tr><td><code>{_e(p['name'])}</code></td>{_num(p['line'])}"
        f"{_num(p['cyclomatic'])}{_num(p['extended'])}{_num(p['nesting'])}"
        f"{_num(p['statements'])}{_num(p['fanIn'])}{_num(p['fanOut'])}{_num(p['gotos'])}"
        f"<td>{_pill(rating_pill.get(str(p['rating']), 'info'), str(p['rating'] or '—').lower())}</td></tr>"
        for p in complexity["procedures"]
    ]
    return (
        _table(
            [
                "Paragraph",
                "Line",
                "Cyclomatic",
                "Extended",
                "Nesting",
                "Statements",
                "Fan-in",
                "Fan-out",
                "GO TO",
                "Rating",
            ],
            rows,
            frozenset(range(1, 9)),
        )
        + f'<p class="note">Total {_e(s.get("total_complexity"))}, mean '
        f'{_e(s.get("mean_complexity"))}, max {_e(s.get("max_complexity"))}. '
        f'Moderate from {_e(t.get("moderate"))}, high from {_e(t.get("high"))}. '
        "Extended complexity also counts each AND/OR in a condition.</p>"
    )


def _analysis_lint(lint: dict[str, Any]) -> str:
    s = lint.get("summary") or {}
    severity_pill = {"error": "fail", "warning": "warn", "info": "info"}
    head = (
        f'<p class="note">{_e(_plural(s.get("total", 0), "finding"))}: {_e(s.get("error", 0))} error, '
        f'{_e(s.get("warning", 0))} warning, {_e(s.get("info", 0))} info. Rules run: '
        f'{_e(", ".join(lint["rulesRun"]) or "none")}.</p>'
    )
    extra = "".join(
        f'<p class="note">Could not check: {_e(c)}</p>' for c in lint["caveats"]
    ) + "".join(
        f'<p class="note">Rule {_e(r)} failed, so its findings are missing.</p>'
        for r in lint["failedRules"]
    )
    if not lint["findings"]:
        return head + extra
    rows = [
        f"<tr><td>{_pill(severity_pill.get(str(f['severity']), 'info'), str(f['severity']))}</td>"
        f"<td><code>{_e(f['rule'])}</code></td>{_num(f['line'])}"
        f"<td>{_e(f['message'])}</td></tr>"
        for f in lint["findings"]
    ]
    more = (
        f'<p class="note">Showing the first {len(lint["findings"])}; run '
        "<code>cobol-parser lint</code> for the rest.</p>"
        if lint["truncated"]
        else ""
    )
    return (
        head
        + _table(["Severity", "Rule", "Line", "Message"], rows, frozenset({2}))
        + more
        + extra
    )


def _analysis_data(data: dict[str, Any]) -> str:
    if not data["items"]:
        return '<p class="empty">No data items.</p>'

    def paras(names: list[str]) -> str:
        shown = ", ".join(names[:4]) + (f" +{len(names) - 4}" if len(names) > 4 else "")
        return f"<td><code>{_e(shown)}</code></td>" if names else "<td>—</td>"

    rows = [
        f"<tr><td><code>{_e(i['name'])}</code></td><td>{_e(i['section'] or '')}</td>"
        f"{_num(i['level'])}{_num(i['line'])}{_num(i['writes'])}{paras(i['writtenIn'])}"
        f"{_num(i['reads'])}{paras(i['readIn'])}</tr>"
        for i in data["items"]
    ]
    note = (
        f'<p class="note">{_plural(data["total"], "data item")}, {data["unreferenced"]} never '
        "referenced in the PROCEDURE DIVISION. Reads include conditions, subscripts, "
        "CALL arguments and SQL host variables."
        + (
            f" Showing the {len(data['items'])} most-referenced."
            if data["truncated"]
            else ""
        )
        + "</p>"
    )
    return (
        _table(
            [
                "Data item",
                "Section",
                "Level",
                "Line",
                "Writes",
                "Written in",
                "Reads",
                "Read in",
            ],
            rows,
            frozenset({2, 3, 4, 6}),
        )
        + note
    )


def _analysis_interface(analysis: dict[str, Any]) -> str:
    parts = []
    signature = analysis.get("signature")
    if signature is not None:
        for entry in signature["entryPoints"]:
            parts.append(
                f'<p class="note">Entry <code>{_e(entry["name"])}</code> ({_e(entry["kind"])})'
                + (
                    f", RETURNING <code>{_e(entry['returning'])}</code>"
                    if entry.get("returning")
                    else ""
                )
                + "</p>"
            )
            if entry.get("callExample"):
                parts.append(f"<pre>{_e(entry['callExample'])}</pre>")
            if entry["parameters"]:
                parts.append(
                    _table(
                        ["#", "Parameter", "Direction", "By", "Declaration", "Bytes"],
                        [
                            f"<tr>{_num(p['position'])}<td><code>{_e(p['name'])}</code></td>"
                            f"<td>{_e(p['direction'])}</td><td>{_e(p['by'])}</td>"
                            f"<td><code>{_e(p['declaration'])}</code></td>{_num(p['bytes'])}</tr>"
                            for p in entry["parameters"]
                        ],
                        frozenset({0, 5}),
                    )
                )
        for note in signature["unchecked"]:
            parts.append(f'<p class="note">{_e(note)}</p>')
    boundaries = analysis.get("boundaries")
    if boundaries:
        parts.append(
            "<h3>External touchpoints (what a test must mock)</h3>"
            + _table(
                ["Kind", "Target", "Paragraph", "Line", "Direction", "Records"],
                [
                    f"<tr><td>{_e(b['category'])}</td><td><code>{_e(b['key'])}</code></td>"
                    f"<td><code>{_e(b['paragraph'])}</code></td>{_num(b['line'])}"
                    f"<td>{_e(str(b['direction'] or '').lower())}</td>"
                    f"<td><code>{_e(', '.join(b['records']))}</code></td></tr>"
                    for b in boundaries
                ],
                frozenset({3}),
            )
        )
    crud = analysis.get("crud")
    if crud:
        mark = {True: "✓", False: "·"}
        parts.append(
            "<h3>Files and tables (CRUD)</h3>"
            + _table(
                ["Kind", "Name", "Create", "Read", "Update", "Delete", "Opened"],
                [
                    f"<tr><td>{_e(r['kind'])}</td><td><code>{_e(r['name'])}</code></td>"
                    f"<td>{mark[r['create']]}</td><td>{mark[r['read']]}</td>"
                    f"<td>{mark[r['update']]}</td><td>{mark[r['delete']]}</td>"
                    f"<td>{_e(', '.join(r['openModes']))}</td></tr>"
                    for r in crud
                ],
            )
        )
    sql = analysis.get("sqlCics")
    if sql is not None and (sql["sqlStatements"] or sql["cicsStatements"]):
        parts.append(
            f'<h3>SQL / CICS checks</h3><p class="note">{_e(sql["sqlStatements"])} SQL and '
            f'{_e(_plural(sql["cicsStatements"], "CICS statement"))}, {_plural(len(sql["violations"]), "problem")}.</p>'
        )
        if sql["violations"]:
            parts.append(
                _table(
                    ["Severity", "Check", "Line", "Message"],
                    [
                        f"<tr><td>{_pill(str(v['severity'] or 'info'))}</td><td><code>{_e(v['kind'])}</code></td>"
                        f"{_num(v['line'])}<td>{_e(v['message'])}</td></tr>"
                        for v in sql["violations"]
                    ],
                    frozenset({2}),
                )
            )
        for note in sql["unchecked"]:
            parts.append(f'<p class="note">Not checked: {_e(note)}</p>')
    return "".join(parts) or '<p class="empty">No external interface found.</p>'


def _members(members: list[dict[str, Any]]) -> str:
    return ", ".join(f"{m['name']} ({m['line']})" for m in members)


def _panel(title: str, summary: str, body: str, *, open_: bool = False) -> str:
    """One collapsible analysis block: the heading and a one-line summary
    stay visible, the (possibly long) table opens on demand."""
    return (
        f'<details class="sub"{" open" if open_ else ""}><summary>'
        f'<span><h3>{_e(title)}</h3><span class="s-sum">{_e(summary)}</span></span>'
        f'</summary><div class="inner">{body}</div></details>'
    )


def _external_calls(graph: dict[str, Any]) -> str:
    if not graph["externalCalls"]:
        return ""
    return _table(
        ["Calls", "From", "Line", "Static / dynamic"],
        [
            f"<tr><td><code>{_e(c['program'])}</code></td><td><code>{_e(c['from'])}</code></td>"
            f"{_num(c['line'])}<td>{'dynamic' if c['dynamic'] else 'static'}"
            + (
                f'<div class="why">may be {_e(", ".join(c["possibleValues"]))}</div>'
                if c["possibleValues"]
                else ""
            )
            + "</td></tr>"
            for c in graph["externalCalls"]
        ],
        frozenset({2}),
    )


def _analysis(report: dict[str, Any]) -> str:
    analysis = report.get("analysis")
    if not analysis:
        return '<p class="empty">This report was written before program analysis was added.</p>'
    if not analysis.get("available"):
        return f'<p class="empty">No program analysis: {_e(analysis.get("reason"))}</p>'
    parts: list[str] = []
    missing = [*analysis.get("unavailable", []), *analysis.get("failed", [])]
    if missing:
        parts.append(
            '<p class="note">'
            + _e(
                "Not shown: "
                + "; ".join(f"{m['title']} ({m['reason']})" for m in missing)
                + ". Upgrade cobol-parser (pip install -U cobol-parser) for the full analysis."
            )
            + "</p>"
        )
    health = analysis.get("health")
    if health:
        parts.append(
            _panel(
                "Health score",
                f"Grade {health['grade']}, technical debt {health['score']:g}/100.",
                _analysis_health(health),
                open_=True,
            )
        )
    graph = analysis["callGraph"]
    untested = sum(
        1 for n in graph["nodes"] if not n["testedBy"] and not n["unreachable"]
    )
    if graph["drawn"]:
        drawing = _call_graph_svg(graph)
    else:
        drawing = (
            f'<p class="note">{len(graph["nodes"])} paragraphs is too many to draw '
            "legibly here; <code>cobol-parser program-flow --format mermaid</code> "
            "draws the whole graph.</p>"
        )
    cycles = "".join(
        f'<p class="note">Cycle ({_e(c["kind"] or "loop")}): '
        f'<code>{_e(" → ".join(c["nodes"]))}</code></p>'
        for c in graph["cycles"]
    )
    parts.append(
        _panel(
            "Call graph",
            f"{_plural(len(graph['nodes']), 'paragraph')}, "
            f"{_plural(len(graph['externalCalls']), 'external CALL')}; "
            + (
                f"{_plural(untested, 'paragraph')} no test reaches."
                if untested
                else "every paragraph is reached by a test."
            ),
            '<p class="intro">Arrows are PERFORMs (grey) and GO TOs (red); blue '
            "boxes are other programs it CALLs. Hover a box for its line and "
            "the tests that reach it.</p>" + drawing + _external_calls(graph) + cycles,
            open_=True,
        )
    )
    complexity = analysis.get("complexity")
    if complexity:
        cs = complexity.get("summary") or {}
        parts.append(
            _panel(
                "Complexity",
                f"Max cyclomatic {cs.get('max_complexity')}, mean "
                f"{cs.get('mean_complexity')}; {cs.get('moderate_count', 0)} moderate, "
                f"{cs.get('high_count', 0)} high.",
                '<p class="intro">Cyclomatic complexity counts the separate paths '
                "through a paragraph: each needs its own test case. Up to 10 is "
                "fine; above 20 is hard to test fully. Fan-in is how many "
                "paragraphs PERFORM this one, fan-out how many it PERFORMs.</p>"
                + _analysis_complexity(complexity),
            )
        )
    lint = analysis.get("lint")
    if lint:
        ls = lint.get("summary") or {}
        by_rule = ls.get("by_rule") or {}
        top = ", ".join(f"{rule} {n}" for rule, n in list(by_rule.items())[:4])
        parts.append(
            _panel(
                "Lint",
                f"{_plural(ls.get('total', 0), 'finding')}: {ls.get('error', 0)} error, "
                f"{ls.get('warning', 0)} warning, {ls.get('info', 0)} info"
                + (f" ({top})." if top else "."),
                '<p class="intro">Automatic checks for common COBOL problems. '
                "Warnings are worth reading; info lines are notes.</p>"
                + _analysis_lint(lint),
            )
        )
    data = analysis.get("dataItems")
    if data:
        parts.append(
            _panel(
                "Data flow",
                f"{_plural(data['total'], 'data item')}, {data['unreferenced']} never referenced.",
                '<p class="intro">For each field: the paragraphs that change it and '
                "the paragraphs that use it. A field a paragraph writes is a good "
                "EXPECT for a test of that paragraph.</p>" + _analysis_data(data),
            )
        )
    if any(
        analysis.get(k) is not None
        for k in ("signature", "boundaries", "crud", "sqlCics")
    ):
        boundaries = analysis.get("boundaries") or []
        crud = analysis.get("crud") or []
        parts.append(
            _panel(
                "Interface",
                f"{_plural(len(boundaries), 'statement')} a test must mock, "
                f"{_plural(len(crud), 'file or table', 'files or tables')}.",
                '<p class="intro">How the program talks to the outside world: what a '
                "caller passes it, and the CALLs, files, SQL, CICS and DL/I "
                "statements a test has to mock.</p>" + _analysis_interface(analysis),
            )
        )
    redundancy = analysis.get("redundancy")
    if redundancy is not None:
        s = redundancy.get("summary") or {}
        groups = redundancy["cloneGroups"]
        clones = (
            _table(
                ["Clone type", "Statements", "Paragraphs"],
                [
                    f"<tr><td>{_e(str(g['type'] or '').replace('_', '-').lower())}</td>{_num(g['statements'])}"
                    f"<td><code>{_e(_members(g['members']))}</code></td></tr>"
                    for g in groups
                ],
                frozenset({1}),
            )
            if groups
            else '<p class="empty">No duplicate paragraphs.</p>'
        )
        parts.append(
            _panel(
                "Dead code and duplicates",
                f"{s.get('dead_procedure_count', 0)} of {s.get('total_procedures', 0)} "
                f"paragraphs never run, {s.get('unused_variable_count', 0)} of "
                f"{s.get('total_variables', 0)} fields unused, "
                f"{_plural(len(groups), 'set')} of copy-pasted paragraphs.",
                clones,
            )
        )
    return f'<div class="analysis">{"".join(parts)}</div>'


def _journal(report: dict[str, Any]) -> str:
    entries = report["journal"]
    problems = report.get("journalProblems") or []
    if not entries and not problems:
        return (
            '<p class="empty">No assistant journal. The cobol-test skill records its '
            "decisions with <code>mockymock journal</code>.</p>"
        )
    out = []
    for entry in entries:
        status = str(entry.get("status", "info"))
        out.append(
            f'<div class="entry"><time>{_e(entry.get("time", ""))}</time><div>'
            f"{_pill(status, str(entry.get('step', '')))} {_e(entry.get('summary', ''))}"
            + (
                f'<div class="decision">Decision: {_e(entry["decision"])}</div>'
                if entry.get("decision")
                else ""
            )
            + (f"<pre>$ {_e(entry['command'])}</pre>" if entry.get("command") else "")
            + "</div></div>"
        )
    for problem in problems:
        out.append(
            f'<div class="entry"><time>—</time><div>{_pill("warn", "skipped line")} {_e(problem)}</div></div>'
        )
    return f'<div class="journal">{"".join(out)}</div>'


def _levels_note() -> str:
    return (
        '<div class="levels-note">'
        + "".join(
            f"<div><span>{_level(level) if level in LEVELS else _L4_BADGE} "
            f"<strong>{_e(LEVEL_TITLES[level])}</strong></span><span>{_e(text)}</span></div>"
            for level, text in _LEVEL_DESCRIPTIONS.items()
        )
        + "</div>"
    )


def _glossary() -> str:
    return (
        '<dl class="glossary">'
        + "".join(
            f"<dt>{_e(term)}</dt><dd>{_md_code(text)}</dd>" for term, text in _GLOSSARY
        )
        + "</dl>"
    )


def render_html(report: dict[str, Any], *, standalone: bool = True) -> str:
    """The report as HTML. `standalone` wraps it in a full document (what
    `mockymock report -o` writes); without it the result is the title,
    style, content and script only, for embedding in a page that supplies
    its own document skeleton."""
    program = report["program"]
    suite = report["cut"].get("suite") or report["cut"]["file"]
    title = f"{program['name']} test report"
    meta = [
        f"<span>Program <code>{_e(program['file'])}</code></span>",
        f"<span>Suite <code>{_e(report['cut']['file'])}</code></span>",
        f"<span>Generated {_e(report['generatedAt'])}</span>",
    ]
    env = next((s for s in report["steps"] if s["id"] == "environment"), None)
    if env:
        d = env.get("details") or {}
        meta.append(
            f"<span>mockymock {_e(d.get('mockymock'))} · cobol-parser {_e(d.get('cobolParser'))}</span>"
        )
    sections = [
        (
            "h-next",
            "What to do next",
            "The most useful actions, most important first.",
            _next_steps(report),
        ),
        (
            "h-findings",
            "Findings",
            "Everything the checks turned up, most serious first.",
            _findings(report),
        ),
        ("h-cases", "Test cases", "", _cases(report)),
        (
            "h-boundaries",
            "Boundaries",
            "Every statement where the program talks to something outside "
            "itself: another program, a file, SQL, CICS, IMS or console input. "
            "A test must MOCK each one it reaches; the last column names the "
            "tests that do.",
            _boundaries(report),
        ),
        (
            "h-analysis",
            "Program analysis",
            "What cobol-parser found about the program itself, independent of "
            "the tests: how risky it is to change, how it is wired together, and "
            "what it touches. Click a panel to open it.",
            _analysis(report),
        ),
        (
            "h-rules",
            "Business rules",
            "Decisions and calculations found in the code. A rule is “cited” "
            "when a test's INTENT label names it, which is what proves the test "
            "checks the rule rather than whatever the program happens to do.",
            _rules(report),
        ),
        (
            "h-paragraphs",
            "Paragraphs",
            "Every paragraph and whether a test reaches it.",
            _paragraphs(report),
        ),
        (
            "h-risks",
            "GnuCOBOL vs IBM COBOL risks",
            "These tests run on GnuCOBOL. Lines listed here may behave "
            "differently on the mainframe's IBM Enterprise COBOL.",
            _risks(report),
        ),
        (
            "h-steps",
            "How the verdict was reached",
            "Each check that produced the numbers above, with the command that "
            "repeats it. Click a step for its details.",
            _steps(report),
        ),
        (
            "h-journal",
            "Assistant journal",
            "Decisions the AI assistant recorded while writing the tests.",
            _journal(report),
        ),
        ("h-levels", "Verification levels", "", _levels_note()),
        (
            "h-glossary",
            "Words used in this report",
            "",
            _glossary(),
        ),
    ]
    nav = "".join(
        f'<a href="#{anchor}">{_e(heading)}</a>'
        for anchor, heading, _, _ in sections
        if anchor not in ("h-next", "h-levels", "h-glossary")
    )
    content = "\n".join(
        f'<section aria-labelledby="{anchor}"><h2 id="{anchor}">{_e(heading)}</h2>'
        + (f'<p class="intro">{_e(intro)}</p>' if intro else "")
        + f"{html_}</section>"
        for anchor, heading, intro, html_ in sections
    )
    body = f"""<title>{_e(title)}</title>
<style>{_CSS}</style>
<div class="wrap">
<header>
  <span class="eyebrow">mockymock report · {_e(suite)}</span>
  <h1><code>{_e(program['name'])}</code> test report</h1>
  <p class="lede">{_e(_verdict_sentence(report))}</p>
  <div class="meta">{''.join(meta)}</div>
  <nav class="toc" aria-label="Sections">{nav}<a href="#h-glossary">Glossary</a></nav>
</header>
{_summary_strip(report)}
{content}
<footer>Every number on this page comes from a mockymock or cobol-parser command run against this program; “How the verdict was reached” names each one.</footer>
</div>
<script>{_JS}</script>
"""
    if not standalone:
        return body
    return (
        '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"</head>\n<body>\n{body}</body>\n</html>\n"
    )
