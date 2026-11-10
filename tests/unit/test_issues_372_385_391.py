"""Open-issue sweep 2026-11-01: #372, #385, #388, #389 (in test_cli_doctor),
#390 and #391."""

from __future__ import annotations

import json

from cobolparser import parse_cobol

from mockymock.analysis.flow_targets import (
    ORIGINAL_ENTRY_PARAGRAPH,
    name_unnamed_main_line,
    normalize_flow_targets,
)
from mockymock.cli.main import main
from mockymock.project import ai_mode
from mockymock.project.config import load_config
from mockymock.report.journal import read_journal

UNNAMED_CBL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CAPT.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT INF ASSIGN TO INFILE
               ORGANIZATION IS SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD  INF.
       01  IN-REC.
           05 IN-AMT PIC 9(5).
       WORKING-STORAGE SECTION.
       01  WS-EOF  PIC X VALUE 'N'.
       01  WS-AMT  PIC 9(5).
       01  WS-PARM PIC X(10).
       PROCEDURE DIVISION.
           OPEN INPUT INF
           PERFORM UNTIL WS-EOF = 'Y'
               READ INF
                   AT END MOVE 'Y' TO WS-EOF
                   NOT AT END
                       MOVE IN-AMT TO WS-AMT
                       CALL 'SUBX' USING WS-PARM
               END-READ
           END-PERFORM
           CLOSE INF
           GOBACK.
"""

SECBAT_CBL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SECBAT.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-FILE ASSIGN TO INFILE
               FILE STATUS IS WS-FS.
       DATA DIVISION.
       FILE SECTION.
       FD  IN-FILE.
       01  IN-REC.
           05 IN-ID      PIC 9(4).
           05 IN-AMT     PIC 9(5)V99.
       WORKING-STORAGE SECTION.
       01  WS-FS         PIC XX VALUE '00'.
       01  WS-EOF        PIC X VALUE 'N'.
           88 END-OF-FILE VALUE 'Y'.
       01  WS-TOTAL      PIC 9(7)V99 VALUE 0.
       01  WS-COUNT      PIC 9(4) VALUE 0.
       01  WS-RC         PIC S9(4) COMP VALUE 0.
       PROCEDURE DIVISION.
       0000-MAIN SECTION.
       0000-START.
           PERFORM 1000-INIT
           PERFORM 2000-PROCESS UNTIL END-OF-FILE
           PERFORM 3000-TERM
           CONTINUE.
       1000-INIT.
           OPEN INPUT IN-FILE
           IF WS-FS NOT = '00'
               DISPLAY 'OPEN FAILED ' WS-FS
               MOVE 16 TO RETURN-CODE
               STOP RUN
           END-IF
           PERFORM 8000-READ.
       2000-PROCESS.
           ADD 1 TO WS-COUNT
           ADD IN-AMT TO WS-TOTAL
           IF IN-AMT > 50000
               CALL 'AUDITPGM' USING IN-REC WS-RC
               IF WS-RC NOT = 0
                   PERFORM 9000-ABEND
               END-IF
           END-IF
           PERFORM 8000-READ.
       3000-TERM.
           CLOSE IN-FILE
           DISPLAY 'COUNT ' WS-COUNT ' TOTAL ' WS-TOTAL.
       8000-READ.
           READ IN-FILE
               AT END SET END-OF-FILE TO TRUE
           END-READ.
       9000-ABEND.
           DISPLAY 'AUDIT FAILED ' WS-RC
           MOVE 12 TO RETURN-CODE
           CONTINUE.
"""


def _generate(tmp_path, name: str, cbl: str, *extra: str) -> tuple[int, str]:
    source = tmp_path / f"{name}.cbl"
    source.write_text(cbl)
    out = tmp_path / f"{name}.cut"
    code = main(["generate", str(source), "-o", str(out), *extra])
    return code, out.read_text() if out.exists() else ""


def _case(cut: str, title: str) -> str:
    start = cut.index(f'TESTCASE "{title}"')
    end = cut.find("TESTCASE ", start + 1)
    return cut[start : end if end != -1 else None]


# --- #385: an unnamed main line is performable as UT-ORIGINAL-ENTRY -------


def test_385_the_unnamed_main_line_is_named_like_the_splicer_names_it():
    program = parse_cobol(UNNAMED_CBL, filename="CAPT.cbl").ast
    assert name_unnamed_main_line(program) is True
    procedure = program.get_division("PROCEDURE")
    assert procedure.children[0].paragraph_name == ORIGINAL_ENTRY_PARAGRAPH
    # Once only: a second pass finds the name already there.
    assert name_unnamed_main_line(program) is False


def test_385_a_named_program_is_left_alone():
    program = parse_cobol(SECBAT_CBL, filename="SECBAT.cbl").ast
    normalize_flow_targets(program)
    names = {p.paragraph_name for p in program.find_all_by_type("CobolParagraph")}
    assert ORIGINAL_ENTRY_PARAGRAPH not in names


