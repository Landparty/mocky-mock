"""A program or `.cut` that is not UTF-8 is reported as a problem by
collect, generate, fixtures and lint -- never a traceback.

Regression: bug hunt round 12."""

import json
import shutil
from pathlib import Path

from mockymock.cli.main import main

_REPO = Path(__file__).resolve().parents[2]


_CUSTINQ = _REPO / "examples" / "custinq" / "CUSTINQ.cbl"


# --- non-UTF-8 .cbl / .cut: a clean error, never a traceback -------------


def _cp1252_program(tmp_path: Path) -> Path:
    text = _CUSTINQ.read_text(encoding="utf-8").split("\n")
    text.insert(1, "      * Caf\u00e9 r\u00e9sum\u00e9")
    target = tmp_path / "CUSTINQ.cbl"
    target.write_bytes("\n".join(text).encode("cp1252"))
    return target


def _cp1252_cut(tmp_path: Path, name: str = "C2.cut") -> Path:
    cut = tmp_path / name
    cut.write_bytes(
        '*> caf\u00e9\nTESTSUITE "S"\nTESTCASE "t"\n    PERFORM 0000-MAIN\n'.encode(
            "cp1252"
        )
    )
    return cut


def test_collect_json_reports_a_non_utf8_cut_as_a_json_error(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    cut = _cp1252_cut(tmp_path)

    assert main(["collect", "--cut", str(cut), "--json"]) == 1

    payload = json.loads(capsys.readouterr().out)
    assert payload["version"] == 1
    assert "not valid UTF-8" in payload["error"]
    assert "C2.cut" in payload["error"]


def test_generate_reports_a_non_utf8_program_without_a_traceback(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    program = _cp1252_program(tmp_path)

    assert main(["generate", str(program), "-o", str(tmp_path / "out.cut")]) == 1

    out = capsys.readouterr().out
    assert out.startswith("mockymock generate: ")
    assert "not valid UTF-8" in out and "iconv" in out
    assert not (tmp_path / "out.cut").exists()


def test_fixtures_reports_a_non_utf8_program_on_stderr_only(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    program = _cp1252_program(tmp_path)

    assert main(["fixtures", str(program)]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "not valid UTF-8" in captured.err


def test_lint_reports_a_non_utf8_program_and_cut_as_problems(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    program = _cp1252_program(tmp_path)
    good_cut = tmp_path / "U.cut"
    good_cut.write_text('TESTSUITE "S"\nTESTCASE "t"\n    PERFORM 0000-MAIN\n')

    assert main(["lint", str(program), "--cut", str(good_cut)]) == 1
    assert "CUSTINQ.cbl is not valid UTF-8" in capsys.readouterr().out

    shutil.copy(_CUSTINQ, tmp_path / "GOOD.cbl")
    bad_cut = _cp1252_cut(tmp_path)
    assert main(["lint", str(tmp_path / "GOOD.cbl"), "--cut", str(bad_cut)]) == 1
    assert "C2.cut is not valid UTF-8" in capsys.readouterr().out
