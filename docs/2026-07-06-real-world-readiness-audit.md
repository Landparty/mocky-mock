# mockymock — Real-World Readiness Audit

Date: 2026-07-06
Author: audit prepared for Samuel Dion
Status: assessment (no code changes proposed here; each finding pairs a
severity with a one-line "what closing it takes")

---

## Scope assumption (read this first — it reorders everything)

"Real world" means different missing-lists depending on who runs this. This
audit assumes the **primary** intended scope is the one implied by the
LegacyLens context: *mockymock run as an automated component of a
modernization pipeline, over customer COBOL the author has never seen, at
scale.* Under that scope, **parser robustness on unseen code** and
**generating usable tests without hand-authored `.cut` files** dominate; DSL
ergonomics matter less.

Where the scope is instead **a standalone developer tool** that a mainframe
engineer installs and hand-drives, the ranking flips: packaging, docs, and
authoring ergonomics rise toward the top and the parser/scale items relax
(a human notices a dropped statement; a pipeline does not).

Findings are tagged `[pipeline]`, `[standalone]`, or `[both]` where the
weight differs.

---

## Verdict

mockymock is a **legitimate, well-engineered logic-testing harness** with an
unusually disciplined fail-closed design — it refuses what it can't do
loudly rather than guessing. For its designed sweet spot (regression-testing
the *control flow and call structure* of a COBOL program during a refactor),
it works today.

It is **not yet ready to certify that a program behaves correctly**, for two
reasons that sit above everything else: (1) it asserts against GnuCOBOL
semantics, which are not IBM Enterprise COBOL / z/OS semantics; and (2) its
correctness is hostage to an unpinned, non-PyPI parser that already has bugs
which break real programs — the flagship "real-world" example
(`DEPTMQP`) **ships `xfail` and does not pass today**.

The single most damning data point in the repo: `examples/real-world/DEPTMQP`
was added specifically to prove production-shaped complexity, and its
integration test is `@pytest.mark.xfail(strict=True)` because cobol-parser
drops a `CALL 'MQOPEN'` from the AST
(`tests/integration/test_realworld_deptmqp_example.py`).

---

## Finding 1 — The fidelity ceiling: a green suite means "correct under GnuCOBOL," not "correct on z/OS" `[both]` · Severity: **critical / structural**

mockymock compiles with GnuCOBOL 3.2 in Docker (`docker/Dockerfile`,
`debian:trixie-slim` + `gnucobol`) and asserts on that binary's runtime
behavior. GnuCOBOL is not the compiler the code will actually run under in
production. A passing test certifies behavior *under GnuCOBOL's dialect and
runtime*, which transfers to the mainframe only for some classes of logic.

**Transfers well (the real value):**
- Control flow, `PERFORM` structure, paragraph reachability.
- CALL / mock invocation counts and ordering (`VERIFY ... WAS CALLED N TIMES`).
- Branching logic driven by simple conditions and `MOVE`s.
- "Did my refactor change which subprograms get called, and how often" — the
  safety-net use case.

**Does *not* reliably transfer (silent-confidence risk):**
- **EBCDIC vs ASCII collation** — GnuCOBOL compares in ASCII. `IF` comparisons
  on alphanumerics, condition-name (`88`) ranges, and `SORT` order can differ
  from z/OS. A test that passes on ASCII ordering can be wrong on EBCDIC.
- **COMP-3 / zoned-decimal sign and edge behavior** — packed-decimal sign
  nibbles, overpunch signs, and truncation edges differ between runtimes.
- **Intermediate arithmetic precision** — `COMPUTE`/rounding intermediate
  precision rules differ; IBM's are specific and not GnuCOBOL's.
- **Numeric-edited PICTURE clauses**, IBM intrinsic functions, and IBM
  language extensions.

**Why this is finding #1 and not a footnote:** it is a *silent* failure mode.
Every other coverage gap in this document is loudly refused; this one hands
you a green checkmark that may not hold on the target platform. The tool
should say, in user-facing docs, exactly which claims a pass supports.

**What closing it takes:** it cannot be fully "closed" without an IBM
compiler in the loop (licensing/host access — out of reach for most). The
achievable mitigation is *honesty*: a "What a passing mockymock run does and
does not prove" section in the README, and optionally a documented
"logic-only" positioning. If higher fidelity is ever required, the path is a
z/OS or Micro Focus toolchain option behind the same runtime interface
(`runtime/compiler.py` / `executor.py` are already reduced to stable
dataclass contracts, so a second toolchain is architecturally feasible).

