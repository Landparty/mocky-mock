# ORDRPROC example

A minimal program that calls an external `DISCRATE` subprogram to get a
discount rate, then computes a net amount. Demonstrates v1's only
mockable category: static CALL.

```bash
mockymock run ORDRPROC.cbl --cut ORDRPROC.cut
```

Try changing `EXPECT WS-NET-AMOUNT TO BE 90.00` to a wrong value and
re-running to see a FAIL case, or `mockymock generate ORDRPROC.cbl` to see
what auto-scaffolding produces for this program from scratch.
