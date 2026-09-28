"""End-to-end proof for `mockymock run --record-expectations`: a
`*> STUB EXPECT` comment becomes a real `EXPECT` line after a real
GnuCOBOL compile-and-run, the rewrite is idempotent on a second pass (the
"golden re-run drift test" docs/2026-08-04-record-expectations-design.md's
PR-slicing gate names), and a case excluded by `--case` is left completely
untouched.

A genuine STOP-RUN-mid-case "crashed before the record point" skip path is
intentionally not exercised here: constructing one that survives
mockymock's own terminator-neutralization feature (`.okf/splicer.md`)
needs a GO TO/SECTION shape not worth building into this fixture. That
skip reason is covered at the unit level instead --
tests/unit/test_record_rewrite.py::
test_stub_whose_case_never_recorded_is_skipped_as_crashed."""

from pathlib import Path

from mockymock.cli.main import main
from tests.integration._docker import requires_docker

FIXTURES = Path(__file__).parent / "fixtures"
PROGRAM = FIXTURES / "record_expectations_example.cbl"


@requires_docker
def test_record_expectations_fills_in_every_stub(tmp_path: Path):
    cut = (FIXTURES / "record_expectations_example.cut").read_text()
    working = tmp_path / "record_expectations_example.cut"
    working.write_text(cut)

    exit_code = main(
        ["run", str(PROGRAM), "--cut", str(working), "--record-expectations"]
    )

    assert exit_code == 0
    rewritten = working.read_text()
    assert "STUB EXPECT" not in rewritten
    assert "EXPECT WS-NET-TOTAL TO BE 0040" in rewritten  # 20 * 2, case one
    assert "EXPECT WS-NET-TOTAL TO BE 0014" in rewritten  # 7 * 2, case two
    # The pre-existing, already-real EXPECT lines are untouched.
    assert rewritten.count("EXPECT WS-DISCOUNT-CODE TO BE 5") == 2


@requires_docker
def test_record_expectations_does_not_affect_the_run_s_pass_fail_result(
    tmp_path: Path,
):
    """Recording is a side channel, not a replacement mode: a suite that
    already passes must still exit 0 with --record-expectations."""
    cut = (FIXTURES / "record_expectations_example.cut").read_text()
    working = tmp_path / "record_expectations_example.cut"
    working.write_text(cut)

    exit_code = main(
        ["run", str(PROGRAM), "--cut", str(working), "--record-expectations"]
    )

    assert exit_code == 0


@requires_docker
def test_record_expectations_is_idempotent_on_a_second_run(tmp_path: Path):
    """The core guarantee: once a stub becomes a real EXPECT, nothing this
    feature does can ever touch that line again (see the design doc's
    "structural, not tracked" section) -- a second run must leave the file
    byte-for-byte unchanged."""
    cut = (FIXTURES / "record_expectations_example.cut").read_text()
    working = tmp_path / "record_expectations_example.cut"
    working.write_text(cut)

    main(["run", str(PROGRAM), "--cut", str(working), "--record-expectations"])
    once_recorded = working.read_text()
    assert "STUB EXPECT" not in once_recorded  # sanity: first pass did its job

    exit_code = main(
        ["run", str(PROGRAM), "--cut", str(working), "--record-expectations"]
    )

    assert exit_code == 0
    assert working.read_text() == once_recorded


@requires_docker
def test_record_expectations_leaves_an_excluded_case_untouched(tmp_path: Path):
    cut = (FIXTURES / "record_expectations_example.cut").read_text()
    working = tmp_path / "record_expectations_example.cut"
    working.write_text(cut)

    exit_code = main(
        [
            "run",
            str(PROGRAM),
            "--cut",
            str(working),
            "--record-expectations",
            "--case",
            "doubles a quantity of 20",
        ]
    )

    assert exit_code == 0
    rewritten = working.read_text()
    # The selected case's stub was recorded...
    assert "EXPECT WS-NET-TOTAL TO BE 0040" in rewritten
    # ...but the excluded case's stub comment is completely untouched.
    assert "*> STUB EXPECT WS-NET-TOTAL -- case two" in rewritten
    assert "EXPECT WS-NET-TOTAL TO BE 0014" not in rewritten


@requires_docker
def test_record_expectations_renders_signed_and_implied_decimal_fields(
    tmp_path: Path,
):
    """Under -std=mvs GnuCOBOL DISPLAYs a signed field with a separate
    sign (`005+`, `00250-`, `+00005` for COMP) and drops an implied
    decimal point (`00250` for 2.50). Rendered from that text alone the
    recorded goldens were `"005+"` and a bare `00250` -- EXPECT lines that
    failed on the very next run. The rewritten file must pass as-is."""
    program = FIXTURES / "record_expectations_signed.cbl"
    working = tmp_path / "signed.cut"
    working.write_text(
        'TESTSUITE "signed"\n'
        'TESTCASE "halves five"\n'
        "    MOVE 0 TO WS-QTY\n"
        "    PERFORM CALC-TOTALS\n"
        "    *> STUB EXPECT WS-QTY\n"
        "    *> STUB EXPECT WS-HALF\n"
        "    *> STUB EXPECT WS-REFUND\n"
        "    *> STUB EXPECT WS-UNSIGNED-HALF\n"
        "    *> STUB EXPECT WS-BIN\n"
    )

    assert (
        main(["run", str(program), "--cut", str(working), "--record-expectations"]) == 0
    )
    rewritten = working.read_text()
    assert "EXPECT WS-QTY TO BE 005\n" in rewritten
    assert "EXPECT WS-HALF TO BE 002.50\n" in rewritten
    assert "EXPECT WS-REFUND TO BE -002.50\n" in rewritten
    assert "EXPECT WS-UNSIGNED-HALF TO BE 002.50\n" in rewritten
    assert "EXPECT WS-BIN TO BE 00005\n" in rewritten

    # The recorded goldens are the program's real values: a plain re-run
    # of the rewritten file passes.
    assert main(["run", str(program), "--cut", str(working)]) == 0
