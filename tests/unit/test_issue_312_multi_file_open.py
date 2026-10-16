"""Issue #312: `OPEN INPUT A-FILE B-FILE` followed by `CLOSE B-FILE` /
`OPEN OUTPUT B-FILE`. The multi-file OPEN was scaffolded as `MOCK OPEN
A-FILE`, which left the later single-file OPEN needing `MOCK OPEN B-FILE`
-- and that MOCK also matches the multi-file site, so run refused the
generated suite AMBIGUOUS_MOCK. Generate (with and without a bundle), lint's
suggestion and --fill now key the multi-file site on the file another site
of the same verb uses, so one MOCK covers both."""

from __future__ import annotations

from cobolparser import parse_cobol

from mockymock.analysis.mock_surface import analyze
from mockymock.dsl.generator import directive_snippet, file_op_key

PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. MO.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT A-FILE ASSIGN TO "A.DAT"
               ORGANIZATION IS LINE SEQUENTIAL.
           SELECT B-FILE ASSIGN TO "B.DAT"
               ORGANIZATION IS LINE SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD  A-FILE.
       01  A-REC PIC X(5).
       FD  B-FILE.
       01  B-REC PIC X(5).
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT A-FILE B-FILE
           CLOSE B-FILE
           OPEN OUTPUT B-FILE
           GOBACK.
"""


def _open_sites():
    surface = analyze(parse_cobol(PROGRAM, filename="mo.cbl").ast)
    return surface, [s for s in surface.boundary_sites if s.label == "OPEN"]


def test_multi_file_open_is_keyed_on_the_file_another_open_uses() -> None:
    surface, (multi, single) = _open_sites()
    assert multi.keys == ("A-FILE", "B-FILE")
    assert file_op_key(multi, surface) == "B-FILE"
    assert file_op_key(single, surface) == "B-FILE"
    assert directive_snippet(multi, surface).lstrip().startswith("MOCK OPEN B-FILE")


def test_multi_file_open_without_a_matching_site_keeps_its_first_file() -> None:
    surface, (multi, _) = _open_sites()
    assert file_op_key(multi, None) == "A-FILE"


def test_generated_scaffolds_use_one_mock_per_verb(tmp_path) -> None:
    from mockymock.cli.main import main

    source = tmp_path / "MO.cbl"
    source.write_text(PROGRAM)
    for flags in ([], ["--with-data", "--seed", "1"]):
        out = tmp_path / "MO.cut"
        assert main(["generate", str(source), *flags, "-o", str(out), "--force"]) == 0
        cut = out.read_text()
        assert "MOCK OPEN A-FILE" not in cut
        assert cut.count("MOCK OPEN B-FILE") == 1
        assert main(["lint", str(source), "--cut", str(out)]) == 0
