"""A TESTCASE with no EXPECT/VERIFY passes whenever its PERFORM runs. lint
warns about it (NO_ASSERTION, exit code unchanged), run reports it as
risky, and `generate` defaults to one case per scenario with
--per-paragraph as the opt-out."""

from pathlib import Path

from mockymock.cli.main import main
from mockymock.dsl.parser import parse_cut
from mockymock.report.formatters import format_console
from mockymock.report.json_report import build_json_report, risky_case_ids
from mockymock.report.results import parse_stdout

_EXAMPLES = Path(__file__).resolve().parents[2] / "examples"
_ORDRPROC_CBL = _EXAMPLES / "ordrproc" / "ORDRPROC.cbl"
_FIXTUREDEMO_CBL = _EXAMPLES / "fixtures" / "FIXTUREDEMO.cbl"

_CUT = """\
TESTSUITE "s"

TESTCASE "asserts"
    PERFORM PROCESS-ORDER
    EXPECT WS-NET-AMOUNT TO BE 90.00

TESTCASE "bare"
    PERFORM PROCESS-ORDER
"""

_STDOUT = """\
__MOCKYMOCK__ TESTSUITE: s
__MOCKYMOCK__ CASE 001 START: asserts
__MOCKYMOCK__ CASE 001 END
__MOCKYMOCK__ CASE 002 START: bare
__MOCKYMOCK__ CASE 002 END
__MOCKYMOCK__ SUMMARY: RUN=2 FAILURES=0
"""


# --- lint -----------------------------------------------------------------


def test_lint_warns_on_a_case_with_no_assertions_without_failing(tmp_path, capsys):
    cut = tmp_path / "ORDRPROC.cut"
    cut.write_text(
        (_EXAMPLES / "ordrproc" / "ORDRPROC.cut").read_text()
        + '\nTESTCASE "bare"\n    MOCK CALL "DISCRATE"\n    END-MOCK\n'
        + "    PERFORM PROCESS-ORDER\n"
    )
    line = cut.read_text().splitlines().index('TESTCASE "bare"') + 1
    assert main(["lint", str(_ORDRPROC_CBL), "--cut", str(cut)]) == 0
    out = capsys.readouterr().out
    assert (
        f'mockymock lint: warning (NO_ASSERTION): .cut line {line}: TESTCASE "bare" '
        "asserts nothing" in out
    )
    assert "mockymock lint: 1 warning(s)." in out
    assert "mockymock lint: no problems found." in out


def test_lint_clean_example_has_no_warning(capsys):
    assert (
        main(
            [
                "lint",
                str(_ORDRPROC_CBL),
                "--cut",
                str(_EXAMPLES / "ordrproc" / "ORDRPROC.cut"),
            ]
        )
        == 0
    )
    assert "NO_ASSERTION" not in capsys.readouterr().out


def test_lint_still_warns_when_a_refusal_stops_the_checks(tmp_path, capsys):
    cbl = tmp_path / "BAD.cbl"
    cbl.write_text("this is not cobol\n")
    cut = tmp_path / "BAD.cut"
    cut.write_text('TESTSUITE "s"\nTESTCASE "bare"\n    PERFORM P\n')
    assert main(["lint", str(cbl), "--cut", str(cut)]) == 1
    out = capsys.readouterr().out
    assert "warning (NO_ASSERTION): .cut line 2:" in out
    assert "problem(s) found." in out


# --- run reports ----------------------------------------------------------


def test_json_report_marks_a_passing_case_with_no_assertions_risky():
    report = build_json_report(parse_stdout(_STDOUT), cut_suite=parse_cut(_CUT))
    by_name = {case["name"]: case for case in report["cases"]}
    assert by_name["asserts"]["status"] == "passed"
    assert by_name["asserts"]["assertions"] == 1
    assert by_name["asserts"]["risky"] is False
    assert by_name["bare"]["status"] == "passed"
    assert by_name["bare"]["assertions"] == 0
    assert by_name["bare"]["risky"] is True
    assert report["summary"]["casesRisky"] == 1


def test_json_report_without_a_cut_model_claims_nothing():
    report = build_json_report(parse_stdout(_STDOUT))
    assert all(case["risky"] is False for case in report["cases"])
    assert all(case["assertions"] is None for case in report["cases"])


def test_console_labels_risky_passes():
    result = parse_stdout(_STDOUT)
    risky = risky_case_ids(result, parse_cut(_CUT))
    assert risky == ["002"]
    text = format_console(result, risky=risky)
    assert "  [PASS] asserts\n" in text
    assert "  [PASS] bare (risky: asserts nothing)" in text
    assert "2 run, 0 failed, 1 risky" in text


# --- generate's default unit ----------------------------------------------


def test_generate_defaults_to_one_case_per_scenario(tmp_path, capsys):
    out = tmp_path / "o.cut"
    assert main(["generate", str(_FIXTUREDEMO_CBL), "--seed", "7", "-o", str(out)]) == 0
    assert "data-driven from a fixture bundle (seed=7)" in capsys.readouterr().out
    explicit = tmp_path / "explicit.cut"
    assert (
        main(
            [
                "generate",
                str(_FIXTUREDEMO_CBL),
                "--with-data",
                "--seed",
                "7",
                "-o",
                str(explicit),
            ]
        )
        == 0
    )
    assert out.read_text() == explicit.read_text()


