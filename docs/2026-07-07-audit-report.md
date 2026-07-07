# mockymock audit — 2026-07-07

Full-repo audit covering the DSL (`mockymock/dsl/`), report layer
(`mockymock/report/`), splicer (`mockymock/splicer/`), runtime + CLI
(`mockymock/runtime/`, `mockymock/cli/`), analysis/refusal layer
(`mockymock/analysis/`), tests, packaging, CI, and the OKF docs. Every
finding below was verified against the code (several empirically, by
running the parser/splicer paths against crafted inputs); suspected
issues that did not survive verification are listed at the end.

State of the suite at audit time: `python -m pytest tests/unit -q` —
**277 passed** (integration tests require Docker and auto-skip without it,
as documented).

Severity legend: **HIGH** = breaks a core guarantee or corrupts results
silently; **MEDIUM** = wrong/blocked behavior or misleading failure, but
loud or narrow; **LOW** = polish, latent traps, docs.

---

## 1. The headline theme: the fail-closed gate has fail-open holes

The safety story of mockymock is *"anything we can't handle is refused"*
(`refusal.py`), and the splicer relies on it: unmocked non-EXEC boundary
sites are left as **real, live COBOL** on the assumption that the gate
proved them unreachable (`orchestrator.py:66-73`). That assumption —
*reachable ⊇ executed* — is broken by three constructs that parse cleanly
and warning-free, i.e. exactly the inputs the `PARSE_WARNING` net cannot
catch:

| # | Finding | Where | Severity |
|---|---------|-------|----------|
| 1.1 | **GO TO edges are never traversed** by the reachability BFS — `_find_performs` collects only `PerformStatement`; `GoStatement` is ignored. Verified: `MAIN-PARA. GO TO HIDDEN-PARA.` with `CALL "REALPGM"` in `HIDDEN-PARA` produces zero refusals and the CALL stays live. An unmocked READ/WRITE there does real file I/O; an unmocked ACCEPT hangs on stdin. `GO TO EXIT-PARA` is idiomatic COBOL. | `analysis/refusal.py:410-423` | **HIGH** |
| 1.2 | **`PERFORM <section-name>` is silently dropped** mid-BFS — unresolvable targets are `continue`d without refusal, and the name table holds paragraphs only. Verified: `PERFORM WORK-SECTION` whose section body contains `CALL "SUBPGM"` → no refusal, no mock required, real CALL executes. (`mock_surface` *does* see the site; the gate just never checks it.) | `analysis/refusal.py:527` | **HIGH** |
| 1.3 | **Boundary statements inside `SEARCH ... WHEN` bodies are invisible** — `_nested_statement_lists` special-cases `EvaluateStatement` but never opens `SearchStatement.when_clauses` (a `list[dict]` with a `"statements"` key). Verified: `SEARCH ... WHEN ... CALL "HIDDENPGM"` yields `boundary_sites == []` — no site, no refusal, no splice. | `analysis/mock_surface.py:254-259` | **HIGH** |
| 1.4 | **DECLARATIVES / USE procedures are unmodeled** — an error-procedure paragraph's CALL is detected as a site but unreachable to the BFS, so never gate-checked. Latent while I/O is mocked, but combined with 1.1 it can fire for real. A fail-closed gate should refuse DECLARATIVES outright. | `analysis/refusal.py` (absent) | MEDIUM |
| 1.5 | **ALTER is not refused** — currently subsumed by 1.1, but becomes its own hole the day GO TO edges are added. Should be an unconditional whole-program refusal like SORT/MERGE. | `analysis/refusal.py` (absent) | MEDIUM |
| 1.6 | `CANCEL` is not classified as a boundary; a mocked `CALL "X"` is spliced but `CANCEL "X"` stays live (a no-op under GnuCOBOL for never-loaded modules, so low impact). | `analysis/mock_surface.py` | LOW |
| 1.7 | Docs overstate the guarantee: `README.md:83-99`, `.okf/analysis.md`, and `orchestrator.py:66-68` ("the refusal gate guarantees it is unreachable") all read as if reachability is complete. Until 1.1–1.3 are fixed, that claim is false. | docs | MEDIUM |

## 2. Splicer correctness

