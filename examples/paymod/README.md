# paymod: a load module, tested as one unit

`PAYMAIN` is a batch entry point. It reads employees, calls the in-module
subprogram `PAYCALC` to price each one, and stamps the run date through
`DATEUTL`, which lives outside the load module. `PAYCALC` reads the
grade's hourly rate from DB2.

`PAYMAIN.cut` runs both programs for real, linked into one test binary:

- `USE REAL CALL "PAYCALC" FROM "PAYCALC.cbl"` links PAYCALC instead of
  mocking its CALL.
- `MOCK SQL "SELECT HOURLY_RATE"` answers the EXEC SQL **inside PAYCALC**.
  Its body names PAYCALC's own `WS-RATE`.
- `DATEUTL`, `EMP-FILE` and DB2 stay mocked: they leave the load module.
- `VERIFY CALL "PAYCALC" WAS CALLED 2 TIMES` still counts the real calls.

```bash
mockymock run examples/paymod/PAYMAIN.cbl --cut examples/paymod/PAYMAIN.cut
```

Change `LK-HOURS` in PAYCALC's LINKAGE to `PIC 9(2)` and the first case
fails. That is the caller/subprogram layout mismatch a unit suite of
either program can't see.

To scaffold a suite like this one:

```bash
mockymock generate examples/paymod/PAYMAIN.cbl --real examples/paymod/PAYCALC.cbl
```

See [docs/2026-11-01-real-call-integration-design.md](../../docs/2026-11-01-real-call-integration-design.md).
