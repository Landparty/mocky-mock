"""Fail-closed coverage of the verbs cobol-parser's 2026-09-02 statement-
coverage work turned from warned-and-discarded into real AST nodes -- and
of the Report Writer verbs that became mockable at the same time.

Before that cobol-parser release, INVOKE aside, every verb below produced a
`ParseResult.warnings` entry that `check_whole_program` refused as
PARSE_WARNING. Once they parse cleanly, only `mock_surface.py` stands
between an external dependency and a silent `[PASS]` -- so this file pins,
for each one: classification (a site, never silently passed through), the
refusal code the gate emits when the site is reachable, and that an
unreachable or flow-mocked site is NOT refused (no over-refusal).

Tests needing an AST node the installed cobol-parser does not have (the
CI compat lane installs the published release) skip rather than fail; the
older parser still warns on those verbs, so the PARSE_WARNING refusal
covers them there -- the fail-closed property holds on both.
"""

import re
from pathlib import Path

import pytest
from cobolparser import parse_cobol

from mockymock.analysis import mock_surface
from mockymock.analysis.mock_surface import (
    UNSUPPORTED_STATEMENT_LABEL,
    BoundarySite,
    analyze,
    analyze_file_status_fields,
)
from mockymock.analysis.refusal import (
    _reachable_paragraphs,
    check_test_case,
    check_whole_program,
)
from mockymock.cli.main import main
from mockymock.dsl.generator import scaffold_cut
from mockymock.dsl.model import (
    REPORT_WRITER_CATEGORIES,
    MockCategory,
    MockDirective,
    MockTestCase,
)
from mockymock.dsl.parser import parse_cut

_HEADER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. VERBS.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-F                PIC X(10).
       01  WS-N                PIC 9(3) VALUE 0.

       PROCEDURE DIVISION.
"""


def _program(main_body: str, extra: str = ""):
    result = parse_cobol(_HEADER + main_body + extra, filename="verbs.cbl")
    assert result.success, result.errors
    assert not result.warnings, result.warnings
    return result.ast


def _case(*mocks: MockDirective, target: str = "MAIN-PARA") -> MockTestCase:
    return MockTestCase(name="t", perform_target=target, mocks=list(mocks))


def _codes(program, case) -> set[str]:
    surface = analyze(program)
    return {
        r.code
        for r in check_test_case(
            surface, program, case, analyze_file_status_fields(program)
        )
    }


def _none_sites(program) -> list[BoundarySite]:
    return [s for s in analyze(program).boundary_sites if s.category is None]


# --- INVOKE ----------------------------------------------------------------

INVOKE_BODY = """\
       MAIN-PARA.
           MOVE 1 TO WS-N
           PERFORM CALL-OBJ.
       CALL-OBJ.
           INVOKE WS-OBJ "doIt" USING WS-F.
       OTHER-PARA.
           DISPLAY "unreached".
"""


@pytest.mark.skipif(not mock_surface._INVOKE_TYPES, reason="no InvokeStatement")
def test_invoke_is_detected_and_refused_when_reachable():
    program = _program(INVOKE_BODY)
    (site,) = _none_sites(program)
    assert site.label == "INVOKE"
    assert site.keys == ("WS-OBJ", "doIt")
    assert site.paragraph_name == "CALL-OBJ"
    assert "UNSUPPORTED_INVOKE" in _codes(program, _case())


@pytest.mark.skipif(not mock_surface._INVOKE_TYPES, reason="no InvokeStatement")
def test_invoke_not_refused_when_unreachable_or_flow_mocked():
    program = _program(INVOKE_BODY)
    assert "UNSUPPORTED_INVOKE" not in _codes(program, _case(target="OTHER-PARA"))
    mocked = _case(MockDirective(category=MockCategory.PARAGRAPH, key="CALL-OBJ"))
    assert "UNSUPPORTED_INVOKE" not in _codes(program, mocked)


# --- CHAIN -----------------------------------------------------------------

CHAIN_BODY = """\
       MAIN-PARA.
           CHAIN "NEXTPGM" USING WS-F.
"""


@pytest.mark.skipif(not mock_surface._CHAIN_TYPES, reason="no ChainStatement")
def test_chain_is_detected_and_refused():
    program = _program(CHAIN_BODY)
    (site,) = _none_sites(program)
    assert site.label == "CHAIN"
    assert site.keys == ('"NEXTPGM"',)
    assert "UNSUPPORTED_CHAIN" in _codes(program, _case())


# --- Communication Module --------------------------------------------------

COMM_BODY = """\
       MAIN-PARA.
           ENABLE INPUT CD-IN WITH KEY WS-F
           RECEIVE CD-IN MESSAGE INTO WS-F
               NO DATA CALL "NODATA" USING WS-F
           END-RECEIVE
           SEND CD-OUT FROM WS-F
           PURGE CD-OUT
           DISABLE INPUT CD-IN WITH KEY WS-F.
