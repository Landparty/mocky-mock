# Real-World COBOL E2E Examples — Design

Date: 2026-07-06
Status: approved for implementation

## Problem

The two existing worked examples (`examples/invupdt/`, `examples/ordrproc/`)
are hand-crafted teaching programs: INVUPDT is ~130 lines built to touch
every boundary category once; ORDRPROC is a ~20-line minimal single-CALL
demo. Both are useful for onboarding, but neither proves mockymock holds up
against COBOL that looks like production code — multiple DB2 cursors per
program, stateful CALL sequences that thread a connection handle across
several mocked calls, COPY-heavy WORKING-STORAGE, COMMIT/ROLLBACK error
branches. Goal: add a small set of genuinely realistic COBOL programs as
polished, documented, GnuCOBOL-verified e2e examples, proving depth rather
than expanding raw fixture count.

## Source

`legacy-application` (sibling repo in this workspace, `../legacy-application/`)
is a purpose-built "realistic enterprise batch system" corpus — 17 COBOL
programs (234–429 lines each) plus copybooks, already used for LegacyLens
parser e2e testing. Chosen over pulling in an external open-source mainframe
demo app (e.g. CardDemo) because it's already in-workspace (no licensing
review, no new external dependency, no network fetch in CI) and its
programs map directly onto mockymock's existing boundary categories (CALL,
file I/O, `EXEC SQL`) without needing CICS support mockymock hasn't been
proven against.

Programs are **copied** into mocky-mock (not symlinked/referenced across
repos) — CI only checks out mocky-mock + cobol-parser today
(`.github/workflows/ci.yml`), and copying keeps each example self-contained
and independently versioned from legacy-application's own evolution.

## Candidates

