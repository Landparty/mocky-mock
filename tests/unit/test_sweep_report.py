"""The corpus-sweep snapshot, its per-category tallies and the diff
against an earlier run (mockymock/report/sweep.py), plus the
scripts/corpus_sweep.py front end that saves and compares them."""

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from mockymock.report.sweep import (
    EXCEPTION,
    NO_TEST_CASE,
    OTHER,
    PARSE_ERROR,
    TIMEOUT,
    UNRESOLVED_COPYBOOK,
    ProgramResult,
    SweepSnapshot,
    classify_output,
    crashed,
    diff_snapshots,
    render_diff,
    render_report,
    timed_out,
)

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "corpus_sweep", REPO / "scripts" / "corpus_sweep.py"
)
corpus_sweep = importlib.util.module_from_spec(_spec)
# dataclasses look the module up by name while the class is built.
sys.modules["corpus_sweep"] = corpus_sweep
_spec.loader.exec_module(corpus_sweep)


def _snap(**programs):
    return SweepSnapshot.from_results(
        ProgramResult(label=label, exit_code=1 if blockers else 0, blockers=blockers)
        for label, blockers in programs.items()
    )


# --- classify_output ------------------------------------------------------


def test_clean_run_has_no_blockers_but_keeps_boundaries():
    stdout = (
        "mockymock generate: wrote 2 test case(s) -> X.cut\n"
        "mockymock generate: 2 boundary point(s) detected that are not "
        "mockable (test cases reaching them will be refused):\n"
        "  - CALL in paragraph 'A' (line 12)\n"
        "  - nested READ in paragraph 'B' (line 20) -- inside AT END\n"
        "mockymock generate: done\n"
    )
    result = classify_output("X.cbl", 0, stdout)
    assert not result.blocked
    assert result.boundaries == {"CALL": 1, "nested READ": 1}


def test_refusal_codes_are_counted_per_code():
    stdout = (
        'mockymock generate: .cut line 4: TESTCASE "a" refused '
        "(UNSUPPORTED_TERMINATOR_LAYOUT): STOP RUN\n"
        "mockymock generate: refused (UNSUPPORTED_TERMINATOR_LAYOUT): again\n"
        "mockymock generate: refused (UNMOCKED_CALL): CALL 'X'\n"
    )
    result = classify_output("X.cbl", 1, stdout)
    assert result.blockers == {
        "UNSUPPORTED_TERMINATOR_LAYOUT": 2,
        "UNMOCKED_CALL": 1,
    }
    assert result.detail is None


def test_refusal_lines_on_a_clean_exit_are_not_blockers():
    result = classify_output("X.cbl", 0, "refused (UNMOCKED_CALL): x\n")
    assert not result.blocked


def test_parse_errors_missing_copybook_and_empty_scaffold():
    assert classify_output(
        "X", 1, "mockymock generate: 3 parse error(s):\n  line 1: bad\n"
    ).blockers == {PARSE_ERROR: 3}
    copybook = (
        "mockymock generate: Copybook 'GTTLBI0A' not found\n"
        "    Pass its location with --copybook-path <dir> (repeatable), or ...\n"
    )
    assert classify_output("X", 1, copybook).blockers == {UNRESOLVED_COPYBOOK: 1}
    empty = "mockymock generate: no test case to write -- no paragraph ...\n"
    assert classify_output("X", 1, empty).blockers == {NO_TEST_CASE: 1}


def test_unrecognised_failure_is_other_with_its_first_line():
    result = classify_output("X", 1, "\nmockymock generate: something new\n")
    assert result.blockers == {OTHER: 1}
    assert result.detail == "something new"


def test_crash_and_timeout():
    tb = "Traceback (most recent call last):\n  ...\nKeyError: 'x'\n"
    assert crashed("X", tb).blockers == {EXCEPTION: 1}
    assert crashed("X", tb).detail == "KeyError: 'x'"
    assert timed_out("X", 30).blockers == {TIMEOUT: 1}
    assert timed_out("X", 30).detail == "no result after 30s"


