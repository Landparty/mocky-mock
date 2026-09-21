# Making mockymock easy: the first ten minutes with a real COBOL program (2026-09-21)

## Problem

mockymock's capability surface is close to complete: fifteen subcommands,
every boundary category, coverage, mutation, trace, a DAP debugger, a
VS Code extension with a Test Explorer, and a fail-closed refusal gate.
The 2026-09-15/16 ergonomics wave (`init`, `doctor`, `explain`,
actionable refusals, `generate --fill`, copybook discovery, universal
`cobol.yml`) closed most of the *ceremony* gap -- how much a user has to
type.

What is still expensive is the gap between "the tool ran" and "I have a
test suite worth keeping". A COBOL developer's first ten minutes today
produce one of three outcomes:

1. **A suite that asserts nothing.** The most-used entry point -- VS Code's
   beaker button -- shells out to plain `generate` (`mocky-mock-vscode/
   src/newTestSuite/cutTemplate.ts:15`), the exact path
   `docs/2026-09-15-init-command-design.md` opens by describing as "a
   suite like that passes trivially and proves nothing". `init` fixed
   this on the CLI side; the button never followed.
2. **A suite full of values no reviewer can defend.** `init` /
   `generate --with-data` fills mock bodies from the fixture generator
   without regard to what the field means, then
   `--record-expectations` freezes whatever fell out.
3. **A refusal whose line number is not in the file.** Refusal messages
   carry post-copybook-expansion line numbers; for any program with a
   `COPY`, they point past the end of the source the user is looking at.

None of these is a correctness bug. All three are reasons a pilot stalls
after the first program.

## Method

Everything below was reproduced on this tree at `0706c39`, mockymock
`0.8.0`, published `cobol-parser 1.8.4`, **no Docker daemon** -- so this
covers `generate`/`init`/`lint` (the on-ramp) and not the console report
of a real `run`. Commands are quoted inline so each claim is checkable.

## Findings

### 1. The one-click path still emits a suite with zero assertions (HIGH)

```
$ mockymock generate LOANPMT.cbl -o plain.cut
$ grep -c '^TESTCASE' plain.cut        -> 7
$ grep -c '^\s*\(EXPECT\|VERIFY\)' plain.cut -> 0
```

Seven cases, seven `PERFORM`s, three commented `*> STUB EXPECT` lines,
and not one executable assertion. Every case passes. That is what
**New Test Suite for This Program** writes today.

**Fix.** Point `cutTemplate.ts` at `init` instead of `generate`, with the
Docker probe surfaced as a VS Code progress notification and `init`'s own
no-Docker fallback message routed to a toast with a **Check Setup**
button (the extension already owns that action). Half a day, one repo,
no new CLI surface.

### 2. `init` and `generate` disagree about test granularity (HIGH)

For the same program:

| Command | Cases | Shape |
|---|---|---|
| `generate` | 7 | one per paragraph, `PERFORM 1000-INITIALIZE` -- no assertions |
| `init` (= `generate --with-data` + record) | **1** | `"happy path"`, `PERFORM 0000-MAIN-PROCESS` |

The paragraph-scoped granularity is the one every reference example uses
and the one that produces business-meaningful failures; the data-driven
path is the one that produces assertions. A user has to pick one. Nobody
wants the whole-program single case as their starting suite.

**Fix.** `init` should scaffold at `generate`'s granularity (one case per
paragraph with boundaries) and run the fixture/record pass over each. The
fixture bundle is already per-boundary, not per-program, so this is a
loop, not a new generator.

### 3. `--scenarios all` names branches it does not drive (HIGH)

```
$ mockymock generate LOANPMT.cbl --with-data --scenarios all -o all.cut
TESTCASE "2400-CHECK-LATE-FEE: THEN"    -> MOVE -291 TO HV-DAYS-PAST-DUE
TESTCASE "2400-CHECK-LATE-FEE: ELSE"    -> (same block, different random values)
```

All seven cases `PERFORM 0000-MAIN-PROCESS`; the values are drawn without
reference to the predicate the case is named after. `docs/2026-09-04-
scenario-branch-verification.md` already records that branch arrival is
unverified, and `init` prints a note saying so -- but the file on disk
still carries seven confident branch names. A name that asserts coverage
the suite does not have is worse than no name.

**Fix, in order of cost.** (a) Seed the mocked fields from the branch
predicate's own constants when it compares a mocked field to a literal --
this is the common COBOL case (`IF HV-DAYS-PAST-DUE > 30`) and turns the
generator from "random" into "solves one inequality"; (b) failing that,
verify arrival with the existing `--trace` machinery and drop the cases
that did not reach their arm; (c) at minimum, rename unverified cases to
`"2400-CHECK-LATE-FEE: candidate THEN (arm not verified)"`.

### 4. Generated suites duplicate every mock instead of using `BEFORE-EACH` (MEDIUM)

