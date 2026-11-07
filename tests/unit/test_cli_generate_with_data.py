"""CLI behavior tests for `mockymock generate --with-data`'s `--rows` and
`--placeholder` flags (Task 4 of the unify-with-data reconciliation plan,
docs/2026-08-04-unify-with-data-plan.md). Companion to
tests/unit/test_dsl_generator_bundle.py (which drives `scaffold_cut`
directly) and tests/integration/test_fixturedemo_golden.py (which pins the
no-new-flags `--fixtures` output byte-for-byte).

FIXTUREDEMO.cbl/.bundle.json/.cut (examples/fixtures/) are reused
throughout: the checked-in bundle already covers a multi-row READ boundary
and a single-row EXEC SQL boundary in one program, and its .cut is the
project's own canonical --with-data golden."""

from pathlib import Path

from mockymock.cli.main import main

_EXAMPLE_DIR = Path(__file__).resolve().parents[2] / "examples" / "fixtures"
_FIXTUREDEMO_CBL = _EXAMPLE_DIR / "FIXTUREDEMO.cbl"
_FIXTUREDEMO_BUNDLE = _EXAMPLE_DIR / "FIXTUREDEMO.bundle.json"
_FIXTUREDEMO_CUT_GOLDEN = _EXAMPLE_DIR / "FIXTUREDEMO.cut"


def _tally_count(cut_text: str) -> int:
    """Number of `WHEN <tally> = N` branches in the READ mock's
    tally-branching EVALUATE -- tracks the generated READ sequence length
    directly (see dsl.generator._read_body)."""
    return cut_text.count("-TALLY = ")


# --- --fixtures: no-new-flags output stays byte-identical -------------------


def test_generate_with_fixtures_no_new_flags_matches_checked_in_golden(tmp_path):
    out = tmp_path / "o.cut"
    rc = main(
        [
            "generate",
            str(_FIXTUREDEMO_CBL),
            "--fixtures",
            str(_FIXTUREDEMO_BUNDLE),
            "-o",
            str(out),
        ]
    )
    assert rc == 0
    assert out.read_text(encoding="utf-8") == _FIXTUREDEMO_CUT_GOLDEN.read_text(
        encoding="utf-8"
    )


def test_generate_with_data_no_new_flags_matches_checked_in_golden(tmp_path):
    """Same golden, reached via the self-generating --with-data path
    (--seed 42 reproduces the exact bundle FIXTUREDEMO.bundle.json was
    itself generated with -- see that file's own header comment)."""
    out = tmp_path / "o.cut"
    rc = main(
        [
            "generate",
            str(_FIXTUREDEMO_CBL),
            "--with-data",
            "--seed",
            "42",
            "-o",
            str(out),
        ]
    )
    assert rc == 0
    assert out.read_text(encoding="utf-8") == _FIXTUREDEMO_CUT_GOLDEN.read_text(
        encoding="utf-8"
    )


# --- --rows -------------------------------------------------------------


def test_rows_plumbed_into_self_generating_bundle_changes_read_sequence(tmp_path):
    default_out = tmp_path / "default.cut"
    rc = main(
        [
            "generate",
            str(_FIXTUREDEMO_CBL),
            "--with-data",
            "--seed",
            "42",
            "-o",
            str(default_out),
        ]
    )
    assert rc == 0
    default_count = _tally_count(default_out.read_text(encoding="utf-8"))
    assert default_count == 10  # cobolparser's DataGeneratorOptions default

    rows_out = tmp_path / "rows.cut"
    rc = main(
        [
            "generate",
            str(_FIXTUREDEMO_CBL),
            "--with-data",
            "--seed",
            "42",
            "--rows",
            "3",
            "-o",
            str(rows_out),
        ]
    )
    assert rc == 0
    assert _tally_count(rows_out.read_text(encoding="utf-8")) == 3


