---
okf_version: "0.1"
---

# mocky-mock OKF Bundle

Knowledge bundle for **mockymock** — mocks a COBOL program's external boundaries
(subprogram `CALL`s including MQ, file I/O, `EXEC SQL`/`CICS`/`DLI`, console
`ACCEPT`), compiles the instrumented copy with GnuCOBOL inside Docker, runs it,
and reports pass/fail. Version 0.1.0. Author: Samuel Dion.

## The `.cut` DSL and Codegen Pipeline

* [DSL](dsl.md) — `.cut` test-file grammar, `MockTestSuite`/`MockTestCase`/`MockDirective` model, parser, and the `generate` scaffolder
* [Analysis](analysis.md) — `mock_surface` boundary-site detection (CALL/file-I-O/EXEC SQL·CICS·DLI/ACCEPT) + `refusal.py`'s fail-closed reachability gate
* [Splicer](splicer.md) — turns boundary sites + a parsed `.cut` into spliced COBOL: dispatch blocks, tally fields, WORKING-STORAGE reset, generated SQLCA
* [Runtime](runtime.md) — Docker-only GnuCOBOL toolchain (`mockymock-cobc` container), compile/run, sandbox model
* [Report](report.md) — `__MOCKYMOCK__` stdout protocol, `TestResult`/`TestSuiteResult` model, console + JUnit XML formatters

## Entry Point

* [CLI](cli.md) — `mockymock setup` / `generate` / `run` / `mutate` and how each orchestrates the modules above

## Integration & Testing

* [Integration Contract](integration.md) — the cobolparser AST surface mockymock depends on (distills the repo-root [interface-contract.md](../interface-contract.md))
* [Testing](testing.md) — unit/integration split, Docker-availability skip gate, `tests/integration/fixtures/` corpus, and the two worked examples (INVUPDT, ORDRPROC)
* [Coverage](coverage.md) — `mockymock run --coverage`: GnuCOBOL/gcov-based per-line coverage reporting

## Change History

* [log.md](log.md) — Dated update log
