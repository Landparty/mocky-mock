"""A TESTCASE with several PERFORMs runs them in order, MOVEs between them
included, so a stateful program can be called the way its caller would
(the LEDGRPT field run had to seed the stale state by hand instead). The
program GOBACKs at the end of every call, so the neutralized terminator
must not cut the next call short."""

from pathlib import Path

from mockymock.cli.main import main
from tests.integration._docker import requires_docker

FIXTURES = Path(__file__).parent / "fixtures"


@requires_docker
def test_a_sequence_of_calls_sees_the_state_the_earlier_calls_left():
    exit_code = main(
        [
            "run",
            str(FIXTURES / "multi_call.cbl"),
            "--cut",
            str(FIXTURES / "multi_call.cut"),
        ]
    )
    assert exit_code == 0


def test_a_mock_no_call_reaches_is_refused(tmp_path, capsys):
    cut = tmp_path / "multi_call.cut"
    cut.write_text(
        'TESTSUITE "s"\n'
        'TESTCASE "c"\n'
        '    MOCK CALL "AUDIT"\n'
        "    END-MOCK\n"
        '    MOCK CALL "NEVER"\n'
        "    END-MOCK\n"
        "    PERFORM 0000-ENTRY\n"
        "    PERFORM 0000-ENTRY\n"
        "    EXPECT WS-CALLS TO BE 2\n",
        encoding="utf-8",
    )
    exit_code = main(["lint", str(FIXTURES / "multi_call.cbl"), "--cut", str(cut)])
    assert exit_code != 0
    assert 'MOCK CALL "NEVER" is not reached' in capsys.readouterr().out
