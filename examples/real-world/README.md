# Real-world worked examples

Four business-flavored COBOL programs modeled on real mainframe patterns
(batch IMS DL/I, IMS MPP, and IBM MQ), each with its own copybooks
resolved via `--copybook-path`. Unlike `examples/invupdt`/`ordrproc`/
`custinq`/`raterte`, which are small teaching programs built to showcase
one boundary category apiece, these four are closer to production shape —
multi-paragraph flows, `COPY`-based WORKING-STORAGE, and (for ACCTPRG and
DEPTIMSM) a real `LINKAGE SECTION`/`ENTRY` pair that mockymock neutralizes
into ordinary WORKING-STORAGE.

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

## Provenance

These four are hand-written, not sourced from a public corpus (unlike
`examples/nist-cobol85/`), modeled on real mainframe deposit-processing
and account-purge patterns. See `docs/2026-07-06-realworld-cobol-examples-design.md`
and `docs/2026-07-06-real-world-readiness-audit.md` for the design and
audit history behind why these four were built.
