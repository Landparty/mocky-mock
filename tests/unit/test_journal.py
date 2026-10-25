"""mockymock.report.journal and `mockymock journal`."""

import json
from datetime import UTC, datetime

import pytest

from mockymock.cli.main import main
from mockymock.report.journal import (
    JournalError,
    append_entry,
    default_journal_path,
    read_journal,
)


def test_default_path_sits_in_the_artifact_folder_next_to_the_cut(tmp_path):
    assert (
        default_journal_path(tmp_path / "PROG.cut")
        == tmp_path / ".mockymock" / "PROG.journal.jsonl"
    )


def test_a_journal_at_the_old_place_keeps_being_used(tmp_path):
    legacy = tmp_path / "PROG.journal.jsonl"
    legacy.write_text("", encoding="utf-8")
    assert default_journal_path(tmp_path / "PROG.cut") == legacy


def test_append_writes_one_json_line_per_entry(tmp_path):
    path = tmp_path / "j.jsonl"
    now = datetime(2026, 10, 4, 13, 0, tzinfo=UTC)
    append_entry(path, step="plan", summary="s1", now=now, decision="why")
    append_entry(path, step="run", summary="s2", status="warn", command="mockymock run")
    lines = path.read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[0]) == {
        "time": "2026-10-04T13:00:00Z",
        "step": "plan",
        "status": "ok",
        "summary": "s1",
        "decision": "why",
    }
    assert json.loads(lines[1])["command"] == "mockymock run"


def test_unknown_status_and_empty_text_are_refused(tmp_path):
    with pytest.raises(JournalError):
        append_entry(tmp_path / "j", step="plan", summary="x", status="great")
    with pytest.raises(JournalError):
        append_entry(tmp_path / "j", step=" ", summary="x")
    assert not (tmp_path / "j").exists()


def test_read_reports_bad_lines_instead_of_dropping_them(tmp_path):
    path = tmp_path / "j.jsonl"
    path.write_text('{"step": "a"}\n\n[1]\nnope\n', encoding="utf-8")
    entries, problems = read_journal(path)
    assert entries == [{"step": "a"}]
    assert len(problems) == 2


def test_read_of_a_missing_journal_is_empty(tmp_path):
    assert read_journal(tmp_path / "none.jsonl") == ([], [])


def test_cli_appends_next_to_the_cut(tmp_path, capsys):
    cut = tmp_path / "PROG.cut"
    exit_code = main(
        ["journal", "--cut", str(cut), "--step", "plan", "--summary", "did it"]
    )
    assert exit_code == 0
    entries, _ = read_journal(tmp_path / ".mockymock" / "PROG.journal.jsonl")
    assert entries[0]["summary"] == "did it"
    assert "appended to" in capsys.readouterr().out


def test_cli_appends_a_batch_in_one_process(tmp_path, capsys):
    """Issue #353: one invocation per program instead of one per step."""
    batch = tmp_path / "steps.jsonl"
    batch.write_text(
        '{"step": "plan", "summary": "s1"}\n'
        '{"step": "run", "summary": "s2", "status": "warn", "command": "x"}\n',
        encoding="utf-8",
    )
    file = tmp_path / "j.jsonl"
    assert main(["journal", "--file", str(file), "--from", str(batch)]) == 0
    entries, _ = read_journal(file)
    assert [(e["step"], e["status"]) for e in entries] == [
        ("plan", "ok"),
        ("run", "warn"),
    ]
    assert "appended 2 entries" in capsys.readouterr().out


def test_cli_batch_accepts_a_json_array_from_stdin(tmp_path, monkeypatch):
    import io

    monkeypatch.setattr("sys.stdin", io.StringIO('[{"step": "a", "summary": "b"}]'))
    file = tmp_path / "j.jsonl"
    assert main(["journal", "--file", str(file), "--from", "-"]) == 0
    assert read_journal(file)[0][0]["step"] == "a"


