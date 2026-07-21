# TAXFILE — BEFORE-EACH scoping and FILE-STATUS sugar

Adapted from the cobol-check wiki's own taxpayer-update-file example: a
program that opens a file, validates a postal code, and reports one of
two error codes.

| Feature | Demonstrated by |
|---------|-----------------|
| `BEFORE-EACH` shared mocks | `MOCK OPEN`/`MOCK READ`/`MOCK CLOSE TAXPAYER-FILE` declared once, applying to all three cases |
| `TESTCASE` overrides `BEFORE-EACH` | Case 2 overrides `OPEN`; case 3 overrides `READ` — each keeps the other two shared mocks |
| `FILE-STATUS IS <mnemonic>` | Case 2's `FILE-STATUS IS FILE-NOT-FOUND` |
| Implicit default-success status | Case 1's `MOCK OPEN` has an empty body — `WS-TAXPAYER-STATUS` still ends up `"00"` |

Things this example demonstrates on purpose:

- **A `BEFORE-EACH` mock still has to be reachable from every case's
  `PERFORM` target**, exactly like a hand-typed one — `MAIN-PROCESS`
  performs `OPEN-FILE`, `VALIDATE-IN-REC`, and `CLOSE-FILE`
  unconditionally in source order (the `IF` around `VALIDATE-IN-REC` is a
  *runtime* guard; static reachability doesn't evaluate it), so all three
  boundaries need mocks in every case even though case 2 never actually
  reaches the `READ` at runtime.
- **`TESTCASE` silently overrides `BEFORE-EACH`, not an error** — case 2
  redeclares `MOCK OPEN TAXPAYER-FILE`; the shared one from `BEFORE-EACH`
  simply doesn't apply to that case.
- **`VERIFY` works on a `BEFORE-EACH`-only mock** — case 1's
  `VERIFY OPEN/CLOSE TAXPAYER-FILE` reference mocks it never declared
  itself.

Run it:

```bash
mockymock run examples/taxfile/TAXFILE.cbl --cut examples/taxfile/TAXFILE.cut
```
