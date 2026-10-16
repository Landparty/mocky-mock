from pathlib import Path

from cobolparser import parse_cobol
from cobolparser.preprocess import normalize_fixed_format

from mockymock.analysis.linkage import address_of_sites, linkage_plan
from mockymock.splicer.linkage import (
    DISCARD_POINTER,
    extra_reset_lines,
    extra_working_storage_lines,
    neutralize,
    redirect_address_of,
)

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
    for idx, (before, after) in enumerate(zip(original, result, strict=True)):
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


# CICS-style shape: LINKAGE SECTION declaring DFHCOMMAREA, no ENTRY at all
# -- see the 2026-08-27 generalization,
# docs/2026-08-27-cics-eib-linkage-support-design.md Part 1.
NO_ENTRY_LINKAGE_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CICSSAMP.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-DONE PIC X VALUE 'N'.

       LINKAGE SECTION.
       01  DFHCOMMAREA.
           05  CA-FIELD PIC X(10).

       PROCEDURE DIVISION.
       0000-MAIN.
           DISPLAY CA-FIELD
           STOP RUN.
"""


def test_neutralize_comments_out_only_linkage_header_when_no_entry():
    program, lines = _parse(NO_ENTRY_LINKAGE_SOURCE)
    plan = linkage_plan(program)
    assert plan.entry_statements == []
    original = list(lines)

    result = neutralize(lines, program, plan)

    assert len(result) == len(original)  # comment-only: no line inserted/removed
    header_idx = plan.header_line - 1
    assert result[header_idx] == "      *> " + original[header_idx]
    for idx, (before, after) in enumerate(zip(original, result, strict=True)):
        if idx == header_idx:
            continue
        assert before == after, f"line {idx + 1} changed unexpectedly"


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


# `SET ADDRESS OF <folded item>`: folding a LINKAGE item into WORKING-STORAGE
# gives it real storage, which is exactly what makes rebinding its address
# illegal afterwards ("cannot change address of 'X', which is not BASED or a
# LINKAGE item"). The IMS DL/I PCB-scheduling idiom does this ~20 times per
# program. Verified against real GnuCOBOL 4.0: the redirected form below
# compiles and runs, the original does not compile at all.
ADDRESS_OF_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CLP100.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-FUNC PIC X(4) VALUE 'GU  '.
       01  WS-SAVE-PTR USAGE POINTER.

       LINKAGE SECTION.
       01  LK-DIB-LIST.
           05  LK-DIB-PTR POINTER OCCURS 10 TIMES.
       01  LKPCB-CLP100MA.
           05  LKPCB-STATUS PIC X(2).

       PROCEDURE DIVISION.
       0000-MAIN.
           PERFORM 7000-SCHEDULE-PSB
           STOP RUN.

       7000-SCHEDULE-PSB.
           CALL 'CBLTDLI' USING WS-FUNC LK-DIB-LIST
           SET ADDRESS OF LKPCB-CLP100MA TO LK-DIB-PTR(2)
           SET WS-SAVE-PTR TO ADDRESS OF LKPCB-CLP100MA.
"""


def _address_of(source: str = ADDRESS_OF_SOURCE):
    program, lines = _parse(source, "CLP100.cbl")
    plan = linkage_plan(program)
    assert plan is not None
    sites, problems = address_of_sites(lines, plan)
    return lines, plan, sites, problems


def test_address_of_sites_finds_only_the_receiving_side():
    lines, _, sites, problems = _address_of()
    assert problems == []
    assert [site.item_name for site in sites] == ["LKPCB-CLP100MA"]
    site = sites[0]
    # The span covers exactly `ADDRESS OF <name>`, nothing of the SET or the
    # pointer being read.
    text = lines[site.line - 1]
    assert text[site.start_column : site.end_column] == "ADDRESS OF LKPCB-CLP100MA"
    # ...and it is the receiving-side statement, not the `SET ptr TO ADDRESS
    # OF item` one on the following line, which stays legal after the fold.
    assert text.strip().startswith("SET ADDRESS OF")


def test_address_of_sites_ignores_items_that_are_not_folded():
    _, _, sites, problems = _address_of(
        ADDRESS_OF_SOURCE.replace(
            "SET ADDRESS OF LKPCB-CLP100MA TO LK-DIB-PTR(2)",
            "SET ADDRESS OF WS-OTHER-REC   TO LK-DIB-PTR(2)",
        )
    )
    assert sites == []
    assert problems == []


def test_redirect_address_of_preserves_every_line_and_column():
    lines, _, sites, _ = _address_of()
    original = list(lines)

    result = redirect_address_of(lines, sites)

    assert len(result) == len(original)
    changed = [
        i for i, (a, b) in enumerate(zip(original, result, strict=True)) if a != b
    ]
    assert changed == [sites[0].line - 1]
    before, after = original[changed[0]], result[changed[0]]
    assert len(before) == len(after)  # width-preserving: no column moves
    assert DISCARD_POINTER in after
    assert "ADDRESS OF" not in after
    # The pointer operand is untouched, so the statement still reads the same
    # source -- only the receiving item changed.
    assert after.rstrip().endswith("TO LK-DIB-PTR(2)")


