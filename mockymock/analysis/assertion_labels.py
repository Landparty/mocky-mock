"""Where each `.cut` assertion's expected value came from.

An `EXPECT`/`VERIFY` is only as good as the reason its value is the right
one. Two reasons are worth telling apart, and the `cobol-test` skill (and
`mockymock report`) asks for them to be written down as a comment line
directly above the assertions they cover:

    *> INTENT: BR-003 orders over 1000.00 get 5% off (ORDRPROC.cbl:212)
    EXPECT WS-NET-AMOUNT TO BE 950.00

    *> CHARACTERIZATION: recorded by run --record-expectations
    EXPECT WS-AUDIT-COUNT TO BE 3

INTENT means the value was derived from a business rule, a spec, or the
developer -- a mismatch is a suspected program bug. CHARACTERIZATION means
the value is whatever the program produced on some run -- it pins current
behavior and proves nothing about correctness.

A label covers every EXPECT/VERIFY line that follows it, up to the first
blank line, the next label, the next TESTCASE, or any other directive.
Other comment lines in between (a `*> STUB EXPECT`, a note) do not end it.

A label written at the top of a test case -- directly above its TESTCASE
line, or inside it before its first assertion, where a MOCK block or a
setup MOVE ends it before it reaches any EXPECT/VERIFY -- is the case's
label instead: it covers every assertion in that case that no label of its
own sits directly above (issue #346). Labels at the top of the case are
what people naturally write, and reading them as covering nothing turned
whole suites written with intent into "0 intent, N unlabelled".

A label written directly above a TESTCASE line still labels that case
when blank lines separate the two -- the commonest way to lay a suite out.

A label inside BEFORE-EACH is the suite's label: it covers every assertion,
in every case, that neither a label of its own nor its case's label covers.

An assertion no label covers is reported as unlabelled, and a label that
still covers nothing (one after the case's last assertion, a second label
at the top of a case that already has one) is reported as an orphan --
lint warns about it, so a label is never silently ignored.

Pure text analysis: works on any `.cut` that `parse_cut` accepts, needs no
program and no Docker.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

ORPHAN_ASSERTION_LABEL = "ORPHAN_ASSERTION_LABEL"
INTENT = "intent"
CHARACTERIZATION = "characterization"

_LABEL_RE = re.compile(
    r"^\*>\s*(?P<kind>INTENT|CHARACTERI[SZ]ATION)\b\s*:?\s*(?P<note>.*)$",
    re.IGNORECASE,
)
_TESTCASE_RE = re.compile(r'^TESTCASE\s+"(?P<name>(?:[^"]|"")*)"', re.IGNORECASE)
_ASSERTION_RE = re.compile(r"^(?P<kind>EXPECT|VERIFY)\b", re.IGNORECASE)
_HOOK_RE = re.compile(
    r"^(?P<hook>BEFORE-ALL|BEFORE-EACH|AFTER-EACH|AFTER-ALL)\.?$", re.IGNORECASE
)
_HOOK_END_RE = re.compile(r"^END-(?:BEFORE|AFTER)\.?$", re.IGNORECASE)
_RULE_ID_RE = re.compile(r"\bBR-\d+\b", re.IGNORECASE)

# The comment line `--record-expectations` writes above the EXPECTs it
# recorded (see report/record_rewrite.py), so recorded values are labelled
# without anyone having to remember to.
RECORDED_LABEL = "*> CHARACTERIZATION: recorded by mockymock run --record-expectations"


@dataclass
class LabelledAssertion:
    case_name: str
    line: int
    kind: str  # "expect" | "verify"
    text: str
    label: str | None = None  # INTENT | CHARACTERIZATION | None
    note: str = ""
    label_line: int | None = None
    rule_ids: list[str] = field(default_factory=list)
    #: "adjacent" (the label sits directly above), "case" (the case's
    #: label from the top of the TESTCASE) or "suite" (the BEFORE-EACH
    #: label); None when unlabelled.
    label_scope: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "case": self.case_name,
            "line": self.line,
            "kind": self.kind,
            "text": self.text,
            "label": self.label,
            "note": self.note,
            "labelLine": self.label_line,
            "labelScope": self.label_scope,
            "ruleIds": list(self.rule_ids),
        }


@dataclass
class OrphanLabel:
    """An INTENT/CHARACTERIZATION line that covers no assertion."""

    line: int
    label: str
    note: str
    case_name: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "line": self.line,
            "label": self.label,
            "note": self.note,
            "case": self.case_name,
        }


def scan_assertion_labels(cut_text: str) -> list[LabelledAssertion]:
    """Every EXPECT/VERIFY inside a TESTCASE, in file order, with the label
    covering it (if any). Assertions outside any TESTCASE (a malformed file)
    are skipped -- they belong to no case the report could attribute."""
    return scan_label_placement(cut_text)[0]


def scan_label_placement(
    cut_text: str,
) -> tuple[list[LabelledAssertion], list[OrphanLabel]]:
    """`scan_assertion_labels`, plus every label that covers nothing."""
    results: list[LabelledAssertion] = []
    labels: list[OrphanLabel] = []
    covered: set[int] = set()
    case_name: str | None = None
    # The label directly above whatever comes next, and the case's own
    # label (from its top), each as an index into `labels`.
    label: int | None = None
    case_label: int | None = None
    case_asserted = False
    # A label separated from what follows by blank lines: kept only in case
    # the next line turns out to be a TESTCASE header.
    detached: int | None = None
    hook: str | None = None
    suite_label: int | None = None

    def end_adjacent() -> None:
        # A label at the top of the case that ran into a MOCK, a setup
        # line or a blank line before any assertion: the case's label.
        nonlocal label, case_label
        if (
            label is not None
            and case_name is not None
            and not case_asserted
            and labels[label].line not in covered
        ):
            case_label = label
        label = None

    for line_no, raw in enumerate(cut_text.splitlines(), start=1):
        stripped = raw.strip()
        if not stripped:
            if label is not None and labels[label].line not in covered:
                detached = label
            end_adjacent()
            if case_label == detached:
                detached = None
            continue
        opened = _HOOK_RE.match(stripped)
        if opened:
            end_adjacent()
            hook = opened.group("hook").upper()
            case_name, case_label, case_asserted, detached = None, None, False, None
            continue
        if _HOOK_END_RE.match(stripped):
            end_adjacent()
            hook, detached = None, None
            continue
        testcase = _TESTCASE_RE.match(stripped)
        if testcase:
            # A label directly above the TESTCASE line labels that case,
            # blank lines between them or not.
            candidate = label if label is not None else detached
            above = (
                candidate
                if candidate is not None and labels[candidate].line not in covered
                else None
            )
            detached = None
            hook = None
            case_name = testcase.group("name").replace('""', '"')
            case_asserted = False
            case_label = above
            if above is not None:
                labels[above].case_name = case_name
            label = None
            continue
        labelled = _LABEL_RE.match(stripped)
        if labelled:
            end_adjacent()
            kind = labelled.group("kind").upper()
            labels.append(
                OrphanLabel(
                    line=line_no,
                    label=INTENT if kind == "INTENT" else CHARACTERIZATION,
                    note=labelled.group("note").strip(),
                    case_name=case_name,
                )
            )
            if hook == "BEFORE-EACH" and suite_label is None:
                suite_label = len(labels) - 1
                continue
            label = len(labels) - 1
            detached = None
            continue
        if stripped.startswith("*>"):
            continue
        detached = None
        assertion = _ASSERTION_RE.match(stripped)
        if assertion is None:
            end_adjacent()
            continue
        if case_name is None:
            continue
        case_asserted = True
        item = LabelledAssertion(
            case_name=case_name,
            line=line_no,
            kind=assertion.group("kind").lower(),
            text=stripped,
        )
        source = label if label is not None else case_label
        if source is not None:
            found = labels[source]
            item.label, item.note, item.label_line = found.label, found.note, found.line
            item.label_scope = "adjacent" if source == label else "case"
            item.rule_ids = sorted(
                {match.upper() for match in _RULE_ID_RE.findall(item.note)}
            )
            covered.add(found.line)
        results.append(item)
    if suite_label is not None:
        found = labels[suite_label]
        for item in results:
            if item.label is None:
                item.label, item.note, item.label_line = (
                    found.label,
                    found.note,
                    found.line,
                )
                item.label_scope = "suite"
                item.rule_ids = sorted(
                    {match.upper() for match in _RULE_ID_RE.findall(found.note)}
                )
                covered.add(found.line)
    orphans = [found for found in labels if found.line not in covered]
    return results, orphans


def orphan_label_warnings(cut_text: str) -> list[str]:
    """One lint warning line per label that covers no assertion (#346)."""
    warnings: list[str] = []
    for orphan in scan_label_placement(cut_text)[1]:
        where = f' in TESTCASE "{orphan.case_name}"' if orphan.case_name else ""
        warnings.append(
            f"warning ({ORPHAN_ASSERTION_LABEL}): .cut line {orphan.line}: the "
            f"{orphan.label.upper()} label{where} covers no EXPECT/VERIFY -- "
            "put it directly above the assertions it is about, at the top "
            "of the test case to cover all of them, or in BEFORE-EACH to "
            "cover the whole suite"
        )
    return warnings


def summarize_labels(items: list[LabelledAssertion]) -> dict[str, int]:
    """Counts by label: the numbers the report's headline shows."""
    return {
        "total": len(items),
        INTENT: sum(1 for i in items if i.label == INTENT),
        CHARACTERIZATION: sum(1 for i in items if i.label == CHARACTERIZATION),
        "unlabelled": sum(1 for i in items if i.label is None),
    }
