# docs/ index

**Start with [`.okf/index.md`](../.okf/index.md).** The `.okf/` bundle is
the living description of how mockymock works. The files here are dated
records: designs, audits and sweeps, each true on the day it was written.

The table below gives each doc's **current** status, checked against the
code on 2026-11-07. Where it disagrees with a doc's own `Status:` line,
the table is right. Many designs still say "proposed" for features that
have since shipped. Implementation plans for shipped work are in
[`archive/plans/`](archive/plans/), and superseded designs are in
[`archive/`](archive/).

When you add a design, add a row here. When it ships, or is superseded,
update the row instead of editing the old doc's header.

## Designs

| doc | topic | status |
|---|---|---|
| [2026-06-30-mockymock-mvp-design](2026-06-30-mockymock-mvp-design.md) | MVP | implemented |
| [2026-07-04-docker-toolchain-design](2026-07-04-docker-toolchain-design.md) | Docker GnuCOBOL toolchain | implemented |
| [2026-07-05-mock-all-boundaries-design](2026-07-05-mock-all-boundaries-design.md) | Mock every boundary category | implemented |
| [2026-07-05-nested-mock-targets-design](2026-07-05-nested-mock-targets-design.md) | Nested mock targets | implemented |
| [2026-07-06-dynamic-call-mocks-design](2026-07-06-dynamic-call-mocks-design.md) | Dynamic CALL mocks | implemented |
| [2026-07-06-perform-thru-design](2026-07-06-perform-thru-design.md) | PERFORM THRU | implemented |
| [2026-07-06-realworld-cobol-examples-design](2026-07-06-realworld-cobol-examples-design.md) | Real-world example programs | implemented |
| [2026-07-08-goback-stop-run-support-design](2026-07-08-goback-stop-run-support-design.md) | GOBACK / STOP RUN | implemented |
| [2026-07-08-ims-linkage-support-design](2026-07-08-ims-linkage-support-design.md) | IMS ENTRY / LINKAGE | implemented |
| [2026-07-09-sql-v1-include-cursor-rows-design](2026-07-09-sql-v1-include-cursor-rows-design.md) | SQL INCLUDE, cursor ROWS | implemented |
| [2026-07-10-conditionally-nested-intermediate-perform-design](2026-07-10-conditionally-nested-intermediate-perform-design.md) | Conditionally nested PERFORM | implemented |
| [2026-07-10-goto-fallthrough-terminator-hazard-design](2026-07-10-goto-fallthrough-terminator-hazard-design.md) | GO TO fall-through hazard | implemented |
| [2026-07-10-goto-reachable-terminators-design](2026-07-10-goto-reachable-terminators-design.md) | GO TO-reachable terminators | investigation, no fix (refusal stays) |
| [2026-07-10-section-scoped-terminator-support-design](2026-07-10-section-scoped-terminator-support-design.md) | SECTION-scoped terminators | implemented |
| [2026-07-17-coverage-reporting-design](2026-07-17-coverage-reporting-design.md) | `run --coverage` | implemented |
| [2026-07-18-cut-lint-command-design](2026-07-18-cut-lint-command-design.md) | `lint` | implemented |
| [2026-07-20-before-blocks-and-file-status-design](2026-07-20-before-blocks-and-file-status-design.md) | BEFORE blocks, FILE-STATUS sugar | implemented |
| [2026-07-20-paragraph-section-mocks-design](2026-07-20-paragraph-section-mocks-design.md) | MOCK PARAGRAPH / SECTION | implemented |
| [2026-07-20-provider-parameterized-test-cases-design](2026-07-20-provider-parameterized-test-cases-design.md) | `USING PROVIDER` | implemented |
| [2026-07-21-debug-trace-design](2026-07-21-debug-trace-design.md) | `run --trace` | implemented |
| [2026-07-22-dap-debugger-design](2026-07-22-dap-debugger-design.md) | `debug` (DAP) | implemented |
| [2026-07-29-mutation-testing-design](2026-07-29-mutation-testing-design.md) | `mutate` | implemented |
| [2026-07-31-csv-sourced-rows-design](2026-07-31-csv-sourced-rows-design.md) | CSV-sourced ROWS | **partial**: inline ROWS shipped, `ROWS FROM` CSV not |
| [2026-08-02-cobol-mocky-mock-publish-pipeline-design](2026-08-02-cobol-mocky-mock-publish-pipeline-design.md) | Skill / plugin publishing | implemented |
| [2026-08-03-mainframe-export-command-design](2026-08-03-mainframe-export-command-design.md) | `export` | implemented |
| [2026-08-04-record-expectations-design](2026-08-04-record-expectations-design.md) | `run --record-expectations` | implemented |
| [2026-08-11-argument-capture-design](2026-08-11-argument-capture-design.md) | `CAPTURE ARG` | implemented |
| [2026-08-17-goto-exit-paragraph-simplification-design](2026-08-17-goto-exit-paragraph-simplification-design.md) | GO TO -> EXIT PARAGRAPH | implemented |
| [2026-08-17-sort-merge-using-giving-mocking-design](2026-08-17-sort-merge-using-giving-mocking-design.md) | MOCK SORT / MERGE | implemented |
| [2026-08-19-expect-comparison-operators-design](2026-08-19-expect-comparison-operators-design.md) | EXPECT operators | implemented |
| [2026-08-27-cics-eib-linkage-support-design](2026-08-27-cics-eib-linkage-support-design.md) | CICS EIB linkage | implemented |
| [2026-09-02-verb-coverage-fail-closed-design](2026-09-02-verb-coverage-fail-closed-design.md) | Every verb mockable or refused | implemented |
| [2026-09-04-export-literal-continuation-design](2026-09-04-export-literal-continuation-design.md) | `export` literal continuation | implemented |
| [2026-09-04-scenario-branch-verification](2026-09-04-scenario-branch-verification.md) | Scenario reaches its branch | **partial**: `--branch-coverage` shipped, no per-scenario assertion |
| [2026-09-15-actionable-refusals-and-fill-design](2026-09-15-actionable-refusals-and-fill-design.md) | Actionable refusals, `generate --fill` | implemented |
| [2026-09-15-cli-ergonomics-design](2026-09-15-cli-ergonomics-design.md) | CLI ergonomics | implemented |
| [2026-09-15-copybook-discovery-defaults-design](2026-09-15-copybook-discovery-defaults-design.md) | Copybook discovery | implemented |
| [2026-09-15-cut-editor-intelligence-design](2026-09-15-cut-editor-intelligence-design.md) | `.cut` editor support | **partial**: CLI side here; editor in its own repo |
| [2026-09-15-doctor-command-design](2026-09-15-doctor-command-design.md) | `doctor` | implemented |
| [2026-09-15-init-command-design](2026-09-15-init-command-design.md) | `init` | implemented |
| [2026-09-16-ai-assistant-modes-design](2026-09-16-ai-assistant-modes-design.md) | AI assistant modes | implemented |
| [2026-09-16-universal-yaml-config-design](2026-09-16-universal-yaml-config-design.md) | `cobol.yml` | implemented |
| [2026-10-10-suite-hooks-design](2026-10-10-suite-hooks-design.md) | Suite hooks | implemented |
| [2026-10-14-multi-suite-layout-design](2026-10-14-multi-suite-layout-design.md) | Several suites per program | implemented |
| [2026-10-27-section-member-terminators-design](2026-10-27-section-member-terminators-design.md) | Terminators in SECTION members | implemented |
| [2026-11-01-baseline-design](2026-11-01-baseline-design.md) | Behaviour baselines | implemented |
| [2026-11-01-real-call-integration-design](2026-11-01-real-call-integration-design.md) | `USE REAL CALL` | implemented |
| [2026-11-01-runner-design](2026-11-01-runner-design.md) | LegacyLens oracle runner | implemented |
| [2026-11-02-real-dynamic-call-design](2026-11-02-real-dynamic-call-design.md) | Dynamic CALL to a real program | implemented |
| [2026-11-06-branch-coverage-design](2026-11-06-branch-coverage-design.md) | `run --branch-coverage` | implemented |
| [2026-11-06-real-files-and-job-runs-design](2026-11-06-real-files-and-job-runs-design.md) | `USE REAL FILE`, `job` | implemented |
| [superpowers/specs/2026-08-11-mockymock-ai-skills-design](superpowers/specs/2026-08-11-mockymock-ai-skills-design.md) | Packaged AI skills | implemented |
| [superpowers/specs/2026-08-16-scenario-generation-skill-design](superpowers/specs/2026-08-16-scenario-generation-skill-design.md) | Scenario-generation skill | implemented |
| [archive/2026-07-29-integration-testing-direction-design](archive/2026-07-29-integration-testing-direction-design.md) | REAL-boundary direction | superseded by the 2026-11-01 real-call and 2026-11-06 real-files designs |

