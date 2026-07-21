# Execution-Trace Debug Support (CLI) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `--trace` / `--trace-json PATH` to `mockymock run`, producing the executed path through the user's original `.cbl` plus an ordered mock-firing timeline for a single test case.

**Architecture:** Two independent channels. The executed path comes from GnuCOBOL's runtime trace file (`-ftraceall` + `COB_SET_TRACE`), remapped onto original `.cbl` lines by reusing coverage.py's difflib alignment. The mock timeline comes from a new trace-mode-only `__MOCKYMOCK__ MOCK:` DISPLAY in the spliced dispatch blocks, parsed off stdout. See `docs/2026-07-21-debug-trace-design.md`.

**Tech Stack:** Python 3.11+, pytest, GnuCOBOL 3.2.0 in the `mockymock-cobc` Docker container.

## Global Constraints

- **Trace is runtime-gated.** `-ftraceall` alone emits nothing; `COB_SET_TRACE=yes` is required at run time. Verified in-container.
- **`COB_TRACE_FILE` must always be set explicitly**, to a path inside the bind-mounted sandbox (`/work/...`). Unset, trace can leak to stderr; outside the sandbox, the host cannot read it back.
- **`COB_TRACE_FORMAT` is `%P|%S|%L`.** Fields remain space-padded — always `.strip()` each split field.
- **A normal `run` (no `--trace`) must stay byte-identical** in spliced source and stdout. This is the entire justification for gating the new DISPLAY on trace mode.
- **`--trace-json` implies `--trace`**, mirroring `args.coverage_json` setting `args.coverage` in `cli/main.py`.
- **`--trace` requires exactly one `--case` and no `--tag`.** Checked from args alone, before `ensure_toolchain()`.
- Run unit tests with `python -m pytest tests/unit -q`. Docker-gated integration tests live under `tests/integration/` and use the existing skip gate in `tests/integration/_docker.py`.

---

### Task 1: Extract a reusable instrumented→original line map

`map_coverage_to_original` already computes exactly the mapping the trace needs, but buries it in a closure over a `CoverageReport`. Extract it so the trace path reuses it instead of duplicating difflib logic.

**Files:**
- Modify: `mockymock/report/coverage.py:140-191`
- Test: `tests/unit/test_coverage.py`

**Interfaces:**
- Produces: `build_original_line_map(instrumented_lines: list[str], normalized_lines: list[str], original_lines: list[str]) -> dict[int, int]` — 1-based instrumented line → 1-based original line. Lines with no mapping (splicer insertions, continuation merges) are absent from the dict.

- [ ] **Step 1: Write the failing test**

```python
def test_build_original_line_map_skips_inserted_lines():
    original = [
        "      *comment",
        "       MOVE 1 TO WS-A",
        "       ADD 1 TO WS-A",
    ]
    normalized = ["MOVE 1 TO WS-A", "ADD 1 TO WS-A"]
    instrumented = ["MOVE 1 TO WS-A", "ADD 1 TO UT-TALLY-1", "ADD 1 TO WS-A"]

    mapping = build_original_line_map(instrumented, normalized, original)

    assert mapping[1] == 2      # instrumented line 1 -> original line 2
    assert mapping[3] == 3      # instrumented line 3 -> original line 3
    assert 2 not in mapping     # the spliced-in tally line maps nowhere
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_coverage.py::test_build_original_line_map_skips_inserted_lines -q`
Expected: FAIL — `ImportError` / `NameError: build_original_line_map`.

- [ ] **Step 3: Extract the function and rewrite the caller in terms of it**

Add to `mockymock/report/coverage.py`, above `map_coverage_to_original`:

