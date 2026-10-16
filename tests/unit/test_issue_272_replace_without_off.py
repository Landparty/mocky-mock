"""Issue #272: a REPLACE left in force to the end of the source (no
closing REPLACE OFF) is standard COBOL and drops nothing, so it must not
be refused as PARSE_WARNING. An unparsable REPLACE still is."""

from cobolparser import parse_cobol

from mockymock.analysis.refusal._gates import check_whole_program_scoped

PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. RP.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       REPLACE ==TABLE-MAX== BY ==5==.
       01  WS-I    PIC 9(3) VALUE 0.
       01  WS-SUM  PIC 9(5) VALUE 0.
       PROCEDURE DIVISION.
       0000-MAIN.
           PERFORM VARYING WS-I FROM 1 BY 1 UNTIL WS-I > TABLE-MAX
               ADD WS-I TO WS-SUM
           END-PERFORM
           GOBACK.
"""


def test_replace_in_force_to_end_of_source_is_not_refused():
    result = parse_cobol(PROGRAM, filename="RP.cbl")
    assert any("still active at end of source" in str(w) for w in result.warnings)
    reasons, scoped = check_whole_program_scoped(result, PROGRAM)
    assert reasons == [] and scoped == []


def test_other_warnings_still_refuse():
    class _Result:
        errors: list = []
        warnings = ["REPLACE statement could not be parsed and was ignored"]
        success = True
        ast = None

    reasons, _ = check_whole_program_scoped(_Result(), PROGRAM)
    assert [r.code for r in reasons] == ["PARSE_WARNING"]
