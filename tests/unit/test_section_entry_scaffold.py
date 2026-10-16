"""Issue #238: on a section-structured program (main line directly under
`A000-MAIN SECTION.`, no paragraph name) the scaffold must PERFORM the
main SECTION, not the first named paragraph of a later section."""

from mockymock.cli.main import main

SECTIONED = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SECT.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-RATE PIC 9(3) VALUE 0.
       01  WS-AMT  PIC 9(3) VALUE 0.
       01  WS-TOT  PIC 9(6) VALUE 0.
       PROCEDURE DIVISION.
       A000-MAIN SECTION.
           CALL "GETRATE" USING WS-RATE
           PERFORM B000-CALC
           GOBACK.
       B000-CALC SECTION.
       B010-COMPUTE.
           CALL "GETAMT" USING WS-AMT
           COMPUTE WS-TOT = WS-AMT * WS-RATE.
       B099-EXIT.
           EXIT.
"""


def _generate(tmp_path, *extra: str) -> str:
    source = tmp_path / "SECT.cbl"
    source.write_text(SECTIONED)
    out = tmp_path / "SECT.cut"
    assert main(["generate", str(source), "-o", str(out), "--seed", "1", *extra]) == 0
    return out.read_text()


def test_generate_enters_a_section_structured_program_at_its_main_section(
    tmp_path,
) -> None:
    cut = _generate(tmp_path)
    assert "PERFORM A000-MAIN" in cut
    assert "PERFORM B010-COMPUTE" not in cut
    assert 'MOCK CALL "GETRATE"' in cut
    assert 'MOCK CALL "GETAMT"' in cut


def test_branch_scenarios_enter_at_the_main_section_too(tmp_path) -> None:
    cut = _generate(tmp_path, "--scenarios", "all")
    performs = [line.strip() for line in cut.splitlines() if "PERFORM " in line]
    assert performs and set(performs) == {"PERFORM A000-MAIN"}


def test_first_paragraph_keeps_a_named_leading_paragraph() -> None:
    from cobolparser import parse_cobol

    from mockymock.dsl.generator import _first_paragraph

    plain = SECTIONED.replace(
        "       A000-MAIN SECTION.\n", "       A000-MAIN SECTION.\n       A010-GO.\n"
    )
    assert _first_paragraph(parse_cobol(plain).ast) == "A000-MAIN"
    unsectioned = SECTIONED.replace(
        "       A000-MAIN SECTION.\n", "       0000-MAIN.\n"
    )
    assert _first_paragraph(parse_cobol(unsectioned).ast) == "0000-MAIN"
