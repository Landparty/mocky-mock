"""Names declared more than once, read through `OF`/`IN` qualification:
their PICTURE (reports, `--record-expectations`) and whether an EXPECT on
one compares by de-edited value."""

from __future__ import annotations

from cobolparser import parse_cobol

from mockymock._qualified import qualified_lookup, qualified_member
from mockymock.dsl.model import ExpectDirective, MockTestCase, MockTestSuite
from mockymock.report.record_rewrite import (
    field_pictures,
    numeric_edited_fields,
    picture_for,
)
from mockymock.splicer.driver import build_driver
from mockymock.splicer.naming import TallyRegistry

PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. P.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  IN-REC.
           05  AMT        PIC S9(5)V99.
           05  RATE       PIC 9(3).
           05  BAL-ED     PIC ZZ9.99.
       01  OUT-REC.
           05  AMT        PIC S9(5)V99 COMP-3.
           05  DETAIL.
               10  RATE   PIC 9V99.
           05  BAL-ED     PIC 9(3)V99.
       PROCEDURE DIVISION.
           STOP RUN.
"""


def _pictures() -> dict[str, str]:
    return field_pictures(parse_cobol(PROGRAM).ast)


def test_a_name_declared_twice_with_one_picture_keeps_its_plain_key() -> None:
    pictures = _pictures()
    assert pictures["AMT"] == "S9(5)V99"
    assert picture_for("AMT OF OUT-REC", pictures) == "S9(5)V99"


def test_differing_pictures_resolve_through_the_qualifier() -> None:
    pictures = _pictures()
    assert "RATE" not in pictures
    assert picture_for("RATE", pictures) is None
    assert picture_for("RATE OF IN-REC", pictures) == "9(3)"
    # Qualification may skip a level, and IN means OF.
    assert picture_for("RATE OF OUT-REC", pictures) == "9V99"
    assert picture_for("RATE IN DETAIL IN OUT-REC", pictures) == "9V99"
    assert picture_for("rate of detail(2)", pictures) == "9V99"
    # Qualifiers in the wrong order, or naming no ancestor, settle nothing.
    assert picture_for("RATE OF OUT-REC OF DETAIL", pictures) is None
    assert picture_for("RATE OF NO-SUCH", pictures) is None


def test_numeric_edited_follows_the_qualified_declaration() -> None:
    edited = numeric_edited_fields(parse_cobol(PROGRAM).ast)
    assert qualified_member("BAL-ED OF IN-REC", edited)
    assert not qualified_member("BAL-ED OF OUT-REC", edited)
    assert not qualified_member("BAL-ED", edited)


def test_qualified_lookup_plain_and_dotted_keys() -> None:
    entries = {"A": "1", "G1.B": "2", "G2.B": "3", "TOP.G3.C": "4"}
    assert qualified_lookup("A", entries) == "1"
    assert qualified_lookup("B", entries) is None
    assert qualified_lookup("B OF G2", entries) == "3"
    assert qualified_lookup("C OF TOP", entries) == "4"
    assert qualified_lookup("C IN G3 IN TOP", entries) == "4"
    assert qualified_lookup("", entries) is None


def _build(*expectations, numeric_edited) -> str:
    case = MockTestCase(
        name="c",
        mocks=[],
        setup_moves=[],
        perform_target="MAIN-PARA",
        expectations=list(expectations),
        verifications=[],
    )
    suite = MockTestSuite(name="s", test_cases=[case])
    artifact = build_driver(
        suite,
        reset_lines=[],
        registry=TallyRegistry(suite),
        numeric_edited=numeric_edited,
    )
    return "\n".join(artifact.working_storage_lines + artifact.procedure_lines)


def test_qualified_numeric_edited_expect_compares_by_value() -> None:
    code = _build(
        ExpectDirective("BAL-ED OF IN-REC", "1.50"),
        numeric_edited={"IN-REC.BAL-ED"},
    )
    assert "MOVE BAL-ED OF IN-REC TO UT-DEEDIT-VALUE" in code
    assert "IF UT-DEEDIT-VALUE NOT = 1.50" in code


def test_combined_condition_on_a_numeric_edited_field_compares_by_value() -> None:
    """`TO BE GREATER THAN 0 AND LESS THAN 10` compared `"  5"` with 0 as
    text, and failed, where the single-relation form passed."""
    code = _build(
        ExpectDirective("WS-ED", "0 AND LESS THAN 10", operator=">"),
        ExpectDirective("WS-ED", "7 OR 8", operator="NOT ="),
        numeric_edited={"WS-ED"},
    )
    assert "01  UT-DEEDIT-VALUE" in code
    assert code.count("MOVE WS-ED TO UT-DEEDIT-VALUE") == 2
    assert "IF NOT (UT-DEEDIT-VALUE > 0 AND LESS THAN 10)" in code
    assert "IF (UT-DEEDIT-VALUE = 7 OR 8)" in code


def test_combined_condition_with_a_text_operand_stays_textual() -> None:
    code = _build(
        ExpectDirective("WS-ED", '"  5" OR "  6"'),
        ExpectDirective("WS-ED(1:2)", "0 OR 1"),
        ExpectDirective("WS-NUM", "0 OR 1"),
        numeric_edited={"WS-ED"},
    )
    assert "UT-DEEDIT-VALUE" not in code
    assert 'IF NOT (WS-ED = "  5" OR "  6")' in code
