# mockymock Real-World Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the gaps between mockymock's current prototype state and running reliably against a real mainframe COBOL portfolio, sequenced so the completable safety and hardening work lands first and the large engine features are gated behind a measured corpus sweep.

**Architecture:** Three execution tiers plus one cross-repo tier. Tier 1 is independent quick wins (any order). Tier 2 is the safety spine — a corpus sweep that *measures* refusal rates and doubles as the acceptance oracle for an AST-fidelity safeguard, plus a real recursive WORKING-STORAGE reset fix. Tier 3 is medium features. Tier 4 is large engine features, each gated by its own design spike AND by what the Tier-2 corpus sweep shows is actually common. Tier 0 (cross-repo) fixes the two cobolparser bugs that block mockymock's own flagship examples.

**Tech Stack:** Python 3.11+, `argparse` CLI, cobolparser (editable sibling install, no PyPI pin), GnuCOBOL 3.2 in Docker (`debian:trixie-slim`), pytest (unit + Docker-gated integration tiers).

## Global Constraints

- **Python floor: 3.11** (`requires-python = ">=3.11"`); code targets 3.11/3.12/3.13.
- **No new runtime dependencies.** `pyproject.toml` `dependencies = []` stays empty; cobolparser is an editable sibling install, not a pinned PyPI package. Any pin is expressed as a documented floor, never a hard `pyproject` constraint that would break the editable-install workflow.
- **Docker-only compile/run.** No local-`cobc` fallback may be reintroduced. Everything COBOL-related runs in the `mockymock-cobc` container.
- **Fail-closed is the invariant.** New analysis must refuse loudly on uncertainty, never silently pass. A new safeguard that produces even one false refusal on a known-good program is a defect, not a tuning nuisance.
- **Verification honesty (critical for this plan):** the integration tier self-skips when `docker info` fails. Docker is **NOT available in the authoring session** and may not be in every executor session. Every task below is tagged `Verify (unit)` (fully provable without Docker) or `Verify (integration/Docker)` (requires a Docker-capable machine; a green unit run does NOT prove it). Do not claim an integration-tagged task complete on unit tests alone.
- **Commit style:** end each commit message with `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- **Standard verification commands:** unit = `python -m pytest tests/unit -v`; full = `python -m pytest tests/ -v`.

---

## Tier 1 — Independent quick wins (any order, all `Verify (unit)` unless noted)

These have no interdependencies and each is completable and provable in a Docker-free session (except Task 4's runtime half). Land them first.

### Task 1: LICENSE + packaging honesty

**Files:**
- Create: `LICENSE`
- Modify: `pyproject.toml:5-25` (add `license` + `license-files`)
- Modify: `README.md` (append a short `## License` section)

**Interfaces:**
- Consumes: nothing.
- Produces: a distributable, legally-adoptable package. No code symbols.

- [ ] **Step 1: Choose and write the license.** Use MIT (permissive, matches an Alpha dev-tool; confirm with repo owner if a different license is mandated). Create `LICENSE` with the standard MIT text, `Copyright (c) 2026 Samuel Dion`.

- [ ] **Step 2: Wire it into packaging.** In `pyproject.toml` `[project]`, add:
```toml
license = "MIT"
license-files = ["LICENSE"]
```

- [ ] **Step 3: Verify metadata resolves.**
Run: `python -c "import tomllib,pathlib; d=tomllib.loads(pathlib.Path('pyproject.toml').read_text()); print(d['project']['license'])"`
Expected: prints `MIT` with no exception.

- [ ] **Step 4: Add a README License section** naming MIT and pointing at `LICENSE`.

- [ ] **Step 5: Commit.**
```bash
git add LICENSE pyproject.toml README.md
git commit -m "chore: add MIT LICENSE and packaging metadata"
```

### Task 2: DSL hardening — unterminated `MOCK` body is an error

**Files:**
- Modify: `mockymock/dsl/parser.py:70-160` (`parse_cut`)
- Test: `tests/unit/test_dsl_parser.py`

**Interfaces:**
- Consumes: `CutParseError` (existing).
- Produces: `parse_cut` raises `CutParseError` on EOF while `in_mock is not None`.

- [ ] **Step 1: Write the failing test.**
```python
def test_unterminated_mock_body_raises():
    text = (
        'TESTSUITE "s"\n'
        'TESTCASE "c"\n'
        '    MOCK CALL "X"\n'
        '        MOVE 0 TO RETURN-CODE\n'
        '    PERFORM MAIN\n'  # no END-MOCK: silently swallowed today
    )
    with pytest.raises(CutParseError, match="unterminated MOCK"):
        parse_cut(text)
```

- [ ] **Step 2: Run it, verify it fails.**
Run: `python -m pytest tests/unit/test_dsl_parser.py::test_unterminated_mock_body_raises -v`
Expected: FAIL (no exception raised — body absorbs the rest of the file).