def test_rows_0_is_honored_not_treated_as_falsy(tmp_path):
    """Mirrors test_cli_fixtures.py's own --rows 0 test: `if args.rows` (a
    truthiness check) would silently drop a real `--rows 0`, since 0 is
    falsy in Python -- `is not None` is required."""
    out = tmp_path / "zero.cut"
    rc = main(
        [
            "generate",
            str(_FIXTUREDEMO_CBL),
            "--with-data",
            "--seed",
            "42",
            "--rows",
            "0",
            "-o",
            str(out),
        ]
    )
    assert rc == 0
    text = out.read_text(encoding="utf-8")
    assert _tally_count(text) == 0
    # Fix round 1 (unify-with-data Task 4): an empty sequence used to
    # short-circuit _read_body to a completely empty MOCK READ body -- no
    # EVALUATE/WHEN OTHER, no terminal MOVE, no replicated AT END MOVE --
    # which would hang FIXTUREDEMO's own PERFORM READ-ORDERS UNTIL
    # WS-EOF = "Y" loop forever if actually run under Docker (--rows
    # didn't exist on `generate` before this commit, so nothing could
    # reach that short-circuit here previously). _read_body now emits the
    # SAME "immediately at end" content its own WHEN OTHER branch would
    # have used instead: the real terminal status MOVE and the real
    # replicated AT END MOVE, with no EVALUATE wrapper since there is no
    # row-selecting branch to choose between with zero rows.
    assert 'MOVE "10" TO WS-ORDER-STATUS' in text
    # The AT END clause itself (`MOVE "Y" TO WS-EOF`) is no longer copied
    # into the mock: the splice runs the program's own clause once the
    # status reports end of file (issue #209).
    assert "the splice runs this READ's own AT END clause" in text
    assert "VERIFY READ ORDER-FILE WAS CALLED 1 TIMES" in text


def test_rows_0_output_round_trips_through_parse_cut(tmp_path):
    from mockymock.dsl.parser import parse_cut

    out = tmp_path / "zero.cut"
    rc = main(
        [
            "generate",
            str(_FIXTUREDEMO_CBL),
            "--with-data",
            "--seed",
            "42",
            "--rows",
            "0",
            "-o",
            str(out),
        ]
    )
    assert rc == 0
    suite = parse_cut(out.read_text(encoding="utf-8"))
    assert len(suite.test_cases) == 1


def test_fixtures_path_empty_read_sequence_still_emits_the_exhaustion_branch(
    tmp_path,
):
    """Hardens the `--fixtures` entry point too (fix round 1, unify-with-data
    Task 4): a bundle can legitimately carry an empty READ sequence on its
    own -- cobol-parser's own "empty input" fixed-family scenario
    (`--scenarios all`) does exactly this, no `--rows` involved at all --
    so the _read_body fix in dsl/generator.py (shared by both the
    --with-data and --fixtures paths) must benefit a hand-authored/
    externally-generated bundle JSON identically to the self-generating
    path. Builds a real bundle via ProgramFixtureGenerator(rows=0),
    writes it to a JSON file, and drives it through --fixtures (not
    --with-data) to prove this isn't just the self-generating
    construction path being fixed."""
    import json

    from cobolparser.generators import DataGeneratorOptions, ProgramFixtureGenerator

    bundle = ProgramFixtureGenerator(
        DataGeneratorOptions(rows=0)
    ).generate_with_scenarios_from_file(str(_FIXTUREDEMO_CBL), mode="happy", seed=42)
    bundle_path = tmp_path / "empty_read.bundle.json"
    bundle_path.write_text(json.dumps(bundle.to_dict()), encoding="utf-8")

    out = tmp_path / "o.cut"
    rc = main(
        [
            "generate",
            str(_FIXTUREDEMO_CBL),
            "--fixtures",
            str(bundle_path),
            "-o",
            str(out),
        ]
    )
    assert rc == 0
    text = out.read_text(encoding="utf-8")
    assert _tally_count(text) == 0
    assert 'MOVE "10" TO WS-ORDER-STATUS' in text
    # Issue #209: the splice runs the program's own AT END clause.
    assert "the splice runs this READ's own AT END clause" in text


