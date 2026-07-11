# CUSTINQ — CICS customer inquiry

A small CICS transaction program that looks up a customer record, flags a
low balance, and returns control to CICS. It's the first `EXEC CICS`
worked example in this repo: mockymock has supported `MOCK CICS` since the
v2 all-boundaries design, but until now no example proved it compiles and
runs for real.

| Boundary | Statement in CUSTINQ | Mocked by |
|----------|----------------------|-----------|
| CICS file read | `EXEC CICS READ DATASET("CUSTFILE") ... END-EXEC` | `MOCK CICS "READ"` |
| CICS transaction return | `EXEC CICS RETURN END-EXEC` | `MOCK CICS "RETURN"` |

Things this example demonstrates on purpose:

- **No CICS translator needed.** `EXEC CICS` blocks are boundary
  statements mockymock splices out entirely before compilation — whether
  mocked (replaced with the test case's mock body) or, if reachable but
  unmocked, replaced with a trap stub (see `.okf/splicer.md`). GnuCOBOL
  never sees a raw `EXEC CICS` block, so this program compiles and runs in
  the plain `mockymock-cobc` container with no CICS runtime or
  preprocessor — the same mechanism that already lets `MOCK SQL`/`MOCK
  DLI` work.
- **`MOCK CICS "<prefix>"` prefix-matches**, exactly like `MOCK SQL`/`MOCK
  DLI`: `"READ"` matches the normalized `EXEC CICS READ ...` text.
- **A mock body can set fields the real `EXEC CICS READ` never touches**
  (e.g. `WS-CUST-BALANCE`, not part of the statement's own `INTO`
  target) — the same pattern INVUPDT's `READ` mock uses for its FD
  record area.
- **`GOBACK` neutralization**: the last test case drives `0000-MAIN`, the
  program's real entry point, through its full `PERFORM` chain
  (`1000-LOOKUP-CUSTOMER` → `2000-CHECK-BALANCE` → `9000-END-TRANSACTION`
  → `GOBACK`) rather than a sub-paragraph — see
  `docs/2026-07-08-goback-stop-run-support-design.md`.

Run it:

```bash
mockymock run examples/custinq/CUSTINQ.cbl --cut examples/custinq/CUSTINQ.cut
```
