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

from mockymock.cli.main import main

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
    # DFHRESP(...) expanded to EIBRESP numbers as the CICS translator would;
    # CICSCHNL's only DFHVALUE sits inside an EXEC block the splicer replaces
    "CICSONLN": ("scaffold", None),
    "CICSCHNL": ("scaffold", None),
    # -- nothing to scaffold per paragraph (refused, no file written) --------
    # no CALL / file I/O / EXEC / console ACCEPT boundary at all: pure
    # computation (COMPDIR, MODERN63), XML/JSON handling (XMLJSON) and
    # INVOKE (OOCLIENT -- not a boundary category mockymock knows)
    "COMPDIR": ("empty", None),
    "MODERN63": ("empty", None),
    "XMLJSON": ("empty", None),
    "OOCLIENT": ("empty", None),
    # a default entry with its own PROCEDURE DIVISION USING (the translated
    # CICS form, an IMS MPP's PCB list, a DB2 stored procedure's parameter
    # list): the clause is blanked and the parameters folded into
    # WORKING-STORAGE for a .cut to MOVE into (2026-10-10, entry parameters)
    "CICSLINK": ("scaffold", None),
    "IMSMPP": ("scaffold", None),
    "DB2SP": ("scaffold", None),
    # -- refusals -------------------------------------------------------------
    # a mocked file statement's exception outcome PERFORMs the USE AFTER
    # procedure that applies (2026-11-03, analysis.declaratives)
    "DECLARE": ("scaffold", None),
    # USE BEFORE REPORTING: Report Writer GENERATE is mocked whole
    "RPTWRTR": ("refused", "UNSUPPORTED_DECLARATIVES"),
    # nested/stacked PROGRAM-IDs: the outermost unit is tested, a CALL to a
    # contained program mocked like any (2026-11-03)
    "NESTED": ("scaffold", None),
    "SUBPROG": ("scaffold", None),
    # an object-oriented class: only the outermost unit is spliced and gated
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
            "--per-paragraph",
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
        # A suite with no TESTCASE asserts nothing and fails `run` with
        # "0 run, 0 failed"; it is no longer written (issue #275).
        assert rc == 1, text
        assert not out_path.exists(), text
        assert "no test case to write" in text
    else:
        assert rc != 0, text
        assert not out_path.exists()
        codes = _REFUSED_RE.findall(text)
        assert codes == [code], f"{name}: {codes} -- {text}"