# --- snapshots ------------------------------------------------------------


def test_snapshot_round_trips_through_json(tmp_path):
    snap = _snap(**{"a.cbl": {"UNMOCKED_CALL": 2}, "b.cbl": {}})
    snap.programs["b.cbl"].boundaries = {"CALL": 1}
    path = tmp_path / "s.json"
    snap.save(path)
    data = json.loads(path.read_text())
    assert data["format"] == "mockymock-sweep" and data["version"] == 1
    assert data["programs"]["a.cbl"]["status"] == "blocked"
    assert data["programs"]["b.cbl"]["status"] == "clean"

    loaded = SweepSnapshot.load(path)
    assert loaded.to_dict() == snap.to_dict()


def test_snapshot_rejects_foreign_or_newer_files():
    with pytest.raises(ValueError, match="not a sweep snapshot"):
        SweepSnapshot.from_dict({"format": "junit"})
    with pytest.raises(ValueError, match="unsupported sweep snapshot version"):
        SweepSnapshot.from_dict({"format": "mockymock-sweep", "version": 99})


def test_duplicate_labels_are_kept_apart():
    snap = SweepSnapshot.from_results(
        [ProgramResult("P.cbl", 0), ProgramResult("P.cbl", 1, {OTHER: 1})]
    )
    assert sorted(snap.programs) == ["P.cbl", "P.cbl (2)"]


def test_tallies_count_programs_for_blockers_and_sites_for_boundaries():
    snap = _snap(
        **{
            "a": {"UNMOCKED_CALL": 3, PARSE_ERROR: 1},
            "b": {"UNMOCKED_CALL": 1},
            "c": {},
        }
    )
    snap.programs["a"].boundaries = {"CALL": 2}
    snap.programs["c"].boundaries = {"CALL": 1}
    assert snap.blocker_tally() == {"UNMOCKED_CALL": 2, PARSE_ERROR: 1}
    assert snap.boundary_tally() == {"CALL": 3}
    assert (snap.clean_count, snap.blocked_count) == (1, 2)


# --- diff -----------------------------------------------------------------


def test_diff_names_progress_and_regressions_per_category():
    before = _snap(
        fixed={"UNSUPPORTED_TERMINATOR_LAYOUT": 1},
        regressed={},
        moved={"UNSUPPORTED_TERMINATOR_LAYOUT": 1},
        same={"UNMOCKED_CALL": 1},
        gone={OTHER: 1},
    )
    after = _snap(
        fixed={},
        regressed={"UNMOCKED_CALL": 1},
        moved={UNRESOLVED_COPYBOOK: 1},
        same={"UNMOCKED_CALL": 2},
        new={TIMEOUT: 1},
    )
    diff = diff_snapshots(before, after)

    assert diff.newly_clean == ["fixed"]
    assert diff.newly_blocked == ["regressed"]
    assert diff.changed == ["moved"]
    assert diff.added == ["new"]
    assert diff.removed == ["gone"]
    assert diff.regressions == ["moved", "regressed"]
    assert diff.has_regressions

    by_name = {c.category: c for c in diff.categories}
    terminator = by_name["UNSUPPORTED_TERMINATOR_LAYOUT"]
    assert (terminator.before, terminator.after, terminator.delta) == (2, 0, -2)
    assert terminator.lost == ["fixed", "moved"] and terminator.gained == []
    call = by_name["UNMOCKED_CALL"]
    assert (call.before, call.after) == (1, 2)
    # "same" kept its category (the count of refusals is not a change).
    assert call.gained == ["regressed"] and call.lost == []
    # Added/removed programs move the counts but are not regressions.
    assert (by_name[TIMEOUT].after, by_name[TIMEOUT].gained) == (1, [])
    assert (by_name[OTHER].before, by_name[OTHER].lost) == (1, [])


