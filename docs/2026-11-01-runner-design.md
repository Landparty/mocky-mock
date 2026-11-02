# mockymock runner: the LegacyLens change-impact oracle worker

Date: 2026-11-01
Status: implemented (v1)

## Why

LegacyLens maps each load module and builds its integration-test pack
(every boundary leaving the module mocked, `USE REAL CALL` inside it). The
change-impact oracle runs that pack once to record a **baseline** of what
the module sends out (docs/2026-11-01-baseline-design.md), and again after
a program or copybook of the module changes, to **compare**. A change that
reaches 1,000 load modules then gets 1,000 verdicts: same, or differs and
where.

The backend never compiles or runs COBOL: uploads are untrusted code, and
GnuCOBOL does not belong in the API image. It keeps a queue of jobs; this
runner, a separate process or container, does the running.

## Protocol

All calls carry `X-Runner-Token` (the backend's `RUNNER_TOKEN`).

1. `POST /api/v1/runner/jobs/claim` with `{"runner": NAME}`: the oldest
   queued job, now `running` for this runner, or 204.
2. `GET /api/v1/runner/jobs/{id}/pack`: the zip.
3. `POST /api/v1/runner/jobs/{id}/result` with
   `{"suites": [...], "error": "..."?}`.

A job the runner never reports is failed by the backend after
`ORACLE_JOB_TIMEOUT_MINUTES`.

## The pack

The load module's integration-test pack plus `oracle.json`:

```json
{"version": 1, "kind": "baseline", "load_module": "PAYMOD",
 "copybook_path": "copybooks",
 "suites": [{"entry": "PAYMAIN", "program": "src/PAYMAIN.cbl",
             "cut": "tests/PAYMAIN.cut",
             "generate": "mockymock generate src/PAYMAIN.cbl --real src/PAYCALC.cbl",
             "baseline": null}]}
```

A compare job also carries, per suite, the frozen `.cut` the baseline was
recorded with and `baselines/<ENTRY>.json`.

## What the runner does per suite

- **Baseline:** scaffold the `.cut` with the `generate` command when the
  pack has none, run `mockymock run --record-baseline`, report the baseline
  document **and the `.cut` text**. The backend keeps both: every later
  compare runs the same `.cut`, so the same mocks answer the same way and a
  difference comes from the code.
- **Compare:** run `mockymock run --baseline --baseline-json` with the
  frozen `.cut`, report the comparison (`matches`, counts, changed inputs,
  the first difference per case). No baseline or no frozen `.cut` for a
  suite is reported as that suite's `error`.

Every `generate` and `run` is a child process with a timeout, so a suite
that hangs or crashes is one suite's error, not a dead runner. The runner
only runs `mockymock generate PROGRAM [--scenarios happy|branches|all]
[--real PATH]...` from the manifest,
and refuses any path (in the zip or the manifest) that leaves the pack.

## Deployment

`docker/runner/Dockerfile`: Debian trixie's GnuCOBOL 3.2, mockymock's
native toolchain (no Docker-in-Docker), a non-root user, entrypoint
`mockymock runner`. Give it `LEGACYLENS_URL` and `RUNNER_TOKEN`; run it
with memory and pid limits on a network that only reaches the backend. The
backend's docker-compose starts it under the `runner` profile.

## Not covered (v1)

- One job at a time per runner; run more containers to go wider.
- Suites of one job run one after the other.
- No streaming of progress: the backend sees `running`, then the result.
