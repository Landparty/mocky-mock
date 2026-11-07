"""Integration tests levels 2 and 3, the parts that need no compiler:
the `USE REAL FILE` / `EXPECT FILE` / `SAVE FILE` DSL, the ASSIGN rewrite,
the per-case staging, the file compare, `generate --real-files`'s suite
rewrite, and the job runner's conditions, utilities and step suite."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from mockymock.dsl.parser import CutParseError, parse_cut
from mockymock.dsl.real_file_suite import (
    RealFilePlan,
    make_real_file_suite,
    read_rows,
    round_trip_case,
)
from mockymock.jobstream.conditions import ConditionError, step_runs
from mockymock.jobstream.runner import (
    StepFile,
    _disposition,
    _verdict,
    ddname_of_assign,
    format_job_console,
    step_suite,
)
from mockymock.jobstream.utilities import (
    UtilityGap,
    control_statements,
    sort_data,
)
from mockymock.runner.jobs import (
    JobPackError,
    _generate_args,
    load_manifest,
    suite_files,
)
from mockymock.splicer.real_files import (
    FileLayout,
    check_files,
    compare_file,
    insert_case_staging,
    rewrite_assigns,
)

# -- the DSL ---------------------------------------------------------------

SUITE = """\
TESTSUITE "INV"

BEFORE-EACH
    USE REAL FILE LOG-FILE
END-BEFORE

TESTCASE "reads the real file"
    USE REAL FILE IN-FILE FROM "data/in.dat"
    PERFORM MAIN-PARA
    EXPECT FILE OUT-FILE MATCHES "expected/out.dat"
    SAVE FILE LOG-FILE TO "out/log.dat"
"""


def test_use_real_file_and_file_checks_parse():
    suite = parse_cut(SUITE)
    (case,) = suite.test_cases
    real = {r.file: r.source for r in case.real_files}
    assert real == {"IN-FILE": "data/in.dat", "LOG-FILE": None}
    kinds = [(c.kind, c.file, c.path) for c in case.file_checks]
    assert kinds == [
        ("EXPECT", "OUT-FILE", "expected/out.dat"),
        ("SAVE", "LOG-FILE", "out/log.dat"),
    ]


def test_use_real_file_after_perform_is_refused():
    text = SUITE.replace(
        "    EXPECT FILE OUT-FILE", "    USE REAL FILE X-FILE\n    EXPECT FILE OUT-FILE"
    )
    with pytest.raises(CutParseError):
        parse_cut(text)


# -- the splicer side --------------------------------------------------------


def test_rewrite_assigns_points_into_the_sandbox():
    lines = [
        "           SELECT IN-FILE",
        "               ASSIGN TO UT-S-INFILE",
        "               ORGANIZATION IS SEQUENTIAL.",
        "           SELECT OTHER ASSIGN TO OTHERDD.",
    ]
    out, problems = rewrite_assigns(lines, {"IN-FILE": 1}, {"IN-FILE", "MISSING"})
    assert out[1] == '               ASSIGN TO "ut-files/IN-FILE"'
    assert out[3] == lines[3]
    assert problems == ["USE REAL FILE MISSING: the program has no SELECT MISSING"]


def test_rewrite_assigns_skips_the_identification_area_and_a_split_name():
    # NIST style: ASSIGN TO ends the line, the name is on the next one, and
    # columns 73-80 hold a sequence tag the compiler ignores.
    tag = "SQ1024.2"
    lines = [
        "       SELECT SQ-FS1".ljust(72) + tag,
        "              ACCESS MODE IS SEQUENTIAL".ljust(72) + tag,
        "              ASSIGN TO".ljust(72) + tag,
        '       "XXXXX001"'.ljust(72) + tag,
        "              .".ljust(72) + tag,
    ]
    out, problems = rewrite_assigns(lines, {"SQ-FS1": 1}, {"SQ-FS1"})
    assert problems == []
    assert out[2] == lines[2]
    assert out[3].startswith('       "ut-files/SQ-FS1"')
    # Normalized text (no columns) works the same way.
    flat = ["SELECT SQ-FS1", "ASSIGN TO", '"XXXXX001"', "."]
    out, _ = rewrite_assigns(flat, {"SQ-FS1": 1}, {"SQ-FS1"})
    assert out[1:3] == ["ASSIGN TO", '"ut-files/SQ-FS1"']


def test_case_staging_goes_after_the_case_marker():
    suite = parse_cut(SUITE)
    instrumented = [
        "       UT-TESTCASE-001.",
        '           MOVE "001" TO UT-CURRENT-CASE',
        "           MOVE 0 TO RETURN-CODE",
        "           PERFORM MAIN-PARA",
        '           DISPLAY "__MOCKYMOCK__ CASE 001 END".',
    ]
    out = insert_case_staging(
        instrumented, suite, {(1, "IN-FILE"): "ut-fixtures/001-IN-FILE"}
    )
    joined = "\n".join(out)
    assert out[2] == '           CALL "CBL_DELETE_FILE" USING "ut-files/IN-FILE"'
    assert (
        'CALL "CBL_COPY_FILE" USING "ut-fixtures/001-IN-FILE" "ut-files/IN-FILE"'
        in joined
    )
    assert joined.index("ut-out/001-0") < joined.index("CASE 001 END")
    assert joined.index("CBL_DELETE_FILE") < joined.index("MOVE 0 TO RETURN-CODE")


def test_compare_fixed_and_line_sequential():
    fixed = FileLayout("SEQUENTIAL", 4)
    assert compare_file(b"AAAABBBB", b"AAAABBBB", fixed) is None
    assert "record 2 differs" in (compare_file(b"AAAABBBX", b"AAAABBBB", fixed) or "")
    assert "expected 1 record(s), got 2" in (
        compare_file(b"AAAABBBB", b"AAAA", fixed) or ""
    )
    line = FileLayout("LINE SEQUENTIAL", None)
    assert compare_file(b"A  \nB\n", b"A\r\nB", line) is None


def test_check_files_records_then_compares(tmp_path: Path):
    suite = parse_cut(SUITE)
    snapshots = {"ut-out/001-0": b"ROW1ROW2", "ut-out/001-1": b"LOG"}
    layouts = {"OUT-FILE": FileLayout("SEQUENTIAL", 4)}
    missing = check_files(suite, snapshots, tmp_path, layouts, record=False, ran={1})
    assert "no such golden file" in (missing[0].failure or "")
    recorded = check_files(suite, snapshots, tmp_path, layouts, record=True, ran={1})
    assert (
        recorded[0].recorded
        and (tmp_path / "expected/out.dat").read_bytes() == b"ROW1ROW2"
    )
    assert (tmp_path / "out/log.dat").read_bytes() == b"LOG"
    snapshots["ut-out/001-0"] = b"ROW1ROWX"
    differs = check_files(suite, snapshots, tmp_path, layouts, record=False, ran={1})
    assert "record 2 differs" in (differs[0].failure or "")
    gone = check_files(suite, {}, tmp_path, layouts, record=False, ran={1})
    assert "left no file" in (gone[0].failure or "")


# -- generate --real-files -----------------------------------------------------

GENERATED = """\
TESTSUITE "CUSTEXT"

