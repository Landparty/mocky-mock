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
.strip { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(150px, 100%), 1fr)); gap: 12px; }
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


def _tile(label: str, value: str, sub: str = "", extra: str = "") -> str:
    return (
        f'<div class="tile"><span class="label">{_e(label)}</span>'
        f'<span class="value">{value}</span>'
        + (f'<span class="sub">{sub}</span>' if sub else "")
        + extra
        + "</div>"
    )


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
    passed_sub = f"{s['failed']} failed, {s['notRun']} not run"
    coverage = "—" if s["coverage"] is None else f"{s['coverage']:.1f}%"
    mutation = "—" if s["mutationScore"] is None else f"{s['mutationScore']:.0f}%"
    intent = "—" if s["intentShare"] is None else f"{s['intentShare']:.0f}%"
    f = s["findings"]
    return (
        '<section class="strip" aria-label="Summary">'
        + _tile("Tests passing", f"{s['passed']}/{cases}", _e(passed_sub))
        + _tile(
            "Verification",
            f"{levels.get('L3', 0) + levels.get('L2', 0)}/{cases}",
            "at L2 or higher",
            f'<div class="ladder">{ladder}</div><div class="legend">{legend}</div>',
        )
        + _tile(
            "Intent assertions",
            intent,
            f"of {s['assertions']} assertions cite a rule or the developer",
        )
        + _tile("Line coverage", coverage, "of the original .cbl")
        + _tile("Mutation score", mutation, f"threshold {s['mutationThreshold']:.0f}%")
        + _tile(
            "Findings",
            str(f["high"] + f["medium"]),
            f"high/medium · {f['low']} low · {f['info']} info",
        )
        + "</section>"
    )


def _verdict_sentence(report: dict[str, Any]) -> str:
    s = report["summary"]
    if s["levels"].get("none"):
        return "The suite is refused by the static gate, so nothing it asserts has been checked yet."
    if s["notRun"] == s["cases"]:
        return (
            "The suite passes the static checks but has not been run here, so no "
            "test is proven by execution yet."
        )
    parts = [f"{s['passed']} of {s['cases']} tests pass under GnuCOBOL"]
    high = s["findings"]["high"]
    if high:
        parts.append(f"{high} high-severity finding(s) need a look first")
    top = max((lvl for lvl in LEVELS if s["levels"].get(lvl)), default=None)
    if top:
        parts.append(
            f"the strongest proof reached is {top} ({LEVEL_TITLES[top].lower()})"
        )
    return "; ".join(parts) + "."


def _findings(report: dict[str, Any]) -> str:
    items = report["findings"]
    if not items:
        return '<p class="empty">No findings.</p>'
    out = []
    for f in items:
        tags = [_pill(f["severity"]), f"<span>{_e(f['category'])}</span>"]
        if f.get("line"):
            tags.append(f"<span>line {_e(f['line'])}</span>")
        if f.get("case"):
            tags.append(f"<span>case “{_e(f['case'])}”</span>")
        out.append(
            f'<article class="finding {_e(f["severity"])}"><div class="stripe"></div>'
            f'<div class="body"><div class="title">{_e(f["title"])}</div>'
            + (
                f'<div class="detail">{_e(f["detail"])}</div>'
                if f.get("detail")
                else ""
            )
            + f'<div class="tags">{"".join(tags)}</div></div></article>'
        )
    return f'<div class="findings">{"".join(out)}</div>'


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
        a = c["assertions"]
        risks = [r for r in c["risks"] if r["severity"] in ("high", "medium")]
        failures = "".join(
            f'<div class="why">✗ line {_e(fl.get("line"))}: {_e(fl.get("message"))}</div>'
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
            f'<td class="num">{a["intent"]}</td><td class="num">{a["characterization"]}</td>'
            f'<td class="num">{a["unlabelled"]}</td>'
            f'<td class="num">{len(risks)}</td></tr>'
        )
    return (
        f'<div class="filters" role="group" aria-label="Filter test cases">{"".join(filters)}</div>'
        '<div class="table-wrap"><table id="cases"><thead><tr>'
        "<th>Level</th><th>Test case</th><th>Result</th><th>Performs</th>"
        '<th class="num">Intent</th><th class="num">Recorded</th><th class="num">Unlabelled</th>'
        '<th class="num">Dialect risks</th>'
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
    body = f"""<title>{_e(title)}</title>
<style>{_CSS}</style>
<div class="wrap">
<header>
  <span class="eyebrow">mockymock report · {_e(suite)}</span>
  <h1><code>{_e(program['name'])}</code> test report</h1>
  <p class="lede">{_e(_verdict_sentence(report))}</p>
  <div class="meta">{''.join(meta)}</div>
</header>
{_summary_strip(report)}
<section aria-labelledby="h-findings"><h2 id="h-findings">Findings</h2>{_findings(report)}</section>
<section aria-labelledby="h-cases"><h2 id="h-cases">Test cases</h2>{_cases(report)}</section>
<section aria-labelledby="h-steps"><h2 id="h-steps">How the verdict was reached</h2>{_steps(report)}</section>
<section aria-labelledby="h-journal"><h2 id="h-journal">Assistant journal</h2>{_journal(report)}</section>
<section aria-labelledby="h-paragraphs"><h2 id="h-paragraphs">Paragraphs</h2>{_paragraphs(report)}</section>
<section aria-labelledby="h-rules"><h2 id="h-rules">Business rules</h2>{_rules(report)}</section>
<section aria-labelledby="h-risks"><h2 id="h-risks">GnuCOBOL vs IBM COBOL risks</h2>{_risks(report)}</section>
<section aria-labelledby="h-levels"><h2 id="h-levels">Verification levels</h2>{_levels_note()}</section>
<footer>Every number on this page comes from a mockymock or cobol-parser command run against this program; the step list above names each one.</footer>
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
