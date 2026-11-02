# oraclemix: the change-impact oracle over many kinds of program

A small application to run the LegacyLens change-impact oracle end to end
(docs/2026-11-01-baseline-design.md, docs/2026-11-01-runner-design.md) on
every kind of program a mainframe shop has. `src/` is what gets uploaded;
`edits/` holds the changes made to it afterwards, one folder per round.

| Load module | Kind | What leaves the module |
|---|---|---|
| `CUSTJOB` | JCL, 2 steps: `CUSTEXT` (static CALL of `CUSTFMT`) then `CUSTSUM` | sequential files, DISPLAY, RETURN-CODE |
| `ACCTJOB` | JCL: an `IDCAMS` step, then `ACCTUPD` | VSAM KSDS random READ / REWRITE, INVALID KEY |
| `DB2JOB` | JCL: `IKJEFT01` + `DSN RUN PROGRAM(DB2RPT)` | DB2 cursor, UPDATE, report file |
| `MQLSN` | MQ listener (`MQGET` loop, reply with `MQPUT`) | MQ calls |
| `CUSTINQ` | CICS pseudo-conversational, BMS map `CUSTSET` | SEND/RECEIVE MAP, `LINK CUSTVAL`, `XCTL CUSTMENU`, READ FILE |
| `CUSTVAL`, `CUSTMENU` | CICS LINK / XCTL targets | the COMMAREA it returns; SEND TEXT |
| `PRTINQ` | IMS MPP (from `imsmod`), static CALLs of `PRTSTK` (DB2), `PRTRATE` (file) | DL/I GU/ISRT, SQL, file |
| `IMSJOB` | JCL: `DFSRRC00 PARM='BMP,IMSBMP,...'` | DL/I GHN / REPL / CHKP on a DB PCB |
| `MISCJOB` | JCL, 2 steps: `DYNDRV` (`CALL WS-RATE-PGM` = `RATECALC`), `NESTPGM` (two nested programs) | files, a dynamic CALL |

`CUSTREC.cpy`, the customer record, is copied by `CUSTEXT`, `CUSTFMT`,
`CUSTSUM`, `ACCTUPD`, `DB2RPT`, `CUSTINQ` and `IMSBMP`.

## Running it

Start a backend with `RUNNER_TOKEN` set, have mockymock and a GnuCOBOL
toolchain on PATH, then:

```bash
RUNNER_TOKEN=... python examples/oraclemix/e2e.py --url http://localhost:9999
```

It uploads `src/`, records a baseline of each load module, then uploads
each `edits/` folder and prints every module's verdict. Before rounds 3, 4
and 5 the previous round is accepted (a new baseline), so each round is
compared on its own.

## Results (2026-11-02, GnuCOBOL 3.1.2, generated suites)

| Module | 1 no-op edits | 2 behaviour edits | 3 copybook layout (`CUST-NAME` 20 -> 24) | 4 copybook comment |
|---|---|---|---|---|
| CUSTJOB | same | differs (`CUSTFMT` report line) | differs (`CUST-OUT` record) | same |
| ACCTJOB | same | differs (REWRITE value) | differs (REWRITE record) | same |
| DB2JOB | same | differs (cursor host variable `EAST` -> `WEST`) | differs (report line) | same |
| MQLSN | same | differs (MQPUT reply) | - | - |
| CUSTMENU | same | differs (SEND TEXT) | - | - |
| CUSTINQ | same | same: the edit is on the second screen, the suite only runs the first | same: the first screen never shows `CUSTREC` | same |
| CUSTVAL | same | same: the generated COMMAREA id is 0, the edit only moves the limit | - | - |
| IMSBMP | same | same: the generated segment is already held, the edit is on the hold path | differs (GHN segment) | same |
| PRTINQ | same | same: `PRTRATE`'s file is an empty placeholder mock, the found path never runs | - | - |
| MISCJOB | incomplete: `NESTPGM` | incomplete | - | - |

Round 5 changes the value `CUSTVAL` returns in its COMMAREA on the path the
suite does run: differs (`RETURNED LINKAGE`).

What a "same" means: every case ran and sent out exactly what it did
before. It says nothing about paths no case reaches. A generated suite has
one case with generated data, so its coverage decides what the oracle can
see:

- **One case per suite.** `CUSTINQ` (first screen only), `IMSBMP` (the
  segment is generated held) and `CUSTVAL` (id 0) never reach the edited
  code.
- **Boundaries inside real subprograms get placeholder mocks**
  (`generate --real`): an empty file, SQLCODE 0 with no data. `PRTRATE`
  never finds a rate.
- **Nested programs** (`NESTPGM`): mockymock refuses multi-unit
  compilation units, so the suite is never recorded and every compare of
  `MISCJOB` is incomplete.
- **Dynamic CALL targets** (`RATECALC`): mocked in `DYNDRV`'s suite, and
  not an entry point of its own, so no suite runs a `RATECALC` change.
- **On-disk data in the old layout**: `CUSTSUM` compares the same after the
  copybook widening because its mocked READs fill fields by name. A real
  file written with the old layout would be read wrongly; the oracle does
  not see data at rest.
