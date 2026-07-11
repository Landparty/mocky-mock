# RATERTE — dynamic rate-program routing

A small program that picks one of three interest-rate subprograms
(`STDRATE`/`PRMRATE`/`VIPRATE`) at runtime based on an account tier code,
then calls whichever one it selected through an identifier rather than a
literal program name — the classic COBOL "poor man's polymorphism"
dispatch pattern. It's a worked, business-flavored counterpart to the
bare `tests/integration/fixtures/dynamic_call.cbl` regression fixture.

| Boundary | Statement in RATERTE | Mocked by |
|----------|-----------------------|-----------|
| Dynamic subprogram call | `CALL WS-PGM-NAME USING WS-BALANCE WS-RATE` | `MOCK CALL WS-PGM-NAME` |

Things this example demonstrates on purpose:

- **One bare-identifier mock covers every routing target.** `MOCK CALL
  WS-PGM-NAME` (no quotes — a bare COBOL word mocks a *dynamic* CALL by
  the identifier it calls through) matches the single `CALL WS-PGM-NAME`
  statement no matter which of the three subprogram names
  `1000-SELECT-RATE-PROGRAM` moved into it. The whole `CALL` statement is
  spliced out, so `STDRATE`/`PRMRATE`/`VIPRATE` never need to exist as
  real, compiled subprograms.
- **The mock body branches on the identifier's own runtime value**
  (`IF WS-PGM-NAME = "STDRATE" ...`) to return a different rate per
  target — per-target behavior without any runtime program resolution.
- **`VERIFY CALL WS-PGM-NAME WAS CALLED ...`** mirrors the mock key; the
  tally field is `UT-CALL-WS-PGM-NAME-TALLY`.
- The fourth test case exercises the `EVALUATE`'s `WHEN OTHER` fallback
  (an unrecognized tier still routes to `STDRATE`).

Run it:

```bash
mockymock run examples/raterte/RATERTE.cbl --cut examples/raterte/RATERTE.cut
```

Try changing `EXPECT WS-INTEREST TO BE 300.00` to a wrong value and
re-running to see a FAIL case.
