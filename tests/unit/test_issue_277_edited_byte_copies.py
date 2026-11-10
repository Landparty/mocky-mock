"""Issue #277: a MOVE into an alphanumeric-edited item edits the sending
text again ("12/31/99" into PIC XX/XX/XX became "12//3/1/"). The reset's
VALUE restore, generated READ rows and synthesized CAPTURE targets all
copy such values as bytes instead."""

from __future__ import annotations

from cobolparser import parse_cobol
from cobolparser.generators.data import FieldCategory, FieldSpec

from mockymock.dsl.generator import _row_move_line
from mockymock.splicer.captures import _declaration_for
from mockymock.splicer.reset import reset_move_lines

SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. AE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-DATE-ED        PIC XX/XX/XX VALUE "12/31/99".
       01  WS-PHONE          PIC XXXBXXXX VALUE "555 1234".
       01  WS-GRP.
           05  WS-G-ED       PIC XX/XX VALUE "AB/CD".
       01  WS-PLAIN          PIC X(8) VALUE "12/31/99".
       PROCEDURE DIVISION.
       MAIN-PARA.
           GOBACK.
"""


def test_reset_restores_an_edited_value_by_reference_modification() -> None:
    result = parse_cobol(SOURCE, filename="ae.cbl")
    assert result.success, result.errors
    lines = reset_move_lines(result.ast)
    assert 'MOVE "12/31/99" TO WS-DATE-ED(1:)' in lines
    assert 'MOVE "555 1234" TO WS-PHONE(1:)' in lines
    assert 'MOVE "AB/CD" TO WS-G-ED OF WS-GRP(1:)' in lines
    assert 'MOVE "12/31/99" TO WS-PLAIN' in lines


def test_generated_row_for_an_edited_field_is_a_byte_copy() -> None:
    spec = FieldSpec(
        name="IN-AE",
        path=("IN-REC", "IN-AE"),
        column="IN-AE",
        level=5,
        picture="XX/XX/XX",
        usage="DISPLAY",
        category=FieldCategory("alphanumeric-edited"),
        size=8,
        integer_digits=0,
        decimal_digits=0,
        is_signed=False,
    )
    line = _row_move_line({"IN-AE": "N8/DF/B3"}, spec, "IN-AE")
    assert line == 'MOVE "N8/DF/B3" TO IN-AE(1:)'


def test_capture_of_an_edited_argument_is_declared_alphanumeric() -> None:
    item = {
        "picture": "XX/XX/XX",
        "usage": "DISPLAY",
        "byte_length": 8,
        "is_group": False,
        "occurs": None,
    }
    declaration, reset = _declaration_for("UT-CAP-LOGDATE-1", item)
    assert declaration == "01  UT-CAP-LOGDATE-1  PIC X(8)."
    assert reset == "MOVE SPACES TO UT-CAP-LOGDATE-1"
