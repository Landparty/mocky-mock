# CPYPROC — a PROCEDURE DIVISION copybook invoked via PERFORM

Every other copybook example (`tests/integration/fixtures/copybook_example/`,
`examples/custprog/`) resolves a copybook that supplies **data** —
WORKING-STORAGE fields or DCLGEN host variables. CPYPROC instead supplies
**procedure logic**: `copybooks/CALCPERF.CPY` is one whole paragraph,
`CALC-DISCOUNT`, copied straight into `CPYPROC.cbl`'s PROCEDURE DIVISION and
invoked with an ordinary `PERFORM` — the idiomatic mainframe pattern for
sharing business logic across programs (what cobol-check's docs and most
shops call a "procedure copybook").

`--copybook-path` expands `COPY` **textually, before parsing** — the same
mechanism the data-copybook examples use. By the time `CALC-DISCOUNT` reaches
analysis and splicing, it is an ordinary paragraph indistinguishable from one
typed inline: nothing about reachability, boundary-mocking, or flow-target
mocking is copybook-aware, because none of it runs until after expansion has
already happened. That means both of mockymock's paragraph-testing strategies
apply to a copybook-sourced paragraph exactly as they would to a local one.

| Testing strategy | `.cut` shape | What it proves |
|---|---|---|
| **Direct** — unit test the copybook's own logic | `PERFORM CALC-DISCOUNT` as the case's entry point, `MOCK CALL "DISCRATE"` for the boundary the copybook itself touches | Test case 1: the copybook's paragraph works correctly in isolation, independent of any caller |
| **Collaborator** — stub the copybook out while testing its caller | `PERFORM MAIN-PROCESS`, `MOCK PARAGRAPH CALC-DISCOUNT` to replace it, `VERIFY PARAGRAPH CALC-DISCOUNT WAS PERFORMED ONCE` | Test case 2: `MAIN-PROCESS`'s own logic (`WS-ORDER-COUNT`) is correct without executing the real copybook body at all |
| **Collaborator, unmocked** — same caller, real copybook body | `PERFORM MAIN-PROCESS`, `MOCK CALL "DISCRATE"` (the copybook's own boundary, now reachable) | Test case 3: confirms the flow mock in case 2 wasn't just hiding a gap — the real copybook body still needs (and gets) its own boundary mock when not stubbed, same lesson as `examples/flowmock/` |

Run it:

```bash
mockymock run examples/cpyproc/CPYPROC.cbl --cut examples/cpyproc/CPYPROC.cut --copybook-path examples/cpyproc/copybooks
```

Without `--copybook-path`, this refuses with `UNRESOLVED_COPYBOOK` before any
splicing is attempted — same fail-closed behavior as every other copybook
example, whether the copybook holds data or procedure logic.

Try `mockymock generate examples/cpyproc/CPYPROC.cbl --copybook-path examples/cpyproc/copybooks` on a copy of this program with no `.cut` file: the scaffolder groups boundary sites by paragraph name *after* expansion, so it proposes a `TESTCASE "CALC-DISCOUNT boundaries: ..."` with `PERFORM CALC-DISCOUNT` and a placeholder `MOCK CALL "DISCRATE"` — it finds the copybook's own paragraph the same way it finds any other.
