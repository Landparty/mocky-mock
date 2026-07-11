from cobolparser import parse_cobol
from cobolparser.preprocess import normalize_fixed_format

from mockymock.analysis.linkage import linkage_plan
from mockymock.analysis.refusal import check_linkage_layout

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


def test_check_linkage_layout_refuses_default_entry_using():
    program, lines = _parse(DEFAULT_ENTRY_USING_SOURCE)
    reasons = check_linkage_layout(program, lines)
    assert any(r.code == "UNSUPPORTED_LINKAGE_LAYOUT" for r in reasons)
    assert any("default entry" in r.message for r in reasons)


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
    def __init__(self, data_items):
        self.data_items = data_items


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
                "WORKING-STORAGE": _FakeSection([_FakeItem("WS-DONE", 2)]),
                "LINKAGE": _FakeSection([_FakeItem("LNK-ITEM", 4)]),
                "REPORT": _FakeSection([_FakeItem("RPT-ITEM", 6)]),
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
