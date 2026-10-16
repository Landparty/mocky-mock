"""Flow-target mocks: `MOCK PARAGRAPH <name>` / `MOCK SECTION <name>`.

Unlike boundary mocks (which replace one statement), a flow mock replaces
what happens when a paragraph/section is entered THROUGH ITS OWN HEADER:
the splicer rewrites the header into a small dispatch paragraph/section --

    P.                                 P.
        <body>            ==>             EVALUATE UT-CURRENT-CASE
                                               WHEN "001" <mock body>
                                               WHEN OTHER PERFORM UT-REAL-1-P
                                           END-EVALUATE.
                                       UT-REAL-1-P.
                                           <body -- original lines, unmoved>

Only the single header line is replaced; the original body lines never
move, so every other line-number-derived splice (boundary dispatch blocks,
terminator neutralization, chain checks) stays valid inside the body, and
cases that do NOT mock the target run the real body via the WHEN OTHER
branch. See docs/2026-07-20-paragraph-section-mocks-design.md.

That trick is only sound when the target is entered exclusively through
its header by a PERFORM naming it (simple or looping): any other entry --
GO TO, fall-through from a THRU range or an enclosing performed SECTION,
or falling in from a paragraph above -- would run the dispatch AND then
fall through into the relocated real body (or bypass the dispatch
entirely). `find_flow_mock_plans` therefore refuses, fail-closed and
program-wide (one binary serves the whole suite, so a hazard anywhere is
a hazard for every case):

- UNRESOLVED_FLOW_MOCK_TARGET: the key names no (or more than one)
  paragraph/section, or names the other kind.
- UNSUPPORTED_FLOW_MOCK_TARGET:
  * the target is a GO TO target anywhere in the program (control would
    fall off the dispatch paragraph's end into the relocated body);
  * the target (or, for a SECTION, any part of it) lies inside a
    PERFORM ... THRU range -- in-program or a test case's own driver
    range -- whose fall-through walk would execute dispatch and body
    back to back;
  * the target is reachable by falling through past a GO TO target
    (refusal._go_to_fallthrough_targets -- never PERFORMed, same hazard);
  * a mocked PARAGRAPH belongs to a SECTION that is itself performed or
    jumped to as a section anywhere (a performed section executes its
    paragraphs by fall-through, straight through the dispatch);
  * the header does not own its line (`P. MOVE ...` one-liners -- the
    single-line header replace would comment out the trailing code).

Per-case checks (entry-point overlap, reachability/UNMATCHED_MOCK, and
excluding a mocked target's body from the reachable set so boundaries
inside it need no mocks of their own) live in refusal.check_test_case.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from cobolparser.models.statements.control import PerformStatement

from mockymock.analysis.mock_surface import _all_paragraphs
from mockymock.dsl.model import FLOW_CATEGORIES, MockCategory, MockTestSuite

_NON_COBOL_NAME_CHAR_RE = re.compile(r"[^A-Z0-9-]")
# "UT-REAL-" + index + "-" + body must stay a conservative 30-char COBOL
# word; the numeric index already guarantees uniqueness, the name tail is
# readability only.
_MAX_REAL_BODY = 18


@dataclass
class FlowMockPlan:
    """One (category, key) flow mock found safe to splice: replace the
    header line at `header_line` with a dispatch header plus a relocated
    real header named `real_name` (see module docstring)."""

    category: MockCategory
    key: str
    header_line: int
    real_name: str

    @property
    def is_section(self) -> bool:
        return self.category is MockCategory.SECTION


def _refusal(code: str, message: str):
    # refusal.py imports this module only inside functions, so a
    # module-load cycle can't happen -- but keep this one import lazy as
    # a guard against that ever changing.
    from mockymock.analysis.refusal import RefusalReason

    return RefusalReason(code=code, message=message)


def _real_name(key: str, index: int) -> str:
    body = _NON_COBOL_NAME_CHAR_RE.sub("-", key.upper())
    body = re.sub(r"-{2,}", "-", body).strip("-")[:_MAX_REAL_BODY].rstrip("-")
    suffix = f"-{body}" if body else ""
    return f"UT-REAL-{index}{suffix}"


def resolved_flow_targets(program, suite_or_case) -> tuple[set[str], set[str]]:
    """(paragraph names, section names) mocked by `suite_or_case` (anything
    with `.mocks` or `.test_cases`) that actually resolve in `program` --
    the exclusion sets the reachability BFS skips traversal into.
    Unresolvable keys are simply absent here; find_flow_mock_plans refuses
    them separately."""
    procedure = program.get_division("PROCEDURE")
    if procedure is None:
        return set(), set()
    paragraph_names = {
        p.paragraph_name
        for p in _all_paragraphs(procedure)
        if p.paragraph_name.strip(".")
    }
    section_names = {name for name in procedure._sections if name}
    cases = getattr(suite_or_case, "test_cases", None)
    if cases is None:
        cases = [suite_or_case]
    mocked_paragraphs: set[str] = set()
    mocked_sections: set[str] = set()
    for case in cases:
        for directive in case.mocks:
            if directive.category is MockCategory.PARAGRAPH:
                if directive.key in paragraph_names:
                    mocked_paragraphs.add(directive.key)
            elif directive.category is MockCategory.SECTION:
                if directive.key in section_names:
                    mocked_sections.add(directive.key)
    return mocked_paragraphs, mocked_sections


def _header_line_problem(
    lines: list[str], header_line: int, name: str, is_section: bool
) -> str | None:
    """The header must own its line and read exactly `NAME.` /
    `NAME SECTION.` -- anything else (a one-line paragraph `P1. MOVE ...`,
    a header sharing its line, or a location the AST mis-reported) makes
    the single-line header replace unsafe."""
    if not (1 <= header_line <= len(lines)):
        return f"header line {header_line} is outside the source text"
    text = lines[header_line - 1].strip()
    if is_section:
        pattern = rf"^{re.escape(name)}\s+SECTION\s*\.$"
    else:
        pattern = rf"^{re.escape(name)}\s*\.$"
    if not re.match(pattern, text, re.IGNORECASE):
        return (
            f"header line {header_line} ({text!r}) is not a bare "
            f"'{name}{' SECTION' if is_section else ''}.' header on its own "
            f"line"
        )
    return None


def _qualified_reference_problem(
    lines: list[str], section: str, members: list[str]
) -> str | None:
    """Why a SECTION mock cannot be spliced when the program names one of
    the section's paragraphs qualified by it (`PERFORM P2 OF CALC`), or
    None. The splice moves every paragraph of the section under the
    relocated `UT-REAL-n-` section, so `P2 OF CALC` no longer resolves and
    cobc rejected the program after a clean lint (issue #293)."""
    if not members:
        return None
    pattern = re.compile(
        r"(?<![A-Z0-9-])("
        + "|".join(re.escape(m.upper()) for m in members)
        + r")\s+(?:OF|IN)\s+"
        + re.escape(section.upper())
        + r"(?![A-Z0-9-])"
    )
    in_procedure = False
    for number, line in enumerate(lines, start=1):
        code = line.split("*>", 1)[0].upper()
        if not in_procedure:
            in_procedure = bool(re.match(r"\s*PROCEDURE\s+DIVISION\b", code))
            continue
        found = pattern.search(code)
        if found:
            return (
                f"has its paragraph '{found.group(1)}' referenced qualified "
                f"by the section at line {number} ('{found.group(1)} OF "
                f"{section.upper()}') -- the splice moves the section's "
                f"paragraphs under the relocated real section, so that "
                f"reference would no longer resolve"
            )
    return None


def find_flow_mock_plans(
    program, suite: MockTestSuite, lines: list[str]
) -> tuple[list[FlowMockPlan], list]:
    """For every distinct PARAGRAPH/SECTION (category, key) mocked anywhere
    in the suite, return either a FlowMockPlan or refusal reason(s) --
    never both for the same key. `lines` is the normalized free-form text
    the splicer edits (SourceLocation lines index into it)."""
    from mockymock.analysis.refusal import (
        _expand_thru_range,
        _find_sort_merge_statements,
        _find_statements_of_type,
        _go_to_fallthrough_targets,
        _go_to_targets,
        _source_ordered_paragraphs,
    )
    from mockymock.analysis.refusal._reachability import (
        _find_xml_parse_statements,
    )

    flow_keys = [
        (category, key)
        for category, key in suite.all_mock_keys()
        if category in FLOW_CATEGORIES
    ]
    if not flow_keys:
        return [], []

    procedure = program.get_division("PROCEDURE")
    if procedure is None:
        return [], [
            _refusal(
                "UNRESOLVED_FLOW_MOCK_TARGET",
                f"MOCK {category.keyword} {key}: program has no PROCEDURE " f"DIVISION",
            )
            for category, key in flow_keys
        ]

    paragraphs_by_name: dict[str, list] = {}
    for paragraph in _all_paragraphs(procedure):
        if paragraph.paragraph_name.strip("."):
            paragraphs_by_name.setdefault(paragraph.paragraph_name, []).append(
                paragraph
            )
    sections = {name: s for name, s in procedure._sections.items() if name}
    paragraph_section: dict[str, str] = {}
    for section_name, section in sections.items():
        for paragraph in section.paragraphs:
            paragraph_section.setdefault(paragraph.paragraph_name, section_name)

    go_to_targets = _go_to_targets(program)
    fallthrough = _go_to_fallthrough_targets(program, go_to_targets)
    ordered = _source_ordered_paragraphs(procedure)

    # Every name used as a PERFORM/GO TO target anywhere (for the
    # enclosing-performed-SECTION check on PARAGRAPH mocks).
    flow_target_names: set[str] = set(go_to_targets)
    for paragraph in _all_paragraphs(procedure):
        for statement in _find_statements_of_type(
            paragraph.statements, PerformStatement
        ):
            if statement.target_paragraph:
                flow_target_names.add(statement.target_paragraph)
            if statement.thru_paragraph:
                flow_target_names.add(statement.thru_paragraph)
    # SORT/MERGE INPUT/OUTPUT PROCEDURE and XML PARSE PROCESSING PROCEDURE
    # are implicit PERFORMs, ranges included (issue #261).
    implicit_ranges: list[tuple[str, str, str | None]] = []
    for paragraph in _all_paragraphs(procedure):
        origin = f"paragraph '{paragraph.paragraph_name}'"
        for statement in _find_sort_merge_statements(paragraph.statements):
            for procedure_attr, thru_attr in (
                ("input_procedure", "input_procedure_thru"),
                ("output_procedure", "output_procedure_thru"),
            ):
                start = getattr(statement, procedure_attr, None)
                if start:
                    implicit_ranges.append(
                        (
                            f"{origin} {statement.statement_type} "
                            f"{procedure_attr.replace('_', ' ').upper()}",
                            start,
                            getattr(statement, thru_attr, None),
                        )
                    )
        for statement in _find_xml_parse_statements(paragraph.statements):
            start = getattr(statement, "processing_procedure", None)
            if start:
                implicit_ranges.append(
                    (
                        f"{origin} XML PARSE PROCESSING PROCEDURE",
                        start,
                        getattr(statement, "processing_procedure_thru", None),
                    )
                )
    for _, start, thru in implicit_ranges:
        flow_target_names.add(start)
        if thru:
            flow_target_names.add(thru)

    # Every PERFORM ... THRU range in the program plus each test case's own
    # driver-side range, kept as (origin, start, thru) for messages.
    thru_ranges: list[tuple[str, str, str]] = []
    for paragraph in _all_paragraphs(procedure):
        for statement in _find_statements_of_type(
            paragraph.statements, PerformStatement
        ):
            if statement.target_paragraph and statement.thru_paragraph:
                thru_ranges.append(
                    (
                        f"paragraph '{paragraph.paragraph_name}'",
                        statement.target_paragraph,
                        statement.thru_paragraph,
                    )
                )
    thru_ranges.extend(
        (origin, start, thru) for origin, start, thru in implicit_ranges if thru
    )
    for case in suite.analysis_cases():
        if case.perform_target and case.perform_thru:
            thru_ranges.append(
                (
                    f"test case {case.name!r} PERFORM",
                    case.perform_target,
                    case.perform_thru,
                )
            )

    line_by_name = {p.paragraph_name: p.location.line for p in ordered or []}

    plans: list[FlowMockPlan] = []
    reasons: list = []
    for index, (category, key) in enumerate(flow_keys, start=1):
        described = f"MOCK {category.keyword} {key}"
        is_section = category is MockCategory.SECTION

        # --- resolution ---------------------------------------------------
        if is_section:
            target = sections.get(key)
            if target is None:
                hint = (
                    " (it names a paragraph -- use MOCK PARAGRAPH)"
                    if key in paragraphs_by_name
                    else ""
                )
                reasons.append(
                    _refusal(
                        "UNRESOLVED_FLOW_MOCK_TARGET",
                        f"{described}: no SECTION named '{key}' in the "
                        f"PROCEDURE DIVISION{hint}",
                    )
                )
                continue
            header_line = target.location.line
            member_names = [
                p.paragraph_name
                for p in target.paragraphs
                if p.paragraph_name.strip(".")
            ]
            entry_names = member_names[:1]
        else:
            matches = paragraphs_by_name.get(key, [])
            if not matches:
                hint = (
                    " (it names a SECTION -- use MOCK SECTION)"
                    if key in sections
                    else ""
                )
                reasons.append(
                    _refusal(
                        "UNRESOLVED_FLOW_MOCK_TARGET",
                        f"{described}: no paragraph named '{key}' in the "
                        f"PROCEDURE DIVISION{hint}",
                    )
                )
                continue
            if len(matches) > 1 or key in sections:
                reasons.append(
                    _refusal(
                        "UNRESOLVED_FLOW_MOCK_TARGET",
                        f"{described}: name '{key}' is ambiguous -- it names "
                        f"more than one paragraph/section, so the mock "
                        f"target cannot be resolved",
                    )
                )
                continue
            target = matches[0]
            header_line = target.location.line
            member_names = [key]
            entry_names = [key]

        # --- entry-hazard checks (see module docstring) --------------------
        problem: str | None = None
        if key in go_to_targets:
            problem = (
                "is a GO TO target somewhere in this program -- a "
                "paragraph/section entered via GO TO falls through past the "
                "dispatch into the relocated real body, running it even "
                "when mocked"
            )
        if problem is None:
            for name in entry_names:
                if name in go_to_targets and is_section:
                    problem = (
                        f"its first paragraph '{name}' is a GO TO target "
                        f"somewhere in this program -- control entering "
                        f"there bypasses the section's mock dispatch"
                    )
                    break
                if name in fallthrough:
                    problem = (
                        f"is reached by falling through past the end of "
                        f"'{fallthrough[name]}' (itself a GO TO target) -- "
                        f"control falling into the header runs the dispatch "
                        f"and then the relocated real body back to back"
                    )
                    break
        if problem is None and not is_section:
            enclosing = paragraph_section.get(key)
            if enclosing is not None and enclosing in flow_target_names:
                problem = (
                    f"belongs to SECTION '{enclosing}', which is itself "
                    f"performed or jumped to as a section -- a performed "
                    f"section executes its paragraphs by fall-through, "
                    f"straight through the mock dispatch into the relocated "
                    f"real body"
                )
        if problem is None and not is_section:
            for case in suite.analysis_cases():
                if paragraph_section.get(key) is not None and paragraph_section[
                    key
                ] in (case.perform_target, case.perform_thru):
                    problem = (
                        f"belongs to SECTION '{paragraph_section[key]}', "
                        f"which test case {case.name!r} uses as its PERFORM "
                        f"entry point -- performing the section executes "
                        f"its paragraphs by fall-through, straight through "
                        f"the mock dispatch"
                    )
                    break
        if problem is None:
            for origin, start, thru in thru_ranges:
                members, range_problem = _expand_thru_range(
                    ordered, start, thru, origin
                )
                if range_problem is not None:
                    problem = (
                        f"cannot be verified against the PERFORM {start} "
                        f"THRU {thru} range ({origin}): "
                        f"{range_problem.message}"
                    )
                    break
                hit = sorted(set(members) & set(member_names))
                straddles = False
                if is_section and not hit and members:
                    member_lines = [
                        line_by_name[m] for m in members if m in line_by_name
                    ]
                    straddles = bool(member_lines) and (
                        min(member_lines) < header_line < max(member_lines)
                    )
                if hit or straddles:
                    problem = (
                        f"lies inside the PERFORM {start} THRU {thru} range "
                        f"({origin}) -- the range's fall-through walk would "
                        f"execute the mock dispatch and the relocated real "
                        f"body back to back"
                    )
                    break

        if problem is None and is_section:
            problem = _qualified_reference_problem(lines, key, member_names)

        # --- header layout --------------------------------------------------
        if problem is None:
            problem = _header_line_problem(lines, header_line, key, is_section)

        if problem is not None:
            reasons.append(
                _refusal(
                    "UNSUPPORTED_FLOW_MOCK_TARGET",
                    f"{described} (line {header_line}) {problem}",
                )
            )
            continue

        plans.append(
            FlowMockPlan(
                category=category,
                key=key,
                header_line=header_line,
                real_name=_real_name(key, index),
            )
        )
    return plans, reasons


def check_flow_mocks(program, suite: MockTestSuite, lines: list[str]) -> list:
    """Thin wrapper over find_flow_mock_plans for the CLI's refusal-gate
    loop, which only needs the refusal reasons (the plans are recomputed
    right before splicing, matching check_terminator_layout's pattern)."""
    return find_flow_mock_plans(program, suite, lines)[1]