def test_rows_negative_is_rejected(tmp_path, capsys):
    """--rows must be validated before any file parsing/generator
    construction (fix, post-PR #46 review, Task 4): a negative value used
    to fall through to DataGeneratorOptions and only get caught by the
    broad try/except around bundle generation, well after cheaper
    flag-only checks could have refused it immediately."""
    out = tmp_path / "o.cut"
    rc = main(
        [
            "generate",
            str(_FIXTUREDEMO_CBL),
            "--with-data",
            "--rows",
            "-1",
            "-o",
            str(out),
        ]
    )
    assert rc == 1
    assert not out.exists()
    err = capsys.readouterr().err
    assert "mockymock generate: --rows must be >= 0, got -1" in err


def test_rows_with_fixtures_file_is_rejected(tmp_path, capsys):
    out = tmp_path / "o.cut"
    rc = main(
        [
            "generate",
            str(_FIXTUREDEMO_CBL),
            "--fixtures",
            str(_FIXTUREDEMO_BUNDLE),
            "--rows",
            "5",
            "-o",
            str(out),
        ]
    )
    assert rc == 1
    assert not out.exists()
    err = capsys.readouterr().err
    assert "--rows" in err
    assert "--fixtures" in err


# --- --placeholder --------------------------------------------------------


def test_placeholder_downgrades_read_boundary_via_cli(tmp_path):
    """Fix round 2: also pins the empirically-reproduced critical bug --
    `generate --fixtures FIXTUREDEMO.bundle.json --placeholder
    READ:ORDER-FILE` used to keep the bundle's original `VERIFY READ
    ORDER-FILE WAS CALLED 11 TIMES` even though the downgraded body's
    real behavior (exhaustion on the very first call) only reaches READ
    once -- a generated .cut that deterministically fails its own
    assertion. Corrected to `1 TIMES`."""
    out = tmp_path / "o.cut"
    rc = main(
        [
            "generate",
            str(_FIXTUREDEMO_CBL),
            "--fixtures",
            str(_FIXTUREDEMO_BUNDLE),
            "--placeholder",
            "READ:ORDER-FILE",
            "-o",
            str(out),
        ]
    )
    assert rc == 0
    text = out.read_text(encoding="utf-8")
    assert "MOCK READ ORDER-FILE" in text  # still mocked
    assert "ORD001" not in text  # just not with seeded data
    assert "VERIFY READ ORDER-FILE WAS CALLED 11 TIMES" not in text
    assert "VERIFY READ ORDER-FILE WAS CALLED 1 TIMES" in text


def test_placeholder_downgrades_exec_sql_boundary_via_cli(tmp_path):
    out = tmp_path / "o.cut"
    rc = main(
        [
            "generate",
            str(_FIXTUREDEMO_CBL),
            "--fixtures",
            str(_FIXTUREDEMO_BUNDLE),
            "--placeholder",
            "SQL:SELECT",
            "-o",
            str(out),
        ]
    )
    assert rc == 0
    text = out.read_text(encoding="utf-8")
    assert 'MOCK SQL "SELECT"' in text  # still mocked
    assert "CHARLES GARCIA" not in text
    assert "MOVE 0 TO SQLCODE" in text


def test_placeholder_category_match_is_case_insensitive_key_is_not(tmp_path):
    """Spec: category compared uppercased; key matched exactly as the
    bundle carries it. A lowercase category still matches; a
    wrong-case key does not (falls through to the unmatched warning)."""
    out = tmp_path / "o.cut"
    rc = main(
        [
            "generate",
            str(_FIXTUREDEMO_CBL),
            "--fixtures",
            str(_FIXTUREDEMO_BUNDLE),
            "--placeholder",
            "read:ORDER-FILE",
            "-o",
            str(out),
        ]
    )
    assert rc == 0
    assert "ORD001" not in out.read_text(encoding="utf-8")


def test_placeholder_works_with_with_data_self_generating_path(tmp_path):
    out = tmp_path / "o.cut"
    rc = main(
        [
            "generate",
            str(_FIXTUREDEMO_CBL),
            "--with-data",
            "--seed",
            "42",
            "--placeholder",
            "READ:ORDER-FILE",
            "-o",
            str(out),
        ]
    )
    assert rc == 0
    text = out.read_text(encoding="utf-8")
    assert "MOCK READ ORDER-FILE" in text
    assert "ORD001" not in text