"""


@pytest.mark.skipif(
    len(mock_surface._COMMUNICATION_TYPES) < 5, reason="no communication nodes"
)
def test_communication_verbs_are_detected_and_refused():
    program = _program(COMM_BODY)
    sites = _none_sites(program)
    assert [s.label for s in sites] == ["communication"] * 5
    assert [s.keys for s in sites] == [
        ("CD-IN",),
        ("CD-IN",),
        ("CD-OUT",),
        ("CD-OUT",),
        ("CD-IN",),
    ]
    # the CALL inside RECEIVE ... NO DATA is walked, and marked as sitting
    # inside a boundary statement's own clause body
    surface = analyze(program)
    (call,) = [s for s in surface.boundary_sites if s.category is MockCategory.CALL]
    assert call.keys == ("NODATA",)
    assert call.nested and call.nested_in_boundary
    assert "UNSUPPORTED_COMMUNICATION" in _codes(program, _case())


# --- STOP literal ----------------------------------------------------------

STOP_LITERAL_BODY = """\
       MAIN-PARA.
           STOP "PRESS ENTER TO CONTINUE"
           DISPLAY "resumed".
       STOP-RUN-PARA.
           STOP RUN.
"""


def test_stop_literal_is_a_console_read_refused_when_reachable():
    program = _program(STOP_LITERAL_BODY)
    sites = _none_sites(program)
    assert [s.label for s in sites] == ["STOP literal", "STOP RUN"]
    assert sites[0].keys == ("PRESS ENTER TO CONTINUE",)
    assert "UNSUPPORTED_STOP_LITERAL" in _codes(program, _case())
    # STOP RUN keeps its own separate (terminator-plan) treatment
    assert "UNSUPPORTED_STOP_LITERAL" not in _codes(
        program, _case(target="STOP-RUN-PARA")
    )


# --- unknown statement class: the catch-all -------------------------------


class _FutureVerbStatement:
    """A statement class mock_surface has never heard of."""

    statement_type = "TELEPORT"

    def __init__(self, line: int) -> None:
        self.location = type("Loc", (), {"line": line})()


def test_unknown_statement_class_is_refused_never_passed_through():
    program = _program("       MAIN-PARA.\n           MOVE 1 TO WS-N.\n")
    paragraph = program.get_division("PROCEDURE").paragraphs[0]
    paragraph.statements.append(_FutureVerbStatement(line=11))
    (site,) = _none_sites(program)
    assert site.label == UNSUPPORTED_STATEMENT_LABEL
    assert site.keys == ("TELEPORT",)
    reasons = check_test_case(
        analyze(program), program, _case(), analyze_file_status_fields(program)
    )
    (reason,) = [r for r in reasons if r.code == "UNSUPPORTED_STATEMENT"]
    assert "TELEPORT" in reason.message
    assert "line 11" in reason.message


def test_every_passthrough_name_is_a_real_cobolparser_statement_class():
    """The allowlist is closed by name; a typo in it would silently turn a
    harmless verb into an UNSUPPORTED_STATEMENT refusal, so every entry
    must resolve to a CobolStatement subclass in the installed
    cobol-parser (entries for nodes newer than the installed release are
    tolerated -- they cannot occur on that release either way)."""
    import cobolparser.models.statements as statements
    from cobolparser.models.statements.base import CobolStatement

    known = {
        name
        for name, obj in vars(statements).items()
        if isinstance(obj, type) and issubclass(obj, CobolStatement)
    }
    newer = {
        "AllocateStatement",
        "EnterStatement",
        "ExamineStatement",
        "ExhibitStatement",
        "FreeStatement",
        "NoteStatement",
        "RaiseStatement",
        "ResumeStatement",
        "ServiceStatement",
        "SuppressStatement",
        "TitleStatement",
        "TraceStatement",
        "TransformStatement",
        "ValidateStatement",
    }
    unknown = mock_surface._PASSTHROUGH_STATEMENT_NAMES - known - newer
    assert not unknown, unknown


# --- Report Writer: mockable ------------------------------------------------

REPORT_WRITER_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. RWTEST.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT RPT-FILE ASSIGN TO "RPTFILE"
               ORGANIZATION IS LINE SEQUENTIAL.

       DATA DIVISION.
       FILE SECTION.
       FD  RPT-FILE
           REPORT IS SALES-RPT.
       WORKING-STORAGE SECTION.
       01  WS-AMOUNT           PIC 9(5) VALUE 0.
       01  WS-TOTAL            PIC 9(7) VALUE 0.
       REPORT SECTION.
       RD  SALES-RPT
           PAGE LIMIT 60 LINES.
       01  DETAIL-LINE TYPE DETAIL.
           05  LINE 1 COLUMN 1 PIC 9(5) SOURCE WS-AMOUNT.

       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN OUTPUT RPT-FILE
           INITIATE SALES-RPT
           PERFORM PRINT-DETAIL
           TERMINATE SALES-RPT
           CLOSE RPT-FILE.
       PRINT-DETAIL.
           MOVE 42 TO WS-AMOUNT
           ADD WS-AMOUNT TO WS-TOTAL
           GENERATE DETAIL-LINE.
"""

