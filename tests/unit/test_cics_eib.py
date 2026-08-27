from cobolparser import parse_cobol
from cobolparser.preprocess import normalize_fixed_format

from mockymock.analysis.cics_eib import cics_eib_plan
from mockymock.analysis.refusal import check_cics_eib_layout
from mockymock.splicer.cics_eib import reset_lines, working_storage_lines

# Mirrors CUSTINQ's real shape (examples/custinq/CUSTINQ.cbl) plus the
# common EIBCALEN-first-invocation idiom: no LINKAGE SECTION, no DFHEIBLK
# declared anywhere, EIBCALEN referenced from ordinary PROCEDURE DIVISION
# code outside any EXEC CICS block.
EIB_REFERENCE_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. EIBSAMP.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-DONE PIC X VALUE 'N'.

       PROCEDURE DIVISION.
       0000-MAIN.
           IF EIBCALEN = 0
               DISPLAY 'FIRST INVOCATION'
           END-IF
           IF EIBAID = 'X'
               DISPLAY 'PF3 PRESSED'
           END-IF
           STOP RUN.
"""

# Ordinary non-CICS program: no EIB reference anywhere.
ORDINARY_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PLAINSAMP.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-DONE PIC X VALUE 'N'.

       PROCEDURE DIVISION.
       MAIN-PARA.
           DISPLAY WS-DONE
           STOP RUN.
"""

# Program that hand-declares its own DFHEIBLK (e.g. via COPY DFHEIBLK) --
# synthesis must not double-declare it.
ALREADY_DECLARED_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. OWNEIBSAMP.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  DFHEIBLK.
           05  EIBCALEN PIC S9(4) COMP.

       PROCEDURE DIVISION.
       MAIN-PARA.
           IF EIBCALEN = 0
               DISPLAY 'FIRST INVOCATION'
           END-IF
           STOP RUN.
"""

# DFHRESP(...) used directly in an ordinary condition -- the CICS-translator
# macro-function this feature deliberately refuses (UNSUPPORTED_CICS_MACRO).
DFHRESP_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. RESPSAMP.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-RESP PIC S9(8) COMP VALUE 0.

       PROCEDURE DIVISION.
       MAIN-PARA.
           IF WS-RESP = DFHRESP(NORMAL)
               DISPLAY 'OK'
           END-IF
           STOP RUN.
"""

# DFHCOMMAREA referenced but never declared anywhere -- unknowable size,
# UNSUPPORTED_CICS_DFHCOMMAREA.
UNDECLARED_DFHCOMMAREA_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. COMMSAMP.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-DONE PIC X VALUE 'N'.

       PROCEDURE DIVISION.
       MAIN-PARA.
           DISPLAY DFHCOMMAREA
           STOP RUN.
"""

# DFHCOMMAREA hand-declared in LINKAGE SECTION, no ENTRY at all -- the
# idiomatic CICS shape Part 1's generalized `linkage_plan` now covers
# instead of refusing here.
DECLARED_DFHCOMMAREA_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. COMMSAMP2.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-DONE PIC X VALUE 'N'.

       LINKAGE SECTION.
       01  DFHCOMMAREA.
           05  CA-FIELD PIC X(10).

       PROCEDURE DIVISION.
       MAIN-PARA.
           DISPLAY DFHCOMMAREA
           STOP RUN.
"""


def _parse(source: str, name: str = "SAMP.cbl"):
    result = parse_cobol(source, filename=name)
    assert result.success, result.errors
    assert not result.warnings
    lines = normalize_fixed_format(source.splitlines()).splitlines()
    return result.ast, lines


def test_cics_eib_plan_none_for_ordinary_program():
    program, lines = _parse(ORDINARY_SOURCE)
    assert cics_eib_plan(program, lines) is None


def test_cics_eib_plan_finds_referenced_fields():
    program, lines = _parse(EIB_REFERENCE_SOURCE)
    plan = cics_eib_plan(program, lines)
    assert plan is not None
    assert plan.referenced_names == ["EIBAID", "EIBCALEN"]


def test_cics_eib_plan_none_when_already_declared():
    program, lines = _parse(ALREADY_DECLARED_SOURCE)
    assert cics_eib_plan(program, lines) is None


def test_check_cics_eib_layout_clean_for_ordinary_program():
    program, lines = _parse(ORDINARY_SOURCE)
    assert check_cics_eib_layout(program, lines) == []


def test_check_cics_eib_layout_clean_for_eib_reference_program():
    program, lines = _parse(EIB_REFERENCE_SOURCE)
    assert check_cics_eib_layout(program, lines) == []


def test_check_cics_eib_layout_refuses_dfhresp_macro():
    program, lines = _parse(DFHRESP_SOURCE)
    reasons = check_cics_eib_layout(program, lines)
    assert any(r.code == "UNSUPPORTED_CICS_MACRO" for r in reasons)


def test_check_cics_eib_layout_refuses_undeclared_dfhcommarea():
    program, lines = _parse(UNDECLARED_DFHCOMMAREA_SOURCE)
    reasons = check_cics_eib_layout(program, lines)
    assert any(r.code == "UNSUPPORTED_CICS_DFHCOMMAREA" for r in reasons)


def test_check_cics_eib_layout_clean_when_dfhcommarea_is_declared():
    # Covered by Part 1's generalized linkage_plan (see test_linkage.py's
    # no-ENTRY DFHCOMMAREA case) instead of this guardrail.
    program, lines = _parse(DECLARED_DFHCOMMAREA_SOURCE)
    assert check_cics_eib_layout(program, lines) == []


def test_working_storage_lines_declares_dfheiblk_group():
    program, lines = _parse(EIB_REFERENCE_SOURCE)
    plan = cics_eib_plan(program, lines)
    ws_lines = working_storage_lines(plan)
    assert ws_lines[0] == "01  DFHEIBLK."
    joined = "\n".join(ws_lines)
    for name in ("EIBCALEN", "EIBAID", "EIBTIME", "EIBRESP2"):
        assert name in joined


def test_reset_lines_initializes_dfheiblk():
    program, lines = _parse(EIB_REFERENCE_SOURCE)
    plan = cics_eib_plan(program, lines)
    assert reset_lines(plan) == ["INITIALIZE DFHEIBLK"]
