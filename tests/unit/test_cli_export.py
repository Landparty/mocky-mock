"""CLI behavior tests for `mockymock export` (Docker-free, mirrors
tests/unit/test_cli.py's style)."""

from pathlib import Path

from mockymock.cli.main import main

_EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


def test_export_missing_inputs_fail_cleanly(tmp_path, capsys):
    exit_code = main(
        ["export", str(tmp_path / "NOPE.cbl"), "--cut", str(tmp_path / "NOPE.cut")]
    )
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "mockymock export: no such file" in out


def test_export_writes_default_output_next_to_program(tmp_path, capsys):
    cbl = tmp_path / "PROG.cbl"
    cbl.write_text(
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. PROG.\n"
        "       PROCEDURE DIVISION.\n"
        "       MAIN-PROCESS.\n"
        '           DISPLAY "HI".\n'
    )
    cut = tmp_path / "PROG.cut"
    cut.write_text('TESTSUITE "s"\nTESTCASE "c"\n    PERFORM MAIN-PROCESS\n')

    exit_code = main(["export", str(cbl), "--cut", str(cut)])
    out = capsys.readouterr().out
    assert exit_code == 0
    output_path = tmp_path / "PROG.mainframe.cbl"
    assert output_path.exists()
    assert "wrote mainframe-compilable source" in out
    assert str(output_path) in out


def test_export_writes_to_explicit_output_path(tmp_path, capsys):
    cbl = tmp_path / "PROG.cbl"
    cbl.write_text(
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. PROG.\n"
        "       PROCEDURE DIVISION.\n"
        "       MAIN-PROCESS.\n"
        '           DISPLAY "HI".\n'
    )
    cut = tmp_path / "PROG.cut"
    cut.write_text('TESTSUITE "s"\nTESTCASE "c"\n    PERFORM MAIN-PROCESS\n')
    output_path = tmp_path / "custom.cbl"

    exit_code = main(
        ["export", str(cbl), "--cut", str(cut), "--output", str(output_path)]
    )
    assert exit_code == 0
    assert output_path.exists()


def test_export_keeps_process_cbl_directives_that_run_would_strip(tmp_path, capsys):
    cbl = tmp_path / "PROG.cbl"
    cbl.write_text(
        "       CBL APOST\n"
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. PROG.\n"
        "       PROCEDURE DIVISION.\n"
        "       MAIN-PROCESS.\n"
        '           DISPLAY "HI".\n'
    )
    cut = tmp_path / "PROG.cut"
    cut.write_text('TESTSUITE "s"\nTESTCASE "c"\n    PERFORM MAIN-PROCESS\n')

    exit_code = main(["export", str(cbl), "--cut", str(cut)])
    assert exit_code == 0
    output_text = (tmp_path / "PROG.mainframe.cbl").read_text()
    assert "CBL APOST" in output_text


def _export_example(tmp_path, name, program):
    exit_code = main(
        [
            "export",
            str(_EXAMPLES / name / f"{program}.cbl"),
            "--cut",
            str(_EXAMPLES / name / f"{program}.cut"),
            "--output",
            str(tmp_path / "out.cbl"),
        ]
    )
    assert exit_code == 0
    return (tmp_path / "out.cbl").read_text().upper()


# Structural guard, one example per boundary category that actually uses
# EXEC syntax: splicing already replaces every mocked boundary's real
# statement (build_site_dispatch/build_exec_trap), this pins that the
# export path doesn't reintroduce any LIVE one -- matching the design
# doc's own claim (docs/2026-08-03-mainframe-export-command-design.md,
# Adjustment 3): "zero live EXEC SQL/CICS/DLI statements remain anywhere."
#
# An earlier version of this guard checked for the bare substring
# "END-EXEC" anywhere in the output. That is stronger than what splicing
# actually promises and was falsified empirically against real example
# output: splicer/stub_writer.py's comment_and_replace comments out the
# ORIGINAL boundary statement's span in place (prefixing each of its
# lines with "      *> ") and inserts the dispatch/trap code immediately
# after it -- it does not delete the original text. So the original
# "EXEC SQL ... END-EXEC" (or CICS/DLI) block survives verbatim behind a
# `*>` marker, exactly like splicer/sqlca.py's own explanatory comments
# (e.g. "*> EXEC SQL INCLUDE SQLCA replaced by...") already do for "EXEC
# SQL". Checking for LIVE (uncommented) occurrences instead is the
# property that actually matters for a real compile, and the one the
# design doc promises.


def _live_exec_lines(output_text: str) -> list[str]:
    """Lines carrying EXEC boundary syntax that are NOT commented out.
    comment_and_replace always comments the original boundary statement
    in place rather than deleting it, so the original EXEC ... END-EXEC
    text survives verbatim behind a `*>` marker -- verified empirically
    against examples/invupdt and examples/custinq. What actually matters
    for a real compile (and what the design doc guarantees) is that no
    LIVE EXEC statement remains; `_export_example`'s `.upper()` is
    harmless here since `*>` has no case."""
    return [
        line
        for line in output_text.splitlines()
        if not line.lstrip().startswith("*>")
        and any(kw in line for kw in ("END-EXEC", "EXEC SQL", "EXEC CICS", "EXEC DLI"))
    ]


def test_export_output_has_no_live_exec_sql_boundary_text(tmp_path):
    output_text = _export_example(tmp_path, "invupdt", "INVUPDT")
    assert _live_exec_lines(output_text) == []


def test_export_output_has_no_live_exec_cics_boundary_text(tmp_path):
    output_text = _export_example(tmp_path, "custinq", "CUSTINQ")
    assert _live_exec_lines(output_text) == []


