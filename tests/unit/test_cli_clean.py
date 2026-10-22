"""`mockymock clean` and the `.mockymock/` artifact folder (issue #353)."""

from mockymock.cli.main import main
from mockymock.web.reports import find_reports


def _suite(tmp_path):
    (tmp_path / "PROG.cbl").write_text("x\n", encoding="utf-8")
    (tmp_path / "PROG.cut").write_text('TESTSUITE "s"\n', encoding="utf-8")
    folder = tmp_path / ".mockymock"
    folder.mkdir()
    for name in (
        "PROG.report.html",
        "PROG.run.json",
        "PROG.mutation.json",
        "PROG.inputs.json",
        "PROG.journal.jsonl",
    ):
        (folder / name).write_text("{}", encoding="utf-8")
    # Left by the layout before #353.
    (tmp_path / "PROG.report.html").write_text("", encoding="utf-8")
    return folder


def test_clean_keeps_the_journal_unless_all(tmp_path, capsys):
    folder = _suite(tmp_path)
    assert main(["clean", str(tmp_path)]) == 0
    assert sorted(p.name for p in folder.iterdir()) == ["PROG.journal.jsonl"]
    assert not (tmp_path / "PROG.report.html").exists()
    assert (tmp_path / "PROG.cbl").exists()
    assert (tmp_path / "PROG.cut").exists()
    assert main(["clean", str(tmp_path), "--all"]) == 0
    assert not folder.exists()
    assert "removed" in capsys.readouterr().out


def test_dry_run_removes_nothing(tmp_path, capsys):
    folder = _suite(tmp_path)
    assert main(["clean", str(tmp_path / "PROG.cut"), "--dry-run"]) == 0
    assert len(list(folder.iterdir())) == 5
    assert "would remove" in capsys.readouterr().out


def test_clean_a_program_covers_all_its_suites(tmp_path):
    folder = _suite(tmp_path)
    (tmp_path / "PROG.batch.cut").write_text('TESTSUITE "b"\n', encoding="utf-8")
    (folder / "PROG.batch.run.json").write_text("{}", encoding="utf-8")
    (folder / "OTHER.run.json").write_text("{}", encoding="utf-8")
    assert main(["clean", str(tmp_path / "PROG.cbl")]) == 0
    assert sorted(p.name for p in folder.iterdir()) == [
        "OTHER.run.json",
        "PROG.journal.jsonl",
    ]


def test_clean_of_a_missing_target_fails(tmp_path, capsys):
    assert main(["clean", str(tmp_path / "nope")]) == 1


def test_dashboard_finds_reports_in_the_artifact_folder(tmp_path):
    _suite(tmp_path)
    paths = sorted(r.path for r in find_reports(tmp_path)[0])
    assert paths == [".mockymock/PROG.report.html", "PROG.report.html"]
