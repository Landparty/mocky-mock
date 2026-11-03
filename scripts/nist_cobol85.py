"""Create, record and replay generated suites over the NIST CCVS85 programs.

What LegacyLens "Create tests" does to each program of a load module, done
to the NIST COBOL-85 validation suite: the runner's `tests` job scaffolds
the suite (`mockymock generate --scenarios all`), fills its expected values
from a run (`mockymock run --record-expectations`) and plays it
(`--json-report`); then "Run tests" plays the recorded suite again, and it
must give the same result. Run this after a change to the generator, the
refusal gates or the splicer, and compare the summary with the last one
(examples/nist-cobol85/generated/README.md has the 2026-11-03 numbers).

The programs as cobol-parser ships them (`examples/cobol/`) are the raw
population file entries: NIST's EXEC85 still has to substitute the X-cards
(`XXXXX055` -> the printer file's name, `XXXXX084` -> a LABEL RECORDS
value, ...) and drop the optional-code lines (a letter in column 7) before
they compile. `expand` does that, with the values GnuCOBOL's own
tests/cobol85/EXEC85.conf.in uses; the expanded programs then run under
plain `cobc -x` and report "NO TEST(S) FAILED".

Usage:
    python scripts/nist_cobol85.py expand ../cobol-parser/examples/cobol nist/
    python scripts/nist_cobol85.py check nist/ --out results/ --jobs 4
    python scripts/nist_cobol85.py check nist/ NC113M IX301M --out results/

`check` needs a GnuCOBOL toolchain (Docker, or MOCKYMOCK_GNUCOBOL_HOME with
MOCKYMOCK_TOOLCHAIN=native). It writes `<out>/summary.json` and one folder
per program holding both packs (`create/`, `replay/`) and `result.json`.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

# X-card values, as GnuCOBOL's tests/cobol85/EXEC85.conf.in sets them. The
# file names only have to be distinct: mockymock mocks every file.
X_CARDS: dict[int, str] = {
    **{n: f'"XXXXX{n:03d}"' for n in range(1, 30)},
    30: '"INPUTQUEUE1"',
    31: '"INPUTKEY1"',
    32: '"OUTPUTQUEUE1"',
    33: '"OUTPUTKEY1"',
    34: '"INPUTQUEUE2"',
    35: '"OUTPUTQUEUE2"',
    36: '"INPUTKEY2"',
    37: '"OUTPUTKEY2"',
    38: '"QUEUE1"',
    39: '"QUEUE2"',
    40: '"QUEUE3"',
    41: '"QUEUE4"',
    42: '"TERM1"',
    43: '"TERM2"',
    47: '"."',
    48: '"../copyalt"',
    49: '"XXXXX049"',
    51: "SWITCH-1",
    52: "SWITCH-2",
    53: "MULTIPLE FILE TFIL",
    55: '"REPORT"',
    56: "SYSOUT",
    57: "SYSIN",
    60: '"XXXXX060"',
    61: '"XXXXX061"',
    62: '"XXXXX062"',
    63: '" $$()*+,-./0123456789;<=>ABCDEFGHIJKLMNOPQRSTUVWXYZ"',
    64: '"ZYXWVUTSRQPONMLKJIHGFEDCBA>=<;9876543210/.-,+*)($$ "',
    65: "1000",
    67: "1000",
    68: "64000",
    69: "SYSIN",
    70: "STANDARD-1",
    73: "FORMFEED",
    74: "OCLABELID",
    75: '"OCDUMMY"',
    76: '"OCDUMMY"',
    77: '"OCDUMMY"',
    81: '"12345678"',
    82: "GNU-Linux",
    83: "GNU-Linux",
    84: "    OMITTED",
    86: "PIC X(8)",
    90: '"A"',
    91: '"D"',
    92: '"XXXXX092"',
}

# EXEC85.conf.in's *BEGIN-UPDATE section: lines replaced by sequence number
# (corrections GnuCOBOL applies to the population file).
UPDATES: dict[str, dict[str, str]] = {
    **{
        name: {seq: f"{seq}     COMPUTE WS-NUM = FUNCTION {func} (4 0 5 3 7)."}
        for name, seq, func in [
            ("IF119A", "061200", "MAX"),
            ("IF120A", "050300", "MEAN"),
            ("IF121A", "050000", "MEDIAN"),
            ("IF122A", "052200", "MIDRANGE"),
            ("IF123A", "061500", "MIN"),
            ("IF132A", "049800", "RANGE"),
            ("IF137A", "053100", "STANDARD-DEVIATION"),
            ("IF138A", "049800", "SUM"),
            ("IF141A", "052500", "VARIANCE"),
        ]
    },
    "IF128A": {"054900": "054900     COMPUTE WS-INT = FUNCTION ORD-MAX (4 0 5 3 7)."},
    "IF129A": {"055200": "055200     COMPUTE WS-INT = FUNCTION ORD-MIN (4 0 5 3 7)."},
    "IF402M": {"005900": "005900", "008600": "008600"},
    "IX110A": {"012250": "012250 01  STATUS-TEST-10          PIC 9 VALUE ZERO."},
    "NC174A": {"065200": "065200"},
    "NC217A": {
        "051300": "051300     STRING  ID1-1 OF ID1-XN-X-25 (ID8-DU-2V0)",
        "051400": "051400             ID1-2 OF ID1-XN-X-25 (ID8-DU-2V0)",
        "051500": "051500             ID1-3 OF ID1-XN-X-25 (ID8-DU-2V0)",
        "051600": "051600             ID1-4 OF ID1-XN-X-25 (ID8-DU-2V0)",
        "051700": "051700             ID1-5 OF ID1-XN-X-25 (ID8-DU-2V0)",
        "051800": "051800             DELIMITED BY SIZE INTO ID7-XN-5",
        "051900": "051900             POINTER ID8-DU-2V0.",
        "052000": "052000     GO      TO STRING-TEST-4-1.",
    },
    "SM208A": {"057300": "057300     GO TO   REP-TEST-7-1."},
    "SQ106A": {
        seq: f"{seq}     GO TO   SEQ-TEST-RD-{para}-03."
        for seq, para in [
            ("114400", "15"),
            ("135600", "17"),
            ("148400", "18"),
            ("174000", "20"),
            ("228400", "24"),
            ("243700", "25"),
        ]
    },
}

TOML = 'source_root = "src"\ntest_root = "tests"\ncopybook_path = ["copybooks"]\nseed = 1\n'


def expand_line(line: str, updates: dict[str, str]) -> str | None:
    """One population-file line as EXEC85 writes it, or None when dropped."""
    line = line.rstrip("\r\n").ljust(80)
    if line[:6] in updates:
        line = updates[line[:6]].ljust(80)
    indicator = line[6]
    if indicator.isalpha() and indicator != "D":
        return None  # optional code, removed (*KILL-DELETIONS)
    if line[11:15] == "XXXX" and line[16:19].isdigit():
        text = X_CARDS.get(int(line[16:19]), "**** X-CARD UNDEFINED ****")
        if line[19] == " " and text.endswith("."):
            text = text[:-1]
        elif line[19] == "." and not text.endswith("."):
            text += "."
        line = line[:11] + text.ljust(61)[:61] + line[72:]
    return line.rstrip()


def expand(source: Path, target: Path) -> int:
    """Expand every .CBL/.CPY of `source` into `target`; how many."""
    target.mkdir(parents=True, exist_ok=True)
    count = 0
    for path in sorted([*source.glob("*.CBL"), *source.glob("*.CPY")]):
        updates = UPDATES.get(path.stem, {})
        lines = [
            expanded
            for raw in path.read_text(errors="replace").split("\n")
            if (expanded := expand_line(raw, updates)) is not None
        ]
        (target / path.name).write_text("\n".join(lines).rstrip("\n") + "\n")
        count += 1
    return count


def write_pack(
    folder: Path, nist: Path, name: str, record: bool, cut_text: str | None
) -> Path:
    """A LegacyLens tests-job pack for one program, as the backend builds it."""
    if folder.exists():
        shutil.rmtree(folder)
    for sub in ("src", "copybooks", "tests"):
        (folder / sub).mkdir(parents=True)
    for copybook in nist.glob("*.CPY"):
        shutil.copy(copybook, folder / "copybooks")
    shutil.copy(nist / f"{name}.CBL", folder / "src")
    (folder / "mockymock.toml").write_text(TOML)
    if cut_text is not None:
        (folder / "tests" / f"{name}.cut").write_text(cut_text)
    suite = {
        "entry": name,
        "program": f"src/{name}.CBL",
        "cut": f"tests/{name}.cut",
        "generate": f"mockymock generate src/{name}.CBL --scenarios all",
        "record": record,
    }
    manifest = {
        "version": 1,
        "kind": "tests",
        "load_module": name,
        "copybook_path": "copybooks",
        "suites": [suite],
    }
    (folder / "oracle.json").write_text(json.dumps(manifest))
    return folder


def statuses(suite: dict[str, Any]) -> dict[str, int]:
    cases = (suite.get("report") or {}).get("cases") or []
    return dict(Counter(str(case.get("status")) for case in cases))


def refusal_codes(suite: dict[str, Any]) -> list[str]:
    import re

    return sorted(set(re.findall(r"refused \(([A-Z_]+)\)", suite.get("log") or "")))


def check_program(nist: Path, name: str, out: Path, timeout: float) -> dict[str, Any]:
    """Create (generate, record, play) then replay one program's suite."""
    from mockymock.runner.jobs import run_pack

    created = run_pack(
        write_pack(out / name / "create", nist, name, True, None), timeout=timeout
    )["suites"][0]
    result: dict[str, Any] = {
        "program": name,
        "error": created.get("error"),
        "refused": refusal_codes(created),
        "create": statuses(created),
        "cases": (created.get("cut_text") or "").count("\nTESTCASE "),
    }
    if created.get("cut_text") and not created.get("error"):
        replayed = run_pack(
            write_pack(out / name / "replay", nist, name, False, created["cut_text"]),
            timeout=timeout,
        )["suites"][0]
        result["replay"] = statuses(replayed)
    (out / name / "result.json").write_text(json.dumps(created, indent=1))
    return result