def test_malformed_placeholder_exits_1(tmp_path, capsys):
    out = tmp_path / "o.cut"
    rc = main(
        [
            "generate",
            str(_FIXTUREDEMO_CBL),
            "--fixtures",
            str(_FIXTUREDEMO_BUNDLE),
            "--placeholder",
            "nope",
            "-o",
            str(out),
        ]
    )
    assert rc == 1
    assert not out.exists()
    err = capsys.readouterr().err
    assert "CATEGORY:KEY" in err


def test_unmatched_placeholder_warns_on_stderr_but_still_succeeds(tmp_path, capsys):
    out = tmp_path / "o.cut"
    rc = main(
        [
            "generate",
            str(_FIXTUREDEMO_CBL),
            "--fixtures",
            str(_FIXTUREDEMO_BUNDLE),
            "--placeholder",
            "READ:NOT-A-REAL-KEY",
            "-o",
            str(out),
        ]
    )
    assert rc == 0
    assert out.exists()
    err = capsys.readouterr().err
    assert "READ:NOT-A-REAL-KEY" in err
    assert "matched no fixture" in err


def test_unmatched_placeholder_warning_omitted_when_matched(tmp_path, capsys):
    out = tmp_path / "o.cut"
    rc = main(
        [
            "generate",
            str(_FIXTUREDEMO_CBL),
            "--fixtures",
            str(_FIXTUREDEMO_BUNDLE),
            "--placeholder",
            "READ:ORDER-FILE",
            "-o",
            str(out),
        ]
    )
    assert rc == 0
    assert "matched no fixture" not in capsys.readouterr().err


def test_placeholder_without_any_bundle_warns_every_pair_and_still_succeeds(
    tmp_path, capsys
):
    """--per-paragraph (no --with-data/--fixtures) -- there is no bundle at
    all, so every requested pair is, by construction, unmatched (the
    `bundle.scenarios if bundle is not None else []` guard in
    _cmd_generate makes this the same code path as an unmatched pair
    against a real bundle). `generate` still succeeds via the ordinary
    bundle-less scaffold; --placeholder is simply a no-op there (nothing
    to downgrade -- see scaffold_cut's own docstring), reported rather
    than silently swallowed."""
    out = tmp_path / "o.cut"
    rc = main(
        [
            "generate",
            str(_FIXTUREDEMO_CBL),
            "--per-paragraph",
            "--placeholder",
            "READ:ORDER-FILE",
            "-o",
            str(out),
        ]
    )
    assert rc == 0
    err = capsys.readouterr().err
    assert "READ:ORDER-FILE" in err
    assert "matched no fixture" in err
    text = out.read_text(encoding="utf-8")
    assert "MOCK READ ORDER-FILE" in text
    assert (
        "ORD001" not in text
    )  # the ordinary bundle-less scaffold has no seeded data anyway


# --- boundary key mismatch warning (issue #164) ------------------------------

_ENTERPRISE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "enterprise"


def test_known_unmockable_sites_do_not_raise_the_key_mismatch_warning(tmp_path, capsys):
    """VSAMKSDS (READ/REWRITE/DELETE nested in a clause body) and BATCHSEQ
    (a READ nested in a clause body, `ACCEPT X FROM DATE YYYYMMDD`) only
    differ from their bundles by sites mockymock already lists as not
    mockable, so the "should not happen" warning stays quiet.

    Both happy paths reach a site nested inside another boundary's clause
    body (VSAMKSDS's DELETE, BATCHSEQ's RELEASE). Those used to be refused
    (generate exited 1, issues #231, #258); they are now spliced inside the
    enclosing statement's lifted clause body, so the scaffold lints clean."""
    for name, expected_rc in (("VSAMKSDS", 0), ("BATCHSEQ", 0)):
        out = tmp_path / f"{name}.cut"
        rc = main(
            [
                "generate",
                str(_ENTERPRISE_DIR / f"{name}.cbl"),
                "--with-data",
                "--seed",
                "42",
                "-o",
                str(out),
            ]
        )
        assert rc == expected_rc, name
        assert out.exists(), name
        assert "boundary key mismatch" not in capsys.readouterr().err, name