| # | Finding | Where | Severity |
|---|---------|-------|----------|
| 2.1 | **Top-level splices have no "owns its line" guard — sibling code on the same line is silently deleted.** Nested sites get the `does not start its own line` refusal, but top-level sites don't. Verified: `MOVE 1 TO WS-A CALL "X" USING WS-A.` on one line → the whole line is commented out, the MOVE vanishes, the program compiles, and the test "passes" against corrupted behavior. Same class: a one-line paragraph `P1. CALL "X".` loses its paragraph header; two mocked statements on one line are replaced in reverse order. | `splicer/source_map.py:64-69`, `orchestrator.py:86`, `stub_writer.py:14-17` | **HIGH** |
| 2.2 | **`collect_boundaries` omits SECTION header lines**, so a splice span for a paragraph's last statement can extend over and comment out the next `SECTION.` header. Verified: span `(6, 7)` swallowing `NEXT-SEC SECTION.`. If the previous section is PERFORMed as a section, its extent then silently includes the following paragraphs. No splicer test uses SECTIONs at all. | `splicer/source_map.py:40-61` | **HIGH** |
| 2.3 | **Reset emits illegal MOVEs for PICTURE-less items** (POINTER/INDEX/COMP-1/COMP-2): `_is_numeric` is False without a picture, so `MOVE SPACES TO WS-PTR` is generated and cobc rejects it. Loud, but blocks otherwise-valid programs. | `splicer/reset.py:103-113` | MEDIUM |
| 2.4 | **`_child_value_restores` emits unsubscripted MOVEs to OCCURS children** — `05 WS-CELL PIC 9 OCCURS 5 TIMES VALUE 7` → `MOVE 7 TO WS-CELL`, rejected by cobc. Any group with an OCCURS-with-VALUE child fails to compile. Also, numeric-edited PICs without `9`-context handling (`PIC ZZZ`) get `MOVE SPACES`. | `splicer/reset.py:87-100` | MEDIUM |
| 2.5 | **Tally and fail-count fields are `PIC 9(4)` and wrap silently at 10,000** — `VERIFY ... 500 TIMES` passes with 10,500 actual calls; `NEVER` passes at exactly 10,000; the SUMMARY fail count wraps identically. Batch loops of this size are realistic in the target domain. | `splicer/driver.py:48-52`, `injector.py:47-49` | MEDIUM |
| 2.6 | **SQLCA scan keys off the literal text `EXEC SQL` anywhere in a DATA DIVISION line** — a `VALUE "EXEC SQL ERROR"` literal starts a bogus block scan; if a real EXEC block follows, every intervening *live* data item can be commented out. Whole-line replacement also deletes trailing content sharing the `END-EXEC.` line. | `splicer/sqlca.py:76-120` | MEDIUM |
| 2.7 | Case IDs are `PIC X(3)` unguarded — case 1000 truncates to `"100"` and executes case 100's mock branches. | `splicer/driver.py:87,93` | LOW |
| 2.8 | `suite.name` is not quote-escaped in generated COBOL while `case.name` is (unreachable via `parse_cut` today; latent trap on the public `build_driver` API). | `splicer/driver.py:56` | LOW |

## 3. DSL parser and generator

| # | Finding | Where | Severity |
|---|---------|-------|----------|
| 3.1 | **A second `TESTSUITE` line silently discards all previously parsed test cases** — concatenated .cut files run only the last suite, exit 0. | `dsl/parser.py:90-91` | MEDIUM |
| 3.2 | **`END-MOCK.` (trailing period — the natural COBOL habit) or lowercase `end-mock` is not recognized**; everything after it is swallowed into the mock body until the next exact `END-MOCK`, surfacing later as a confusing refusal or compile error. | `dsl/parser.py:41,80-84` | MEDIUM |
| 3.3 | **VERIFY expectation text is unvalidated** — `WAS CALLED TWICE` passes parsing and refusal, then explodes at codegen as an uncaught `ValueError` traceback with no .cut line number. | `dsl/parser.py:46` + `splicer/driver.py:144-155` + `cli/main.py:219` | MEDIUM |
| 3.4 | **`CutParseError` is never caught in the CLI** — any .cut syntax error prints a raw Python traceback instead of the (otherwise good, line-numbered) message. | `cli/main.py:180` | MEDIUM |
| 3.5 | Duplicate `MOCK` keys in one TESTCASE parse fine and surface later as `AMBIGUOUS_MOCK` with misleading advice ("make the keys unambiguous") and no line numbers. | `dsl/parser.py:97-111` | LOW |
| 3.6 | The unterminated-MOCK error is the only parse error without a line number; empty quoted keys (`MOCK CALL ""`) are accepted and only rejected downstream; DSL keywords are fully case-sensitive (undocumented). | `dsl/parser.py:164-168,36` | LOW |
| 3.7 | Generator: a static CALL site with no captured key emits `MOCK CALL ""` instead of skipping (the file-op and ACCEPT branches return `None`); `suite_name` is interpolated unescaped into `TESTSUITE "..."`. | `dsl/generator.py:82-84,44` | LOW |

