# `mockymock report` and `mockymock journal`

## Writing the report

```bash
mockymock report PROGRAM.cbl [--cut PROGRAM.cut] [-o PROGRAM.report.html]
    [--json PROGRAM.report.json]
    [--execute] [--mutate]                      # run now (Docker)
    [--run-json R] [--coverage-json C] [--mutation-json M]   # or reuse results
    [--journal FILE] [--scenarios happy|branches|all|none] [--seed N]
    [--timeout S] [--mutation-threshold PCT] [--copybook-path DIR ...]
```

- Writes one self-contained HTML page (no network needed to open it) and,
  with `--json`, the same data as JSON.
- Exit code 1 when a test failed or the suite is refused, else 0, so it
  can gate CI.
- The journal defaults to `<cut stem>.journal.jsonl` next to the `.cut`.
- Without `--execute`/`--run-json`, the run, coverage and verdict steps say
  "not run" instead of guessing; every case stays at L0.

## What the page shows, top to bottom

1. **Verdict line and summary tiles** -- tests passing, cases at L2+,
   share of INTENT assertions, line coverage, mutation score, findings.
2. **Findings**, most severe first (table below).
3. **Test cases** -- level, result, why it stopped at that level, failures
   with line numbers, assertion label counts, dialect risks reached.
   Filter by result or level.
4. **How the verdict was reached** -- the eleven steps in order
   (environment, understand, rules, inventory, lint, scenarios, run,
   coverage, mutation, dialect, verdict), each with the equivalent command,
   its summary, details and timing.
5. **Assistant journal** -- your `mockymock journal` entries.
6. **Paragraphs** -- line, size, complexity, which tests reach it.
7. **Business rules** -- condition/formula, arms, which tests cite it.
8. **GnuCOBOL vs IBM COBOL risks** and the level definitions.

## Finding categories and what to do

| Category | Severity | Do this |
|---|---|---|
| `refused` | high | Fix the lint problem; nothing else is trustworthy until then. |
| `suspected-bug` | high | An INTENT assertion failed. Trace it; if the setup is right, report it. Never relabel it to get green. |
| `test-failure` | high | A non-intent assertion failed or a case crashed. Usually the test; trace it. |
| `missing-assertion` | medium | A mutant survived: add the assertion that would notice that line changing. |
| `untested-paragraph` | medium | Add a case that PERFORMs it. |
| `no-assertion` | medium | A passing case asserts nothing; add EXPECT/VERIFY. |
| `dialect` | high/medium | Note it in the hand-over; the case is GnuCOBOL-proven only. |
| `rule-without-intent` | low | Add an INTENT case for that rule (or say why not). |
| `unlabelled` | low | Label each assertion INTENT or CHARACTERIZATION. |
| `dead-code` | low | Report it; do not test it. |
| `coverage` | low | Lines never executed; usually a branch without a case. |
| `scenario-gap` | info | Neither the automatic fixture generator nor any test in the suite reaches that arm; write the inputs by hand. |
| `scenario-gap-covered-by-hand` | info | The automatic generator can't build data for that arm, but a hand-written case already reaches it (checked against line coverage) -- nothing to do. |

## Journal entries

```bash
mockymock journal --cut PROGRAM.cut --step <name> --summary "<what and result>" \
    [--status ok|warn|fail|skipped|info] [--command "<cmd>"] [--decision "<why>"]
```

Suggested step names, matching this skill's workflow: `ground-check`,
`understand`, `plan`, `scaffold`, `intent-cases`, `paragraph:<NAME>`,
`whole-program`, `prove`, `hand-over`. One entry per decision a reviewer
would ask about: what you skipped, what you parked, which rule a case
covers, why you accepted a level below L3.
