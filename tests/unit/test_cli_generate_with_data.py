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
    assert 'MOVE "Y" TO WS-EOF' in text
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
    assert 'MOVE "Y" TO WS-EOF' in text


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
    """Neither --with-data nor --fixtures given -- there is no bundle at
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
    mockable, so the "should not happen" warning stays quiet."""
    for name in ("VSAMKSDS", "BATCHSEQ"):
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
        assert rc == 0
        assert "boundary key mismatch" not in capsys.readouterr().err, name