- [ ] **Step 3: Implement.** In `parse_cut`, after the `for` loop and before `if suite is None`, add:
```python
    if in_mock is not None:
        raise CutParseError(
            f"unterminated MOCK {in_mock.describe()}: reached end of file "
            f"with no END-MOCK"
        )
```

- [ ] **Step 4: Run the whole parser suite, verify green.**
Run: `python -m pytest tests/unit/test_dsl_parser.py tests/unit/test_dsl_parser_v2.py -v`
Expected: PASS (new test passes; no regression — there is no existing test pinning the old swallow behavior, per dsl.md Gotchas).

- [ ] **Step 5: Commit.**
```bash
git add mockymock/dsl/parser.py tests/unit/test_dsl_parser.py
git commit -m "fix(dsl): raise on unterminated MOCK body instead of swallowing file"
```

### Task 3: DSL hardening — duplicate `PERFORM` in one TESTCASE is an error

**Files:**
- Modify: `mockymock/dsl/parser.py:124-128` (PERFORM branch)
- Test: `tests/unit/test_dsl_parser.py`

**Interfaces:**
- Consumes: `MockTestCase.perform_target` (existing; `None` until first PERFORM).
- Produces: second PERFORM in a case raises `CutParseError`.

- [ ] **Step 1: Write the failing test.**
```python
def test_duplicate_perform_raises():
    text = (
        'TESTSUITE "s"\n'
        'TESTCASE "c"\n'
        '    PERFORM ONE\n'
        '    PERFORM TWO\n'
    )
    with pytest.raises(CutParseError, match="already has a PERFORM"):
        parse_cut(text)
```

- [ ] **Step 2: Run it, verify it fails.**
Run: `python -m pytest tests/unit/test_dsl_parser.py::test_duplicate_perform_raises -v`
Expected: FAIL (last-write-wins today, no error).

- [ ] **Step 3: Implement.** Replace the PERFORM branch body:
```python
        elif (m := _PERFORM_RE.match(line)) is not None:
            if case is None:
                raise CutParseError(f"line {line_no}: PERFORM outside TESTCASE")
            if case.perform_target is not None:
                raise CutParseError(
                    f"line {line_no}: TESTCASE {case.name!r} already has a "
                    f"PERFORM target {case.perform_target!r}; one PERFORM "
                    f"per test case"
                )
            case.perform_target = m.group("target")
            case.perform_thru = m.group("thru")
```
Confirm `MockTestCase.perform_target` defaults to `None` in `model.py` (it does per dsl.md); if it defaults to `""`, guard on `if case.perform_target:` instead.

- [ ] **Step 4: Run parser suites, verify green.**
Run: `python -m pytest tests/unit/test_dsl_parser.py tests/unit/test_dsl_parser_v2.py -v`
Expected: PASS.

- [ ] **Step 5: Commit.**
```bash
git add mockymock/dsl/parser.py tests/unit/test_dsl_parser.py
git commit -m "fix(dsl): reject duplicate PERFORM in a single TESTCASE"
```

### Task 4: `--keep-sandbox` / `--verbose` debug escape hatch

**Files:**
- Modify: `mockymock/cli/main.py:96-210` (`_cmd_run`), `:254-265` (run subparser)
- Test: `tests/unit/test_cli_docker.py` (arg wiring), `tests/integration/test_cli.py` (behavior, Docker)

**Interfaces:**
- Consumes: `sandbox_dir` (existing).
- Produces: `mockymock run ... --keep-sandbox` prints the retained sandbox path and does not delete it; `--verbose` prints the instrumented source path on compile failure.

- [ ] **Step 1: Write the failing unit test (arg wiring only — no Docker).**
```python
def test_run_parser_accepts_keep_sandbox_and_verbose():
    from mockymock.cli.main import build_parser
    args = build_parser().parse_args(
        ["run", "P.cbl", "--cut", "P.cut", "--keep-sandbox", "--verbose"]
    )
    assert args.keep_sandbox is True
    assert args.verbose is True
```

- [ ] **Step 2: Run it, verify it fails.**
Run: `python -m pytest tests/unit/test_cli_docker.py::test_run_parser_accepts_keep_sandbox_and_verbose -v`
Expected: FAIL (`unrecognized arguments`).

- [ ] **Step 3: Add the flags to the run subparser** (after `--copybook-path`):
```python
    run_parser.add_argument(
        "--keep-sandbox",
        action="store_true",
        help="Do not delete the sandbox; print its path for inspection",
    )
    run_parser.add_argument(
        "--verbose",
        action="store_true",
        help="On compile failure, print the path to the instrumented source",
    )
```

