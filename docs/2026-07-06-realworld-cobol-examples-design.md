# Real-World COBOL E2E Examples — Design

Date: 2026-07-06
Status: approved for implementation (revised after spiking all three candidates
against real GnuCOBOL — see "Revision" below)

## Revision (post-spike)

The original design below picked three candidates: DEPTMQP, ACCTMNT,
DEPTMQC. Spiking all three end-to-end against the real mockymock CLI +
Docker/GnuCOBOL toolchain (not just read through) found:

- **DEPTMQP** and **DEPTMQC**: fully proven. Both compile and run correctly
  end-to-end through `mockymock run` with hand-written `.cut` suites,
  documented below in "Candidates (final)".
- **ACCTMNT**: blocked by two separate, real gaps, not mere compileability
  trims:
  1. Its WORKING-STORAGE `EXEC SQL DECLARE ACCT_CURSOR CURSOR FOR ... END-EXEC`
     isn't recognized by mockymock's `sqlca.py` (only `DECLARE ... TABLE` is)
     — whole-file refusal before any test case runs. A one-line fix was
     spiked and confirmed working, but is **not included in this plan** —
     filed as a follow-up (see "Follow-ups filed" below) since it has no
     example left to exercise it once ACCTMNT is dropped.
  2. A deeper, separate bug in the sibling **cobol-parser** dependency (not
     mockymock): it silently drops at least two of ACCTMNT's own EXEC SQL
     statements (`2100-PROCESS-RATE-CHANGE`'s UPDATE, `2230-POST-FEE-
     TRANSACTION`'s INSERT/UPDATE) from the AST with no parse error, so
     mockymock's splicer never sees them to remove them — raw EXEC SQL text
     reaches GnuCOBOL and fails to compile, for **any** test case, since
     GnuCOBOL compiles the whole file regardless of which paragraph is
     targeted. The exact trigger wasn't isolated (structurally similar
     statements in the same file, and in DEPTMQC, parse correctly) — fixing
     it is out of scope here (different repo, unscoped effort).

  **Decision: ACCTMNT is dropped from this pass.** DEPTMQP + DEPTMQC alone
  still deliver the design's core goal — proving mockymock against
  production-shaped complexity — via a stateful multi-call MQ sequence and a
  mixed MQ+DB2 program with a dual-commit/backout pattern. This was put to
  the user explicitly and confirmed.

**Follow-ups filed** (separate spawned sessions, not part of this plan):
- cobol-parser AST gap (task_c5e3b268, in the `cobol-parser` repo).
- `sqlca.py` DECLARE CURSOR support (task_d610057b, in this repo) — bundles
  the already-spiked one-line fix; explicitly notes it only becomes useful
  for a new example once the cobol-parser bug above is also fixed.
- A pre-existing, unrelated report-formatting bug was also found and fixed
  by a separately spawned session while this plan was being written:
  `mockymock run` used to report a test case that crashed via `STOP RUN`
  (see "STOP RUN" below) as a misleading `[PASS]`; `TestResult` now tracks
  whether the case's `END` marker was actually seen and renders `[CRASH]`
  instead. That fix already exists in this repo's working tree
  (uncommitted) as of this writing — this plan's tasks don't need to
  redo it, only account for its existence in `mockymock/report/results.py`.

## Original design (candidates section superseded above; rest still applies)

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

## Candidates (final)

| Example | Source program | Boundary shape it proves |
|---|---|---|
| **DEPTMQP** | `legacy-application/cobol/DEPTMQP.cbl` (MQ deposit producer) | A *stateful CALL sequence*: `MQCONN → MQOPEN → (loop) MQPUT → MQCMIT → MQCLOSE → MQDISC`, each mocked call threading a connection/queue handle to the next, plus sequential file I/O (read input, write report). Proves mockymock beyond one-off static `CALL`s (ORDRPROC's only category). |
| **DEPTMQC** | `legacy-application/cobol/DEPTMQC.cbl` (MQ deposit consumer) | Mixes MQ (`MQGET` no-wait loop) and DB2 (`INSERT`) boundaries in one program with a *dual-commit/backout* pattern — MQCMIT and DB2 COMMIT issued together each periodic commit; on an INSERT failure, ROLLBACK + `CALL 'MQBACK'` undo both sides together. A structurally different MQ+SQL combination than DEPTMQP alone, and DB2 without any cursor (sidesteps the DECLARE CURSOR / cobol-parser gaps below entirely). |

ACCTMNT (originally a third candidate, DB2 cursor depth) was dropped after
spiking — see "Revision" above. No CICS example (absent from the source
corpus). IMS DL/I (`ACCTPRG`/`DEPTIMSM`) was never attempted: both declare
PCB masks in `LINKAGE SECTION` behind `ENTRY 'DLITCBL' USING ...`, and
mockymock's driver only ever `PERFORM`s paragraphs, never `CALL`s the
program — unverified whether GnuCOBOL safely allocates storage for a
standalone program's `LINKAGE SECTION` under that access pattern. Left for
a future pass; not attempted here.

## Driving strategy: avoid `STOP RUN`

**Key finding from spiking, load-bearing for every task below:** a `.cut`
test case's `PERFORM` target must never reach a COBOL `STOP RUN` statement,
directly or transitively. mockymock's driver checks a test case's
`EXPECT`/`VERIFY` and prints its `CASE ... END`/pass-fail marker *after* the
performed target returns, all within one generated COBOL paragraph — a
`STOP RUN` reached mid-target kills the whole compiled test binary
immediately, before that case's own checks run and before any later
`TESTCASE` in the same suite gets a chance to run at all. (mockymock now
reports this honestly as `[CRASH]` rather than a misleading `[PASS]` — see
"Follow-ups filed" above — but the underlying limitation is unchanged: a
crashed case still never checks its own assertions, and the suite still
stops there.)

Both DEPTMQP's and DEPTMQC's real entry points (`0000-MAIN-PROCESS`) end in
an unconditional `STOP RUN`, so **no test case may `PERFORM 0000-MAIN-PROCESS`**.
Instead, each `.cut` targets sub-paragraphs directly:

- `1000-INITIALIZE` (no `STOP RUN` in it or anything it calls) — proves the
  MQ connect/open sequence and the first file `READ`.
- `2000-PROCESS-DEPOSITS` / `2300-DB2-INSERT` (the per-record processing
  paragraphs) — driven via the `.cut` file's `MOVE ... TO ...` setup
  statements to seed the record's fields directly, rather than relying on a
  mocked `READ`'s tally to feed data in. This also sidesteps a second, real
  wrinkle: `PERFORM <paragraph> THRU <paragraph>` across a range that
  includes paragraphs *also* invoked via inline `PERFORM` from within that
  same range (e.g. `1000-INITIALIZE` internally `PERFORM`s
  `1100-MQ-CONNECT`) double-executes those inline-performed paragraphs
  under THRU's fall-through semantics — avoided entirely by only ever
  targeting single paragraphs (no `THRU`) in these two examples.

One consequence: this cannot exercise the programs' real multi-record
`READ ... UNTIL WS-EOF` loop (that loop lives only inside
`0000-MAIN-PROCESS`) — each test case proves one record's processing
deterministically instead. This is a legitimate, deliberate trade-off
(traded loop-iteration depth for harness safety), not an oversight.

## Structure

Mirrors the existing `examples/` convention (polished + README, distinct
from the terser `tests/integration/fixtures/` corpus):

```
examples/real-world/
├── README.md                     # provenance note, links to the 2 examples
├── DEPTMQP/
│   ├── DEPTMQP.cbl
│   ├── copybooks/{WSCOMMON,ERRORCD,MQMSG}.cpy
│   ├── DEPTMQP.cut
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

Each `.cut` mocks every boundary statically reachable from its `PERFORM`
target (`MOCK CALL "<name>"` per external subprogram, `MOCK SQL "<prefix>"`
per distinct DB2 statement — see the schema-qualified-name gotcha below,
`MOCK OPEN|READ|WRITE|CLOSE <name>` for file I/O), with a happy-path
`TESTCASE` and an error-path `TESTCASE` (non-`MQCC-OK` completion code /
negative `SQLCODE` forcing the program's own rollback/backout branch) per
target paragraph — the same success/failure pairing INVUPDT's README calls
out. Both proven `.cut` suites already exist from spiking (see the tasks
below) and are used close to verbatim.

**Schema-qualified SQL table names need a space after the period.**
cobolparser's lexer tokenizes `BANK.ACCOUNT` as three tokens (`BANK`, `.`,
`ACCOUNT`) and mockymock's SQL-prefix match text re-joins tokens with single
spaces, so `MOCK SQL "INSERT INTO BANK.TRANSACTION_HIST"` will never match —
the working key is `MOCK SQL "INSERT INTO BANK. TRANSACTION_HIST"` (space
after the period). Verified directly against DEPTMQC's real INSERT
statement. Call this out explicitly in both example READMEs since it's
non-obvious and will trip up anyone editing these `.cut` files later.

**Mock bodies must use literal values, not named MQ-constant fields, for
anything non-zero.** `reset.py`'s WORKING-STORAGE reset uses plain
`INITIALIZE <group>` for a group with no `VALUE` clause of its own — this is
the already-documented "known v1 fidelity limit" in splicer.md (INITIALIZE
does not restore a group's children's own `VALUE` clauses; it zero-fills
numeric children and space-fills alphanumeric ones instead). `MQ-CONSTANTS`
(from `MQMSG.cpy`) is exactly such a group: after the first test case, a
reset silently zeroes every named constant in it. `MQCC-OK` (`VALUE +0`)
survives this by coincidence; `MQCC-FAILED` (`VALUE +2`) does not — a mock
body that does `MOVE MQCC-FAILED TO MQ-COMP-CODE` in test case 2 silently
gets `0`, not `2`, once test case 1 has run. Caught empirically: an early
draft of `.cut` test case 2 in both examples referenced `MQCC-FAILED` and
produced a wrong-but-plausible passing-looking result until traced through
raw stdout. **Fix: mock bodies always use bare literals** (`MOVE 2 TO
MQ-COMP-CODE`, not `MOVE MQCC-FAILED TO MQ-COMP-CODE`) — matching INVUPDT's
own existing convention (`MOVE 0 TO SQLCODE`, `MOVE 0 TO MQ-COMPCODE`),
which was presumably already written this way for exactly this reason.
Same root cause explains why `EXPECT WS-MQ-CONNECTED TO BE "N"` doesn't
work as an error-path assertion either: `WS-MQ-FLAGS` (the group holding
`WS-MQ-CONNECTED`) resets to spaces, not `"N"`, between cases — the error
test cases below assert on `WS-MQ-ERRORS`/tally `VERIFY`s instead, which
are set by real code paths at runtime rather than relying on reset fidelity.

## Adaptation policy

Programs are copied close to verbatim — realism is the point — but where a
program relies on formatting a native COBOL compiler can't tolerate, the
minimum necessary trim is made and called out explicitly in that example's
README as a documented deviation from the source file. Both known instances
(found by spiking, both purely cosmetic re-wraps, no logic changes) are
**column-72 overflow**: `legacy-application`'s files were authored without
strict adherence to fixed-format COBOL's 72-column program-text boundary
(columns 73-80 are the identification area and are silently truncated by
cobolparser's `normalize_fixed_format`, per real fixed-format COBOL rules).
Confirmed by an actual compile failure (a dropped terminating period cascaded
into a syntax error) before the fix:

- **`MQMSG.cpy` line 158** (`05 MQ-QUEUE-NAME PIC X(48) VALUE
  'BANK.DEPOSIT.QUEUE'.`, 73 chars): the terminating period lands in column
  73 and is dropped. Fix: wrap onto two lines (`PIC X(48)` / `VALUE
  '...'.`). Affects both DEPTMQP and DEPTMQC (both `COPY MQMSG`).
- Both `.cbl` files also have a handful of `*`-comment lines running past
  column 72 (DEPTMQP lines 138/156, DEPTMQC lines 236/305/306) — harmless
  (a truncated trailing word in a comment has no compile impact) but note
  them in the README for completeness; no fix needed.

Any other adaptation needed to get a candidate compiling is expected to be
similarly small and mechanical. If a candidate turns out to need
substantial rewriting to compile, that's a signal to swap it for a
different corpus program rather than force it in — implementation should
flag this rather than silently reshaping the program beyond a documented
one- or two-line trim. (ACCTMNT above is exactly this signal firing: its
gaps were not mechanical trims, so it was dropped rather than forced.)

If running one of these programs through the full pipeline surfaces an
actual mockymock (or cobol-parser) engine bug, that becomes its own
follow-up rather than being silently folded into this plan — exercised
twice already during spiking (see "Follow-ups filed" above).

## Testing

One integration test file per example under `tests/integration/`
(`test_realworld_deptmqp_example.py`, `test_realworld_deptmqc_example.py`),
following the exact pattern of `test_invupdt_example.py`: `@requires_docker`,
invokes `mockymock run` via the CLI with `--copybook-path`, asserts
`exit_code == 0`. These join the existing `tests/ -v` run — no new CI wiring
needed since the integration tier already self-skips without Docker and
GnuCOBOL is Docker-only in CI as today.

## Documentation updates

- `.okf/testing.md`: new subsection alongside the existing INVUPDT/ORDRPROC
  write-up, with the same boundary-table format, for the two real-world
  examples; refresh its `timestamp`.
- `.okf/log.md`: dated entry noting the addition and the two follow-ups filed.
- Top-level `README.md`: one line pointing at `examples/real-world/`.
- `examples/real-world/README.md`: provenance (adapted from
  `legacy-application`, workspace-sibling repo — not third-party code),
  the `STOP RUN` driving-strategy note, and a one-line pointer to each of
  the two sub-READMEs.

## Out of scope

- No changes to mockymock's splicer/analysis/refusal engine (the one
  spiked-and-verified `sqlca.py` change is filed as its own follow-up,
  task_d610057b, not included here since ACCTMNT was dropped).
- No CICS example (absent from the source corpus).
- IMS DL/I (`ACCTPRG`/`DEPTIMSM`) not attempted — `LINKAGE SECTION` behind
  `ENTRY 'DLITCBL' USING ...` with no driving `CALL` is unverified against
  mockymock's `PERFORM`-only driver model. Left for a future pass.
- No changes to `legacy-application` itself — this is a one-directional
  copy.
- No changes to the cobol-parser AST gap found while spiking ACCTMNT
  (filed as task_c5e3b268) — different repo, unscoped.