`all.cut` is **653 lines for one 431-line program**: seven copies of a
66-line mock block differing only in random literals, `grep -c BEFORE-EACH
-> 0`. The DSL has had `BEFORE-EACH` since 2026-07-20 and
`examples/taxfile/` demonstrates exactly this factoring. A file that size
is not read, reviewed, or maintained -- it is regenerated, which defeats
the purpose of checking tests into source control.

**Fix.** Emit the directives common to every case once under
`BEFORE-EACH`, leaving per-case overrides inline. Mechanical: the
generator already has all cases in memory before it renders.

### 5. Generated data ignores what the field is (MEDIUM)

From an unedited `init` run:

```
MOVE "JONES" TO HV-LAST-PMT-DATE
MOVE "J" TO HV-LATE-FEE-ASSESSED
MOVE -8012567.34 TO HV-ESCROW-PMT
MOVE 9718891773545.54 TO HV-PRINCIPAL-PAID
```

A name in a date field, a negative escrow payment, 9.7 trillion in
principal paid. The values are PICTURE-valid and domain-absurd. Two
consequences: a reviewer cannot tell a deliberate edge case from noise,
and `--record-expectations` then freezes the program's response to
nonsense as the golden expectation.

**Fix.** A name-and-picture-aware value dictionary: `-DATE`/`-DT` suffixes
get dates in the program's own date format, `-AMT`/`-BAL` get money in a
plausible magnitude for the PICTURE's scale, `-CODE`/`-STATUS` get values
drawn from the program's own `88` levels when it declares them (the
parser already exposes condition names), `-NAME` gets names. Roughly a
day, and it is the difference between a generated suite a team reviews
and one they delete.

### 6. Refusal line numbers are not line numbers in the user's file (HIGH)

```
$ mockymock lint examples/real-world/ACCTMNT/ACCTMNT.cbl --cut .../ACCTMNT.cut
refused (UNMOCKED_FILE_OP): CLOSE boundary at line 565 (paragraph '3000-FINALIZE', ...)
$ wc -l ACCTMNT.cbl   -> 431        # 3000-FINALIZE is at line 413
```

The numbers are post-`COPY`-expansion. `mocky-mock-vscode/src/linting/
lintOutput.ts:11-14` documents this and therefore cannot anchor the
diagnostic to the boundary -- the extension knows the number is unusable.
Every refusal that names a statement in a program with copybooks is
affected, which in a real shop is nearly all of them.

**Fix.** Carry the pre-expansion `(file, line)` alongside the expanded
one through `mock_surface` -> `RefusalReason` and print the original,
naming the copybook member and its own line when the site is inside one
(`COPY WSCOMMON. line 14`). Unlocks a clickable diagnostic in the
extension for free.

### 7. The suggested fix is mechanically right and can be semantically wrong (MEDIUM)

Same refusal:

```
    Add to this TESTCASE:
        MOCK CLOSE PARMFILE
```

The actual cause is fall-through: the case `PERFORM`s
`2200-PROCESS-FEE-POSTING`, which contains `GO TO 2290-FEE-DONE`
(`ACCTMNT.cbl:284`), so control leaves the PERFORM range and runs on
through `2300-...` into `3000-FINALIZE`. The right fix is
`PERFORM 2200-PROCESS-FEE-POSTING THRU 2290-FEE-DONE` -- the `.cut`
file's own header comment says as much. Taking the suggested fix instead
produces a green test that mocks its way past a control-flow bug.

**Fix.** The reachability walk already knows *how* it reached the site.
When the path leaves the PERFORMed paragraph by fall-through or `GO TO`,
say so and lead with the `THRU` remedy; keep the `MOCK` snippet as the
secondary option. This is the single highest-value line of text in the
tool: it is where a user decides whether mockymock is telling them
something true about their program.

### 8. Messages written for the maintainer, not the user (MEDIUM)

One unedited `init` run on a shipped example prints:

- a seven-line `WARNING: boundary key mismatch ... (see this repo's own
  tests/unit/test_fixture_bundle_contract.py)` -- a pip-installed user
  has no such file, and the warning is not actionable by them;
- `see docs/2026-07-08-goback-stop-run-support-design.md` -- a path that
  ships in no wheel;
- `provenance=assumed-bidirectional`, `not asserted in v1` inside the
  generated `.cut` comments;
- `VERIFY OPEN PMTFILE WAS CALLED 1 TIMES`;
- `MOCK SQL "INSERT INTO BANK. TRANSACTION_HIST ( TRAN_ID, ... DR, LPM"`
  -- a 180-character match key truncated mid-literal, with a space
  inserted into `BANK.TRANSACTION_HIST` by the SQL text normalizer (the
  source has no space: `LOANPMT.cbl:11`).

**Fix.** One pass over user-facing strings: internals behind `--verbose`,
doc references as `mockymock explain <topic>` rather than repo paths,
`1 TIME`/`n TIMES`, fix the normalizer's `.` spacing, and shorten SQL
match keys to `<VERB> <TABLE>` with a disambiguating suffix only when two
sites collide.

