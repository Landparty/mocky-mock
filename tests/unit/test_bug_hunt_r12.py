"""Regression tests for bug hunt round 12. Each test reproduces one defect
found (and fixed) in this round; see the commit message for the list."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from mockymock.cli.ai_mode import resolve_mode
from mockymock.cli.config import MockymockConfig
from mockymock.cli.main import _collect_boundaries, main
from mockymock.debug.gdb_session import ResultRecord, parse_mi_line
from mockymock.debug.variable_map import (
    _unquote_c_string,
    parse_local_header,
    read_variable,
)
from mockymock.splicer.sqlca import transform_data_division_exec

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


# --- generate --fill keeps a CRLF .cut CRLF -------------------------------


def test_fill_preserves_crlf_line_endings(tmp_path, monkeypatch, capsys):
    """read_text() translated CRLF to LF, so the CRLF check was dead and a
    CRLF .cut came back LF on POSIX (and, written without newline="", an
    LF join would have become CRLF on Windows regardless of the input)."""
    monkeypatch.chdir(tmp_path)
    shutil.copy(_CUSTINQ, tmp_path / "CUSTINQ.cbl")
    cut = tmp_path / "CUSTINQ.cut"
    cut.write_bytes(
        b'TESTSUITE "S"\r\n\r\nTESTCASE "t"\r\n'
        b"    PERFORM 1000-LOOKUP-CUSTOMER\r\n"
        b'    EXPECT WS-INQUIRY-STATUS TO BE "FOUND"\r\n'
    )

    assert main(["generate", str(tmp_path / "CUSTINQ.cbl"), "--fill", str(cut)]) == 0

    written = cut.read_bytes()
    assert b'MOCK CICS "READ"' in written
    assert b"\r\r\n" not in written
    assert written.count(b"\n") == written.count(b"\r\n")


def test_fill_writes_without_newline_translation(tmp_path, monkeypatch):
    """The in-place write must not let the platform translate "\\n"
    (Windows would turn the CRLF join into CR CR LF)."""
    monkeypatch.chdir(tmp_path)
    shutil.copy(_CUSTINQ, tmp_path / "CUSTINQ.cbl")
    cut = tmp_path / "CUSTINQ.cut"
    cut.write_bytes(
        b'TESTSUITE "S"\r\nTESTCASE "t"\r\n    PERFORM 1000-LOOKUP-CUSTOMER\r\n'
    )
    calls: list[dict] = []
    real_write_text = Path.write_text

    def spy(self, data, *args, **kwargs):
        if self == cut:
            calls.append(kwargs)
        return real_write_text(self, data, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", spy)
    assert main(["generate", str(tmp_path / "CUSTINQ.cbl"), "--fill", str(cut)]) == 0
    assert calls and all(call.get("newline") == "" for call in calls)


# --- debugger: gdb's octal escapes are bytes, repeat blocks are values ----


def test_octal_escaped_utf8_decodes_as_one_character():
    # Verbatim gdb 15 MI output for a `cob_u8_t[8]` holding "Café   ",
    # C locale (gdb escapes each UTF-8 byte in the value text) ...
    c_locale = parse_mi_line('^done,value="\\"Caf\\\\303\\\\251   \\""\n')
    # ... and C.UTF-8 (the value is raw UTF-8, MI escapes the bytes).
    utf8_locale = parse_mi_line('^done,value="\\"Caf\\303\\251   \\""\n')

    assert _unquote_c_string(c_locale.payload["value"]) == "Caf\u00e9   "
    assert utf8_locale.payload["value"] == '"Caf\u00e9   "'
    assert _unquote_c_string(utf8_locale.payload["value"]) == "Caf\u00e9   "


def test_non_utf8_escaped_byte_still_decodes_to_its_code_point():
    assert _unquote_c_string('"\\377AB"') == "\u00ffAB"
    assert _unquote_c_string('"\\001ABC"') == "\x01ABC"


@pytest.mark.parametrize(
    ("gdb_value", "expected"),
    [
        # All verbatim from gdb 15 `-data-evaluate-expression` of a
        # `cob_u8_t[N]` buffer (default `print repeats` threshold of 10).
        ("\"JANE SMITH\", ' ' <repeats 20 times>", "JANE SMITH" + " " * 20),
        ("' ' <repeats 30 times>", " " * 30),
        ("'\\000' <repeats 29 times>", "\x00" * 29),
        ("'\\377' <repeats 30 times>", "\u00ff" * 30),
        ("''' <repeats 12 times>, \"\\\\\\\"xy\"", "'" * 12 + '\\"xy'),
        (
            "'A' <repeats 12 times>, \"\\303\\251\\303\\251\"",
            "A" * 12 + "\u00e9\u00e9",
        ),
    ],
)
def test_gdb_repeat_blocks_are_decoded(gdb_value, expected):
    assert _unquote_c_string(gdb_value) == expected


def test_truncated_gdb_string_is_not_decoded():
    assert _unquote_c_string('"abc"...') is None


def test_plain_pic_x_buffer_with_trailing_spaces_is_alphanumeric():
    class _Session:
        def send(self, command: str):
            if command == "-data-evaluate-expression (int)(b_8).attr->type":
                return [
                    ResultRecord("error", {"msg": "There is no member named attr."})
                ]
            if command == "-data-evaluate-expression b_8":
                return [
                    ResultRecord(
                        "done", {"value": "\"JANE SMITH\", ' ' <repeats 20 times>"}
                    )
                ]
            raise AssertionError(command)

    value = read_variable(_Session(), "WS-CUST-NAME", "b_8")

    assert value.kind == "alphanumeric"
    assert value.decoded == "JANE SMITH" + " " * 20


def test_alphanumeric_field_memory_is_decoded_as_utf8():
    raw = "Caf\u00e9".encode()

    class _Session:
        def send(self, command: str):
            answers = {
                "-data-evaluate-expression (int)(f_9).attr->type": "33",
                "-data-evaluate-expression (int)(f_9).attr->digits": "0",
                "-data-evaluate-expression (int)(f_9).attr->scale": "0",
                "-data-evaluate-expression (int)(f_9).attr->flags": "0",
                "-data-evaluate-expression (f_9).size": str(len(raw)),
                "-data-evaluate-expression (long)(f_9).data": "4096",
                "-data-evaluate-expression f_9": "{size = 5, ...}",
            }
            if command in answers:
                return [ResultRecord("done", {"value": answers[command]})]
            if command == f"-data-read-memory-bytes 4096 {len(raw)}":
                return [ResultRecord("done", {"memory": [{"contents": raw.hex()}]})]
            raise AssertionError(command)

    value = read_variable(_Session(), "WS-NAME", "f_9")

    assert value.kind == "alphanumeric"
    assert value.decoded == "Caf\u00e9"


# --- debugger: .c.l.h names are cobc's bare f->name -----------------------

_DUPLICATE_HEADER = """\
/* Data storage */
static cob_u8_t	b_8[10] __attribute__((aligned));	/* GRP-A */
static cob_u8_t	b_11[10] __attribute__((aligned));	/* GRP-B */
static cob_u8_t	b_14[4] __attribute__((aligned));	/* WS_TOTAL */