```python
def build_original_line_map(
    instrumented_lines: list[str],
    normalized_lines: list[str],
    original_lines: list[str],
) -> dict[int, int]:
    """1-based instrumented line -> 1-based ORIGINAL .cbl line.

    Composes the same two alignments `map_coverage_to_original` uses:
    instrumented -> normalized (the splicer inserts lines but keeps
    untouched source verbatim and in order), then normalized -> original
    (fixed-format extraction drops comments/sequence columns). Instrumented
    lines with no original counterpart -- the splicer's own dispatch and
    driver code -- are simply absent from the result.
    """
    normalized_stripped = [line.rstrip() for line in normalized_lines]
    instrumented_stripped = [line.rstrip() for line in instrumented_lines]
    inst_to_norm = _matching_index_map(normalized_stripped, instrumented_stripped)

    extracted = _extract_fixed_format(original_lines)
    norm_to_orig = _matching_index_map(
        [content for _, content in extracted], normalized_stripped
    )

    mapping: dict[int, int] = {}
    for inst_index, norm_index in inst_to_norm.items():
        extracted_index = norm_to_orig.get(norm_index)
        if extracted_index is not None:
            mapping[inst_index + 1] = extracted[extracted_index][0]
    return mapping
```

Then replace the body of `map_coverage_to_original` between its docstring and the `mapped: dict[int, bool] = {}` line with:

```python
    line_map = build_original_line_map(
        instrumented_lines, normalized_lines, original_lines
    )

    def to_original(instrumented_line: int) -> int | None:
        return line_map.get(instrumented_line)
```

- [ ] **Step 4: Run the full coverage suite to prove the refactor is behavior-preserving**

Run: `python -m pytest tests/unit/test_coverage.py -q`
Expected: PASS — the new test plus every pre-existing coverage test.

- [ ] **Step 5: Commit**

```bash
git add mockymock/report/coverage.py tests/unit/test_coverage.py
git commit -m "refactor(coverage): extract build_original_line_map for reuse by trace"
```

---

### Task 2: Compile with `-ftraceall`

**Files:**
- Modify: `mockymock/runtime/docker_toolchain.py:247-278`
- Test: `tests/unit/test_docker_toolchain.py`

**Interfaces:**
- Produces: `compile_source(source_path: Path, coverage: bool = False, trace: bool = False) -> CompileResult`

- [ ] **Step 1: Write the failing test**

```python
def test_compile_source_adds_traceall_flag(monkeypatch, tmp_path):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(docker_toolchain.subprocess, "run", fake_run)
    source = tmp_path / "PROG.cbl"
    source.write_text("")
    (tmp_path / "PROG").write_text("")  # stand in for the produced binary

    docker_toolchain.compile_source(source, trace=True)

    assert "-ftraceall" in captured["cmd"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_docker_toolchain.py::test_compile_source_adds_traceall_flag -q`
Expected: FAIL — `TypeError: compile_source() got an unexpected keyword argument 'trace'`.

- [ ] **Step 3: Add the parameter**

Change the signature at `mockymock/runtime/docker_toolchain.py:247` to:

```python
def compile_source(
    source_path: Path, coverage: bool = False, trace: bool = False
) -> CompileResult:
```

and immediately after the existing `if coverage: cmd.append("--coverage")` block add:

```python
    if trace:
        # -ftraceall only *generates* the trace hooks; COB_SET_TRACE at run
        # time is what actually emits anything (see run_binary).
        cmd.append("-ftraceall")
```

Append to the docstring:

```
    `trace=True` adds `-ftraceall`, which generates statement-level trace
    hooks. It emits nothing on its own -- `run_binary(trace_path=...)`
    supplies the runtime environment that turns tracing on.
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/unit/test_docker_toolchain.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add mockymock/runtime/docker_toolchain.py tests/unit/test_docker_toolchain.py
git commit -m "feat(runtime): compile with -ftraceall when trace requested"
```

---

### Task 3: Enable tracing at run time

**Files:**
- Modify: `mockymock/runtime/docker_toolchain.py:313-368`
- Test: `tests/unit/test_docker_toolchain.py`

