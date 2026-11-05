"""A record copybook COPYed twice (`TXN-AMT OF IN-TXN` / `TXN-AMT OF
OUT-TXN`), and a name declared twice with different PICTUREs: EXPECTs on
the `OF`-qualified names compare, report and record like any other field.

Before the fix every such name had no PICTURE at all, so a numeric-edited
one compared as edited text, a failure showed the raw DISPLAY image, and
`--record-expectations` wrote that image as the golden, failing the next
run."""

from __future__ import annotations

from pathlib import Path

from mockymock.cli.main import main
from tests.integration._docker import requires_docker

FIXTURE = Path(__file__).parent / "fixtures" / "qualified_twice"
CBL = FIXTURE / "QUALTW.cbl"
CUT = FIXTURE / "QUALTW.cut"
COPYBOOKS = FIXTURE / "copybooks"


def _run(cut: Path, *extra: str) -> int:
    return main(
        ["run", str(CBL), "--cut", str(cut), "--copybook-path", str(COPYBOOKS)]
        + list(extra)
    )


@requires_docker
def test_qualified_expects_pass() -> None:
    assert _run(CUT) == 0


@requires_docker
def test_failures_show_the_value_in_console_and_junit(tmp_path: Path, capsys) -> None:
    cut = tmp_path / "QUALTW.cut"
    cut.write_text(
        CUT.read_text()
        .replace("OUT-TXN TO BE -24.68\n", "OUT-TXN TO BE -24.69\n", 1)
        .replace("TO BE 1.25", "TO BE 1.26")
    )
    junit = tmp_path / "junit.xml"
    assert _run(cut, "--junit-xml", str(junit)) == 1
    out = capsys.readouterr().out
    assert (
        "expected TXN-AMT OF OUT-TXN = -24.69, got -24.68 (displayed as -0002468)"
        in out
    )
    assert "expected RATE OF OUT-TOTALS = 1.26, got 1.25 (displayed as 125)" in out
    xml = junit.read_text()
    assert "got -24.68 (displayed as -0002468)" in xml
    assert "got 1.25 (displayed as 125)" in xml


@requires_docker
def test_recorded_goldens_pass_the_next_run(tmp_path: Path, capsys) -> None:
    cut = tmp_path / "QUALTW.cut"
    cut.write_text(
        "\n".join(
            (
                "    *> STUB EXPECT " + line.split("EXPECT ", 1)[1].split(" TO BE")[0]
                if "    EXPECT " in line
                else line
            )
            for line in CUT.read_text().splitlines()
        )
        + "\n"
    )
    assert _run(cut, "--record-expectations") == 0
    text = cut.read_text()
    assert "EXPECT TXN-AMT OF OUT-TXN TO BE -00024.68" in text
    assert "EXPECT TXN-QTY OF OUT-TXN TO BE 002.5" in text
    assert "EXPECT RATE OF OUT-TOTALS TO BE 1.25" in text
    capsys.readouterr()
    assert _run(cut) == 0, capsys.readouterr().out
