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
      [ MOCK ... END-MOCK ]*
      [ MOVE <value> TO <target> | PERFORM <paragraph> [ THRU <paragraph> ] ]*
  END-BEFORE ]

[ BEFORE-EACH
      [ MOCK ... END-MOCK ]*
      [ MOVE <value> TO <target> | PERFORM <paragraph> [ THRU <paragraph> ] ]*
  END-BEFORE ]

[ AFTER-EACH
      [ MOVE <value> TO <target> | PERFORM <paragraph> [ THRU <paragraph> ] ]*
  END-AFTER ]

[ AFTER-ALL
      [ MOVE <value> TO <target> | PERFORM <paragraph> [ THRU <paragraph> ] ]*
  END-AFTER ]

TESTCASE "<name>" [ TAGS "<tag>" ... ] [ USING PROVIDER <name> ]
    [ MOCK <category> <key> ... END-MOCK ]*
    [ MOVE <value> TO <target> ]*
    PERFORM <paragraph> [ THRU|THROUGH <paragraph> ]
    [ EXPECT <data-name> [NOT] TO BE [GREATER|LESS THAN [OR EQUAL TO]] <value> ]*
    [ VERIFY [<category>] <key> WAS CALLED|PERFORMED <expectation> ]*
```

Rules that matter in practice:

- Exactly one `TESTSUITE` per file, at most one each of `BEFORE-ALL`,
  `BEFORE-EACH`, `AFTER-EACH` and `AFTER-ALL` (all before the first
  `TESTCASE`), exactly one `PERFORM` per `TESTCASE`.
- Setup `MOVE`s go above the `PERFORM`, `EXPECT`/`VERIFY` below it; the
  other order is a parse error (they would silently run on the wrong side
  of it). `MOCK` directives can go anywhere in the case.
- Every keyword is case-sensitive uppercase, **except** `END-MOCK`/
  `END-BEFORE`/`END-AFTER` (case-insensitive, optional trailing period --
  `end-mock.` is fine).
- Lines starting with `*>` are comments outside a `MOCK` body; inside a
  body they pass through as ordinary COBOL comments.

## `TESTSUITE "<name>"`

One per file. The suite's display name.

## `TESTCASE "<name>" [TAGS "<tag>" ...] [USING PROVIDER <name>]`

One test case. Options:

- `TAGS "<tag>" ["<tag>" ...]` -- attaches selection tags, used by
  `run --tag` and shown in `collect`'s output. Purely for selection; no
  runtime effect. It may also follow `USING PROVIDER <name>`; give it once.
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
| `INITIATE`, `GENERATE`, `TERMINATE` (Report Writer) | bare report name (GENERATE: report or detail-group name) | `MOCK GENERATE DETAIL-LINE` |
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

### `ROWS` -- one response per call (`SQL`, `READ`, `RETURN`, `CALL`, `MQ`, `DLI`)

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

A plain `MOCK CALL` body answers every call of that key the same way. When
one routine is called for different purposes in one run -- IMS `CBLTDLI`
used for a priming GHN, a DLET and the loop's next GHN, an `MQGET` loop, a
DB2 access module called in a loop -- give it `ROWS` instead, one row per
call in the order the program makes them:

```
MOCK CALL "CBLTDLI" ROWS
    ( CUST-STATUS = SPACES, CUST-IO-CIF = "C000000001", CUST-IO-STATUS = "CL" )
    ( CUST-STATUS = SPACES )
    TERMINAL ( CUST-STATUS = "GB" )
