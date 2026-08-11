# The `.cut` file: directive reference

The `.cut` file is a small DSL, not YAML/JSON/TOML -- it's how you tell
mockymock which boundaries to mock, what data to move in first, which
paragraph to run, and what to assert afterward.

## Top-level shape

```
TESTSUITE "<name>"

[ PROVIDER <name>
      HEADER <col>, ...
      ROW <value>, ... ]*

[ BEFORE-ALL
      MOCK ... END-MOCK
  END-BEFORE ]

[ BEFORE-EACH
      MOCK ... END-MOCK
  END-BEFORE ]

TESTCASE "<name>" [ TAGS "<tag>" ... ] [ USING PROVIDER <name> ]
    [ MOCK <category> <key> ... END-MOCK ]*
    [ MOVE <value> TO <target> ]*
    PERFORM <paragraph> [ THRU|THROUGH <paragraph> ]
    [ EXPECT <data-name> TO BE <value> ]*
    [ VERIFY [<category>] <key> WAS CALLED|PERFORMED <expectation> ]*
```

Rules that matter in practice:

- Exactly one `TESTSUITE` per file, at most one `BEFORE-ALL` and one
  `BEFORE-EACH`, exactly one `PERFORM` per `TESTCASE`.
- Every keyword is case-sensitive uppercase, **except** `END-MOCK`/
  `END-BEFORE` (case-insensitive, optional trailing period -- `end-mock.`
  is fine).
- Lines starting with `*>` are comments outside a `MOCK` body; inside a
  body they pass through as ordinary COBOL comments.

## `TESTSUITE "<name>"`

One per file. The suite's display name.

## `TESTCASE "<name>" [TAGS "<tag>" ...] [USING PROVIDER <name>]`

One test case. Options:

- `TAGS "<tag>" ["<tag>" ...]` -- attaches selection tags, used by
  `run --tag` and shown in `collect`'s output. Purely for selection; no
  runtime effect.
- `USING PROVIDER <name>` -- binds this case as a template that gets
  expanded once per row of the named `PROVIDER` block (see below).

## `MOCK <category> <key> ... END-MOCK`

Declares what happens when the program reaches one boundary. Two key
syntaxes, split by category:

| Category | Key syntax | Example |
|---|---|---|
| `CALL` (static) | quoted literal | `MOCK CALL "DISCRATE"` |
| `CALL` (dynamic, called through a variable) | bare identifier | `MOCK CALL WS-PGM-NAME` |
| `MQ` (sugar for `CALL`) | quoted literal | `MOCK MQ "MQPUT"` |
| `SQL`, `CICS`, `DLI` | quoted literal (prefix of the statement text) | `MOCK SQL "UPDATE INVENTORY"` |
| `OPEN`, `CLOSE`, `READ`, `WRITE`, `REWRITE`, `DELETE`, `START`, `UNLOCK` | bare file/record name | `MOCK OPEN INV-FILE`, `MOCK WRITE RPT-REC` |
| `ACCEPT` | bare data-name | `MOCK ACCEPT WS-CONFIRM` |
| `PARAGRAPH`, `SECTION` | bare paragraph/section name | `MOCK PARAGRAPH CALC-TOTALS` |

The body between `MOCK` and `END-MOCK` is free-form COBOL, spliced in
verbatim when that boundary is reached (typically `MOVE` statements
setting return codes, SQLCODE, or output fields):

```
MOCK CALL "DISCRATE"
    MOVE 0.15 TO WS-DISCOUNT-RATE
END-MOCK
```

`PARAGRAPH`/`SECTION` mocks replace the whole body of that paragraph or
section, letting you isolate a caller from its own collaborators.

### `ROWS` -- multi-row cursor sugar (`SQL` and `READ` only)

For a `SQL` cursor `FETCH` loop or a sequential `READ` loop that should
return a fixed sequence of rows and then signal exhaustion:

```
MOCK SQL "FETCH CUST_CURSOR" ROWS
    ( CUST-NAME = "ALICE", CUST-BAL = 100.00 )
    ( CUST-NAME = "BOB",   CUST-BAL = 250.50 )
END-MOCK
```

```
MOCK READ INV-FILE ROWS
    ( INV-QTY = 5 )
    ( INV-QTY = 12 )
    TERMINAL ( WS-EOF = "Y" )
END-MOCK
```

- Each `( FIELD = value, ... )` group is one row, returned in order on
  successive calls.
- `TERMINAL ( FIELD = value, ... )` (`READ` only, optional, at most one)
  sets the fields for the rows-exhausted branch. If your loop guard is a
  flag set by the program's own `AT END` clause (not the file status),
  put that flag's `MOVE` here too, or the loop will never terminate.
- `SQL`'s exhausted branch is fixed (`SQLCODE = 100`, DB2's "not found"
  code) and needs no `TERMINAL` group.
- `ROWS` is only valid on `SQL` and `READ`; using it elsewhere is a parse
  error.

## `MOVE <value> TO <target>`

Sets up working-storage before the test runs, evaluated in file order (a
later `MOVE` to the same target wins, same as COBOL):