_CHKCLR = Path(__file__).resolve().parents[2] / "examples" / "real-world" / "CHKCLR"


_GOTO_MAIN = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. GOTOMAIN.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-X PIC 9 VALUE 0.
       PROCEDURE DIVISION.
       0000-MAIN.
           PERFORM 1000-STEP
           DISPLAY "X" STOP RUN.
       1000-STEP.
           ADD 1 TO WS-X
           IF WS-X < 3
               GO TO 0000-MAIN
           END-IF.
"""


def test_generate_fails_when_lint_refuses_the_scaffold_it_wrote(tmp_path, capsys):
    """Issue #231: a STOP RUN whose paragraph is itself a GO TO target
    can't be neutralized (and, sharing its line with a DISPLAY, cannot be
    spliced into a GOBACK to the test either), which lint refuses as
    UNSUPPORTED_TERMINATOR_LAYOUT. No MOCK block can fix that, so generate
    says so and exits 1 instead of 0 -- while still writing the file.
    (CHKCLR, this test's first subject, became testable once a GO TO to
    the end of a closed `PERFORM ... THRU 2000-EXIT` range stopped counting
    as falling past 2000-EXIT: see the next test.)"""
    program = tmp_path / "GOTOMAIN.cbl"
    program.write_text(_GOTO_MAIN, encoding="utf-8")
    out = tmp_path / "GOTOMAIN.cut"
    rc = main(["generate", str(program), "-o", str(out)])
    captured = capsys.readouterr()
    assert rc == 1
    assert out.exists()
    assert "UNSUPPORTED_TERMINATOR_LAYOUT" in captured.out + captured.err
    assert "lint` refuses it" in captured.err


def test_generate_scaffolds_chkclr_through_its_closed_thru_range(tmp_path, capsys):
    """CHKCLR's STOP RUN propagates back through 3000-FINALIZE, which sits
    after 2000-EXIT, the target of every GO TO in 2000-PROCESS-CHECKS. Those
    GO TOs only run inside `PERFORM 2000-PROCESS-CHECKS THRU 2000-EXIT`, so
    they return from it and never fall into 3000-FINALIZE: the scaffold is
    not refused."""
    out = tmp_path / "CHKCLR.cut"
    rc = main(
        [
            "generate",
            str(_CHKCLR / "CHKCLR.cbl"),
            "--copybook-path",
            str(_CHKCLR / "copybooks"),
            "-o",
            str(out),
        ]
    )
    captured = capsys.readouterr()
    assert rc == 0
    assert "UNSUPPORTED_TERMINATOR_LAYOUT" not in captured.out + captured.err


# Regression: executed bug hunt of 2026-10-05 (issues #139-#150); the executed
# counterparts live in tests/integration/test_bug_hunt_m1_fixes.py.
import shutil

import pytest

from tests.unit._generate import _generate

FETCH_CBL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. FETCH.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
           EXEC SQL INCLUDE SQLCA END-EXEC.
       01  HV-ID     PIC X(4).
       01  WS-COUNT  PIC 9(4) VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           EXEC SQL OPEN C1 END-EXEC
           PERFORM FETCH-PARA UNTIL SQLCODE = 100
           EXEC SQL CLOSE C1 END-EXEC
           DISPLAY WS-COUNT
           GOBACK.
       FETCH-PARA.
           EXEC SQL FETCH C1 INTO :HV-ID END-EXEC
           IF SQLCODE = 0
               ADD 1 TO WS-COUNT
           END-IF.
"""


def test_141_one_row_looped_fetch_is_mocked_with_rows_and_counted_once_more(
    tmp_path,
) -> None:
    cut = _generate(tmp_path, "FETCH", FETCH_CBL, "--seed", "1")
    assert 'MOCK SQL "FETCH" ROWS' in cut
    assert 'VERIFY SQL "FETCH" WAS CALLED 2 TIMES' in cut


