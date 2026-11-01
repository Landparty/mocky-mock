# ordmod: a batch load module with DB2, MQ and a file inside its subprograms

`ORDJOB` runs `ORDMAIN`, which reads the day's orders and, for each one:

- CALLs `ORDVAL`, which reads the customer's credit limit from DB2 and
  CALLs `ORDLOG` to append a line to the log file;
- CALLs `ORDPUB` for an accepted order, which puts it on an MQ queue
  (`MQOPEN` / `MQPUT` / `MQCLOSE`) and marks it published in DB2.

`ORDMAIN` also CALLs `DATEUTL` (outside the module) and an audit program
through `CALL WS-AUDIT-PGM` (a dynamic CALL).

`ORDMAIN.cut` runs `ORDMAIN`, `ORDVAL`, `ORDPUB` and `ORDLOG` for real,
linked into one test binary. It mocks what leaves the load module, including
inside the subprograms: the two SQL statements, the three MQ calls, the log
file, `DATEUTL` and the dynamic CALL. The mock bodies name each
subprogram's own data (`WS-CUST`, `WS-LIMIT` in ORDVAL; `WS-COMPCODE` in
ORDPUB).

```bash
mockymock run examples/ordmod/ORDMAIN.cbl --cut examples/ordmod/ORDMAIN.cut \
    --copybook-path examples/ordmod
```

The three cases cover publish versus reject on the credit limit, an unknown
customer (`SQLCODE` 100) that never reaches MQ, and a failed `MQOPEN` that
neither puts nor updates. The suite catches changes that unit suites of
either program cannot see:

- ORDVAL's limit test inverted: case 1 counts 1 accepted instead of 2;
- ORDVAL's LINKAGE declared with another layout than `ORDREC`: every order
  is rejected.

LegacyLens builds this kind of suite from a load module
(`GET /load-modules/{id}/integration-tests/pack`). This example is the
end-to-end check of that pack, with its scaffolded mocks replaced by
data for each case.