def test_385_an_entry_only_leading_paragraph_is_not_the_main_line():
    source = UNNAMED_CBL.replace(
        "       PROCEDURE DIVISION.\n",
        "       PROCEDURE DIVISION.\n       ENTRY 'ALT'.\n       MAIN-PARA.\n",
    )
    program = parse_cobol(source, filename="CAPT.cbl").ast
    assert name_unnamed_main_line(program) is False


def test_385_generate_scaffolds_a_case_for_the_unnamed_main_line(tmp_path):
    code, cut = _generate(tmp_path, "CAPT", UNNAMED_CBL, "--seed", "1")
    assert code == 0
    assert f"PERFORM {ORIGINAL_ENTRY_PARAGRAPH}" in cut
    assert "MOCK OPEN INF" in cut and 'MOCK CALL "SUBX"' in cut


def test_385_a_hand_written_case_performing_it_lints_clean(tmp_path):
    source = tmp_path / "CAPT.cbl"
    source.write_text(UNNAMED_CBL)
    cut = tmp_path / "CAPT.cut"
    cut.write_text(
        'TESTSUITE "CAPT"\n\nTESTCASE "eof at once"\n'
        "    MOCK OPEN INF\n    END-MOCK\n"
        '    MOCK READ INF\n        MOVE "10" TO UT-MOCK-STATUS\n    END-MOCK\n'
        "    MOCK CLOSE INF\n    END-MOCK\n"
        '    MOCK CALL "SUBX"\n    END-MOCK\n'
        f"    PERFORM {ORIGINAL_ENTRY_PARAGRAPH}\n"
        "    VERIFY CLOSE INF WAS CALLED 1 TIMES\n"
    )
    assert main(["lint", str(source), "--cut", str(cut)]) == 0


# --- #372: the error-status case pins the OPEN once, not twice ------------


def test_372_error_status_case_counts_the_failing_open_once(tmp_path):
    code, cut = _generate(
        tmp_path, "SECBAT", SECBAT_CBL, "--scenarios", "all", "--seed", "1"
    )
    assert code == 0
    case = _case(cut, "error status: OPEN IN-FILE not found")
    assert "VERIFY OPEN IN-FILE WAS CALLED 1 TIMES" in case
    # What the STOP RUN skips has no exact count.
    assert "VERIFY READ IN-FILE WAS CALLED" not in case.replace("*> VERIFY", "")
    assert "VERIFY CLOSE IN-FILE WAS CALLED" not in case.replace("*> VERIFY", "")


# --- #388: a generated case name shows a quoted value's content -----------


def test_388_display_value_undoes_doubled_quotes():
    from mockymock.dsl.parser import _display_value

    assert _display_value("'it''s'") == "it's"
    assert _display_value('"say ""hi"""') == 'say "hi"'
    assert _display_value("ABC") == "ABC"


# --- #390: journal --from keeps `time`; --status is the batch default -----


def test_390_journal_batch_keeps_each_entrys_time(tmp_path):
    batch = tmp_path / "old.jsonl"
    batch.write_text(
        json.dumps({"time": "2026-01-02T03:04:05Z", "step": "plan", "summary": "s"})
        + "\n",
        encoding="utf-8",
    )
    file = tmp_path / "j.jsonl"
    assert main(["journal", "--file", str(file), "--from", str(batch)]) == 0
    assert read_journal(file)[0][0]["time"] == "2026-01-02T03:04:05Z"


def test_390_journal_batch_rejects_a_malformed_time(tmp_path, capsys):
    batch = tmp_path / "bad.jsonl"
    batch.write_text('{"time": "yesterday", "step": "a", "summary": "b"}\n')
    file = tmp_path / "j.jsonl"
    assert main(["journal", "--file", str(file), "--from", str(batch)]) == 1
    assert not file.exists()
    assert "YYYY-MM-DDTHH:MM:SSZ" in capsys.readouterr().out


def test_390_journal_status_flag_is_the_default_for_batch_entries(tmp_path):
    batch = tmp_path / "steps.jsonl"
    batch.write_text(
        '{"step": "a", "summary": "x"}\n'
        '{"step": "b", "summary": "y", "status": "fail"}\n'
    )
    file = tmp_path / "j.jsonl"
    args = ["journal", "--file", str(file), "--from", str(batch), "--status", "warn"]
    assert main(args) == 0
    entries, _ = read_journal(file)
    assert [e["status"] for e in entries] == ["warn", "fail"]


# --- #391: `skills mode --set` keeps a quoted key and its comment ---------


def test_391_rewrite_replaces_a_quoted_key_and_keeps_its_comment(tmp_path):
    config_path = tmp_path / "mockymock.toml"
    config_path.write_text('"ai_mode" = "hands-on"  # chosen by the team\nseed = 7\n')
    ai_mode.write_mode("hands-off", load_config(tmp_path), start_dir=tmp_path)
    text = config_path.read_text(encoding="utf-8")
    assert text.count("ai_mode") == 1
    assert text.splitlines()[0] == 'ai_mode = "hands-off"  # chosen by the team'
    assert load_config(tmp_path).seed == 7


def test_391_a_hash_inside_the_value_is_not_a_comment():
    assert ai_mode._trailing_comment(' "a#b"  # real\n') == "# real"
    assert ai_mode._trailing_comment(' "a#b"\n') == ""
