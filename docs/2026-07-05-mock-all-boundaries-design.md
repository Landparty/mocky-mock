# mockymock v2 — Mock All Boundaries

**Status:** Implemented on branch `mock-all-boundaries`.
**Date:** 2026-07-05
**Builds on:** `2026-06-30-mockymock-mvp-design.md` (v1: static CALL only) and
`2026-07-04-docker-toolchain-design.md` (Docker-only compile/run).

## 1. Goal

v1 mocks only static `CALL "LITERAL"` statements and *refuses* any test case
whose reachable paragraphs touch file I/O, EXEC SQL/CICS/DLI, or console
ACCEPT. v2 turns every one of those detected-but-refused boundaries into a
first-class mockable category, so a test case can mock **all** of a
paragraph's external resources: subprogram calls (including MQ API calls),
file reads/writes, SQL, CICS, IMS/DLI, and console input.

The splicing mechanism is unchanged (comment out the real statement, splice
an `EVALUATE UT-CURRENT-CASE` dispatch block with a tally counter). What v2
adds is: a category-generic DSL, a full boundary-site inventory with AST
statement references, per-category matching rules, category-generic codegen,
and the DATA DIVISION `EXEC SQL INCLUDE SQLCA` transform SQL programs need
to compile under GnuCOBOL.

## 2. Mock categories

| Category | Directive | Site matched | Match key |
|----------|-----------|--------------|-----------|
| CALL | `MOCK CALL "<name>"` | static `CALL "<name>"` | called program literal |
| MQ (alias) | `MOCK MQ "<name>"` | same as CALL | MQ API program literal (`MQPUT`, `MQGET`, …) |
| OPEN | `MOCK OPEN <file>` | `OPEN … <file> …` | `<file>` ∈ statement's `file_names` |
| CLOSE | `MOCK CLOSE <file>` | `CLOSE … <file> …` | `<file>` ∈ statement's `file_names` |
| READ | `MOCK READ <file>` | `READ <file> …` | statement `file_name` |
| WRITE | `MOCK WRITE <record>` | `WRITE <record> …` | statement `record_name` |
| REWRITE | `MOCK REWRITE <record>` | `REWRITE <record> …` | statement `record_name` |
| DELETE | `MOCK DELETE <file>` | `DELETE <file> …` | statement `file_name` |
| START | `MOCK START <file>` | `START <file> …` | statement `file_name` |
| UNLOCK | `MOCK UNLOCK <file>` | `UNLOCK <file>` | statement `file_name` |
| SQL | `MOCK SQL "<prefix>"` | `EXEC SQL … END-EXEC` | prefix of whitespace-normalized, uppercased SQL text |
| CICS | `MOCK CICS "<prefix>"` | `EXEC CICS … END-EXEC` | prefix of normalized command+options text |
| DLI | `MOCK DLI "<prefix>"` | `EXEC IMS`/`EXEC DLI … END-EXEC` | prefix of normalized command text |
| ACCEPT | `MOCK ACCEPT <data-name>` | console `ACCEPT <data-name>` | ACCEPT target identifier |

`MOCK MQ` is deliberately thin sugar: mainframe MQ is invoked through static
`CALL 'MQPUT' USING …` etc., so MQ mocking **is** CALL mocking. The alias
exists so `.cut` files read at the right level of intent, and so
`mockymock generate` can label MQ boundaries distinctly. The known MQ API
names (`MQCONN`, `MQOPEN`, `MQGET`, `MQPUT`, `MQPUT1`, `MQCLOSE`, `MQDISC`,
`MQCMIT`, `MQBACK`, …) are flagged in the mock surface.

`VERIFY` generalizes the same way — the key syntax after `VERIFY` mirrors
the `MOCK` key syntax, and `WAS CALLED`/`WAS PERFORMED` are interchangeable:

```
VERIFY "DISCRATE" WAS CALLED ONCE          *> v1 back-compat (CALL implied)
VERIFY CALL "DISCRATE" WAS CALLED ONCE
VERIFY READ INFILE WAS PERFORMED 3 TIMES
VERIFY SQL "UPDATE ORDERS" WAS PERFORMED AT LEAST ONCE
VERIFY WRITE OUT-REC WAS PERFORMED NEVER
```

`.cut` files also now allow `*>` comment lines (the scaffold generator emits
guidance comments).

## 3. Matching rules

