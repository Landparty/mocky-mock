---
type: Test Suite
title: Testing
description: Unit vs. integration split, the Docker-availability skip guard, the fixtures/ corpus, and the two full worked GnuCOBOL examples (INVUPDT, ORDRPROC).
tags: [testing, ci, examples, fixtures]
timestamp: 2026-07-06T00:00:00Z
---
# Overview

Two-tier split under `tests/`:

| Tier | Path | What it exercises | Docker required? |
|------|------|--------------------|-------------------|
| Unit | `tests/unit/` | DSL parser/generator, splicer, orchestrator, naming, refusal rules, SQLCA, sandbox, source maps, reporting -- all in-process, no compiler | No |
| Integration | `tests/integration/` | Full pipeline: parse -> splice -> compile with real GnuCOBOL (in Docker) -> run -> assert exit code | Yes (skipped otherwise) |

Unit tests (`tests/unit/`, 20 files) include `test_dsl_parser.py` / `test_dsl_parser_v2.py`,
`test_dsl_generator.py`, `test_injector.py`, `test_mock_surface.py` / `_v2.py`,
`test_orchestrator.py`, `test_refusal.py` / `_v2.py`, `test_dynamic_call.py`,
`test_sqlca.py`, `test_sandbox.py`, `test_source_map.py`, `test_stub_writer.py`,
`test_naming.py`, `test_reset.py`, `test_report.py`, `test_driver.py`,
`test_docker_toolchain.py`, `test_cli_docker.py`, `test_smoke.py`. The `_v2` files
track a second generation of the DSL/mock-surface grammar living alongside the
original -- both are still exercised, implying the surface is mid-migration
rather than the v1 files being dead weight.

# Docker-availability skip pattern

