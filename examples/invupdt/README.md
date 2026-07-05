# INVUPDT — all boundary categories in one program

`INVUPDT.cbl` is a small inventory updater that touches every boundary
mockymock can mock:

| Boundary | Statement in INVUPDT | Mocked by |
|----------|---------------------|-----------|
| File open (two files, one OPEN) | `OPEN INPUT INV-FILE OUTPUT RPT-FILE` | `MOCK OPEN INV-FILE` |
| Sequential read loop | `READ INV-FILE AT END ...` | `MOCK READ INV-FILE` (tally-driven EOF) |
| Report write | `WRITE RPT-REC` | `MOCK WRITE RPT-REC` |
| File close | `CLOSE INV-FILE RPT-FILE` | `MOCK CLOSE INV-FILE` |
| DB2 update | `EXEC SQL UPDATE INVENTORY ... END-EXEC` | `MOCK SQL "UPDATE INVENTORY"` |
| MQ notification | `CALL "MQPUT" USING MQ-COMPCODE` | `MOCK MQ "MQPUT"` |
| Operator input | `ACCEPT WS-CONFIRM` | `MOCK ACCEPT WS-CONFIRM` |

The program also uses `EXEC SQL INCLUDE SQLCA END-EXEC`, which mockymock
replaces with a generated SQLCA so mock bodies can set `SQLCODE`.

Things this example demonstrates on purpose:

- **Tally-driven EOF**: the `READ` mock uses its own tally field
  (`UT-READ-INV-FILE-TALLY`) to return two records and then signal end of
  file on the third invocation.
- **FD record areas without OPEN**: the `READ` mock `MOVE`s into `INV-QTY`
  (a FILE SECTION field) even though `INV-FILE` is never really opened —
  no `INV.DAT` needs to exist in the sandbox.
- **Static reachability**: test case 2 never executes the `WRITE` (EOF on
  first read), but the WRITE is statically reachable, so it still needs a
  `MOCK WRITE` — verified with `VERIFY WRITE RPT-REC WAS PERFORMED NEVER`.
- **Error-path testing**: test case 2 forces `SQLCODE = -911` and asserts
  the program's failure branch runs.

Run it:

```bash
mockymock run examples/invupdt/INVUPDT.cbl --cut examples/invupdt/INVUPDT.cut
```
