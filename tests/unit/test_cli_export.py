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


def _column_overflow_program(tmp_path, mock_body):
    """A program + `.cut` pair whose MOCK body line lands past column 72
    once spliced. `injector.py`'s build_site_dispatch re-indents a MOCK
    body's lines by 19 columns, so an ordinary statement with modest names
    routinely overflows once restore_fixed_format_columns's own 7-space
    prefix is added on top -- the routinely-reachable COLUMN_OVERFLOW
    path, reached from user-authored text rather than from mockymock's own
    generated DISPLAY boilerplate. `mockymock lint` reports no problems on
    either pair below (neither is a static-check refusal)."""
    cbl = tmp_path / "PROG.cbl"
    cbl.write_text(
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. PROG.\n"
        "\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01  WS-A-RATHER-LONG-FIELD-NAME-HERE   PIC X(40).\n"
        "       01  WS-ANOTHER-RATHER-LONG-FIELD-NAME  PIC X(40).\n"
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
        f"        {mock_body}\n"
        "    END-MOCK\n"
        "    PERFORM MAIN-PROCESS\n"
    )
    return cbl, cut


def test_export_continues_an_overlong_mock_body_literal(tmp_path, capsys):
    """An over-72 line whose length comes from a quoted literal is split
    across fixed-format continuation lines rather than refused: the
    literal's content is unchanged, so there is nothing for the `.cut`
    author to shorten. The same rewrite is what makes a program declaring
    a wide WORKING-STORAGE marker field exportable at all -- reset.py
    re-serializes its VALUE clause into a MOVE nothing outside the
    program could shorten."""
    cbl, cut = _column_overflow_program(
        tmp_path,
        'MOVE "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA" TO '
        "WS-A-RATHER-LONG-FIELD-NAME-HERE",
    )

    exit_code = main(["export", str(cbl), "--cut", str(cut)])
    assert exit_code == 0, capsys.readouterr().out

    written = (tmp_path / "PROG.mainframe.cbl").read_text().splitlines()
    assert all(len(line) <= 72 for line in written)
    continuations = [line for line in written if len(line) > 6 and line[6] == "-"]
    assert continuations, "the long MOVE was expected to be continued"
    assert all(line[7:].lstrip().startswith('"') for line in continuations)


def test_export_breaks_a_literal_less_overflow_at_whitespace(tmp_path, capsys):
    """An overflow with no literal to continue is not a refusal either: a
    COBOL statement may span as many fixed-format lines as it needs, so the
    line is simply broken at a space with the remainder in Area B."""
    cbl, cut = _column_overflow_program(
        tmp_path,
        "MOVE WS-A-RATHER-LONG-FIELD-NAME-HERE TO WS-ANOTHER-RATHER-LONG-FIELD-NAME",
    )

    exit_code = main(["export", str(cbl), "--cut", str(cut)])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "COLUMN_OVERFLOW" not in out
    written = (tmp_path / "PROG.mainframe.cbl").read_text().splitlines()
    assert all(len(line) <= 72 for line in written)
    joined = "\n".join(written)
    assert "MOVE WS-A-RATHER-LONG-FIELD-NAME-HERE TO" in joined
    assert "WS-ANOTHER-RATHER-LONG-FIELD-NAME" in joined


def test_export_still_refuses_what_it_genuinely_cannot_fit(tmp_path, capsys):
    """Fitting is not a licence to ship a too-long line. A single word too
    long for Area B (columns 12-72, so 61 characters) has no literal to
    continue AND no break point, so it still refuses with COLUMN_OVERFLOW
    and writes nothing."""
    cbl, cut = _column_overflow_program(tmp_path, "DISPLAY WS-" + "X" * 62)

    exit_code = main(["export", str(cbl), "--cut", str(cut)])
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "COLUMN_OVERFLOW" in out
    assert not (tmp_path / "PROG.mainframe.cbl").exists()


def test_a_refusal_names_where_the_line_actually_came_from(tmp_path, capsys):
    """The message used to assert "this typically comes from a `.cut` file's
    MOCK body text" whatever the real source was -- so a reader whose
    offending line was mockymock's own generated reset went to the wrong
    file first. It now names the actual source by exact text match."""
    cbl, cut = _column_overflow_program(tmp_path, "DISPLAY WS-" + "X" * 62)

    assert main(["export", str(cbl), "--cut", str(cut)]) == 1
    out = capsys.readouterr().out
    assert "source: MOCK body text, " in out
    assert str(cut) in out


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


