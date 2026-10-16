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


def test_default_path_sits_next_to_the_cut(tmp_path):
    assert (
        default_journal_path(tmp_path / "PROG.cut") == tmp_path / "PROG.journal.jsonl"
    )


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
    entries, _ = read_journal(tmp_path / "PROG.journal.jsonl")
    assert entries[0]["summary"] == "did it"
    assert "appended to" in capsys.readouterr().out


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
