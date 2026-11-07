"""Tests for mockymock.mutation.runner's execution classification.

_classify_execution reduces one run's exit code + parsed stdout to a
(status, detail) pair -- split out of _run_suite_once specifically so this
logic is testable without a real compile/run (see its docstring)."""

from mockymock.mutation.runner import _classify_execution
from mockymock.report.results import parse_stdout
from mockymock.runtime.executor import ExecutionResult

CLEAN_STDOUT = (
    "__MOCKYMOCK__ TESTSUITE: s\n"
    "__MOCKYMOCK__ CASE 001 START: c\n"
    "__MOCKYMOCK__ CASE 001 END\n"
    "__MOCKYMOCK__ SUMMARY: RUN=1 FAILURES=0\n"
)

FAILING_STDOUT = (
    "__MOCKYMOCK__ TESTSUITE: s\n"
    "__MOCKYMOCK__ CASE 001 START: c\n"
    "__MOCKYMOCK__ CASE 001 FAIL: expected WS-X = 1, got 9\n"
    "__MOCKYMOCK__ CASE 001 END\n"
    "__MOCKYMOCK__ SUMMARY: RUN=1 FAILURES=1\n"
)

CRASHED_STDOUT = "__MOCKYMOCK__ TESTSUITE: s\n__MOCKYMOCK__ CASE 001 START: c\n"


def test_clean_exit_and_all_passed_is_passed():
    execution = ExecutionResult(exit_code=0, stdout=CLEAN_STDOUT, stderr="")
    status, detail = _classify_execution(execution, parse_stdout(CLEAN_STDOUT))
    assert (status, detail) == ("passed", "")


def test_case_failure_reason_is_used_verbatim():
    execution = ExecutionResult(exit_code=1, stdout=FAILING_STDOUT, stderr="")
    status, detail = _classify_execution(execution, parse_stdout(FAILING_STDOUT))
    assert status == "failed"
    assert "expected WS-X = 1, got 9" in detail


def test_crashed_case_names_the_case():
    execution = ExecutionResult(exit_code=139, stdout=CRASHED_STDOUT, stderr="")
    status, detail = _classify_execution(execution, parse_stdout(CRASHED_STDOUT))
    assert status == "failed"
    assert "'c' crashed" in detail


def test_duplicate_case_starts_are_named_not_blamed_on_exit_code():
    """Audit finding F28: a duplicate CASE START anomaly makes all_passed
    False with a clean exit code and no individual case failure/crash --
    the old fallback reported this as "binary exited 0", which is true
    but not the reason, and reads as if the binary itself misbehaved.
    Both occurrences cleanly START/END here (unlike an orphaning
    collision) specifically so neither case's own crashed/failure_reasons
    check can explain the anomaly first -- isolating the duplicate-start
    branch itself."""
    stdout = (
        "__MOCKYMOCK__ TESTSUITE: s\n"
        "__MOCKYMOCK__ CASE 001 START: first\n"
        "__MOCKYMOCK__ CASE 001 END\n"
        "__MOCKYMOCK__ CASE 001 START: second\n"
        "__MOCKYMOCK__ CASE 001 END\n"
        "__MOCKYMOCK__ SUMMARY: RUN=2 FAILURES=0\n"
    )
    execution = ExecutionResult(exit_code=0, stdout=stdout, stderr="")
    suite_result = parse_stdout(stdout)
    assert suite_result.duplicate_case_starts  # precondition
    assert not any(c.crashed or c.failure_reasons for c in suite_result.results)
    status, detail = _classify_execution(execution, suite_result)
    assert status == "failed"
    assert "binary exited" not in detail
    assert "duplicate" in detail.lower()


def test_orphan_failure_is_named_not_blamed_on_exit_code():
    stdout = CLEAN_STDOUT + "__MOCKYMOCK__ CASE 007 FAIL: mystery\n"
    execution = ExecutionResult(exit_code=0, stdout=stdout, stderr="")
    suite_result = parse_stdout(stdout)
    assert suite_result.all_passed is False
    status, detail = _classify_execution(execution, suite_result)
    assert status == "failed"
    assert "binary exited" not in detail
    assert "orphan" in detail.lower() or "no matching" in detail.lower()


def test_zero_tests_run_is_named_not_blamed_on_exit_code():
    stdout = "__MOCKYMOCK__ TESTSUITE: s\n__MOCKYMOCK__ SUMMARY: RUN=0 FAILURES=0\n"
    execution = ExecutionResult(exit_code=0, stdout=stdout, stderr="")
    status, detail = _classify_execution(execution, parse_stdout(stdout))
    assert status == "failed"
    assert "binary exited" not in detail


def test_nonzero_exit_with_no_other_explanation_still_cites_the_exit_code():
    """The exit code remains a legitimate, honest explanation when
    nothing else does: every case genuinely passed (suite_result.all_passed
    is True), so the process itself exiting nonzero -- not any test
    outcome -- really is the whole story. This fallback isn't being
    removed, just no longer reached when it would be misleading."""
    execution = ExecutionResult(exit_code=139, stdout=CLEAN_STDOUT, stderr="")
    suite_result = parse_stdout(CLEAN_STDOUT)
    assert suite_result.all_passed  # precondition: nothing else can explain it
    status, detail = _classify_execution(execution, suite_result)
    assert status == "failed"
    assert detail == "binary exited 139"


def test_compile_stillborn_detail_is_the_error_not_the_paragraph_context():
    """cobc's first stderr line is `<sandbox path>: in paragraph 'X':`,
    which says nothing about why the mutant did not compile."""
    from mockymock.mutation.runner import _compile_error_detail

    stderr = (
        "/root/.mockymock/work/mockymock-x/instrumented_M.cbl: "
        "in paragraph 'MAIN-PARA':\n"
        "/root/.mockymock/work/mockymock-x/instrumented_M.cbl:12: error: "
        "syntax error, unexpected Identifier\n"
    )
    assert _compile_error_detail(stderr) == (
        "error: syntax error, unexpected Identifier"
    )


def test_compile_stillborn_detail_falls_back_to_first_line_then_default():
    from mockymock.mutation.runner import _compile_error_detail

    assert _compile_error_detail("cobc: something odd\nmore\n") == (
        "cobc: something odd"
    )
    assert _compile_error_detail("  \n") == "compile failed"