Integration tests need a real GnuCOBOL compiler, which mockymock only ships
via a Docker image (`mockymock-gnucobol`) -- there is deliberately no
GnuCOBOL install step in CI (see `.github/workflows/ci.yml` comment: "No
GnuCOBOL install: the toolchain is Docker-only"). Gating lives in one shared
module:

```python
# tests/integration/_docker.py
@functools.lru_cache(maxsize=1)
def docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    return subprocess.run(["docker", "info"], ...).returncode == 0

requires_docker = pytest.mark.skipif(not docker_available(), reason="Docker daemon not reachable")
```

Every integration test file decorates its test functions with
`@requires_docker` (imported from `tests.integration._docker`). The check is
memoized per test process (`lru_cache(maxsize=1)`) so the `docker info`
subprocess only runs once no matter how many integration tests are collected.
This means:

- On a machine/CI runner with no Docker daemon, the entire integration tier
  reports as **skipped**, not failed -- a green run does not by itself prove
  the compile-and-run path works.
- On first use per machine, the `mockymock-gnucobol` image is built
  on-demand (~1 min), which is why CI comments call out the extra latency on
  a cold cache.

# fixtures/ corpus

`tests/integration/fixtures/` holds `.cbl`/`.cut` pairs used directly by the
integration tests (not the polished `examples/` programs -- these are
narrower, purpose-built regression fixtures):

| Fixture | Exercises | Test file |
|---------|-----------|-----------|
| `dynamic_call.cbl` / `.cut` | Dynamic `CALL WS-PGM-NAME` (identifier-valued program name) matched by one bare-key `MOCK CALL` whose body branches on the runtime value -- previously blanket-refused as `DYNAMIC_CALL` | `test_dynamic_call_example.py` |
| `nested_boundaries.cbl` / `.cut` | Mock boundaries nested inside other control structures | `test_nested_boundaries.py` |
| `thru_boundaries.cbl` / `.cut` | `PERFORM ... THRU` range expansion in reachability analysis | `test_thru_boundaries.py` |
| `walking_skeleton.cbl` (no `.cut`) | Minimal smoke-test program for the CLI end to end | `test_walking_skeleton.py` |
| `copybook_example/` (`MAINPGM.cbl`, `MAINPGM.cut`, `copybooks/`) | `COPY` expansion feeding the mock surface / splicer | `test_copybook_expansion.py` |

`test_cli.py` covers CLI argument handling generically (not tied to one fixture).

Each fixture pair follows the same shape as the worked examples: a `.cbl`
program plus a `.cut` (mockymock's own DSL file) that both declares `MOCK`
bodies for boundary statements and asserts outcomes with `EXPECT` / `VERIFY`.
The dynamic-call test additionally shows the pattern used to assert
*failure* modes: it round-trips the fixture's own `.cut` text, mutates one
literal (`EXPECT WS-TOTAL TO BE 5` -> `... 6`, or `WAS CALLED 3 TIMES` -> `...
2 TIMES`), writes it to `tmp_path`, and asserts `exit_code == 1` -- proving
the harness actually fails closed on a wrong expectation/verify count, not
just that the happy path returns 0.

# Worked examples (examples/)

Two full, documented, runnable programs under `examples/` -- these are
polished end-to-end demos (with READMEs), distinct from the terser
`tests/integration/fixtures/` corpus, and are also driven by their own
integration tests (`test_invupdt_example.py`, `test_ordrproc_example.py`):

## INVUPDT (`examples/invupdt/`)

Inventory updater touching **every** boundary category mockymock supports in
one program:

| Boundary | COBOL statement | Mock directive |
|----------|-----------------|-----------------|
| File open (2 files, 1 OPEN) | `OPEN INPUT INV-FILE OUTPUT RPT-FILE` | `MOCK OPEN INV-FILE` |
| Sequential read loop | `READ INV-FILE AT END ...` | `MOCK READ INV-FILE` (tally-driven EOF) |
| Report write | `WRITE RPT-REC` | `MOCK WRITE RPT-REC` |
| File close | `CLOSE INV-FILE RPT-FILE` | `MOCK CLOSE INV-FILE` |
| DB2 update | `EXEC SQL UPDATE INVENTORY ... END-EXEC` | `MOCK SQL "UPDATE INVENTORY"` |
| MQ notification | `CALL "MQPUT" USING MQ-COMPCODE` | `MOCK MQ "MQPUT"` |
| Operator input | `ACCEPT WS-CONFIRM` | `MOCK ACCEPT WS-CONFIRM` |

Notable design points the README calls out explicitly:

- **Tally-driven EOF**: the `READ` mock keeps its own tally field
  (`UT-READ-INV-FILE-TALLY`) to return two records, then signal end-of-file
  on the third call -- no real `INV.DAT` needed in the sandbox.
- **FD record areas without OPEN**: the `READ` mock `MOVE`s into `INV-QTY`
  (a FILE SECTION field) even though `INV-FILE` is never actually opened.
- **Static reachability still requires a mock for unreached code**: test
  case 2 hits EOF on the first read and so never executes the `WRITE`, but
  because `WRITE` is *statically* reachable it still needs a `MOCK WRITE` --
  verified via `VERIFY WRITE RPT-REC WAS PERFORMED NEVER`. This is a direct
  worked demonstration of reachability-driven refusal (see
  [analysis](analysis.md)): mockymock reasons about what a real GnuCOBOL
  compile could execute, not just what one test run happens to hit.
- **Error-path testing**: test case 2 forces `SQLCODE = -911` and asserts
  the program's failure branch actually runs.
- Also demonstrates `EXEC SQL INCLUDE SQLCA END-EXEC` replaced with a
  generated SQLCA so mock bodies can set `SQLCODE` directly (see
  [runtime](runtime.md) for the generated-SQLCA mechanism).

Run: `mockymock run examples/invupdt/INVUPDT.cbl --cut examples/invupdt/INVUPDT.cut`

## ORDRPROC (`examples/ordrproc/`)

Minimal program calling an external `DISCRATE` subprogram for a discount
rate, then computing a net amount. Demonstrates v1's narrowest mockable
category -- static `CALL` (a literal program name, as opposed to INVUPDT's
richer boundary set or the dynamic-call fixture's identifier-valued `CALL`).
The README frames it as the smallest possible teaching example: flip
`EXPECT WS-NET-AMOUNT TO BE 90.00` to a wrong value to see a FAIL, or run
`mockymock generate ORDRPROC.cbl` to see what auto-scaffolding produces from
a bare `.cbl` with no `.cut` at all.

Run: `mockymock run ORDRPROC.cbl --cut ORDRPROC.cut`

# CI (.github/workflows/ci.yml)

- Push/PR to `main`, `ubuntu-latest`, Python 3.11/3.12/3.13 matrix.
- Checks out `mocky-mock` *and* a sibling `Landparty/cobol-parser` checkout
  (path `cobol-parser`), because `requirements-dev.txt` installs cobolparser
  as an editable sibling (`-e ../cobol-parser`) -- mockymock is not on PyPI
  and depends on cobol-parser the same way the LegacyLens backend does.
- The cobol-parser checkout uses `secrets.COBOL_PARSER_PAT` (falling back to
  `GITHUB_TOKEN`) since the default token can't check out a different repo;
  this is a **known, flagged gap** -- if the PAT isn't configured and
  cobol-parser isn't public, the checkout step fails loudly by design rather
  than silently skipping the dependency.
- No GnuCOBOL install step -- the Docker toolchain builds
  `mockymock-gnucobol` on first use inside the job (~1 min cold).
- Single run step: `python -m pytest tests/ -v` -- unit and integration tests
  run together; integration tests self-skip if `docker info` fails, but
  `ubuntu-latest` ships Docker so in practice CI exercises both tiers.

# See Also

- [analysis](analysis.md) -- static reachability analysis that determines
  which boundary statements *must* be mocked (the INVUPDT `WRITE` case above
  is a direct consequence of this).
- [splicer](splicer.md) -- how `MOCK` bodies from the `.cut` DSL get spliced
  into the `.cbl` source before it's handed to GnuCOBOL.
- [runtime](runtime.md) -- generated SQLCA, tally fields, and other
  runtime-support scaffolding that mock bodies (like INVUPDT's `READ` tally
  and `SQLCODE` sets) depend on.