def test_a_bad_entry_appends_nothing(tmp_path, capsys):
    batch = tmp_path / "steps.jsonl"
    batch.write_text(
        '{"step": "plan", "summary": "s1"}\n{"step": "run", "status": "great"}\n',
        encoding="utf-8",
    )
    file = tmp_path / "j.jsonl"
    assert main(["journal", "--file", str(file), "--from", str(batch)]) == 1
    assert not file.exists()
    assert "entry 2" in capsys.readouterr().out


def test_batch_and_single_entry_flags_do_not_mix(tmp_path, capsys):
    file = tmp_path / "j.jsonl"
    code = main(["journal", "--file", str(file), "--from", "-", "--step", "x"])
    assert code == 1
    assert "drop --step" in capsys.readouterr().out


def test_single_entry_needs_step_and_summary(tmp_path, capsys):
    assert main(["journal", "--file", str(tmp_path / "j"), "--step", "x"]) == 1
    assert "--step and --summary" in capsys.readouterr().out


def test_cli_needs_a_cut_or_a_file(capsys):
    assert main(["journal", "--step", "plan", "--summary", "x"]) == 1
    assert "--cut" in capsys.readouterr().out


def test_cli_rejects_an_unknown_status(tmp_path, capsys):
    exit_code = main(
        [
            "journal",
            "--file",
            str(tmp_path / "j.jsonl"),
            "--step",
            "plan",
            "--summary",
            "x",
            "--status",
            "great",
        ]
    )
    assert exit_code == 1
    assert "unknown status" in capsys.readouterr().out


def test_entry_with_unicode_line_separators_reads_back_as_one_entry(tmp_path):
    """#283: json.dumps(ensure_ascii=False) leaves U+2028/U+2029/NEL raw,
    and read_journal's splitlines() broke the entry apart on them."""
    path = tmp_path / "j.jsonl"
    summary = "Parked 2000-CALC because of NEL\x85 here done"
    append_entry(path, step="plan", summary=summary)
    append_entry(path, step="next", summary="plain")
    entries, problems = read_journal(path)
    assert problems == []
    assert [entry["summary"] for entry in entries] == [summary, "plain"]


def test_cli_puts_an_early_journal_where_generate_will_put_the_suite(
    tmp_path, monkeypatch, capsys
):
    """The 2026-10-25 field run: a plan step journaled before `generate`
    with `--cut PROG.cut` beside the program landed in the program's
    folder, while `generate` then wrote tests/PROG.cut and `report` read
    the journal from tests/.mockymock/."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "PROG.cbl").write_text("       PROGRAM-ID. PROG.\n")
    (tmp_path / "src").mkdir()  # the program lies outside it: no mirror
    src = tmp_path / "src" / "PAY.cbl"
    src.write_text("       PROGRAM-ID. PAY.\n")
    for typed in ("src/PAY.cut", "src/PAY.cbl"):
        assert (
            main(["journal", "--cut", typed, "--step", "plan", "--summary", "s"]) == 0
        )
    out = capsys.readouterr().out
    assert "using the suite" in out
    entries, _ = read_journal(tmp_path / "tests" / ".mockymock" / "PAY.journal.jsonl")
    assert len(entries) == 2
    assert not (tmp_path / "src" / ".mockymock").exists()


def test_cli_resolves_a_program_to_its_existing_suite(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "PROG.cbl").write_text("       PROGRAM-ID. PROG.\n")
    (tmp_path / "PROG.cut").write_text('TESTSUITE "s"\n')
    assert (
        main(["journal", "--cut", "PROG.cbl", "--step", "plan", "--summary", "s"]) == 0
    )
    entries, _ = read_journal(tmp_path / ".mockymock" / "PROG.journal.jsonl")
    assert len(entries) == 1


def test_cli_refuses_a_path_that_is_neither_a_cut_nor_a_program(tmp_path, capsys):
    missing = tmp_path / "NOPE.cbl"
    assert (
        main(["journal", "--cut", str(missing), "--step", "p", "--summary", "s"]) == 1
    )
    assert "does not exist" in capsys.readouterr().out
