"""CLI behavior tests (non-Docker-specific)."""

import json

from mockymock.cli.main import main


def test_generate_reports_terminators_separately_from_unmockable(tmp_path, capsys):
    cbl = tmp_path / "TERMDEMO.cbl"
    cbl.write_text(
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. TERMDEMO.\n"
        "\n"
        "       PROCEDURE DIVISION.\n"
        "       0000-MAIN-PROCESS.\n"
        "           STOP RUN.\n"
    )
    exit_code = main(["generate", str(cbl)])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "STOP RUN/GOBACK site(s) detected" in out
    assert "will be refused" not in out


def test_generate_circular_copybook_reports_a_problem_instead_of_raising(
    tmp_path, capsys
):
    """Audit finding F6: unlike _cmd_fixtures, _cmd_generate's own
    expand_copybooks() call had no try/except -- a circular COPY (or an
    oversized/deeply-nested chain, or a mis-encoded copybook file) raised
    a raw Python traceback instead of a clean, on-topic error."""
    (tmp_path / "SELFREF.cpy").write_text("           COPY SELFREF.\n")
    cbl = tmp_path / "P.cbl"
    cbl.write_text(
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. P.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       COPY SELFREF.\n"
    )
    exit_code = main(["generate", str(cbl), "--copybook-path", str(tmp_path)])
    assert exit_code == 1
    out = capsys.readouterr().out
    assert "Circular copybook dependency" in out


def test_generate_bad_output_dir_reports_cleanly(tmp_path, capsys):
    """2026-08-12 audit Finding 13: generate's -o write was a bare
    write_text with no guard -- a bad parent directory raised a raw
    OSError traceback after a full parse+analyze pass, unlike run/export
    whose writes route through _write_report_file."""
    cbl = tmp_path / "TERMDEMO.cbl"
    cbl.write_text(
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. TERMDEMO.\n"
        "\n"
        "       PROCEDURE DIVISION.\n"
        "       0000-MAIN-PROCESS.\n"
        "           STOP RUN.\n"
    )
    # A missing parent is created (issue #257); a parent that is a file
    # still cannot be, and the failure goes to stderr.
    (tmp_path / "no").write_text("x")
    bad_target = tmp_path / "no" / "such" / "dir" / "out.cut"
    exit_code = main(["generate", str(cbl), "-o", str(bad_target)])
    assert exit_code == 1
    err = capsys.readouterr().err
    assert "could not write" in err
    assert str(bad_target) in err


def test_mutate_bad_json_report_dir_reports_cleanly(tmp_path, capsys, monkeypatch):
    """Finding 13's mutate half: --json-report was a bare write_text; a
    bad parent directory raised a raw traceback AFTER a full (potentially
    multi-minute) mutation run. Like run's report flags, a failed
    auxiliary write must not flip an otherwise-clean outcome's exit code."""
    import mockymock.mutation.runner as runner
    from mockymock.mutation.operators import Mutant
    from mockymock.mutation.report import MutantResult, MutationOutcome

    mutant = Mutant(
        line=6,
        operator="move-literal",
        original="           MOVE 1 TO WS-X.",
        mutated="           MOVE 2 TO WS-X.",
        description="MOVE literal changed",
    )
    outcome = MutationOutcome(
        program="P.cbl",
        cut="P.cut",
        results=[MutantResult(mutant=mutant, status="killed", detail="")],
    )
    monkeypatch.setattr(
        runner,
        "run_mutation",
        lambda *args, **kwargs: ([], outcome, []),
    )
    cbl = tmp_path / "P.cbl"
    cbl.write_text("           MOVE 1 TO WS-X.\n")
    cut = tmp_path / "P.cut"
    cut.write_text('TESTSUITE "s"\n')
    (tmp_path / "no").write_text("x")  # a missing dir would be created (#257)
    bad_target = tmp_path / "no" / "such" / "dir" / "report.json"
    exit_code = main(
        [
            "mutate",
            str(cbl),
            "--cut",
            str(cut),
            "--json-report",
            str(bad_target),
        ]
    )
    err = capsys.readouterr().err
    assert "could not write" in err
    assert exit_code == 0  # outcome was clean; the report file is auxiliary


