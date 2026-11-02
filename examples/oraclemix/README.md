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
| `VSAMJOB` | JCL, 4 steps: `VSKSDSR` (KSDS random: READ / WRITE / REWRITE / DELETE, 88s on the status), `VSKSDSD` (KSDS dynamic: START, READ NEXT, READ PREVIOUS, READ by alternate key with `02`), `VSESDS` (ESDS: OPEN `35` then create, WRITE, READ NEXT), `VSRRDS` (RRDS: READ by slot, WRITE in its INVALID KEY, START + READ NEXT) | VSAM files, FILE STATUS codes |
| `VSCICS` | CICS program on a VSAM file | READ FILE, STARTBR / READNEXT / ENDBR, `RESP` |

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

## Results (2026-11-02, GnuCOBOL 3.1.2, generated suites, one case per branch and error path)

Suites are generated with `--scenarios all`: one case per branch the
generator can drive, plus empty input, each declared error handler, and
each FILE STATUS code a file statement is tested for (failing that one
statement, on the path that runs it). A dynamically called program with
source runs for real (`USE REAL CALL` answers `CALL WS-RATE-PGM`).

| Module | Cases | 1 no-op edits | 2 behaviour edits | 3 copybook layout (`CUST-NAME` 20 -> 24) | 4 copybook comment |
|---|---|---|---|---|---|
| CUSTJOB | 10 + 3 | same | differs (`CUSTFMT` report line) | differs (`CUST-OUT` record) | same |
| ACCTJOB | 5 | same | differs (REWRITE value) | differs (REWRITE record) | same |
| DB2JOB | 2 | same | differs (cursor host variable `EAST` -> `WEST`) | differs (report line) | same |
| MQLSN | 11 | same | differs (MQPUT reply) | - | - |
| CUSTMENU | 1 | same | differs (SEND TEXT) | - | - |
| IMSBMP | 10 | same | differs (the hold path has its own case) | differs (GHN segment) | same |
| MISCJOB | 2 | incomplete: `NESTPGM` | differs (`RATECALC`'s rate, through the dynamic CALL) | - | - |
| CUSTINQ | 11 | same | differs (second screen: cases set `EIBCALEN` and `EIBAID`) | same | same |
| CUSTVAL | 10 | same | differs (cases at the limit: 899999 and 900000) | - | - |
| PRTINQ | 6 | same | differs (a case where `PRTRATE` finds the record asked for) | - | - |
| VSAMJOB | 12 + 8 + 9 + 7 | same | differs in all 4 steps: `VSKSDSR` not-found message (READ `23` in the change path), `VSKSDSD` duplicate message (READ by alternate key `02`), `VSESDS` OPEN `35` message, `VSRRDS` failed-WRITE message (READ `23` then WRITE `22`) | - | - |
| VSCICS | 18 | same | differs (`DUPREC` response code returned in the COMMAREA) | - | - |

Round 5 changes the value `CUSTVAL` returns in its COMMAREA when the id is
rejected: differs (`RETURNED LINKAGE`).

What reaches those branches: a CICS program's COMMAREA and the EIB fields
its branches test are generated inputs; a never-written `VALUE` item and
`DFHRESP(...)` count as constants; each numeric comparison also gets a case
at its edge; and a real subprogram that READs a record keyed by what its
caller passes gets a case where the record is found.

What a "same" means: every case ran and sent out exactly what it did
before. It says nothing about paths no case reaches:

- **Branches the generator cannot drive**: a case per branch needs the
  branch condition to depend on data the generator sets (for example,
  `NOT NUMERIC` on a `PIC 9` item cannot be generated).
- **Other boundaries inside real subprograms get placeholder mocks**
  (`generate --real`): an empty file, SQLCODE 0 with no data, except the
  found-record case above.
- **Nested programs** (`NESTPGM`): mockymock refuses multi-unit
  compilation units, so the suite is never recorded and every compare of
  `MISCJOB` is incomplete.
- **On-disk data in the old layout**: `CUSTSUM` compares the same after the
  copybook widening because its mocked READs fill fields by name. A real
  file written with the old layout would be read wrongly; the oracle does
  not see data at rest.