---

## Finding 2 — Parser fragility is a hard blocker on real code `[pipeline]` · Severity: **critical / blocker**

mockymock's whole surface (`analysis/mock_surface.py`, `analysis/refusal.py`,
`splicer/`) is built on ~30 pinned cobol-parser AST attributes
(`interface-contract.md`). Two problems make this the tallest pole for
pipeline use:

**2a. The parser has bugs that silently drop statements — the worst outcome
for a test tool.** Because GnuCOBOL compiles the *whole file* regardless of
which paragraph a test targets, one dropped statement fails the entire
compile (or worse, leaves raw `EXEC SQL` text that never gets stubbed):
- `COMPUTE` without an explicit terminator swallows the following statement →
  `CALL 'MQOPEN'` vanishes from DEPTMQP's AST → the example ships `xfail`
  (`test_realworld_deptmqp_example.py`; upstream follow-up `task_24002e6a`).
- cobol-parser silently drops `EXEC SQL` `UPDATE`/`INSERT` statements from
  the AST with no parse error → the `ACCTMNT` candidate was **dropped
  entirely** from the real-world example set
  (`docs/2026-07-06-realworld-cobol-examples-design.md`, "Revision";
  follow-up `task_c5e3b268`).

On unseen customer code at scale, "the parser occasionally drops a statement
with no error" is not an edge case — it is the expected failure distribution.

**2b. The dependency is unpinned and un-distributable.** cobol-parser is
**not on PyPI**; it is installed as an editable sibling
(`requirements-dev.txt`: `-e ../cobol-parser`). There is no version pin, so
the AST contract mockymock depends on can drift underneath it, guarded only
by a hand-maintained `interface-contract.md`. CI has to check the sibling
repo out with a PAT and flags this as a known gap
(`.github/workflows/ci.yml`).

**What closing it takes:** (a) pin cobol-parser to an exact commit/version
and vendor a pinned snapshot rather than an editable sibling (the CI comment
already lists this as the mitigation); (b) treat the interface contract as a
tested contract (contract tests that fail when an attribute changes shape),
not prose; (c) upstream the COMPUTE terminator and dropped-`EXEC SQL` fixes
before claiming real-world DB2 coverage. Until 2a is fixed, DB2-heavy and
`COMPUTE`-heavy programs are not reliably testable.

---

## Finding 3 — Program terminators (`STOP RUN` / `GOBACK`) reached from a test kill the run — and `GOBACK` isn't even acknowledged `[both]` · Severity: **high**

**Partially resolved 2026-07-08** — see
[docs/2026-07-08-goback-stop-run-support-design.md](2026-07-08-goback-stop-run-support-design.md).
A terminator reachable through a chain of plain, unconditional `PERFORM`
calls is now neutralized and the test case completes normally; `GO
TO`-reachable and `SECTION`-scoped terminators still refuse rather than
crash. The remainder of this finding is kept below for history.

A `.cut` test case `PERFORM`s a target paragraph inside the program's *own*
compilation unit. If that target reaches a program terminator — directly or
transitively — the whole compiled test binary exits immediately, before the
case's own `EXPECT`/`VERIFY` run and before any later case in the suite runs
at all. mockymock now *reports* this honestly as `[CRASH]` instead of a
misleading `[PASS]` (`report/results.py` `crashed`/`ended`), but the
underlying limitation is unchanged: **you cannot test any paragraph that
reaches a terminator.**

This matters because real batch programs' main entry points almost always
end in a terminator. In practice you can only test *sub*-paragraphs, and you
must already know the call graph well enough to avoid the terminator — which
also means **the real top-level driver loop (e.g. `READ ... UNTIL WS-EOF` in
`0000-MAIN-PROCESS`) usually cannot be exercised at all**; the DEPTMQP/DEPTMQC
examples explicitly trade loop-iteration depth for harness safety by
targeting single sub-paragraphs
(`docs/2026-07-06-realworld-cobol-examples-design.md`, "Driving strategy").

**Newly confirmed gap:** the code reasons only about `STOP RUN`. A grep of
`mockymock/` shows **no handling of `GOBACK` or `EXIT PROGRAM` anywhere**.
Because the driver always `PERFORM`s the target (the program is the main run
unit), `GOBACK` behaves exactly like `STOP RUN` under GnuCOBOL and kills the
binary the same way — but there is not even the `STOP RUN`-level
crash-detection awareness for it, and no refusal warns the `.cut` author
before the run. Real subprograms terminate with `GOBACK` far more often than
`STOP RUN`, so this is the common case, not the rare one.

