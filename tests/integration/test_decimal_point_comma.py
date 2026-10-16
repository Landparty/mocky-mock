"""Issue #230, executed: a `DECIMAL-POINT IS COMMA` program compiles and
passes under `generate --with-data`, `run --record-expectations` and the
`run` after it. Every one of those steps used to write `1.25`-style
literals the program's own compiler setting reads as `1` and a period."""

from __future__ import annotations

from pathlib import Path

from mockymock.cli.main import main
from tests.integration._docker import requires_docker


@requires_docker
def test_comma_decimal_program_generates_records_and_reruns(
    tmp_path: Path, capsys
) -> None:
    from tests.unit.test_decimal_point_comma import COMMA_CBL

    source = tmp_path / "DPC.cbl"
    source.write_text(COMMA_CBL)
    cut = tmp_path / "DPC.cut"
    assert main(["generate", str(source), "--with-data", "-o", str(cut)]) == 0
    text = cut.read_text().replace(
        "    PERFORM 0000-MAIN\n",
        "    MOVE 100 TO WS-AMT\n    PERFORM 0000-MAIN\n    *> STUB EXPECT WS-OUT\n",
    )
    cut.write_text(text)
    assert main(["run", str(source), "--record-expectations"]) == 0
    recorded = cut.read_text()
    assert "EXPECT WS-OUT TO BE " in recorded
    golden = recorded.split("EXPECT WS-OUT TO BE ", 1)[1].split()[0]
    assert "," in golden and "." not in golden, golden
    capsys.readouterr()
    assert main(["run", str(source)]) == 0
    assert "1 run, 0 failed" in capsys.readouterr().out