## 4. Runtime and CLI

| # | Finding | Where | Severity |
|---|---------|-------|----------|
| 4.1 | **The container is never recreated when the image changes**, defeating the content-hash tag: `ensure_toolchain` checks only that a container named `mockymock-cobc` is running, never its image. Edit `docker/Dockerfile` → new image builds, but every compile keeps using the stale container forever. This contradicts `_image_tag`'s stated purpose. | `runtime/docker_toolchain.py:103-124` | **HIGH** |
| 4.2 | **`executed.stderr` and `executed.exit_code` are ignored by `run`** — the infinite-loop hint that `run_binary` attaches on exit 124 is never shown to any user (timeouts render as `[CRASH]` with the misleading "STOP RUN?" framing); libcob runtime aborts printed to stderr vanish; a nonzero exit after the SUMMARY line still exits 0. | `cli/main.py:247-258` (hint at `docker_toolchain.py:219-224`) | **HIGH** |
| 4.3 | **Untrusted COBOL runs as root, with network access, no resource limits**, in a long-lived container with `~/.mockymock/work` mounted read-write. GnuCOBOL supports `CALL "SYSTEM"`, so a hostile `.cbl` or MOCK body (spliced verbatim) can run arbitrary shell in the container: network exfiltration, fork-bomb (no `--pids-limit`/`--memory`), tampering with other concurrent runs' sandboxes. No host escape, but `docker run` should add `--network none`, a non-root `USER`, and pids/memory limits; the threat model is absent from `.okf/runtime.md`. | `runtime/docker_toolchain.py:108-114`, `docker/Dockerfile` | MEDIUM |
| 4.4 | Concurrent first invocations race on `docker run --name` — the loser gets "name already in use" wrapped as `DockerNotAvailableError` and exits 1 even though the container is usable. No retry/recheck. | `runtime/docker_toolchain.py:106-118` | MEDIUM |
| 4.5 | A foreign container named `mockymock-cobc`, or one whose `/work` bind mount is stale (deleted+recreated `~/.mockymock/work`), is silently adopted; failures surface as opaque `exec: cobc: not found` / "no such file or directory" with no remediation hint. | `runtime/docker_toolchain.py:103-124` | MEDIUM |
| 4.6 | Container-side `timeout 30` sends SIGTERM only (no `-k`); a process that ignores it keeps burning CPU in the persistent container after the host-side timeout kills only the `docker exec` client. Each run adds another orphan. | `runtime/docker_toolchain.py:191-200` | MEDIUM |
| 4.7 | No output size limit — `capture_output=True` buffers unbounded stdout in host RAM; a DISPLAY loop can emit GBs inside the 30s window. | `runtime/docker_toolchain.py:146,191` | MEDIUM |
| 4.8 | Nonexistent `program`/`--cut` paths produce raw `FileNotFoundError` tracebacks — and for `run`, only *after* `ensure_toolchain()` may have spent minutes building the image. Existence checks should precede toolchain startup. | `cli/main.py:151,180,43` | MEDIUM |
| 4.9 | `--junit-xml` is written only on the happy path (refusals/compile failures produce no XML — CI collectors see a missing or stale file) and a bad parent directory tracebacks after a successful run. | `cli/main.py:255-256` | LOW |
| 4.10 | All diagnostics go to stdout; exit code is a flat 1 for every failure class (refusal vs docker-down vs test failure), limiting CI discrimination. No `--timeout` flag (the 30s default is unreachable from the CLI); no `setup --force` / `clean` verbs (kept sandboxes and superseded images accumulate with no cleanup path; stale-container remedy `docker rm -f` is documented nowhere). | `cli/main.py` | LOW |
| 4.11 | `IMAGE` is computed at import time by reading `docker/Dockerfile` — a non-editable install crashes on import with a raw `FileNotFoundError` instead of a "requires editable install" message. | `runtime/docker_toolchain.py:36-40` | LOW |

## 5. Report layer

