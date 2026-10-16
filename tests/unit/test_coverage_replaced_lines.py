"""Issue #297: a statement the splicer replaced -- a mocked boundary, a
neutralized GOBACK -- keeps its place in the original-file coverage view.
It counts as executed exactly when its replacement block ran, so an
untaken CALL-only branch is no longer read as 100% covered."""

from __future__ import annotations

from cobolparser.preprocess import normalize_fixed_format

from mockymock._lines import split_source_lines
from mockymock.report.coverage import (
    CoverageReport,
    UncoveredLine,
    build_original_line_map,
    map_coverage_to_original,
)
from mockymock.splicer.stub_writer import comment_and_replace

ORIGINAL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. COV1.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A                 PIC 9(2) VALUE 0.
       PROCEDURE DIVISION.
       0000-MAIN.
           ADD 1 TO WS-A
           IF WS-A > 5
               CALL "AUDITLOG" USING WS-A
           END-IF
           GOBACK.
""".splitlines()


def _instrumented() -> tuple[list[str], list[str]]:
    normalized = split_source_lines(normalize_fixed_format(ORIGINAL))
    call_at = next(i for i, text in enumerate(normalized) if "AUDITLOG" in text) + 1
    goback_at = next(i for i, text in enumerate(normalized) if "GOBACK" in text) + 1
    lines = comment_and_replace(
        normalized,
        goback_at,
        goback_at,
        ['           MOVE "Y" TO UT-EARLY-EXIT', "           EXIT PARAGRAPH."],
    )
    lines = comment_and_replace(
        lines,
        call_at,
        call_at,
        [
            "           EVALUATE UT-CURRENT-CASE",
            '               WHEN "001"',
            "                   CONTINUE",
            "           END-EVALUATE",
        ],
    )
    driver = ["UT-DRIVER.", '           DISPLAY "START"']
    return driver + lines, normalized


def test_replacement_blocks_map_to_the_statement_they_replace() -> None:
    instrumented, normalized = _instrumented()
    mapping = build_original_line_map(instrumented, normalized, ORIGINAL)
    evaluate = instrumented.index("           EVALUATE UT-CURRENT-CASE") + 1
    exit_paragraph = instrumented.index("           EXIT PARAGRAPH.") + 1
    assert mapping[evaluate] == 10  # the CALL
    assert mapping[exit_paragraph] == 12  # the GOBACK
    assert 1 not in mapping and 2 not in mapping  # driver code


def test_untaken_boundary_branch_is_reported_uncovered() -> None:
    instrumented, normalized = _instrumented()

    def at(text: str) -> int:
        return instrumented.index(text) + 1

    ran = [
        at("    ADD 1 TO WS-A"),
        at("    IF WS-A > 5"),
        at('           MOVE "Y" TO UT-EARLY-EXIT'),
    ]
    not_ran = [at("           EVALUATE UT-CURRENT-CASE")]
    report = CoverageReport(
        total_executable=len(ran) + len(not_ran),
        total_covered=len(ran),
        uncovered_lines=[UncoveredLine(line_number=n, text="") for n in not_ran],
        covered_lines=ran,
    )
    mapped = {
        line.line: line.covered
        for line in map_coverage_to_original(report, instrumented, normalized, ORIGINAL)
    }
    assert mapped[10] is False  # the CALL never ran
    assert mapped[12] is True  # the GOBACK did