| Example | Source program | Boundary shape it proves |
|---|---|---|
| **DEPTMQP** | `legacy-application/cobol/DEPTMQP.cbl` (MQ deposit producer) | A *stateful CALL sequence*: `MQCONN → MQOPEN → (loop) MQPUT → MQCMIT → MQCLOSE → MQDISC`, each mocked call threading a connection/queue handle to the next, plus sequential file I/O (read input, write report). Proves mockymock beyond one-off static `CALL`s (ORDRPROC's only category). |
| **ACCTMNT** | `legacy-application/cobol/ACCTMNT.cbl` (account maintenance batch) | A `DECLARE CURSOR`/`OPEN`/`FETCH`-loop/`UPDATE`/`COMMIT`/`ROLLBACK` DB2 pattern with multiple distinct `EXEC SQL` prefixes in one program (richer than INVUPDT's single `UPDATE`), plus two external subprogram `CALL`s (assembler `ACCTVAL`, PL/1 `DATAVAL`). |
| **DEPTMQC** | `legacy-application/cobol/DEPTMQC.cbl` (MQ deposit consumer) | Mixes MQ (`MQGET` no-wait loop) and DB2 (`INSERT`) boundaries in one program with a *dual-commit* pattern — MQCMIT and DB2 COMMIT issued together, both rolled back together on failure. A structurally different MQ+SQL combination than ACCTMNT or DEPTMQP alone. |

**Stretch, conditional on a spike:** `ACCTPRG` (`legacy-application/cobol/ACCTPRG.cbl`,
IMS DL/I purge via `CALL 'CBLTDLI'`). Deferred because it (and `DEPTIMSM`)
declare PCB masks in `LINKAGE SECTION` behind `ENTRY 'DLITCBL' USING ...` —
mockymock's driver only ever `PERFORM`s paragraphs, never `CALL`s the
program, so it's unverified whether GnuCOBOL safely allocates storage for a
standalone program's `LINKAGE SECTION` under that access pattern. First
implementation task for this one: a throwaway spike compiling a minimal
`LINKAGE SECTION` program with no driving `CALL` under mockymock's GnuCOBOL
Docker image. If it doesn't compile/run cleanly, drop `ACCTPRG` from this
pass entirely rather than working around it here.

Not attempted: `DEPTIMSM` (same LINKAGE SECTION risk as ACCTPRG, plus dual
PCBs — more risk for the same unresolved question), and no CICS example
(not present anywhere in the source corpus).

## Structure

Mirrors the existing `examples/` convention (polished + README, distinct
from the terser `tests/integration/fixtures/` corpus):

```
examples/real-world/
├── README.md                     # provenance note, links to the 3 examples
├── DEPTMQP/
│   ├── DEPTMQP.cbl
│   ├── copybooks/{WSCOMMON,ERRORCD,MQMSG}.cpy
│   ├── DEPTMQP.cut
│   └── README.md
├── ACCTMNT/
│   ├── ACCTMNT.cbl
│   ├── copybooks/{WSCOMMON,ERRORCD,ACCTMAST}.cpy
│   ├── ACCTMNT.cut
│   └── README.md
└── DEPTMQC/
    ├── DEPTMQC.cbl
    ├── copybooks/{WSCOMMON,ERRORCD,MQMSG}.cpy
    ├── DEPTMQC.cut
    └── README.md
```

`mockymock run <PROGRAM>.cbl --cut <PROGRAM>.cut --copybook-path copybooks`
is the run invocation for each, matching the existing `--copybook-path`
mechanism proven by `tests/integration/fixtures/copybook_example/`.

Each `.cut` mocks every boundary the program's reachable paths hit
(`MOCK CALL "<name>"` per external subprogram, `MOCK SQL "<prefix>"` per
distinct DB2 statement, `MOCK OPEN|READ|WRITE|CLOSE <name>` for file I/O),
with at least one happy-path `TESTCASE` and one error-path `TESTCASE`
(non-`MQCC-OK` completion code / negative `SQLCODE` forcing the program's
own rollback branch) per program — the same success/failure pairing
INVUPDT's README calls out.

## Adaptation policy

Programs are copied close to verbatim — realism is the point — but where a
program relies on syntax only a mainframe precompiler would have stripped
before a native COBOL compiler ever saw it, the minimum necessary trim is
made and called out explicitly in that example's README as a documented
deviation from the source file. One known instance going in:

- **ACCTMNT** declares one DB2 host variable with a bare
  `INDICATOR IS HV-RATE-IND-IND` clause directly in `WORKING-STORAGE`
  (outside any `EXEC SQL` block). This is DB2-precompiler-only syntax;
  GnuCOBOL has no precompiler pass and mockymock's `sqlca.py` only
  transforms text inside `EXEC SQL ... END-EXEC` markers, so this clause
  would fail to parse as-is. Fix: drop the `INDICATOR IS` clause on that
  one field (the nullable-column case it supports isn't exercised by this
  example's test cases anyway), documented in `ACCTMNT/README.md`.

Any other adaptation needed to get a candidate compiling is expected to be
similarly small (e.g. a `STEPLIB`/JCL-only reference in a comment needs no
change since comments aren't compiled). If a candidate turns out to need
substantial rewriting to compile, that's a signal to swap it for a
different corpus program rather than force it in — implementation should
flag this rather than silently reshaping the program beyond a documented
one- or two-line trim.

If running one of these programs through the full pipeline surfaces an
actual mockymock engine bug (not just a compileability trim), that becomes
its own follow-up design — not silently folded into this one.

## Testing

One integration test file per example under `tests/integration/`
(`test_realworld_deptmqp_example.py`, `test_realworld_acctmnt_example.py`,
`test_realworld_deptmqc_example.py`), following the exact pattern of
`test_invupdt_example.py`: `@requires_docker`, invokes `mockymock run` via
the CLI with `--copybook-path`, asserts `exit_code == 0`. These join the
existing `tests/ -v` run — no new CI wiring needed since the integration
tier already self-skips without Docker and GnuCOBOL is Docker-only in CI as
today.

## Documentation updates

- `.okf/testing.md`: new subsection alongside the existing INVUPDT/ORDRPROC
  write-up, with the same boundary-table format, for the three real-world
  examples; refresh its `timestamp`.
- `.okf/log.md`: dated entry noting the addition.
- Top-level `README.md`: one line pointing at `examples/real-world/`.
- `examples/real-world/README.md`: provenance (adapted from
  `legacy-application`, workspace-sibling repo — not third-party code),
  and a one-line pointer to each of the three sub-READMEs.

## Out of scope

- No changes to mockymock's splicer/analysis/refusal engine unless a real
  bug surfaces while wiring these examples up.
- No CICS example (absent from the source corpus).
- `ACCTPRG`/IMS only proceeds if its `LINKAGE SECTION` spike passes; no
  fallback engine work to make it pass artificially.
- No changes to `legacy-application` itself — this is a one-directional
  copy.
