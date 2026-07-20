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

For a deeper reference (DSL grammar, splicer internals, Docker/GnuCOBOL
runtime, analysis/refusal rules, CLI, testing), see the
[OKF knowledge bundle](.okf/index.md) in `.okf/` — start there before making
non-trivial changes.

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
- `MOCK PARAGRAPH <name>` / `MOCK SECTION <name>` (bare COBOL names) mock
  an **internal flow target** rather than a boundary: for this test case,
  entering the named paragraph/section through its own header runs the
  mock body instead of the real one (other cases still run the real body
  — the splicer relocates it behind a dispatch, one binary per suite).
  Everything inside the mocked body — CALLs, file I/O, EXEC blocks,
  further PERFORMs — becomes unreachable for that case and needs no mocks
  of its own. `VERIFY PARAGRAPH|SECTION <name> WAS PERFORMED ...` asserts
  on the tally (`UT-PARAGRAPH-<NAME>-TALLY` / `UT-SECTION-<NAME>-TALLY`),
  counting one per entry through the header (a looping
  `PERFORM <name> N TIMES` counts N). Fail-closed refusals
  (`UNRESOLVED_FLOW_MOCK_TARGET` / `UNSUPPORTED_FLOW_MOCK_TARGET`) reject
  any target the header-dispatch rewrite cannot handle soundly: a GO TO
  target anywhere in the program, a paragraph inside a `PERFORM ... THRU`
  range or inside a SECTION that is itself performed, a target reached by
  GO-TO fall-through, a header sharing its line with code, or a test
  case's own PERFORM entry point. See the worked example in
  `examples/flowmock/`.
- Every mock gets a tally field (`UT-...-TALLY`, visible to mock bodies —
  handy for driving EOF off the read count) that `VERIFY ... WAS
  CALLED|PERFORMED ONCE | AT LEAST ONCE | NEVER | <n> TIMES` asserts on.
- `MOCK SQL "<prefix>" ROWS ( FIELD = value, ... ) ( FIELD = value, ... )
  END-MOCK` is sugar for a cursor FETCH loop: each row's fields are MOVEd
  and `SQLCODE` is set to 0 on the Nth call (matching the mock's own tally
  field reaching N); once rows run out, `SQLCODE` is set to 100 (DB2's
  "not found" code). SQL-only; mutually exclusive with a hand-written mock
  body.
- `EXEC SQL INCLUDE SQLCA END-EXEC` is replaced with a generated SQLCA, so
  mock bodies can set `SQLCODE`. `EXEC SQL INCLUDE <member> END-EXEC` for
  any other member (e.g. a DCLGEN host-variable copybook) is resolved via
  `--copybook-path` the same way a plain `COPY <member>.` is, exposing its
  host variables as real WORKING-STORAGE fields a mock body can `MOVE`
  into; without a matching `--copybook-path`, or if the member can't be
  found, it refuses `UNRESOLVED_COPYBOOK`. Only one level of `EXEC SQL
  INCLUDE` resolves — a member that itself contains another live `EXEC SQL
  INCLUDE` refuses. Like the generated SQLCA, these fields are spliced in
  after parsing and are never reset between test cases — a mock body is
  expected to set them on every run (the `ROWS` sugar above does this
  automatically).
- Lines starting with `*>` are comments.

`mockymock generate <program.cbl>` scaffolds a starter `.cut` covering
every mockable boundary it finds.

Boundary statements nested inside IF/EVALUATE/SEARCH/inline-PERFORM bodies
(including nested EXEC blocks) are mockable when the statement sits on its
own line(s) — the common layout. Reachability follows `PERFORM` **and**
`GO TO` edges (including every target of `GO TO A B C DEPENDING ON X`),
and both may name a paragraph or a SECTION (a performed section makes all
of its paragraphs reachable). `PERFORM A THRU B` is supported both inside
the program (the range is expanded in source order for reachability) and
as a test case's entry point (`PERFORM A THRU B` in the .cut, `THROUGH`
accepted); degenerate ranges — missing, duplicate, or backwards endpoints
— are refused, and so is any `PERFORM`/`GO TO` whose target resolves to
neither a paragraph nor a section (`UNRESOLVED_FLOW_TARGET` — never a
silent skip). Refused outright, program-wide: `DECLARATIVES` (USE
procedures run outside any PERFORM/GO TO edge) and `ALTER` (it rewrites
GO TO targets at runtime). Also refused, fail-closed: dynamic CALLs whose
target identifier the parser cannot determine,
`SORT`/`MERGE`/`RELEASE`/`RETURN`, statements — nested *or top-level* —
sharing a line with other code (`IF X CALL "F" END-IF` one-liners,
`P1. CALL "F".` one-line paragraphs), statements inside another boundary
statement's clause body (`READ ... AT END`, `CALL ... ON EXCEPTION`), and
mocks with clause bodies of their own — each refusal names the exact
layout problem. `CANCEL "X"` is left in place and counts as covered when
the test case mocks `CALL "X"` (the mocked CALL never loads a real module,
so the CANCEL is a guaranteed no-op); otherwise it refuses
(`UNMOCKED_CANCEL`). Programs whose parse reports a warning are also
refused (`PARSE_WARNING`): since cobolparser's silent-drop remediation, a
warning on an otherwise clean parse means statements were dropped from the
AST (unsupported verbs like `INVOKE`, multi-program source members), and
splicing an incomplete AST would silently skip real program behavior.
Likewise a copybook whose bytes can't be decoded losslessly refuses with
`EXPANSION_WARNING`. `DISPLAY` passes through unmocked. See the worked
example in `examples/invupdt/`.