- [ ] **Step 4: Thread `keep_sandbox` through `_cmd_run`.** Replace the `with sandbox_dir(...) as tmp:` block so that when `args.keep_sandbox` is set, the directory is created outside the context manager (so it survives) and its path is printed. Minimal implementation:
```python
    import tempfile
    from mockymock.runtime import docker_toolchain as _dt

    if args.keep_sandbox:
        _dt.WORK_ROOT.mkdir(parents=True, exist_ok=True)
        tmp = Path(tempfile.mkdtemp(prefix="mockymock-", dir=_dt.WORK_ROOT))
        print(f"mockymock run: keeping sandbox {tmp}")
        cleanup = None
    else:
        _ctx = sandbox_dir(root=docker_toolchain.WORK_ROOT)
        tmp = _ctx.__enter__()
        cleanup = _ctx
    try:
        instrumented_path = tmp / source_path.with_suffix(".cbl").name
        instrumented_path.write_text("\n".join(instrumented) + "\n", newline="\n")
        compiled = docker_toolchain.compile_source(instrumented_path)
        if not compiled.success:
            print("mockymock run: compile failed:")
            print(compiled.stderr)
            if args.verbose or args.keep_sandbox:
                print(f"mockymock run: instrumented source at {instrumented_path}")
            return 1
        executed = docker_toolchain.run_binary(compiled.binary_path)
    finally:
        if cleanup is not None:
            cleanup.__exit__(None, None, None)
```
(Prefer refactoring the manual `__enter__`/`__exit__` into a small helper if the reviewer objects to the idiom; behavior is what matters.)

- [ ] **Step 5: Run the arg-wiring test, verify green.**
Run: `python -m pytest tests/unit/test_cli_docker.py::test_run_parser_accepts_keep_sandbox_and_verbose -v`
Expected: PASS.

- [ ] **Step 6: `Verify (integration/Docker)` — behavior.** On a Docker-capable machine, add a test asserting a deliberately-broken program under `--keep-sandbox` leaves the `.cbl` on disk and prints its path. Mark `@requires_docker`. Run `python -m pytest tests/integration/test_cli.py -v`. **This step cannot be closed in a Docker-free session — leave it unchecked and note "pending Docker" if Docker is absent.**

- [ ] **Step 7: Commit.**
```bash
git add mockymock/cli/main.py tests/unit/test_cli_docker.py tests/integration/test_cli.py
git commit -m "feat(cli): add --keep-sandbox and --verbose for run debugging"
```

### Task 5: Docker image staleness — content-tagged image

**Files:**
- Modify: `mockymock/runtime/docker_toolchain.py:24-30` (IMAGE constant), `:75-113` (`ensure_toolchain`)
- Test: `tests/unit/test_docker_toolchain.py`

**Interfaces:**
- Consumes: `_DOCKER_CONTEXT` (existing).
- Produces: `IMAGE` becomes `mockymock-gnucobol:<tag>` where `<tag>` is an 8-char hash of `docker/Dockerfile` content; a changed Dockerfile changes the tag so `image inspect` misses and rebuilds.

- [ ] **Step 1: Write the failing test.**
```python
def test_image_tag_changes_with_dockerfile(monkeypatch, tmp_path):
    from mockymock.runtime import docker_toolchain as dt
    tag_a = dt._image_tag(dockerfile_text="FROM debian:trixie-slim\n")
    tag_b = dt._image_tag(dockerfile_text="FROM debian:trixie-slim\nRUN true\n")
    assert tag_a != tag_b
    assert dt.IMAGE.startswith("mockymock-gnucobol:")
```

- [ ] **Step 2: Run it, verify it fails.**
Run: `python -m pytest tests/unit/test_docker_toolchain.py::test_image_tag_changes_with_dockerfile -v`
Expected: FAIL (`_image_tag` undefined; `IMAGE` has no `:` tag).

- [ ] **Step 3: Implement the tag.** In `docker_toolchain.py`:
```python
import hashlib

def _image_tag(dockerfile_text: str | None = None) -> str:
    if dockerfile_text is None:
        dockerfile_text = (_DOCKER_CONTEXT / "Dockerfile").read_text()
    return hashlib.sha256(dockerfile_text.encode()).hexdigest()[:8]

IMAGE = f"mockymock-gnucobol:{_image_tag()}"
```
Move `_DOCKER_CONTEXT` above `IMAGE`. Everything else (`_docker("image","inspect",IMAGE,...)`, `docker build -t IMAGE`) already interpolates `IMAGE`, so a new tag rebuilds automatically.

- [ ] **Step 4: Update the constant-drift assertions.** `test_docker_toolchain.py` and runtime.md assert `IMAGE == "mockymock-gnucobol"`. Update the unit test to assert the `startswith` form; note the runtime.md constant table needs refreshing (Tier-5 docs task).

