# A dynamic CALL can reach a real program (2026-11-02)

## Problem

`USE REAL CALL "X" FROM "x.cbl"` (docs/2026-11-01-real-call-integration-design.md)
linked X into the test binary, but only a static `CALL "X"` ran it. A
program reached through `CALL WS-PGM` stayed mocked, so a change inside it
was never run: in the oraclemix end-to-end run, DYNDRV calls RATECALC through
`WS-RATE-PGM` and a change to RATECALC's rate compared as *same*.

## Behaviour

A case that has `USE REAL CALL "X"` (in the TESTCASE or a BEFORE block) runs
X for real at a dynamic CALL site whenever the CALL's identifier holds `X`
when it runs. Any other value goes to the site's `MOCK CALL <identifier>`,
as before. The splice of a dynamic CALL site becomes:

```cobol
EVALUATE TRUE
    WHEN (UT-CURRENT-CASE = "001"
      OR UT-CURRENT-CASE = "002"
      ) AND FUNCTION UPPER-CASE(WS-RATE-PGM)
            = "RATECALC"
        ADD 1 TO <tally of CALL "RATECALC">
        CALL WS-RATE-PGM USING WS-RATE-AREA     *> the statement as written
    WHEN OTHER
        <the usual EVALUATE UT-CURRENT-CASE mock dispatch>
END-EVALUATE
```

* The statement runs as written: GnuCOBOL resolves the name at run time to
  the program linked into the binary, which is also how a static real CALL
  resolves. Its ON EXCEPTION clauses run as part of it; when the site has
  lifted clauses, `UT-MOCK-STATUS` is set to SPACES first so the guard after
  the mock dispatch selects none.
* `VERIFY CALL "X"` counts the real calls made through the identifier too.
* The `MOCK CALL <identifier>` stays required: the gate cannot know which
  value the identifier holds, so the mock answers every other name.
* Gate: a reached dynamic CALL site marks the case's USE REAL CALL
  directives as used (no UNMATCHED_MOCK), and `matched_directive_ids` counts
  them for any program that has a dynamic CALL site, so the entry program's
  view keeps them.
* `generate --real X.cbl` needs no change: it adds `USE REAL CALL "X"` and
  X's placeholder mocks, and keeps `MOCK CALL WS-PGM`.

## Callers

LegacyLens' integration-test plan adds every resolved dynamic CALL target
with source to a run unit's real programs, so its pack and change-impact
oracle suites run them.

## Lookup records in real subprograms

`generate --real` answers a real program's READ with a placeholder that
returns end-of-file at once, so a lookup routine (`PRTRATE`: read until
`IF RATE-PART = LK-PART`) never ran its "found" path. `dsl/real_branches.py`
finds every `IF <record field> = <LINKAGE item>` on a file the real program
READs and adds one TESTCASE per match: the suite's first case again, with
its own `MOCK READ <file>` that returns a record holding the caller's value
(`MOVE LK-PART TO RATE-PART`, other fields from their PICTUREs) and then the
placeholder's end-of-file answer. The mock body runs inside the real program,
so it can name its LINKAGE items.