def test_141_fetch_outside_a_loop_keeps_its_single_row_body(tmp_path) -> None:
    cbl = FETCH_CBL.replace(
        "PERFORM FETCH-PARA UNTIL SQLCODE = 100", "PERFORM FETCH-PARA"
    )
    cut = _generate(tmp_path, "FETCH", cbl, "--seed", "1")
    assert 'MOCK SQL "FETCH" ROWS' not in cut
    assert 'VERIFY SQL "FETCH" WAS CALLED 1 TIMES' in cut


TWO_CBL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TWO.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-N PIC 9 VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           CALL "FMT" USING WS-N
           CALL "FMT" USING WS-N
           GOBACK.
"""


def test_142_two_call_sites_of_one_key_render_one_summed_verify(tmp_path) -> None:
    cut = _generate(tmp_path, "TWO", TWO_CBL, "--seed", "1")
    assert cut.count('VERIFY CALL "FMT"') == 1
    assert 'VERIFY CALL "FMT" WAS CALLED 2 TIMES' in cut


def test_142_a_conditional_extra_site_demotes_the_summed_count(tmp_path) -> None:
    cbl = TWO_CBL.replace(
        '           CALL "FMT" USING WS-N\n           GOBACK.',
        '           IF WS-N > 5\n               CALL "FMT" USING WS-N\n'
        "           END-IF\n           GOBACK.",
    )
    cut = _generate(tmp_path, "TWO", cbl, "--seed", "1")
    assert 'VERIFY CALL "FMT" WAS CALLED 2 TIMES' not in cut
    assert '*> VERIFY CALL "FMT" WAS CALLED <count not exact' in cut


UNR_CBL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. UNR.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-N PIC 9 VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           CALL "SUBA" USING WS-N
           GOBACK.
       DEAD-PARA.
           CALL "SUBB" USING WS-N.
"""


def test_143_generate_does_not_mock_a_boundary_the_case_cannot_reach(
    tmp_path, capsys
) -> None:
    from mockymock.cli.main import main

    cut = _generate(tmp_path, "UNR", UNR_CBL, "--seed", "1")
    assert 'MOCK CALL "SUBA"' in cut
    assert '"SUBB"' not in cut
    capsys.readouterr()
    assert main(["lint", str(tmp_path / "UNR.cbl")]) == 0, capsys.readouterr().out


_ENTERPRISE = Path(__file__).resolve().parents[1] / "fixtures" / "enterprise"


@pytest.mark.parametrize(
    "program", sorted(p.stem for p in _ENTERPRISE.glob("*.cbl")), ids=str
)
def test_143_no_generated_enterprise_cut_has_an_unmatched_mock(
    tmp_path, capsys, program
) -> None:
    from mockymock.cli.main import main

    source = tmp_path / f"{program}.cbl"
    shutil.copy(_ENTERPRISE / f"{program}.cbl", source)
    shutil.copytree(_ENTERPRISE / "copybooks", tmp_path / "copybooks")
    copybooks = ["--copybook-path", str(tmp_path / "copybooks")]
    out = tmp_path / f"{program}.cut"
    if (
        main(
            [
                "generate",
                str(source),
                "--with-data",
                "--seed",
                "1",
                "-o",
                str(out),
                *copybooks,
            ]
        )
        != 0
        # Since #231 generate exits 1 when lint refuses the scaffold it
        # still wrote; that file must still carry no UNMATCHED_MOCK.
        and not out.exists()
    ):
        pytest.skip("generate --with-data does not support this program")
    capsys.readouterr()
    main(["lint", str(source), *copybooks])
    assert "UNMATCHED_MOCK" not in capsys.readouterr().out


QUAL_CBL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. QUAL.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-REC.
           05  WS-QTY PIC 9(3) VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 42 TO WS-QTY
           DISPLAY WS-QTY
           GOBACK.