| # | Finding | Where | Severity |
|---|---------|-------|----------|
| 5.1 | Crash diagnosis is stdout-only and the JUnit `<error>` message hardcodes the "PERFORM target reached STOP RUN?" hypothesis even when the real cause was a runtime abort or timeout (whose evidence went to the discarded stderr — see 4.2). | `report/formatters.py:81-85` + `cli/main.py:247-258` | MEDIUM |
| 5.2 | `format_junit_xml` crashes with `ExpatError` when any name/reason contains a control character (verified with `\x01`); suite/case names come from the .cut, which the parser accepts with control chars. | `report/formatters.py:97-98` | LOW-MED |
| 5.3 | No timing anywhere — no `time` attribute on `<testsuite>`/`<testcase>`. | `report/formatters.py` | LOW |
| 5.4 | Duplicate case ids overwrite the `by_id` index (later FAIL/END lines misattributed); an END for an unknown id is silently ignored, asymmetric with FAIL's orphan tracking. Defense-in-depth only — driver ids are sequential. | `report/results.py:62-64` | LOW |

## 6. Packaging, CI, and QA infrastructure

| # | Finding | Where | Severity |
|---|---------|-------|----------|
| 6.1 | **CI checks out cobol-parser unpinned** (no `ref:`), and `requirements-dev.txt` is `-e ../cobol-parser` with no version constraint. The `PARSE_WARNING` refusal gate's teeth live in the sibling repo ("2026-07-07 silent-drop remediation"); a sibling regression silently weakens mockymock's guarantees with no signal here. Pin a ref/tag, or add a contract-test job that fails loudly on drift. | `.github/workflows/ci.yml:43-48`, `requirements-dev.txt:1` | **HIGH** |
| 6.2 | **No linter, formatter, or type-checker at all** — zero `[tool.*]` config, no ruff/black/mypy/pre-commit, and no CI lint/typecheck job. The sibling cobol-parser runs ruff + black + strict mypy in CI; this repo has nothing. | `pyproject.toml`, `.github/workflows/ci.yml` | MEDIUM |
| 6.3 | **No coverage threshold** — pytest-cov is installed but never invoked with `--cov-fail-under` (sibling enforces 81%); no `[tool.pytest.ini_options]` at all. | `pyproject.toml` | MEDIUM |
| 6.4 | Corpus sweep is stale: `docs/corpus-sweep-report.md` names 5/17 real-world programs blocked by a cobolparser EVALUATE bug that has since been fixed upstream (`d8ad880`), but the sweep was never re-run; also `scripts/corpus_sweep.py:40-46` scrapes human-readable CLI stdout with regexes, so any wording change silently zeroes categories. | `docs/corpus-sweep-report.md`, `scripts/corpus_sweep.py` | MEDIUM |
| 6.5 | `mockymock/py.typed` is missing — the code is fully annotated but PEP 561-invisible to downstream mypy. | packaging | LOW |
| 6.6 | `examples/real-world/{DEPTMQC,DEPTMQP}` lack READMEs (invupdt/ and ordrproc/ each have one); no CHANGELOG (sibling keeps one). | examples/, repo root | LOW |

## 7. Documentation drift (OKF actively contradicts code)

