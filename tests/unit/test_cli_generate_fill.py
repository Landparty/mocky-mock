"""docs/2026-09-15-actionable-refusals-and-fill-design.md: suggested_fix
on lint/run's UNMOCKED_* output, and `generate --fill`."""

from mockymock.cli.main import main

_PROGRAM = (
    "       IDENTIFICATION DIVISION.\n"
    "       PROGRAM-ID. P.\n"
    "       DATA DIVISION.\n"
    "       WORKING-STORAGE SECTION.\n"
    "       01 WS-EOF PIC X VALUE 'N'.\n"
    "       PROCEDURE DIVISION.\n"
    "       0000-MAIN-PROCESS.\n"
    "           OPEN INPUT INV-FILE.\n"
    "           READ INV-FILE\n"
    "               AT END MOVE 'Y' TO WS-EOF\n"
    "           END-READ.\n"
    "           CLOSE INV-FILE.\n"
    "           STOP RUN.\n"
)

_PARTIALLY_MOCKED_CUT = (
    'TESTSUITE "s"\n'
    "\n"
    'TESTCASE "opens and closes"\n'
    "    MOCK OPEN INV-FILE\n"
    "    END-MOCK\n"
    "    MOCK CLOSE INV-FILE\n"
    "    END-MOCK\n"
    "    PERFORM 0000-MAIN-PROCESS\n"
)

_FULLY_MOCKED_CUT = (
    'TESTSUITE "s"\n'
    "\n"
    'TESTCASE "opens and closes"\n'
    "    MOCK OPEN INV-FILE\n"
    "    END-MOCK\n"
    "    MOCK CLOSE INV-FILE\n"
    "    END-MOCK\n"
    "    MOCK READ INV-FILE\n"
    "    END-MOCK\n"
    "    PERFORM 0000-MAIN-PROCESS\n"
)


def _write_pair(tmp_path, cut_text):
    cbl = tmp_path / "P.cbl"
    cbl.write_text(_PROGRAM)
    cut = tmp_path / "P.cut"
    cut.write_text(cut_text)
    return cbl, cut


def test_lint_appends_suggested_fix_for_unmocked_read(tmp_path, capsys):
    cbl, cut = _write_pair(tmp_path, _PARTIALLY_MOCKED_CUT)
    exit_code = main(["lint", str(cbl), "--cut", str(cut)])
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "UNMOCKED_FILE_OP" in out
    assert "Add to this TESTCASE:" in out
    assert "MOCK READ INV-FILE" in out
    assert "END-MOCK" in out


def test_lint_no_suggested_fix_block_when_fully_mocked(tmp_path, capsys):
    cbl, cut = _write_pair(tmp_path, _FULLY_MOCKED_CUT)
    exit_code = main(["lint", str(cbl), "--cut", str(cut)])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Add to this TESTCASE" not in out


def test_generate_fill_inserts_only_missing_mock_block(tmp_path, capsys):
    cbl, cut = _write_pair(tmp_path, _PARTIALLY_MOCKED_CUT)
    exit_code = main(["generate", str(cbl), "--fill", str(cut)])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "added 1 mock block(s) across 1 test case(s)" in out

    result = cut.read_text()
    assert "MOCK READ INV-FILE" in result
    # Everything that was already there is untouched.
    assert "MOCK OPEN INV-FILE" in result
    assert "MOCK CLOSE INV-FILE" in result
    assert result.count("END-MOCK") == 3


def test_generate_fill_is_idempotent(tmp_path, capsys):
    cbl, cut = _write_pair(tmp_path, _PARTIALLY_MOCKED_CUT)
    main(["generate", str(cbl), "--fill", str(cut)])
    capsys.readouterr()
    after_first = cut.read_text()

    exit_code = main(["generate", str(cbl), "--fill", str(cut)])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "added 0 mock block(s)" in out
    assert cut.read_text() == after_first


def test_generate_fill_leaves_fully_mocked_case_untouched(tmp_path, capsys):
    cbl, cut = _write_pair(tmp_path, _FULLY_MOCKED_CUT)
    original = cut.read_text()
    exit_code = main(["generate", str(cbl), "--fill", str(cut)])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "added 0 mock block(s) across 0 test case(s)" in out
    assert cut.read_text() == original


