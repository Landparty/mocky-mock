"""Issue #245: a CICS LINK server's `IF EIBCALEN < LENGTH OF DFHCOMMAREA
EXEC CICS ABEND` guard was always taken by the generated happy path (the
reset zeroes EIBCALEN, and a mocked ABEND ends the run), so the scaffold's
own VERIFYs for what follows failed. Every generated case now starts with
the commarea a real LINK passes."""

from __future__ import annotations

from pathlib import Path

import pytest

ENTERPRISE = Path(__file__).resolve().parents[1] / "fixtures" / "enterprise"
SEED = "    MOVE LENGTH OF DFHCOMMAREA TO EIBCALEN"


def _generate(tmp_path, name: str, *flags: str) -> str:
    from mockymock.cli.main import main

    out = tmp_path / f"{name}.cut"
    args = ["generate", str(ENTERPRISE / f"{name}.cbl"), *flags, "-o", str(out)]
    assert main(args) == 0
    return out.read_text()


@pytest.mark.parametrize(
    "flags", [(), ("--with-data", "--seed", "1"), ("--per-paragraph",)]
)
def test_link_server_cases_pass_the_commarea(tmp_path, flags) -> None:
    lines = _generate(tmp_path, "CICSLINK", *flags).splitlines()
    performs = [i for i, line in enumerate(lines) if line.startswith("    PERFORM ")]
    assert performs
    for index in performs:
        assert lines[index - 1] == SEED


def test_first_time_path_of_a_pseudo_conversational_program_is_kept(
    tmp_path,
) -> None:
    # CICSONLN's `IF EIBCALEN = 0` sends its fresh map: a genuine path, not
    # an ABEND guard.
    assert "EIBCALEN" not in _generate(tmp_path, "CICSONLN")