def verdict(result: dict[str, Any]) -> str:
    if result["refused"] and not result["create"].get("passed"):
        return "refused"
    if result["error"]:
        return "error"
    create = result["create"]
    if set(create) == {"passed"} and result.get("replay") == create:
        return "green"
    return "failing"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    exp = sub.add_parser("expand", help="EXEC85-expand raw NIST programs")
    exp.add_argument("source", type=Path)
    exp.add_argument("target", type=Path)
    chk = sub.add_parser("check", help="create + replay generated suites")
    chk.add_argument("nist", type=Path, help="folder of expanded programs")
    chk.add_argument("programs", nargs="*", help="program names (default: all)")
    chk.add_argument("--out", type=Path, required=True)
    chk.add_argument("--jobs", type=int, default=4)
    chk.add_argument("--timeout", type=float, default=600)
    args = parser.parse_args(argv)

    if args.command == "expand":
        print(f"expanded {expand(args.source, args.target)} file(s)")
        return 0
    names = args.programs or sorted(p.stem for p in args.nist.glob("*.CBL"))
    args.out.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(args.jobs) as pool:
        results = list(
            pool.map(
                lambda n: check_program(args.nist, n, args.out, args.timeout), names
            )
        )
    for result in results:
        result["verdict"] = verdict(result)
        print(
            f"{result['program']:8} {result['verdict']:8} cases={result['cases']:3} "
            f"create={result['create']} replay={result.get('replay')} "
            f"{' '.join(result['refused'])}"
        )
    (args.out / "summary.json").write_text(json.dumps(results, indent=1))
    tally = Counter(result["verdict"] for result in results)
    print("summary:", dict(tally))
    return 0


if __name__ == "__main__":
    sys.exit(main())
