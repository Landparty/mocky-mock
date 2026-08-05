"""CLI behavior tests for `mockymock fixtures`."""

import json
from pathlib import Path

from mockymock.cli.main import main

from .test_bundle_surface import SOURCE

_FIXTUREDEMO = (
    Path(__file__).resolve().parents[2] / "examples" / "fixtures" / "FIXTUREDEMO.cbl"
)


def test_fixtures_prints_bundle_json(tmp_path, capsys):
    cbl = tmp_path / "BSMOKE.cbl"
    cbl.write_text(SOURCE, encoding="utf-8")
    rc = main(["fixtures", str(cbl), "--seed", "7", "--scenarios", "happy"])
    assert rc == 0
    bundle = json.loads(capsys.readouterr().out)
    assert bundle["bundle_version"] == 1
    assert bundle["seed"] == 7


def test_fixtures_parse_failure_exits_1(tmp_path, capsys):
    bad = tmp_path / "BAD.cbl"
    bad.write_text("not cobol at all", encoding="utf-8")
    rc = main(["fixtures", str(bad)])
    assert rc == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip()


def test_fixtures_rows_0_is_honored_not_treated_as_falsy(capsys):
    """--rows 0 must reach DataGeneratorOptions(rows=0), not fall through
    to the generator's own default via a truthy `if args.rows` check.
    FIXTUREDEMO's READ-ORDERS loop is the discriminating boundary: its
    generated sequence length tracks --rows directly, so a truthiness bug
    (0 treated as "no --rows given") is invisible on every other field but
    produces a full-length default sequence here instead of an empty one."""

    def read_sequence_len(rc: int) -> int:
        assert rc == 0
        bundle = json.loads(capsys.readouterr().out)
        for scenario in bundle["scenarios"]:
            for fixture in scenario["fixtures"]:
                if fixture["category"] == "READ":
                    return len(fixture["sequence"])
        raise AssertionError("no READ fixture found")

    rc_default = main(["fixtures", str(_FIXTUREDEMO), "--seed", "7"])
    default_len = read_sequence_len(rc_default)
    assert default_len > 0

    rc_zero = main(["fixtures", str(_FIXTUREDEMO), "--seed", "7", "--rows", "0"])
    assert read_sequence_len(rc_zero) == 0


# --- mockymock fixtures --copybook-path ------------------------------------

SOURCE_WITH_COPY = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. BCOPY.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
           COPY QTYREC.
       PROCEDURE DIVISION.
       MAIN-PARA.
           ACCEPT WS-QTY
           DISPLAY WS-QTY
           GOBACK.
"""


def test_fixtures_resolves_copybook_via_copybook_path(tmp_path, capsys):
    copybook_dir = tmp_path / "copybooks"
    copybook_dir.mkdir()
    (copybook_dir / "QTYREC.CPY").write_text(
        "       01  WS-QTY PIC 9(3).\n", encoding="utf-8"
    )
    cbl = tmp_path / "BCOPY.cbl"
    cbl.write_text(SOURCE_WITH_COPY, encoding="utf-8")
    rc = main(["fixtures", str(cbl), "--copybook-path", str(copybook_dir)])
    assert rc == 0
    bundle = json.loads(capsys.readouterr().out)
    assert bundle["bundle_version"] == 1


def test_fixtures_unresolved_copybook_exits_1_with_nothing_on_stdout(tmp_path, capsys):
    copybook_dir = tmp_path / "copybooks"
    copybook_dir.mkdir()  # empty -- QTYREC.CPY intentionally absent
    cbl = tmp_path / "BCOPY.cbl"
    cbl.write_text(SOURCE_WITH_COPY, encoding="utf-8")
    rc = main(["fixtures", str(cbl), "--copybook-path", str(copybook_dir)])
    assert rc == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip()
