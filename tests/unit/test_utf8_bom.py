"""Issue #198: a `.cut` saved as UTF-8 with a byte-order mark (PowerShell
5 `Out-File -Encoding utf8`, some editors) parses like one without."""

from mockymock._lines import read_utf8_source
from mockymock.dsl.parser import parse_cut

CUT = 'TESTSUITE "s"\r\nTESTCASE "c"\r\n    PERFORM P\r\n'


def test_read_drops_a_leading_bom_and_the_cut_parses(tmp_path):
    path = tmp_path / "BOM.cut"
    path.write_bytes(b"\xef\xbb\xbf" + CUT.encode("utf-8"))
    text = read_utf8_source(path)
    assert text.startswith("TESTSUITE")
    assert parse_cut(text).name == "s"


def test_rewrite_reads_keep_the_bom_to_round_trip_it(tmp_path):
    path = tmp_path / "BOM.cut"
    path.write_bytes(b"\xef\xbb\xbf" + CUT.encode("utf-8"))
    text = read_utf8_source(path, keep_newlines=True)
    assert text == "﻿" + CUT
    assert parse_cut(text).test_cases[0].name == "c"