## Open work named by these docs

These are the only gaps left in the designs above:

- `ROWS FROM "file.csv"` for SQL and READ mocks (csv-sourced-rows).
- A per-scenario assertion that a generated scenario reaches the branch it
  is named for (scenario-branch-verification).

## Audits, sweeps, reviews

Point-in-time records, newest first. Each later audit re-checks the
previous one's findings.

| doc | kind |
|---|---|
| [2026-11-06-tech-debt-audit](2026-11-06-tech-debt-audit.md) | tech-debt audit (and the remediation that followed) |
| [2026-09-21-cobol-testing-usability-design](2026-09-21-cobol-testing-usability-design.md) | first-ten-minutes usability review |
| [2026-09-16-project-audit](2026-09-16-project-audit.md) | project audit |
| [2026-09-05-project-deep-audit](2026-09-05-project-deep-audit.md) | deep audit |
| [2026-08-12-framework-audit](2026-08-12-framework-audit.md) | framework audit |
| [2026-08-10-framework-audit-and-roadmap](2026-08-10-framework-audit-and-roadmap.md) | audit and roadmap |
| [2026-08-01-silent-gaps-audit-followup](2026-08-01-silent-gaps-audit-followup.md) | silent-gaps follow-up |
| [2026-07-08-cobol-parser-corpus-sweep](2026-07-08-cobol-parser-corpus-sweep.md) | cobol-parser corpus sweep |
| [corpus-sweep-report](corpus-sweep-report.md) | corpus sweep output |
| [2026-07-07-audit-report](2026-07-07-audit-report.md) | audit |
| [2026-07-06-real-world-readiness-audit](2026-07-06-real-world-readiness-audit.md) | readiness audit |

## Reference

- [options-reference](options-reference.md): every CLI option (living).
