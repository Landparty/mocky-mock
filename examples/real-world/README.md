# Real-world worked examples

Seventeen business-flavored COBOL programs modeled on real mainframe
patterns (batch IMS DL/I, IMS BMP/DBB, IMS MPP, IBM MQ, and DB2 batch),
each with its own copybooks resolved via `--copybook-path`. Unlike
`examples/invupdt`/`ordrproc`/`custinq`/`raterte`, which are small
teaching programs built to showcase one boundary category apiece, these
are closer to production shape — multi-paragraph flows, `COPY`-based
WORKING-STORAGE, and (for the IMS batch programs) a real `LINKAGE
SECTION`/`ENTRY` pair that mockymock neutralizes into ordinary
WORKING-STORAGE.

The first four (`ACCTPRG`, `DEPTIMSM`, `DEPTMQC`, `DEPTMQP`) are
hand-written; the other thirteen are sourced from the sibling
`legacy-application` corpus (`../legacy-application/cobol/`) — see
"Provenance" below. Together all 17 give the corpus's entire COBOL
program set a real, passing `mockymock run` suite (238 test cases total,
0 failing), not just a clean `mockymock generate` static pass — see
`docs/corpus-sweep-report.md` for the standing parse/generate sweep
across the same 17 programs.

Every run needs `--copybook-path` pointed at that program's own
`copybooks/` directory:

```bash
mockymock run examples/real-world/<PROGRAM>/<PROGRAM>.cbl \
    --cut examples/real-world/<PROGRAM>/<PROGRAM>.cut \
    --copybook-path examples/real-world/<PROGRAM>/copybooks
```

## ACCTPRG — IMS DL/I batch account purge

Scans every `CUSTSEG` segment in `CUSTDB` via `CALL 'CBLTDLI'` (`GHN`/
`DLET`) and purges closed, stale accounts. Demonstrates the classic IMS
batch idiom: a bare `ENTRY 'DLITCBL'` with a `LINKAGE SECTION` PCB mask
(`CUST-PCB-LNK`) that mockymock neutralizes into real, addressable
WORKING-STORAGE — a `MOCK CALL "CBLTDLI"` body can `MOVE` straight into
`CUST-STATUS` to simulate a DL/I response code. The last test case drives
`0000-MAIN-PROCESS`, the program's real entry point, to `GOBACK`.

```bash
mockymock run examples/real-world/ACCTPRG/ACCTPRG.cbl \
    --cut examples/real-world/ACCTPRG/ACCTPRG.cut \
    --copybook-path examples/real-world/ACCTPRG/copybooks
```

## DEPTIMSM — IMS MPP deposit transaction (and the coverage worked example)

An IMS message-processing program: receives a deposit/withdrawal message
off the `IOPCB`, validates it, looks up the customer and posts a `TRNSEG`
child segment via the `CUST-PCB`, then replies — two PCBs neutralized into
WORKING-STORAGE (`IOPCB-LNK`, `CUST-PCB-LNK`) off one `CALL 'CBLTDLI'`
boundary. Its 20-case suite is also this repo's coverage-reporting worked
example (`.okf/coverage.md`, `docs/2026-07-17-coverage-reporting-design.md`):

```bash
mockymock run examples/real-world/DEPTIMSM/DEPTIMSM.cbl \
    --cut examples/real-world/DEPTIMSM/DEPTIMSM.cut \
    --copybook-path examples/real-world/DEPTIMSM/copybooks \
    --coverage
```

reports `75.90% lines executed (693/913)` even though every real branch —
including the full `0000-MAIN-PROCESS` entry point — is exercised. That
gap is structural, not a weak suite: it's the driver's own dead
`FAIL`/tally lines plus the splicer's one-dispatch-per-boundary-site
design emitting a `WHEN` branch for every test case that mocks a key, not
only the cases that actually reach that site. See `.okf/coverage.md`
before reading a coverage number as suite quality. Add `--coverage-out
PATH` to also write the full report to a file.

## DEPTMQC — IBM MQ batch consumer

