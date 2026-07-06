# mockymock

Mocks a COBOL program's external boundaries — subprogram `CALL`s (including
the MQ API), file I/O (`OPEN`/`CLOSE`/`READ`/`WRITE`/`REWRITE`/`DELETE`/
`START`/`UNLOCK`), `EXEC SQL`, `EXEC CICS`, `EXEC DLI`, and console
`ACCEPT` — compiles the instrumented copy with GnuCOBOL, runs it, and
reports pass/fail.

See `docs/2026-06-30-mockymock-mvp-design.md` for the original CALL-only
design, `docs/2026-07-05-mock-all-boundaries-design.md` for the v2
all-boundaries design, and `docs/2026-07-06-dynamic-call-mocks-design.md`
for identifier-keyed dynamic CALL mocks.

## The `.cut` DSL at a glance

```
TESTSUITE "INVUPDT all boundary categories"

TESTCASE "totals two records then updates and notifies"
    MOCK OPEN INV-FILE
    END-MOCK
    MOCK READ INV-FILE
        IF UT-READ-INV-FILE-TALLY > 2
            MOVE "Y" TO WS-EOF
        ELSE
            MOVE 5 TO INV-QTY
        END-IF
    END-MOCK
    MOCK WRITE RPT-REC
    END-MOCK
    MOCK CLOSE INV-FILE
    END-MOCK
    MOCK SQL "UPDATE INVENTORY"
        MOVE 0 TO SQLCODE
    END-MOCK
    MOCK MQ "MQPUT"
        MOVE 0 TO MQ-COMPCODE
    END-MOCK
    MOCK ACCEPT WS-CONFIRM
        MOVE "Y" TO WS-CONFIRM
    END-MOCK
    PERFORM MAIN-PROCESS
    EXPECT WS-TOTAL-QTY TO BE 10
    VERIFY READ INV-FILE WAS PERFORMED 3 TIMES
    VERIFY SQL "UPDATE INVENTORY" WAS PERFORMED ONCE
    VERIFY MQ "MQPUT" WAS CALLED ONCE
```

- `MOCK CALL "X"` / `MOCK MQ "X"` (sugar — MQ is invoked through static
  CALLs) / `MOCK SQL "<prefix>"` / `MOCK CICS "<prefix>"` /
  `MOCK DLI "<prefix>"` take a quoted key; SQL/CICS/DLI keys prefix-match
  the statement's normalized text.
- `MOCK CALL WS-PGM-NAME` (bare COBOL word) mocks a **dynamic** CALL by
  the identifier it calls through — the whole statement is replaced, so
  the runtime target never needs resolving, and the mock body can branch
  on the identifier's value (`IF WS-PGM-NAME = "PGMA" ...`) for
  per-target behavior. `VERIFY CALL WS-PGM-NAME WAS CALLED ...` mirrors
  it; the tally field is `UT-CALL-<IDENTIFIER>-TALLY`.
- `MOCK OPEN|CLOSE|READ|DELETE|START|UNLOCK <file>` and
  `MOCK WRITE|REWRITE <record>` take a bare COBOL name (WRITE/REWRITE name
  the record, matching COBOL's own syntax); `MOCK ACCEPT <data-name>` mocks
  console input.
- Every mock gets a tally field (`UT-...-TALLY`, visible to mock bodies —
  handy for driving EOF off the read count) that `VERIFY ... WAS
  CALLED|PERFORMED ONCE | AT LEAST ONCE | NEVER | <n> TIMES` asserts on.
- `EXEC SQL INCLUDE SQLCA END-EXEC` is replaced with a generated SQLCA, so
  mock bodies can set `SQLCODE`.
- Lines starting with `*>` are comments.

`mockymock generate <program.cbl>` scaffolds a starter `.cut` covering
every mockable boundary it finds.

Boundary statements nested inside IF/EVALUATE/inline-PERFORM bodies
(including nested EXEC blocks) are mockable when the statement sits on its
own line(s) — the common layout. Still refused, fail-closed: dynamic
CALLs whose target identifier the parser cannot determine,
`SORT`/`MERGE`/`RELEASE`/`RETURN`, `PERFORM ... THRU`,
nested statements sharing a line with other code (`IF X CALL "F" END-IF`
one-liners), statements inside another boundary statement's clause body
(`READ ... AT END`, `CALL ... ON EXCEPTION`), and mocks with clause bodies
of their own — each refusal names the exact layout problem. `DISPLAY`
passes through unmocked. See the worked example in `examples/invupdt/`.

## Setup

Requires a running Docker daemon (Docker Desktop on Windows/macOS). COBOL
is compiled and executed inside a GnuCOBOL container — nothing runs on the
host, and no local GnuCOBOL install is needed.

```bash
python -m venv .venv
.venv/Scripts/activate   # or source .venv/bin/activate on macOS/Linux
pip install -r requirements-dev.txt
mockymock setup           # builds the GnuCOBOL image, starts mockymock-cobc
python -m pytest tests/unit -v
```

`tests/integration/` additionally requires the Docker daemon to be
reachable and is skipped automatically if it isn't. `mockymock run` brings
the container up on its own, so `mockymock setup` is optional.

### Windows notes

On Windows, ensure Docker Desktop is running before invoking `mockymock setup` or
`mockymock run`. COBOL compilation and execution happen entirely inside the container.
