from pathlib import Path

from cobolparser import parse_cobol
from cobolparser.preprocess import normalize_fixed_format

from mockymock.analysis.mock_surface import analyze
from mockymock.cli.main import main
from mockymock.dsl.parser import parse_cut
from mockymock.splicer.naming import TallyRegistry
from mockymock.splicer.orchestrator import splice_program
from mockymock.splicer.source_map import collect_boundaries
from tests.integration._docker import requires_docker

ORDRPROC_CBL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ORDRPROC.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  ORD-AMOUNT          PIC 9(5)V99.
       01  WS-DISCOUNT-PCT     PIC 9V99.
       01  WS-NET-AMOUNT       PIC 9(5)V99.

       PROCEDURE DIVISION.
       PROCESS-ORDER.
           CALL "DISCRATE" USING ORD-AMOUNT WS-DISCOUNT-PCT
           COMPUTE WS-NET-AMOUNT =
               ORD-AMOUNT - (ORD-AMOUNT * WS-DISCOUNT-PCT).
"""

ORDRPROC_CUT = """\
TESTSUITE "ORDRPROC discount calculation"

TESTCASE "10% discount reduces net amount correctly"
    MOCK CALL "DISCRATE"
        MOVE 0.10 TO WS-DISCOUNT-PCT
    END-MOCK
    MOVE 100.00 TO ORD-AMOUNT
    PERFORM PROCESS-ORDER
    EXPECT WS-NET-AMOUNT TO BE 90.00
    VERIFY "DISCRATE" WAS CALLED ONCE

TESTCASE "Zero discount leaves amount unchanged"
    MOCK CALL "DISCRATE"
        MOVE 0.00 TO WS-DISCOUNT-PCT
    END-MOCK
    MOVE 50.00 TO ORD-AMOUNT
    PERFORM PROCESS-ORDER
    EXPECT WS-NET-AMOUNT TO BE 50.00
"""

# Two paragraphs, each with its own static CALL to a program that gets
# mocked. Regression test for a line-shift bug: splicing multiple CALL
# sites must not use stale (pre-splice) line numbers against a `lines`
# list that has already grown from an earlier splice -- otherwise later
# splices land on the wrong lines (observed: commenting out a paragraph
# header instead of the CALL statement it precedes).
TWOSITE_CBL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TWOSITE.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A                PIC 9(5).
       01  WS-B                PIC 9(5).
       01  WS-RATE             PIC 9V99.

       PROCEDURE DIVISION.
       PARA-ONE.
           CALL "DISCRATE" USING WS-A WS-RATE.

       PARA-TWO.
           CALL "DISCRATE" USING WS-B WS-RATE.
"""

TWOSITE_CUT = """\
TESTSUITE "TWOSITE both call sites mocked"

TESTCASE "PARA-ONE calls DISCRATE"
    MOCK CALL "DISCRATE"
        MOVE 0.25 TO WS-RATE
    END-MOCK
    MOVE 10 TO WS-A
    PERFORM PARA-ONE
    EXPECT WS-RATE TO BE 0.25

TESTCASE "PARA-TWO calls DISCRATE"
    MOCK CALL "DISCRATE"
        MOVE 0.50 TO WS-RATE
    END-MOCK
    MOVE 20 TO WS-B
    PERFORM PARA-TWO
    EXPECT WS-RATE TO BE 0.50
"""


# INVOKE has no registered statement parser: cobolparser drops it from the
# AST with success=True, errors=0, and a ParseResult.warnings entry (its
# 2026-07-07 silent-drop remediation). A scaffold or splice built from that
# AST would silently miss program behavior, so both commands refuse.
INVOKER_CBL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. INVOKER.

       PROCEDURE DIVISION.
       MAIN-PARA.
           INVOKE SOME-OBJECT "someMethod".
           DISPLAY "done".
"""

INVOKER_CUT = """\
TESTSUITE "INVOKER"

TESTCASE "display runs"
    PERFORM MAIN-PARA