- [ ] **Step 5: Run, verify green.**
Run: `python -m pytest tests/unit/test_docker_toolchain.py -v`
Expected: PASS.

- [ ] **Step 6: `Verify (integration/Docker)`** that a rebuild is triggered after editing the Dockerfile — pending Docker.

- [ ] **Step 7: Commit.**
```bash
git add mockymock/runtime/docker_toolchain.py tests/unit/test_docker_toolchain.py
git commit -m "fix(runtime): content-tag the GnuCOBOL image so Dockerfile edits rebuild"
```

### Task 6: Report — surface unknown case-id in FAIL lines instead of dropping

**Files:**
- Modify: `mockymock/report/results.py:48-72` (`parse_stdout`), add an `orphan_failures` field to `TestSuiteResult:36-45`
- Modify: `mockymock/report/formatters.py` (render orphans)
- Test: `tests/unit/test_report.py`

**Interfaces:**
- Consumes: existing markers.
- Produces: `TestSuiteResult.orphan_failures: list[tuple[str,str]]` (id, reason) for FAIL/END lines whose id was never in a START; `all_passed` returns `False` when `orphan_failures` is non-empty.

- [ ] **Step 1: Write the failing test.**
```python
def test_fail_line_with_unknown_case_id_is_surfaced():
    out = (
        "__MOCKYMOCK__ TESTSUITE: s\n"
        "__MOCKYMOCK__ CASE 001 START: c\n"
        "__MOCKYMOCK__ CASE 999 FAIL: orphaned reason\n"
        "__MOCKYMOCK__ CASE 001 END\n"
        "__MOCKYMOCK__ SUMMARY: RUN=1 FAILURES=0\n"
    )
    suite = parse_stdout(out)
    assert ("999", "orphaned reason") in suite.orphan_failures
    assert suite.all_passed is False
```

- [ ] **Step 2: Run it, verify it fails.**
Run: `python -m pytest tests/unit/test_report.py::test_fail_line_with_unknown_case_id_is_surfaced -v`
Expected: FAIL (no `orphan_failures`; suite reports passed).

- [ ] **Step 3: Implement.** Add `orphan_failures: list[tuple[str, str]] = field(default_factory=list)` to `TestSuiteResult`. In the FAIL branch, `else: suite.orphan_failures.append((m.group("id"), m.group("reason")))`. Update `all_passed`:
```python
    @property
    def all_passed(self) -> bool:
        return (
            self.failures == 0
            and self.tests_run > 0
            and not self.orphan_failures
        )
```

- [ ] **Step 4: Render in both formatters.** In `format_console`, after the per-case block, if `suite.orphan_failures` print an `ORPHANED FAILURES (unknown case id):` section. In `format_junit_xml`, add each orphan as a `<testcase name="orphan-<id>"><error .../></testcase>` and include them in `errors=`.

- [ ] **Step 5: Run report suite, verify green.**
Run: `python -m pytest tests/unit/test_report.py -v`
Expected: PASS.

- [ ] **Step 6: Commit.**
```bash
git add mockymock/report/results.py mockymock/report/formatters.py tests/unit/test_report.py
git commit -m "fix(report): surface FAIL lines with unknown case id instead of dropping them"
```

---

## Tier 2 — The safety spine (SEQUENTIAL; Task 7 gates Task 8)

### Task 7: Corpus sweep harness + measured refusal report

**Rationale:** This is priority-#3 from the audit AND the acceptance oracle for Task 8's safeguard AND the gate for all of Tier 4. It must run first. It is a measurement/reporting deliverable, not an engine change.

**Files:**
- Create: `scripts/corpus_sweep.py`
- Create: `docs/corpus-sweep-report.md` (generated output, committed as a baseline)

**Interfaces:**
- Consumes: `mockymock generate` via `mockymock.cli.main.main`; `mockymock.analysis` refusal codes.
- Produces: a per-program, per-refusal-code table over all 17 `../legacy-application/cobol/*.cbl` programs + `tests/integration/fixtures/*.cbl`.

- [ ] **Step 1: Write the sweep script.** It must, for each program: locate copybooks (`../legacy-application/copybooks` if present), run `generate` capturing stdout, and tally (a) parse errors, (b) each `refused (<CODE>)` line, (c) each `not mockable` boundary line by category. No Docker needed — `generate` is parse-and-analyze only. Emit a Markdown table `program × {parsed?, refusal codes, unmockable-boundary counts}` and a per-code total footer.

- [ ] **Step 2: Run the sweep.**
Run: `python scripts/corpus_sweep.py > docs/corpus-sweep-report.md`
Expected: a table covering all 17 programs; no traceback.

- [ ] **Step 3: Read the report and record findings inline** at the top of `docs/corpus-sweep-report.md`: the three most common refusal codes, which categories (SORT/MERGE, DYNAMIC_CALL, NESTED_EXEC, etc.) dominate, and how many programs parse at all. **This table replaces the audit's guesswork and drives Tier-4 prioritization.**

