"""Statements whose GnuCOBOL result may differ from IBM Enterprise COBOL's.

mockymock runs the program under GnuCOBOL (`-std=mvs`), which is the right
everyday oracle -- a real compile and a real run -- but not IBM Enterprise
COBOL. A small, well-known set of constructs behaves differently between
the two, and a test that touches one has only been proven on GnuCOBOL.
`mockymock export`'s provenance header lists those gaps in prose; this
module finds them in a specific program, so `mockymock report` can say
*which* test cases they touch instead of disclaiming every case equally.

Fail-honest in the same spirit as the refusal gate: it flags, it never
rewrites, and a construct it cannot classify (an operand whose PICTURE it
cannot resolve) is simply not flagged -- the report states that the check
is heuristic. Severities:

* ``high``   -- the result almost certainly differs (a hex literal names
  bytes, and the same bytes are different characters in EBCDIC and ASCII).
* ``medium`` -- the result differs for some data (collating order,
  overpunched signs, intermediate precision, clock-dependent values).
* ``low``    -- depends on compiler options the shop chose (TRUNC) or on
  an intrinsic's corner cases; worth knowing, not worth blocking on.

A test case reaching a ``high`` or ``medium`` risk cannot be reported at
verification level L3 ("dialect-checked") -- see report/test_report.py.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

HIGH = "high"
MEDIUM = "medium"
LOW = "low"
SEVERITY_ORDER = {HIGH: 0, MEDIUM: 1, LOW: 2}
BLOCKING_SEVERITIES = frozenset({HIGH, MEDIUM})

_ORDERING_OPERATORS = frozenset(
    {"LESS", "GREATER", "LESS_OR_EQUAL", "GREATER_OR_EQUAL", "<", ">", "<=", ">="}
)
_NESTED_STATEMENT_KEYS = frozenset(
    {"statements", "then_statements", "else_statements", "inline_statements"}
)
_FUNCTION_RE = re.compile(r"\bFUNCTION\s+([A-Z][A-Z0-9-]*)", re.IGNORECASE)
_HEX_LITERAL_RE = re.compile(r"""(?<![A-Z0-9-])X(['"])[0-9A-F]+\1""", re.IGNORECASE)
_CLOCK_FUNCTIONS = frozenset({"CURRENT-DATE", "WHEN-COMPILED", "RANDOM"})
_ARITHMETIC_TYPES = frozenset({"ADD", "SUBTRACT", "MULTIPLY", "DIVIDE", "COMPUTE"})

MESSAGES: dict[str, str] = {
    "HEX_LITERAL": (
        "A hex literal names bytes, and the same bytes are a different "
        "character in EBCDIC and ASCII (X'C1' is 'A' on z/OS, not on "
        "GnuCOBOL)."
    ),
    "EBCDIC_COLLATION": (
        "Ordering comparison on alphanumeric data: EBCDIC sorts lowercase "
        "before uppercase before digits, ASCII the reverse, so the branch "
        "taken can differ for data mixing letters and digits."
    ),
    "SORT_COLLATION": (
        "SORT/MERGE orders alphanumeric keys by the native collating "
        "sequence: EBCDIC on z/OS, ASCII on GnuCOBOL."
    ),
    "SEARCH_ALL_COLLATION": (
        "SEARCH ALL assumes the table is in key order; an alphanumeric key "
        "ordered for EBCDIC is out of order under ASCII (and vice versa)."
    ),
    "SIGN_OVERPUNCH": (
        "MOVE between signed zoned-decimal and alphanumeric data: the sign "
        "is overpunched into the last byte, and that byte's character "
        "differs between EBCDIC and ASCII."
    ),
    "INTERMEDIATE_PRECISION": (
        "Division or exponentiation: IBM Enterprise COBOL and GnuCOBOL size "
        "intermediate results differently, so trailing digits or a ROUNDED "
        "result can differ."
    ),
    "CLOCK_DEPENDENT": (
        "Value depends on the clock or the compile; anything derived from it "
        "changes from run to run unless the test pins it."
    ),
    "BINARY_TRUNCATION": (
        "Arithmetic into a COMP/BINARY item: whether a result wider than "
        "the PICTURE is truncated depends on the TRUNC option (GnuCOBOL "
        "-std=mvs behaves like TRUNC(STD))."
    ),
    "NUMERIC_EDITED": (
        "MOVE into a numeric-edited item: edited output (CR/DB, floating "
        "insertion, BLANK WHEN ZERO) has small dialect differences."
    ),
    "INTRINSIC": (
        "Intrinsic function: precision and corner cases are implementation "
        "defined; compare one value against a mainframe run."
    ),
}


@dataclass
class DialectRisk:
    code: str
    severity: str
    line: int | None  # line in the original .cbl, None when inside a copybook
    paragraph: str | None
    statement: str
    detail: str

    @property
    def message(self) -> str:
        return MESSAGES[self.code]

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "line": self.line,
            "paragraph": self.paragraph,
            "statement": self.statement,
            "detail": self.detail,
            "message": self.message,
        }


@dataclass
class _Item:
    usage: str
    pattern: str | None
    signed: bool
    edited: bool
    sign_separate: bool
    group: bool

    @property
    def alphanumeric(self) -> bool:
        if self.group:
            return True
        return self.pattern is not None and bool(re.search(r"[XA]", self.pattern))

    @property
    def zoned_signed(self) -> bool:
        return (
            self.usage == "DISPLAY"
            and self.signed
            and not self.sign_separate
            and not self.edited
            and not self.group
        )

    @property
    def binary(self) -> bool:
        return self.usage in {
            "COMP",
            "COMP-4",
            "BINARY",
            "COMPUTATIONAL",
            "COMPUTATIONAL-4",
        }


def _base_name(operand: Any) -> str | None:
    if not isinstance(operand, str):
        return None
    text = operand.strip()
    if not text or text[0] in "'\"" or text[0].isdigit() or text[0] in "+-.":
        return None
    return re.split(r"[\s(]", text, maxsplit=1)[0].upper()


def _data_dictionary(ast: Any) -> dict[str, _Item]:
    items: dict[str, _Item] = {}
    for node in ast.find_all_by_type("CobolDataItem"):
        name = getattr(node, "name", None)
        if not name or getattr(node, "is_filler", False):
            continue
        pc = getattr(node, "picture_clause", None)
        usage = str(getattr(node, "usage", "") or "DISPLAY").upper()
        items.setdefault(
            name.upper(),
            _Item(
                usage=usage,
                pattern=getattr(pc, "pattern", None) if pc else None,
                signed=bool(getattr(pc, "is_signed", False)) if pc else False,
                edited=bool(getattr(pc, "is_edited", False)) if pc else False,
                sign_separate="SEPARATE"
                in str(getattr(node, "sign_clause", "") or "").upper(),
                group=bool(getattr(node, "is_group_item", False)) and pc is None,
            ),
        )
    return items


def _walk_comparisons(node: Any) -> list[dict[str, Any]]:
    """Every COMPARISON dict under one statement's own dict, not descending
    into nested statement lists (those statements are visited on their own,
    so descending would report them twice at the outer statement's line)."""
    found: list[dict[str, Any]] = []
    if isinstance(node, dict):
        if node.get("operator") in _ORDERING_OPERATORS and "left_operand" in node:
            found.append(node)
        for key, value in node.items():
            if key in _NESTED_STATEMENT_KEYS:
                continue
            found.extend(_walk_comparisons(value))
    elif isinstance(node, list):
        for value in node:
            found.extend(_walk_comparisons(value))
    return found


def _shallow_dict(statement_dict: dict[str, Any]) -> dict[str, Any]:
    """*statement_dict* without the statements nested in it, at any depth.

    A SEARCH's WHEN bodies sit under ``when_clauses[].statements`` and its
    AT END body under ``at_end_clause``; those statements are visited on
    their own, so scanning them again here reported them at the SEARCH line
    (#453)."""
    stripped = _strip_nested_statements(
        {k: v for k, v in statement_dict.items() if k not in _NESTED_STATEMENT_KEYS}
    )
    return stripped if isinstance(stripped, dict) else {}


def _strip_nested_statements(node: Any) -> Any:
    if isinstance(node, dict):
        return {
            k: _strip_nested_statements(v)
            for k, v in node.items()
            if k not in _NESTED_STATEMENT_KEYS and not _is_statement(v)
        }
    if isinstance(node, list):
        return [_strip_nested_statements(v) for v in node if not _is_statement(v)]
    return node


def _is_statement(node: Any) -> bool:
    """A serialized statement (or a list of them) nested in another one."""
    if isinstance(node, dict):
        return "statement_type" in node
    if isinstance(node, list) and node:
        return all(isinstance(v, dict) and "statement_type" in v for v in node)
    return False


def _is_alphanumeric_operand(operand: Any, items: dict[str, _Item]) -> bool:
    if not isinstance(operand, str):
        return False
    text = operand.strip()
    if len(text) >= 2 and text[0] in "'\"" and text[-1] == text[0]:
        return not re.fullmatch(r"[+-]?\d+(\.\d+)?", text[1:-1])
    name = _base_name(text)
    item = items.get(name) if name else None
    return item is not None and item.alphanumeric


def find_dialect_risks(
    ast: Any,
    original_lines: list[str],
    line_map: dict[int, int] | None = None,
) -> list[DialectRisk]:
    """Every dialect risk in `ast`'s PROCEDURE DIVISION.

    `line_map` maps a 1-based line of the source the AST was parsed from
    (the copybook-expanded text, when copybooks were expanded) to its
    1-based line in `original_lines`; `None` means the AST was parsed from
    `original_lines` itself. A statement with no original line (it came
    from a copybook) is still reported, with `line` None.
    """
    items = _data_dictionary(ast)

    def to_original(line: int) -> int | None:
        if line_map is None:
            return line if 0 < line <= len(original_lines) else None
        return line_map.get(line)

    # Sections count as owners too: statements written directly under a
    # SECTION header (cobol-parser's unnamed paragraph, left out here)
    # belong to that section, not to the previous section's last
    # paragraph (issue #292).
    paragraphs = sorted(
        (p.location.line, name)
        for p in ast.get_procedures()
        if getattr(p, "location", None) is not None
        and (
            name := getattr(p, "paragraph_name", None)
            or getattr(p, "section_name", None)
            or ""
        )
    )

    def paragraph_at(line: int) -> str | None:
        current = None
        for start, name in paragraphs:
            if start > line:
                break
            current = name
        return current

    risks: list[DialectRisk] = []
    seen: set[tuple[str, int]] = set()

    def add(code: str, severity: str, line: int, statement: str, detail: str) -> None:
        key = (code, line)
        if key in seen:
            return
        seen.add(key)
        risks.append(
            DialectRisk(
                code=code,
                severity=severity,
                line=to_original(line),
                paragraph=paragraph_at(line),
                statement=statement,
                detail=detail,
            )
        )

    for statement in ast.get_all_statements():
        location = getattr(statement, "location", None)
        line = getattr(location, "line", 0) or 0
        if line <= 0:
            continue
        data = statement.to_dict()
        kind = str(data.get("statement_type") or type(statement).__name__).upper()
        shallow = _shallow_dict(data)

        if kind in {"SORT", "MERGE"}:
            add("SORT_COLLATION", MEDIUM, line, kind, f"{kind} statement")
        # cobol-parser flags SEARCH ALL in the statement's metadata; a
        # substring test over the whole SEARCH matched any serial SEARCH
        # naming WS-SMALL-K or displaying 'ALLOWED' (#453).
        metadata = data.get("metadata") or {}
        if kind == "SEARCH" and metadata.get("is_search_all"):
            add("SEARCH_ALL_COLLATION", MEDIUM, line, kind, "SEARCH ALL")

        for comparison in _walk_comparisons(shallow):
            left = comparison.get("left_operand")
            right = comparison.get("right_operand")
            if _is_alphanumeric_operand(left, items) or _is_alphanumeric_operand(
                right, items
            ):
                add(
                    "EBCDIC_COLLATION",
                    MEDIUM,
                    line,
                    kind,
                    f"{left} {comparison.get('operator')} {right}",
                )

        for function in _FUNCTION_RE.findall(json.dumps(shallow)):
            name = function.upper()
            if name in _CLOCK_FUNCTIONS:
                add("CLOCK_DEPENDENT", MEDIUM, line, kind, f"FUNCTION {name}")
            else:
                add("INTRINSIC", LOW, line, kind, f"FUNCTION {name}")

        if kind == "COMPUTE":
            expression = str(data.get("expression") or "")
            if "/" in expression or "**" in expression:
                add("INTERMEDIATE_PRECISION", MEDIUM, line, kind, expression)
        elif kind == "DIVIDE":
            add("INTERMEDIATE_PRECISION", MEDIUM, line, kind, "DIVIDE")

        targets = [t for t in (data.get("targets") or []) if isinstance(t, str)]
        targets += [g for g in (data.get("givings") or []) if isinstance(g, str)]
        target_items = [
            (t, items[n]) for t in targets if (n := _base_name(t)) and n in items
        ]
        if kind in _ARITHMETIC_TYPES:
            for target, item in target_items:
                if item.binary:
                    add("BINARY_TRUNCATION", LOW, line, kind, f"into {target}")
        if kind == "MOVE":
            source = data.get("source")
            source_name = _base_name(source)
            source_item = items.get(source_name) if source_name else None
            for target, item in target_items:
                if item.edited:
                    add("NUMERIC_EDITED", LOW, line, kind, f"MOVE {source} TO {target}")
                if source_item is None:
                    continue
                if (source_item.zoned_signed and item.alphanumeric) or (
                    source_item.alphanumeric and item.zoned_signed
                ):
                    add(
                        "SIGN_OVERPUNCH",
                        MEDIUM,
                        line,
                        kind,
                        f"MOVE {source} TO {target}",
                    )

    in_procedure = False
    for number, raw in enumerate(original_lines, start=1):
        code = raw[6:72] if len(raw) > 6 else ""
        if len(raw) > 6 and raw[6] in "*/":
            continue
        if re.search(r"\bPROCEDURE\s+DIVISION\b", code, re.IGNORECASE):
            in_procedure = True
            continue
        if not in_procedure:
            continue
        match = _HEX_LITERAL_RE.search(code)
        if match and ("HEX_LITERAL", -number) not in seen:
            seen.add(("HEX_LITERAL", -number))
            expanded_line = next(
                (k for k, v in (line_map or {}).items() if v == number), number
            )
            risks.append(
                # Positional, not `code=`: dialect risks are not refusal
                # codes (tests/unit/test_refusal_explanations.py scans for
                # that keyword).
                DialectRisk(
                    "HEX_LITERAL",
                    HIGH,
                    line=number,
                    paragraph=paragraph_at(expanded_line),
                    statement="literal",
                    detail=match.group(0),
                )
            )

    risks.sort(
        key=lambda r: (
            SEVERITY_ORDER[r.severity],
            r.line if r.line is not None else 10**9,
            r.code,
        )
    )
    return risks
