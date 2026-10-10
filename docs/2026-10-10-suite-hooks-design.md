# Suite hooks: BEFORE-ALL / BEFORE-EACH / AFTER-EACH / AFTER-ALL

## Motivation

JUnit's `@BeforeAll` / `@BeforeEach` / `@AfterEach` / `@AfterAll` let a
suite do expensive or shared setup once, reset per-test state, and clean
up. `.cut` had `BEFORE-ALL` / `BEFORE-EACH`, but they only held shared
`MOCK` blocks, desugared into every case: the names promised a timing
difference that did not exist (see
`2026-07-20-before-blocks-and-file-status-design.md`, which listed
`MOVE`/`PERFORM` inside them as deferred). COBOL programs typically have
an init paragraph (load a rate table, open files, prime counters) that a
test wants run once, and a close paragraph to run at the end.

## Grammar

```
BEFORE-ALL
    [ MOCK ... END-MOCK ]*
    [ MOVE <value> TO <target> | PERFORM <para> [ THRU <para> ] ]*
END-BEFORE
BEFORE-EACH            (same body as BEFORE-ALL)
END-BEFORE
AFTER-EACH
    [ MOVE <value> TO <target> | PERFORM <para> [ THRU <para> ] ]*
END-AFTER
AFTER-ALL              (same body as AFTER-EACH)
END-AFTER
```

At most one of each, all before the first `TESTCASE` (same rule as
before, keeps "everything after a TESTCASE belongs to it"). Steps keep
their written order. `EXPECT`/`VERIFY` stay TESTCASE-only; `MOCK` is not
allowed in `AFTER-*` (the error says where the mock belongs). Existing
`.cut` files parse unchanged.

## Semantics

| Block | When | `UT-CURRENT-CASE` | Mocks in force |
|---|---|---|---|
| BEFORE-ALL | once, before case 1 | `SUITE` | BEFORE-ALL's |
| BEFORE-EACH | start of each case, before its own MOVEs | the case | the case's |
| AFTER-EACH | end of each case, after EXPECT/VERIFY | the case | the case's |
| AFTER-ALL | once, after the last case | `SUITE` | BEFORE-ALL's |

**Each case starts from the state BEFORE-ALL left** (chosen by the user
over "no reset" and "clean each time"): JUnit-like shared setup, while
cases stay isolated from each other. Implemented as a snapshot: the
driver runs `UT-RESET-WORKING-STORAGE`, the BEFORE-ALL steps, then
`UT-SAVE-STATE`; each case runs the reset and then `UT-RESTORE-STATE`.
Without BEFORE-ALL steps nothing changes: no snapshot fields, no extra
paragraphs.

`VERIFY` counts only the case's own `PERFORM`: tallies are zeroed again
after BEFORE-EACH steps when they include a `PERFORM`.

## Snapshot (`splicer/snapshot.py`)

Covers the items `splicer.reset` covers. Copy rules, each one COBOL
defines as exact: groups by a group MOVE into a `PIC X(n)` buffer with n
an upper bound of the group's size (a group move is a byte copy; the
restore copies back exactly the group's own bytes); elementary items by
MOVE through a field with the same PICTURE/USAGE/SIGN; POINTER/INDEX by
SET. The bound is computed here rather than taken from cobol-parser's
`calculate_size`, which undercounted some usages before 2026-09-10 (the
floor is 1.7.7). A group containing `OCCURS ... DEPENDING ON` is refused
(`UNSAVABLE_BEFORE_ALL_STATE`): its size at restore time depends on a
counter the restore itself rewrites. The refusal suggests BEFORE-EACH.

## Static checks

A hook `PERFORM` enters the program exactly like a case's `PERFORM`.
`MockTestSuite.hook_checks()` builds one synthetic `MockTestCase` per
hook PERFORM (EACH hooks: per case, with that case's mocks; ALL hooks:
with BEFORE-ALL's mocks), and `analysis_cases()` adds them to the test
cases. `cli.checks` gates each with `check_test_case` and reports
problems prefixed with the hook, once (deduplicated across cases), with
an `Add to BEFORE-ALL:` / `Add to BEFORE-EACH:` fix hint. Reachability
unions, terminator plans and flow-mock checks iterate `analysis_cases()`.

Shared mocks changed meaning slightly: a BEFORE-* mock is a default, so
a case that doesn't reach it is no longer refused; it is refused
(`UNMATCHED_MOCK`) only when no case and no hook step reaches it. Without
this, a mock that exists for a BEFORE-ALL step (the main use) would be
refused in every case.

## Dispatch

`injector.dispatch_entries(suite)` lists one WHEN branch per case plus
`WHEN "SUITE"` with BEFORE-ALL's mocks when the suite has ALL steps.
Both the boundary dispatch and the MOCK PARAGRAPH/SECTION dispatch use
it.

## Not done

- Integration tests: the integration tier (real GnuCOBOL) is not run in
  CI and the toolchain image could not be built where this was written.
  Generated shapes are pinned by `tests/unit/test_suite_hooks.py` and
  checked by `mockymock export` output; run `python -m pytest
  tests/integration` locally before relying on it.
- Restoring OCCURS ... DEPENDING ON groups.
- Hook steps in `mockymock generate --fill` (fill only edits TESTCASEs).