def test_diff_without_regressions():
    before = _snap(a={"UNMOCKED_CALL": 1}, b={})
    after = _snap(a={}, b={})
    diff = diff_snapshots(before, after)
    assert not diff.has_regressions
    assert diff.newly_clean == ["a"]
    assert "No regressions." in render_diff(diff)


def test_boundary_diff():
    before = _snap(a={})
    before.programs["a"].boundaries = {"CALL": 2}
    after = _snap(a={})
    after.programs["a"].boundaries = {"nested READ": 1}
    diff = diff_snapshots(before, after)
    by_name = {c.category: c for c in diff.boundaries}
    assert (by_name["CALL"].before, by_name["CALL"].lost) == (2, ["a"])
    assert (by_name["nested READ"].after, by_name["nested READ"].gained) == (1, ["a"])
    # A boundary is not a blocker: no regression.
    assert not diff.has_regressions


# --- Markdown -------------------------------------------------------------


def test_render_report_tables():
    snap = _snap(a={"UNMOCKED_CALL": 2}, b={})
    snap.programs["b"].boundaries = {"CALL": 1}
    snap.programs["a"].detail = "x | y"
    text = render_report(snap)
    assert "| a | blocked | 1 | UNMOCKED_CALL x2 (x / y) | - |" in text
    assert "| b | clean | 0 | - | CALL |" in text
    assert "- Blocked: 1" in text
    assert "| UNMOCKED_CALL | 1 |" in text


def test_render_diff_lists_changes():
    before = _snap(a={"UNMOCKED_CALL": 1}, b={})
    after = _snap(a={}, b={PARSE_ERROR: 1})
    text = render_diff(diff_snapshots(before, after))
    assert "**1 regression(s):**" in text
    assert "| PARSE_ERROR | 0 | 1 | +1 | b | - |" in text
    assert "| UNMOCKED_CALL | 1 | 0 | -1 | - | a |" in text
    assert "- a: UNMOCKED_CALL -> clean" in text
    assert "- b: clean -> PARSE_ERROR" in text


def test_long_program_lists_are_shortened():
    before = _snap(**{f"p{i:02}": {} for i in range(10)})
    after = _snap(**{f"p{i:02}": {OTHER: 1} for i in range(10)})
    text = render_diff(diff_snapshots(before, after))
    assert "p07, +2 more" in text


# --- scripts/corpus_sweep.py ----------------------------------------------

BROKEN = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. BROKEN.
       PROCEDURE DIVISION.
           MOVE TO.
"""

NEEDS_COPYBOOK = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. NEEDSCPY.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       COPY NOSUCHCP.
       PROCEDURE DIVISION.
           GOBACK.
"""


@pytest.fixture
def corpus(tmp_path):
    root = tmp_path / "src"
    root.mkdir()
    shutil.copy(
        REPO / "tests" / "integration" / "fixtures" / "walking_skeleton.cbl",
        root / "GOOD.cbl",
    )
    (root / "sub").mkdir()
    (root / "sub" / "BROKEN.cob").write_text(BROKEN)
    (root / "NEEDCPY.CBL").write_text(NEEDS_COPYBOOK)
    (root / "notes.txt").write_text("not a program")
    return root


def test_discover_corpus_dir_labels_relative_to_its_parent(corpus, tmp_path):
    extra = tmp_path / "copy"
    entries = corpus_sweep.discover_corpus([corpus], [extra])
    assert sorted(e.label for e in entries) == [
        "src/GOOD.cbl",
        "src/NEEDCPY.CBL",
        "src/sub/BROKEN.cob",
    ]
    assert all(e.copybook_dirs == [extra] for e in entries)
    single = corpus_sweep.discover_corpus([corpus / "GOOD.cbl"])
    assert [e.label for e in single] == ["GOOD.cbl"]


