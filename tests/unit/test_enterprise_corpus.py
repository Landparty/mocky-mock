"""Every IBM Enterprise COBOL *program type*, through ``mockymock generate``.

``tests/fixtures/enterprise/`` mirrors cobol-parser's
``tests/samples/enterprise/`` corpus: one representative program per kind of
program an Enterprise COBOL shop compiles (batch, VSAM, CICS, IMS, DB2, MQ,
subprograms, nested programs, Report Writer, OO, XML/JSON, DECLARATIVES, LE
services, compiler directives, 6.x data, copybooks). This test pins what
mockymock does with each: which types scaffold a starter ``.cut`` and which
are refused, under which code -- so a program type silently changing sides
(a refusal disappearing, or a scaffold turning into a refusal) is caught,
and the matrix in ``docs/enterprise-program-types.md`` stays honest.

No Docker: only the static ``generate`` path runs here.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from cobolparser.models.program import CobolProgram

from mockymock.cli.main import main

#: The corpus exercises what cobol-parser's 2026-09-15 release added (OO
#: units, DECLARATIVES modelling, the 6.x data clauses, conditional
#: compilation by default, ...). On an older release those programs parse
#: with warnings and every outcome below reads PARSE_WARNING, which says
#: nothing about mockymock. `CobolProgram.program_attributes` shipped in
#: that release, so its absence identifies an older pin -- the same
#: capability-probe pattern test_fixture_bundle_contract.py uses.
PARSER_COVERS_ENTERPRISE_TYPES = hasattr(CobolProgram, "program_attributes")

pytestmark = pytest.mark.skipif(
    not PARSER_COVERS_ENTERPRISE_TYPES,
    reason=(
        "needs the cobol-parser release that parses every Enterprise program "
        "type cleanly (CobolProgram.program_attributes present); bump the pin "
        "in pyproject.toml once it is published"
    ),
)

CORPUS = Path(__file__).parent.parent / "fixtures" / "enterprise"
COPYBOOKS = CORPUS / "copybooks"

#: file stem -> (expected outcome, refusal code or None)
#:
#: "scaffold" means ``generate`` wrote a .cut file with at least one test
#: case; "empty" means it wrote one with none (the program has no mockable
#: boundary); "refused" means it exited non-zero with exactly that code.
EXPECTED: dict[str, tuple[str, str | None]] = {
    # -- scaffolds with test cases ------------------------------------------
    "BATCHSEQ": ("scaffold", None),  # SORT is refused only at run time
    "VSAMKSDS": ("scaffold", None),
    "IMSDLIB": ("scaffold", None),  # ENTRY 'DLITCBL' + PCB LINKAGE neutralized
    "EXECDLI": ("scaffold", None),
    "DB2BATCH": ("scaffold", None),
    "MQBATCH": ("scaffold", None),
    "LESERV": ("scaffold", None),
    "COPYREPL": ("scaffold", None),
    # -- scaffolds with nothing to mock -------------------------------------
    # no CALL / file I/O / EXEC / console ACCEPT boundary at all: pure
    # computation (COMPDIR, MODERN63), XML/JSON handling (XMLJSON) and
    # INVOKE (OOCLIENT -- not a boundary category mockymock knows)
    "COMPDIR": ("empty", None),
    "MODERN63": ("empty", None),
    "XMLJSON": ("empty", None),
    "OOCLIENT": ("empty", None),
    # -- refusals -------------------------------------------------------------
    # DFHRESP(...) / DFHVALUE(...) expand through the CICS translator's
    # condition table
    "CICSONLN": ("refused", "UNSUPPORTED_CICS_MACRO"),
    "CICSCHNL": ("refused", "UNSUPPORTED_CICS_MACRO"),
    # a default entry with its own PROCEDURE DIVISION USING (the translated
    # CICS form, an IMS MPP's PCB list, a DB2 stored procedure's parameter
    # list) is the general CALL-driving case mockymock does not drive yet
    "CICSLINK": ("refused", "UNSUPPORTED_LINKAGE_LAYOUT"),
    "IMSMPP": ("refused", "UNSUPPORTED_LINKAGE_LAYOUT"),
    "DB2SP": ("refused", "UNSUPPORTED_LINKAGE_LAYOUT"),
    # USE procedures run on I/O conditions no PERFORM/GO TO edge reaches
    "DECLARE": ("refused", "UNSUPPORTED_DECLARATIVES"),
    "RPTWRTR": ("refused", "UNSUPPORTED_DECLARATIVES"),
    # only the outermost unit is spliced and gated
    "NESTED": ("refused", "UNSUPPORTED_NESTED_PROGRAM"),
    "SUBPROG": ("refused", "UNSUPPORTED_NESTED_PROGRAM"),
    "OOCOBOL": ("refused", "UNSUPPORTED_NESTED_PROGRAM"),
}

_REFUSED_RE = re.compile(r"refused \(([A-Z_]+)\)")


def _params():
    return [pytest.param(name, id=name) for name in EXPECTED]


def test_corpus_and_expectations_agree():
    on_disk = {p.stem for p in CORPUS.glob("*.cbl")}
    assert on_disk == set(EXPECTED), (
        "tests/fixtures/enterprise and EXPECTED disagree -- keep the corpus "
        "identical to cobol-parser's tests/samples/enterprise"
    )


@pytest.mark.parametrize("name", _params())
def test_generate_outcome_per_program_type(name, tmp_path, capsys):
    outcome, code = EXPECTED[name]
    out_path = tmp_path / f"{name}.cut"
    rc = main(
        [
            "generate",
            str(CORPUS / f"{name}.cbl"),
            "--copybook-path",
            str(COPYBOOKS),
            "-o",
            str(out_path),
        ]
    )
    captured = capsys.readouterr()
    text = captured.out + captured.err
    if outcome == "scaffold":
        assert rc == 0, text
        assert out_path.exists(), text
        assert "TESTCASE" in out_path.read_text(encoding="utf-8")
    elif outcome == "empty":
        assert rc == 0, text
        assert out_path.exists(), text
        assert "wrote 0 test case(s)" in text
    else:
        assert rc != 0, text
        assert not out_path.exists()
        codes = _REFUSED_RE.findall(text)
        assert codes == [code], f"{name}: {codes} -- {text}"