def test_skills_without_subcommand_prints_skills_usage(capsys):
    """2026-08-12 audit Finding 14: `mockymock skills` used to print the
    full top-level help (all subcommands) because only skills install set
    a func default."""
    exit_code = main(["skills"])
    assert exit_code == 1
    out = capsys.readouterr().out
    assert "install" in out
    # The top-level subcommand list must NOT be what got printed.
    assert "mutate" not in out


def test_mutate_list_refuses_flags_it_would_silently_ignore(tmp_path, capsys):
    """2026-08-12 audit Finding 16: --list returned before --json-report/
    --fail-under were ever read, silently ignoring them."""
    cbl = tmp_path / "P.cbl"
    cbl.write_text("           MOVE 1 TO WS-X.\n")
    cut = tmp_path / "P.cut"
    cut.write_text('TESTSUITE "s"\n')
    exit_code = main(
        [
            "mutate",
            str(cbl),
            "--cut",
            str(cut),
            "--list",
            "--json-report",
            str(tmp_path / "r.json"),
        ]
    )
    assert exit_code == 1
    out = capsys.readouterr().out
    assert "--list" in out
    assert "--json-report" in out


# --- mockymock lint -------------------------------------------------------

from pathlib import Path

_EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


def test_lint_clean_example_reports_no_problems(capsys):
    exit_code = main(
        [
            "lint",
            str(_EXAMPLES / "ordrproc" / "ORDRPROC.cbl"),
            "--cut",
            str(_EXAMPLES / "ordrproc" / "ORDRPROC.cut"),
        ]
    )
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "mockymock lint: no problems found." in out


def test_lint_reports_problems_and_count(tmp_path, capsys):
    cbl = tmp_path / "BAD.cbl"
    cbl.write_text("this is not cobol\n")
    cut = tmp_path / "BAD.cut"
    cut.write_text('TESTSUITE "s"\n')
    exit_code = main(["lint", str(cbl), "--cut", str(cut)])
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "mockymock lint: refused (" in out
    assert "problem(s) found." in out


def test_lint_reports_invalid_cut_file(tmp_path, capsys):
    cut = tmp_path / "X.cut"
    cut.write_text("NOT A DIRECTIVE\n")
    exit_code = main(
        ["lint", str(_EXAMPLES / "ordrproc" / "ORDRPROC.cbl"), "--cut", str(cut)]
    )
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "invalid .cut file" in out


_CAPTURE_REPRO_CBL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. REPRO.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A          PIC 9(5).
       01  WS-B          PIC 9(5).
       01  WS-CAPTURED   PIC 9(5).
       PROCEDURE DIVISION.
       RICH-PATH.
           CALL "VALIDATE" USING WS-A WS-B.
       LEAN-PATH.
           CALL "VALIDATE" USING WS-A.
"""

# Two independent cases mocking the SAME key; only "rich" CAPTUREs, and only
# "rich" reaches the two-argument site. LEAN-PATH's one-argument site is
# unreachable from "rich" -- yet splice_program matches "rich"'s directive
# against it anyway (directive_matches_site is category+key only, blind to
# which case is being spliced), so build_site_dispatch would emit
# `CAPTURE ARG 2` there and raise.
_CAPTURE_REPRO_CUT = """\
TESTSUITE "repro"
TESTCASE "rich"
    MOCK CALL "VALIDATE"
        CAPTURE ARG 2 INTO WS-CAPTURED
    END-MOCK
    PERFORM RICH-PATH
TESTCASE "lean"
    MOCK CALL "VALIDATE"
        MOVE 0 TO WS-A
    END-MOCK
    PERFORM LEAN-PATH
