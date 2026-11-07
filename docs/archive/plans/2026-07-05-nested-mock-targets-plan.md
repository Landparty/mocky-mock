# Nested Mock Targets Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make nested boundary statements (inside IF/EVALUATE/inline-PERFORM bodies) mockable in every category, refusing only layouts that cannot be spliced provably safely.

**Architecture:** A lexer-derived scope-boundary map (`collect_scope_map`) locates the block words the AST lacks (ELSE/WHEN/END-IF/...); `annotate_nested_sites` stamps each nested `BoundarySite` with a validated replacement span or a precise `unspliceable_reason`. The refusal gate and splicer then read the annotation: safe nested sites get the normal EVALUATE dispatch / EXEC trap, unsafe ones keep narrowed `UNSUPPORTED_NESTED_MOCK_TARGET` / `NESTED_EXEC` refusals. Spec: `docs/2026-07-05-nested-mock-targets-design.md`.

**Tech Stack:** Python 3.14, cobolparser (editable sibling), pytest; GnuCOBOL-in-Docker for integration tests.

## Global Constraints

- Top-level splicing behavior must not change (`collect_boundaries` / `statement_span` untouched).
- Fail closed: a nested site without a validated span must always be refused, never silently skipped or spliced.
- All refusal codes keep their existing names; only their firing conditions narrow.
- Run tests with `./.venv/Scripts/python.exe -m pytest tests/unit -q` (integration: `tests/integration`, requires Docker).

---

### Task 1: `nested_in_boundary` flag + annotation fields on BoundarySite

**Files:**
- Modify: `mockymock/analysis/mock_surface.py`
- Test: `tests/unit/test_mock_surface_v2.py`

**Interfaces:**
- Produces: `BoundarySite.nested_in_boundary: bool`, `BoundarySite.span: tuple[int, int] | None`, `BoundarySite.unspliceable_reason: str | None`; `_walk_statements(..., in_boundary: bool = False)`.

- [x] Write failing tests: a CALL inside `CALL ... ON EXCEPTION` has `nested_in_boundary=True`; a CALL inside IF/EVALUATE-WHEN/inline-PERFORM has `nested=True, nested_in_boundary=False`.
- [x] Implement: add the three fields (defaults `False`/`None`/`None`); add module tuple `_BOUNDARY_STATEMENT_TYPES` (CallStatement, the eight IO types, EXEC types, IOAcceptStatement, SORT/MERGE types); `_walk_statements` gains `in_boundary` and passes `in_boundary or isinstance(statement, _BOUNDARY_STATEMENT_TYPES)` when recursing; `_classify_statement` forwards it into every `BoundarySite`.
- [x] Tests pass; commit.

### Task 2: scope map + nested-span annotation in source_map

**Files:**
- Modify: `mockymock/splicer/source_map.py`
- Test: `tests/unit/test_source_map.py`

**Interfaces:**
- Produces:
  - `@dataclass ScopeBoundary(line: int, column: int, word: str)` — `word` is the uppercase scope word, `""` for statement-start/paragraph boundaries.
  - `collect_scope_map(program, lines: list[str]) -> ScopeMap` where `ScopeMap.boundaries: list[ScopeBoundary]` sorted by (line, column). Contents: paragraph headers (phantom `"."` excluded), statement starts at every depth (recursion via `_nested_statement_lists`), and lexer tokens whose uppercase value is in `_SCOPE_WORDS` (ELSE, WHEN, OTHERWISE, END-IF, END-EVALUATE, END-PERFORM, END-CALL, END-READ, END-WRITE, END-REWRITE, END-DELETE, END-START, END-ACCEPT, END-EXEC, END-SEARCH, END-STRING, END-UNSTRING, END-COMPUTE, END-ADD, END-SUBTRACT, END-MULTIPLY, END-DIVIDE, END-DISPLAY, END-RETURN) — excluding tokens on lines inside any `EXEC ... END-EXEC` range (embedded SQL may contain WHEN/ELSE/CASE text).
  - `annotate_nested_sites(surface, scope_map, lines) -> None` — for each `site.nested` BoundarySite sets `site.span` or `site.unspliceable_reason` per the spec's five rules (control-flow ancestry only; no clause bodies of its own; owns its start line; clean next boundary, own-verb terminator exempt; EXEC span must contain END-EXEC).