"""


def test_generate_refuses_program_with_dropped_statements(tmp_path: Path, capsys):
    program = tmp_path / "INVOKER.cbl"
    program.write_text(INVOKER_CBL)
    output = tmp_path / "INVOKER.cut"

    exit_code = main(["generate", str(program), "-o", str(output)])

    assert exit_code == 1
    assert "PARSE_WARNING" in capsys.readouterr().out
    assert not output.exists()


@requires_docker
def test_run_refuses_program_with_dropped_statements(tmp_path: Path, capsys):
    program = tmp_path / "INVOKER.cbl"
    program.write_text(INVOKER_CBL)
    cut_file = tmp_path / "INVOKER.cut"
    cut_file.write_text(INVOKER_CUT)

    exit_code = main(["run", str(program), "--cut", str(cut_file)])

    assert exit_code == 1
    assert "PARSE_WARNING" in capsys.readouterr().out


def test_generate_writes_a_parseable_cut_file(tmp_path: Path):
    program = tmp_path / "ORDRPROC.cbl"
    program.write_text(ORDRPROC_CBL)
    output = tmp_path / "ORDRPROC.cut"

    exit_code = main(["generate", str(program), "-o", str(output)])

    assert exit_code == 0
    assert output.exists()
    assert 'MOCK CALL "DISCRATE"' in output.read_text()


@requires_docker
def test_run_passes_when_both_cases_are_correct(tmp_path: Path):
    program = tmp_path / "ORDRPROC.cbl"
    program.write_text(ORDRPROC_CBL)
    cut_file = tmp_path / "ORDRPROC.cut"
    cut_file.write_text(ORDRPROC_CUT)

    exit_code = main(["run", str(program), "--cut", str(cut_file)])

    assert exit_code == 0


@requires_docker
def test_run_fails_when_expectation_is_wrong(tmp_path: Path):
    program = tmp_path / "ORDRPROC.cbl"
    program.write_text(ORDRPROC_CBL)
    cut_file = tmp_path / "ORDRPROC.cut"
    cut_file.write_text(ORDRPROC_CUT.replace("TO BE 90.00", "TO BE 99.99"))

    exit_code = main(["run", str(program), "--cut", str(cut_file)])

    assert exit_code == 1


@requires_docker
def test_run_keep_sandbox_leaves_instrumented_source_on_disk(tmp_path: Path, capsys):
    """--keep-sandbox must survive a normal (successful) run: the sandbox
    directory and its instrumented .cbl stay on disk after `run` returns,
    and the kept path is printed so the user can find it."""
    program = tmp_path / "ORDRPROC.cbl"
    program.write_text(ORDRPROC_CBL)
    cut_file = tmp_path / "ORDRPROC.cut"
    cut_file.write_text(ORDRPROC_CUT)

    exit_code = main(["run", str(program), "--cut", str(cut_file), "--keep-sandbox"])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "mockymock run: keeping sandbox " in out

    kept_line = next(line for line in out.splitlines() if "keeping sandbox " in line)
    kept_dir = Path(kept_line.split("keeping sandbox ", 1)[1].strip())

    assert kept_dir.is_dir()
    instrumented_files = list(kept_dir.glob("*.cbl"))
    assert len(instrumented_files) == 1
    assert "ORDRPROC" in instrumented_files[0].read_text()


# Parses fine under cobolparser (no semantic name resolution) but cobc
# rejects it: WS-A is undefined -- a deliberate compile failure so the
# --verbose / --keep-sandbox "print the instrumented source path on
# failure" behavior has something real to trigger against.
BADCOMPILE_CBL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. BADCOMPILE.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-KNOWN            PIC 9(5).

       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE WS-UNDEFINED-FIELD TO WS-KNOWN.
"""

BADCOMPILE_CUT = """\
TESTSUITE "BADCOMPILE never compiles"

TESTCASE "runs MAIN-PARA"
    PERFORM MAIN-PARA
    EXPECT WS-KNOWN TO BE 0
"""


@requires_docker
def test_run_verbose_prints_instrumented_source_path_on_compile_failure(
    tmp_path: Path, capsys
):
    """--verbose alone (no --keep-sandbox) must still leave the printed
    instrumented-source path actionable: the sandbox has to be retained on
    compile failure whenever --verbose is set, or the path printed here
    points at an already-deleted file."""
    program = tmp_path / "BADCOMPILE.cbl"
    program.write_text(BADCOMPILE_CBL)
    cut_file = tmp_path / "BADCOMPILE.cut"
    cut_file.write_text(BADCOMPILE_CUT)

    exit_code = main(["run", str(program), "--cut", str(cut_file), "--verbose"])
    out = capsys.readouterr().out

    assert exit_code == 1
    assert "mockymock run: compile failed:" in out
    assert "mockymock run: instrumented source at " in out

    source_line = next(
        line for line in out.splitlines() if "instrumented source at " in line
    )
    instrumented_path = Path(source_line.split("instrumented source at ", 1)[1].strip())

    assert instrumented_path.is_file()
    assert "BADCOMPILE" in instrumented_path.read_text()