### `STOP RUN` / `GOBACK` inside a test case's PERFORM target

A `.cut` test case's `PERFORM` target may reach `STOP RUN` or `GOBACK`
through a chain of plain, unconditional `PERFORM` calls, and the test
still completes correctly: the terminator is neutralized (an early-exit
flag propagates back up the real call chain via `EXIT PARAGRAPH`) and
this case's own `EXPECT`/`VERIFY` checks run normally, with later test
cases in the same suite unaffected. This is what makes it possible to
`PERFORM` a program's real top-level driver paragraph (the one that
naturally ends in `STOP RUN`/`GOBACK`) as a test target, not only its
sub-paragraphs.

Some layouts are not yet supported and refuse
(`UNSUPPORTED_TERMINATOR_LAYOUT`) rather than risk corrupting the
program: a terminator reachable via `GO TO` anywhere in the program, one
inside a `SECTION`, one reached through an intermediate `PERFORM` that's
nested inside a conditional body, or one reached only through the target
of a looping `PERFORM ... UNTIL`/`VARYING`/`TIMES` (the early-exit flag
only ends the current loop iteration, not the loop itself, so a
terminator inside a loop body cannot be safely neutralized). Restructure
to a plain, unconditional, single-shot `PERFORM` chain to avoid this.

## Examples

Worked, runnable programs under `examples/` — each pairs a `.cbl` with a
`.cut` and its own `README.md` explaining what it demonstrates. Start with
INVUPDT or ORDRPROC if you're new to the DSL; the rest each add one
distinctive feature.

| Example | Demonstrates |
|---------|--------------|
| [`examples/ordrproc/`](examples/ordrproc/) | The smallest possible teaching example: one static `CALL` |
| [`examples/invupdt/`](examples/invupdt/) | Every boundary category in one program (file I/O, `EXEC SQL`, MQ via `CALL`, `ACCEPT`), tally-driven EOF, static-reachability-driven refusal |
| [`examples/custinq/`](examples/custinq/) | `EXEC CICS` (`READ`/`RETURN`), `GOBACK` neutralization |
| [`examples/claimseg/`](examples/claimseg/) | Raw `EXEC DLI` (`GU`/`ISRT`) |
| [`examples/raterte/`](examples/raterte/) | Dynamic `CALL` through an identifier (`MOCK CALL WS-PGM-NAME`), one mock covering multiple runtime targets |
| [`examples/flowmock/`](examples/flowmock/) | Internal flow-target mocks (`MOCK PARAGRAPH` / `MOCK SECTION`), boundaries inside a mocked body needing no mocks of their own |
| [`examples/custprog/`](examples/custprog/) | `MOCK SQL ... ROWS` cursor-fetch sugar, DCLGEN-style `EXEC SQL INCLUDE <member>` via `--copybook-path` |
| [`examples/real-world/`](examples/real-world/) | Four business-flavored programs — IMS DL/I batch, IMS MPP, MQ consumer, MQ producer — plus the `--coverage` worked example |
| [`examples/nist-cobol85/`](examples/nist-cobol85/) | Static `CALL` against real, unmodified NIST COBOL-85 validation-suite programs |

## Linting, discovery, and selective runs

Three fast paths that never touch Docker or the toolchain:

```bash
# Every static refusal check (parse, copybooks, linkage, terminators, per
# test case), no daemon needed -- editor/pre-commit/CI friendly:
mockymock lint ORDRPROC.cbl --cut ORDRPROC.cut

# List a .cut file's suite/cases with line numbers and tags:
mockymock collect --cut ORDRPROC.cut [--json]
```

And selective execution (`run` still compiles once and runs one binary,
just with only the selected cases spliced in):

```bash
mockymock run ORDRPROC.cbl --cut ORDRPROC.cut --case "10% discount reduces net amount correctly"
mockymock run ORDRPROC.cbl --cut ORDRPROC.cut --tag fast
```