def test_per_paragraph_keeps_the_old_scaffold(tmp_path, capsys):
    out = tmp_path / "o.cut"
    assert (
        main(["generate", str(_FIXTUREDEMO_CBL), "--per-paragraph", "-o", str(out)])
        == 0
    )
    assert "fixture bundle" not in capsys.readouterr().out
    assert "boundaries:" in out.read_text()


def test_per_paragraph_conflicts_with_with_data(tmp_path, capsys):
    rc = main(
        [
            "generate",
            str(_FIXTUREDEMO_CBL),
            "--per-paragraph",
            "--with-data",
            "-o",
            str(tmp_path / "o.cut"),
        ]
    )
    assert rc == 1
    assert "--per-paragraph is not valid together with" in capsys.readouterr().err


def _break_the_generator(monkeypatch):
    import cobolparser.generators as generators

    def boom(self, *args, **kwargs):
        raise TypeError("Expected type, got ABCMeta")

    monkeypatch.setattr(
        generators.ProgramFixtureGenerator, "generate_with_scenarios_from_file", boom
    )


def test_default_falls_back_to_per_paragraph_when_the_generator_fails(
    tmp_path, capsys, monkeypatch
):
    _break_the_generator(monkeypatch)
    out = tmp_path / "o.cut"
    assert main(["generate", str(_FIXTUREDEMO_CBL), "-o", str(out)]) == 0
    text = capsys.readouterr().out
    assert "fixture bundle generation failed: Expected type, got ABCMeta" in text
    assert "falling back to one test case per paragraph" in text
    assert "boundaries:" in out.read_text()


def test_explicit_with_data_still_fails_when_the_generator_fails(
    tmp_path, capsys, monkeypatch
):
    _break_the_generator(monkeypatch)
    out = tmp_path / "o.cut"
    assert main(["generate", str(_FIXTUREDEMO_CBL), "--with-data", "-o", str(out)]) == 1
    assert "falling back" not in capsys.readouterr().out
    assert not out.exists()


def test_lint_warns_on_a_label_that_covers_no_assertion(tmp_path, capsys):
    """Issue #346: a misplaced INTENT/CHARACTERIZATION label is a lint
    warning, not a silent no-op."""
    cut = tmp_path / "ORDRPROC.cut"
    cut.write_text(
        (_EXAMPLES / "ordrproc" / "ORDRPROC.cut").read_text()
        + "\n    *> INTENT: dangling after the last assertion\n"
    )
    line = len(cut.read_text().splitlines())
    assert main(["lint", str(_ORDRPROC_CBL), "--cut", str(cut)]) == 0
    out = capsys.readouterr().out
    assert f"warning (ORPHAN_ASSERTION_LABEL): .cut line {line}:" in out
    assert "mockymock lint: no problems found." in out


# Regression: open gaps the cobol-test run on PAYMAIN + PAYCALC found
# (2026-11-06); executed counterpart:
# tests/integration/test_open_gaps_2026_11_06.py. lint and generate agree on
# cases that only hold `*> STUB EXPECT` comments.
import shutil

from mockymock.cli.checks import (
    cases_asserting_nothing,
    no_assertion_warnings,
    stub_case_lines,
)

FIXTURES = Path(__file__).parent.parent / "fixtures" / "open_gaps_2026_11_06"


CUT = """TESTSUITE "T"

TESTCASE "stubbed"
    PERFORM 0000-MAIN
    *> STUB EXPECT WS-A -- set by the program
    *> STUB EXPECT WS-B

TESTCASE "empty"
    PERFORM 0000-MAIN

TESTCASE "asserted"
    PERFORM 0000-MAIN
    EXPECT WS-A TO BE "X"
"""


def test_stub_case_lines_counts_each_case_block():
    suite = parse_cut(CUT)
    assert stub_case_lines(CUT, suite) == {3: 2}


def test_lint_names_the_pending_stubs_generate_leaves_out():
    suite = parse_cut(CUT)
    warnings = no_assertion_warnings(suite, CUT)
    assert len(warnings) == 2
    assert 'TESTCASE "stubbed" asserts nothing yet' in warnings[0]
    assert "2 `*> STUB EXPECT` comment(s)" in warnings[0]
    assert "--record-expectations" in warnings[0]
    assert 'TESTCASE "empty" asserts nothing --' in warnings[1]
    # generate's count: the stubbed case is left out, as before.
    assert cases_asserting_nothing(CUT, stubs_count=True) == [
        '.cut line 8: TESTCASE "empty"'
    ]
    # Without the text (older callers) the wording is unchanged.
    assert all("yet" not in w for w in no_assertion_warnings(suite))


def test_generate_and_lint_counts_now_add_up(tmp_path, monkeypatch, capsys):
    shutil.copy(FIXTURES / "PAYMAIN.cbl", tmp_path / "PAYMAIN.cbl")
    monkeypatch.chdir(tmp_path)
    assert main(["generate", "PAYMAIN.cbl", "--per-paragraph"]) == 0
    out = capsys.readouterr().out
    assert "1 test case(s) assert nothing" in out
    assert "2 test case(s) have no EXPECT yet, only `*> STUB EXPECT`" in out
    main(["lint", "PAYMAIN.cbl"])
    lint = capsys.readouterr().out
    assert lint.count("warning (NO_ASSERTION)") == 3
    assert lint.count("asserts nothing yet") == 2
