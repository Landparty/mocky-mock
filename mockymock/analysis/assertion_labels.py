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
An assertion no label covers is reported as unlabelled.

Pure text analysis: works on any `.cut` that `parse_cut` accepts, needs no
program and no Docker.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

INTENT = "intent"
CHARACTERIZATION = "characterization"

_LABEL_RE = re.compile(
    r"^\*>\s*(?P<kind>INTENT|CHARACTERI[SZ]ATION)\b\s*:?\s*(?P<note>.*)$",
    re.IGNORECASE,
)
_TESTCASE_RE = re.compile(r'^TESTCASE\s+"(?P<name>(?:[^"]|"")*)"', re.IGNORECASE)
_ASSERTION_RE = re.compile(r"^(?P<kind>EXPECT|VERIFY)\b", re.IGNORECASE)
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

    def to_dict(self) -> dict[str, Any]:
        return {
            "case": self.case_name,
            "line": self.line,
            "kind": self.kind,
            "text": self.text,
            "label": self.label,
            "note": self.note,
            "labelLine": self.label_line,
            "ruleIds": list(self.rule_ids),
        }


def scan_assertion_labels(cut_text: str) -> list[LabelledAssertion]:
    """Every EXPECT/VERIFY inside a TESTCASE, in file order, with the label
    covering it (if any). Assertions outside any TESTCASE (a malformed file)
    are skipped -- they belong to no case the report could attribute."""
    results: list[LabelledAssertion] = []
    case_name: str | None = None
    label: tuple[str, str, int] | None = None  # (kind, note, line)

    for line_no, raw in enumerate(cut_text.splitlines(), start=1):
        stripped = raw.strip()
        if not stripped:
            label = None
            continue
        testcase = _TESTCASE_RE.match(stripped)
        if testcase:
            case_name = testcase.group("name").replace('""', '"')
            label = None
            continue
        labelled = _LABEL_RE.match(stripped)
        if labelled:
            kind = labelled.group("kind").upper()
            label = (
                INTENT if kind == "INTENT" else CHARACTERIZATION,
                labelled.group("note").strip(),
                line_no,
            )
            continue
        if stripped.startswith("*>"):
            continue
        assertion = _ASSERTION_RE.match(stripped)
        if assertion is None:
            label = None
            continue
        if case_name is None:
            continue
        item = LabelledAssertion(
            case_name=case_name,
            line=line_no,
            kind=assertion.group("kind").lower(),
            text=stripped,
        )
        if label is not None:
            item.label, item.note, item.label_line = label
            item.rule_ids = sorted(
                {match.upper() for match in _RULE_ID_RE.findall(item.note)}
            )
        results.append(item)
    return results


def summarize_labels(items: list[LabelledAssertion]) -> dict[str, int]:
    """Counts by label: the numbers the report's headline shows."""
    return {
        "total": len(items),
        INTENT: sum(1 for i in items if i.label == INTENT),
        CHARACTERIZATION: sum(1 for i in items if i.label == CHARACTERIZATION),
        "unlabelled": sum(1 for i in items if i.label is None),
    }