@requires_docker
def test_run_verbose_only_does_not_leave_sandbox_after_successful_run(
    tmp_path: Path,
):
    """--verbose must not leave sandbox cruft behind when compile+run
    succeed -- it's only retained long enough to make a compile-failure
    path printout actionable, not kept around unconditionally like
    --keep-sandbox."""
    from mockymock.runtime import docker_toolchain

    program = tmp_path / "ORDRPROC.cbl"
    program.write_text(ORDRPROC_CBL)
    cut_file = tmp_path / "ORDRPROC.cut"
    cut_file.write_text(ORDRPROC_CUT)

    docker_toolchain.WORK_ROOT.mkdir(parents=True, exist_ok=True)
    before = set(docker_toolchain.WORK_ROOT.glob("mockymock-*"))

    exit_code = main(["run", str(program), "--cut", str(cut_file), "--verbose"])

    after = set(docker_toolchain.WORK_ROOT.glob("mockymock-*"))

    assert exit_code == 0
    assert after - before == set()


def test_run_refuses_program_with_parse_errors(tmp_path: Path, capsys):
    program = tmp_path / "BAD.cbl"
    program.write_text("NOT EVEN VALID COBOL { } [ ]")
    cut_file = tmp_path / "BAD.cut"
    cut_file.write_text('TESTSUITE "X"\n\nTESTCASE "Y"\nPERFORM Z\n')

    exit_code = main(["run", str(program), "--cut", str(cut_file)])

    assert exit_code == 1
    assert "PARSE_ERROR" in capsys.readouterr().out


@requires_docker
def test_run_splices_both_call_sites_correctly(tmp_path: Path):
    """Regression test: two static CALL sites to the same mocked program,
    in two different paragraphs. Both must be spliced correctly -- if the
    line-shift bug regresses, the second splice comments out PARA-TWO's
    paragraph header, and PERFORM PARA-TWO fails to compile/resolve."""
    program = tmp_path / "TWOSITE.cbl"
    program.write_text(TWOSITE_CBL)
    cut_file = tmp_path / "TWOSITE.cut"
    cut_file.write_text(TWOSITE_CUT)

    exit_code = main(["run", str(program), "--cut", str(cut_file)])

    assert exit_code == 0


# One paragraph with TWO static CALLs to the SAME mocked program. Regression
# test for a double-counting bug: MockSurface.static_call_sites() yields one
# CallSite per physical CALL, all sharing paragraph_name "PARA-ONE" -- so a
# naive (site x statement-in-paragraph) nested loop matches every site
# against every statement in that paragraph, producing a span per pairing
# instead of a span per physical CALL (2 sites x 2 statements = 4 spans for
# 2 real CALLs). Observed effect before the fix: each CALL got double- or
# quadruple-commented and its dispatch block duplicated, so VERIFY "..."
# WAS CALLED ONCE would see the tally at 2x the real count.
SAMEPARA_CBL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SAMEPARA.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A                PIC 9(5).
       01  WS-B                PIC 9(5).
       01  WS-RATE             PIC 9V99.

       PROCEDURE DIVISION.
       PARA-ONE.
           CALL "DISCRATE" USING WS-A WS-RATE
           CALL "DISCRATE" USING WS-B WS-RATE.
"""

SAMEPARA_CUT = """\
TESTSUITE "SAMEPARA two calls in one paragraph"

TESTCASE "both calls mocked once each"
    MOCK CALL "DISCRATE"
        MOVE 0.25 TO WS-RATE
    END-MOCK
    PERFORM PARA-ONE
    EXPECT WS-RATE TO BE 0.25
    VERIFY "DISCRATE" WAS CALLED 2 TIMES