**What closing it takes:** (short term) a **static refusal** — reachability
analysis already walks the call graph (`analysis/refusal.py`
`_reachable_paragraphs`); extend it to detect a terminator (`STOP RUN`,
`GOBACK`, `EXIT PROGRAM`) reachable from a `perform_target` and refuse *at
analysis time* with a precise message, instead of discovering it as a runtime
`[CRASH]`. (Longer term) support calling the program as a unit, or intercept
terminators, so top-level flows become testable.

---

## Finding 4 — Silent-correctness risks: cases where a passing test can be *wrong* `[both]` · Severity: **high**

The worst outcome for a test tool is a false green. Beyond Finding 1's
dialect ceiling, three in-tool behaviors can produce a passing-but-wrong
result and deserve to be grouped and weighted above any loudly-refused gap:

- **`reset.py` `INITIALIZE` drops group children's `VALUE` clauses.** Between
  test cases, WORKING-STORAGE is reset; a group with no `VALUE` of its own is
  reset with `INITIALIZE`, which zero-fills numeric / space-fills alphanumeric
  children and **does not restore their declared `VALUE`s** (`splicer.md`,
  "Known v1 fidelity limit"). This already bit the real examples: mock bodies
  that `MOVE MQCC-FAILED TO ...` silently got `0` instead of `2` in the second
  test case, producing a "wrong-but-plausible passing-looking result until
  traced through raw stdout" (`realworld-cobol-examples-design.md`). The
  documented workaround — "always use bare literals, never named constants" —
  is a sharp edge every `.cut` author must know or be silently misled.
- **Parser drops statements with no error** (Finding 2a) — when it drops a
  *mockable* boundary rather than breaking the compile, the boundary silently
  isn't there to mock or verify.
- **Phantom `"."`-paragraph handling is version-fragile.** cobol-parser emits
  a paragraph literally named `"."` after `EXEC ... END-EXEC`; mockymock
  filters these positionally (`analysis.md`, `source_map.py`). The OKF notes
  that if a future parser version ever attributed real statements to one, the
  reachability picture shifts. Filtering keyed on a parser quirk is a
  standing correctness dependency on parser internals.

Reset also uses type-default fill for no-`VALUE` elementary items rather than
true "undefined" memory (`reset.py`) — a deliberate divergence for
determinism, but one that can *mask* an uninitialized-variable bug that would
surface on the mainframe.

**What closing it takes:** make `INITIALIZE` restore children's `VALUE`
clauses (walk the group recursively and emit per-child `MOVE`s); add contract
tests that fail when the parser drops a known statement shape; and document
the reset-fidelity and named-constant traps in *user-facing* docs, not just
design notes.

---

## Finding 5 — Coverage gaps that are *safely* refused (a strength, not a defect) `[both]` · Severity: **medium (scope-limiting, not risky)**

These are things mockymock cannot do, but refuses loudly and fail-closed —
so they limit *applicability* without risking a false green. Weight them
below the silent risks above.

| Unsupported construct | Behavior | Real-world impact |
|---|---|---|
| `SORT` / `MERGE` / `RELEASE` / `RETURN` | refused `UNSUPPORTED_SORT_MERGE` | common in batch; whole test refused if reachable |
| Dynamic `CALL` with unresolvable identifier | refused `DYNAMIC_CALL` | resolvable dynamic calls *are* supported (`DYNCALL`) |
| CICS | **resolved 2026-07-10** — proven end-to-end (`EXEC CICS READ`/`RETURN`, splice-and-replace, no CICS translator needed) via `examples/custinq/`, `test_custinq_example.py` | closed |
| IMS DL/I | classified but **never attempted** — `LINKAGE`/`ENTRY 'DLITCBL'` vs the `PERFORM`-only driver is unverified | IMS programs unsupported in practice |
| `EXEC SQL INCLUDE <member>` (non-SQLCA) | **resolved 2026-07-09** via `--copybook-path` — see [docs/2026-07-09-sql-v1-include-cursor-rows-design.md](2026-07-09-sql-v1-include-cursor-rows-design.md) | closed |
| `EXEC SQL DECLARE CURSOR` in WORKING-STORAGE | **resolved** — DECLARE CURSOR is commented out declaratively; OPEN/FETCH/CLOSE handled by generic boundary-mocking machinery | closed |
| Unresolved `COPY` | refused `UNRESOLVED_COPYBOOK` | requires every copybook supplied via `--copybook-path` |
| Boundary statements sharing a line, or nested inside another boundary's clause body (`READ ... AT END CALL ...`) | refused | forces the common one-statement-per-line layout |