def test_generate_fill_rejects_with_data(tmp_path, capsys):
    cbl, cut = _write_pair(tmp_path, _PARTIALLY_MOCKED_CUT)
    exit_code = main(["generate", str(cbl), "--fill", str(cut), "--with-data"])
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "--fill is not valid together with --with-data" in out


def test_generate_fill_rejects_output_flag(tmp_path, capsys):
    cbl, cut = _write_pair(tmp_path, _PARTIALLY_MOCKED_CUT)
    exit_code = main(
        ["generate", str(cbl), "--fill", str(cut), "-o", str(tmp_path / "x.cut")]
    )
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "--fill is not valid together with -o/--output" in out


def test_generate_fill_missing_cut_file_reports_cleanly(tmp_path, capsys):
    cbl = tmp_path / "P.cbl"
    cbl.write_text(_PROGRAM)
    missing_cut = tmp_path / "MISSING.cut"
    exit_code = main(["generate", str(cbl), "--fill", str(missing_cut)])
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "no such file" in out


def test_generate_fill_preserves_line_endings_and_trailing_newline(tmp_path, capsys):
    cbl, cut = _write_pair(tmp_path, _PARTIALLY_MOCKED_CUT)
    main(["generate", str(cbl), "--fill", str(cut)])
    capsys.readouterr()
    result = cut.read_text()
    assert result.endswith("\n")
    assert "\r\n" not in result


_TWO_READS_PROGRAM = (
    "       IDENTIFICATION DIVISION.\n"
    "       PROGRAM-ID. P.\n"
    "       DATA DIVISION.\n"
    "       WORKING-STORAGE SECTION.\n"
    "       01 WS-EOF PIC X VALUE 'N'.\n"
    "       PROCEDURE DIVISION.\n"
    "       0000-MAIN-PROCESS.\n"
    "           OPEN INPUT INV-FILE.\n"
    "           READ INV-FILE\n"
    "               AT END MOVE 'Y' TO WS-EOF\n"
    "           END-READ.\n"
    "           PERFORM 1000-NEXT.\n"
    "           CLOSE INV-FILE.\n"
    "           STOP RUN.\n"
    "       1000-NEXT.\n"
    "           READ INV-FILE\n"
    "               AT END MOVE 'Y' TO WS-EOF\n"
    "           END-READ.\n"
)


def test_generate_fill_inserts_one_block_for_two_sites_sharing_a_key(tmp_path, capsys):
    """A priming READ plus a READ in a PERFORMed paragraph are two
    UNMOCKED reasons with one MOCK header; two blocks would be a
    duplicate the .cut parser rejects."""
    cbl = tmp_path / "P.cbl"
    cbl.write_text(_TWO_READS_PROGRAM)
    cut = tmp_path / "P.cut"
    cut.write_text(_PARTIALLY_MOCKED_CUT)
    exit_code = main(["generate", str(cbl), "--fill", str(cut)])
    out = capsys.readouterr().out
    assert exit_code == 0, out
    assert "added 1 mock block(s) across 1 test case(s)" in out
    assert cut.read_text().count("MOCK READ INV-FILE") == 1
    assert main(["lint", str(cbl), "--cut", str(cut)]) == 0


def test_generate_fill_skips_a_perform_inside_a_mock_body(tmp_path, capsys):
    """A mock body is verbatim COBOL and may hold an inline PERFORM (a
    PERFORM of a paragraph is refused, issue #287); the inserted block must
    land before the case's own PERFORM, never inside another mock's body."""
    cut_text = (
        'TESTSUITE "s"\n'
        "\n"
        'TESTCASE "opens and closes"\n'
        "    MOCK OPEN INV-FILE\n"
        "        PERFORM 2 TIMES\n"
        "            CONTINUE\n"
        "        END-PERFORM\n"
        "    END-MOCK\n"
        "    MOCK CLOSE INV-FILE\n"
        "    END-MOCK\n"
        "    PERFORM 0000-MAIN-PROCESS\n"
    )
    cbl, cut = _write_pair(tmp_path, cut_text)
    exit_code = main(["generate", str(cbl), "--fill", str(cut)])
    out = capsys.readouterr().out
    assert exit_code == 0, out
    lines = cut.read_text().splitlines()
    read_at = lines.index("    MOCK READ INV-FILE")
    assert lines[read_at - 1] == "    END-MOCK"
    read_end = lines.index("    END-MOCK", read_at)
    assert lines[read_end + 1] == "    PERFORM 0000-MAIN-PROCESS"
    assert main(["lint", str(cbl), "--cut", str(cut)]) == 0


