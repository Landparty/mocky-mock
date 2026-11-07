"""Integration tests levels 2 and 3 on a real compiler: `generate
--real-files` + `run --record-expectations` on a real input file, and
`mockymock job` over examples/jobflow (IEFBR14, a COBOL step with DB2
mocked, a SORT, a report step, COND= on the real return codes)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from mockymock.cli.main import main
from tests.integration._docker import requires_docker

JOBFLOW = Path(__file__).parent.parent.parent / "examples" / "jobflow"


def _jcl_available() -> bool:
    try:
        import cobolparser.jcl  # noqa: F401
    except ImportError:
        return False
    return True


requires_jcl = pytest.mark.skipif(
    not _jcl_available(), reason="jcl-parser not installed"
)


@requires_docker
def test_generate_real_files_then_record_and_compare(tmp_path: Path):
    program = tmp_path / "CUSTEXT.cbl"
    shutil.copyfile(JOBFLOW / "src" / "CUSTEXT.cbl", program)
    cut = tmp_path / "CUSTEXT.cut"
    assert main(["generate", str(program), "-o", str(cut), "--real-files"]) == 0
    text = cut.read_text()
    assert "USE REAL FILE CUST-IN FROM" in text
    assert "EXPECT FILE CUST-OUT MATCHES" in text
    assert main(["run", str(program), "--cut", str(cut), "--record-expectations"]) == 0
    golden = next((tmp_path / "expected").rglob("*.dat"))
    report = tmp_path / "report.json"
    assert (
        main(["run", str(program), "--cut", str(cut), "--json-report", str(report)])
        == 0
    )
    # A changed golden file is a failure that names the record.
    golden.write_bytes(b"X" * 20 + golden.read_bytes()[20:])
    assert (
        main(["run", str(program), "--cut", str(cut), "--json-report", str(report)])
        != 0
    )
    failures = [
        f["message"]
        for case in json.loads(report.read_text())["cases"]
        for f in case.get("failures") or []
    ]
    assert any("record 1 differs" in message for message in failures)


@requires_docker
@requires_jcl
def test_job_runs_end_to_end_and_compares(tmp_path: Path, capsys):
    report = tmp_path / "job.json"
    code = main(
        [
            "job",
            str(JOBFLOW / "jcl" / "CUSTJOB.jcl"),
            "--src",
            str(JOBFLOW / "src"),
            "--data",
            str(JOBFLOW / "data"),
            "--expected",
            str(JOBFLOW / "expected"),
            "--json-report",
            str(report),
        ]
    )
    document = json.loads(report.read_text())
    assert code == 0, capsys.readouterr().out
    assert document["verdict"] == "passed"
    assert [(s["name"], s["status"], s["rc"]) for s in document["steps"]] == [
        ("CLEANUP", "ran", 0),
        ("EXTRACT", "ran", 0),
        ("SORTHI", "ran", 0),
        ("REPORT", "ran", 0),
    ]
    assert document["datasets"] == [{"name": "PROD.CUST.REPORT", "status": "same"}]


@requires_docker
@requires_jcl
def test_job_bypasses_steps_on_the_real_return_code(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "PROD.CUST.MASTER").write_bytes(b"00001ALICE     00050")
    report = tmp_path / "job.json"
    code = main(
        [
            "job",
            str(JOBFLOW / "jcl" / "CUSTJOB.jcl"),
            "--src",
            str(JOBFLOW / "src"),
            "--data",
            str(data),
            "--expected",
            str(JOBFLOW / "expected"),
            "--json-report",
            str(report),
        ]
    )
    document = json.loads(report.read_text())
    assert code == 1
    statuses = {s["name"]: (s["status"], s["rc"]) for s in document["steps"]}
    assert statuses["EXTRACT"] == ("ran", 4)
    assert statuses["SORTHI"][0] == statuses["REPORT"][0] == "bypassed"
    assert document["datasets"][0]["status"] == "missing"


IXPROG = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. IXPROG.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IX-FILE ASSIGN TO IXDD
               ORGANIZATION IS INDEXED
               ACCESS MODE IS SEQUENTIAL
               RECORD KEY IS IX-KEY.
       DATA DIVISION.
       FILE SECTION.
       FD  IX-FILE.
       01  IX-REC.
           05  IX-KEY  PIC 9(4).
           05  IX-DATA PIC X(10).
       WORKING-STORAGE SECTION.
       01  WS-RESULT PIC X(4) VALUE SPACES.
       01  WS-SUM PIC 9(4) VALUE ZERO.
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN OUTPUT IX-FILE
           MOVE 1 TO IX-KEY
           MOVE "ONE" TO IX-DATA
           WRITE IX-REC
           MOVE 2 TO IX-KEY
           MOVE "TWO" TO IX-DATA
           WRITE IX-REC
           CLOSE IX-FILE
           OPEN INPUT IX-FILE
           READ IX-FILE
           ADD IX-KEY TO WS-SUM
           READ IX-FILE
           ADD IX-KEY TO WS-SUM
           CLOSE IX-FILE
           IF WS-SUM = 3
               MOVE "PASS" TO WS-RESULT
           ELSE
               MOVE "FAIL" TO WS-RESULT
           END-IF
           CALL "IXSUB" USING WS-RESULT
           STOP RUN.
"""

IXSUB = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. IXSUB.
       DATA DIVISION.
       LINKAGE SECTION.
       01  LK-RESULT PIC X(4).
       PROCEDURE DIVISION USING LK-RESULT.
       MAIN-PARA.
           IF LK-RESULT = "PASS"
               MOVE "DONE" TO LK-RESULT
           END-IF
           GOBACK.
"""


@requires_docker
def test_round_trip_indexed_file_and_real_calls_run(tmp_path: Path):
    program = tmp_path / "IXPROG.cbl"
    program.write_text(IXPROG)
    (tmp_path / "IXSUB.cbl").write_text(IXSUB)
    cut = tmp_path / "IXPROG.cut"
    assert main(["generate", str(program), "-o", str(cut), "--scenarios", "all"]) == 0
    text = cut.read_text()
    assert 'TESTCASE "round trip: IX-FILE real"' in text
    assert "    USE REAL FILE IX-FILE\n" in text
    assert 'TESTCASE "real calls: IXSUB"' in text
    assert 'USE REAL CALL "IXSUB" FROM "IXSUB.cbl"' in text
    assert main(["run", str(program), "--cut", str(cut), "--record-expectations"]) == 0
    coverage = tmp_path / "coverage.json"
    assert (
        main(
            ["run", str(program), "--cut", str(cut), "--branch-coverage", str(coverage)]
        )
        == 0
    )
    (report,) = [
        p
        for p in json.loads(coverage.read_text())["programs"]
        if p["programId"] == "IXPROG"
    ]
    # The round trip reads back what the program wrote: WS-SUM = 3 is taken.
    (branch,) = report["branches"]["items"]
    assert branch["outcomes"][0]["covered"]
