---
name: mockymock
description: Use when writing or running .cut test files for mockymock (a COBOL unit-test framework that mocks CALL/file-I-O/EXEC SQL·CICS·DLI/ACCEPT boundaries and runs the real program under GnuCOBOL), or when a mockymock run fails or refuses and the reason needs interpreting.
---

<!--
Maintainer note: this is a curated duplicate of docs/options-reference.md
in the mocky-mock repo, adapted for agent consumption. A .cut directive or
CLI flag change should be reflected in reference/cut-dsl.md and
reference/cli-flags.md here too. A FixtureBundle schema change
(docs/fixture-bundle-schema.md in cobol-parser) should be reflected in
reference/scenario-generation.md.
-->

# mockymock: COBOL unit testing

mockymock mocks a COBOL program's external boundaries (subprogram `CALL`s
including MQ, file I/O, `EXEC SQL`/`CICS`/`DLI`, console `ACCEPT`),
compiles the instrumented copy with real GnuCOBOL inside Docker, runs it,
and reports pass/fail. Use it to write and run `.cut` test files against
`.cbl` programs.

## Workflow

1. **Understand before generating** -- for a program you haven't
   scaffolded a data-driven `.cut` for yet, don't jump straight to
   `--with-data`:
   a. Run `mockymock fixtures PROGRAM.cbl --scenarios all` and read the
      first scenario's `fixtures` plus any OUT-only boundaries in its
      `expectations` (every scenario carries a fixture for every boundary
      the program touches, so one scenario is a complete inventory).
      Explain in plain language what's mockable -- which CALLs/files/
      SQL/ACCEPT, and each one's direction -- before generating anything.
      See `reference/scenario-generation.md` for exactly which bundle
      fields to read and how to phrase this.
   b. Recommend a `--scenarios` mode with a reason tied to the program's
      own `scenario_coverage.total_arms` from that same bundle (0 arms:
      `happy`; 1+: `branches`, or `all` if the developer also wants fixed
      edge-case families), instead of defaulting silently to `happy`.
      Confirm with the developer.
      ```bash
      mockymock generate PROGRAM.cbl                                       # placeholder mocks, one TESTCASE per paragraph
      mockymock generate PROGRAM.cbl --with-data --seed 7 --scenarios all  # real generated data + EXPECT/VERIFY per scenario
      ```
   c. Generate with the confirmed mode. `generate` also prints every
      boundary it could **not** mock (an unidentifiable dynamic `CALL`,
      an unspliceable nested site) -- a test case that reaches one of
      those will be refused by `run` until you resolve it.
   d. Read back the result: name any unresolved boundaries by paragraph
      (from `unresolved` and each fixture's own `unresolved`), not just a
      count. Offer to refine (`--placeholder CATEGORY:KEY`, a different
      `--seed`, a narrower `--scenarios`) based on what's missing.

2. **Fill in / edit mocks** using the `.cut` DSL -- see
   `reference/cut-dsl.md` for the full directive reference. The shape:
   ```
   TESTSUITE "<name>"

   TESTCASE "<name>"
       MOCK <category> <key>
           <COBOL statements, e.g. MOVE 5 TO INV-QTY>
       END-MOCK
       PERFORM <paragraph>
       EXPECT <data-name> TO BE <value>
       VERIFY <category> <key> WAS PERFORMED <n> TIMES
   ```

3. **Check for problems without Docker** while iterating:
   ```bash
   mockymock lint PROGRAM.cbl --cut PROGRAM.cut
   ```
   Prints every refusal `run` would print, with zero Docker dependency --
   use this as the fast inner loop while writing a `.cut` file.

4. **Run it for real** (needs a running Docker daemon; `mockymock setup`
   warms it up ahead of time, but `run` does this automatically):
   ```bash
   mockymock run PROGRAM.cbl --cut PROGRAM.cut
   ```

5. **When a run fails or refuses**, read the printed reason literally --
   mockymock is deliberately fail-closed (a refusal names exactly what it
   couldn't soundly rewrite, e.g. `GO TO` into a mock target, `ALTER`, a
   parse warning) rather than silently skipping or mis-mocking. See
   `reference/cli-flags.md`'s `run`/`debug` sections for `--trace`
   (replay one case's execution path plus the mock timeline in order),
   `--record-expectations` (turn `*> STUB EXPECT <name>` comments into
   real assertions filled in from the actual run), and `--verbose`
   (print the instrumented source path on a compile failure).

## Full reference

- `reference/cut-dsl.md` -- every `.cut` directive: `MOCK`/`END-MOCK`
  categories, `ROWS` cursor sugar, `EXPECT`, `VERIFY`, `FILE-STATUS IS`,
  `BEFORE-ALL`/`BEFORE-EACH`, `PROVIDER`/`HEADER`/`ROW`, `*> STUB EXPECT`.
- `reference/cli-flags.md` -- every subcommand and flag: `setup`,
  `generate`, `fixtures`, `run`, `debug`, `lint`, `mutate`, `collect`,
  `dashboard`, `export`, `analyze`, `skills`.
- `reference/scenario-generation.md` -- how to read a `mockymock
  fixtures` bundle (boundary inventory, branch-arm coverage, unresolved
  gaps), how to recommend a `--scenarios` mode, and how to phrase a
  generation read-back.