Drains `BANK.DEPOSIT.QUEUE` via `MQGET` in a no-wait loop and posts each
payload to DB2 (`BANK.TRANSACTION_HIST`), committing MQ and DB2 together
every `WS-COMMIT-FREQ` messages. Demonstrates an MQ/DB2 two-phase
happy-path plus the rollback pairing: a DB2 failure both rolls back the
`EXEC SQL` unit of work and issues `MQBACK` so the two never drift out of
sync.

```bash
mockymock run examples/real-world/DEPTMQC/DEPTMQC.cbl \
    --cut examples/real-world/DEPTMQC/DEPTMQC.cut \
    --copybook-path examples/real-world/DEPTMQC/copybooks
```

## DEPTMQP — IBM MQ batch producer

The upstream counterpart to DEPTMQC: reads deposit records off a
sequential file (`DEPTIN`), validates each one, and `MQPUT`s a persistent
message to the same queue. Demonstrates the mirror-image MQ connect/open
happy-path and failure-path (a failed `MQCONN` must short-circuit before
`MQOPEN` is ever attempted, not just because `MQOPEN` is statically
reachable).

```bash
mockymock run examples/real-world/DEPTMQP/DEPTMQP.cbl \
    --cut examples/real-world/DEPTMQP/DEPTMQP.cut \
    --copybook-path examples/real-world/DEPTMQP/copybooks
```

## ACCTMNT — account maintenance batch

Applies parameter-card-driven maintenance to `BANK.ACCOUNT` over a DB2
cursor: interest-rate changes by account type, minimum-balance fee
assessment (with its own fetch-and-assess sub-cursor), and dormancy
flagging by inactivity threshold. 13 test cases covering the rate-change
and dormancy commit/rollback paths, the fee cursor's posted-vs-skipped
branches, and the job's `RETURN-CODE` exit contract.

```bash
mockymock run examples/real-world/ACCTMNT/ACCTMNT.cbl \
    --cut examples/real-world/ACCTMNT/ACCTMNT.cut \
    --copybook-path examples/real-world/ACCTMNT/copybooks
```

## ACHPROC — ACH (NACHA) batch processor

Processes an inbound NACHA-format ACH file: validates each entry via a
`CALL 'ACCTVAL'` routing/account check, posts debit/credit entries to
`BANK.ACCOUNT` and `BANK.TRANSACTION_HIST`, and writes return items for
rejected entries (invalid routing, account not found, closed, NSF). 21
test cases spanning the full record-type dispatch (header/batch/entry/
control/padding) and every entry-detail rejection reason.

```bash
mockymock run examples/real-world/ACHPROC/ACHPROC.cbl \
    --cut examples/real-world/ACHPROC/ACHPROC.cut \
    --copybook-path examples/real-world/ACHPROC/copybooks
```

## CHKCLR — check clearing

Processes check-clearing items against a `CALL 'ACCTVAL'` routing check,
a `STOPPAY` VSAM lookup, and `BANK.ACCOUNT`, posting debits for cleared
items and returning NSF/stop-payment/closed-account rejections. 11 test
cases cover a cleared check, a posting rollback, and each of the six
early-return reason codes.

```bash
mockymock run examples/real-world/CHKCLR/CHKCLR.cbl \
    --cut examples/real-world/CHKCLR/CHKCLR.cut \
    --copybook-path examples/real-world/CHKCLR/copybooks
```

## CTRRPT — currency transaction report (BSA/AML)

A regulatory compliance program: aggregates each customer's same-day
cash in/out via a DB2 cursor with a `HAVING SUM(...) >= 10000.00`
threshold clause, filing a FinCEN CTR record for a plain threshold hit
or a SAR for a "structuring" pattern (more than 3 sub-threshold
transactions). 10 test cases cover both filing types, both edges of the
SAR amount/count band, and the cursor-open/fetch/insert failure paths.

```bash
mockymock run examples/real-world/CTRRPT/CTRRPT.cbl \
    --cut examples/real-world/CTRRPT/CTRRPT.cut \
    --copybook-path examples/real-world/CTRRPT/copybooks
```

