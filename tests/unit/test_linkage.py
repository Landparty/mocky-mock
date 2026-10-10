from cobolparser import parse_cobol
from cobolparser.preprocess import normalize_fixed_format

from mockymock.analysis.linkage import linkage_plan, procedure_header_clause_spans
from mockymock.analysis.refusal import check_linkage_layout
from mockymock.splicer.linkage import neutralize

# Mirrors ACCTPRG's real shape: bare default entry (no USING), a separate
# named ENTRY 'DLITCBL' USING a LINKAGE group, LINKAGE SECTION last.
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

# Ordinary CALL-only program: no ENTRY, no LINKAGE SECTION at all.
ORDINARY_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PLAINSAMP.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-DONE PIC X VALUE 'N'.

       PROCEDURE DIVISION.
       MAIN-PARA.
           CALL "OTHERPGM" USING WS-DONE
           STOP RUN.
"""

# Mirrors real IMS PCB-mask linkage sections: a boilerplate comment block
# sits between "LINKAGE SECTION." and the first 01-level item. Regression
# for the header_line derivation that used to assume the header is always
# exactly one line above the first data item (measured to drift 12-14 lines
# on real-world programs whose LINKAGE SECTION opens with such a comment
# block -- see linkage_plan's docstring).
COMMENTED_LINKAGE_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. IMSSAMP2.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-DONE PIC X VALUE 'N'.

       LINKAGE SECTION.
      *****************************************************
      * PCB MASK FOR CUSTOMER DATABASE
      * DESCRIBES THE DL/I PCB LAYOUT FOR THIS PROGRAM
      *****************************************************
       01  CUST-PCB-LNK.
           05  CUST-DBD-NAME     PIC X(08).
           05  CUST-STATUS       PIC X(02).

       PROCEDURE DIVISION.
       ENTRY 'DLITCBL' USING CUST-PCB-LNK.
       0000-MAIN.
           DISPLAY CUST-STATUS
           STOP RUN.
"""

# CICS-style shape: LINKAGE SECTION declaring DFHCOMMAREA, no ENTRY
# statement at all. Covered by the 2026-08-27 generalization -- see
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

# Named ENTRY present, but the default entry ALSO declares its own USING --
# the general CALL-driving case (Milestone B), not this feature's scope.
DEFAULT_ENTRY_USING_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. USINGSAMP.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-DONE PIC X VALUE 'N'.

       LINKAGE SECTION.
       01  LNK-ITEM PIC X(08).

       PROCEDURE DIVISION USING LNK-ITEM.
       ENTRY 'ALTENTRY' USING LNK-ITEM.
       0000-MAIN.
           DISPLAY LNK-ITEM
           STOP RUN.