- A **directive matches a site** per the table above. SQL/CICS/DLI use
  case-insensitive, whitespace-collapsed **prefix** matching so
  `MOCK SQL "UPDATE ORDERS"` distinguishes `UPDATE ORDERS …` from
  `UPDATE CUSTOMERS …` without requiring the author to reproduce the whole
  statement.
- One directive may match **several sites** (e.g. two `READ INFILE`
  statements in different paragraphs get the same mock body — same behavior
  v1 already had for two `CALL "X"` sites).
- A site matching **two or more directives** of the same test case is
  refused (`AMBIGUOUS_MOCK`) — fail closed rather than pick one.
- Every **reachable** boundary site must be matched by exactly one directive
  of each test case that reaches it, else `UNMOCKED_CALL` /
  `UNMOCKED_FILE_OP` / `UNMOCKED_SQL` / `UNMOCKED_CICS` / `UNMOCKED_DLI` /
  `UNMOCKED_CONSOLE_ACCEPT`. Rationale unchanged from v1: an unmocked CALL
  cannot link; unmocked file I/O would hit a nonexistent file in the
  sandbox; unmocked EXEC cannot compile; unmocked console ACCEPT reads
  whatever stdin is attached.
- A directive matching **no reachable site** is refused (`UNMATCHED_MOCK`).
- A directive whose matched site is **nested** (inside IF/EVALUATE branches,
  inline PERFORM bodies, IO clause bodies) is refused
  (`UNSUPPORTED_NESTED_MOCK_TARGET`) — same splice-span limitation as v1's
  nested CALL rule, now uniform across categories: cobolparser has no
  location data for block terminators, so a nested statement's replacement
  span cannot be bounded safely.

## 4. Category-specific mechanics

### 4.1 File I/O

The FILE SECTION (SELECT/FD) is left untouched. Because every reachable
OPEN/CLOSE/READ/WRITE/… is replaced by its mock body, the file is never
actually opened, and no real file needs to exist in the sandbox. GnuCOBOL
allocates FD record areas statically, so mock bodies can freely `MOVE`
into/out of record areas of never-opened files (verified by integration
test, not assumed).

Practical authoring pattern for a read loop — the tally field is visible to
mock bodies, so EOF can be driven off the invocation count:

```
MOCK READ INFILE
    IF UT-READ-INFILE-TALLY > 2
        MOVE "Y" TO WS-EOF
    ELSE
        MOVE "ACME CORP" TO IN-CUSTOMER-NAME
    END-IF
END-MOCK
```

Note the mock body **replaces the whole statement including its AT END /
INVALID KEY / NOT AT END clauses** — the span runs to the next top-level
statement boundary, which is exactly v1's CALL-with-ON-EXCEPTION behavior.
The mock author owns the flag/record effects those clauses used to produce.

`SORT`/`MERGE`/`RELEASE`/`RETURN` remain **refused**
(`UNSUPPORTED_SORT_MERGE`): mocking a SORT means mocking an algorithm plus
its INPUT/OUTPUT PROCEDURE contract, not a boundary statement; out of scope.