END-MOCK
```

- Each `( FIELD = value, ... )` group is one row, returned in order on
  successive calls. Rows only `MOVE` values; anything else (a `SET`, an
  `IF`) needs a plain mock body.
- For `CALL`/`MQ`/dynamic `CALL`/`DLI`, rows count the calls of that key
  across **every** call site in the test case (row 2 is the second
  `CBLTDLI` call wherever it happens), restarting at row 1 in each test
  case. `run --trace` prints the order mocks fired in, if you need to
  check it.
- `TERMINAL ( FIELD = value, ... )` answers every call after the last
  row. It is **required** for `CALL`/`MQ`/`DLI` (give the end-of-data
  response, e.g. `GB`, or the loop never ends), optional for `READ`, and
  needed for `RETURN`. The program's own `AT END` clause runs once the
  rows run out (see below), so its end-of-data flag needs no `MOVE`
  here.
- `SQL`'s exhausted branch is fixed (`SQLCODE = 100`, DB2's "not found"
  code) and takes no `TERMINAL` group.
- `CAPTURE ARG` still works inside a `CALL ... ROWS` body.
- `ROWS` on any other category is a parse error.

### A mock replaces the statement, not its clauses

A `MOCK` replaces the I/O or the call itself. The program's own clause
bodies still run after the mock body, picked by the outcome the mock
reports, the way the real statement would pick them:

| Clause | Runs when the mocked outcome is |
|---|---|
| `AT END` | end of file (status `1x`, e.g. `"10"`) |
| `INVALID KEY` | invalid key (status `2x`, e.g. `"23"`) |
| `NOT AT END` / `NOT INVALID KEY` | success (status `0x`, the default) |
| `NOT ON EXCEPTION` (CALL) | success (the default) |
| `ON EXCEPTION` (CALL) | `"EX"` |

This covers `READ`, `RETURN`, `WRITE`, `REWRITE`, `DELETE`, `START` and
`CALL`. The outcome is the file's own FILE STATUS field after the mock
body, so `FILE-STATUS IS RECORD-NOT-FOUND` runs `INVALID KEY` and an
exhausted `ROWS` mock runs `AT END`. A mock that sets nothing reports
success.

So a mock supplies the record, and the program's own `NOT AT END` does
the rest:

```
       READ PURGE-PARM-FILE
           AT END
               MOVE "Y" TO WS-EOF
           NOT AT END
               MOVE PURG-CUTOFF-DATE TO WS-CUTOFF-DATE
       END-READ
```

```
MOCK READ PURGE-PARM-FILE
    MOVE "20260101" TO PURG-CUTOFF-DATE    *> NOT AT END copies it on
END-MOCK
```

When there is no FILE STATUS field to report through (a file without
one, or a `CALL`), set the outcome field `UT-MOCK-STATUS` in the mock
body instead. It starts at `"00"` in every mocked call:

```
MOCK READ PARM-FILE                *> no FILE STATUS clause
    IF UT-READ-PARM-FILE-TALLY > 2
        MOVE "10" TO UT-MOCK-STATUS    *> runs the program's AT END
    ELSE
        MOVE "ACME CORP" TO PARM-NAME
    END-IF
END-MOCK

MOCK CALL "RATESUB"
    MOVE "EX" TO UT-MOCK-STATUS        *> runs the CALL's ON EXCEPTION
END-MOCK
```

A body may hold a `GO TO`: it runs in the same paragraph, so it jumps
where it always did. A body ended by the sentence period may leave an
`IF` open; the period closes it, as in the program.

A mocked statement is **refused** (`UNLIFTABLE_CLAUSE_BODY`) when one of
its clause bodies cannot run safely in place: when it holds another
boundary statement (a `CALL`, file I/O, `EXEC`), `GOBACK`, `STOP RUN`,
`EXIT PROGRAM`, `ALTER`, `NEXT SENTENCE` or `CANCEL`, a nested
conditional phrase such as `ON SIZE ERROR` not closed by its own
`END-<verb>`, or an `IF` with no `END-IF` before the next clause; and for
`WRITE ... AT END-OF-PAGE`. Splicing the mock would delete every body of
the statement with it. Move that code out of the clause (set a flag in
it and act on the flag after the statement).

### `CAPTURE ARG <n> INTO <target>` -- argument capture (`CALL`/dynamic `CALL` only)

Captures the real value a mocked `CALL` was passed, so you can assert on
it with an ordinary `EXPECT`:

```
MOCK CALL "DISCRATE"
    CAPTURE ARG 1 INTO WS-CAPTURED-RATE
    MOVE 0 TO RETURN-CODE
END-MOCK
...
PERFORM CALC-DISCOUNT
EXPECT WS-CAPTURED-RATE TO BE 0.15
```

- `<n>` is 1-based and positional (the CALL's Nth `USING` argument), not
  a COBOL variable name -- it works even if different call sites of the
  same mocked key use differently-named arguments.
- If the mocked `CALL` runs more than once in one `TESTCASE` (e.g. inside
  a loop), the captured field ends up holding the *last* call's value.
- Only valid inside `MOCK CALL`/`MOCK MQ` bodies; using it elsewhere is a
  parse error.

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

This single line is what decides whether a case is a paragraph test or a
whole-program test. `PERFORM VALIDATE-INPUT` exercises that paragraph
alone, so a failure can only come from it; `PERFORM 0000-MAIN` (the
program's entry paragraph) drives the entire `PERFORM` chain, with every
boundary reachable through it needing a `MOCK`. Build the paragraph
cases first -- see `paragraph-first-workflow.md`.

## `EXPECT <data-name> [NOT] TO BE [<comparison>] <value>`

An assertion checked after `PERFORM` returns:

```
EXPECT WS-TOTAL-QTY TO BE 10
EXPECT WS-TABLE(1, 2) TO BE "Y"
EXPECT WS-STATUS NOT TO BE "99"
EXPECT WS-COUNT TO BE GREATER THAN 0
EXPECT WS-RATE TO BE LESS THAN OR EQUAL TO 0.15
```

The relation phrase is one of (each also negatable with a leading `NOT`,
e.g. `NOT TO BE GREATER THAN` asserts `<=`):

| Phrase | Asserts |
|---|---|
| `TO BE` | `=` |
| `TO BE GREATER THAN` | `>` |
| `TO BE LESS THAN` | `<` |
| `TO BE GREATER THAN OR EQUAL TO` | `>=` |
| `TO BE LESS THAN OR EQUAL TO` | `<=` |

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

`MOCK CICS` works the same way: the command's own `RESP(item)` and
`RESP2(item)`, and `EIBRESP` / `EIBRESP2` when the program uses them, get
an implicit `MOVE 0` (`DFHRESP(NORMAL)`) before the body, as real CICS
sets them on every command. Set them in the body to signal a condition,
e.g. `MOVE DFHRESP(NOTFND) TO WS-RESP`.

```
MOCK OPEN INV-FILE
    FILE-STATUS IS FILE-NOT-FOUND