def test_redirect_address_of_leaves_the_value_side_statement_alone():
    lines, _, sites, _ = _address_of()
    result = redirect_address_of(lines, sites)
    assert any(
        "SET WS-SAVE-PTR TO ADDRESS OF LKPCB-CLP100MA" in line for line in result
    )


def test_extra_working_storage_declares_the_sink_pointer_only_when_needed():
    _, _, sites, _ = _address_of()
    declared = extra_working_storage_lines(sites)
    assert len(declared) == 1
    assert DISCARD_POINTER in declared[0]
    assert "POINTER" in declared[0]
    assert extra_working_storage_lines([]) == []


# Deliberately short names: two SET statements on one line still have to fit
# inside fixed-format Area B (columns 12-72).
TWO_SITES_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TWOSITE.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  P1 USAGE POINTER.
       01  P2 USAGE POINTER.

       LINKAGE SECTION.
       01  LK-A PIC X(2).
       01  LK-B PIC X(2).

       PROCEDURE DIVISION.
       0000-MAIN.
           SET ADDRESS OF LK-A TO P1 SET ADDRESS OF LK-B TO P2
           STOP RUN.
"""


def test_two_sites_on_one_line_are_both_rewritten():
    """Applied right-to-left, so the first rewrite cannot invalidate the
    second one's columns."""
    lines, _, sites, problems = _address_of(TWO_SITES_SOURCE)
    assert problems == []
    assert [site.item_name for site in sites] == ["LK-A", "LK-B"]
    assert len({site.line for site in sites}) == 1

    original = list(lines)
    result = redirect_address_of(lines, sites)

    rewritten = result[sites[0].line - 1]
    assert "ADDRESS OF" not in rewritten
    assert rewritten.count(DISCARD_POINTER) == 2
    assert len(rewritten) == len(original[sites[0].line - 1])
    assert "TO P1" in rewritten and "TO P2" in rewritten


def test_address_of_continued_onto_the_next_line_is_reported_not_guessed():
    _, _, sites, problems = _address_of(
        ADDRESS_OF_SOURCE.replace(
            "SET ADDRESS OF LKPCB-CLP100MA TO LK-DIB-PTR(2)",
            "SET ADDRESS OF\n               LKPCB-CLP100MA TO LK-DIB-PTR(2)",
        )
    )
    assert sites == []
    assert any("continued onto the next line" in problem for problem in problems)


# The two shapes a real CICS-DL/I program (HY1130IC) was refused for, with
# neither being a `SET` rebind: an `EXEC CICS ADDRESS` operand (the whole
# block is replaced by a mock/trap stub, so it never reaches cobc) and the
# UIB-returning `CALL 'CBLTDLI' USING ... ADDRESS OF DLIUIB` argument, split
# from its CALL across lines (legal on a WORKING-STORAGE item -- verified
# against GnuCOBOL 3.1.2).
CICS_DLI_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. HY1130IC.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  PCB-FUNC PIC X(4) VALUE 'PCB '.
       01  PSB-NAME PIC X(8) VALUE 'HY1130  '.

       LINKAGE SECTION.
       01  DLIUIB.
           05  UIBPCBAL POINTER.
       01  TCTUA.
           05  TCTUA-DATA PIC X(10).

       PROCEDURE DIVISION.
       0000-MAIN.
           EXEC CICS ADDRESS
                     TCTUA (ADDRESS OF TCTUA)
           END-EXEC.
           CALL 'CBLTDLI' USING PCB-FUNC PSB-NAME
                ADDRESS OF DLIUIB.
           STOP RUN.
