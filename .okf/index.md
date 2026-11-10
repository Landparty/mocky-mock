---
okf_version: "0.1"
---

# mocky-mock OKF Bundle

Knowledge bundle for **mockymock** — mocks a COBOL program's external boundaries
(subprogram `CALL`s including MQ, file I/O, `EXEC SQL`/`CICS`/`DLI`, console
`ACCEPT`), compiles the instrumented copy with GnuCOBOL inside Docker, runs it,
and reports pass/fail. The version lives in `mockymock/__init__.py`, kept in
step with `pyproject.toml` by release-please's `extra-files`. Distributed on PyPI as
`mocky-mock`. Author: Samuel Dion.

## Layering

Imports only point down; `tests/unit/test_layering.py` fails on one that
points up, and on any import cycle beyond the CLI's own (its
`KNOWN_CYCLES` may only shrink).

| Layer | Packages | Holds |
|---|---|---|
| interface | `cli`, `web`, `debug` | flags, console output, the DAP and HTTP protocols |
| features | `mutation`, `jobstream`, `report.test_report`, `report.html_report` | tools built on the engine |
| engine | `engine`, `project`, `api` | `engine.checks` (the static checks every command starts with), `engine.build` (one instrumented program from a checked suite: run, debug, export and mutate all build through it), `project` (config, discovery, assistant mode), `api` (the public Python API) |
| core | `dsl`, `analysis`, `splicer`, the rest of `report` | the pipeline's transforms |
| infra | `runtime`, `runner` | GnuCOBOL toolchains, child processes (`runtime._proc`), the oracle worker |

Two rules keep the core acyclic: `analysis` never imports
`dsl.generator` (the refusal gate receives the fix renderer as
`suggest_fix`), and shared walking helpers live in leaf modules
(`analysis/_program_walk.py`, `splicer/literals.py`, `runtime/_proc.py`).

## The `.cut` DSL and Codegen Pipeline

* [DSL](dsl.md) — `.cut` test-file grammar, `MockTestSuite`/`MockTestCase`/`MockDirective` model, parser, and the `generate` scaffolder
* [Analysis](analysis.md) — `mock_surface` boundary-site detection (CALL/file-I-O/EXEC SQL·CICS·DLI/ACCEPT) + the `refusal/` package's fail-closed reachability gate; `assertion_labels` (INTENT/CHARACTERIZATION labels on EXPECT/VERIFY) and `dialect_risk` (GnuCOBOL-vs-IBM divergence hotspots) for `mockymock report`
* [Splicer](splicer.md) — turns boundary sites + a parsed `.cut` into spliced COBOL: dispatch blocks, tally fields, WORKING-STORAGE reset, synthesized `UT-CAP-` capture targets, generated SQLCA
* [Runtime](runtime.md) — GnuCOBOL toolchain: the `mockymock-cobc` container (default) or a bundled native tree (`MOCKYMOCK_GNUCOBOL_HOME`), compile/run, sandbox model
* [Report](report.md) — `__MOCKYMOCK__` stdout protocol, `TestResult`/`TestSuiteResult` model, console + JUnit XML + JSON formatters, execution trace; the `mockymock report` builder/HTML renderer and the assistant step journal

## Entry Point

* [CLI](cli.md) — the subcommands (`setup` / `init` / `generate` / `fixtures` / `run` / `debug` / `lint` / `mutate` / `collect` / `explain` / `dashboard` / `doctor` / `export` / `analyze` / `skills` / `report` / `journal` / `clean` / `runner`), how argument resolution and the project config file work, and how each subcommand orchestrates the modules above. Also the home of the `debug` DAP adapter (`mockymock/debug/`), `mutate` (`mockymock/mutation/`), and `export` (`engine/mainframe_export.py`) write-ups.
* [Dashboard](dashboard.md) — `mockymock dashboard` (loopback static page) and `mockymock doctor` (terminal-native), plus the read-only `runtime.status` Docker health probe both sit on

## Integration & Testing

* [Integration Contract](integration.md) — the cobolparser AST surface mockymock depends on (distills the repo-root [interface-contract.md](../interface-contract.md))
* [Testing](testing.md) — unit/integration split, the Docker-availability skip gate, `tests/integration/fixtures/` corpus, the enterprise program-type corpus, the worked examples, and **which CI jobs are currently switched off**
* [Coverage](coverage.md) — `mockymock run --coverage`: GnuCOBOL/gcov-based per-line coverage reporting

## Publishing

* [Publishing](publishing.md) — mockymock publishes a plain sdist+wheel to PyPI (`release-please.yml`); the separate Nuitka-executable path mocky-mock-vscode's `build-and-release.yml` builds from source is unaffected

## Change History

* [log.md](log.md) — Dated update log, **newest entry first**
* [docs/index.md](../docs/index.md) — every design record and audit in `docs/` with its current status (implemented / partial / superseded), checked against the code; the two open gaps the designs still name