- [ ] **Step 4: Commit.**
```bash
git add scripts/corpus_sweep.py docs/corpus-sweep-report.md
git commit -m "chore: add corpus-sweep harness and baseline refusal report"
```

- [ ] **Step 5: GATE.** Review the report with the repo owner before building Task 8's detector and before any Tier-4 task. If a Tier-4 category (e.g. CICS) shows zero occurrences, drop it from scope here rather than building it speculatively.

### Task 8: AST-fidelity cross-check (design-gated safeguard)

**Rationale:** The single highest-value safety fix — refuse when cobolparser silently drops a boundary statement (the COMPUTE-swallows-CALL and dropped-EXEC-SQL bug classes). **Its acceptance criterion is "zero false refusals across the entire Task-7 corpus."** Because the algorithm has a real false-positive surface (EXEC SQL legitimately uses `OPEN`/`CLOSE`/`DELETE`/`FETCH` as keywords), it gets a mandatory design step and is NOT written as if the algorithm is obvious.

**Files:**
- Create: `mockymock/analysis/fidelity.py`
- Modify: `mockymock/cli/main.py` (`_cmd_run` and `_cmd_generate`: call after parse, before splice)
- Test: `tests/unit/test_fidelity.py`
- Design: `docs/2026-07-06-ast-fidelity-design.md`

**Interfaces:**
- Consumes: `CobolLexer`/`TokenType` (as `refusal.check_unresolved_copybooks` does), `source_map._exec_range`/`_inside_exec_range` (reuse — do NOT reimplement EXEC-range exclusion), the AST paragraph/statement line map.
- Produces: `check_ast_fidelity(raw_source, ast) -> list[RefusalReason]` with code `AST_FIDELITY_GAP`.

- [ ] **Step 1: Design spike (write `docs/2026-07-06-ast-fidelity-design.md`).** Decide and document:
  - **Detector MVP (advisor-recommended):** a boundary-verb token (`CALL`, the 8 file-op verbs, `EXEC`) that begins a statement on a source line where the AST has **no** statement starting — the exact signature of the COMPUTE-swallows-CALL bug (the swallowed `CALL 'MQOPEN'` sits on its own line with no AST node).
  - **Mandatory EXEC exclusion:** skip any candidate token inside an `EXEC ... END-EXEC` range using `source_map._exec_range`/`_inside_exec_range`. Enumerate why (DB2 `DELETE`/`OPEN`/`CLOSE`/`FETCH` keywords).
  - **False-positive budget:** best-effort, fail-*open* on ambiguity within this detector specifically — it is a secondary net, and a false refusal here breaks good programs. State this explicitly (it is the one place in the codebase where fail-open is correct, because the primary refusal gate already fails closed).
  - **Acceptance oracle:** the Task-7 corpus. Zero `AST_FIDELITY_GAP` on all programs that are otherwise accepted today.

- [ ] **Step 2: Write failing tests from the design** — one positive (a COMPUTE-swallows-CALL fixture MUST refuse), several negative (every legitimate EXEC-keyword shape and every currently-passing fixture/example MUST NOT refuse). Use the real `tests/integration/fixtures/*.cbl` and `examples/**/*.cbl` as negative corpus in a parametrized test.

- [ ] **Step 3: Run tests, verify the positive fails and negatives pass-by-absence.**
Run: `python -m pytest tests/unit/test_fidelity.py -v`
Expected: positive-case test FAILs (no refusal yet), negative tests pass trivially.

- [ ] **Step 4: Implement `check_ast_fidelity`** per the design, reusing the EXEC-range helpers.

- [ ] **Step 5: Wire into `_cmd_run` and `_cmd_generate`** after `parse_cobol` succeeds and after copybook checks, printing `refused (AST_FIDELITY_GAP): ...` and returning 1. Place it before `analyze()`.

- [ ] **Step 6: Run unit tests, verify green.**
Run: `python -m pytest tests/unit/test_fidelity.py -v`
Expected: PASS.

- [ ] **Step 7: Re-run the corpus sweep (Task 7) with the detector active** and confirm **zero new refusals** on programs accepted before. Any new refusal on good code is a defect — fix the detector, do not suppress the test.
Run: `python scripts/corpus_sweep.py > /tmp/sweep_after.md` and diff against the baseline.

- [ ] **Step 8: Commit.**
```bash
git add mockymock/analysis/fidelity.py mockymock/cli/main.py tests/unit/test_fidelity.py docs/2026-07-06-ast-fidelity-design.md
git commit -m "feat(analysis): AST-fidelity cross-check to catch silently-dropped boundary statements"
```

### Task 9: Recursive VALUE-restoring WORKING-STORAGE reset

