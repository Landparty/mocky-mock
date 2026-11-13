"""`mockymock job` fixes for the smaller notes of the 2026-11-10 bug hunts:
the post-abend IF guard, in-stream SORTIN framing, the end-of-job layout of
fixed records holding X'0A', and the up-front JobOptions.command check."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import cobolparser.jcl as cj
import pytest

from mockymock.jobstream.conditions import step_runs
from mockymock.jobstream.runner import JobOptions, run_job_stream


def _dd(
    name, dataset=None, disposition=None, *, instream=None, lrecl=None, dummy=False
):
    dd = SimpleNamespace(
        name=name,
        dataset=dataset,
        disposition=disposition,
        is_dummy=dummy,
        is_instream=instream is not None,
        instream_lines=instream,
        sysout=None,
        record_length=lrecl,
    )
    dd.flatten = lambda: [dd]
    return dd


def _step(name, program, dds, condition=None):
    return SimpleNamespace(
        name=name, program=program, dd_statements=dds, condition=condition
    )


def _run(monkeypatch, tmp_path: Path, steps, inputs=None, expected=None, **options):
    data = tmp_path / "data"
    data.mkdir()
    for name, content in (inputs or {}).items():
        (data / name).write_bytes(content)
    (tmp_path / "j.jcl").write_text("x")
    monkeypatch.setattr(
        cj,
        "parse_jcl",
        lambda *a, **k: SimpleNamespace(
            errors=[], jobs=[SimpleNamespace(name="J", steps=steps)], unresolved=[]
        ),
    )
    return run_job_stream(
        JobOptions(
            jcl=tmp_path / "j.jcl",
            sources=options.pop("sources", []),
            data=data,
            expected=expected,
            work_dir=tmp_path,
            **options,
        )
    )


def test_step_named_like_abend_does_not_pass_the_post_abend_guard():
    rcs = {"S1": None, "ABENDCHK": 0}
    assert step_runs("(ABENDCHK.RC = 0)", rcs, True) is False
    assert step_runs("(S1.ABEND)", rcs, True) is True
    assert step_runs("(ABEND)", rcs, True) is True
    assert step_runs("(ABENDCHK.RC = 0)", rcs, False) is True


def test_instream_sortin_without_lrecl_sorts_80_byte_cards(monkeypatch, tmp_path):
    expected = tmp_path / "expected"
    expected.mkdir()
    (expected / "OUT.SORTED").write_bytes(b"AAA".ljust(80) + b"BBB".ljust(80))
    report = _run(
        monkeypatch,
        tmp_path,
        [
            _step(
                "S1",
                "SORT",
                [
                    _dd("SORTIN", instream=["BBB", "AAA"]),
                    _dd("SORTOUT", "OUT.SORTED", "(NEW,CATLG)"),
                    _dd("SYSIN", instream=["  SORT FIELDS=(1,3,CH,A)"]),
                ],
            )
        ],
        expected=expected,
    )
    assert report["steps"][0]["status"] == "ran", report
    assert report["datasets"] == [{"name": "OUT.SORTED", "status": "same"}]


@pytest.mark.parametrize(
    ("out_lrecl", "width"), [(40, 40), (160, 160)], ids=["shorter", "longer"]
)
def test_instream_sortin_is_split_as_cards_then_fitted_to_sortout(
    monkeypatch, tmp_path, out_lrecl, width
):
    """#460: SORTOUT's LRECL does not re-split 80-byte in-stream cards."""
    expected = tmp_path / "expected"
    expected.mkdir()
    (expected / "OUT.DS").write_bytes(
        b"AAAAA RECORD TWO".ljust(width) + b"BBBBB RECORD ONE".ljust(width)
    )
    report = _run(
        monkeypatch,
        tmp_path,
        [
            _step(
                "S1",
                "SORT",
                [
                    _dd("SORTIN", instream=["BBBBB RECORD ONE", "AAAAA RECORD TWO"]),
                    _dd("SORTOUT", "OUT.DS", "(NEW,CATLG)", lrecl=out_lrecl),
                    _dd("SYSIN", instream=["  SORT FIELDS=(1,5,CH,A)"]),
                ],
            )
        ],
        expected=expected,
    )
    assert report["steps"][0]["status"] == "ran", report
    assert report["datasets"] == [{"name": "OUT.DS", "status": "same"}]


def test_fixed_records_holding_x0a_are_compared_as_fixed(monkeypatch, tmp_path):
    # 8-byte fixed records; the second holds X'0A'. Read as lines, the
    # trailing blanks GnuCOBOL drops from a LINE SEQUENTIAL record would hide
    # the difference from the golden file.
    actual = b"DDDDDDDD" + b"AB\nCCC  "
    golden = b"DDDDDDDD" + b"AB  \nCCC"
    expected = tmp_path / "expected"
    expected.mkdir()
    (expected / "OUT.FIXED").write_bytes(golden)
    report = _run(
        monkeypatch,
        tmp_path,
        [
            _step(
                "S1",
                "IEBGENER",
                [
                    _dd("SYSUT1", "IN.FIXED", "SHR", lrecl=8),
                    _dd("SYSUT2", "OUT.FIXED", "(NEW,CATLG)", lrecl=8),
                    _dd("SYSIN", dummy=True),
                ],
            )
        ],
        inputs={"IN.FIXED": actual},
        expected=expected,
    )
    [result] = report["datasets"]
    assert result["status"] == "differs"
    assert result["detail"].startswith("record 2 differs")


def test_missing_command_fails_before_any_step_runs(monkeypatch, tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "MYPROG.cbl").write_text(
        "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. MYPROG.\n"
    )
    ran = []
    import mockymock.jobstream.runner as runner

    original = runner.JobRun._run_step
    monkeypatch.setattr(
        runner.JobRun,
        "_run_step",
        lambda self, name, step: ran.append(name) or original(self, name, step),
    )
    with pytest.raises(ValueError, match="JobOptions.command"):
        _run(
            monkeypatch,
            tmp_path,
            [_step("S1", "IEFBR14", []), _step("S2", "MYPROG", [])],
            sources=[src],
        )
    assert ran == []