def test_sweep_saves_snapshot_and_diffs_against_baseline(corpus, tmp_path, capsys):
    first = tmp_path / "first.json"
    assert corpus_sweep.main(["--corpus", str(corpus), "--json", str(first)]) == 0
    snap = SweepSnapshot.load(first)
    assert snap.programs["src/GOOD.cbl"].blocked is False
    assert snap.programs["src/sub/BROKEN.cob"].blockers.keys() == {PARSE_ERROR}
    assert snap.programs["src/NEEDCPY.CBL"].blockers == {UNRESOLVED_COPYBOOK: 1}
    assert "# Corpus Sweep Report" in capsys.readouterr().out

    # Fix one program, break another.
    (corpus / "NEEDCPY.CBL").write_text(NEEDS_COPYBOOK.replace("COPY NOSUCHCP.", ""))
    (corpus / "GOOD.cbl").write_text(BROKEN)
    report = tmp_path / "report.md"
    code = corpus_sweep.main(
        [
            "--corpus",
            str(corpus),
            "--baseline",
            str(first),
            "--fail-on-regression",
            "-o",
            str(report),
        ]
    )
    assert code == 1
    text = report.read_text()
    assert "## Changes since the previous sweep" in text
    assert "- src/GOOD.cbl: clean -> PARSE_ERROR" in text
    assert "| UNRESOLVED_COPYBOOK | 1 | 0 | -1 | - | src/NEEDCPY.CBL |" in text


def test_fail_on_regression_needs_a_baseline(capsys):
    assert corpus_sweep.main(["--fail-on-regression"]) == 2
    assert "needs --baseline" in capsys.readouterr().err


def test_bad_baseline_fails_before_sweeping(tmp_path, monkeypatch):
    bad = tmp_path / "bad.json"
    bad.write_text('{"format": "other"}')
    monkeypatch.setattr(corpus_sweep, "sweep", pytest.fail)
    with pytest.raises(ValueError, match="not a sweep snapshot"):
        corpus_sweep.main(["--baseline", str(bad)])


def test_subprocess_mode_matches_in_process(corpus):
    entries = corpus_sweep.discover_corpus([corpus])
    in_process = corpus_sweep.sweep(entries)
    child = corpus_sweep.sweep(entries, timeout=300, jobs=2)
    assert [r.to_dict() for r in child] == [r.to_dict() for r in in_process]


def test_subprocess_timeout_and_crash(corpus, monkeypatch):
    (entry,) = corpus_sweep.discover_corpus([corpus / "GOOD.cbl"])

    def hang(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])

    monkeypatch.setattr(corpus_sweep.subprocess, "run", hang)
    result = corpus_sweep.run_generate_subprocess(entry, Path("x.cut"), 5)
    assert result.blockers == {TIMEOUT: 1}

    def crash(*args, **kwargs):
        return subprocess.CompletedProcess(
            args[0], 1, "", "Traceback (most recent call last):\nRuntimeError: boom\n"
        )

    monkeypatch.setattr(corpus_sweep.subprocess, "run", crash)
    result = corpus_sweep.run_generate_subprocess(entry, Path("x.cut"), 5)
    assert result.blockers == {EXCEPTION: 1}
    assert result.detail == "RuntimeError: boom"


def test_in_process_crash_is_recorded(corpus, monkeypatch):
    (entry,) = corpus_sweep.discover_corpus([corpus / "GOOD.cbl"])
    import mockymock.cli.main as cli_main

    def boom(argv):
        raise RuntimeError("boom")

    monkeypatch.setattr(cli_main, "main", boom)
    result = corpus_sweep.run_generate(entry, Path("x.cut"))
    assert result.blockers == {EXCEPTION: 1}
    assert result.detail == "RuntimeError: boom"


def test_missing_copybook_with_a_search_path_tallies_as_unresolved(corpus, tmp_path):
    # With --copybook-path, generate fails with the cobol-parser error and
    # the --copybook-path hint instead of the refusal code: same category.
    (entry,) = corpus_sweep.discover_corpus(
        [corpus / "NEEDCPY.CBL"], [tmp_path / "copy"]
    )
    (tmp_path / "copy").mkdir()
    result = corpus_sweep.run_generate(entry, tmp_path / "x.cut")
    assert result.blockers == {UNRESOLVED_COPYBOOK: 1}