**Rationale:** The advisor inverted the audit's suggested difficulty: the real fix (restore group children's VALUE clauses) is a contained AST change in `reset.py` and actually solves the silent-constant-corruption bug the real-world spike hit (`MOVE MQCC-FAILED` silently became `MOVE 0`). Prefer it over the flaky "warn on mock-body reference" idea.

**Files:**
- Modify: `mockymock/splicer/reset.py:18-45` (`reset_move_lines`), add a recursive walker
- Test: `tests/unit/test_reset.py`

**Interfaces:**
- Consumes: `_is_group`, `_top_level_items`, `_default_value_literal` (existing), `CobolDataItem.name/.level/.value_clause/.children`.
- Produces: for a group whose children (recursively) carry VALUE clauses, emit per-child `MOVE <value> TO <child-name>` for those children plus `INITIALIZE <group>` first, so declared constants survive a reset.

- [ ] **Step 1: Write the failing test.** Model a group like `MQMSG.cpy`'s `MQ-CONSTANTS` (group, no group-level VALUE, children with `VALUE +2` etc.):
```python
def test_group_children_value_clauses_are_restored():
    program = _parse(
        "       01 MQ-CONSTANTS.\n"
        "          05 MQCC-OK    PIC S9(9) VALUE +0.\n"
        "          05 MQCC-FAIL  PIC S9(9) VALUE +2.\n"
    )
    lines = reset_move_lines(program)
    assert "INITIALIZE MQ-CONSTANTS" in lines
    assert any("MOVE +2 TO MQCC-FAIL" in ln for ln in lines)
```
(Use the same parse helper the existing `test_reset.py` uses; match its VALUE literal formatting.)