**Interfaces:**
- Produces: `run_binary(binary_path: Path, timeout_seconds: int = 30, trace_path: Path | None = None) -> ExecutionResult`. `trace_path` must live under `WORK_ROOT`; it is translated with `to_container_path` and passed as `COB_TRACE_FILE`.

- [ ] **Step 1: Write the failing test**

```python
def test_run_binary_sets_trace_env(monkeypatch, tmp_path):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(docker_toolchain.subprocess, "run", fake_run)
    monkeypatch.setattr(docker_toolchain, "WORK_ROOT", tmp_path)

    docker_toolchain.run_binary(tmp_path / "sbx" / "PROG", trace_path=tmp_path / "sbx" / "PROG.trace")

    cmd = captured["cmd"]
    assert "COB_SET_TRACE=yes" in cmd
    assert "COB_TRACE_FORMAT=%P|%S|%L" in cmd
    assert any(a.startswith("COB_TRACE_FILE=/work/") for a in cmd)


def test_run_binary_without_trace_sets_no_env(monkeypatch, tmp_path):
    captured = {}
    monkeypatch.setattr(
        docker_toolchain.subprocess,
        "run",
        lambda cmd, **kw: captured.setdefault("cmd", cmd)
        or subprocess.CompletedProcess(cmd, 0, "", ""),
    )
    monkeypatch.setattr(docker_toolchain, "WORK_ROOT", tmp_path)

    docker_toolchain.run_binary(tmp_path / "sbx" / "PROG")

    assert not any("COB_SET_TRACE" in a for a in captured["cmd"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/test_docker_toolchain.py -k trace_env -q`
Expected: FAIL — `TypeError: run_binary() got an unexpected keyword argument 'trace_path'`.

- [ ] **Step 3: Add env plumbing**

Change the signature at `mockymock/runtime/docker_toolchain.py:313` to:

```python
def run_binary(
    binary_path: Path,
    timeout_seconds: int = 30,
    trace_path: Path | None = None,
) -> ExecutionResult:
```

Replace the hard-coded argument list inside the `subprocess.run([...])` call with a built list. Immediately after `container_dir = container_binary.rsplit("/", 1)[0]` insert:

```python
    trace_env: list[str] = []
    if trace_path is not None:
        # COB_TRACE_FILE must point inside the bind-mounted sandbox or the
        # host can never read the trace back; left unset entirely, GnuCOBOL
        # can spill trace onto stderr and pollute the run's diagnostics.
        trace_env = [
            "-e",
            "COB_SET_TRACE=yes",
            "-e",
            f"COB_TRACE_FILE={to_container_path(trace_path, WORK_ROOT)}",
            "-e",
            "COB_TRACE_FORMAT=%P|%S|%L",
        ]
    command = [
        "docker",
        "exec",
        "-w",
        container_dir,
        *trace_env,
        CONTAINER,
        "timeout",
        "-k",
        "5",
        str(timeout_seconds),
        container_binary,
    ]
```

then pass `command` as the first argument to `subprocess.run`.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/unit/test_docker_toolchain.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add mockymock/runtime/docker_toolchain.py tests/unit/test_docker_toolchain.py
git commit -m "feat(runtime): enable COB_SET_TRACE and route trace into the sandbox"
```

---

### Task 4: Emit the mock-firing marker in trace mode

**Files:**
- Modify: `mockymock/splicer/injector.py:44-99`, `mockymock/splicer/orchestrator.py:55-81`
- Test: `tests/unit/test_injector.py`

**Interfaces:**
- Produces: `build_site_dispatch(site, suite, registry, file_status_fields=None, trace: bool = False)` and `splice_program(..., file_status_fields=None, trace: bool = False)`.
- The emitted line is exactly `DISPLAY "__MOCKYMOCK__ MOCK: <site.label>"`, placed immediately after that branch's `ADD 1 TO <tally>`.

- [ ] **Step 1: Write the failing tests**

```python
def test_site_dispatch_emits_mock_marker_in_trace_mode(sample_site, sample_suite, registry):
    lines = build_site_dispatch(sample_site, sample_suite, registry, trace=True)
    assert any('__MOCKYMOCK__ MOCK: ' + sample_site.label in line for line in lines)