REPORT_WRITER_CUT = """\
TESTSUITE "report writer"

TESTCASE "detail line is generated once"
    PERFORM MAIN-PARA
    MOCK OPEN RPT-FILE
    END-MOCK
    MOCK INITIATE SALES-RPT
    END-MOCK
    MOCK GENERATE DETAIL-LINE
    END-MOCK
    MOCK TERMINATE SALES-RPT
    END-MOCK
    MOCK CLOSE RPT-FILE
    END-MOCK
    VERIFY GENERATE DETAIL-LINE WAS CALLED 1 TIMES
    EXPECT WS-TOTAL TO BE 42
"""


def _report_writer_program():
    result = parse_cobol(REPORT_WRITER_SOURCE, filename="rwtest.cbl")
    assert result.success, result.errors
    assert not result.warnings, result.warnings
    return result.ast


rw_available = pytest.mark.skipif(
    not (mock_surface._INITIATE_TYPES and mock_surface._TERMINATE_TYPES),
    reason="no Report Writer nodes",
)


@rw_available
def test_report_writer_verbs_are_classified_by_report_name():
    program = _report_writer_program()
    sites = analyze(program).boundary_sites
    by_category = {s.category: s for s in sites}
    assert by_category[MockCategory.INITIATE].keys == ("SALES-RPT",)
    assert by_category[MockCategory.TERMINATE].keys == ("SALES-RPT",)
    assert by_category[MockCategory.GENERATE].keys == ("DETAIL-LINE",)
    assert by_category[MockCategory.GENERATE].paragraph_name == "PRINT-DETAIL"
    assert {s.category for s in sites} == {
        MockCategory.OPEN,
        MockCategory.CLOSE,
        *REPORT_WRITER_CATEGORIES,
    }
    assert not check_whole_program(parse_cobol(REPORT_WRITER_SOURCE))


@rw_available
def test_report_writer_unmocked_refuses_with_its_own_code():
    program = _report_writer_program()
    case = _case(
        MockDirective(category=MockCategory.OPEN, key="RPT-FILE"),
        MockDirective(category=MockCategory.CLOSE, key="RPT-FILE"),
    )
    reasons = check_test_case(
        analyze(program), program, case, analyze_file_status_fields(program)
    )
    rw = [r for r in reasons if r.code == "UNMOCKED_REPORT_WRITER"]
    assert {r.message.split(" boundary")[0] for r in rw} == {
        "INITIATE",
        "GENERATE",
        "TERMINATE",
    }
    assert {r.code for r in reasons} == {"UNMOCKED_REPORT_WRITER"}


def test_report_writer_directives_parse_as_bare_keys():
    suite = parse_cut(REPORT_WRITER_CUT)
    (case,) = suite.test_cases
    assert [(m.category, m.key) for m in case.mocks] == [
        (MockCategory.OPEN, "RPT-FILE"),
        (MockCategory.INITIATE, "SALES-RPT"),
        (MockCategory.GENERATE, "DETAIL-LINE"),
        (MockCategory.TERMINATE, "SALES-RPT"),
        (MockCategory.CLOSE, "RPT-FILE"),
    ]
    assert case.mocks[2].describe() == "GENERATE DETAIL-LINE"
    (verify,) = case.verifications
    assert (verify.category, verify.key) == (MockCategory.GENERATE, "DETAIL-LINE")


@rw_available
def test_report_writer_scaffold_emits_bare_directives():
    program = _report_writer_program()
    text = scaffold_cut("rwtest", analyze(program))
    assert "MOCK INITIATE SALES-RPT" in text
    assert "MOCK GENERATE DETAIL-LINE" in text
    assert "MOCK TERMINATE SALES-RPT" in text