def test_generate_fill_keeps_same_named_test_cases_apart(tmp_path, capsys):
    """Duplicate TESTCASE names are legal; each case must get exactly
    the blocks it is missing, not the last namesake's."""
    cut_text = (
        'TESTSUITE "s"\n'
        "\n"
        'TESTCASE "same"\n'
        "    MOCK OPEN INV-FILE\n"
        "    END-MOCK\n"
        "    MOCK CLOSE INV-FILE\n"
        "    END-MOCK\n"
        "    MOCK READ INV-FILE\n"
        "    END-MOCK\n"
        "    PERFORM 0000-MAIN-PROCESS\n"
        "\n"
        'TESTCASE "same"\n'
        "    MOCK OPEN INV-FILE\n"
        "    END-MOCK\n"
        "    MOCK CLOSE INV-FILE\n"
        "    END-MOCK\n"
        "    PERFORM 0000-MAIN-PROCESS\n"
    )
    cbl, cut = _write_pair(tmp_path, cut_text)
    exit_code = main(["generate", str(cbl), "--fill", str(cut)])
    out = capsys.readouterr().out
    assert exit_code == 0, out
    assert "added 1 mock block(s) across 1 test case(s)" in out
    assert cut.read_text().count("MOCK READ INV-FILE") == 2
    assert main(["lint", str(cbl), "--cut", str(cut)]) == 0


def test_generate_fill_reports_problems_it_cannot_fix_and_fails(tmp_path, capsys):
    """`--fill` exiting 0 must mean the next `lint` exits 0: a problem
    no MOCK block can fix is printed and fails the command."""
    cut_text = _FULLY_MOCKED_CUT.replace(
        "    PERFORM 0000-MAIN-PROCESS\n",
        "    MOCK PARAGRAPH NO-SUCH-PARA\n"
        "    END-MOCK\n"
        "    PERFORM 0000-MAIN-PROCESS\n",
    )
    cbl, cut = _write_pair(tmp_path, cut_text)
    original = cut.read_text()
    exit_code = main(["generate", str(cbl), "--fill", str(cut)])
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "UNRESOLVED_FLOW_MOCK_TARGET" in out
    assert cut.read_text() == original


def test_generate_fill_reports_the_line_each_block_landed_on(tmp_path, capsys):
    cbl, cut = _write_pair(tmp_path, _PARTIALLY_MOCKED_CUT)
    main(["generate", str(cbl), "--fill", str(cut)])
    out = capsys.readouterr().out
    lines = cut.read_text().splitlines()
    landed = lines.index("    MOCK READ INV-FILE") + 1
    assert f"{cut}:{landed}: MOCK READ INV-FILE" in out


_HOOK_PROGRAM = (
    "       IDENTIFICATION DIVISION.\n"
    "       PROGRAM-ID. P.\n"
    "       DATA DIVISION.\n"
    "       WORKING-STORAGE SECTION.\n"
    "       01 WS-EOF PIC X VALUE 'N'.\n"
    "       PROCEDURE DIVISION.\n"
    "       OPEN-FILE.\n"
    "           OPEN INPUT INV-FILE.\n"
    "       CLOSE-FILE.\n"
    "           CLOSE INV-FILE.\n"
)


