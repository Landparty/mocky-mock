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


def _staged_copylib(tmp_path):
    from mockymock.project.copybook_aliases import stage_copybook_aliases

    lib = tmp_path / "copylib"
    lib.mkdir(parents=True)
    (lib / "gttlbi0a.copy").write_text("       01 A PIC X.\n", encoding="utf-8")
    staged = stage_copybook_aliases([str(lib)])
    assert staged is not None
    return lib, staged


def test_clean_removes_staged_copies_of_renamed_copybooks(tmp_path, capsys):
    from mockymock.project.copybook_aliases import manifest_path

    _lib, staged = _staged_copylib(tmp_path)
    manifest = manifest_path(staged)
    assert manifest.is_file()
    assert main(["clean", str(tmp_path), "--dry-run"]) == 0
    assert staged.is_dir()
    assert f"would remove {staged}" in capsys.readouterr().out
    assert main(["clean", str(tmp_path)]) == 0
    assert not staged.exists()
    assert not manifest.exists()
    assert "staged copybook copies" in capsys.readouterr().out


def test_clean_keeps_another_projects_staged_copies(tmp_path):
    _lib, staged = _staged_copylib(tmp_path / "other")
    (tmp_path / "mine").mkdir()
    assert main(["clean", str(tmp_path / "mine")]) == 0
    assert staged.is_dir()


def test_clean_follows_the_configured_copybook_path(tmp_path, monkeypatch):
    lib, staged = _staged_copylib(tmp_path / "shared")
    project = tmp_path / "project"
    project.mkdir()
    (project / "mockymock.toml").write_text(
        f"copybook_path = [{str(lib)!r}]\n", encoding="utf-8"
    )
    monkeypatch.chdir(project)
    assert main(["clean", str(project)]) == 0
    assert not staged.exists()


def test_clean_removes_staging_without_a_manifest(tmp_path):
    from mockymock.project.copybook_aliases import manifest_path

    _lib, staged = _staged_copylib(tmp_path / "other")
    manifest_path(staged).unlink()
    (tmp_path / "mine").mkdir()
    assert main(["clean", str(tmp_path / "mine")]) == 0
    assert not staged.exists()
