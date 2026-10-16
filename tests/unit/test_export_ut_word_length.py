"""#279: `export` wrote a UT-TESTSUITE- paragraph up to 60 characters long,
past IBM Enterprise COBOL's 30-character user-defined-word limit."""

import re
from pathlib import Path

import pytest

from mockymock.cli.main import main

_EXAMPLES = Path(__file__).resolve().parents[2] / "examples"
_UT_WORD_RE = re.compile(r"\bUT-[A-Z0-9-]*[A-Z0-9]")


@pytest.mark.parametrize(
    ("example", "program"), [("raterte", "RATERTE"), ("custinq", "CUSTINQ")]
)
def test_every_generated_word_in_export_fits_ibm_30_char_limit(
    tmp_path, example, program
):
    out = tmp_path / f"{program}.mainframe.cbl"
    exit_code = main(
        [
            "export",
            str(_EXAMPLES / example / f"{program}.cbl"),
            "--cut",
            str(_EXAMPLES / example / f"{program}.cut"),
            "--output",
            str(out),
        ]
    )
    assert exit_code == 0
    code_lines = [
        line[6:]
        for line in out.read_text().splitlines()
        if len(line) > 6 and line[6] not in "*-"
    ]
    words = {
        word
        for line in code_lines
        for word in _UT_WORD_RE.findall(re.sub(r'"[^"]*"', "", line.split("*>")[0]))
    }
    assert any(word.startswith("UT-TESTSUITE") for word in words)
    too_long = sorted(word for word in words if len(word) > 30)
    assert too_long == []
