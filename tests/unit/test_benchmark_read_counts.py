"""READ call counts from the 2026-11-14 benchmark run against a real z/OS
codebase: a bundle whose line numbers are not mockymock's (another
copybook expansion) lost the end-of-file read, and a read loop that can
GOBACK on a row value kept the bundle's rows + 1 (PDBRP16A)."""

import json

from mockymock.cli.main import main
from mockymock.dsl.entry_parameters import fixture_generator
from mockymock.dsl.fixture_bundle import inline_fixtures

READ_LOOP = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. RDLOOP.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-FILE ASSIGN TO INF
               ORGANIZATION IS SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD  IN-FILE.
       01  IN-REC.
           05  IN-TYPE    PIC X(2).
               88  IN-V9  VALUE 'V9'.
           05  IN-NAME    PIC X(10).
       WORKING-STORAGE SECTION.
       01  WS-EOF PIC X VALUE 'N'.
           88  END-OF-FILE VALUE 'Y'.
       01  WS-CNT PIC 9(4) VALUE 0.
       PROCEDURE DIVISION.
       0000-MAIN.
           OPEN INPUT IN-FILE
           PERFORM 2000-READ
           PERFORM 1000-ROW UNTIL END-OF-FILE
           CLOSE IN-FILE
           GOBACK.
       1000-ROW.
      *EXIT
           ADD 1 TO WS-CNT
           PERFORM 2000-READ.
       2000-READ.
           READ IN-FILE
               AT END SET END-OF-FILE TO TRUE
           END-READ.
"""

EARLY_EXIT = READ_LOOP.replace(
    "      *EXIT\n",
    "           IF IN-V9\n"
    "               CLOSE IN-FILE\n"
    "               GOBACK\n"
    "           END-IF\n",
)


def _shifted_bundle(source, shift: int) -> dict:
    """The bundle `generate` would build, every line moved by `shift`: what
    a bundle made from another copybook expansion looks like."""
    bundle = fixture_generator(None).generate_with_scenarios_from_file(
        str(source), mode="happy", seed=1
    )
    data = inline_fixtures(bundle.to_dict())

    def move(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "line" and isinstance(value, int):
                    node[key] = value + shift
                else:
                    move(value)
        elif isinstance(node, list):
            for value in node:
                move(value)

    move(data)
    return data


def test_a_bundle_numbered_by_another_expansion_keeps_the_end_of_file_read(
    tmp_path,
):
    """No READ site sat on the bundle's line, so the AT END was not seen
    and the count was the rows alone (PDBRP36A: "11 TIMES" generated as
    10)."""
    source = tmp_path / "RDLOOP.cbl"
    source.write_text(READ_LOOP)
    fixtures = tmp_path / "bundle.json"
    fixtures.write_text(json.dumps(_shifted_bundle(source, 7)))
    out = tmp_path / "RDLOOP.cut"
    main(["generate", str(source), "--fixtures", str(fixtures), "-o", str(out)])
    assert "VERIFY READ IN-FILE WAS CALLED 11 TIMES" in out.read_text()


def test_a_read_loop_that_can_goback_on_a_row_gets_no_row_count(tmp_path):
    """PDBRP16A: the first generated row selects V9, which GOBACKs after
    one READ; `11 TIMES` could never pass."""
    source = tmp_path / "EARLYX.cbl"
    source.write_text(EARLY_EXIT)
    out = tmp_path / "EARLYX.cut"
    main(["generate", str(source), "--with-data", "--seed", "1", "-o", str(out)])
    cut = out.read_text()
    assert "VERIFY READ IN-FILE WAS CALLED 11 TIMES" not in cut
    assert "*> VERIFY READ IN-FILE WAS CALLED <count not exact" in cut
    assert "can end the run before end of file" in cut


def test_a_read_loop_with_no_exit_keeps_its_row_count(tmp_path):
    source = tmp_path / "RDLOOP.cbl"
    source.write_text(READ_LOOP)
    out = tmp_path / "RDLOOP.cut"
    main(["generate", str(source), "--with-data", "--seed", "1", "-o", str(out)])
    assert "VERIFY READ IN-FILE WAS CALLED 11 TIMES" in out.read_text()