- [ ] **Step 2: Run it, verify it fails.**
Run: `python -m pytest tests/unit/test_reset.py::test_group_children_value_clauses_are_restored -v`
Expected: FAIL (only `INITIALIZE MQ-CONSTANTS` emitted; children's VALUEs lost).

- [ ] **Step 3: Implement a recursive child-VALUE emitter.** In the group branch of `reset_move_lines`:
```python
        if _is_group(item) and not item.value_clause:
            lines.append(f"INITIALIZE {item.name}")
            lines.extend(_child_value_restores(item))
        else:
            ...
```
with:
```python
def _child_value_restores(group) -> list[str]:
    """After INITIALIZE zeroes/space-fills a group, restore any child that
    declared its own VALUE clause (INITIALIZE does not honor those)."""
    out: list[str] = []
    for child in getattr(group, "children", []):
        if getattr(child, "level", None) is None:
            continue  # clause node, not a data item
        if _is_group(child):
            out.extend(_child_value_restores(child))
        elif getattr(child, "value_clause", None):
            out.append(f"MOVE {child.value_clause} TO {child.name}")
    return out
```

- [ ] **Step 4: Run the reset suite, verify green.**
Run: `python -m pytest tests/unit/test_reset.py -v`
Expected: PASS (new test passes; existing tests unaffected — VALUE-less groups still get bare `INITIALIZE`).

- [ ] **Step 5: `Verify (integration/Docker)`** — update the DEPTMQC error-path example to `MOVE MQCC-FAILED` and confirm it now yields 2, not 0. Pending Docker.

- [ ] **Step 6: Commit.**
```bash
git add mockymock/splicer/reset.py tests/unit/test_reset.py
git commit -m "fix(reset): restore group children's VALUE clauses after INITIALIZE"
```

---

## Tier 0 — Cross-repo cobolparser fixes (unblocks mockymock's own examples)

These run in `../cobol-parser`, with that repo's own tests and CI. They are sequenced here because Task 10 un-`xfail`s mockymock's flagship real-world example.

### Task 10: Fix COMPUTE statement-boundary parsing (mirror `c68a8ff`)

**Files (in `../cobol-parser`):** the statement-boundary logic that commit `c68a8ff` fixed for MOVE/SUBTRACT/MULTIPLY/DIVIDE; extend to COMPUTE. Its own regression test.
**Then in mocky-mock:** Modify `tests/integration/test_realworld_deptmqp_example.py:33` — remove the `@pytest.mark.xfail`.

**Interfaces:**
- Consumes: cobolparser's statement-boundary parser.
- Produces: a `COMPUTE` with no explicit terminator no longer swallows the following statement; `CALL 'MQOPEN'` survives in `1200-MQ-OPEN`'s AST.

- [ ] **Step 1: In `../cobol-parser`, write the failing regression test** — a `COMPUTE X = Y` immediately followed on the next line by `CALL 'Z'` with no period between; assert both statements appear in the AST. Model it on the existing MOVE/SUBTRACT boundary test `c68a8ff` added.
- [ ] **Step 2: Run it, confirm the CALL is dropped (FAIL).**
- [ ] **Step 3: Apply the same terminator handling `c68a8ff` used for the other verbs to COMPUTE.**
- [ ] **Step 4: Run the cobolparser test suite, verify green.**
- [ ] **Step 5: Commit in `../cobol-parser`** (that repo's convention); note the task id (`task_24002e6a`).
- [ ] **Step 6: In mocky-mock, remove the DEPTMQP `xfail` mark** and `Verify (integration/Docker)`: `python -m pytest tests/integration/test_realworld_deptmqp_example.py -v` now passes (pending Docker + the updated cobolparser checkout). Commit the un-xfail separately.

### Task 11: Investigate dropped EXEC SQL statements (`task_c5e3b268`)

**Files (in `../cobol-parser`):** parser path for `EXEC SQL UPDATE`/`INSERT`. **Gated by** first isolating the trigger (ACCTMNT's `2100-PROCESS-RATE-CHANGE` UPDATE and `2230-POST-FEE-TRANSACTION` INSERT vanish; structurally similar statements parse fine).

- [ ] **Step 1: Isolate a minimal repro** — bisect ACCTMNT down to the smallest program where an EXEC SQL statement disappears from the AST with `success=True`. This is an investigation task; its deliverable is a failing test + root-cause note, not necessarily a fix in one pass.
- [ ] **Step 2: If root cause is contained, fix + regression test in `../cobol-parser`.** If it's deep, file findings and STOP — this is explicitly unscoped in the real-world examples design.
- [ ] **Step 3: Note for mockymock:** once fixed, Task 8's AST-fidelity check should catch any *recurrence* — add ACCTMNT to the Task-7 corpus and confirm it either parses fully or is refused (never silently mis-compiled).

---

## Tier 3 — Medium features (each design-gated; prioritize by Task-7 report)

Each of these gets a one-page design doc as its first step (they involve DSL grammar or codegen changes with real design choices), then TDD tasks derived from it. Do NOT expand into bite-sized code here — the design decision comes first.

### Task 12: Batch / directory mode for `run`
- **Deliverable:** `mockymock run <dir>` (or a `--suite-glob`) discovers `*.cbl`/`*.cut` pairs, runs each, and emits one aggregated JUnit XML. Sandboxes are already isolated; the single shared container should serialize fine — measure before parallelizing.
- **Design step:** pairing convention (`FOO.cbl`↔`FOO.cut`), aggregate exit code (non-zero if any suite fails), aggregate JUnit `<testsuites>` wrapper.
- **Verify:** unit for discovery/pairing + aggregation; `Verify (integration/Docker)` for end-to-end.

### Task 13: Argument capture in `VERIFY`
- **Deliverable:** assert *what* a mocked boundary received, not just call count — e.g. `VERIFY CALL "MQPUT" ARG 2 WAS "..."`. Today the only path is folklore (mock body copies args to a WS field + `EXPECT`).
- **Design step:** grammar addition; how the splicer captures the Nth `USING` argument at the dispatch site into a generated WS field; interaction with the tally mechanism.
- **Verify:** unit (parser + injector codegen) fully provable; `Verify (integration/Docker)` for real capture.

### Task 14: Richer `EXPECT` (ranges, `NOT`, multiple values)
- **Deliverable:** `EXPECT X TO BE NOT 0`, `EXPECT X TO BE BETWEEN A AND B`.
- **Design step:** grammar + the `driver.py` `_verify_condition`-style codegen for each comparator; quote-escaping already handled by `_display_text`.
- **Verify:** unit (parser + driver codegen) fully provable; `Verify (integration/Docker)` for runtime.

---

## Tier 4 — Large engine features (GATED by Task-7 report; each needs its own sub-plan)

**These are milestones, not tasks.** Each requires a dedicated design spike that becomes its own plan document before any code. Writing bite-sized TDD steps for them now would mean inventing code against undesigned behavior — a plan failure. Prioritize strictly by what the Task-7 corpus sweep shows is common; drop any category the corpus proves rare or absent (e.g. CICS is absent from the source corpus).

Each milestone's design spike must answer, at minimum: the exact cobolparser AST surface it needs (extend `.okf/integration.md`), the splicer/driver changes, the new refusal codes it removes, and 2+ real corpus programs it must run green.

### Milestone A: `STOP RUN` / `GOBACK` handling
Splice `STOP RUN`/`GOBACK` reached from a test case's PERFORM target into a controlled return (e.g. `GOBACK` → paragraph exit, or a generated flag + `GO TO` the driver's case-end), so whole-program entry points and multi-record read loops become testable and a crash stops being the only outcome. Highest-leverage: it unblocks the read-loop depth both real-world examples had to give up. Note `GOBACK` currently has zero handling anywhere in the codebase.

### Milestone B: CALL-style driving with `LINKAGE SECTION`
Let the driver `CALL` the program (allocating `LINKAGE` storage / COMMAREA / PCB masks) instead of only `PERFORM`-ing paragraphs. Unblocks the entire subprogram class and is a prerequisite for IMS DL/I (`ENTRY 'DLITCBL' USING ...`) and CICS COMMAREA programs. Verify GnuCOBOL's storage semantics for a standalone program's `LINKAGE SECTION` under `CALL` first — the real-world design flagged this as unverified.

### Milestone C: DB2 cursor support
Recognize `DECLARE <cursor> CURSOR FOR SELECT` in WORKING-STORAGE (`sqlca.py`) — the one-line-ish fix already spiked as `task_d610057b`. **Blocked behind Task 11** (the dropped-EXEC-SQL cobolparser bug) — has no example to exercise it until then. Land the `sqlca.py` change with a unit test now if cheap, but its integration example waits on Task 11.

### Milestone D: SORT / MERGE
Currently refused (`UNSUPPORTED_SORT_MERGE`). Mocking a SORT means mocking the algorithm plus its INPUT/OUTPUT PROCEDURE contract, not a boundary statement — a genuinely new mocking model. Only build if the Task-7 report shows SORT is common in the corpus (batch COBOL suggests it will be).

### Milestone E: `GO TO` in reachability
The refusal gate's BFS follows only `PerformStatement` edges (`refusal.py:_find_performs`); a boundary reached via `GO TO` isn't flagged at refusal time and fails late at runtime (WHEN OTHER trap / missing file). Add `GoToStatement` edges to `_reachable_paragraphs`. Design must handle the `GO TO ... DEPENDING ON` and the THRU-EXIT idiom interactions. Lower priority (fails loud today, just late) but removes a confusing failure mode.

### Milestone F: CICS (conditional on corpus)
No CICS example exists in the source corpus. Build only if a real target portfolio requires it; otherwise defer indefinitely. Depends on Milestone B (COMMAREA).

---

## Tier 5 — Documentation sync (after each tier lands)

**Files:** `.okf/*.md` (refresh `timestamp` on every concept touched), `.okf/log.md` (dated entry per tier), `README.md`, `interface-contract.md`.

- [ ] After Tier 1: update `.okf/dsl.md` (unterminated-MOCK / duplicate-PERFORM now error — remove the "doesn't error" Gotchas), `.okf/runtime.md` (IMAGE constant is now tagged), `.okf/report.md` (unknown-case-id gap closed), `.okf/cli.md` (`--keep-sandbox`/`--verbose`).
- [ ] After Tier 2: new `.okf/fidelity.md` concept for the AST-fidelity check, linked from `index.md`; update `.okf/splicer.md` reset section (VALUE-restoring is no longer a "known v1 fidelity limit").
- [ ] After each tier: `okf:validate .okf --strict` must pass before committing bundle changes (per workspace CLAUDE.md).
- [ ] Run `/okf:validate .okf --strict` and resolve every error.

---

## Self-Review (performed against the audit)

**Spec coverage vs. the audit's six priority items:**
1. AST-fidelity cross-check → Task 8 (gated by Task 7). ✓
2. Get DEPTMQP green (COMPUTE fix) → Task 10. ✓
3. Corpus sweep → Task 7. ✓ (promoted to a gate, per advisor)
4. DECLARE CURSOR + reset fidelity → Milestone C + Task 9. ✓ (reset changed to the real fix, per advisor)
5. STOP RUN/GOBACK + CALL-driving → Milestones A + B. ✓
6. Packaging (LICENSE, pin, PyPI) → Task 1 + Global Constraints (pin as documented floor, not hard constraint). ✓

**Audit §3/§5 items also covered:** argument capture → Task 13; EXPECT ranges → Task 14; reset corruption → Task 9; DSL robustness → Tasks 2–3; batch mode → Task 12; `--keep-sandbox` → Task 4; unknown-case-id → Task 6; image staleness → Task 5; GO TO → Milestone E; SORT/MERGE → Milestone D; CICS → Milestone F.

**Deliberately deferred (with reason):** EBCDIC/dialect fidelity (§4) — inherent to the GnuCOBOL-not-mainframe choice; documented as a caveat rather than fixed (belongs in README, folded into Tier-5 docs). Concurrency of the shared container (§5) — measure in Task 12 before acting.

**Placeholder scan:** Tier 1–2 tasks and Task 9 carry complete code. Tier 3–4 are intentionally milestone-level with a mandatory design-doc first step — this is a deliberate structural choice (writing fabricated TDD code for undesigned engine features would violate the no-placeholders rule), not an omission.

**Verification honesty:** every Docker-dependent step is tagged `Verify (integration/Docker)` and flagged "pending Docker" because the authoring session has no Docker daemon.
