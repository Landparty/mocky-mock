from pathlib import Path

from cobolparser import parse_cobol
from cobolparser.preprocess import normalize_fixed_format

from mockymock.analysis.linkage import linkage_plan
from mockymock.splicer.linkage import extra_reset_lines, neutralize

QUALIFYING_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. IMSSAMP.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-DONE PIC X VALUE 'N'.

       LINKAGE SECTION.
       01  CUST-PCB-LNK.
           05  CUST-DBD-NAME     PIC X(08).
           05  CUST-STATUS       PIC X(02).

       PROCEDURE DIVISION.
       ENTRY 'DLITCBL' USING CUST-PCB-LNK.
       0000-MAIN.
           EVALUATE CUST-STATUS
               WHEN '  '
                   DISPLAY 'OK'
               WHEN OTHER
                   DISPLAY 'OTHER'
           END-EVALUATE
           STOP RUN.
"""


def _parse(source: str, name: str = "SAMP.cbl"):
    result = parse_cobol(source, filename=name)
    assert result.success, result.errors
    assert not result.warnings
    lines = normalize_fixed_format(source.splitlines()).splitlines()
    return result.ast, lines


def test_neutralize_comments_out_entry_and_linkage_header_only():
    program, lines = _parse(QUALIFYING_SOURCE)
    plan = linkage_plan(program)
    original = list(lines)

    result = neutralize(lines, program, plan)

    assert len(result) == len(original)  # comment-only: no line inserted/removed
    header_idx = plan.header_line - 1
    assert result[header_idx] == "      *> " + original[header_idx]
    entry_line = plan.entry_statements[0].location.line
    assert result[entry_line - 1] == "      *> " + original[entry_line - 1]
    # Everything else, including the LINKAGE data items themselves and the
    # PROCEDURE DIVISION/paragraph lines, is untouched.
    for idx, (before, after) in enumerate(zip(original, result)):
        if idx in (header_idx, entry_line - 1):
            continue
        assert before == after, f"line {idx + 1} changed unexpectedly"


def test_extra_reset_lines_covers_every_linkage_item():
    program, _ = _parse(QUALIFYING_SOURCE)
    plan = linkage_plan(program)
    lines = extra_reset_lines(plan)
    # CUST-PCB-LNK is a VALUE-less group -> INITIALIZE, no children carry a
    # VALUE clause here so no follow-up MOVE lines (matches reset.py's
    # existing group-without-VALUE behavior).
    assert lines == ["INITIALIZE CUST-PCB-LNK"]


def test_neutralize_against_real_acctprg_source():
    acctprg = (
        Path(__file__).parent.parent.parent.parent
        / "legacy-application"
        / "cobol"
        / "ACCTPRG.cbl"
    )
    if not acctprg.is_file():
        import pytest

        pytest.skip("sibling legacy-application repo not present")
    raw = acctprg.read_text(encoding="utf-8", errors="replace")
    result = parse_cobol(raw, filename="ACCTPRG.cbl")
    assert result.success
    lines = normalize_fixed_format(raw.splitlines()).splitlines()
    plan = linkage_plan(result.ast)
    assert plan is not None
    assert [e.entry_name for e in plan.entry_statements] == ["DLITCBL"]
    assert lines[plan.header_line - 1].strip().upper() == "LINKAGE SECTION."

    neutralized = neutralize(lines, result.ast, plan)
    assert neutralized[plan.header_line - 1].startswith("      *> LINKAGE SECTION")
    entry_line = plan.entry_statements[0].location.line
    assert neutralized[entry_line - 1].startswith("      *> ENTRY 'DLITCBL'")
    # The LINKAGE data items themselves are untouched, just re-parented by
    # the now-missing section header.
    assert neutralized[entry_line] == lines[entry_line]  # first paragraph header