"""


def _write_capture_repro(tmp_path):
    cbl = tmp_path / "REPRO.cbl"
    cbl.write_text(_CAPTURE_REPRO_CBL)
    cut = tmp_path / "REPRO.cut"
    cut.write_text(_CAPTURE_REPRO_CUT)
    return cbl, cut


def test_lint_refuses_capture_arg_against_a_site_only_another_case_reaches(
    tmp_path, capsys
):
    """Whole-branch review bug: the CAPTURE_ARG_OUT_OF_RANGE gate filtered
    sites by the owning case's reachability while the splicer does not, so
    `lint` reported no problems and `export`/`run` then died with an
    unhandled ValueError from injector.build_site_dispatch. The gate now
    checks every matching site program-wide, so the CLI refuses cleanly."""
    cbl, cut = _write_capture_repro(tmp_path)
    exit_code = main(["lint", str(cbl), "--cut", str(cut)])
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "mockymock lint: refused (CAPTURE_ARG_OUT_OF_RANGE)" in out
    assert "LEAN-PATH" in out
    assert "1 USING parameter" in out


def test_export_refuses_the_same_shape_instead_of_raising(tmp_path, capsys):
    """The other half of the invariant: whenever build_site_dispatch could
    raise its CAPTURE_ARG_OUT_OF_RANGE ValueError, the gate must have
    refused first -- so export exits 1 with a refusal, never a traceback."""
    cbl, cut = _write_capture_repro(tmp_path)
    exit_code = main(
        ["export", str(cbl), "--cut", str(cut), "--out", str(tmp_path / "out")]
    )
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "refused (CAPTURE_ARG_OUT_OF_RANGE)" in out


def test_lint_missing_inputs_fail_cleanly(tmp_path, capsys):
    exit_code = main(
        ["lint", str(tmp_path / "NOPE.cbl"), "--cut", str(tmp_path / "NOPE.cut")]
    )
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "mockymock lint: no such file" in out


_AMBIGUOUS_REPRO_CBL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. REPRO.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-FILE ASSIGN TO "IN"
               ORGANIZATION IS SEQUENTIAL.
           SELECT OUT-FILE ASSIGN TO "OUT"
               ORGANIZATION IS SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD  IN-FILE.
       01  IN-REC PIC X(10).
       FD  OUT-FILE.
       01  OUT-REC PIC X(10).
       PROCEDURE DIVISION.
       MAIN-BOTH.
           PERFORM CASE-A-PATH.
           PERFORM CASE-B-PATH.
       CASE-A-PATH.
           OPEN INPUT IN-FILE.
           CLOSE IN-FILE.
       CASE-B-PATH.
           OPEN OUTPUT OUT-FILE.
           CLOSE OUT-FILE.
       DEAD-CODE-PATH.
           OPEN INPUT IN-FILE OUTPUT OUT-FILE.
           CLOSE IN-FILE OUT-FILE.
"""

# One test case, mocking IN-FILE and OUT-FILE separately for its own
# reachable single-file OPEN/CLOSE sites (CASE-A-PATH, CASE-B-PATH) -- no
# ambiguity there. DEAD-CODE-PATH's multi-file OPEN/CLOSE is never PERFORMed
# by anyone, so no test case's own reachability BFS ever examines it -- yet
# orchestrator.splice_program matches directives to sites program-wide
# (directive_matches_site is category+key only, blind to reachability), so
# both of this case's directives match DEAD-CODE-PATH's sites too, and
# injector.build_site_dispatch would raise its "matched by multiple
# directives ... AMBIGUOUS_MOCK" ValueError.
_AMBIGUOUS_REPRO_CUT = """\
TESTSUITE "repro"
TESTCASE "both"
    MOCK OPEN IN-FILE
    END-MOCK
    MOCK OPEN OUT-FILE
    END-MOCK
    MOCK CLOSE IN-FILE
    END-MOCK
    MOCK CLOSE OUT-FILE
    END-MOCK
    PERFORM MAIN-BOTH
"""


