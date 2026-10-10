"""End-to-end proof that `mockymock.splicer.linkage.neutralize` actually
fixes the crash, against the real GnuCOBOL toolchain -- not just that it
edits the expected lines (see tests/unit/test_splicer_linkage.py for that).
Mirrors the design spike in docs/2026-07-08-ims-linkage-support-design.md:
the un-neutralized shape crashes (SIGSEGV); the neutralized shape does not.
"""

import tempfile
from pathlib import Path

from cobolparser import parse_cobol
from cobolparser.preprocess import normalize_fixed_format

from mockymock.analysis.linkage import linkage_plan
from mockymock.runtime import docker_toolchain as dt
from mockymock.splicer.linkage import neutralize
from tests.integration._docker import requires_docker

SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. LKGSPIKE.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-DONE PIC X VALUE 'N'.

       LINKAGE SECTION.
       01  CUST-PCB-LNK.
           05  CUST-DBD-NAME     PIC X(08).
           05  CUST-STATUS       PIC X(02).

       PROCEDURE DIVISION.
       ENTRY 'DLITCBL' USING CUST-PCB-LNK.
       0000-MAIN.
           DISPLAY 'START'
           EVALUATE CUST-STATUS
               WHEN '  '
                   DISPLAY 'OK'
               WHEN OTHER
                   DISPLAY 'OTHER'
           END-EVALUATE
           DISPLAY 'END'
           STOP RUN.
"""


def _compile_and_run(source: str, name: str):
    dt.ensure_toolchain()
    dt.WORK_ROOT.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="test-linkage-splice-", dir=dt.WORK_ROOT))
    path = tmp / f"{name}.cbl"
    path.write_text(source, newline="\n")
    compiled = dt.compile_source(path)
    assert compiled.success, compiled.stderr
    return dt.run_binary(compiled.binary_path)


@requires_docker
def test_unneutralized_shape_crashes():
    """Dereferencing unbound LINKAGE SECTION storage is undefined behavior,
    not a guaranteed crash by the COBOL standard -- it segfaulted reliably
    against the pinned GnuCOBOL 3.2 build during the design spike, but if
    this ever flakes green on a different build, that's why: it isn't a
    hard invariant, just the observed, repeatable behavior of this
    toolchain."""
    executed = _compile_and_run(SOURCE, "lkgcrash")
    assert executed.exit_code != 0


@requires_docker
def test_neutralized_shape_runs_clean():
    result = parse_cobol(SOURCE, filename="LKGSPIKE.cbl")
    assert result.success
    lines = normalize_fixed_format(SOURCE.splitlines()).splitlines()
    plan = linkage_plan(result.ast)
    assert plan is not None

    neutralized = neutralize(lines, result.ast, plan)
    executed = _compile_and_run("\n".join(neutralized) + "\n", "lkgfixed")
    assert executed.exit_code == 0
    # The EVALUATE dereferenced the folded LINKAGE storage and control
    # reached the end: that is the proof. Which WHEN arm it took is NOT
    # asserted: since ecc7dbe compiles with `-std=mvs`, whose config sets
    # `defaultbyte: 0`, VALUE-less storage starts as LOW-VALUES (not
    # spaces), so CUST-STATUS matches WHEN OTHER. In a real `run` the
    # driver's UT-RESET-WORKING-STORAGE (linkage.extra_reset_lines) sets
    # it to SPACES before every case; this raw compile has no driver.
    assert executed.stdout.splitlines()[0] == "START"
    assert executed.stdout.splitlines()[-1] == "END"