## DEPTBMP — IMS BMP deposit posting

An IMS batch message processor: reads deposit records off a sequential
file and inserts a `TRNSEG` child under `CUSTSEG` in `CUSTDB` for each
one via `CALL 'CBLTDLI'` (`GU`/`ISRT`), checkpointing every
`WS-CHKP-FREQ` records for IMS restart. 20 test cases, one per paragraph
plus an end-to-end run through the real `0000-MAIN-PROCESS` entry point.

```bash
mockymock run examples/real-world/DEPTBMP/DEPTBMP.cbl \
    --cut examples/real-world/DEPTBMP/DEPTBMP.cut \
    --copybook-path examples/real-world/DEPTBMP/copybooks
```

## DORMACCT — dormant account identification

Scans `BANK.ACCOUNT` via a DB2 cursor and flags accounts crossing
state-escheatment-law inactivity thresholds: dormant vs. escheated,
computed from two `SELECT CHAR(DATE(...) - n YEARS)` cutoff dates. 13
test cases cover both cutoff branches and their exact boundary edges,
UPDATE-failure error paths, and the interim-commit batch idiom.

```bash
mockymock run examples/real-world/DORMACCT/DORMACCT.cbl \
    --cut examples/real-world/DORMACCT/DORMACCT.cut \
    --copybook-path examples/real-world/DORMACCT/copybooks
```

## EODPROC — end-of-day processing driver

Orchestrates the bank's end-of-day batch cycle: DB2 aggregate queries
for daily transaction/account totals (each value formatted through a
mocked `CALL 'CURRFMT'` assembler routine), a GL balanced/out-of-balance
check, and next-business-day computation via `CALL 'DATEUTIL'`. 16 test
cases cover every summary paragraph's happy and DB2-error paths plus two
full end-to-end runs.

```bash
mockymock run examples/real-world/EODPROC/EODPROC.cbl \
    --cut examples/real-world/EODPROC/EODPROC.cut \
    --copybook-path examples/real-world/EODPROC/copybooks
```

## FNDTXFR — IMS BMP funds transfer

An IMS batch processor mirroring `DEPTBMP`'s shape but doubled: reads a
transfer request and posts a debit `TRNSEG` under the source `CUSTSEG`
and a credit `TRNSEG` under the target `CUSTSEG`, both via `CALL
'CBLTDLI'`. 24 test cases cover both legs' DL/I success and failure
paths (customer-not-found, unexpected status, insert failure) plus an
end-to-end run through the real entry point.

```bash
mockymock run examples/real-world/FNDTXFR/FNDTXFR.cbl \
    --cut examples/real-world/FNDTXFR/FNDTXFR.cut \
    --copybook-path examples/real-world/FNDTXFR/copybooks
```

## GLRECON — general ledger reconciliation

Aggregates today's posted transactions by tran-code via one DB2 cursor
(`GL_AGG_CUR`) and applies the delta to each active GL account's
balance via a second cursor (`GL_BAL_CUR`), reconciling total debits vs.
credits into a clean commit, an in-balance-with-errors return code, or a
full out-of-balance exception report. 13 test cases exercise both
cursors' fetched-row/end-of-cursor/DB2-error paths independently and
end-to-end.

```bash
mockymock run examples/real-world/GLRECON/GLRECON.cbl \
    --cut examples/real-world/GLRECON/GLRECON.cut \
    --copybook-path examples/real-world/GLRECON/copybooks
```

## INTCALC — interest calculation

Walks all interest-bearing accounts over a DB2 cursor, computing daily
accrual via a mocked `CALL 'INTRATE'` rate lookup and posting interest
payments on statement-cycle pay days. 15 test cases cover accrue-only
vs. pay-day branches, a zero-balance edge case, and the INTRATE/DB2
failure fallback paths.

```bash
mockymock run examples/real-world/INTCALC/INTCALC.cbl \
    --cut examples/real-world/INTCALC/INTCALC.cut \
    --copybook-path examples/real-world/INTCALC/copybooks
```