def _write_ambiguous_repro(tmp_path):
    cbl = tmp_path / "REPRO.cbl"
    cbl.write_text(_AMBIGUOUS_REPRO_CBL)
    cut = tmp_path / "REPRO.cut"
    cut.write_text(_AMBIGUOUS_REPRO_CUT)
    return cbl, cut


def test_lint_refuses_ambiguous_mock_against_a_site_unreachable_by_any_case(
    tmp_path, capsys
):
    """Whole-program review bug: the AMBIGUOUS_MOCK gate only examined
    sites reachable from the owning case's own PERFORM target, while the
    splicer matches directives to sites program-wide with no reachability
    filter at all -- so `lint` reported no problems and `export`/`run` then
    died with an unhandled ValueError from injector.build_site_dispatch
    ("matched by multiple directives ... AMBIGUOUS_MOCK"). The gate now
    checks every matching site program-wide too, so the CLI refuses
    cleanly instead."""
    cbl, cut = _write_ambiguous_repro(tmp_path)
    exit_code = main(["lint", str(cbl), "--cut", str(cut)])
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "mockymock lint: refused (AMBIGUOUS_MOCK)" in out
    assert "DEAD-CODE-PATH" in out


def test_export_refuses_the_ambiguous_mock_shape_instead_of_raising(tmp_path, capsys):
    """The other half of the invariant: whenever build_site_dispatch could
    raise its AMBIGUOUS_MOCK ValueError, the gate must have refused first --
    so export exits 1 with a refusal, never a traceback."""
    cbl, cut = _write_ambiguous_repro(tmp_path)
    exit_code = main(
        ["export", str(cbl), "--cut", str(cut), "--output", str(tmp_path / "out.cbl")]
    )
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "refused (AMBIGUOUS_MOCK)" in out


# --- mockymock collect ----------------------------------------------------