**Partially resolved 2026-07-09** — the non-SQLCA `EXEC SQL INCLUDE
<member>` row above is closed (host-variable copybooks now resolve the
same way `COPY` does); the `EXEC SQL DECLARE CURSOR` row was already
closed by an earlier `sqlca.py` change (DECLARE CURSOR is commented out
declaratively; OPEN/FETCH/CLOSE were always handled by the generic
boundary-mocking machinery). The remaining rows in this table are
unaffected.

**What closing it takes:** each is its own project (SORT/MERGE modeling; the
IMS `ENTRY DLITCBL` driving model; cursor support via `task_d610057b`). The
right near-term move is a **user-facing "Supported COBOL subset" document**
so adopters know the boundaries before they hit a refusal — today those
boundaries live in design docs and OKF concepts, not where an end user
looks.

**Correction, 2026-07-10:** this paragraph originally listed "a CICS
translation/stub layer" as needed engine work for the CICS row above. That
assumption was never actually tested and turned out to be wrong: `EXEC
CICS` is spliced out entirely before compilation via the same
splice-and-replace mechanism already used for `EXEC SQL`/`EXEC DLI` (see
`.okf/splicer.md`) — GnuCOBOL never sees a raw `EXEC CICS` block, so no
translator or stub layer was ever required. Closing the row only needed a
worked example proving the existing mechanism, not new engine work.

---

## Finding 6 — Test-authoring ergonomics and assertion power `[standalone]` · Severity: **medium**

Writing a correct `.cut` today requires internal knowledge that a mainframe
developer wouldn't have without training:
- Know which paragraphs are reachable and which reach a terminator (Finding 3).
- Schema-qualified SQL needs a **space after the period**
  (`MOCK SQL "INSERT INTO BANK. TRANSACTION_HIST"`) because the parser
  tokenizes `BANK.ACCOUNT` as three tokens
  (`realworld-cobol-examples-design.md`).
- Use bare literals, never named constants, in mock bodies (Finding 4).
- `EXPECT` is **equality only** — no ranges, comparisons, substring, or
  tolerance; no way to assert on the *arguments* a mocked `CALL` received
  (only tally counts), and no cross-mock ordering assertions.
- Silent footguns in the DSL: an unterminated `MOCK` body doesn't error (it
  swallows the rest of the file); a second `PERFORM` in a case silently
  wins over the first (`dsl.md`, Gotchas).