### 9. There is no answer to "will this work on our codebase?" (MEDIUM)

The first question any adopter asks. Answering it today means a shell
loop over `lint` and reading the output by hand.
`docs/2026-08-10-framework-audit-and-roadmap.md`'s add-on 7 proposed
`analyze --refusal-report` a month ago; nothing was built
(`grep -rn refusal.report --include=*.py -> no hits`).

**Fix.** `mockymock scan <dir>`: per-program testable/refused verdict,
refusal codes ranked by frequency, `--json` for a dashboard. Most of the
machinery is in `scripts/corpus_sweep.py` already; it is aggregation and
presentation over `lint`.

Its natural companion is add-on 8, **boundary coverage** -- "this suite
exercises 12 of the 19 mockable boundaries in this program". Line
coverage is available from any tool; boundary coverage is the number only
this one can produce, and it is the number that tells a team when they
are done.

### 10. Docker is the wall before any of the above (MEDIUM, adoption-gating)

`mockymock setup` builds `debian:trixie-slim` + `apt-get install gnucobol`
locally (`mockymock/runtime/docker/Dockerfile`), and the runtime shells
out to a hardcoded `"docker"` binary at six sites in
`mockymock/runtime/docker_toolchain.py`. The target audience is
mainframe shops, where Docker Desktop is frequently a licensing decision
and outbound access to Docker Hub plus Debian mirrors is frequently not
available at all.

**Fix, cheapest first.** (a) Publish the toolchain image to a registry so
`setup` is a pull, not a build; (b) honour `MOCKYMOCK_CONTAINER_RUNTIME`
(podman/nerdctl are CLI-compatible for everything used here) -- a
constant, not a rewrite; (c) document a `docker save`/`load` tarball path
for air-gapped sites. None of this changes the sandbox model.

### 11. The on-ramp is unguarded and has already rotted (HIGH, cheap)

Linting all 43 example/fixture pairs in the repo:

```
5 of 43 pairs fail `mockymock lint` today:
  examples/nist-cobol85/IC101A          UNMOCKED_FILE_OP + UNSUPPORTED_TERMINATOR_LAYOUT
  examples/real-world/ACCTMNT           UNMOCKED_FILE_OP  (fall-through, finding 7)
  examples/real-world/ACHPROC           UNMOCKED_SQL
  examples/real-world/CHKCLR            UNMOCKED_FILE_OP
  examples/real-world/INTCALC           UNMOCKED_SQL
```

`.github/workflows/ci.yml` carries `if: false` on both `test` and
`test-cross-platform`, so no test has run in CI since 2026-08. The
examples are the onboarding path; a user who follows the README into
`examples/real-world/` meets a refusal in 4 of its 17 programs on
their first command.

**Fix.** A `lint-examples` CI job: `mockymock lint` over every pair,
Docker-free, ~40 seconds, red when an example stops passing its own
static gate. Then repair the five (four are finding 7's fall-through
shape and want `THRU`, not more mocks).

## Prioritized plan

**This week -- the first artifact is worth keeping.**

1. Extension button -> `init` (finding 1).
2. `init` at paragraph granularity (finding 2).
3. `lint-examples` CI job + repair the five (finding 11).
4. Refusals report original file/line (finding 6) and lead with `THRU`
   for fall-through (finding 7).

**Next -- the artifact is worth reading.**

5. `BEFORE-EACH` factoring (finding 4).
6. Domain-aware generated data (finding 5).
7. Message pass: internals behind `--verbose`, SQL key shortening,
   `1 TIME`, normalizer spacing (finding 8).
8. Honest scenario names, then predicate-seeded data (finding 3).

**Then -- the tool answers the questions a buyer asks.**

9. `mockymock scan` refusal report (finding 9).
10. Boundary coverage (finding 9's companion).
11. Registry-published image + `MOCKYMOCK_CONTAINER_RUNTIME` + offline
    tarball (finding 10).

## Non-goals

- No change to the refusal *model*. Fail-closed is the reason to trust a
  green run; findings 6 and 7 change what a refusal says and where it
  points, never whether it fires.
- No new DSL surface. Every finding above is served by the grammar as it
  stands (`BEFORE-EACH`, `PERFORM ... THRU`, `EXPECT`, `VERIFY`).
- No second generator. Findings 2-5 are changes to what the existing
  fixture-driven path emits.

## Open questions

- **Does `init` at paragraph granularity multiply run time past comfort?**
  Each case is spliced into one compile, but recording runs the binary
  per case; a 40-paragraph program needs measuring before defaulting.
- **What should `--scenarios all` do when the predicate is not
  literal-comparable** (a `88` level over a group, a computed field)?
  Options: skip the case, emit it with the honest name, or leave it to
  the AI skill.
- **Registry choice and licence posture** for a published toolchain
  image, given the EULA (finding 10a).