Tag cases in the DSL with `TESTCASE "name" TAGS "fast" "io"`. For editor
integrations, `run --json-report PATH` writes a machine-readable report with
per-case status, `.cut` line numbers, and expected/actual per failure.

## Coverage reporting

`mockymock run --coverage` compiles with GnuCOBOL's own `--coverage`
flag (GnuCOBOL transpiles COBOL to C, so this builds on gcc's gcov) and,
after the run, reports the percentage of lines executed plus the exact
uncovered lines:

```
mockymock run: coverage: 76.30% lines executed (692/907) in DEPTIMSM.cbl
mockymock run: coverage: uncovered lines:
  751:               EXIT PARAGRAPH
  ...
```

`--coverage-out PATH` additionally writes the full report to a file.
`--coverage-json PATH` (implies `--coverage`) writes machine-readable
coverage **remapped onto the original `.cbl`'s line numbers** — splicer-
inserted lines are excluded, so it answers "which of my lines ran"; editor
integrations (the VS Code extension's coverage view) consume this file.
Coverage is purely additive: it never changes the pass/fail exit code.

Two things to know before reading a number:

- **Console line numbers are against the *instrumented* source** (after
  mock-body splicing and the generated test-driver code), not the original
  `.cbl` — the same file `--verbose`/`--keep-sandbox` already expose. The
  `--coverage-json` output is the exception: it carries the remapped
  original-line view.
- **A suite that exercises every real branch still won't read near
  100%.** Two structural sources of "uncovered" lines are expected, not a
  sign of a weak suite: the driver's own `FAIL`/tally-increment lines
  (dead whenever every check passes), and — the larger one — the splicer
  emitting one shared dispatch per boundary site with a `WHEN` branch for
  *every* test case that mocks that key, not only cases whose `PERFORM`
  target reaches that exact site. See
  `docs/2026-07-17-coverage-reporting-design.md` for the full writeup and
  a worked example.

## Install

mockymock isn't on PyPI, but its `pyproject.toml` declares a full
dependency set (including a pinned `cobolparser` git dependency — see
[`.okf/integration.md`](.okf/integration.md)), so [uv](https://docs.astral.sh/uv/)
can install it straight from the repo as a standalone CLI tool, available
on `PATH` from any directory:

```bash
uv tool install git+https://github.com/samdion1994/mocky-mock.git
# or, from a local checkout:
uv tool install --from . mockymock
```

Both repos are private, so `git`/`uv` need working GitHub credentials
(`gh auth setup-git`, or an SSH key) to fetch them. Upgrade with
`uv tool upgrade mockymock`; remove with `uv tool uninstall mockymock`.
`mockymock setup`/`mockymock run` still need a running Docker daemon (see
below) — the CLI itself has no other host dependency.

## Setup (contributing)

Requires a running Docker daemon (Docker Desktop on Windows/macOS). COBOL
is compiled and executed inside a GnuCOBOL container — nothing runs on the
host, and no local GnuCOBOL install is needed.

```bash
python -m venv .venv
.venv/Scripts/activate   # or source .venv/bin/activate on macOS/Linux
pip install -r requirements-dev.txt
pip install --no-deps -e .   # mockymock itself; --no-deps skips its pinned-git
                              # cobolparser dep (see "Install" above), which
                              # would otherwise conflict with the editable
                              # sibling checkout requirements-dev.txt just installed
mockymock setup           # builds the GnuCOBOL image, starts mockymock-cobc
python -m pytest tests/unit -v
```

`tests/integration/` additionally requires the Docker daemon to be
reachable and is skipped automatically if it isn't. `mockymock run` brings
the container up on its own, so `mockymock setup` is optional.

### Windows notes

On Windows, ensure Docker Desktop is running before invoking `mockymock setup` or
`mockymock run`. COBOL compilation and execution happen entirely inside the container.

### Sandboxing

The program under test — and any `MOCK` body, which is spliced in verbatim —
runs as untrusted code inside the GnuCOBOL container, which is launched locked
down:

- `--network none` — no outbound network.
- `--pids-limit`, `--memory` / `--memory-swap` — bounded processes and memory.
- `--cap-drop ALL --cap-add DAC_OVERRIDE` — every Linux capability dropped
  except the one root needs to read/write the bind mount.
- `--security-opt no-new-privileges` — no privilege escalation.

This contains the blast radius of a hostile `.cbl` or mock body (e.g. a
`CALL "SYSTEM"`), though it is not a substitute for reviewing what you run. See
`.okf/runtime.md` (Threat model) for the full rationale and residual risk.

## License

mockymock is licensed under the MIT License. See [LICENSE](LICENSE) for details.