def test_collect_json_lists_cases_with_lines_and_tags(tmp_path, capsys):
    cut = tmp_path / "PROG.cut"
    cut.write_text(
        'TESTSUITE "demo suite"\n'
        "\n"
        'TESTCASE "first" TAGS "fast"\n'
        "    PERFORM MAIN\n"
        "\n"
        'TESTCASE "second"\n'
        "    PERFORM MAIN\n"
    )
    exit_code = main(["collect", "--cut", str(cut), "--json"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["version"] == 1
    assert payload["suite"] == {"name": "demo suite", "line": 1}
    assert payload["cases"] == [
        {"name": "first", "line": 3, "tags": ["fast"]},
        {"name": "second", "line": 6, "tags": []},
    ]


def test_collect_human_listing(tmp_path, capsys):
    cut = tmp_path / "PROG.cut"
    cut.write_text('TESTSUITE "s"\nTESTCASE "only"\n    PERFORM MAIN\n')
    exit_code = main(["collect", "--cut", str(cut)])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "TESTSUITE 's' (line 1)" in out
    assert "TESTCASE 'only' (line 2)" in out
    assert "1 test case(s)" in out


def test_collect_invalid_cut_reports_error_in_json(tmp_path, capsys):
    cut = tmp_path / "PROG.cut"
    cut.write_text("junk\n")
    exit_code = main(["collect", "--cut", str(cut), "--json"])
    assert exit_code == 1
    payload = json.loads(capsys.readouterr().out)
    assert "error" in payload


def test_collect_lists_expanded_provider_cases(tmp_path, capsys):
    cut = tmp_path / "PROG.cut"
    cut.write_text(
        'TESTSUITE "s"\n'
        "PROVIDER Nums\n"
        "    HEADER N\n"
        "    ROW 1\n"
        "    ROW 2\n"
        'TESTCASE "c" USING PROVIDER Nums\n'
        "    MOVE {N} TO WS-N\n"
        "    PERFORM MAIN\n"
    )
    exit_code = main(["collect", "--cut", str(cut), "--json"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert [c["name"] for c in payload["cases"]] == [
        "c [row 1: 1]",
        "c [row 2: 2]",
    ]


# --- mockymock run --trace ------------------------------------------------
# The refusal below must fire before Docker is touched, so these tests need
# no daemon and no valid .cbl/.cut -- reaching the toolchain at all would
# itself be the failure.


def _trace_files(tmp_path):
    cbl = tmp_path / "P.cbl"
    cbl.write_text(
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. P.\n"
        "       PROCEDURE DIVISION.\n"
        "       0000-MAIN.\n"
        "           DISPLAY 'HI'.\n"
    )
    cut = tmp_path / "P.cut"
    cut.write_text('TESTSUITE "P"\n\nTESTCASE "a"\n    PERFORM 0000-MAIN\nEND\n')
    return cbl, cut


def test_trace_without_any_case_is_refused(tmp_path, capsys):
    cbl, cut = _trace_files(tmp_path)
    exit_code = main(["run", str(cbl), "--cut", str(cut), "--trace"])
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "--trace requires exactly one --case" in out


def test_trace_with_two_cases_is_refused(tmp_path, capsys):
    cbl, cut = _trace_files(tmp_path)
    exit_code = main(
        ["run", str(cbl), "--cut", str(cut), "--trace", "--case", "a", "--case", "b"]
    )
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "--trace requires exactly one --case" in out


def test_trace_with_a_tag_selection_is_refused(tmp_path, capsys):
    cbl, cut = _trace_files(tmp_path)
    exit_code = main(
        [
            "run",
            str(cbl),
            "--cut",
            str(cut),
            "--trace",
            "--case",
            "a",
            "--tag",
            "smoke",
        ]
    )
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "--trace requires exactly one --case" in out


def test_trace_json_implies_trace_and_inherits_the_same_refusal(tmp_path, capsys):
    """--trace-json alone (no --case) must hit the trace refusal, which only
    happens if it turned --trace on first."""
    cbl, cut = _trace_files(tmp_path)
    exit_code = main(
        ["run", str(cbl), "--cut", str(cut), "--trace-json", str(tmp_path / "t.json")]
    )
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "--trace requires exactly one --case" in out


# --- mockymock debug --------------------------------------------------------
# Like the trace refusals above, these must fire before Docker is touched.


def test_debug_without_dap_stdio_is_refused(tmp_path, capsys):
    cbl, cut = _trace_files(tmp_path)
    exit_code = main(["debug", str(cbl), "--cut", str(cut), "--case", "a"])
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "--dap-stdio" in out
    assert "VS Code extension" in out


def test_debug_without_any_case_is_refused(tmp_path, capsys):
    cbl, cut = _trace_files(tmp_path)
    exit_code = main(["debug", str(cbl), "--cut", str(cut), "--dap-stdio"])
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "requires exactly one --case" in out


def test_debug_with_two_cases_is_refused(tmp_path, capsys):
    cbl, cut = _trace_files(tmp_path)
    exit_code = main(
        [
            "debug",
            str(cbl),
            "--cut",
            str(cut),
            "--dap-stdio",
            "--case",
            "a",
            "--case",
            "b",
        ]
    )
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "requires exactly one --case" in out


def test_debug_refuses_before_touching_missing_files(tmp_path, capsys):
    """The --dap-stdio/case-count refusals fire before file-existence
    checks would even matter, but a missing file must still be refused
    cleanly once those pass, not raise."""
    exit_code = main(
        [
            "debug",
            str(tmp_path / "missing.cbl"),
            "--cut",
            str(tmp_path / "missing.cut"),
            "--dap-stdio",
            "--case",
            "a",
        ]
    )
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "no such file" in out
