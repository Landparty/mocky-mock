"""A GOBACK in the main paragraph is neutralized even though a paragraph
it PERFORMs physically follows a GO TO target: the GO TO only runs inside
`PERFORM 3000-POST THRU 3400-POST-EXIT`, so it returns from that PERFORM
and never falls past 3400-POST-EXIT into 4000-REPORT. Until 2026-10-25
every whole-program case was refused UNSUPPORTED_TERMINATOR_LAYOUT (the
LEDGRPT field run)."""

from pathlib import Path

from mockymock.cli.main import main
from tests.integration._docker import requires_docker

FIXTURES = Path(__file__).parent / "fixtures"


@requires_docker
def test_whole_program_case_through_a_closed_thru_range_passes():
    exit_code = main(
        [
            "run",
            str(FIXTURES / "thru_exit_goto.cbl"),
            "--cut",
            str(FIXTURES / "thru_exit_goto.cut"),
        ]
    )
    assert exit_code == 0