"""


def test_splice_call_sites_does_not_duplicate_same_program_calls_in_one_paragraph():
    """Runs for real regardless of cobc: exercises `splice_program`
    directly rather than going through compile+execute."""
    result = parse_cobol(SAMEPARA_CBL, filename="SAMEPARA.cbl")
    assert result.success, result.errors
    ast = result.ast
    surface = analyze(ast)

    suite = parse_cut(SAMEPARA_CUT)
    normalized = normalize_fixed_format(SAMEPARA_CBL.splitlines())
    lines = normalized.splitlines()
    boundaries = collect_boundaries(ast)

    spliced = splice_program(lines, boundaries, surface, suite, TallyRegistry(suite))
    spliced_text = "\n".join(spliced)

    # Exactly one tally increment per physical CALL (2 calls -> 2 increments),
    # not 4 (which the double-counting bug produced).
    assert spliced_text.count("ADD 1 TO UT-DISCRATE-TALLY") == 2
    # No statement line was commented out twice.
    assert "*>       *>" not in spliced_text
    assert "PARA-ONE." in spliced_text


@requires_docker
def test_run_verify_count_is_correct_for_two_calls_in_one_paragraph(tmp_path: Path):
    program = tmp_path / "SAMEPARA.cbl"
    program.write_text(SAMEPARA_CBL)
    cut_file = tmp_path / "SAMEPARA.cut"
    cut_file.write_text(SAMEPARA_CUT)

    exit_code = main(["run", str(program), "--cut", str(cut_file)])

    assert exit_code == 0


BOUNDARY_MIX_CBL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. BOUNDMIX.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT ORDER-FILE ASSIGN TO "ORDERS"
               ORGANIZATION IS LINE SEQUENTIAL.
           SELECT SORTED-FILE ASSIGN TO "SORTED"
               ORGANIZATION IS LINE SEQUENTIAL.
           SELECT SORT-WORK ASSIGN TO "SRTWRK".

       DATA DIVISION.
       FILE SECTION.
       FD  ORDER-FILE.
       01  ORDER-RECORD       PIC X(11).
       FD  SORTED-FILE.
       01  SORTED-RECORD      PIC X(11).
       SD  SORT-WORK.
       01  SORT-RECORD        PIC X(11).

       WORKING-STORAGE SECTION.
       01  WS-PGM-NAME        PIC X(8) VALUE "DISCRATE".
       01  WS-AMOUNT          PIC 9(5)V99.
       01  WS-RATE            PIC 9V99.
       01  WS-NAME            PIC X(10).

       PROCEDURE DIVISION.
       CALLS-STATIC.
           CALL "DISCRATE" USING WS-AMOUNT WS-RATE.

       CALLS-DYNAMIC.
           CALL WS-PGM-NAME USING WS-AMOUNT.

       SORTS-DATA.
           SORT SORT-WORK ON ASCENDING KEY SORT-RECORD
               USING ORDER-FILE GIVING SORTED-FILE.

       READS-A-FILE.
           READ ORDER-FILE
               AT END DISPLAY "EOF"
           END-READ.

       READS-CONSOLE.
           ACCEPT WS-NAME.
"""


def test_generate_reports_detected_unsupported_boundaries(tmp_path: Path, capsys):
    """The mock surface still detects boundaries no version can mock
    (SORT/MERGE family). generate must say so, not silently drop them --
    otherwise the scaffold looks like complete coverage of the program's
    boundary points when it isn't. File I/O, console ACCEPT, and (since
    the 2026-07-06 design) dynamic CALL are mockable and must NOT be
    reported."""
    program = tmp_path / "BOUNDMIX.cbl"
    program.write_text(BOUNDARY_MIX_CBL)
    output = tmp_path / "BOUNDMIX.cut"

    exit_code = main(["generate", str(program), "-o", str(output)])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "not mockable" in out
    assert "SORT/MERGE" in out
    assert "dynamic CALL" not in out
    assert "file I/O" not in out
    assert "console ACCEPT" not in out
    # The scaffold covers the static CALL, the dynamic CALL (bare key),
    # the READ, and the ACCEPT.
    scaffold = output.read_text()
    assert 'MOCK CALL "DISCRATE"' in scaffold
    assert "MOCK CALL WS-PGM-NAME" in scaffold
    assert "MOCK READ ORDER-FILE" in scaffold
    assert "MOCK ACCEPT WS-NAME" in scaffold


def test_generate_stays_quiet_when_everything_is_mockable(tmp_path: Path, capsys):
    program = tmp_path / "ORDRPROC.cbl"
    program.write_text(ORDRPROC_CBL)
    output = tmp_path / "ORDRPROC.cut"

    exit_code = main(["generate", str(program), "-o", str(output)])

    assert exit_code == 0
    assert "not mockable" not in capsys.readouterr().out


def test_splice_preserves_sentence_period_of_replaced_call():
    """When the mocked CALL is the last statement of its paragraph, its line
    carries the sentence-terminating period. The dispatch block that replaces
    it must end with a period too -- otherwise the sentence runs into the next
    paragraph header and cobc rejects the program ('PARA-TWO' undefined)."""
    result = parse_cobol(TWOSITE_CBL, filename="TWOSITE.cbl")
    assert result.success, result.errors
    ast = result.ast
    surface = analyze(ast)

    suite = parse_cut(TWOSITE_CUT)
    normalized = normalize_fixed_format(TWOSITE_CBL.splitlines())
    lines = normalized.splitlines()
    boundaries = collect_boundaries(ast)

    spliced = splice_program(lines, boundaries, surface, suite, TallyRegistry(suite))

    # Both CALLs were sentence-final, so both dispatch blocks must terminate
    # their sentence.
    end_evaluates = [
        line for line in spliced if line.strip().startswith("END-EVALUATE")
    ]
    assert len(end_evaluates) == 2
    assert all(line.rstrip().endswith("END-EVALUATE.") for line in end_evaluates)