"""


def _parse(source: str, name: str = "SAMP.cbl"):
    result = parse_cobol(source, filename=name)
    assert result.success, result.errors
    assert not result.warnings
    lines = normalize_fixed_format(source.splitlines()).splitlines()
    return result.ast, lines


def test_linkage_plan_none_for_ordinary_program():
    program, _ = _parse(ORDINARY_SOURCE)
    assert linkage_plan(program) is None


def test_linkage_plan_finds_entries_and_header_line_for_qualifying_program():
    program, lines = _parse(QUALIFYING_SOURCE)
    plan = linkage_plan(program)
    assert plan is not None
    assert [e.entry_name for e in plan.entry_statements] == ["DLITCBL"]
    assert [item.name for item in plan.linkage_items] == ["CUST-PCB-LNK"]
    assert lines[plan.header_line - 1].strip().upper() == "LINKAGE SECTION."


def test_check_linkage_layout_clean_for_ordinary_program():
    program, lines = _parse(ORDINARY_SOURCE)
    assert check_linkage_layout(program, lines) == []


def test_check_linkage_layout_clean_for_qualifying_program():
    program, lines = _parse(QUALIFYING_SOURCE)
    assert check_linkage_layout(program, lines) == []


def test_linkage_plan_finds_linkage_with_no_entry_statement():
    program, lines = _parse(NO_ENTRY_LINKAGE_SOURCE)
    plan = linkage_plan(program)
    assert plan is not None
    assert plan.entry_statements == []
    assert [item.name for item in plan.linkage_items] == ["DFHCOMMAREA"]
    assert lines[plan.header_line - 1].strip().upper() == "LINKAGE SECTION."


def test_check_linkage_layout_clean_with_no_entry_statement():
    program, lines = _parse(NO_ENTRY_LINKAGE_SOURCE)
    assert check_linkage_layout(program, lines) == []


def test_linkage_plan_header_line_survives_comment_block_before_first_item():
    program, lines = _parse(COMMENTED_LINKAGE_SOURCE)
    plan = linkage_plan(program)
    assert plan is not None
    assert lines[plan.header_line - 1].strip().upper() == "LINKAGE SECTION."
    # The naive "one line above the first data item" derivation would have
    # landed inside the comment block instead of on the header.
    assert (
        plan.header_line
        != program.get_division("DATA")._sections["LINKAGE"].data_items[0].location.line
        - 1
    )


def test_check_linkage_layout_clean_with_comment_block_before_first_item():
    program, lines = _parse(COMMENTED_LINKAGE_SOURCE)
    assert check_linkage_layout(program, lines) == []


def test_default_entry_using_is_neutralized_not_refused():
    # 2026-10-10 (entry parameters): the USING clause is blanked out of the
    # instrumented copy, the parameters folded into WORKING-STORAGE like
    # every other LINKAGE item, for a .cut to MOVE into.
    program, lines = _parse(DEFAULT_ENTRY_USING_SOURCE)
    assert check_linkage_layout(program, lines) == []
    plan = linkage_plan(program)
    assert plan is not None
    out = neutralize(list(lines), program, plan)
    header = next(line for line in out if "PROCEDURE DIVISION" in line)
    assert header.split() == ["PROCEDURE", "DIVISION", "."]
    assert len(header) == len(
        next(line for line in lines if "PROCEDURE DIVISION" in line)
    ), "the edit must keep the line's width"
    assert any(line.lstrip().startswith("*> ENTRY 'ALTENTRY'") for line in out)


def test_wrapped_using_and_returning_are_blanked_up_to_the_period():
    source = DEFAULT_ENTRY_USING_SOURCE.replace(
        "       01  LNK-ITEM PIC X(08).\n",
        "       01  LNK-ITEM PIC X(08).\n       01  LNK-RET PIC 9(4).\n",
    ).replace(
        "       PROCEDURE DIVISION USING LNK-ITEM.\n",
        "       PROCEDURE DIVISION USING BY REFERENCE LNK-ITEM\n"
        "                          RETURNING LNK-RET.\n",
    )
    program, lines = _parse(source)
    spans = procedure_header_clause_spans(lines, program)
    assert spans is not None and len(spans) == 2
    out = neutralize(list(lines), program, linkage_plan(program))
    first = spans[0][0] - 1
    assert out[first].split() == ["PROCEDURE", "DIVISION"]
    assert out[first + 1].strip() == "."


def test_chaining_header_is_still_refused():
    source = DEFAULT_ENTRY_USING_SOURCE.replace(
        "PROCEDURE DIVISION USING LNK-ITEM.", "PROCEDURE DIVISION CHAINING LNK-ITEM."
    )
    program, lines = _parse(source)
    assert procedure_header_clause_spans(lines, program) is None
    reasons = check_linkage_layout(program, lines)
    assert any(
        r.code == "UNSUPPORTED_LINKAGE_LAYOUT" and "CHAINING" in r.message
        for r in reasons
    )


def test_header_without_a_clause_has_no_spans():
    program, lines = _parse(ORDINARY_SOURCE)
    assert procedure_header_clause_spans(lines, program) == []


class _FakeLocation:
    def __init__(self, line):
        self.line = line


class _FakeEntry:
    def __init__(self, name, line):
        self.entry_name = name
        self.location = _FakeLocation(line)


class _FakeItem:
    def __init__(self, name, line):
        self.name = name
        self.location = _FakeLocation(line)


class _FakeSection:
    def __init__(self, data_items, line=None):
        self.data_items = data_items
        self.location = _FakeLocation(line) if line is not None else None


class _FakeDataDivision:
    def __init__(self, sections):
        self._sections = sections


class _FakeProcDivision:
    def __init__(self, line):
        self.location = _FakeLocation(line)


class _FakeProgram:
    """Minimal stand-in for CobolProgram -- used only to drive the
    LINKAGE-must-be-last-section guardrail directly, since no cobolparser-
    supported DATA DIVISION section is known to legally follow LINKAGE
    without already tripping the (unrelated, pre-existing) PARSE_WARNING
    gate -- see the design doc's guardrail-2 note."""

    def __init__(self, entries, data_division, procedure_division):
        self._entries = entries
        self._data_division = data_division
        self._procedure_division = procedure_division

    def get_entry_statements(self):
        return self._entries

    def get_division(self, name):
        return {"DATA": self._data_division, "PROCEDURE": self._procedure_division}.get(
            name
        )