def test_generate_fill_fails_on_an_unmocked_hook_boundary_it_cannot_fill(
    tmp_path, capsys
):
    """Issue #208: a BEFORE-EACH PERFORM's UNMOCKED_* refusal starts with
    the same "refused (UNMOCKED_" prefix as a TESTCASE's own, so --fill
    treated it as filled, inserted nothing, and exited 0 -- while the next
    lint still failed."""
    cut_text = (
        'TESTSUITE "hooks"\n'
        "BEFORE-EACH\n"
        "    PERFORM OPEN-FILE\n"
        "END-BEFORE\n"
        "\n"
        'TESTCASE "close only"\n'
        "    MOCK CLOSE INV-FILE\n"
        "    END-MOCK\n"
        "    PERFORM CLOSE-FILE\n"
    )
    cbl = tmp_path / "P.cbl"
    cbl.write_text(_HOOK_PROGRAM)
    cut = tmp_path / "P.cut"
    cut.write_text(cut_text)
    exit_code = main(["generate", str(cbl), "--fill", str(cut)])
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "BEFORE-EACH" in out and "UNMOCKED_FILE_OP" in out
    assert cut.read_text() == cut_text


def test_generate_refuses_to_overwrite_an_existing_sibling_cut(tmp_path, capsys):
    """Issue #201: the default output is the program's existing sibling
    PROG.cut, which plain `generate` replaced with a bare scaffold."""
    cbl, cut = _write_pair(tmp_path, _FULLY_MOCKED_CUT)
    exit_code = main(["generate", str(cbl), "--per-paragraph"])
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "already exists" in out and "--force" in out
    assert cut.read_text() == _FULLY_MOCKED_CUT


def test_generate_refuses_an_existing_explicit_output_too(tmp_path, capsys):
    cbl, cut = _write_pair(tmp_path, _FULLY_MOCKED_CUT)
    exit_code = main(["generate", str(cbl), "--per-paragraph", "-o", str(cut)])
    assert exit_code == 1
    assert "--force" in capsys.readouterr().out
    assert cut.read_text() == _FULLY_MOCKED_CUT


def test_generate_force_overwrites_an_existing_cut(tmp_path, capsys):
    cbl, cut = _write_pair(tmp_path, _FULLY_MOCKED_CUT)
    exit_code = main(["generate", str(cbl), "--per-paragraph", "--force"])
    assert exit_code == 0, capsys.readouterr().out
    assert cut.read_text() != _FULLY_MOCKED_CUT


# Regression: bug hunt round 12.
import shutil
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]


_CUSTINQ = _REPO / "examples" / "custinq" / "CUSTINQ.cbl"


# --- generate --fill keeps a CRLF .cut CRLF -------------------------------


def test_fill_preserves_crlf_line_endings(tmp_path, monkeypatch, capsys):
    """read_text() translated CRLF to LF, so the CRLF check was dead and a
    CRLF .cut came back LF on POSIX (and, written without newline="", an
    LF join would have become CRLF on Windows regardless of the input)."""
    monkeypatch.chdir(tmp_path)
    shutil.copy(_CUSTINQ, tmp_path / "CUSTINQ.cbl")
    cut = tmp_path / "CUSTINQ.cut"
    cut.write_bytes(
        b'TESTSUITE "S"\r\n\r\nTESTCASE "t"\r\n'
        b"    PERFORM 1000-LOOKUP-CUSTOMER\r\n"
        b'    EXPECT WS-INQUIRY-STATUS TO BE "FOUND"\r\n'
    )

    assert main(["generate", str(tmp_path / "CUSTINQ.cbl"), "--fill", str(cut)]) == 0

    written = cut.read_bytes()
    assert b'MOCK CICS "READ"' in written
    assert b"\r\r\n" not in written
    assert written.count(b"\n") == written.count(b"\r\n")


def test_fill_writes_without_newline_translation(tmp_path, monkeypatch):
    """The in-place write must not let the platform translate "\\n"
    (Windows would turn the CRLF join into CR CR LF)."""
    monkeypatch.chdir(tmp_path)
    shutil.copy(_CUSTINQ, tmp_path / "CUSTINQ.cbl")
    cut = tmp_path / "CUSTINQ.cut"
    cut.write_bytes(
        b'TESTSUITE "S"\r\nTESTCASE "t"\r\n    PERFORM 1000-LOOKUP-CUSTOMER\r\n'
    )
    calls: list[dict] = []
    real_write_text = Path.write_text

    def spy(self, data, *args, **kwargs):
        if self == cut:
            calls.append(kwargs)
        return real_write_text(self, data, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", spy)
    assert main(["generate", str(tmp_path / "CUSTINQ.cbl"), "--fill", str(cut)]) == 0
    assert calls and all(call.get("newline") == "" for call in calls)
