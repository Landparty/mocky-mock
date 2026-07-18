# CUSTPROG — cursor `ROWS` sugar and DCLGEN `EXEC SQL INCLUDE`

A cursor-driven customer lister: `EXEC SQL INCLUDE CUSTREC END-EXEC`
resolves a DCLGEN-style host-variable copybook (with its own embedded
`EXEC SQL DECLARE TABLE` stanza) into real WORKING-STORAGE data items via
`--copybook-path`, then a `DECLARE CURSOR`/`OPEN`/fetch-loop/`CLOSE` walks
it, driven entirely by a `MOCK SQL "FETCH ..." ROWS` block — two DSL
features that, until now, were proven only by a terser regression fixture
(`tests/integration/fixtures/sql_cursor_example/`) rather than a
documented, runnable example.

| Boundary | Statement in CUSTPROG | Mocked by |
|----------|------------------------|-----------|
| Cursor declare | `EXEC SQL DECLARE CUST_CURSOR CURSOR FOR SELECT ... END-EXEC` | `MOCK SQL "DECLARE CUST_CURSOR"` |
| Cursor open | `EXEC SQL OPEN CUST_CURSOR END-EXEC` | `MOCK SQL "OPEN CUST_CURSOR"` |
| Cursor fetch | `EXEC SQL FETCH CUST_CURSOR INTO :CUST-ID, :CUST-NAME END-EXEC` | `MOCK SQL "FETCH CUST_CURSOR" ROWS (...)` |
| Cursor close | `EXEC SQL CLOSE CUST_CURSOR END-EXEC` | `MOCK SQL "CLOSE CUST_CURSOR"` |

Things this example demonstrates on purpose:

- **`ROWS` cursor-fetch sugar.** `MOCK SQL "FETCH CUST_CURSOR" ROWS
  ( CUST-ID = 100, CUST-NAME = "SMITH" ) ( CUST-ID = 101, CUST-NAME =
  "JONES" ) END-MOCK` is sugar for a `FETCH` loop: each row's fields are
  `MOVE`d and `SQLCODE` is set to 0 on the Nth call (matching the mock's
  own tally reaching N); once rows run out, `SQLCODE` is set to 100
  (DB2's "not found" code) — which is exactly what drives `WS-EOF` to
  `"Y"` and ends `FETCH-LOOP` after two customers. No hand-written
  `IF UT-...-TALLY = ...` branching needed in the `.cut` file.
- **DCLGEN-style `EXEC SQL INCLUDE <member>` resolution.** `CUSTREC.CPY`
  is not the generated `SQLCA` — it's an ordinary copybook (resolved via
  `--copybook-path`, same as a plain `COPY`) that happens to contain both
  an `EXEC SQL DECLARE TABLE` stanza (purely declarative, commented out by
  the splicer) and the `01 CUSTREC` host-variable group `FETCH ... INTO
  :CUST-ID, :CUST-NAME` writes into — the classic DCLGEN shape.
- **`VERIFY SQL "FETCH CUST_CURSOR" WAS PERFORMED 3 TIMES`** — two rows
  plus the exhausting `SQLCODE = 100` call — proves the tally counts every
  invocation, not just the ones that returned a row.

Run it:

```bash
mockymock run examples/custprog/CUSTPROG.cbl --cut examples/custprog/CUSTPROG.cut --copybook-path examples/custprog/copybooks
```

Without `--copybook-path`, `EXEC SQL INCLUDE CUSTREC` can't resolve and
the run refuses with `UNRESOLVED_COPYBOOK` — try it to see the fail-closed
behavior.