TESTCASE "happy path"
    MOCK OPEN CUST-IN
    END-MOCK
    MOCK READ CUST-IN
        EVALUATE TRUE
            WHEN UT-READ-CUST-IN-TALLY = 1
                MOVE 7 TO CI-ID
                MOVE "ANNA" TO CI-NAME
            WHEN OTHER
                MOVE "10" TO UT-FILE-STATUS
        END-EVALUATE
    END-MOCK
    MOCK WRITE CUST-OUT-REC
    END-MOCK
    MOCK SQL "INSERT"
        MOVE 0 TO SQLCODE
    END-MOCK
    PERFORM MAIN-PARA
    VERIFY WRITE CUST-OUT-REC WAS CALLED 1 TIME
    *> STUB EXPECT CUST-OUT-REC TO BE "x"
    EXPECT RETURN-CODE TO BE 0
"""


def test_read_rows_reads_the_tally_arms():
    body = GENERATED.split("MOCK READ CUST-IN\n")[1].split("END-MOCK")[0].splitlines()
    assert read_rows(body) == [{"CI-ID": "7", "CI-NAME": "ANNA"}]
    assert read_rows(["    MOVE 3 TO A-FIELD"]) == [{"A-FIELD": "3"}]


def test_make_real_file_suite_rewrites_the_file_mocks(tmp_path: Path):
    plans = [
        RealFilePlan("CUST-IN", {"CUST-IN", "CUST-IN-REC"}, reads=True, writes=False),
        RealFilePlan(
            "CUST-OUT", {"CUST-OUT", "CUST-OUT-REC"}, reads=False, writes=True
        ),
    ]
    text, files, notes = make_real_file_suite(
        GENERATED, plans, "CUSTEXT", tmp_path / "CUSTEXT.cut"
    )
    assert "MOCK OPEN CUST-IN" not in text and "MOCK WRITE" not in text
    assert 'MOCK SQL "INSERT"' in text
    assert "VERIFY WRITE" not in text and "STUB EXPECT" not in text
    assert 'USE REAL FILE CUST-IN FROM "data/CUSTEXT/1-CUST-IN.dat"' in text
    assert text.index("USE REAL FILE CUST-OUT") < text.index("PERFORM MAIN-PARA")
    assert text.rstrip().endswith(
        'EXPECT FILE CUST-OUT MATCHES "expected/CUSTEXT/1-CUST-OUT.dat"'
    )
    assert list(files) == [tmp_path / "data/CUSTEXT/1-CUST-IN.dat"]
    parse_cut(text)  # still a valid suite
    assert notes[-1].startswith("real files: CUST-IN, CUST-OUT")


ROUND_TRIP = """\
TESTSUITE "SQ1"