"""


DUPF_CBL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. DUPF.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-FILE ASSIGN TO "IN.DAT"
               ORGANIZATION IS LINE SEQUENTIAL
               FILE STATUS IS WS-IN-STATUS.
           SELECT OUT-FILE ASSIGN TO "OUT.DAT"
               ORGANIZATION IS LINE SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD  IN-FILE.
       01  IN-REC.
           05  CUST-ID   PIC X(5).
           05  CUST-AMT  PIC 9(5).
       FD  OUT-FILE.
       01  OUT-REC.
           05  CUST-ID   PIC X(5).
           05  CUST-AMT  PIC 9(5).
       WORKING-STORAGE SECTION.
       01  WS-IN-STATUS PIC XX.
       01  WS-EOF       PIC X VALUE "N".
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT IN-FILE
           OPEN OUTPUT OUT-FILE
           PERFORM READ-PARA UNTIL WS-EOF = "Y"
           CLOSE IN-FILE
           CLOSE OUT-FILE
           GOBACK.
       READ-PARA.
           READ IN-FILE
               AT END MOVE "Y" TO WS-EOF
           END-READ
           IF WS-EOF = "N"
               MOVE CUST-ID OF IN-REC TO CUST-ID OF OUT-REC
               MOVE CUST-AMT OF IN-REC TO CUST-AMT OF OUT-REC
               WRITE OUT-REC
           END-IF.
"""


def test_144_expect_uses_the_cobol_leaf_name_not_record_dot_field(tmp_path) -> None:
    cut = _generate(tmp_path, "QUAL", QUAL_CBL, "--seed", "1")
    assert "EXPECT WS-QTY TO BE 42" in cut
    assert "WS-REC.WS-QTY" not in cut


def test_144_ambiguous_read_fields_are_qualified_with_their_record(tmp_path) -> None:
    cut = _generate(tmp_path, "DUPF", DUPF_CBL, "--seed", "1", "--rows", "2")
    assert "TO CUST-ID OF IN-REC" in cut
    assert "TO CUST-ID\n" not in cut


PARM_CBL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PARM.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT PARM-FILE ASSIGN TO "PARM.DAT"
               ORGANIZATION IS LINE SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD  PARM-FILE.
       01  PARM-REC.
           05  PARM-DAYS  PIC 9(3).
       WORKING-STORAGE SECTION.
       01  WS-DAYS PIC 9(3) VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT PARM-FILE
           READ PARM-FILE
           MOVE PARM-DAYS TO WS-DAYS
           CLOSE PARM-FILE
           GOBACK.
"""


def test_read_outside_any_loop_is_verified_once_whatever_the_row_count(
    tmp_path,
) -> None:
    """Found while checking #144 against the legacy corpus (DORMACCT): a
    parameter-card READ got `VERIFY ... 10 TIMES` from the bundle's row
    count."""
    cut = _generate(tmp_path, "PARM", PARM_CBL, "--seed", "1", "--rows", "5")
    assert "VERIFY READ PARM-FILE WAS CALLED 1 TIMES" in cut


def test_148_generated_sql_open_and_close_bodies_set_sqlcode(tmp_path) -> None:
    cut = _generate(tmp_path, "FETCH", FETCH_CBL, "--seed", "1")
    for key in ("OPEN", "CLOSE"):
        block = cut.split(f'MOCK SQL "{key}"', 1)[1].split("END-MOCK", 1)[0]
        assert "MOVE 0 TO SQLCODE" in block


DLITCBL_CBL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. DLIENT.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  DLI-GU     PIC X(4) VALUE "GU  ".
       01  WS-SEG     PIC X(10).
       LINKAGE SECTION.
       01  CUST-PCB.
           05  PCB-DBD     PIC X(8).
           05  PCB-LEVEL   PIC XX.
           05  PCB-STATUS  PIC XX.
       PROCEDURE DIVISION.
       ENTRY 'DLITCBL' USING CUST-PCB.
       MAIN-PARA.
           CALL 'CBLTDLI' USING DLI-GU CUST-PCB WS-SEG
           GOBACK.
"""


def test_150_an_ims_dlitcbl_program_falls_back_to_its_first_paragraph(
    tmp_path,
) -> None:
    cut = _generate(tmp_path, "DLIENT", DLITCBL_CBL, "--seed", "1")
    assert "TESTCASE" in cut
    assert "PERFORM MAIN-PARA" in cut