- [x] Write failing tests covering: span for a multi-line nested CALL in IF-then; nested CALL in ELSE branch, WHEN branch, WHEN OTHER, inline PERFORM body; explicit `END-CALL` included in span; refusal reasons for `IF X CALL "F" END-IF` one-liner, glued trailing `END-IF`, CALL with ON EXCEPTION handler (clause bodies), CALL inside a CALL handler (boundary ancestry), nested EXEC SQL span includes END-EXEC, and EXEC text containing `CASE WHEN` not truncating the span.
- [x] Implement `_SCOPE_WORDS`, `ScopeBoundary`, `ScopeMap`, `collect_scope_map`, `_VERB_TERMINATORS` ({CALL: END-CALL, READ: END-READ, WRITE: END-WRITE, REWRITE: END-REWRITE, DELETE: END-DELETE, START: END-START, ACCEPT: END-ACCEPT}), `annotate_nested_sites`.
- [x] Tests pass; commit.

### Task 3: narrow the refusal gate

**Files:**
- Modify: `mockymock/analysis/refusal.py`
- Test: `tests/unit/test_refusal_v2.py`

**Interfaces:**
- Consumes: `site.span` / `site.unspliceable_reason` (annotation must have run; `span is None` on a nested site ⇒ refuse — fail closed).
- Produces: unchanged signatures `check_nested_exec(surface)`, `check_test_case(surface, program, case)`.

- [x] Write failing tests: a mocked nested CALL in an IF with a clean layout passes the gate (no `UNSUPPORTED_NESTED_MOCK_TARGET`) after annotation; the same program *without* annotation still refuses; a one-liner nested CALL still refuses with the layout reason in the message; a spliceable nested EXEC no longer triggers `NESTED_EXEC`; an EXEC inside a CALL handler still does.
- [x] Implement: both nested branches condition on `site.span is None` and append `site.unspliceable_reason or "nested-site spliceability was not annotated"` to the message.
- [x] Tests pass; commit.

### Task 4: splice nested sites in the orchestrator

**Files:**
- Modify: `mockymock/splicer/orchestrator.py`
- Test: `tests/unit/test_orchestrator.py`

**Interfaces:**
- Consumes: `site.span` for nested sites; `statement_span` for top-level (unchanged).
- Produces: unchanged signature `splice_program(lines, boundaries, surface, suite, registry)`; caller must run `annotate_nested_sites` first.

- [x] Write failing tests: mocked nested CALL inside IF — original CALL lines commented, dispatch block present, `END-IF` line NOT commented, trailing period preserved on the replacement when the span carried it; unmocked nested EXEC SQL gets the trap stub and its END-EXEC line is commented; unmocked nested non-EXEC site left untouched; nested site with `span=None` that is mocked raises ValueError.
- [x] Implement: replace the `site.nested` skip with span/mock handling per design; update module docstring (nested sites *do* reach this module now).
- [x] Tests pass; commit.

### Task 5: wire generate/run CLI + scaffold nested sites

**Files:**
- Modify: `mockymock/cli/main.py`, `mockymock/dsl/generator.py`
- Test: `tests/unit/test_dsl_generator.py`, `tests/unit/test_cli_docker.py` (only if touched paths break)

**Interfaces:**
- Consumes: `collect_scope_map`, `annotate_nested_sites`.
- Produces: `generate` scaffolds spliceable nested sites and reports only unspliceable ones (reason included); `run` normalizes + annotates before `check_nested_exec`/`check_test_case`/`splice_program`.

- [x] Write failing test: scaffold from a program whose only CALL is nested inside an IF includes `MOCK CALL "..."` (today it yields no TESTCASE).
- [x] Implement: generator skip condition becomes `site.category is None or (site.nested and site.span is None)`; `_cmd_generate` normalizes source and annotates; `_cmd_run` moves normalization above `check_nested_exec` and annotates; `_report_unsupported_boundaries` prints `site.unspliceable_reason`.
- [x] Tests pass; commit.

### Task 6: integration test end-to-end

**Files:**
- Create: `tests/integration/fixtures/nested_boundaries.cbl`, `tests/integration/fixtures/nested_boundaries.cut`
- Test: `tests/integration/test_nested_boundaries.py`

- [x] Fixture: program with a CALL inside IF, a CALL inside EVALUATE WHEN, and an EXEC SQL inside IF; .cut mocking all three with VERIFY tallies.
- [x] Test drives `mockymock run` via the CLI (same Docker gating as `test_invupdt_example.py`) and asserts exit 0 + all cases PASS.
- [x] Full suite green: `python -m pytest tests/unit -q` and (Docker available) `tests/integration -q`; commit.
