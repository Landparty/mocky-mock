# NIST COBOL-85 CALL examples

These examples are driven straight from the **cobol-parser** project's
example corpus (`examples/cobol/` — the public-domain NIST COBOL-85
validation suite). They exercise mockymock's headline boundary — a static
subprogram `CALL` — against real, unmodified test-suite programs rather than
hand-written fixtures, and every one compiles and runs for real under
GnuCOBOL in the `mockymock-cobc` container.

| Program | Boundary mocked | Entry point | Source |
|---------|-----------------|-------------|--------|
| `IC101A.CBL` | `CALL "IC102A" USING DN1` + report `WRITE` | `PERFORM CALL-TEST-1 THRU CALL-WRITE-1` | NIST IC (inter-program comms) |
| `IC116M.CBL` | `CALL "IC117M"` | `PERFORM USNG-TEST-01` | NIST IC (CALL without USING) |
| `IC117M.CBL` | `CALL "IC118M"` | `PERFORM USNG-TEST-03` | NIST IC (CALL without USING) |
| `OBIC1A.CBL` | `CALL "OBIC2A"`, `CALL "OBIC3A"` | `PERFORM CALL-IC219` / `PERFORM CALL-FAIL` | NIST OBIC (obsolete language CALL) |

Run one with:

```bash
mockymock run examples/nist-cobol85/IC101A.CBL --cut examples/nist-cobol85/IC101A.cut
```

## Why these programs, and why a `PERFORM ... THRU` entry

The NIST programs are not tidy business modules; each one *is* the CCVS85
self-checking harness. A single program OPENs a `PRINT-FILE`, runs its
feature tests, and WRITEs a formatted pass/fail report, and the paragraphs
**fall through** into that reporting machinery. Two consequences shape these
`.cut` files:

- **Bounded entry.** Driving a whole program from its first paragraph makes
  the report `CLOSE PRINT-FILE` statically reachable — but that file was
  never opened (mockymock doesn't run `OPEN-FILES`), so GnuCOBOL aborts with
  `file not open (status = 42)` at runtime. Several of these `.cut` files use
  `PERFORM <first> THRU <last>` to bound reachability to just the CALL test,
  keeping the run clear of the print machinery. (`IC101A` still mocks the
  report `WRITE` it does reach.)

- **The auto-scaffold is only a starter.** `mockymock generate` emits one
  test case per paragraph, mocking only that paragraph's own boundaries. For
  a CCVS program that is not enough: fall-through reaches the shared
  `WRT-LN` / `PRINT-DETAIL` paragraphs, so an ungenerous scaffold is
  correctly *refused* at run time with `UNMOCKED_FILE_OP`. These curated
  `.cut` files are the hand-finished result.

A wider sweep of the whole cobol-parser example folder — what mocks cleanly,
what refuses, and why — is written up in
[`docs/2026-07-08-cobol-parser-corpus-sweep.md`](../../docs/2026-07-08-cobol-parser-corpus-sweep.md).

## Provenance

The `.CBL` files are copied verbatim from the NIST COBOL-85 test suite as
vendored in the cobol-parser repository (`examples/cobol/`). The suite is a
US Government work and is in the public domain.