"""


def test_exec_operands_and_call_arguments_are_neither_sites_nor_problems():
    # cobolparser 1.8.x warns on (and drops) `USING ... ADDRESS OF X`; the
    # scan under test is textual, so only a clean parse error-wise matters.
    result = parse_cobol(CICS_DLI_SOURCE, filename="HY1130IC.cbl")
    assert result.success, result.errors
    lines = normalize_fixed_format(CICS_DLI_SOURCE.splitlines()).splitlines()
    plan = linkage_plan(result.ast)
    assert plan is not None
    sites, problems = address_of_sites(lines, plan)
    assert sites == []
    assert problems == []


def test_a_set_target_list_continued_onto_the_next_line_is_still_rewritten():
    """The SET keyword need not share a line with the receiving operand: only
    the `ADDRESS OF <item>` span itself has to fit on one line."""
    lines, _, sites, problems = _address_of(
        ADDRESS_OF_SOURCE.replace(
            "SET ADDRESS OF LKPCB-CLP100MA TO LK-DIB-PTR(2)",
            "SET WS-SAVE-PTR\n               ADDRESS OF LKPCB-CLP100MA "
            "TO LK-DIB-PTR(2)",
        )
    )
    assert problems == []
    assert [site.item_name for site in sites] == ["LKPCB-CLP100MA"]
    text = lines[sites[0].line - 1]
    assert text[sites[0].start_column : sites[0].end_column] == (
        "ADDRESS OF LKPCB-CLP100MA"
    )


def test_a_value_side_address_of_continued_onto_the_next_line_is_legal():
    _, _, sites, problems = _address_of(
        ADDRESS_OF_SOURCE.replace(
            "SET WS-SAVE-PTR TO ADDRESS OF LKPCB-CLP100MA.",
            "SET WS-SAVE-PTR TO\n               ADDRESS OF LKPCB-CLP100MA.",
        )
    )
    assert problems == []
    assert [site.item_name for site in sites] == ["LKPCB-CLP100MA"]  # line 1 only


REBIND_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. LK.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-BUF                PIC X(10) VALUE "HELLOWORLD".
       01  WS-PTR                USAGE POINTER.
       01  WS-OUT                PIC X(5) VALUE SPACES.
       01  WS-OUT2               PIC X(5) VALUE SPACES.
       LINKAGE SECTION.
       01  LK-PARM               PIC X(3).
       01  LK-VIEW               PIC X(10).
       01  LK-PCB                PIC X(4).
       01  LK-UIB.
           05  LK-PCBAL          USAGE POINTER.
       PROCEDURE DIVISION USING LK-PARM.
       0000-MAIN.
           SET WS-PTR TO ADDRESS OF WS-BUF
           SET ADDRESS OF LK-VIEW TO WS-PTR
           MOVE LK-VIEW(1:5) TO WS-OUT
           GOBACK.
       1000-DIRECT.
           SET ADDRESS OF LK-VIEW TO ADDRESS OF WS-BUF
           MOVE LK-VIEW(6:5) TO WS-OUT2
           MOVE "XY" TO LK-VIEW(1:2).
       2000-PSB.
           CALL "CBLTDLI" USING LK-PARM ADDRESS OF LK-UIB
           SET ADDRESS OF LK-PCB TO LK-PCBAL
           MOVE LK-PCB TO WS-OUT.
       3000-PEEK.
           MOVE LK-VIEW(1:5) TO WS-OUT.
"""

REBIND_CUT = """\
TESTSUITE "lk"
BEFORE-ALL
    PERFORM 1000-DIRECT
END-BEFORE
TESTCASE "addr"
    PERFORM 0000-MAIN
    EXPECT WS-OUT TO BE "HELLO"
"""


def test_set_address_of_to_a_program_address_is_a_real_rebind(tmp_path):
    """Issue #226 (option 1, with the mocked-boundary exception): a folded
    item the program re-addresses at its own storage -- ADDRESS OF an item,
    or a pointer it only ever SETs to an ADDRESS OF -- becomes BASED over
    its own backing storage, so reads through it see the data it points
    at. A rebind to a pointer anything else fills (LK-PCBAL, written by
    the mocked CBLTDLI) keeps the redirect into UT-ADDR-SINK."""
    from mockymock.cli.checks import extra_working_storage, run_static_checks
    from mockymock.splicer.linkage import extra_reset_lines

    cbl = tmp_path / "LK.cbl"
    cbl.write_text(REBIND_SOURCE)
    cut = tmp_path / "LK.cut"
    cut.write_text(REBIND_CUT)
    checked = run_static_checks(cbl, cut, None)
    assert checked.problems == []
    assert checked.lines is not None and checked.linkage is not None
    assert any("01  LK-VIEW BASED" in line for line in checked.lines)
    assert not any("LK-PCB BASED" in line for line in checked.lines)
    assert [site.item_name for site in checked.linkage_address_of] == ["LK-PCB"]
    assert any("SET ADDRESS OF LK-VIEW TO WS-PTR" in line for line in checked.lines)
    assert any("SET UT-ADDR-SINK" in line for line in checked.lines)

    [rebinding] = checked.linkage.rebindings
    assert rebinding.item_name == "LK-VIEW"
    assert rebinding.size >= 10
    assert f"01  UT-LKB-001  PIC X({rebinding.size})." in (
        extra_working_storage(checked) or []
    )
    reset = extra_reset_lines(checked.linkage)
    assert reset[0] == "SET ADDRESS OF LK-VIEW TO ADDRESS OF UT-LKB-001"
    assert checked.snapshot is not None
    assert checked.snapshot.save_lines[0] == "SET UT-SNAP-001 TO ADDRESS OF LK-VIEW"
    assert checked.snapshot.restore_lines[0] == "SET ADDRESS OF LK-VIEW TO UT-SNAP-001"
