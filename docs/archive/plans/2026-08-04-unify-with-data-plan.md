# Unify with-data Implementation Plan (port branch deliverables onto origin/main)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Unify the parked `feature/generate-with-data` branch with origin/main's released Phase 8 implementation: keep main's emission engine, port the branch's unique deliverables on top.

**Architecture:** Fresh branch `feature/unify-with-data` off origin/main (e87c027). Main's `dsl/fixture_bundle.py` + rewritten `dsl/generator.py` + AT-END replication stay the emission engine. Ported from the parked branch (worktree `../generate-with-data`, head 5f7dba9): the DSL `ROWS`-on-READ + `TERMINAL` grammar with splicer/refusal support (hand-authoring feature), the `mockymock fixtures` subcommand, `--rows`/`--placeholder` on `generate --with-data`, and the newest cobolparser pin. Evidence base: `.worktrees/generate-with-data/.superpowers/sdd/2026-08-04-generate-with-data-plan/reconciliation-scout.md`.

**Tech Stack:** Python 3.11+, pytest; same style gates as always (ruff/black 88/mypy, cov floor 83).

## Global Constraints

- Work in `C:/Users/samdi/Documents/workspace/legacylens/mocky-mock/.worktrees/unify-with-data` only. The parked worktree `../generate-with-data` is read-only source material.
- cobolparser pin target: `ff64b25c377150da432c57f39c43a0357ffeba86` (cobol-parser origin/main at reconciliation time — includes PR #110's gen-fixtures fixes and PR #112's EJECT support) — supersedes main's `b3e2b32`, the branch's `565b764`, and this plan's earlier `2a56db0` note *(bumped 2026-08-05 during Task 1: origin moved again; the sibling checkout's local docs commit was rebased onto it as `7324aa8`)*.
- Main's released behavior must not regress: `generate`, `generate --with-data`, `generate --fixtures`, `run --record-expectations`, `export`, `dashboard` all keep today's semantics; existing tests keep passing unmodified (adapting a test is a finding, not a default).
- Every generated `.cut` round-trips through `parse_cut()`.
- Full suite green (`python -m pytest tests/ -q`) with the coverage floor before any task is called done.

---

### Task 1: Pin bump + bundle-surface smoke port

- Rebase the sibling cobol-parser checkout's local `main` onto its origin/main (`git pull --rebase` in C:/Users/samdi/Documents/workspace/legacylens/cobol-parser — it holds one local docs-only commit d9e9a0e that must survive on top of 2a56db0), then editable-install it into the venv (`python -m pip install -e <abs path> --no-deps -q`).
- `pyproject.toml`: pin `cobolparser @ ...@2a56db0...` (full 40-char SHA from `git -C ../../../cobol-parser rev-parse origin/main`); update the comment block per house convention; bump the cobol-parser checkout ref(s) in `.github/workflows/ci.yml` (there are TWO — test and test-cross-platform).
- Port `tests/unit/test_bundle_surface.py` from the parked worktree verbatim; run it. PR #110 (33b984e) removed the gen-fixtures `--describe` CLI flag and fixed `write_csv_dir` manifest typing — neither is consumed by mockymock, but if the smoke test trips on a changed key, correct the test to the real shape (schema doc in cobol-parser is authoritative).
- Run main's own fixture-bundle contract tests (`tests/unit/test_fixture_bundle_contract.py`) against the new pin — they pin bundle-key == `_unique_prefix` equality and must still hold.
- Full suite; commit.

### Task 2: Port DSL ROWS/TERMINAL + splicer + refusal

- Cherry-pick from the parked branch: `ca25055` (DSL), `21e038b` + `c6e8a2f` (splicer/refusal). Expected drift: origin/main's `parser.py`/`injector.py`/`refusal.py` gained changes via 3ad3378/acb1663/4b05d84 — resolve conflicts preserving BOTH sides' behavior (main's AT-END replication is untouched by this grammar; they serve different paths: the grammar is for hand-written `.cut` files, main's replication is for generated ones).
- All parked-branch tests for these commits come along (`test_dsl_parser.py` additions, injector/refusal test additions). Full suite; commit(s).

### Task 3: Port the `mockymock fixtures` subcommand

- Hand-port (not cherry-pick — main's `cli/main.py` diverged) from parked `2b0f7e2`: subparser (`--scenarios happy|branches|all`, `--seed`, `--rows`, `--copybook-path`), `_cmd_fixtures` with the copybook-expansion + parse-success gate ordering, stdout purity (JSON only), stderr/exit-1 errors, `--rows 0` honored (`is not None`).
- Port `tests/unit/test_cli_fixtures.py` (4 tests) adapting imports/paths as needed. Full suite; commit.

### Task 4: `--rows` and `--placeholder` on main's `generate --with-data`

- `--rows N` → `DataGeneratorOptions(rows=N)` into main's `ProgramFixtureGenerator` construction on the `--with-data` (self-generating) path. Combining `--rows` with `--fixtures FILE` is a clean stderr error + exit 1 (the bundle's rows are already baked).
- `--placeholder CATEGORY:KEY` (repeatable) → main's emission engine (`dsl/generator.py`'s bundle-driven path) downgrades a matched fixture's body to the placeholder body; matching key is the fixture's own `(category, key)`; malformed value (no colon) → stderr naming `CATEGORY:KEY` + exit 1. Valid with `--fixtures` too (bundle consumed, selected fixtures placeholdered).
- Tests: rows plumbed (bundle row count changes), rows+fixtures rejection, placeholder downgrade (READ and one EXEC), malformed placeholder, no-flags path byte-identical. Full suite; commit.

### Task 5: Examples, contract test, docs, changelog

- Goldens: keep main's `examples/fixtures/` FIXTUREDEMO as the canonical golden. Do NOT port the parked `examples/fixturedemo/` duplicate. If `--placeholder`/`--rows` need a golden, extend main's example's test file.
- Port the parked `tests/unit/test_bundle_surface_keys.py` ONLY if it pins something main's `test_fixture_bundle_contract.py` does not (read both; the parked one checks bundle-vs-mock_surface key agreement incl. EXEC-by-line; main's checks bundle-key == `_unique_prefix`). If complementary, adapt and keep; if redundant, skip with a note in the report.
- OKF: `.okf/dsl.md` (ROWS on READ + TERMINAL grammar, hand-authoring scope), `.okf/splicer.md` (build_rows_block signature + READ WHEN OTHER), `.okf/analysis.md` (refusal trigger), `.okf/cli.md` (fixtures subcommand; --rows/--placeholder), `.okf/log.md` dated entry, CHANGELOG Unreleased. Reconcile with whatever PR #44 already documented — no contradictions left standing.
- Full suite; commit.