def test_site_dispatch_is_unchanged_without_trace(sample_site, sample_suite, registry):
    lines = build_site_dispatch(sample_site, sample_suite, registry)
    assert not any("__MOCKYMOCK__ MOCK:" in line for line in lines)
```

Build `sample_site` / `sample_suite` / `registry` with the same fixtures the existing tests in this file already use for `build_site_dispatch`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/test_injector.py -k mock_marker -q`
Expected: FAIL — `TypeError: build_site_dispatch() got an unexpected keyword argument 'trace'`.

- [ ] **Step 3: Implement**

In `mockymock/splicer/injector.py`, add `trace: bool = False` as the last parameter of `build_site_dispatch`. Directly after the existing line:

```python
        lines.append(f"                   ADD 1 TO {tally_name}")
```

insert:

```python
        if trace:
            # Mock firing order cannot come from the GnuCOBOL trace file:
            # these dispatch blocks are splicer-inserted, and the trace's
            # line remap drops inserted lines by design. Emitting on the
            # __MOCKYMOCK__ stdout channel instead puts each firing between
            # the driver's CASE START/END markers, so attribution is free.
            lines.append(
                f'                   DISPLAY "__MOCKYMOCK__ MOCK: {site.label}"'
            )
```

In `mockymock/splicer/orchestrator.py`, add `trace: bool = False` as the last parameter of `splice_program`, and change line 81 to:

```python
            replacement = build_site_dispatch(
                site, suite, registry, file_status_fields, trace=trace
            )
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/unit/test_injector.py tests/unit/test_splicer.py -q`
Expected: PASS, including every existing splicer test — the no-trace path must be untouched.

- [ ] **Step 5: Commit**

```bash
git add mockymock/splicer/injector.py mockymock/splicer/orchestrator.py tests/unit/test_injector.py
git commit -m "feat(splicer): emit __MOCKYMOCK__ MOCK markers in trace mode"
```

---

### Task 5: Parse the mock marker off stdout

**Files:**
- Modify: `mockymock/report/results.py:8-75`
- Test: `tests/unit/test_results.py`

**Interfaces:**
- Produces: `TestResult.mock_hits: list[str]` — mock labels in firing order for that case.

- [ ] **Step 1: Write the failing test**

```python
def test_parse_stdout_records_mock_hits_in_order():
    stdout = "\n".join([
        "__MOCKYMOCK__ TESTSUITE: S",
        "__MOCKYMOCK__ CASE 001 START: posts a credit",
        "__MOCKYMOCK__ MOCK: CALL 'CUSTLOOK'",
        "__MOCKYMOCK__ MOCK: READ ACCT-FILE",
        "__MOCKYMOCK__ CASE 001 END",
        "__MOCKYMOCK__ SUMMARY: RUN=1 FAILURES=0",
    ])

    suite = parse_stdout(stdout)

    assert suite.results[0].mock_hits == ["CALL 'CUSTLOOK'", "READ ACCT-FILE"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_results.py::test_parse_stdout_records_mock_hits_in_order -q`
Expected: FAIL — `AttributeError: 'TestResult' object has no attribute 'mock_hits'`.

- [ ] **Step 3: Implement**

Add the regex beside the others at the top of `mockymock/report/results.py`:

```python
_MOCK_RE = re.compile(r"^__MOCKYMOCK__ MOCK: (?P<label>.+)$")
```

Add the field to `TestResult`, after `failure_reasons`:

```python
    mock_hits: list[str] = field(default_factory=list)
```

Add a branch in `parse_stdout`'s loop, after the `_CASE_FAIL_RE` branch. A MOCK line always follows its case's START, so attribute it to the most recently started case:

```python
        elif (m := _MOCK_RE.match(line)) is not None:
            if suite.results:
                suite.results[-1].mock_hits.append(m.group("label"))
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/unit/test_results.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add mockymock/report/results.py tests/unit/test_results.py
git commit -m "feat(report): parse __MOCKYMOCK__ MOCK markers into TestResult.mock_hits"
```

---

### Task 6: Trace file parser and JSON contract

**Files:**
- Create: `mockymock/report/trace.py`
- Test: `tests/unit/test_trace.py` (create)

**Interfaces:**
- Consumes: `build_original_line_map` (Task 1), `TestResult.mock_hits` (Task 5).
- Produces:
  - `TRACE_JSON_VERSION = 1`
  - `TraceEntry` dataclass: `line: int`, `statement: str | None`, `paragraph: str | None`
  - `parse_trace(trace_text: str) -> list[TraceEntry]` — instrumented line numbers, in execution order
  - `TRACE_ENTRY_CAP = 50_000`
  - `format_trace_json(entries, line_map, mock_hits, case_name, case_line, cut_file, program_file) -> str`

- [ ] **Step 1: Write the failing tests**

```python
TRACE_SAMPLE = "\n".join([
    "Source: 'SPIKE.cbl'",
    "Program-Id:  SPIKE",
    "Program-Id:  SPIKE           |    Entry: SPIKE          |     8",
    "Program-Id:  SPIKE           |Paragraph: MAIN-PARA      |     8",
    "Program-Id:  SPIKE           |           MOVE           |     9",
    "Program-Id:  SPIKE           |           PERFORM        |    10",
])


def test_parse_trace_skips_headers_and_strips_padding():
    entries = parse_trace(TRACE_SAMPLE)
    assert [e.line for e in entries] == [8, 8, 9, 10]
    assert entries[1].paragraph == "MAIN-PARA"
    assert entries[2].statement == "MOVE"
    assert entries[2].paragraph is None


def test_format_trace_json_drops_unmapped_lines_and_orders_mocks():
    entries = [TraceEntry(line=9, statement="MOVE", paragraph=None),
               TraceEntry(line=10, statement="ADD", paragraph=None)]
    payload = json.loads(format_trace_json(
        entries, {9: 42}, ["CALL 'X'"], "posts a credit", 12, "t.cut", "P.cbl"))

    assert payload["version"] == 1
    assert payload["case"] == {"name": "posts a credit", "line": 12}
    assert payload["path"] == [{"line": 42, "statement": "MOVE"}]
    assert payload["mocks"] == [{"order": 1, "label": "CALL 'X'"}]
    assert payload["truncated"] is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/test_trace.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'mockymock.report.trace'`.

- [ ] **Step 3: Implement**

Create `mockymock/report/trace.py`:

```python
"""Parses GnuCOBOL's COB_TRACE_FILE output into an executed-path report.

The trace is emitted with COB_TRACE_FORMAT='%P|%S|%L'. Fields stay
space-padded, so every split field is stripped. Two header lines
(`Source: '...'` and a bare `Program-Id:`) precede the entries. Line
numbers are INSTRUMENTED-source lines and must be remapped through
`report.coverage.build_original_line_map` before they mean anything to
the user.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

TRACE_JSON_VERSION = 1

# A PERFORM UNTIL with many iterations can emit an unbounded trace. Cap it
# and say so, rather than streaming or sampling.
TRACE_ENTRY_CAP = 50_000


@dataclass
class TraceEntry:
    """One traced statement, at an INSTRUMENTED-source line number."""

    line: int
    statement: str | None
    paragraph: str | None


def parse_trace(trace_text: str) -> list[TraceEntry]:
    entries: list[TraceEntry] = []
    for raw in trace_text.splitlines():
        parts = raw.split("|")
        if len(parts) != 3:
            continue  # header lines carry no delimiters
        _program, what, line_text = (part.strip() for part in parts)
        try:
            line = int(line_text)
        except ValueError:
            continue
        if what.startswith("Paragraph:"):
            entries.append(
                TraceEntry(
                    line=line,
                    statement=None,
                    paragraph=what[len("Paragraph:"):].strip(),
                )
            )
        elif what.startswith("Entry:"):
            continue  # program entry, not a user statement
        else:
            entries.append(TraceEntry(line=line, statement=what, paragraph=None))
    return entries


def format_trace_json(
    entries: list[TraceEntry],
    line_map: dict[int, int],
    mock_hits: list[str],
    case_name: str,
    case_line: int | None,
    cut_file: str,
    program_file: str,
) -> str:
    path: list[dict[str, object]] = []
    truncated = False
    for entry in entries:
        original = line_map.get(entry.line)
        if original is None:
            continue  # splicer-inserted line: not the user's code
        if len(path) >= TRACE_ENTRY_CAP:
            truncated = True
            break
        if entry.paragraph is not None:
            path.append({"line": original, "paragraph": entry.paragraph})
        else:
            path.append({"line": original, "statement": entry.statement})

    payload = {
        "version": TRACE_JSON_VERSION,
        "cutFile": cut_file,
        "programFile": program_file,
        "case": {"name": case_name, "line": case_line},
        "path": path,
        "mocks": [
            {"order": index, "label": label}
            for index, label in enumerate(mock_hits, start=1)
        ],
        "truncated": truncated,
    }
    return json.dumps(payload, indent=2) + "\n"
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/unit/test_trace.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add mockymock/report/trace.py tests/unit/test_trace.py
git commit -m "feat(report): add trace parser and trace-JSON contract"
```

---

### Task 7: Wire `--trace` / `--trace-json` into the CLI

**Files:**
- Modify: `mockymock/cli/main.py` (arg definitions near :590, `_cmd_run` at :200 and :313-404)
- Test: `tests/unit/test_cli.py`

**Interfaces:**
- Consumes: everything from Tasks 1-6.

- [ ] **Step 1: Write the failing tests**

```python
def test_trace_requires_exactly_one_case(capsys):
    code = main(["run", "P.cbl", "--cut", "t.cut", "--trace"])
    assert code == 1
    assert "exactly one --case" in capsys.readouterr().out


def test_trace_rejects_tag_selection(capsys):
    code = main(["run", "P.cbl", "--cut", "t.cut", "--trace",
                 "--case", "a", "--tag", "smoke"])
    assert code == 1
    assert "exactly one --case" in capsys.readouterr().out


def test_trace_json_implies_trace():
    parser_args = build_parser().parse_args(
        ["run", "P.cbl", "--cut", "t.cut", "--case", "a", "--trace-json", "o.json"]
    )
    assert _normalize_trace_args(parser_args) is True
```

If `main`/`build_parser` are named differently in this file, match the existing tests' import style rather than inventing names.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/test_cli.py -k trace -q`
Expected: FAIL — `unrecognized arguments: --trace`.

- [ ] **Step 3: Implement**

Add after the `--coverage-json` argument (`mockymock/cli/main.py:596`):

```python
    run_parser.add_argument(
        "--trace",
        action="store_true",
        help=(
            "Trace the executed path through the program for a single test "
            "case and print it after the run. Requires exactly one --case"
        ),
    )
    run_parser.add_argument(
        "--trace-json",
        help=(
            "Write the machine-readable execution trace (executed path "
            "remapped onto the ORIGINAL .cbl's lines, plus the ordered mock "
            "timeline) to this file. Implies --trace"
        ),
    )
```

At the top of `_cmd_run`, before `ensure_toolchain()` is reached, add:

```python
    # Asking for the trace JSON is asking for the trace.
    if args.trace_json:
        args.trace = True
    if args.trace:
        # The suite compiles and runs as ONE binary, and the trace file
        # shares no timestamps with stdout -- so an unscoped trace
        # interleaves every case with no way to segment it. Requiring a
        # single case makes attribution true by construction.
        if len(args.case or []) != 1 or args.tag:
            print(
                "mockymock run: --trace requires exactly one --case "
                "(and no --tag): the suite runs as a single binary, so an "
                "unscoped trace cannot be attributed to one case"
            )
            return 1
```

Inside the `with sandbox_dir_maybe_kept(...)` block, change the compile call to pass trace, and capture the trace text before the sandbox is cleaned up. Replace lines 322-333 with:

```python
        compiled = docker_toolchain.compile_source(
            instrumented_path, coverage=args.coverage, trace=args.trace
        )
        if not compiled.success:
            print("mockymock run: compile failed:")
            print(compiled.stderr)
            if args.verbose or args.keep_sandbox:
                print(f"mockymock run: instrumented source at {instrumented_path}")
            return 1

        assert compiled.binary_path is not None  # implied by compiled.success
        trace_path = tmp / f"{instrumented_path.stem}.trace" if args.trace else None
        executed = docker_toolchain.run_binary(
            compiled.binary_path, trace_path=trace_path
        )

        # Must be read before the sandbox context manager removes it.
        trace_text = ""
        if trace_path is not None and trace_path.exists():
            trace_text = trace_path.read_text(errors="replace")
```

Then, alongside the other artifact writers near line 388, add:

```python
    if args.trace:
        if not trace_text:
            print(
                "mockymock run: no trace produced -- the binary wrote no "
                "trace file (it may have died before executing any statement)"
            )
        else:
            selected = args.case[0]
            case_result = next(
                (r for r in suite_result.results if r.case_name == selected), None
            )
            model_case = next(
                (c for c in suite.test_cases if c.name == selected), None
            )
            entries = parse_trace(trace_text)
            line_map = build_original_line_map(
                instrumented, normalized_lines, source_path.read_text().splitlines()
            )
            trace_json = format_trace_json(
                entries,
                line_map,
                case_result.mock_hits if case_result else [],
                selected,
                model_case.line if model_case else None,
                str(cut_path),
                str(source_path),
            )
            if args.trace_json:
                Path(args.trace_json).write_text(trace_json)
            print(format_trace_console(json.loads(trace_json)))
```

Add the deferred imports at the top of `_cmd_run`'s body, beside the existing `from mockymock.report.coverage import ...`:

```python
    import json

    from mockymock.report.coverage import build_original_line_map
    from mockymock.report.trace import (
        format_trace_console,
        format_trace_json,
        parse_trace,
    )
```

Add `format_trace_console` to `mockymock/report/trace.py`:

```python
def format_trace_console(payload: dict) -> str:
    """Human-readable rendering of the trace-JSON contract."""
    lines = [f"Execution trace for case: {payload['case']['name']}"]
    if payload["mocks"]:
        lines.append("  mocks fired, in order:")
        lines.extend(
            f"    {entry['order']}. {entry['label']}" for entry in payload["mocks"]
        )
    else:
        lines.append("  mocks fired: none")
    lines.append(f"  statements executed: {len(payload['path'])}")
    if payload["truncated"]:
        lines.append(f"  (truncated at {TRACE_ENTRY_CAP} entries)")
    for entry in payload["path"]:
        what = entry.get("paragraph") or entry.get("statement")
        marker = "paragraph" if "paragraph" in entry else "         "
        lines.append(f"    line {entry['line']:>6}  {marker}  {what}")
    return "\n".join(lines)
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/unit -q`
Expected: PASS — the whole unit suite, confirming no regression in the non-trace path.

- [ ] **Step 5: Commit**

```bash
git add mockymock/cli/main.py mockymock/report/trace.py tests/unit/test_cli.py
git commit -m "feat(cli): add --trace and --trace-json to run"
```

---

### Task 8: End-to-end integration test and documentation

**Files:**
- Create: `tests/integration/test_trace.py`
- Modify: `.okf/cli.md`, `.okf/report.md`, `.okf/log.md`, `README.md`

