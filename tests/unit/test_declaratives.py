"""`analysis.declaratives`: which USE AFTER EXCEPTION procedure a mocked
file statement runs, and what the splice and the reachability walk do
with it (2026-11-03)."""

from pathlib import Path

from cobolparser import parse_cobol

from mockymock.analysis.declaratives import (
    declarative_paragraphs,
    unsupported_use,
    use_procedures,
)
from mockymock.analysis.refusal._reachability import _reachable_paragraphs

DECL = (
    Path(__file__).parent.parent / "fixtures" / "declaratives" / "DECL.cbl"
).read_text()


def _program(source: str = DECL):
    result = parse_cobol(source, filename="DECL.cbl")
    assert result.success, result.errors
    return result.ast


def test_procedures_by_file_and_by_mode():
    uses = use_procedures(_program())
    assert uses is not None
    assert uses.by_file == {"KEY-FILE": "KEY-ERROR"}
    assert uses.by_mode == {"INPUT": "INPUT-ERROR"}
    assert uses.file_of("OUT-REC") == "OUT-FILE"


def test_a_file_named_by_a_use_needs_no_mode_field():
    uses = use_procedures(_program())
    assert uses is not None
    assert uses.mode_field("KEY-FILE") is None
    assert uses.perform_lines("KEY-FILE", None) == ["PERFORM KEY-ERROR"]
    assert uses.mode_fields() == [
        ("IN-FILE", "UT-OPEN-MODE-1"),
        ("OUT-FILE", "UT-OPEN-MODE-3"),
    ]


def test_an_open_names_its_mode_and_other_statements_read_the_recorded_one():
    uses = use_procedures(_program())
    assert uses is not None
    assert uses.perform_lines("IN-FILE", "INPUT") == ["PERFORM INPUT-ERROR"]
    assert uses.perform_lines("OUT-FILE", "OUTPUT") == []
    assert uses.perform_lines("IN-FILE", None) == [
        "EVALUATE UT-OPEN-MODE-1",
        '    WHEN "I"',
        "        PERFORM INPUT-ERROR",
        "END-EVALUATE",
    ]


def test_the_walk_reaches_the_procedure_through_a_file_statement():
    program = _program()
    reached, reasons = _reachable_paragraphs(program, "READ-ALL")
    assert not reasons
    assert {"INPUT-ERROR", "INPUT-ERROR-1"} <= reached
    assert "KEY-ERROR" not in reached
    reached, _ = _reachable_paragraphs(program, "READ-KEYS")
    assert "KEY-ERROR-1" in reached


def test_declarative_names_and_supported_forms():
    program = _program()
    assert {"INPUT-ERROR", "INPUT-ERROR-1", "KEY-ERROR"} <= declarative_paragraphs(
        program
    )
    assert "READ-ALL" not in declarative_paragraphs(program)
    assert unsupported_use(program) is None


def test_a_use_naming_no_select_is_unsupported():
    source = DECL.replace("ON KEY-FILE.", "ON NO-SUCH-FILE.")
    assert "NO-SUCH-FILE" in (unsupported_use(_program(source)) or "")


def test_the_driver_goes_after_end_declaratives():
    from types import SimpleNamespace

    from mockymock.cli.main import _insert_driver

    artifact = SimpleNamespace(
        working_storage_lines=["01  UT-X PIC X."],
        procedure_lines=["       UT-DRIVER.", "           STOP RUN."],
        program_end=False,
    )
    lines = _insert_driver(DECL.splitlines(), artifact)
    end = next(i for i, line in enumerate(lines) if "END DECLARATIVES" in line)
    driver = lines.index("       UT-DRIVER.")
    assert driver > end
    assert lines.index("       DECLARATIVES.") < end


def test_a_span_stops_before_end_declaratives():
    from mockymock.splicer.source_map import _trim_trailing_blank_lines

    lines = ["           STOP RUN.", "       END DECLARATIVES.", "       MAIN SECTION."]
    assert _trim_trailing_blank_lines(1, 2, lines) == 1
