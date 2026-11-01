# imsmod: an IMS transaction with DB2 and a file inside its subprograms

`PRTINQ` is an IMS message processing program (`ENTRY 'DLITCBL' USING
IOPCB`). It reads part inquiries off the message queue with `GU` on the
I/O PCB until IMS answers `QC`, and for each one:

- CALLs `PRTSTK`, which reads the stock on hand from DB2
  (`SELECT QTY_ON_HAND FROM PART_STOCK`);
- when the stock does not cover the quantity, CALLs `PRTRATE`, which reads
  a rate file for the part's lead time;
- answers `IN STOCK`, `BACKORDER`, `UNKNOWN` or `NO SOURCE` with `ISRT` on
  the I/O PCB.

`PRTINQ.cut` runs all three programs for real, linked into one test binary,
and mocks what leaves the load module: the CBLTDLI calls, the SQL SELECT
inside PRTSTK and the rate file inside PRTRATE.

```bash
mockymock run examples/imsmod/PRTINQ.cbl --cut examples/imsmod/PRTINQ.cut \
    --copybook-path examples/imsmod
```

The suite catches changes that unit suites of either program cannot see:

- PRTRATE matching the wrong record: the backorder case reports 30 days
  instead of 14;
- PRTSTK reading its LINKAGE with `PIC 9(5)` for an on-hand the caller
  passes as `PIC 9(7)`: the on-hand reads 200 instead of 2.

`mockymock generate src/PRTINQ.cbl --real PRTSTK.cbl --real PRTRATE.cbl`
scaffolds a suite that runs to the end: its one `MOCK CALL "CBLTDLI"`
answers `QC` only to a `GU`, read from the function code it captures, so
the `ISRT` replies still succeed.