**Interfaces:**
- Consumes: the full CLI surface from Task 7.

- [ ] **Step 1: Write the failing integration test**

```python
import json

from tests.integration._docker import requires_docker


@requires_docker
def test_trace_reports_executed_path_and_mocks(tmp_path, run_cli, fixture):
    """A real GnuCOBOL run must produce a path over the ORIGINAL .cbl's
    lines plus the mock timeline in firing order."""
    out = tmp_path / "trace.json"
    code = run_cli([
        "run", str(fixture("acctprg.cbl")),
        "--cut", str(fixture("acctprg.cut")),
        "--case", "posts a credit",
        "--trace-json", str(out),
    ])

    assert code == 0
    payload = json.loads(out.read_text())
    assert payload["version"] == 1
    assert payload["case"]["name"] == "posts a credit"
    assert payload["path"], "expected a non-empty executed path"
    original_line_count = len(fixture("acctprg.cbl").read_text().splitlines())
    assert all(1 <= e["line"] <= original_line_count for e in payload["path"])
    assert [m["order"] for m in payload["mocks"]] == list(
        range(1, len(payload["mocks"]) + 1)
    )
```

Match `run_cli` / `fixture` to the helpers the neighbouring integration tests already use (see `tests/integration/test_realworld_acctprg_example.py`); do not invent new fixtures.

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/integration/test_trace.py -q`
Expected: FAIL (or skip if Docker is unavailable — then start the container and re-run; this test is the only real proof the design works).

- [ ] **Step 3: Fix whatever it surfaces**

The unit tests mock Docker, so this is the first genuine exercise of the compile flag, the env plumbing, and the line remap together. Expect the remap to need the most scrutiny: verify `path` line numbers land on real statements in the original `.cbl`.

- [ ] **Step 4: Run the full suite**

Run: `python -m pytest tests/unit tests/integration -q`
Expected: PASS.

- [ ] **Step 5: Update documentation**

- `.okf/cli.md`: add `--trace` / `--trace-json` to the `run` flag list and the flow description; refresh `timestamp`.
- `.okf/report.md`: document the `MOCK` protocol line and the trace-JSON contract; refresh `timestamp`.
- `.okf/log.md`: prepend a dated entry (newest-first ordering is enforced).
- `README.md`: document both flags in the DSL/CLI reference.

- [ ] **Step 6: Validate the OKF bundle**

Run: `/okf:validate .okf --strict`
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add tests/integration/test_trace.py .okf README.md
git commit -m "test: prove execution trace end-to-end; document --trace"
```

---

## Self-Review

**Spec coverage:** Two channels → Tasks 1/6 (path) and 4/5 (mocks). CLI surface + `--trace-json` implies `--trace` → Task 7. Single-case refusal → Task 7. Trace file in sandbox → Task 3. JSON contract → Task 6. Extension work is deliberately out of scope (separate plan, separate repo). Error-handling table: single-case refusal (Task 7), missing/empty trace file (Task 7), unmappable lines (Task 6), crash mid-case (covered — trace is read whenever the file exists, regardless of exit code). Byte-identical no-trace regression → Tasks 4 and 7 step 4. Limitations: entry cap → Task 6.

**Type consistency:** `build_original_line_map` returns `dict[int, int]`, consumed as `line_map` in Task 6 and Task 7. `TestResult.mock_hits` is `list[str]`, consumed by `format_trace_json(mock_hits=...)`. `parse_trace` returns `list[TraceEntry]`, consumed by `format_trace_json(entries=...)`. `trace_path` is `Path | None` in both `run_binary` and `_cmd_run`.

**Known soft spot:** Task 7's test names (`main`, `build_parser`, `_normalize_trace_args`) and Task 8's helpers (`run_cli`, `fixture`) are written against assumed local conventions; both steps say explicitly to match the neighbouring tests' actual style instead of inventing names.