**What closing it takes:** richer assertions (comparison operators, argument
capture/spies on mocked CALLs); a `.cut` linter that flags unterminated
mocks, duplicate `PERFORM`s, terminator-reaching targets, and the SQL-period
quirk before a run; and surfacing the sharp edges in a user tutorial. The
`generate` scaffolder already lowers the authoring barrier — leaning into it
(auto-mocking transitively-reached boundaries, not just a paragraph's own)
would help more.

---

## Finding 7 — Distribution, CI, and operational readiness `[both]` · Severity: **medium–high**

- **Not installable standalone.** No PyPI; `pyproject.toml` marks it
  `Development Status :: 3 - Alpha`, and install requires the sibling
  cobol-parser checkout. Adoption today effectively requires the whole
  LegacyLens workspace layout.
- **Hard Docker dependency, no fallback.** The local-`cobc` toolchain was
  deleted deliberately (`runtime.md`); if the daemon is down the CLI exits 1.
  In locked-down enterprise/CI environments (Docker Desktop licensing,
  rootless-only, air-gapped) this is a real adoption barrier with no
  alternative path.
- **Green CI does not prove the compile-and-run path.** Integration tests
  self-skip when `docker info` fails (`tests/integration/_docker.py`), so a
  passing run on a Docker-less runner exercises only the unit tier
  (`testing.md`). The suite can be green while the end-to-end path is untested.
- **Cross-repo CI checkout is a flagged gap** (PAT / private-repo access,
  `.github/workflows/ci.yml`).
- **No release process / changelog / versioning discipline** beyond
  `version = "0.1.0"`; no `LICENSE` present at repo root.

**What closing it takes:** pin + vendor cobol-parser and publish an
installable artifact; add a CI job (or an explicit gate) that *fails* rather
than skips if Docker is unavailable, so the integration tier can't silently
no-op; add a LICENSE and a release/changelog process.

---

## Finding 8 — Scale and whole-file compilation `[pipeline]` · Severity: **medium**

Everything is proven on 20–430-line programs
(`realworld-cobol-examples-design.md`). Real mainframe programs run to
thousands of lines with deep copybook nesting and dozens of boundaries. Two
structural concerns at that size:
- The splicer is line/AST-offset based over `normalize_fixed_format` output
  (`splicer.md`); more boundaries and deeper nesting mean more chances to hit
  an unspliceable layout or a parser quirk.
- **Whole-file compile is all-or-nothing**: one unsupported construct
  *anywhere* in the file (a raw `EXEC`, a dropped statement, a `SORT`) fails
  or refuses the entire program, regardless of which paragraph the test
  targets (`injector.py` `build_exec_trap`; `analysis.md` `NESTED_EXEC` is
  whole-program). Larger programs are proportionally more likely to contain
  at least one such construct, so the refusal rate rises with program size.

**What closing it takes:** a corpus test against genuinely large programs to
find where the line-based splicer and parser degrade; and, longer term,
reducing whole-file refusal to per-paragraph isolation where feasible.

---

## Finding 9 — Sandbox / security posture for running untrusted code `[pipeline]` · Severity: **medium** (low for standalone, higher for a hosted pipeline)

mockymock compiles and runs arbitrary COBOL — including arbitrary COBOL
spliced in from `.cut` mock bodies — inside a **long-lived** container
(`mockymock-cobc`, `sleep infinity`) with `~/.mockymock/work` bind-mounted
(`runtime.md`). Controls today: a per-run `timeout` (default 30s, layered
host+container) and per-run sandbox `rmtree`.

Not present: memory/CPU limits (`--memory`/`--cpus`), network isolation
(`--network none`), read-only mounts, or per-run container teardown. For a
standalone developer running their own code this is fine; for a **hosted
pipeline running customer code**, arbitrary spliced COBOL with container
filesystem access and no resource caps is a meaningful hardening gap.

**What closing it takes:** run with `--network none`, memory/CPU/pids limits,
a read-only root with a tmpfs work dir, and non-root execution; consider
ephemeral-per-run containers if the ~1s `docker run` cost is acceptable
outside tight test loops.

---

## Finding 10 — Diagnosability `[both]` · Severity: **low–medium**

- A genuine in-container infinite loop and a wedged `docker exec` both
  surface as `exit_code == 124`; only stderr text distinguishes them
  (`runtime.md`).
- An unknown case id in a `FAIL` line is silently dropped, so a malformed /
  truncated stdout stream can lose failure reasons rather than erroring
  (`report.md`, Gotchas — flagged as a still-open gap).
- No coverage reporting: nothing tells you which boundaries/paragraphs a
  suite actually exercised, so gaps in a hand-written `.cut` are invisible.

**What closing it takes:** distinct exit codes / clearer messaging for the two
timeout causes; surface (don't drop) unknown-id FAIL lines; add a
boundary-coverage summary to the report.

---

## Priority summary

| Tier | Findings | Why |
|---|---|---|
| **Blocker** | 1 (fidelity ceiling), 2 (parser fragility incl. DEPTMQP `xfail`) | Until these are addressed/positioned honestly, "certifies correctness" is not a claim the tool can make; DB2/`COMPUTE`-heavy real code breaks today. |
| **High** | 3 (terminators incl. unhandled `GOBACK`), 4 (silent-wrong: reset/`INITIALIZE`, dropped statements), 7 (distribution/CI can be green while unproven) | Each either blocks common real programs or risks a *false green*. |
| **Medium** | 5 (safely-refused coverage), 6 (authoring/assertions), 8 (scale/whole-file), 9 (sandbox for untrusted code) | Limit applicability or matter mainly at pipeline scale; not correctness-risky. |
| **Low–Med** | 10 (diagnosability) | Quality-of-life. |

## The three things to do first

1. **Position the fidelity ceiling honestly** (Finding 1) — a README section
   stating exactly what a passing run proves. Cheapest, highest-trust move.
2. **Fix or refuse the terminator case** (Finding 3) — turn the
   `STOP RUN`/`GOBACK` runtime `[CRASH]` into a static, pre-run refusal;
   handle `GOBACK`, not just `STOP RUN`.
3. **Pin + vendor cobol-parser and land the two parser fixes** (Finding 2) —
   so real-world examples pass for real and the AST contract stops floating.
   Remove the DEPTMQP `xfail` only when it genuinely passes.