# Regression: executed bug hunt of 2026-10-05 (issues #139-#150); the executed
# counterparts live in tests/integration/test_bug_hunt_m1_fixes.py.


RINTO_CBL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. RINTO.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-FILE ASSIGN TO "IN.DAT"
               ORGANIZATION IS LINE SEQUENTIAL
               FILE STATUS IS WS-STAT.
           SELECT OUT-FILE ASSIGN TO "OUT.DAT"
               ORGANIZATION IS LINE SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD  IN-FILE.
       01  IN-REC.
           05  IN-AMT  PIC 9(3).
       FD  OUT-FILE.
       01  OUT-REC    PIC X(5).
       WORKING-STORAGE SECTION.
       01  WS-STAT  PIC XX.
       01  WS-EOF   PIC X VALUE "N".
       01  WS-REC.
           05  WS-AMT  PIC 9(3).
       01  WS-TOTAL PIC 9(4) VALUE 0.
       01  WS-LINE  PIC X(5) VALUE "HELLO".
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM READ-PARA UNTIL WS-EOF = "Y"
           GOBACK.
       READ-PARA.
           READ IN-FILE INTO WS-REC
               AT END MOVE "Y" TO WS-EOF
           END-READ
           IF WS-EOF = "N"
               ADD WS-AMT TO WS-TOTAL
           END-IF.
       WRITE-PARA.
           WRITE OUT-REC FROM WS-LINE.
"""


def _rinto_case(cut_body: str) -> str:
    return 'TESTSUITE "into"\nTESTCASE "one"\n' + cut_body


def _exported(tmp_path: Path, cut: str) -> str:
    from mockymock.cli.main import main

    (tmp_path / "RINTO.cbl").write_text(RINTO_CBL)
    (tmp_path / "RINTO.cut").write_text(cut)
    out = tmp_path / "RINTO.exp.cbl"
    exit_code = main(
        [
            "export",
            str(tmp_path / "RINTO.cbl"),
            "--cut",
            str(tmp_path / "RINTO.cut"),
            "--output",
            str(out),
        ]
    )
    assert exit_code == 0
    return out.read_text()


def test_149_read_into_rows_copy_the_record_after_each_row(tmp_path) -> None:
    exported = _exported(
        tmp_path,
        _rinto_case(
            "MOCK READ IN-FILE ROWS\n    ( IN-AMT = 5 )\n    ( IN-AMT = 7 )\n"
            "END-MOCK\nPERFORM MAIN-PARA\nEXPECT WS-TOTAL TO BE 12\n"
        ),
    )
    assert exported.count("MOVE IN-REC TO WS-REC") >= 1


def test_149_read_into_body_copies_the_record_after_the_body(tmp_path) -> None:
    exported = _exported(
        tmp_path,
        _rinto_case(
            "MOCK READ IN-FILE\n    MOVE 9 TO IN-AMT\nEND-MOCK\n"
            "PERFORM READ-PARA\nEXPECT WS-AMT TO BE 9\n"
        ),
    )
    body, copy = (
        exported.index("MOVE 9 TO IN-AMT"),
        exported.index("MOVE IN-REC TO WS-REC"),
    )
    assert body < copy


def test_149_a_body_that_sets_the_into_item_itself_is_not_overwritten(
    tmp_path,
) -> None:
    exported = _exported(
        tmp_path,
        _rinto_case(
            "MOCK READ IN-FILE\n    MOVE 4 TO WS-AMT\nEND-MOCK\n"
            "PERFORM READ-PARA\nEXPECT WS-TOTAL TO BE 4\n"
        ),
    )
    assert "MOVE IN-REC TO WS-REC" not in exported


def test_149_write_from_moves_the_source_into_the_record(tmp_path) -> None:
    exported = _exported(
        tmp_path,
        _rinto_case(
            "MOCK WRITE OUT-REC\nEND-MOCK\n"
            'PERFORM WRITE-PARA\nEXPECT OUT-REC TO BE "HELLO"\n'
        ),
    )
    assert "MOVE WS-LINE TO OUT-REC" in exported
