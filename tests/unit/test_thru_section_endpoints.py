"""A THRU range whose endpoints are SECTIONs (NIST ST108A's `SORT ...
OUTPUT PROCEDURE OUTPROC THRU OUTPROC-EXIT`, 2026-11-03)."""

from cobolparser import parse_cobol

from mockymock.analysis.refusal._reachability import (
    _expand_thru_range,
    _source_ordered_paragraphs,
)

SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SECTHRU.
       PROCEDURE DIVISION.
       MAIN SECTION.
       M1.
           PERFORM OUTPROC THRU OUTPROC-EXIT
           STOP RUN.
       OUTPROC SECTION.
       O1.
           DISPLAY "O1".
       O2.
           DISPLAY "O2".
       MIDDLE SECTION.
       X1.
           DISPLAY "X1".
       OUTPROC-EXIT SECTION.
       E1.
           EXIT.
       AFTER-ALL SECTION.
       Z1.
           DISPLAY "Z1".
"""


def _ordered():
    result = parse_cobol(SOURCE, filename="secthru.cbl")
    assert result.success, result.errors
    return _source_ordered_paragraphs(result.ast.get_division("PROCEDURE"))


def test_a_section_range_runs_from_the_first_sections_start_to_the_last_ones_end():
    members, reason = _expand_thru_range(_ordered(), "OUTPROC", "OUTPROC-EXIT", "t")
    assert reason is None
    assert members[:4] == ["O1", "O2", "X1", "E1"]
    assert set(members[4:]) == {"OUTPROC", "MIDDLE", "OUTPROC-EXIT"}
    assert "Z1" not in members and "AFTER-ALL" not in members


def test_a_section_may_end_a_range_that_starts_at_a_paragraph():
    members, reason = _expand_thru_range(_ordered(), "O2", "MIDDLE", "t")
    assert reason is None
    assert [m for m in members if m in ("O1", "O2", "X1")] == ["O2", "X1"]
    assert "MIDDLE" in members and "OUTPROC" not in members


def test_an_unknown_endpoint_still_refuses():
    _, reason = _expand_thru_range(_ordered(), "NOPE", "OUTPROC-EXIT", "t")
    assert reason is not None and "'NOPE' not found" in reason.message
