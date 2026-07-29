"""End-to-end proof for a PROCEDURE DIVISION copybook: one that supplies a
whole paragraph invoked via PERFORM, not just WORKING-STORAGE fields.
COPY expansion is textual and happens before parsing, so the copybook's
paragraph is testable exactly like an inline one -- directly (PERFORM its
own name) and as a stubbed collaborator (MOCK PARAGRAPH) of its caller. See
examples/cpyproc/README.md."""

from pathlib import Path

from mockymock.cli.main import main
from tests.integration._docker import requires_docker

EXAMPLE_DIR = Path(__file__).parent.parent.parent / "examples" / "cpyproc"
COPYBOOK_PATH = EXAMPLE_DIR / "copybooks"


@requires_docker
def test_committed_cpyproc_example_passes():
    exit_code = main(
        [
            "run",
            str(EXAMPLE_DIR / "CPYPROC.cbl"),
            "--cut",
            str(EXAMPLE_DIR / "CPYPROC.cut"),
            "--copybook-path",
            str(COPYBOOK_PATH),
        ]
    )
    assert exit_code == 0


@requires_docker
def test_cpyproc_fails_when_flow_mock_verify_count_is_wrong(tmp_path: Path):
    """Proves the flow-mock tally on a copybook-sourced paragraph is real
    accounting, not a rubber stamp -- mutating the expected PERFORMED count
    must fail closed, same as examples/flowmock's own proof."""
    cut = (EXAMPLE_DIR / "CPYPROC.cut").read_text()
    original = "VERIFY PARAGRAPH CALC-DISCOUNT WAS PERFORMED ONCE"
    assert original in cut
    broken = tmp_path / "CPYPROC.cut"
    broken.write_text(
        cut.replace(original, "VERIFY PARAGRAPH CALC-DISCOUNT WAS PERFORMED 2 TIMES")
    )
    exit_code = main(
        [
            "run",
            str(EXAMPLE_DIR / "CPYPROC.cbl"),
            "--cut",
            str(broken),
            "--copybook-path",
            str(COPYBOOK_PATH),
        ]
    )
    assert exit_code == 1


def test_run_without_copybook_path_refuses_unresolved_copybook(capsys):
    """This must not require GnuCOBOL: the refusal fires before any
    splicing/compilation is attempted -- same fail-closed guarantee as
    tests/integration/fixtures/copybook_example, now checked against a
    copybook that supplies procedure logic instead of data."""
    exit_code = main(
        [
            "run",
            str(EXAMPLE_DIR / "CPYPROC.cbl"),
            "--cut",
            str(EXAMPLE_DIR / "CPYPROC.cut"),
        ]
    )
    assert exit_code == 1
    assert "UNRESOLVED_COPYBOOK" in capsys.readouterr().out


def test_expansion_turns_copybook_paragraph_into_ordinary_perform_target():
    """The core claim this example exists to prove: COPY expansion is
    textual and happens before parsing, so CALC-DISCOUNT (defined only in
    copybooks/CALCPERF.CPY) becomes an ordinary paragraph in the expanded
    source -- bit-for-bit indistinguishable from one typed inline by the
    time anything looks at paragraph names. Nothing in mock_surface.py or
    refusal.py's reachability BFS special-cases copybook origin; this is
    why they don't have to."""
    from cobolparser.preprocess import expand_copybooks

    raw_source = (EXAMPLE_DIR / "CPYPROC.cbl").read_text()
    expansion = expand_copybooks(raw_source, copybook_paths=[str(COPYBOOK_PATH)])
    assert "COPY CALCPERF" not in expansion.expanded_source
    assert "CALC-DISCOUNT." in expansion.expanded_source
    assert 'CALL "DISCRATE"' in expansion.expanded_source


def test_generate_scaffolds_testcase_for_copybook_paragraph(tmp_path: Path):
    """`mockymock generate` groups boundary sites by paragraph name after
    copybook expansion, so it discovers CALC-DISCOUNT's own CALL boundary
    the same way it would for a paragraph typed directly in the program."""
    output = tmp_path / "CPYPROC.cut"
    exit_code = main(
        [
            "generate",
            str(EXAMPLE_DIR / "CPYPROC.cbl"),
            "-o",
            str(output),
            "--copybook-path",
            str(COPYBOOK_PATH),
        ]
    )
    assert exit_code == 0
    generated = output.read_text()
    assert 'MOCK CALL "DISCRATE"' in generated
    assert "PERFORM CALC-DISCOUNT" in generated