@rw_available
def test_report_writer_lint_and_export_splice_the_verbs_out(tmp_path, capsys):
    cbl = tmp_path / "RWTEST.cbl"
    cut = tmp_path / "RWTEST.cut"
    cbl.write_text(REPORT_WRITER_SOURCE)
    cut.write_text(REPORT_WRITER_CUT)
    assert main(["lint", str(cbl), "--cut", str(cut)]) == 0
    out = tmp_path / "spliced.cbl"
    assert main(["export", str(cbl), "--cut", str(cut), "-o", str(out)]) == 0
    spliced = out.read_text()
    live = [
        line
        for line in spliced.splitlines()
        if line[6:7] != "*"
        and re.match(r"\s*(INITIATE|GENERATE|TERMINATE)\b", line, re.IGNORECASE)
    ]
    assert live == [], live
    assert "UT-GENERATE-DETAIL-LINE-TALLY" in spliced
    # the RD/FD declarations stay (GnuCOBOL compiles them; the file is never touched)
    assert "REPORT IS SALES-RPT" in spliced
    assert "RD  SALES-RPT" in spliced


# --- XML PARSE: a flow edge, not a boundary --------------------------------

XML_PARSE_BODY = """\
       MAIN-PARA.
           XML PARSE WS-F
               PROCESSING PROCEDURE HANDLE-XML THRU HANDLE-XML-END
             ON EXCEPTION
               CALL "XMLERR" USING WS-F
           END-XML.
       HANDLE-XML.
           CALL "XMLSUB" USING WS-F.
       HANDLE-XML-MID.
           MOVE 1 TO WS-N.
       HANDLE-XML-END.
           EXIT.
       OTHER-PARA.
           DISPLAY "unreached".
"""


def _xml_parse_program():
    return _program(XML_PARSE_BODY)


def _xml_parse_statement(program):
    return program.get_division("PROCEDURE").paragraphs[0].statements[0]


xml_structured = pytest.mark.skipif(
    not mock_surface._XML_JSON_TYPES
    or not hasattr(
        mock_surface._XML_JSON_TYPES[0]("XML", "PARSE", None), "processing_procedure"
    ),
    reason="cobol-parser without structured XML PARSE clauses",
)


@xml_structured
def test_xml_parse_processing_procedure_is_a_reachability_edge():
    program = _xml_parse_program()
    reachable, reasons = _reachable_paragraphs(program, "MAIN-PARA", None)
    assert reasons == []
    assert reachable == {"MAIN-PARA", "HANDLE-XML", "HANDLE-XML-MID", "HANDLE-XML-END"}
    # ... so the CALL inside the processing procedure and the one inside
    # ON EXCEPTION both need mocks
    assert _codes(program, _case()) == {"UNMOCKED_CALL"}
    case = _case(
        MockDirective(category=MockCategory.CALL, key="XMLSUB"),
        MockDirective(category=MockCategory.CALL, key="XMLERR"),
    )
    codes = _codes(program, case)
    assert "UNMOCKED_CALL" not in codes
    # XML PARSE itself is never a boundary site
    assert all(
        s.label != UNSUPPORTED_STATEMENT_LABEL for s in analyze(program).boundary_sites
    )


@xml_structured
def test_xml_parse_without_structured_fields_fails_closed():
    """Simulate the older cobol-parser shape: clause kept as text only."""
    program = _xml_parse_program()
    stmt = _xml_parse_statement(program)
    del stmt.processing_procedure
    del stmt.processing_procedure_thru
    _, reasons = _reachable_paragraphs(program, "MAIN-PARA", None)
    assert [r.code for r in reasons] == ["UNRESOLVED_FLOW_TARGET"]
    assert "PROCESSING PROCEDURE" in reasons[0].message
    # and a handler kept only as text makes the statement unmodelable
    stmt.clause_text = "PROCESSING PROCEDURE HANDLE-XML ON EXCEPTION CALL 'X'"
    del stmt.on_exception
    (site,) = _none_sites(program)
    assert site.label == UNSUPPORTED_STATEMENT_LABEL
    assert "XML PARSE" in site.keys[0]


# --- corpus sweep: nothing in the example programs is an unknown statement --


def test_example_corpus_has_no_unmodeled_statements():
    """Every `examples/**/*.cbl` this repo ships must classify without a
    single catch-all site: the pass-through allowlist is complete for real
    programs, and no example silently depends on the catch-all."""
    root = Path(__file__).resolve().parents[2]
    offenders: dict[str, list[str]] = {}
    seen = 0
    for path in sorted(root.glob("examples/**/*.cbl")):
        result = parse_cobol(path.read_text(errors="replace"), filename=path.name)
        if result.ast is None:
            continue
        seen += 1
        unknown = [
            f"{s.keys[0] if s.keys else '?'}@{s.line}"
            for s in analyze(result.ast).boundary_sites
            if s.label == UNSUPPORTED_STATEMENT_LABEL
        ]
        if unknown:
            offenders[str(path.relative_to(root))] = unknown
    assert seen > 10
    assert offenders == {}
