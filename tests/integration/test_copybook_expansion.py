from pathlib import Path
from unittest.mock import patch

import pytest

from mockymock.cli.main import main
from tests.integration._docker import requires_docker

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "copybook_example"


@requires_docker
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


def test_generate_without_copybook_path_leaves_copy_unresolved(tmp_path: Path, capsys):
    """`--copybook-path` is genuinely optional: omitting it must not crash
    argument parsing. But the CLI must not silently pretend the COPY
    statement was expanded and proceed to scaffold against a program missing
    WORKING-STORAGE fields -- without the flag, `COPY ORDREC.` is left
    unresolved by cobolparser (it does not raise a parse error; it simply
    produces zero data items for that section), which is the concrete,
    observable reason the flag matters and is not a no-op. This is checked
    directly against parse_cobol's AST (rather than only via the CLI's
    refusal message), because cobolparser does not treat an unexpanded COPY
    as a parse error (verified: parsing the raw fixture source with no
    copybook path yields `result.success is True` and an empty `data_items`
    list for WORKING-STORAGE) -- so asserting a "PARSE_ERROR" refusal here
    would be asserting something that is not true of the underlying parser.

    Since mockymock cannot safely proceed with missing data items, `generate`
    now refuses cleanly with UNRESOLVED_COPYBOOK (exit 1) instead of the
    previous silent no-op (exit 0) -- replacing what would otherwise surface
    as a confusing downstream crash once splicing/compiling depended on the
    missing fields.
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
    assert exit_code == 1
    assert "UNRESOLVED_COPYBOOK" in capsys.readouterr().out


def test_generate_refuses_lossy_copybook_decode(tmp_path: Path, capsys):
    """A copybook whose bytes cannot be decoded losslessly is expanded with
    U+FFFD replacement characters; the only signal is
    `CopybookExpansion.statistics.warnings`. Corrupted DATA DIVISION content
    must refuse (EXPANSION_WARNING), not scaffold."""
    copybook_dir = tmp_path / "copybooks"
    copybook_dir.mkdir()
    (copybook_dir / "ORDREC.CPY").write_bytes(
        b"       01  ORD-AMOUNT PIC X(5) VALUE 'ab\xffcd'.\n"
    )
    output = tmp_path / "MAINPGM.cut"
    exit_code = main(
        [
            "generate",
            str(FIXTURE_DIR / "MAINPGM.cbl"),
            "-o",
            str(output),
            "--copybook-path",
            str(copybook_dir),
        ]
    )
    assert exit_code == 1
    assert "EXPANSION_WARNING" in capsys.readouterr().out
    assert not output.exists()


def test_generate_with_copybook_path_does_not_flag_unresolved_copybook(
    tmp_path: Path, capsys
):
    """With `--copybook-path` given and the copybook properly resolved, the
    UNRESOLVED_COPYBOOK check must not fire."""
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
    assert "UNRESOLVED_COPYBOOK" not in capsys.readouterr().out


def test_run_without_copybook_path_refuses_unresolved_copybook(capsys):
    """`run` on the copybook fixture without --copybook-path must refuse
    cleanly with UNRESOLVED_COPYBOOK and exit 1, rather than proceeding to
    splice/compile a program with missing WORKING-STORAGE fields (which
    previously surfaced as a confusing compile crash instead of a clean
    refusal). This must not require GnuCOBOL: the refusal fires before any
    splicing/compilation is attempted."""
    exit_code = main(
        [
            "run",
            str(FIXTURE_DIR / "MAINPGM.cbl"),
            "--cut",
            str(FIXTURE_DIR / "MAINPGM.cut"),
        ]
    )
    assert exit_code == 1
    assert "UNRESOLVED_COPYBOOK" in capsys.readouterr().out


class _StopAfterParse(Exception):
    """Raised by the `parse_cobol` spy to short-circuit the CLI command
    immediately after capturing the source text it was called with, so the
    test never needs GnuCOBOL or a real parse/compile to succeed."""


def _spy_and_capture(argv: list[str]) -> str:
    """Run `main(argv)` with `cobolparser.parse_cobol` patched to a spy that
    records the exact source text it receives and then aborts via
    `_StopAfterParse`. Returns that captured text.

    Patches `cobolparser.parse_cobol` (not `mockymock.cli.main.parse_cobol`)
    because both `_cmd_generate` and `_cmd_run` do a function-local
    `from cobolparser import parse_cobol` on every invocation -- there is no
    module-level `mockymock.cli.main.parse_cobol` binding to intercept, so
    the patch must target the name inside the `cobolparser` package itself.
    """
    captured: dict[str, str] = {}

    def fake_parse_cobol(source, *args, **kwargs):
        captured["source"] = source
        raise _StopAfterParse

    with patch("cobolparser.parse_cobol", side_effect=fake_parse_cobol):
        with pytest.raises(_StopAfterParse):
            main(argv)

    assert "source" in captured, "parse_cobol spy was never called"
    return captured["source"]


def test_run_with_copybook_path_expands_before_parsing():
    """Proves the `--copybook-path` wiring actually does something, rather
    than silently no-op'ing: inspects the literal source text handed to
    `parse_cobol` and checks it contains the expanded PIC clauses (and not
    the unresolved `COPY ORDREC.`) when the flag is given, and the reverse
    when it is omitted. Covers both `generate` and `run`, since both
    commands independently gate copybook expansion behind
    `if args.copybook_path:`.
    """
    cut_path = FIXTURE_DIR / "MAINPGM.cut"

    with_flag = _spy_and_capture(
        [
            "run",
            str(FIXTURE_DIR / "MAINPGM.cbl"),
            "--cut",
            str(cut_path),
            "--copybook-path",
            str(FIXTURE_DIR / "copybooks"),
        ]
    )
    assert "PIC 9(5)V99" in with_flag
    assert "COPY ORDREC" not in with_flag

    without_flag = _spy_and_capture(
        [
            "run",
            str(FIXTURE_DIR / "MAINPGM.cbl"),
            "--cut",
            str(cut_path),
        ]
    )
    assert "COPY ORDREC" in without_flag
    assert "PIC 9(5)V99" not in without_flag


def test_generate_with_copybook_path_expands_before_parsing(tmp_path: Path):
    """Same proof as above, against the `generate` command instead of
    `run` -- both commands have their own independent
    `if args.copybook_path: expand_copybooks(...)` gate in
    `mockymock/cli/main.py`, so each needs its own spy assertion."""
    output = tmp_path / "MAINPGM.cut"

    with_flag = _spy_and_capture(
        [
            "generate",
            str(FIXTURE_DIR / "MAINPGM.cbl"),
            "-o",
            str(output),
            "--copybook-path",
            str(FIXTURE_DIR / "copybooks"),
        ]
    )
    assert "PIC 9(5)V99" in with_flag
    assert "COPY ORDREC" not in with_flag

    without_flag = _spy_and_capture(
        [
            "generate",
            str(FIXTURE_DIR / "MAINPGM.cbl"),
            "-o",
            str(output),
        ]
    )
    assert "COPY ORDREC" in without_flag
    assert "PIC 9(5)V99" not in without_flag
