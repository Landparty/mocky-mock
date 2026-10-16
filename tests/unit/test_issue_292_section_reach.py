"""Issue #292: a TESTCASE that PERFORMs a SECTION reached only the section
name (its paragraphs hang off it by FALL_THROUGH edges, which reach
ignores), so its paragraphs read "No test reaches P2" and their dialect
risks never blocked L3. And a statement directly under a SECTION header
was attributed to the previous section's paragraph."""

from __future__ import annotations

from cobolparser import parse_cobol

from mockymock.analysis.dialect_risk import find_dialect_risks
from mockymock.report.test_report import ReportOptions, build_report

HEADERLESS = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SEC.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A                PIC 9(3) VALUE 10.
       01  WS-B                PIC 9(3) VALUE 0.
       PROCEDURE DIVISION.
       S1 SECTION.
       P1.
           MOVE 7 TO WS-B.
       S2 SECTION.
           DIVIDE 2 INTO WS-A.
"""

WITH_P2 = HEADERLESS.replace("       S2 SECTION.\n", "       S2 SECTION.\n       P2.\n")

CUT = """\
TESTSUITE "sec"
TESTCASE "s2 divides"
    PERFORM S2
    EXPECT WS-A TO BE 5
TESTCASE "p1 moves"
    PERFORM P1
    EXPECT WS-B TO BE 7
"""


def _risk_paragraphs(source: str) -> set[str | None]:
    ast = parse_cobol(source, filename="sec.cbl").ast
    return {r.paragraph for r in find_dialect_risks(ast, source.splitlines(), None)}


def test_statement_under_a_section_header_belongs_to_that_section() -> None:
    paragraphs = _risk_paragraphs(HEADERLESS)
    assert paragraphs, "expected the DIVIDE to raise a dialect risk"
    assert paragraphs == {"S2"}
    assert _risk_paragraphs(WITH_P2) == {"P2"}


def _report(tmp_path, source: str):
    (tmp_path / "SEC.cbl").write_text(source)
    (tmp_path / "SEC.cut").write_text(CUT)
    return build_report(
        ReportOptions(
            program=tmp_path / "SEC.cbl",
            cut=tmp_path / "SEC.cut",
            probe_toolchain=False,
            scenarios="none",
        )
    )


def test_performing_a_section_reaches_its_paragraphs(tmp_path) -> None:
    report = _report(tmp_path, WITH_P2)
    cases = {c["name"]: c for c in report["cases"]}
    assert "P2" in cases["s2 divides"]["reach"]
    assert [r["paragraph"] for r in cases["s2 divides"]["risks"]] == ["P2"]
    assert cases["p1 moves"]["risks"] == []
    titles = [f["title"] for f in report["findings"]]
    assert "No test reaches P2" not in titles


def test_headerless_section_risk_is_charged_to_the_case_that_runs_it(tmp_path):
    report = _report(tmp_path, HEADERLESS)
    cases = {c["name"]: c for c in report["cases"]}
    assert [r["paragraph"] for r in cases["s2 divides"]["risks"]] == ["S2"]
    assert cases["p1 moves"]["risks"] == []