Unreachable, unmocked file I/O compiles fine and is never executed, so it is
left in place (unchanged from v1's per-testcase philosophy).

### 4.2 EXEC SQL / CICS / DLI

GnuCOBOL cannot compile raw `EXEC SQL`/`EXEC CICS`/`EXEC DLI` blocks (they
need a precompiler that isn't part of the toolchain), so reachability is not
enough: **every** EXEC site in the PROCEDURE DIVISION is stubbed out
program-wide. Mocked sites get the normal dispatch block; unmocked
(necessarily unreachable, or the refusal gate already fired) sites get a
runtime trap:

```
DISPLAY "__MOCKYMOCK__ ERROR: unmocked EXEC SQL reached (line N)"
ADD 1 TO UT-FAIL-COUNT
```

A **nested** EXEC anywhere in the program is a whole-program refusal
(`NESTED_EXEC`): it must be stubbed for the program to compile, and nested
statements cannot be stubbed safely (§3).

DATA DIVISION EXEC SQL is handled textually by a new pre-compile transform:

- `EXEC SQL INCLUDE SQLCA END-EXEC` → replaced with a generated standard
  SQLCA group item (so mock bodies can `MOVE 0 TO SQLCODE`,
  `MOVE 100 TO SQLCODE`, …).
- `EXEC SQL BEGIN/END DECLARE SECTION END-EXEC` → commented out (host
  variables between them are plain COBOL and stay).
- `EXEC SQL DECLARE … TABLE … END-EXEC` → commented out (declarative only).
- `EXEC SQL INCLUDE <anything-else> END-EXEC` → whole-program refusal
  (`UNSUPPORTED_DATA_DIVISION_EXEC`), same spirit as `UNRESOLVED_COPYBOOK`.

`DECLARE CURSOR` sits in the PROCEDURE DIVISION as an `ExecSQLStatement`
like any other and is stubbed/mocked normally (mocking `OPEN`/`FETCH`/
`CLOSE` is what carries behavior; a mocked cursor DECLARE is typically an
empty body).

### 4.3 Console ACCEPT

`MOCK ACCEPT WS-USER-INPUT` replaces the ACCEPT statement with the dispatch
block; the body is typically one `MOVE "…" TO WS-USER-INPUT`. Non-console
ACCEPT sources (DATE/TIME/COMMAND-LINE/…) stay unmocked and unrefused,
exactly as v1 classified them.

### 4.4 DISPLAY

Still passthrough, still not mocked (unchanged v1 posture): DISPLAY output
is multiplexed with the `__MOCKYMOCK__` protocol on stdout and simply
ignored by the report parser. Capturing/asserting DISPLAY output remains
future work.

## 5. Implementation shape

- `dsl/model.py` — `MockCategory` enum + one generic
  `MockDirective(category, key, body_lines)`; `VerifyDirective` gains
  `category`. (`MockCallDirective` is gone; this API is repo-internal.)
- `dsl/parser.py` — grammar per §2, `*>` comments, quoted keys for
  CALL/MQ/SQL/CICS/DLI and bare COBOL words for file ops/ACCEPT.
- `analysis/mock_surface.py` — emits `BoundarySite(category, key,
  match_text, paragraph_name, line, nested, statement)` for every category,
  keeping v1's `CallSite` shape folded in; MQ names flagged; SORT/MERGE
  tracked as their own category for the refusal gate.
- `analysis/refusal.py` — per-case gate re-implemented over generic
  directive↔site matching (§3); whole-program checks gain `NESTED_EXEC` and
  the DATA DIVISION SQL rules.
- `splicer/naming.py` — deterministic `(category, key)` → `UT-…-TALLY`
  registry (sanitized, length-capped, collision-suffixed) shared by
  injector, driver, and mock-body authors.
- `splicer/injector.py` — `build_dispatch(directive_key, suite)`
  generalizing v1's `build_call_dispatch`.
- `splicer/driver.py` — tally declarations/resets and VERIFY conditions per
  `(category, key)`.
- `splicer/sqlca.py` — the DATA DIVISION transform of §4.2.
- `splicer/orchestrator.py` — the span-collection/splice loop moved out of
  `cli/main.py`, generalized to all categories + program-wide EXEC trap
  stubs.
- `dsl/generator.py` — scaffolds one TESTCASE per paragraph covering all of
  its mockable sites, with placeholder bodies and `*>` hints; labels MQ.
- `cli/main.py` — wires the above; `generate` reports remaining
  unsupported boundaries (dynamic CALL, SORT/MERGE, nested sites).

## 6. What stays refused

| Code | Why |
|------|-----|
| `PARSE_ERROR`, `UNRESOLVED_COPYBOOK` | unchanged from v1 |
| `DYNAMIC_CALL` | target unknown at parse time; still future work |
| `UNSUPPORTED_PERFORM_THRU` | range expansion still unverified |
| `UNSUPPORTED_NESTED_MOCK_TARGET` | no terminator locations (was `UNSUPPORTED_NESTED_CALL_TARGET`) |
| `UNSUPPORTED_SORT_MERGE` | SORT/MERGE/RELEASE/RETURN not boundary-shaped |
| `NESTED_EXEC` | must stub for compile, cannot stub nested |
| `UNSUPPORTED_DATA_DIVISION_EXEC` | non-SQLCA INCLUDE / unknown WS EXEC SQL |
| `AMBIGUOUS_MOCK` | one site, several matching directives |

## 7. Testing

- Unit: every module above (grammar round-trips, surface inventory per
  category, each refusal code both firing and not firing, dispatch/driver
  codegen goldens, SQLCA transform, orchestrator span math).
- Integration (Docker): a new example program exercising CALL + MQ CALL +
  sequential file READ/WRITE + EXEC SQL + console ACCEPT end-to-end,
  compiled and executed in the `mockymock-cobc` container; asserts real
  PASS/FAIL parsing, including the FD-record-area-without-OPEN assumption of
  §4.1.