```
MOVE 100 TO WS-ORDER-QTY
MOVE "ACTIVE" TO WS-STATUS
```

## `PERFORM <paragraph> [THRU|THROUGH <paragraph>]`

The entry point for the test case -- exactly one per `TESTCASE`:

```
PERFORM MAIN-PROCESS
PERFORM VALIDATE-INPUT THRU VALIDATE-INPUT-EXIT
```

## `EXPECT <data-name> TO BE <value>`

An assertion checked after `PERFORM` returns:

```
EXPECT WS-TOTAL-QTY TO BE 10
EXPECT WS-TABLE(1, 2) TO BE "Y"
```

Subscripts (`FIELD(1, 2)` or `FIELD(1:5)` reference modification) are
supported for both the data-name and the `MOVE` target above; qualified
names (`FIELD OF RECORD`) are not.

## `VERIFY [<category>] <key> WAS CALLED|PERFORMED <expectation>`

Asserts how many times a boundary was reached. `CALLED` and `PERFORMED`
are interchangeable. `<expectation>` is one of:

| Expectation | Meaning |
|---|---|
| `ONCE` | Exactly one call. |
| `NEVER` | Zero calls. |
| `AT LEAST ONCE` | One or more calls. |
| `<n> TIMES` | Exactly `n` calls. |

```
VERIFY READ INV-FILE WAS PERFORMED 3 TIMES
VERIFY WRITE RPT-REC WAS PERFORMED NEVER
VERIFY CALL "DISCRATE" WAS CALLED ONCE
```

A bare `VERIFY "X" WAS CALLED ...` with no category keyword defaults to
`CALL` (kept for backward compatibility).

## `FILE-STATUS IS <mnemonic-or-"code">`

Usable once, inside a `MOCK OPEN|CLOSE|READ|DELETE|START|UNLOCK` body
(not `WRITE`/`REWRITE`). Sets the file-status field mockymock generates
for that file.

| Mnemonic | File status code |
|---|---|
| `SUCCESS` | `00` |
| `END-OF-FILE` | `10` |
| `DUPLICATE-KEY` | `22` |
| `RECORD-NOT-FOUND` | `23` |
| `FILE-NOT-FOUND` | `35` |
| `ALREADY-OPEN` | `41` |
| `NOT-OPEN` | `42` |
| `NO-CURRENT-RECORD` | `43` |

A quoted two-character code also always works, e.g. `FILE-STATUS IS "92"`.
Every eligible category gets an implicit `MOVE "00"` (success) before its
own body automatically, whether or not `FILE-STATUS IS` is used -- you
only need this directive to signal something *other* than success.

```
MOCK OPEN INV-FILE
    FILE-STATUS IS FILE-NOT-FOUND
END-MOCK
```

## `BEFORE-ALL` / `BEFORE-EACH ... END-BEFORE`

Shared `MOCK` directives, declared once and applied to every `TESTCASE` in
the suite -- useful when most cases need the same boundary mocked the
same way, with only a few needing to override it. Precedence on a
collision is `TESTCASE`'s own mock > `BEFORE-EACH` > `BEFORE-ALL`. The
two blocks differ *only* in that precedence -- there's no timing
difference despite the xUnit-style names.

```
BEFORE-EACH
    MOCK OPEN INV-FILE
    END-MOCK
END-BEFORE

TESTCASE "override for one case"
    MOCK OPEN INV-FILE
        FILE-STATUS IS FILE-NOT-FOUND
    END-MOCK
    ...
```

## `PROVIDER <name>` / `HEADER` / `ROW` -- parameterized test cases

Runs the same `TESTCASE` body once per row of a data table, substituting
`{ColumnName}` placeholders into that case's `MOVE` and `EXPECT` values
only (mock bodies, `PERFORM` target, and `VERIFY` stay identical across
every row):

```
PROVIDER StateCodes
    HEADER State, ExpectedRegion
    ROW "NY", "NORTHEAST"
    ROW "CA", "WEST"
    ROW "TX", "SOUTH"

TESTCASE "region lookup" USING PROVIDER StateCodes
    MOVE "{State}" TO WS-STATE-CODE
    PERFORM LOOKUP-REGION
    EXPECT WS-REGION TO BE "{ExpectedRegion}"
```

This expands into three ordinary test cases, named
`"region lookup [row 1: NY]"`, etc. `PROVIDER` must be declared before any
`TESTCASE` that references it.

## `*> STUB EXPECT <data-name> [-- <note>]`

Not new grammar -- an ordinary `*>` comment convention. Write it where a
real `EXPECT` would go, for a field whose correct value you don't know
yet:

```
TESTCASE "computes total"
    MOCK READ INV-FILE
        MOVE 5 TO INV-QTY
    END-MOCK
    PERFORM MAIN-PROCESS
    *> STUB EXPECT WS-TOTAL-QTY -- computed in CALC-TOTALS
```

Run `mockymock run ... --record-expectations` to turn every such stub into
a real `EXPECT <name> TO BE <value>` line, filled in with the value the
program actually produced.
