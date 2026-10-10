"""mockymock.analysis.dialect_risk: statements whose GnuCOBOL result may
differ from IBM Enterprise COBOL's."""

from cobolparser import parse_cobol

from mockymock.analysis.dialect_risk import (
    BLOCKING_SEVERITIES,
    HIGH,
    LOW,
    MEDIUM,
    find_dialect_risks,
)

SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. T.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 A PIC X(5).
       01 B PIC S9(5)V99.
       01 C PIC S9(4) COMP.
       01 D PIC ZZ,ZZ9.99-.
       01 E PIC S9(5) COMP-3.
       01 F PIC 9(5).
       PROCEDURE DIVISION.
       P1.
           IF A < "ABC" DISPLAY "X" END-IF
           IF A > X'C1' CONTINUE END-IF
           COMPUTE B = (B / 3) ** 2
           DIVIDE B BY 7 GIVING E
           MOVE B TO A
           MOVE B TO D
           ADD 1 TO C
           PERFORM P2.
       P2.
           MOVE FUNCTION CURRENT-DATE TO A
           MOVE FUNCTION UPPER-CASE(A) TO A
           IF F > 5 CONTINUE END-IF
           ADD 1 TO F
           STOP RUN.
"""


def _risks():
    result = parse_cobol(SOURCE)
    return find_dialect_risks(result.ast, SOURCE.splitlines())


def _codes():
    return {(r.code, r.line) for r in _risks()}


def test_flags_each_known_construct_at_its_line():
    codes = _codes()
    assert ("EBCDIC_COLLATION", 13) in codes
    assert ("HEX_LITERAL", 14) in codes
    assert ("INTERMEDIATE_PRECISION", 15) in codes
    assert ("INTERMEDIATE_PRECISION", 16) in codes
    assert ("SIGN_OVERPUNCH", 17) in codes
    assert ("NUMERIC_EDITED", 18) in codes
    assert ("BINARY_TRUNCATION", 19) in codes
    assert ("CLOCK_DEPENDENT", 22) in codes
    assert ("INTRINSIC", 23) in codes


def test_numeric_comparisons_and_display_arithmetic_are_not_flagged():
    codes = _codes()
    assert not any(line in (24, 25) for _, line in codes)


def test_severities_and_paragraphs():
    by_code = {r.code: r for r in _risks()}
    assert by_code["HEX_LITERAL"].severity == HIGH
    assert by_code["EBCDIC_COLLATION"].severity == MEDIUM
    assert by_code["BINARY_TRUNCATION"].severity == LOW
    assert by_code["HEX_LITERAL"].paragraph == "P1"
    assert by_code["CLOCK_DEPENDENT"].paragraph == "P2"
    assert HIGH in BLOCKING_SEVERITIES and LOW not in BLOCKING_SEVERITIES


def test_sorted_most_severe_first():
    severities = [r.severity for r in _risks()]
    order = {HIGH: 0, MEDIUM: 1, LOW: 2}
    assert severities == sorted(severities, key=order.__getitem__)


def test_line_map_translates_and_unmapped_lines_become_none():
    result = parse_cobol(SOURCE)
    line_map = {13: 113}
    risks = find_dialect_risks(result.ast, SOURCE.splitlines(), line_map)
    collation = sorted(
        (r.line for r in risks if r.code == "EBCDIC_COLLATION"),
        key=lambda n: (n is None, n),
    )
    assert collation == [113, None]
    assert all(r.line is None for r in risks if r.code == "INTERMEDIATE_PRECISION")


def test_comment_lines_are_not_scanned_for_hex_literals():
    source = SOURCE.replace(
        "           IF A > X'C1' CONTINUE END-IF",
        "      *    IF A > X'C1' CONTINUE END-IF",
    )
    result = parse_cobol(source)
    codes = {r.code for r in find_dialect_risks(result.ast, source.splitlines())}
    assert "HEX_LITERAL" not in codes


def test_to_dict_carries_the_message():
    item = _risks()[0].to_dict()
    assert item["code"] == "HEX_LITERAL"
    assert "EBCDIC" in item["message"]
