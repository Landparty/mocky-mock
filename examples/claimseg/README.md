# CLAIMSEG — raw `EXEC DLI` claim retrieval and payment insert

A small IMS DL/I batch program that retrieves a claim segment (`GU`) and,
if found, inserts a payment segment (`ISRT`) — written using the `EXEC
DLI...END-EXEC` statement form rather than the `CALL 'CBLTDLI'` style
`examples/real-world/ACCTPRG` and `examples/real-world/DEPTIMSM` use. It's
the first worked example to prove `MOCK DLI` end-to-end: mockymock has
classified `EXEC DLI`/`EXEC IMS` as a boundary category since the v2
all-boundaries design, but until now — like `EXEC CICS` before
`examples/custinq` — no example proved it compiles and runs for real.

| Boundary | Statement in CLAIMSEG | Mocked by |
|----------|------------------------|-----------|
| Segment retrieval | `EXEC DLI GU SEGMENT(CLAIM-SEG) INTO(WS-CLAIM-AMOUNT) END-EXEC` | `MOCK DLI "GU"` |
| Segment insert | `EXEC DLI ISRT SEGMENT(PAYMENT-SEG) FROM(WS-CLAIM-AMOUNT) END-EXEC` | `MOCK DLI "ISRT"` |

Things this example demonstrates on purpose:

- **No IMS DL/I runtime or preprocessor needed.** `EXEC DLI` blocks are
  boundary statements mockymock splices out entirely before compilation —
  mocked ones become the test case's mock body, unmocked-but-reachable
  ones become a trap stub (same mechanism as `EXEC SQL`/`EXEC CICS`, see
  `.okf/splicer.md`). GnuCOBOL never sees a raw `EXEC DLI` block, so this
  compiles and runs in the plain `mockymock-cobc` container.
- **`MOCK DLI "<prefix>"` prefix-matches**, exactly like `MOCK SQL`/`MOCK
  CICS`: `"GU"` matches the normalized `EXEC DLI GU ...` text.
- **A mock body sets fields the real statement's own clauses never
  touch** (e.g. `WS-CLAIM-STATUS`, not part of `GU`'s own `INTO` target) —
  the same pattern `examples/custinq`'s CICS `READ` mock and
  `examples/invupdt`'s file `READ` mock both use.
- **Static reachability still requires a mock for unreached code**: the
  third test case never actually inserts (`WS-CLAIM-FOUND` is `"N"`), but
  because `ISRT` sits inside an `IF` that is still *statically* reachable
  from `2000-POST-PAYMENT`, it still needs a `MOCK DLI "ISRT"` — verified
  via `VERIFY DLI "ISRT" WAS PERFORMED NEVER`. This is the same
  reachability-driven-refusal lesson `examples/invupdt`'s unreached
  `WRITE` teaches for file I/O (see `.okf/analysis.md`).
- **`GOBACK` neutralization**: the last test case drives `0000-MAIN`, the
  program's real entry point, through its full `PERFORM` chain rather
  than a sub-paragraph — see
  `docs/2026-07-08-goback-stop-run-support-design.md`.

Run it:

```bash
mockymock run examples/claimseg/CLAIMSEG.cbl --cut examples/claimseg/CLAIMSEG.cut
```