CLAUDE.md declares the OKF authoritative ("more specific and more
current"), which makes these worse than ordinary staleness:

| # | Finding | Where | Severity |
|---|---------|-------|----------|
| 7.1 | `.okf/splicer.md:38-40` says the SQLCA transform runs on the DATA DIVISION "before any of the above"; the CLI deliberately runs it **after** `splice_program` because it shifts line numbers. Reimplementing from the OKF would corrupt every span in an INCLUDE-SQLCA program. | `.okf/splicer.md` vs `cli/main.py:196-216` | MEDIUM |
| 7.2 | `.okf/splicer.md:193-196` documents a "known v1 fidelity limit" (group children's VALUE clauses not restored) that `reset.py:87-100` fixed and `test_reset.py:120-155` covers. | `.okf/splicer.md` | MEDIUM |
| 7.3 | `.okf/dsl.md` claims a later PERFORM "overwrites rather than appends" and that unterminated MOCK bodies don't error "with no regression test" — both false (parser raises in both cases; tests exist). | `.okf/dsl.md:45-47,133,142-143,216-223` | MEDIUM |
| 7.4 | `.okf/report.md` describes the orphan-FAIL gap as "still open" — it's fixed (`results.py:42-50,69-70`), gates `all_passed`, and renders in both formatters. | `.okf/report.md:33,57-65,92,149-156` | MEDIUM |
| 7.5 | `.okf/runtime.md` documents the fixed untagged image name (code uses `mockymock-gnucobol:<hash>`), claims sandboxes are "always removed on exit" (`--keep-sandbox`/`--verbose` retention exists), and `.okf/cli.md` omits both flags. | `.okf/runtime.md:73-79,185-193`, `.okf/cli.md:83-137` | LOW |

## 8. Notable test coverage gaps

- **Splicer**: no test contains a SECTION (2.2 unexposed) or same-line
  sibling statements / one-line paragraphs (2.1 unexposed); `statement_span`'s
  end-of-file fallback is never hit; `test_reset.py` has no PICTURE-less
  items, OCCURS-with-VALUE, or numeric-edited PICs; `test_sqlca.py` misses
  the missing-END-EXEC refusal and the literal-text false positive;
  `test_naming.py` misses the empty-key fallback and triple collisions;
  `test_driver.py` misses `_verify_condition`'s ValueError and the 60-char
  suite-paragraph truncation.
- **DSL**: no tests for directives outside TESTCASE, missing TESTSUITE,
  duplicate TESTSUITE (3.1), `END-MOCK.` (3.2), duplicate MOCKs, empty
  quoted keys, or the malformed-MOCK hint path. `test_report.py`'s sample
  fixture invents a `, got 49.99` FAIL-reason suffix the real driver never
  emits — the useful "show actual value" feature doesn't exist.
- **Runtime/CLI**: nothing asserts the timeout hint reaches CLI output
  (which is why 4.2 shipped); `cobc_version()` has no direct unit test;
  `--junit-xml` has zero end-to-end coverage; `sandbox_dir_maybe_kept` has
  no unit test; no tests for missing input files, concurrent
  `ensure_toolchain`, or the stale-image/container scenario.
- No JUnit-escaping pin tests (works today via ElementTree, unpinned).

## 9. What's done well

- **Fail-closed engineering where it exists is genuinely good**: nested
  sites are annotated with validated spans or precise machine-checkable
  refusal reasons, consumed by the gate, and re-checked by the splicer —
  three independent layers. Degenerate THRU ranges refuse instead of
  degrading; unresolved COPY detection re-lexes rather than substring-
  matching; unmocked-unreachable EXEC sites get loud runtime traps.
- **Result integrity in the report layer**: `all_passed` demands
  `tests_run > 0` and no orphans; crash detection via missing END markers;
  JUnit failure-vs-error semantics — truncated output from a killed binary
  can never pass. `test_report.py` is exemplary.
- **Injection/traversal posture at the Docker boundary**: every docker
  call is an argv list (never `shell=True`); `to_container_path` resolves
  both sides before `relative_to`, with unit tests pinning both properties.
- **Empirical verification culture**: docstrings, the OKF, and
  interface-contract.md cite behaviors verified against the real parser
  and compiler (phantom `"."` paragraphs, quote doubling, dynamic-CALL
  identifier capture), and the corpus-sweep report includes positive
  controls for its own detectors.
- The bottom-up span application in the orchestrator, the layered
  timeout design in the toolchain, and the generator's round-trip test
  (scaffold → parse → refusal-gate clean) are all sound designs.

## 10. Recommended priorities

1. **Close the reachability holes** (1.1 GO TO, 1.2 PERFORM-section,
   1.3 SEARCH WHEN) or, cheaper and truly fail-closed: refuse any program
   containing GO TO / PERFORM-of-a-section / SEARCH-with-boundaries /
   DECLARATIVES / ALTER until each is properly modeled. Update the docs'
   guarantee language (1.7) in the same change.
2. **Add the top-level own-line guard and SECTION-header boundaries to the
   splicer** (2.1, 2.2) — these silently corrupt the program under test.
3. **Surface stderr/exit-code in `run`** (4.2/5.1) and recreate the
   container on image-hash change (4.1).
4. **Pin the cobol-parser dependency in CI** (6.1).
5. Bring QA parity with the sibling repo: ruff + black + mypy + coverage
   floor + py.typed (6.2, 6.3, 6.5).
6. Fix the reset-clause compile blockers (2.3, 2.4), widen tally fields or
   guard overflow (2.5), and the DSL ergonomics batch (3.1–3.4).
7. Refresh the four contradicting OKF sections (7.1–7.5) and re-run the
   corpus sweep against the fixed cobolparser (6.4).

## Suspected issues checked and cleared

- Hostile file/program names cannot shell-inject (argv lists throughout);
  symlink/`..` traversal out of `WORK_ROOT` raises.
- 88-level condition names are safely skipped by reset; generated long
  lines are safe under `cobc -free`; the naming registry keeps all
  generated names ≤ 30 chars even under collision.
- STRING/UNSTRING (in-memory), EXEC SQL cursors, and dynamic-CALL
  identifier capture are all handled correctly.
- `--version` exists; DISPLAY pass-through is intentional and documented.
