# mockymock — Mainframe (z/OS) Export Command Design

Date: 2026-08-03
Status: proposed

## Motivation

mockymock's instrumented build — the source `_cmd_run` actually compiles —
is mock-only by construction. `injector.py`'s `build_site_dispatch`
docstring says it plainly: "EVALUATE block **replacing** one mocked boundary
statement." Every mockable boundary (subprogram `CALL`, file I/O, `EXEC
SQL`/`CICS`/`DLI`, `ACCEPT`) has its real statement deleted; an uncovered
site becomes `build_exec_trap` (`injector.py:168`), which "still has to be
commented out for the program to compile at all" and fails loudly
(`ADD 1 TO UT-FAIL-COUNT`) instead of running the real call. No real I/O
executes in this build today, even under GnuCOBOL.

This matters for what a new "copy to the mainframe" command can honestly
promise. It cannot mean "test the program for real against DB2/CICS on
z/OS" — mockymock has no path from fake mock data to real DB2 rows or CICS
transactions. It *can* mean "compile and run this same mock-only build
under the real IBM Enterprise COBOL compiler instead of GnuCOBOL," which
validates exactly the gap `docs/2026-07-06-real-world-readiness-audit.md`'s
Finding 1 (the "fidelity ceiling") already flags as open and structural:
EBCDIC collation, COMP-3/zoned-decimal sign edges, intermediate arithmetic
precision, numeric-edited PICTUREs, IBM intrinsics/extensions — none of
which GnuCOBOL can prove. Confirmed with the user during brainstorming:
this is the target (not the real-I/O reading, and not both).

## Scope

**In scope:**
- A new Docker-free CLI subcommand, `mockymock export`, that runs the same
  parse → static-checks → splice → driver-insert pipeline `run` uses
  (`_cmd_run` steps 2–13 per `.okf/cli.md`), stopping before any Docker
  step, and writes the result to a chosen file instead of a throwaway
  `sandbox_dir`.
- Three adjustments so that output is z/OS-compilable rather than
  GnuCOBOL-only (detailed below): preserved `PROCESS`/`CBL` directives,
  restored fixed-format columns (padding + generated-`DISPLAY` wrapping,
  with a residual refusal backstop), and a provenance/disclaimer header.
- A new VS Code command-palette entry, `mockymock.exportMainframe`, that
  resolves the active `.cut`/`.cbl` pair and shells out to the CLI command.
- Unit tests for the new refusal and for the directive-preservation
  behavior.

**Explicitly out of scope** (considered and deferred, not forgotten):
- **JCL generation.** Dataset names, PROC libraries, DB2 plan/collection
  names, and CICS region config are shop-specific and unknowable from this
  repo. If wanted later, the right shape is a skeleton with marked
  placeholders the user fills in — a separate, smaller ask once this
  lands.
- **A `--target` flag / multi-target design.** Only one target exists
  today. Building for hypothetical future targets now is speculative scope.
- **`cobc -std=ibm` as a smoke-compile proxy check.** GnuCOBOL's
  IBM-compatibility dialect flag is a plausible cheap pre-check (still
  inside the existing container, no new image), but its exact behavior is
  unverified against this codebase's output. Noted as a future idea, not
  built here.
- **Automated verification against a real IBM compiler.** None is
  available in this environment or in CI. The provenance header states the
  ceiling explicitly instead of the command silently overclaiming.
- **Shipping the original, unmodified program plus a `.cut`-derived manual
  test plan for real DB2/CICS/dataset validation.** This was the other
  option surfaced during brainstorming (real I/O, real mainframe
  resources, but nothing about it can be automated — mock data has no
  mechanical path to becoming real DB2 rows or CICS transactions). Rejected
  in favor of the real-compiler-validation reading above.
- **Finding 1's README mitigation** ("what a passing run proves" section).
  Adjacent, already-tracked separately; not folded into this feature.

## Design

### Pipeline

```
mockymock export <program> --cut PATH [-o/--output PATH]
                  [--copybook-path DIR ...] [--case NAME ...] [--tag TAG ...]
   │
   ├─ run_static_checks(..., preserve_compiler_directives=True)   (no Docker)
   │     same refusal gates as run/lint: expansion warnings, parse errors,
   │     unresolved copybooks, nested-EXEC, data-division-EXEC precheck,
   │     per-case checks
   ├─ collect_boundaries / TallyRegistry / terminator+flow plans / splice_program
   │     (identical to _cmd_run steps 11-13)
   ├─ transform_data_division_exec(lines)            (real pass, kept output)
   ├─ reset_move_lines + build_driver + _insert_driver
   ├─ NEW: restore_fixed_format_columns (7-space prefix restoration)
   ├─ NEW: wrap_long_display_lines (split over-72 generated DISPLAYs;
   │        refuse (COLUMN_OVERFLOW) only on a residual that can't be wrapped
   ├─ NEW: prepend provenance/disclaimer header
   └─ write to --output (default "<program-stem>.mainframe.cbl", next to
        the input .cbl, matching `generate`'s suffix-swap convention)
```

No Docker/GnuCOBOL dependency, matching `generate`/`lint`/`collect`'s
existing Docker-free pattern — the instrumented source is fully built
before `_cmd_run` ever calls `ensure_toolchain()`.

`--case`/`--tag` are threaded straight into the shared `run_static_checks`
selection logic already used by `run`, at no extra cost.

### Adjustment 1 — preserve `PROCESS`/`CBL` directives

Today, `run_static_checks` unconditionally strips these
(`checks.py:176-186`) because they precede `IDENTIFICATION DIVISION`,
parse fine for `cobolparser`, but GnuCOBOL's `cobc` rejects options/syntax
it doesn't recognize. `export` needs the real IBM compiler-directing
statements kept intact. `run_static_checks` gains
`preserve_compiler_directives: bool = False`; default behavior for
`run`/`lint` is unchanged, `export` passes `True`.

### Adjustment 2 — restore real fixed-format columns

Two distinct problems here, both found empirically (spiked against
`examples/custprog/` and a real GnuCOBOL compile+run before writing this
revision — see below), not reasoned from the docstrings alone:

**2a. `normalize_fixed_format` strips columns 1-7, and splicer-generated
lines don't expect that.** Its own docstring says "Extract program text
cols 8-72" — confirmed: `'       IDENTIFICATION DIVISION.'` (7 leading
spaces in the raw source) normalizes to `'IDENTIFICATION DIVISION.'` (cols
1-7 gone). But `driver.py`/`injector.py` generate their OWN lines assuming
index 0 *is* column 1 (`_insert_driver`'s WORKING-STORAGE lines get a
literal `f"       {ws_line}"` 7-space prefix; `driver.py`'s paragraph
headers are written as `f"       UT-TESTCASE-{case_id}."`). Spiked
directly: prepending 7 spaces to every `checked.lines` entry (right after
`run_static_checks` returns, before `collect_boundaries`/`splice_program`)
lets the full pipeline (`collect_boundaries` → `find_terminator_plans` →
`find_flow_mock_plans` → `splice_program` → `transform_data_division_exec`
→ `build_driver` → `_insert_driver`) run to completion with no errors, and
the resulting paragraph headers (`UT-TESTSUITE-...`, `UT-TESTCASE-001.`)
land at exactly 7 leading spaces — real column 8, real Area A — confirming
`splice_program` and friends are line-granular (whole-line replacement,
per the "fail closed on any shared-line content" pattern already seen in
`sqlca.py`/`injector.py`), never column-position-sensitive, so a uniform
prefix is transparent to them. `restore_fixed_format_columns` in the new
`export`-only module does exactly this — scoped to `_cmd_export`, touches
no shared code.

**2b. Column-72 overflow is real, but it isn't the user's fault, so
refusing on it would be wrong.** Spiked against `examples/custprog/`: the
final instrumented output already has 8 lines past column 72 (up to 138
chars) even for this ordinary, already-shipped example. Every one of them
is a `DISPLAY "__MOCKYMOCK__ ..."` statement generated by `driver.py`
(`build_driver`/`_build_testcase_paragraph`) or `injector.py`
(`build_exec_trap`) — the `__MOCKYMOCK__` protocol boilerplate text itself
is long; zero original-source lines and zero user-authored mock-body
lines overflowed. A `.cut` author cannot fix text they didn't write, so a
refusal here would block the command on nearly every real program while
giving the user nothing actionable. Simply warning and shipping the
overflow is equally wrong the other way: it hands back an artifact that
silently miscompiles (truncates) on the one target this feature exists to
serve.

The fix is at the generator, for the export path only:
`wrap_long_display_lines` recognizes every over-72 line matching mockymock's
own generated shape — `DISPLAY "<literal>"[ <trailing non-literal
expression>][.]` (the only shape `driver.py`/`injector.py` ever produce,
confirmed by reading every `DISPLAY` call site in both files) — and splits
the literal text across multiple `DISPLAY "<chunk>" WITH NO ADVANCING`
lines (re-escaping doubled quotes per chunk) plus a final plain `DISPLAY`
carrying the trailing expression and any original trailing period, each
line within 72 columns. **Verified empirically against the real
`mockymock-cobc` container** (`compile_source`/`run_binary`, not a
reimplemented subprocess call): a hand-split `DISPLAY "frag1" WITH NO
ADVANCING` / `DISPLAY "frag2" WITH NO ADVANCING` / `DISPLAY FUNCTION
TRIM(...)` sequence produces byte-identical stdout to the single long
`DISPLAY` it replaces — the `__MOCKYMOCK__` stdout protocol survives the
split exactly. (This proves the split preserves COBOL's `DISPLAY`
semantics under a real COBOL runtime; it does not prove IBM Enterprise
COBOL accepts the wrapped form specifically, since GnuCOBOL still compiles
via `-free` here too — that residual belongs in the disclaimer header, not
in another spike, as no IBM compiler is reachable from this environment.)

A line that still can't be brought under 72 after wrapping (not a
recognized `DISPLAY` shape, or a single trailing expression alone too
long to fit) is the honest fail-closed backstop: refuse
(`COLUMN_OVERFLOW`), naming the line. Expected to fire approximately
never given the shapes actually generated today.

### Adjustment 3 — provenance/disclaimer header

A comment block prepended to the output, naming the source `.cbl`/`.cut`
and stating plainly: this build is mock-only (no real I/O anywhere in it —
every boundary is either a mock or a fail-loud trap), and listing the
known GnuCOBOL-vs-IBM-COBOL gaps a clean compile here does *not* rule out
(EBCDIC collation, COMP-3/zoned-decimal sign edges, intermediate
arithmetic precision, numeric-edited PICTUREs, IBM intrinsics). This keeps
"compiles clean on z/OS" from being mistaken for "fully validated," in the
same honest-about-the-ceiling spirit as Finding 1's recommended mitigation.

**No change needed** to `splicer/sqlca.py`'s synthesized SQLCA — it's
already the standard field layout (`SQLCAID`/`SQLCODE`/`SQLERRD`/...,
`sqlca.py:41-61`), not GnuCOBOL-specific. By the time splicing finishes,
zero live `EXEC SQL`/`CICS`/`DLI` statements remain anywhere (all replaced
by plain `EVALUATE`/`MOVE`/`DISPLAY`), so the export needs no DB2/CICS/IMS
precompiler step — a plain COBOL compile is sufficient.

### VS Code command

The extension has exactly one existing palette command,
`mockymock.checkEnvironment` (`package.json:26-30`, `extension.ts:25-35`) —
`run`/`lint`/`debug` are wired through the Testing API and diagnostics, not
palette entries. `mockymock.exportMainframe` follows `checkEnvironment`'s
simpler shape (a one-shot action, not a per-test-case one):

1. Resolve the active editor's `.cut`/`.cbl` pair via the existing
   `resolveCblPath` convention (`cutDiscovery.ts:157-160`); if the active
   editor doesn't resolve to a known pair, quick-pick among the suites the
   Test Explorer has already discovered.
2. Run `mockymock export <cbl> --cut <cut> --copybook-path <configured
   paths from mockymock.copybookPaths> -o <path>`.
3. On success: open the written file in a new editor tab, plus an info
   message (mirrors `checkEnvironment`'s "success needs its own feedback"
   comment — a silent success is easy to miss).
4. On failure: surface the CLI's refusal text, following whatever
   convention `lintDiagnostics.ts` already uses for showing CLI errors —
   exact mechanism (Output channel vs. error message) confirmed during
   implementation by reading that file, not assumed here.

## Testing

- Unit: `restore_fixed_format_columns` — a fixture list of normalized
  lines, assert each gets exactly a 7-space prefix.
- Unit: `wrap_long_display_lines` against the *actual* over-72 lines seen
  in the `examples/custprog/` spike (literal-only, literal +
  `FUNCTION TRIM(...)`, literal + plain identifier, literal + trailing
  period) — assert each wraps into `WITH NO ADVANCING` fragments all
  ≤ 72 columns, with the trailing period (where present) landing only on
  the last fragment.
- Unit: a deliberately unwrappable line (not a recognized `DISPLAY` shape)
  -> `COLUMN_OVERFLOW` refusal naming it — the residual backstop.
- Unit: a fixture program with a leading `CBL`/`PROCESS` directive ->
  `export` keeps it in the output; `run`/`lint` on the same fixture still
  strip it (regression guard that the shared-checks default is unchanged).
- Unit: structural assertion that no live `EXEC SQL`/`CICS`/`DLI` text or
  real dynamic-`CALL` boundary survives in export output for a fixture that
  exercises every boundary category (`examples/invupdt/` is the natural
  fixture — every category in one program).
- Integration (Docker-gated, skipped without a daemon like the rest of
  `tests/integration/`): compile+run the wrapped `DISPLAY` sequence through
  the real `mockymock-cobc` container and diff stdout against the
  unwrapped original, exactly as spiked during design — pins the byte-
  identical-output claim as a regression guard, not just a one-time manual
  check.
- No test can reach a real z/OS system or a real IBM compiler; that
  ceiling is stated in the output header, not hidden or simulated.

## Docs to update after implementation

- `.okf/cli.md` — new `## mockymock export` subcommand section, in the
  same style as the other seven; update the overview's subcommand list and
  ASCII pipeline diagram.
- `.okf/index.md` — link the CLI doc's updated description if the summary
  line changes.
- `.okf/log.md` — dated entry once implemented.
- `README.md` — one line under "Beyond pass/fail" alongside `--coverage`/
  `--trace`/`--dap-stdio`/`dashboard`.
- mocky-mock-vscode-extension's own docs/CLAUDE.md, if any exist there,
  for the new command — confirmed by checking that repo at implementation
  time rather than assumed here.

## Alternatives considered

- **Export the original, unmodified program plus a manual DB2/CICS test
  plan derived from the `.cut` file**, for real mainframe-resource testing.
  Rejected during brainstorming: cannot be automated (no mechanical path
  from mock data to real DB2 rows/CICS transactions), and is a
  fundamentally different, much larger feature (a UAT-checklist generator)
  than a code export.
- **Wire the new command into the VS Code Testing API tree**, like
  `run`/`lint`/`debug`. Rejected — this isn't a per-test-case action; it
  produces one artifact per program/cut pair, which matches
  `checkEnvironment`'s existing one-shot palette-command shape better.
- **A `--target` flag for future non-z/OS dialects.** Rejected as
  speculative — nothing today needs a second target, and the three
  adjustments above are z/OS-specific by nature (IBM directives, z/OS's
  fixed-format column discipline).