def test_150_generate_fails_when_no_scenario_becomes_a_case(
    tmp_path, monkeypatch
) -> None:
    from mockymock.cli.main import main
    from mockymock.dsl.generator import scaffold as generator

    monkeypatch.setattr(generator, "_first_paragraph", lambda program: None)
    source = tmp_path / "DLIENT.cbl"
    source.write_text(DLITCBL_CBL)
    out = tmp_path / "DLIENT.cut"
    assert main(["generate", str(source), "--with-data", "-o", str(out)]) == 1


# Regression: LegacyLens "Create tests" (generate, record, play) over the NIST
# CCVS85 suite, 2026-11-02 (examples/nist-cobol85/generated/README.md).
from mockymock.dsl.parser import parse_cut

# --- generate: a READ whose rows move nothing (NIST IX301M) ----------------

EMPTY_ROWS = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. EMPTYROW.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT TFIL ASSIGN TO "TFIL"
               ORGANIZATION IS INDEXED
               ACCESS MODE IS RANDOM
               RECORD KEY IS RKEY.
       DATA DIVISION.
       FILE SECTION.
       FD  TFIL.
       01  FREC.
           03 RKEY  PIC X(8).
       WORKING-STORAGE SECTION.
       01  STATE    PIC X(4) VALUE SPACES.
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN I-O TFIL.
           PERFORM READ-PARA 3 TIMES.
           CLOSE TFIL.
           STOP RUN.
       READ-PARA.
           READ TFIL INVALID KEY MOVE "INV" TO STATE
               NOT INVALID KEY MOVE "OK" TO STATE.
"""


def _nist_generate(tmp_path: Path, name: str, source: str, capsys) -> tuple[str, str]:
    program = tmp_path / f"{name}.cbl"
    program.write_text(source)
    cut = tmp_path / f"{name}.cut"
    main(["generate", str(program), "-o", str(cut), "--force", "--scenarios", "all"])
    return cut.read_text(), capsys.readouterr().err


def test_read_rows_that_move_nothing_get_no_empty_when(tmp_path, capsys):
    """A keyed READ of a record holding only its key: each generated row
    moved nothing, and `WHEN tally = 1 ... WHEN tally = 10 END-EVALUATE`
    with no statement failed cobc 3.1 ("invalid expression")."""
    text, _ = _nist_generate(tmp_path, "EMPTYROW", EMPTY_ROWS, capsys)
    assert "UT-READ-TFIL-TALLY" not in text
    for case in parse_cut(text).test_cases:
        assert case.perform_target == "MAIN-PARA"


# --- a WRITE of a record qualified by its file (NIST SQ207M) ---------------


def test_write_of_a_qualified_record_keys_on_the_record_name(tmp_path, capsys):
    """`WRITE PRINT-REC IN PRINT-FILE` made generate write `MOCK WRITE
    PRINT-REC IN PRINT-FILE`, which the .cut grammar cannot parse: the
    whole suite failed to load."""
    source = (
        EMPTY_ROWS.replace(
            "       FD  TFIL.\n       01  FREC.\n           03 RKEY  PIC X(8).\n",
            "       FD  TFIL.\n       01  FREC.\n           03 RKEY  PIC X(8).\n"
            "       FD  PFIL.\n       01  PREC PIC X(10).\n",
        )
        .replace(
            '           SELECT TFIL ASSIGN TO "TFIL"\n',
            '           SELECT PFIL ASSIGN TO "PFIL".\n'
            '           SELECT TFIL ASSIGN TO "TFIL"\n',
        )
        .replace(
            "           CLOSE TFIL.\n",
            "           CLOSE TFIL.\n           OPEN OUTPUT PFIL.\n"
            "           WRITE PREC IN PFIL.\n           WRITE PREC OF PFIL.\n"
            "           CLOSE PFIL.\n",
        )
    )
    text, _ = _nist_generate(tmp_path, "QUALWRT", source, capsys)
    suite = parse_cut(text)
    keys = {(d.category.value, d.key) for d in suite.test_cases[0].mocks}
    assert ("WRITE", "PREC") in keys
    assert not any(" " in key for _, key in keys)
