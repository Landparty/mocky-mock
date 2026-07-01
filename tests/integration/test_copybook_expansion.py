import shutil
from pathlib import Path

import pytest

from mockymock.cli.main import main

requires_gnucobol = pytest.mark.skipif(
    shutil.which("cobc") is None, reason="GnuCOBOL (cobc) not installed"
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "copybook_example"


@requires_gnucobol
def test_run_expands_copybook_and_passes():
    exit_code = main(
        [
            "run",
            str(FIXTURE_DIR / "MAINPGM.cbl"),
            "--cut",
            str(FIXTURE_DIR / "MAINPGM.cut"),
            "--copybook-path",
            str(FIXTURE_DIR / "copybooks"),
        ]
    )
    assert exit_code == 0


def test_generate_expands_copybook_and_finds_call_site(tmp_path: Path):
    output = tmp_path / "MAINPGM.cut"
    exit_code = main(
        [
            "generate",
            str(FIXTURE_DIR / "MAINPGM.cbl"),
            "-o",
            str(output),
            "--copybook-path",
            str(FIXTURE_DIR / "copybooks"),
        ]
    )
    assert exit_code == 0
    assert 'MOCK CALL "DISCRATE"' in output.read_text()


def test_generate_without_copybook_path_leaves_copy_unresolved(tmp_path: Path):
    """`--copybook-path` is genuinely optional: omitting it must not crash
    argument parsing, and `generate` still runs to completion. But the CLI
    must not silently pretend the COPY statement was expanded -- without
    the flag, `COPY ORDREC.` is left unresolved by cobolparser (it does not
    raise a parse error; it simply produces zero data items for that
    section), which is the concrete, observable reason the flag matters and
    is not a no-op. This is checked directly against parse_cobol's AST
    rather than via a "PARSE_ERROR" refusal message, because cobolparser
    does not treat an unexpanded COPY as a parse error (verified: parsing
    the raw fixture source with no copybook path yields
    `result.success is True` and an empty `data_items` list for
    WORKING-STORAGE) -- so asserting a parse-error refusal here would be
    asserting something that is not true of the underlying parser.
    """
    from cobolparser import parse_cobol

    raw_source = (FIXTURE_DIR / "MAINPGM.cbl").read_text()
    result = parse_cobol(raw_source, filename="MAINPGM.cbl")
    assert result.success
    data_division = result.ast.get_division("DATA")
    working_storage = next(
        s for s in data_division.sections if s.section_name == "WORKING-STORAGE"
    )
    assert working_storage.data_items == []

    output = tmp_path / "MAINPGM.cut"
    exit_code = main(
        [
            "generate",
            str(FIXTURE_DIR / "MAINPGM.cbl"),
            "-o",
            str(output),
        ]
    )
    assert exit_code == 0