def test_export_output_has_no_live_exec_dli_boundary_text(tmp_path):
    output_text = _export_example(tmp_path, "claimseg", "CLAIMSEG")
    assert _live_exec_lines(output_text) == []


def test_export_reports_refused_static_checks_and_writes_nothing(tmp_path, capsys):
    cbl = tmp_path / "BAD.cbl"
    cbl.write_text("this is not cobol\n")
    cut = tmp_path / "BAD.cut"
    cut.write_text('TESTSUITE "s"\n')

    exit_code = main(["export", str(cbl), "--cut", str(cut)])
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "mockymock export: refused (" in out
    assert not (tmp_path / "BAD.mainframe.cbl").exists()


def test_export_wraps_a_long_cut_mock_body_line_instead_of_refusing(tmp_path, capsys):
    """The routinely-reachable overflow: a `.cut` file's own MOCK body text.
    `injector.py`'s build_site_dispatch re-indents a MOCK body's lines by 19
    columns when it splices them in, so an ordinary MOVE with a modest
    literal and a modest field name routinely lands past column 72 once
    restore_fixed_format_columns's own 7-space prefix is added on top.

    `export` used to refuse the whole file on it (COLUMN_OVERFLOW) even
    though a COBOL statement may span as many fixed-format lines as it
    needs. It now wraps: the statement is broken at whitespace, every line
    fits, and nothing is lost."""
    cbl = tmp_path / "PROG.cbl"
    cbl.write_text(
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. PROG.\n"
        "\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01  WS-A-RATHER-LONG-FIELD-NAME-HERE   PIC X(40).\n"
        "\n"
        "       PROCEDURE DIVISION.\n"
        "       MAIN-PROCESS.\n"
        '           CALL "SUBPROG"\n'
        '           DISPLAY "DONE".\n'
    )
    cut = tmp_path / "PROG.cut"
    cut.write_text(
        'TESTSUITE "s"\n'
        "\n"
        'TESTCASE "long mock body line"\n'
        '    MOCK CALL "SUBPROG"\n'
        '        MOVE "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA" TO '
        "WS-A-RATHER-LONG-FIELD-NAME-HERE\n"
        "    END-MOCK\n"
        "    PERFORM MAIN-PROCESS\n"
    )

    exit_code = main(["export", str(cbl), "--cut", str(cut)])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "COLUMN_OVERFLOW" not in out
    written = (tmp_path / "PROG.mainframe.cbl").read_text().splitlines()
    assert all(len(line) <= 72 for line in written)
    # Broken across two lines, with both halves present and in order.
    joined = "\n".join(written)
    assert 'MOVE "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA" TO' in joined
    assert "WS-A-RATHER-LONG-FIELD-NAME-HERE" in joined


def test_export_wraps_its_own_generated_working_storage_reset(tmp_path, capsys):
    """The other routinely-reachable overflow, and the one no `.cut` edit
    could ever have fixed: mockymock's OWN generated
    `UT-RESET-WORKING-STORAGE` re-serializes a long VALUE clause onto a
    single `MOVE "<literal>" TO <item>` line. The original program declared
    it legally across two fixed-format lines; the reset block did not."""
    cbl = tmp_path / "PROG.cbl"
    cbl.write_text(
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. PROG.\n"
        "\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01  DEBUT-WORKING-STORAGE  PIC X(52)\n"
        '           VALUE "*** DEBUT DE LA WORKING STORAGE PROGRAMME XYZ ***".\n'
        "\n"
        "       PROCEDURE DIVISION.\n"
        "       MAIN-PROCESS.\n"
        '           CALL "SUBPROG"\n'
        '           DISPLAY "DONE".\n'
    )
    cut = tmp_path / "PROG.cut"
    cut.write_text(
        'TESTSUITE "s"\n'
        "\n"
        'TESTCASE "c"\n'
        '    MOCK CALL "SUBPROG"\n'
        "        MOVE 0 TO RETURN-CODE\n"
        "    END-MOCK\n"
        "    PERFORM MAIN-PROCESS\n"
    )

    exit_code = main(["export", str(cbl), "--cut", str(cut)])
    assert exit_code == 0
    assert "COLUMN_OVERFLOW" not in capsys.readouterr().out
    written = (tmp_path / "PROG.mainframe.cbl").read_text().splitlines()
    assert all(len(line) <= 72 for line in written)
    joined = "\n".join(written)
    assert (
        'MOVE "*** DEBUT DE LA WORKING STORAGE PROGRAMME XYZ ***" TO'
        "\n           DEBUT-WORKING-STORAGE." in joined
    )


def test_export_never_imports_docker_toolchain(tmp_path):
    import sys

    saved = sys.modules.pop("mockymock.runtime.docker_toolchain", None)
    try:
        cbl = _EXAMPLES / "ordrproc" / "ORDRPROC.cbl"
        cut = _EXAMPLES / "ordrproc" / "ORDRPROC.cut"
        # The exit code must be checked: an early refusal also wouldn't
        # import docker_toolchain, but for the wrong reason -- without this
        # assertion the test would pass vacuously if `export` regressed to
        # refusing on this fixture instead of actually succeeding.
        exit_code = main(
            [
                "export",
                str(cbl),
                "--cut",
                str(cut),
                "--output",
                str(tmp_path / "out.cbl"),
            ]
        )
        assert exit_code == 0
        assert "mockymock.runtime.docker_toolchain" not in sys.modules
    finally:
        if saved is not None:
            sys.modules["mockymock.runtime.docker_toolchain"] = saved