/* Fields (local) */
static cob_field f_9	= {5, b_8 + 5, &a_1};	/* WS-NAME */
static cob_field f_12	= {5, b_11 + 5, &a_1};	/* WS-NAME */
static cob_field f_14	= {4, b_14, &a_2};	/* WS_TOTAL */
"""


def test_same_named_items_are_both_listed():
    """cobc's comment is the unqualified name (cobc/codegen.c writes
    `/* %s */` with f->name): WS-NAME OF GRP-A and WS-NAME OF GRP-B used
    to collapse into one entry showing GRP-B's field."""
    table = parse_local_header(_DUPLICATE_HEADER)

    assert table["WS-NAME"] == "f_9"
    assert table["WS-NAME (2)"] == "f_12"


def test_underscore_names_are_mapped_and_prefer_their_field_wrapper():
    """GnuCOBOL words may contain `_` (cobc/scanner.l's word pattern)."""
    table = parse_local_header(_DUPLICATE_HEADER)

    assert table["WS_TOTAL"] == "f_14"


# --- EXEC SQL INCLUDE of a copybook cobol-parser refuses to expand --------


def test_circular_sql_include_member_refuses_instead_of_raising(tmp_path):
    (tmp_path / "SELFREF.cpy").write_text(
        "       01  WS-A PIC X.\n       COPY SELFREF.\n"
    )
    lines = [
        "IDENTIFICATION DIVISION.",
        "PROGRAM-ID. P.",
        "DATA DIVISION.",
        "WORKING-STORAGE SECTION.",
        "    EXEC SQL INCLUDE SELFREF END-EXEC.",
        "01  WS-X PIC X.",
        "PROCEDURE DIVISION.",
    ]

    _, reasons = transform_data_division_exec(lines, copybook_paths=[str(tmp_path)])

    assert [r.code for r in reasons] == ["UNRESOLVED_COPYBOOK"]
    assert "SELFREF" in reasons[0].message


# --- ai_mode provenance ---------------------------------------------------


def test_ai_mode_origin_is_the_file_that_set_it(tmp_path):
    toml = tmp_path / "mockymock.toml"
    yml = tmp_path / "cobol.yml"
    config = MockymockConfig(
        source=toml,
        sources=(yml, toml),
        seed=3,
        ai_mode="hands-off",
        ai_mode_source=yml,
    )

    assert resolve_mode(config).source == yml


def test_load_config_records_where_ai_mode_came_from(tmp_path):
    pytest.importorskip("cobolparser.config")
    from mockymock.cli.config import load_config

    (tmp_path / "cobol.yml").write_text("mockymock:\n  ai_mode: hands-off\n")
    (tmp_path / "mockymock.toml").write_text("seed = 3\n")

    config = load_config(tmp_path)

    assert config.source == tmp_path / "mockymock.toml"
    assert resolve_mode(config).source == (tmp_path / "cobol.yml").resolve()
    assert resolve_mode(config).mode == "hands-off"


# --- collect --boundaries reports lines of the .cbl, not the expansion ----

_COPY_PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. P.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       COPY WSREC.
       01  WS-X PIC X.
       PROCEDURE DIVISION.
       0000-MAIN.
           CALL "SUBA" USING WS-X
           GOBACK.
"""


def test_collect_boundaries_lines_are_program_lines(tmp_path):
    from cobolparser.preprocess import expand_copybooks

    books = tmp_path / "copybooks"
    books.mkdir()
    (books / "WSREC.cpy").write_text(
        "".join(f"       01  WS-{c} PIC X.\n" for c in "ABCD")
    )
    program = tmp_path / "P.cbl"
    program.write_text(_COPY_PROGRAM)
    if not expand_copybooks(
        _COPY_PROGRAM, copybook_paths=[str(books)], preserve_source_locations=True
    ).source_location_map:
        pytest.skip("installed cobol-parser does not fill in a source map")

    boundaries = _collect_boundaries(program, [str(books)])

    assert [(b["label"], b["line"]) for b in boundaries] == [("CALL", 9)]