def test_check_linkage_layout_refuses_when_linkage_is_not_last_section():
    lines = [
        "WORKING-STORAGE SECTION.",
        "01  WS-DONE PIC X.",
        "LINKAGE SECTION.",
        "01  LNK-ITEM PIC X(08).",
        "REPORT SECTION.",
        "01  RPT-ITEM.",
        "PROCEDURE DIVISION.",
        "ENTRY 'ALT' USING LNK-ITEM.",
    ]
    program = _FakeProgram(
        entries=[_FakeEntry("ALT", 8)],
        data_division=_FakeDataDivision(
            {
                "WORKING-STORAGE": _FakeSection([_FakeItem("WS-DONE", 2)], line=1),
                "LINKAGE": _FakeSection([_FakeItem("LNK-ITEM", 4)], line=3),
                "REPORT": _FakeSection([_FakeItem("RPT-ITEM", 6)], line=5),
            }
        ),
        procedure_division=_FakeProcDivision(7),
    )
    reasons = check_linkage_layout(program, lines)
    assert any(
        r.code == "UNSUPPORTED_LINKAGE_LAYOUT"
        and "last DATA DIVISION section" in r.message
        for r in reasons
    )


def test_check_linkage_layout_refuses_when_header_line_cannot_be_verified():
    program, lines = _parse(QUALIFYING_SOURCE)
    plan = linkage_plan(program)
    # Simulate a mismatch between the AST's location bookkeeping and the
    # actual text handed in (defense in depth -- should never happen with
    # correctly paired program/lines, but must fail closed if it does).
    tampered = list(lines)
    tampered[plan.header_line - 1] = "    NOT-LINKAGE-SECTION-ANYMORE."
    reasons = check_linkage_layout(program, tampered)
    assert any(
        r.code == "UNSUPPORTED_LINKAGE_LAYOUT" and "could not locate" in r.message
        for r in reasons
    )


# `SET ADDRESS OF <folded item>` shapes the redirect in
# `splicer.linkage.redirect_address_of` cannot express as a single-line
# column span. Left alone they are a hard cobc error once the LINKAGE
# SECTION has been folded, so the gate refuses rather than emit source that
# cannot compile.
ADDRESS_OF_CONTINUED_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CLP100.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-PTR USAGE POINTER.

       LINKAGE SECTION.
       01  LKPCB-CLP100MA.
           05  LKPCB-STATUS PIC X(2).

       PROCEDURE DIVISION.
       0000-MAIN.
           SET ADDRESS OF
               LKPCB-CLP100MA TO WS-PTR
           STOP RUN.
"""


def test_check_linkage_layout_refuses_an_unrewritable_address_of():
    program, lines = _parse(ADDRESS_OF_CONTINUED_SOURCE)
    reasons = check_linkage_layout(program, lines)
    assert any(r.code == "UNSUPPORTED_LINKAGE_ADDRESSING" for r in reasons)
    assert any("not BASED or a LINKAGE item" in r.message for r in reasons)


def test_check_linkage_layout_allows_a_rewritable_address_of():
    """The ordinary single-line DL/I shape is handled by the redirect, not
    refused -- otherwise the whole IMS corpus would stop running."""
    program, lines = _parse(
        ADDRESS_OF_CONTINUED_SOURCE.replace(
            "SET ADDRESS OF\n               LKPCB-CLP100MA TO WS-PTR",
            "SET ADDRESS OF LKPCB-CLP100MA TO WS-PTR",
        )
    )
    assert check_linkage_layout(program, lines) == []


def test_check_linkage_layout_allows_cics_address_and_dli_uib_call():
    """`EXEC CICS ADDRESS TCTUA(ADDRESS OF TCTUA)` split over two lines, and
    `CALL 'CBLTDLI' USING ... ADDRESS OF DLIUIB` with the operand on its own
    line: neither rebinds a folded item, so neither refuses."""
    source = ADDRESS_OF_CONTINUED_SOURCE.replace(
        "           SET ADDRESS OF\n               LKPCB-CLP100MA TO WS-PTR\n",
        "           EXEC CICS ADDRESS\n"
        "                     TCTUA (ADDRESS OF LKPCB-CLP100MA)\n"
        "           END-EXEC\n"
        "           CALL 'CBLTDLI' USING WS-PTR\n"
        "                ADDRESS OF LKPCB-CLP100MA\n",
    )
    # cobolparser 1.8.x warns on (and drops) `USING ... ADDRESS OF X`; the
    # gate under test is textual, so only a clean parse error-wise matters.
    result = parse_cobol(source, filename="SAMP.cbl")
    assert result.success, result.errors
    lines = normalize_fixed_format(source.splitlines()).splitlines()
    assert check_linkage_layout(result.ast, lines) == []