## LNRECOV — IMS DBB loan recovery

An IMS batch (dynamic-backout) processor: scans `LOANDB` via `CALL
'CBLTDLI'` (`GHN`) for loans past a control-card days-past-due
threshold and marks them for recovery via `REPL` on the `LOANSEG`
segment. 19 test cases cover each qualification-rule rejection branch
individually plus DL/I success/end-of-database/error paths and an
end-to-end entry-point run.

```bash
mockymock run examples/real-world/LNRECOV/LNRECOV.cbl \
    --cut examples/real-world/LNRECOV/LNRECOV.cut \
    --copybook-path examples/real-world/LNRECOV/copybooks
```

## LOANPMT — loan payment posting

Walks loans due today over a DB2 cursor, splits each payment into
principal/interest via a mocked `CALL 'INTRATE'` lookup (looking up the
customer segment via `CALL 'CBLTDLI'`), and assesses late fees. 9 test
cases cover a normal payment, the INTRATE-failure fallback, and DB2
fetch/update failure paths — including a real business-logic finding
(the late-fee branch is unreachable as paragraphs are currently
sequenced) pinned as a documented test case rather than silently masked.

```bash
mockymock run examples/real-world/LOANPMT/LOANPMT.cbl \
    --cut examples/real-world/LOANPMT/LOANPMT.cut \
    --copybook-path examples/real-world/LOANPMT/copybooks
```

## STMTGEN — monthly statement generation

Generates statements for every account whose cycle date matches today,
over a nested pair of DB2 cursors (accounts, then that account's period
transactions), formatting each line through a mocked `CALL 'STMTFMT'`
assembler routine. 20 test cases cover both cursors' fetched-row/
end-of-cursor/DB2-error paths, a zero-transaction account, and two
end-to-end runs proving the outer cursor loop and the inner cursor's
per-account reset both work.

```bash
mockymock run examples/real-world/STMTGEN/STMTGEN.cbl \
    --cut examples/real-world/STMTGEN/STMTGEN.cut \
    --copybook-path examples/real-world/STMTGEN/copybooks
```

## Provenance

`ACCTPRG`, `DEPTIMSM`, `DEPTMQC`, and `DEPTMQP` are hand-written, not
sourced from a public corpus (unlike `examples/nist-cobol85/`), modeled
on real mainframe deposit-processing and account-purge patterns. See
`docs/2026-07-06-realworld-cobol-examples-design.md` and
`docs/2026-07-06-real-world-readiness-audit.md` for the design and audit
history behind why these four were built.

The other thirteen (`ACCTMNT`, `ACHPROC`, `CHKCLR`, `CTRRPT`, `DEPTBMP`,
`DORMACCT`, `EODPROC`, `FNDTXFR`, `GLRECON`, `INTCALC`, `LNRECOV`,
`LOANPMT`, `STMTGEN`) are copied from the sibling `legacy-application`
repo's `cobol/`/`copybook/` directories (a banking-batch mainframe
corpus used to test a separate parser pipeline), the same source
`scripts/corpus_sweep.py` already swept for parse/generate cleanliness.
Driving them through a real `mockymock run` surfaced several genuine
compile-blocking bugs in that source corpus (fixed-format column-72
overflows, an undeclared `FATAL-ERROR-FOUND` condition-name repeated
copy-paste-style across five programs, a couple of ambiguous data names
and missing sentence periods) — fixed upstream in `legacy-application`,
not worked around here. A few real *business-logic* control-flow bugs
(missing `PERFORM ... THRU` on paragraphs with internal early-exit `GO
TO`s, in `ACCTMNT`/`ACHPROC`/`CHKCLR`/`INTCALC`; a missing `FILE STATUS`
clause in `ACCTMNT`; `LOANPMT`'s late-fee branch being unreachable as
sequenced) were found but deliberately left alone — fixing them would
change program behavior, which was out of scope for adding test
coverage. Each is documented in a comment in its `.cut` file for
whoever owns that logic to follow up on.