END-MOCK
```

## Suite hooks: `BEFORE-ALL` / `BEFORE-EACH` / `AFTER-EACH` / `AFTER-ALL`

Like JUnit's `@BeforeAll` / `@BeforeEach` / `@AfterEach` / `@AfterAll`.
The steps are `MOVE` and `PERFORM` lines, run in the order written:

| Block | Runs | Steps run with the mocks of |
|---|---|---|
| `BEFORE-ALL ... END-BEFORE` | once, before the first test case | `BEFORE-ALL` |
| `BEFORE-EACH ... END-BEFORE` | at the start of every test case, before its own `MOVE`s | that test case |
| `AFTER-EACH ... END-AFTER` | at the end of every test case, after its `EXPECT`/`VERIFY` | that test case |
| `AFTER-ALL ... END-AFTER` | once, after the last test case | `BEFORE-ALL` |

**Every test case starts from the state `BEFORE-ALL` left behind.**
mockymock saves WORKING-STORAGE, LOCAL-STORAGE and the file records right
after `BEFORE-ALL` and restores them at the start of each case, so a
one-time `PERFORM 0100-INIT` is set up once and no case sees what an
earlier case changed. A program whose state can't be saved exactly (a
group holding an `OCCURS ... DEPENDING ON` table) is refused with
`UNSAVABLE_BEFORE_ALL_STATE`: use `BEFORE-EACH` for that setup instead.

`VERIFY` counts only the test case's own `PERFORM`: calls a `BEFORE-EACH`
step made are not counted.

```
BEFORE-ALL
    MOCK CALL "LOADRATE"
        MOVE 1.25 TO WS-RATE
    END-MOCK
    PERFORM 0100-INIT
END-BEFORE

BEFORE-EACH
    MOVE 0 TO WS-TOTAL
END-BEFORE

AFTER-ALL
    PERFORM 9000-CLOSE-FILES
END-AFTER
```

A hook `PERFORM` is checked like a test case's own: a boundary it reaches
needs a `MOCK` (in `BEFORE-ALL` for the `-ALL` hooks, in `BEFORE-EACH` or
the test case for the `-EACH` ones), and the refusal says where to add it.

### Entry parameters (`PROCEDURE DIVISION USING`)

A subprogram's parameters (`PROCEDURE DIVISION USING ...`, `ENTRY ...
USING ...`, `RETURNING ...`) are ordinary fields in a test: mockymock never
CALLs the program, so it turns the LINKAGE SECTION into storage the test
owns. Set entry values with `MOVE` (in the `TESTCASE`, `BEFORE-EACH` or
`BEFORE-ALL`) and check what the program wrote back with `EXPECT`. They
are reset before every test case like WORKING-STORAGE, and saved after
`BEFORE-ALL` like it too.

```
BEFORE-EACH
    MOVE "CUST0001" TO LS-CUST-ID
    MOVE 500.00 TO LS-LIMIT
END-BEFORE

TESTCASE "over the limit"
    MOVE 600.00 TO LS-AMOUNT(1)
    PERFORM 1000-CHECK
    EXPECT LS-RC TO BE 8
```

### Shared mocks

`MOCK` blocks in `BEFORE-ALL`/`BEFORE-EACH` are also defaults for every
`TESTCASE` -- useful when most cases need the same boundary mocked the
same way. Precedence on a collision is the `TESTCASE`'s own mock >
`BEFORE-EACH` > `BEFORE-ALL`. A shared mock only has to be reached by
some test case or hook step, not by every one. `AFTER-EACH`/`AFTER-ALL`
hold no `MOCK` blocks.

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
