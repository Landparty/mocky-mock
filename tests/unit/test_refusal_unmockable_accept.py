"""`MOCK ACCEPT` aimed at an `ACCEPT ... FROM DATE/TIME/...` gets its own
refusal, not the generic reachability one.

`mock_surface` deliberately creates no boundary site for a system-source
ACCEPT: GnuCOBOL resolves DATE/TIME/DAY/COMMAND-LINE from the runtime
without touching stdin, so there is nothing to intercept and nothing that
could hang a test. Before UNMOCKABLE_ACCEPT_SOURCE existed, a `.cut`
mocking one of those fell through to `UNMATCHED_MOCK: ... does not match
any boundary site reachable from '<paragraph>'` -- which reads as a
call-graph reachability bug and sends the author off verifying reachability
by hand, when the real answer ("this ACCEPT variant is not mockable at
all") is a completely different problem.
"""

from cobolparser import parse_cobol

from mockymock.analysis.mock_surface import analyze
from mockymock.analysis.refusal import check_test_case
from mockymock.dsl.model import MockCategory, MockDirective, MockTestCase

SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ACCEPTS.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-TODAY           PIC 9(6).
       01  WS-NAME            PIC X(20).

       PROCEDURE DIVISION.
       START-HERE.
           ACCEPT WS-TODAY FROM DATE.
           ACCEPT WS-NAME.
"""


def _analyze():
    result = parse_cobol(SOURCE, filename="ACCEPTS.cbl")
    return result.ast, analyze(result.ast)


def _case(*mocks: MockDirective) -> MockTestCase:
    return MockTestCase(
        name="case", mocks=list(mocks), perform_target="START-HERE", verifications=[]
    )


def _reasons(*mocks: MockDirective):
    program, surface = _analyze()
    return check_test_case(surface, program, _case(*mocks))


def test_mocking_a_system_source_accept_refuses_with_its_own_code():
    reasons = _reasons(
        MockDirective(MockCategory.ACCEPT, "WS-TODAY"),
        MockDirective(MockCategory.ACCEPT, "WS-NAME"),
    )
    unmockable = [r for r in reasons if r.code == "UNMOCKABLE_ACCEPT_SOURCE"]
    assert len(unmockable) == 1
    message = unmockable[0].message
    assert "ACCEPT WS-TODAY FROM DATE" in message
    assert "not mockable at all" in message
    # The misleading half of the old message must not appear.
    assert "reachable from" not in message
    assert not [r for r in reasons if r.code == "UNMATCHED_MOCK"]


def test_a_genuinely_unmatched_accept_still_reports_unmatched_mock():
    """The carve-out is narrow: a MOCK ACCEPT naming nothing at all in the
    program is still an ordinary UNMATCHED_MOCK."""
    reasons = _reasons(
        MockDirective(MockCategory.ACCEPT, "WS-NAME"),
        MockDirective(MockCategory.ACCEPT, "WS-NO-SUCH-FIELD"),
    )
    codes = {r.code for r in reasons}
    assert "UNMATCHED_MOCK" in codes
    assert "UNMOCKABLE_ACCEPT_SOURCE" not in codes


def test_mocking_the_console_accept_alone_is_clean():
    """The console ACCEPT in the same paragraph is a real, mockable
    boundary -- mocking only it refuses nothing."""
    assert _reasons(MockDirective(MockCategory.ACCEPT, "WS-NAME")) == []