TESTCASE "happy path"
    MOCK OPEN PRINT-FILE
    END-MOCK
    MOCK OPEN SQ-FS1 OUTPUT
    END-MOCK
    MOCK READ SQ-FS1
        MOVE "A" TO SQ-REC
    END-MOCK
    PERFORM OPEN-FILES THRU CCVS-999999
    *> CHARACTERIZATION: recorded by mockymock run --record-expectations
    EXPECT SQ-REC TO BE "A"
    VERIFY OPEN PRINT-FILE WAS CALLED 1 TIMES
    VERIFY OPEN SQ-FS1 OUTPUT WAS CALLED 1 TIMES
    *> VERIFY READ SQ-FS1 WAS CALLED <count not exact by construction>

TESTCASE "empty input"
    PERFORM OPEN-FILES THRU CCVS-999999
"""


def _plan(first_create, first_open_read, reads=True, writes=True):
    return RealFilePlan(
        "SQ-FS1",
        {"SQ-FS1", "SQ-REC"},
        reads=reads,
        writes=writes,
        first_create=first_create,
        first_open_read=first_open_read,
    )


def test_round_trip_case_copies_the_first_case_with_the_file_real():
    text = round_trip_case(ROUND_TRIP, [_plan(10, 20)])
    case = text.split('TESTCASE "round trip: SQ-FS1 real"\n')[1]
    assert case.startswith("    USE REAL FILE SQ-FS1\n    MOCK OPEN PRINT-FILE")
    assert "SQ-FS1" not in case.replace("USE REAL FILE SQ-FS1", "")
    assert "EXPECT" not in case and "CHARACTERIZATION" not in case
    assert "VERIFY OPEN PRINT-FILE WAS CALLED 1 TIMES" in case
    assert text.startswith(ROUND_TRIP.rstrip("\n"))
    assert len(parse_cut(text).test_cases) == 3


@pytest.mark.parametrize(
    "plan",
    [
        _plan(20, 10),  # read before the program creates the file
        _plan(None, 10),
        _plan(10, 20, writes=False),
        _plan(10, 20, reads=False),
    ],
)
def test_round_trip_case_needs_a_file_written_before_it_is_read(plan):
    assert round_trip_case(ROUND_TRIP, [plan]) == ROUND_TRIP


def test_round_trip_case_without_a_case():
    assert round_trip_case('TESTSUITE "X"\n', [_plan(1, 2)]) == 'TESTSUITE "X"\n'


# -- conditions ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("condition", "rcs", "abended", "runs"),
    [
        (None, {}, False, True),
        (None, {"S1": None}, True, False),
        ("(4,LE)", {"S1": 0}, False, True),
        ("(4,LE)", {"S1": 4}, False, False),
        ("(4,LE,S1)", {"S1": 0, "S2": 8}, False, True),
        ("((4,LT),(8,GT,S2))", {"S1": 0, "S2": 4}, False, False),
        ("EVEN", {"S1": None}, True, True),
        ("ONLY", {"S1": 0}, False, False),
        ("ONLY", {"S1": None}, True, True),
        ("(S1.RC = 0)", {"S1": 0}, False, True),
        ("(S1.RC = 0) AND (S2.RC < 8)", {"S1": 0, "S2": 8}, False, False),
        ("NOT (S1.RC > 4)", {"S1": 4}, False, True),
        ("(RC <= 4)", {"S1": 0, "S2": 4}, False, True),
        ("(S1.ABEND)", {"S1": None}, True, True),
        ("(S9.RUN)", {"S1": 0}, False, False),
    ],
)
def test_step_runs(condition, rcs, abended, runs):
    assert step_runs(condition, rcs, abended) is runs


@pytest.mark.parametrize(
    "condition", ["(4,XX)", "(S1.RC = )", "(NOSUCH.RC = 0)", "(FOO)"]
)
def test_unreadable_conditions_are_gaps(condition):
    with pytest.raises(ConditionError):
        step_runs(condition, {"S1": 0}, False)


# -- utilities -------------------------------------------------------------------


def test_sort_by_character_and_zoned_keys():
    data = b"03CC" + b"01AA" + b"02BB"
    assert (
        sort_data(data, control_statements(["  SORT FIELDS=(3,2,CH,A)"]), 4)
        == b"01AA02BB03CC"
    )
    assert (
        sort_data(data, control_statements(["  SORT FIELDS=(1,2,ZD,D)"]), 4)
        == b"03CC02BB01AA"
    )
    assert sort_data(data, control_statements([" SORT FIELDS=COPY"]), 4) == data


def test_unsupported_sort_statements_are_gaps():
    with pytest.raises(UtilityGap):
        sort_data(
            b"AAAA",
            control_statements(
                ["  SORT FIELDS=(1,2,CH,A)", "  INCLUDE COND=(1,1,CH,EQ,C'A')"]
            ),
            4,
        )


# -- the job runner ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("assign", "dd"),
    [
        ("UT-S-INFILE", "INFILE"),
        ('"CUSTIN"', "CUSTIN"),
        ("CUSTIN", "CUSTIN"),
        ("/tmp/x.dat", None),
        (None, None),
    ],
)
def test_ddname_of_assign(assign, dd):
    assert ddname_of_assign(assign) == dd


def test_disposition_defaults():
    dd = SimpleNamespace(disposition="(NEW,CATLG,DELETE)", dataset="PROD.X")
    assert _disposition(dd) == ("NEW", "CATLG", "DELETE")
    assert _disposition(SimpleNamespace(disposition="SHR", dataset="PROD.X")) == (
        "SHR",
        "KEEP",
        "KEEP",
    )
    assert _disposition(SimpleNamespace(disposition=None, dataset="&&T"))[1] == "DELETE"


def test_step_suite_keeps_one_case_and_declares_the_files():
    files = [
        StepFile(
            "CUST-IN",
            "CUSTIN",
            [],
            True,
            False,
            source=Path("/w/in"),
            names={"CUST-IN", "CUST-IN-REC"},
        ),
        StepFile(
            "CUST-OUT", "CUSTOUT", [], False, True, names={"CUST-OUT", "CUST-OUT-REC"}
        ),
    ]
    text = step_suite(
        GENERATED + '\nTESTCASE "second"\n    PERFORM MAIN-PARA\n', files, "EXTRACT"
    )
    assert 'TESTCASE "step EXTRACT"' in text and '"second"' not in text
    assert "MOCK READ CUST-IN" not in text and "MOCK WRITE CUST-OUT-REC" not in text
    assert 'MOCK SQL "INSERT"' in text
    assert 'USE REAL FILE CUST-IN FROM "/w/in"' in text
    assert 'SAVE FILE CUST-OUT TO "out/CUST-OUT"' in text
    assert text.count("EXPECT RETURN-CODE TO BE 0") == 1
    parse_cut(text)


def test_verdicts_and_console():
    from mockymock.jobstream.runner import StepResult

    ran = [StepResult("S1", "P", "cobol", "ran", rc=0)]
    assert _verdict(ran, [{"status": "same"}], [], False) == "passed"
    assert _verdict(ran, [{"status": "differs"}], [], False) == "failed"
    assert _verdict(ran, [], [], True) == "recorded"
    assert _verdict(ran, [], ["gap"], False) == "incomplete"
    shown = format_job_console(
        {
            "job": "J",
            "jcl": "j.jcl",
            "verdict": "passed",
            "steps": [s.to_dict() for s in ran],
            "datasets": [{"name": "D", "status": "same"}],
            "gaps": [],
            "notes": ["n"],
        }
    )
    assert "step S1" in shown and "dataset D: same" in shown and "note: n" in shown


# -- the runner's pack ----------------------------------------------------------------


def test_manifest_with_jobs_only(tmp_path: Path):
    (tmp_path / "oracle.json").write_text(
        json.dumps(
            {"version": 1, "kind": "tests", "jobs": [{"name": "J", "jcl": "jcl/J.jcl"}]}
        )
    )
    assert load_manifest(tmp_path)["suites"] == []
    (tmp_path / "oracle.json").write_text(
        json.dumps(
            {"version": 1, "kind": "baseline", "jobs": [{"name": "J"}], "suites": [{}]}
        )
    )
    with pytest.raises(JobPackError):
        load_manifest(tmp_path)


def test_generate_takes_real_files(tmp_path: Path):
    (tmp_path / "src").mkdir()
    args = _generate_args(
        tmp_path, "mockymock generate src/P.cbl --real-files --scenarios all"
    )
    assert args == ["generate", "src/P.cbl", "--real-files", "--scenarios", "all"]


def test_suite_files_reports_the_named_files(tmp_path: Path):
    (tmp_path / "tests/data").mkdir(parents=True)
    (tmp_path / "tests/data/in.dat").write_bytes(b"ROW")
    cut = tmp_path / "tests/P.cut"
    text = (
        'TESTCASE "x"\n    USE REAL FILE A FROM "data/in.dat"\n    PERFORM P\n'
        '    EXPECT FILE B MATCHES "expected/none.dat"\n'
        '    EXPECT FILE C MATCHES "../../outside.dat"\n'
    )
    assert suite_files(tmp_path, cut, text) == {
        "tests/data/in.dat": base64.b64encode(b"ROW").decode()
    }
