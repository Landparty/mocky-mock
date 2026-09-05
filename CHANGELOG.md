# Changelog

## Unreleased

### Changed

- **`mockymock analyze gen-data` can now emit a copybook's real record bytes**, via `--format record` (packed/binary/zoned bytes a COBOL program would actually read) or `--format hex` (the same image annotated with each field's offset, length, PICTURE and USAGE — the form that survives being opened in an editor). No mockymock code changed: `analyze` is an unguarded `REMAINDER` passthrough into cobol-parser's CLI, so every new `gen-data` flag — `--charset ascii|ebcdic`, `--endian`, `--record-separator` — is available as soon as cobol-parser has it. Worth knowing because the VS Code extension's "Generate Data from Copybook" action builds exactly this invocation; surfacing the format there is an extension-side change. mockymock's own mocking never needed it — the splicer emits `MOVE <literal> TO <field>` and lets GnuCOBOL pack the value, so `COMP-3`/`COMP-5` boundaries already worked.
- `examples/fixtures/FIXTUREDEMO.bundle.json` re-copied from cobol-parser. Its `FieldSpec` entries gained four **additive** keys (`storage_size` — the item's real byte width, as opposed to `size`, which counts PICTURE character positions; plus `sign_clause`, `synchronized`, `occurs_depending_on`). `bundle_version` stays `1` and `dsl/fixture_bundle.py` ignores unknown keys, so the loader is unchanged.

### Added

- **`mockymock generate` now scaffolds `CAPTURE ARG <n> INTO ...` for every mockable CALL argument, and mockymock declares the storage.** Asserting on what a mocked `CALL` actually received is usually the most interesting assertion in a test, but the `CAPTURE ARG` target had to be an existing data item of a compatible type -- so finding or adding one was a manual step before every capture, and `generate` never emitted one (explicitly out of scope in the original argument-capture design). A target named `UT-CAP-...` now means "declare this for me": `splicer.captures` synthesizes a WORKING-STORAGE item mirroring the argument's own PICTURE/USAGE (a DISPLAY-only group becomes one `PIC X(<byte length>)` field, exactly what a group MOVE copies) plus a reset line between test cases, threaded through all four splice pipelines. The reserved prefix keeps it from being a footgun -- a mistyped real data name never starts with `UT-CAP-`. Fail-closed elsewhere: a new `UNRESOLVED_CAPTURE_TARGET` refusal covers an argument that names different items at different matching call sites, a layout that cannot be mirrored (a table, a PICTURE-less COMP-1/POINTER item, a group holding non-DISPLAY data), and a name the program already declares. A target without the prefix behaves exactly as before. `generate` also emits one `*> STUB EXPECT <target>` comment per capture, which `run --record-expectations` promotes to a real `EXPECT` from an actual run.
- `mockymock run --coverage-fail-under PERCENT` -- exits 1 when the ORIGINAL program's line coverage falls below the given percentage, the `run` counterpart of `mutate --fail-under`. Implies `--coverage`. Coverage previously could not be CI-gated at all even though mutation score could. Gated on the original program's number rather than the instrumented copy's (that one moves whenever mockymock's own injected line count changes, which says nothing about the program under test), folded into the command's final exit-code decision so `--trace` output still prints, and a failed `gcov` pass FAILS the gate -- "no number" must never read as "good enough".
- `refusal` code `UNMOCKABLE_ACCEPT_SOURCE` -- a `MOCK ACCEPT` aimed at an `ACCEPT <target> FROM DATE/TIME/DAY/COMMAND-LINE/...` now refuses with its own message saying that ACCEPT variant is not mockable at all (it reads a system register, never the console, so `mock_surface` deliberately creates no boundary site for it). It used to fall through to `UNMATCHED_MOCK: ... does not match any boundary site reachable from '<paragraph>'`, which reads as a call-graph reachability bug and sent authors off verifying reachability by hand for a problem that was never about reachability. `MockSurface.non_interactive_accepts` records these detected-and-deliberately-unmockable ACCEPTs for the message; they are still never spliced and never listed as unsupported boundaries.

- **`mockymock mutate` got its two big cost levers** (`docs/2026-07-29-mutation-testing-design.md`'s deferred items 1 and 3). Neither changes a verdict; both remove or spread work. **A coverage gate, on by default**: the baseline is compiled with GnuCOBOL's `--coverage` and its gcov output remapped onto the ORIGINAL source, so any mutant sitting on a line the whole suite provably never executes is reported `survived` from that evidence alone -- no splice, compile or run of its own. That is exact rather than heuristic: a line no test case reaches cannot change what any test case observes. A line *absent* from the remap (driver insertions, boundary replacements, continuation merges -- the cases `map_coverage_to_original` deliberately drops) is unknown, never "uncovered", and is always built. A `--coverage` build is a different compile and a slower binary than the one `run` performs, so a baseline that fails *at the compile step* or times out is re-run plain before it is believed -- while a genuinely red suite or a refusal-gate stop is not, since gcov instrumentation changes neither (the new `SuiteRun.phase`, "checks"/"compile"/"run", is what tells those apart, and is also the hook a future stillborn-vs-refused split needs). A gcov pass that produces nothing appends a `mockymock mutate:` note and the run builds everything. Gated survivors are scored exactly like built ones; they carry `ran: false` and `totals.not_compiled` in `--json-report` and print as `uncovered` rather than `SURVIVED`, so a verdict reached from coverage never reads as a mutant that was built and beat the suite. `--no-coverage-gate` builds everything. **And `--jobs N` / `-j N`** (default 1): the per-mutant pipeline spread across N worker *processes* -- processes, not threads, because the dominant Docker-free cost is `run_static_checks`, which is CPU-bound pure Python. Measured on a synthetic 3,610-line program on 4 cores: 1.93x at `--jobs 2`, 3.90x at `--jobs 4` (that program's static-check cost alone is ~23 minutes serial, before a single `cobc` runs). Results are consumed in submission order, so the report, the live progress stream and the notes union stay byte-identical to a serial run whatever order the workers finish in, and the source is handed to each worker once through the pool initializer rather than pickled per task. The default is 1 deliberately: the ceiling is not the core count but the shared `mockymock-cobc` container's `--memory 1g`, which every concurrent `cobc` draws from at once -- an OOM-killed compile would be recorded as a `stillborn`, a wrong verdict, quietly. **Neither lever has been exercised against a real Docker daemon** (none available where this was built); the coverage/parallel logic is covered by `tests/unit/test_mutation_speed.py` against a stubbed pipeline, and the parallel scaling number above was measured on the Python half only.
- **CICS implicit-linkage support**: a program referencing CICS EIB fields (`EIBCALEN`, `EIBAID`, `EIBTIME`, `EIBTRMID`, `EIBDATE`, ...) from ordinary COBOL outside any `EXEC CICS` block -- a real CICS translator inserts `DFHEIBLK`'s LINKAGE SECTION layout ahead of `cobc` ever seeing the source, so these names would otherwise fail compilation as undeclared -- now gets a synthesized `01 DFHEIBLK.` WORKING-STORAGE group with the standard IBM EIB layout, reset between test cases (`INITIALIZE DFHEIBLK`), and addressable from `.cut` `MOCK`/`EXPECT`/setup-move directives like any other field (`analysis.cics_eib`/`splicer.cics_eib`, wired into `run`/`debug`/`export`/`mutate`/`generate`). Also generalizes the existing IMS ENTRY/LINKAGE neutralization (`analysis.linkage.linkage_plan`) to LINKAGE SECTIONs with zero `ENTRY` statements -- the idiomatic CICS `LINKAGE SECTION. 01 DFHCOMMAREA. ...` / `PROCEDURE DIVISION.` (no `ENTRY`) shape is now real, addressable WORKING-STORAGE too, per the IMS design's own empirical finding that the storage is unbound regardless of `ENTRY`'s presence. Two new fail-closed refusals for what neither mechanism can safely handle: `UNSUPPORTED_CICS_MACRO` (`DFHRESP(...)`/`DFHVALUE(...)` macro calls, which only a real CICS translator can expand) and `UNSUPPORTED_CICS_DFHCOMMAREA` (`DFHCOMMAREA` referenced but never declared anywhere -- unknowable size). **Not yet verified against real GnuCOBOL** -- no working Docker daemon when this was built; see `docs/2026-08-27-cics-eib-linkage-support-design.md`'s "No corpus evidence" section for the required follow-up.
- `.cut` DSL: `EXPECT` negation and comparison operators — `EXPECT <name> [NOT] TO BE [GREATER THAN|LESS THAN [OR EQUAL TO]] <value>`. Each phrase normalizes at parse time to a canonical COBOL relation operator on `ExpectDirective.operator` (`=`, `NOT =`, `>`, `<`, `>=`, `<=` and their negations); plain `TO BE` stays exact equality, so every existing `.cut` file parses and compiles byte-identically. The generated failure check compiles the operator's negation (`TO BE GREATER THAN` emits `IF <name> NOT > <value>`); the FAIL line and the `--json-report` `expected` field carry the operator (`expected WS-X > 5, got 004`; the bare-value report shape is unchanged for plain equality). A dangling comparison phrase (`TO BE GREATER 5`, `... OR EQUAL 5`) is a line-numbered `CutParseError` instead of a cobc compile error in generated code.

- `.cut` DSL: `MOCK SORT <sd-name>` / `MOCK MERGE <sd-name>` (and matching `VERIFY`) — a plain-file-form `SORT ... USING ... GIVING ...` / `MERGE ... USING ... GIVING ...` (no INPUT/OUTPUT PROCEDURE) is now a mockable boundary, keyed by its own SD file name, spliced the same way as any other file-op verb. `MOCK RELEASE <record>` / `MOCK RETURN <sd-name>` (the latter also gaining the `ROWS ( ... ) TERMINAL ( ... )` sugar previously READ-only) — a pure `INPUT PROCEDURE ... OUTPUT PROCEDURE ...` SORT (no USING/GIVING at all) is left real/unspliced, with its RELEASE/RETURN statements independently mockable instead; the reachability gate now models a SORT/MERGE's INPUT/OUTPUT PROCEDURE as an implicit PERFORM edge so a RELEASE/RETURN reachable only through one is never invisible to the fail-closed refusal gate. `mockymock generate` scaffolds all four automatically. A SORT/MERGE mixing a USING/GIVING file with a procedure clause on the other side stays refused fail-closed with `UNSUPPORTED_SORT_MERGE` — mocking that shape would either skip the procedure's own logic or touch a physical file mockymock has no mechanism to seed. See `docs/2026-08-17-sort-merge-using-giving-mocking-design.md`.
- `mockymock fixtures <program> [--scenarios happy|branches|all] [--seed N] [--rows N] [--copybook-path DIR]...` — new subcommand: prints a cobolparser `FixtureBundle` (scenarios, seeded mock data, expectations) as JSON on stdout, for editor integrations. No Docker dependency; stdout is JSON only, all diagnostics go to stderr.
- `mockymock generate --with-data --rows N` — seeds the self-generating fixture bundle's row count (`--rows 0` is honored, not treated as falsy). Rejected with a stderr error and exit 1 when combined with `--fixtures`, whose row count is already baked into the checked-in bundle.
- `mockymock generate --placeholder CATEGORY:KEY` (repeatable; valid with either `--with-data` or `--fixtures`) — downgrades a matched fixture's mock body to its ordinary non-data placeholder while keeping it mocked; a malformed value (no `:`) exits 1, an unmatched pair warns on stderr. A downgraded loop-bearing boundary (a multi-row `READ`, a multi-row `SQL ... ROWS` cursor fetch) keeps real loop-termination semantics instead of silently hanging, and its tier-1 `VERIFY ... WAS CALLED n TIMES` is recomputed to match the downgraded body's actual call count (or demoted to a `*>` comment when that count isn't knowable by construction).
- `.cut` DSL: `ROWS` now applies to `MOCK READ <file> ROWS` (previously `MOCK SQL "..." ROWS` only), with an optional READ-only `TERMINAL ( FIELD = value, ... )` group for the rows-exhausted branch. Hand-authoring grammar only — the bundle-driven `generate --with-data`/`--fixtures` scaffold does not emit it.
- `refusal.find_goto_exit_plans` — automatically splices a `GO TO` into a provably no-op paragraph (one bare `EXIT.` statement) into `EXIT PARAGRAPH` at its own call site, letting a `STOP RUN`/`GOBACK` chain that was only blocked by that exact GO-TO-as-early-exit idiom qualify for terminator neutralization too. Only applies when the exit-only paragraph immediately follows the enclosing (top-level) paragraph in source order; SECTION-scoped enclosing paragraphs are not supported. **Not yet verified against real GnuCOBOL** — see `docs/2026-08-17-goto-exit-paragraph-simplification-design.md`'s Status note; the Docker-required integration fixture that would confirm it has not been run.

### Changed

- **`mockymock export` fits a literal-less overflow too, and its refusal names the real source.** Two follow-ups to the literal-continuation work landed in #101. First, `fit_within_columns` gained a third pass (`_break_at_whitespace`) for the one shape the first two cannot fit: a line with no literal at all (`MOVE WS-A-LONG-SOURCE-NAME TO WS-A-LONG-TARGET-NAME`), which pass 2 could only report as "holds no single quoted literal to split". A COBOL statement may span as many fixed-format lines as it needs -- only a *literal* broken across the boundary needs the column-7 `-` -- so that line needs no continuation machinery at all, just a break at a space with the remainder starting in Area B. Only a single word too long for Area B (61 characters) still refuses. Second, that refusal now names where the line came from (`SourceAttribution`): mockymock's own generated reset for a specific item, the `.cut` file and line, the `.cbl` file and line, or explicitly neither. The message used to assert "this typically comes from a `.cut` file's MOCK body text" whatever the real source was, sending readers to the wrong file whenever the offending text was mockymock's own generated code -- which no `.cut` edit could shorten. Matching is exact stripped-text lookup, so an attribution is a fact rather than an inference.

- **`mockymock run --coverage`'s console report now leads with the ORIGINAL `.cbl`'s own coverage.** There have always been two coverage numbers and, until now, the prominent one was the less useful one: the stdout line reported the *instrumented sandbox copy* (inflated by mockymock's injected dispatch/driver lines), while the meaningful original-file figure existed only inside `--coverage-json`. The headline percentage and the listed uncovered lines are now the original program's, by their original line numbers; the instrumented number still appears, once, on a labelled line saying why it is higher. `--coverage-json`'s `original` block gained a `percentage` key to match (additive -- a v1 consumer is unaffected).
- **`mockymock mutate` now reports WHY each stillborn mutant was stillborn.** Stillborn mutants are excluded from the mutation score entirely, so a bare count made them a black box: a line whose every mutant failed to compile looked identical to a line with no mutants at all, and a genuine gap the mutation engine could never probe hid behind a clean-looking score. `SuiteRun.phase` already knew the answer and was dropped when the `MutantResult` was built; it is now carried through as `stillborn_reason`, and the console report groups stillborns as `checks` (a mockymock static gate rejected the mutated program before any compiler ran -- often an equivalent mutant) vs `compile` (GnuCOBOL rejected it -- that line was never probed), listing each mutant under its reason. `--json-report` gained `stillbornByReason` totals and a per-mutant `stillbornReason`. The classification is never re-derived from the raw compiler/gate `detail` text.

- **`UNSUPPORTED_CICS_MACRO` is now reachability-scoped for `run`/`lint`/`export`/`debug`.** A `DFHRESP(...)`/`DFHVALUE(...)` call used to refuse the whole file the moment the text appeared anywhere in it -- on a real 16.9k-line CICS program, one such call in a screen-handling paragraph nothing under test performs blocked every test case in the file, with no `.cut` change able to work around it. It now travels the same held-back path `PARSE_WARNING` and `UNRESOLVED_COPYBOOK` already do (`check_cics_eib_layout_scoped`): refused only when some selected test case can execute the paragraph holding the call, otherwise waived with a transparency note. The macro is scopable because it describes *code that evaluates it*, not storage layout -- which is why `UNSUPPORTED_CICS_DFHCOMMAREA`, a missing declaration, stays whole-program unconditionally. A waived call is rewritten in place to `-1`, space-padded to the identical width so no line or column moves, since `cobc` has no CICS translator and could not compile the unexpanded macro even in dead code (the same reasoning as commenting out a waived unresolved `COPY`). Anything the classification cannot pin down -- a DATA DIVISION occurrence, a call continued across lines, an argument that is not a single COBOL word -- stays a whole-program refusal, fail closed; `generate`/`fixtures` (no test cases to scope by) keep the unconditional entry point. **The rewritten source has not been compiled against real GnuCOBOL** -- no working Docker daemon when this was built.
- **The static-check pass (`mockymock lint`/`run`) is now linear in program size instead of quadratic.** Three scans were the cause and all three are pure speedups -- `lint` output is byte-identical before and after, on runs producing thousands of refusals: `ScopeMap` queries were full scans of the boundary list (two of them copying the whole list first) with one query per boundary site, `collect_scope_map` re-scanned the EXEC-block range list per lexed token, and `_falls_through` was re-evaluated for every paragraph on every GO TO target's fall-through walk (4.4M calls on a 53k-line program in the shared-exit-label shape, where nothing on the chain provably diverts so each walk runs to end of program). Also collapsed `cics_eib_plan`'s 29 separate whole-text regex searches into one alternation pass. Measured on a 53k-line CICS-shaped program: 14.2s -> 5.5s.
- `refusal.check_test_case` gained a second `UNRESOLVED_FILE_STATUS_TARGET` trigger: a `MOCK READ ... ROWS` mock with neither its own `TERMINAL` group nor a declared `FILE STATUS` field on that file now refuses fail-closed instead of generating a read loop with no way to terminate.
- `splicer/injector.build_rows_block` generalized from a SQL-only function that hardcoded SQLCODE 0/100 to `build_rows_block(tally_name, rows, *, row_suffix_moves, exhausted_moves)`, with the SQLCODE literals moved to their SQL call site in `build_site_dispatch` and a new READ call site alongside it.
- **`cobol-parser` is now consumed as a normal pinned PyPI dependency (`cobol-parser>=1.7.7,<2`), not a vendored git-SHA pin.** `cobol-parser` publishes closed-source wheels to PyPI, so CI no longer checks out and builds the sibling repo from source; the editable sibling install and cross-repo checkout steps are gone from `requirements-dev.txt`/`ci.yml`.

### Fixed

- **`mockymock generate --with-data` now surfaces cobol-parser's self-verification verdict.** A generated scenario's name is a claim about which branch its data reaches, and nothing in the generated `.cut` said whether that claim held -- confirming it meant running `mockymock run --trace` on every case. cobol-parser now verifies each scenario against its own generated data and records the result in the bundle; an `unverified` verdict renders as a `*> UNVERIFIED:` comment above the affected TESTCASE, naming each field whose generated values do not satisfy the branch and each enclosing condition that was never pinned. Verified scenarios get no note, and a bundle produced before the key existed is read as "no verdict recorded" rather than as unverified.
- **A scaffolded `MOCK READ`'s `WHEN OTHER` arm now carries the program's own `AT END` imperative instead of a `TODO` comment.** The splicer replaces the WHOLE `READ` statement, deleting its `AT END` clause with it -- so a generated mock that moves only the FILE STATUS field never runs the program's own end-of-data handling, and a `PERFORM ... UNTIL <eof-flag>` loop keyed on it spins until the executor timeout. A `TODO` left in place is therefore not a visible gap but a silent 30-second hang with no diagnosis. The AST-driven replication (a literal-sourced `MOVE`, a constant-valued `SET`) is unchanged and still preferred; when it comes up empty, `_lifted_at_end_lines` now lifts the clause's own source text verbatim -- a slice of the program, exactly the text the splice is about to delete, so it covers identifier-sourced MOVEs, `ADD`, `IF`, `PERFORM` and everything else a real clause holds rather than only the shapes an AST walk knows. `AT END` is located positionally with words scanned outside quoted literals (a `DISPLAY "AT END OF FILE"` is never mistaken for it) and cut at the first of `NOT AT END` / `END-READ` / `INVALID KEY` / a sentence-terminating period. Lifted lines carry a `*>` comment naming the source line. The `TODO` remains as the fallback when the clause cannot be located.
- **`mockymock generate --with-data` no longer silently drops the bundle's boundary-level stub expectations.** Every `WRITE:` (and any other OUT-direction) tier-3 stub in the bundle was discarded on the reasoning that the same boundary's `call_count` VERIFY already covered it -- but an OUT-direction boundary has no such VERIFY, so the analysis knew something the generated `.cut` never said. They now render as `*> STUB EXPECT <CATEGORY> <KEY> -- <note>` comments (inert, so they cannot break the generated file), and are dropped only when this same TESTCASE genuinely emits a live `VERIFY ... WAS CALLED` for that boundary. The two-token boundary form does not match the `--record-expectations` scanner's data-name grammar, so it is left alone there rather than mistaken for a data item.

- **`mockymock mutate` generated stillborn mutants on traditional 80-column source (four distinct causes).** Measured over a 542-file corpus (the vendored NIST CCVS85 suite, the shamrice examples, and this repo's own fixtures), **2,165 of 17,689 generated mutants -- 12.2% -- were defective**: each wasted a full splice/compile/run cycle and inflated the `stillborn` count that is supposed to measure operator precision. (1) **Column overflow**: mockymock normalizes source by slicing columns 8-72, so `ADD..TO -> SUBTRACT..FROM` (seven characters longer) pushed its own tail off the end of 671 lines. (2) **Identification-area drag**: the inverse swap is seven characters *shorter*, and carrying the rest of the line along with the edit slid columns 73-80 leftwards into the program text on 1,775 lines -- `NC1014.2` becoming code. Running every mutant through the same `normalize_fixed_format` the pipeline feeds `cobc` puts a verified floor under both: 1,580 of them (8.9% of the whole population) compiled something other than what their own report line described -- 546 with identification text leaked into the program, 1,209 with the statement's tail cut off; afterwards, none do. Both causes are now one `_rewrite_code` helper that rewrites strictly within columns 1-72 and re-pins the identification area at column 73, reclaiming the columns a longer verb needs from interior whitespace runs (never from the indent that decides Area A vs Area B, never from inside a literal -- which still recovers 287 of the 671 overflowing sites) and refusing the mutant outright when the line cannot give them up. (3) **`\b` word boundaries on the arithmetic verbs**: the same bug audit finding F8 fixed for `_EXCLUDED_VERBS`/`_SCOPE_TOKENS` was still live in `_ADD_TO`/`_SUBTRACT_FROM`/`_MULTIPLY_BY`/`_DIVIDE_INTO`/`_MOVE_INT`, so `\bADD\b` matched inside `GRP-FOR-ADD-CORR-R` and rewrote an ordinary `MOVE` to `MOVE GRP-FOR-SUBTRACT-CORR-R FROM ...` (102 occurrences); they now use the shared `_cobol_word()` helper like every other pattern in the module. (4) **`stmt-delete` on the head of a multi-line statement**: replacing `COMPUTE WS-AVG =` with `CONTINUE` strands its own second half, and replacing an `ADD` whose `END-ADD` is two lines down strands the scope terminator (135 occurrences). Deletion now requires the statement to provably end on its own line -- a trailing period, or a next code line that opens something new -- and refuses a line trailing off in a preposition. Also: fixed-format continuation lines (indicator `-`) are no longer treated as mutable code, and `PROCEDURE DIVISION` state is reset at `END PROGRAM`/a following `IDENTIFICATION DIVISION` so a second program's DATA DIVISION is not mutated as if it were procedural. Net effect on the same corpus: 621 sites are no longer offered as mutants at all, every remaining mutant compiles the program its own report line describes, and the Docker-gated integration fixture's pinned mutant population is unchanged.
- **`mockymock export` no longer refuses a line just because a quoted literal makes it overflow column 72 -- it continues the literal.** Reported from a real export of a 52-boundary program: after 50 refusals were worked around by shortening `.cut` text, two remained that no `.cut` edit could reach. They came from the program's own `DEBUT-WORKING-STORAGE` / `FIN-WORKING-STORAGE` storage-dump marker fields (declared, never referenced -- standard practice in IBM shops), whose `VALUE` clauses `splicer/reset.py` re-serializes into `UT-RESET-WORKING-STORAGE` as single-line `MOVE`s 85 columns wide. Unconditional -- it happens even with `--case` restricting the run to one `TESTCASE` -- and with no flag to skip it, so the only remedy was editing production COBOL to shorten a banner string. Now `mainframe_export.wrap_long_literal_lines` splits the literal across fixed-format continuation lines (`-` in the indicator area, the literal re-opened at column 12) leaving the statement and the literal's content byte-for-byte unchanged, and the new `fit_within_columns` sequences the two passes: generated `DISPLAY`s first (their byte-identical-stdout equivalence is what the `__MOCKYMOCK__` protocol rides on), then literal continuation over the residue, reporting only lines *neither* pass can fit. Every continued line is filled to exactly column 72 -- not cosmetic: a continued line's trailing blanks through column 72 are part of the open literal, so a short one silently pads the value with spaces (both directions verified against real GnuCOBOL 4.0 in fixed format, and pinned by `tests/integration/test_export_literal_continuation.py`). The same change fixes a second refusal with the same cause: a literal the *original* source already continued, which cobolparser's `normalize_fixed_format` collapses onto one long line. Still fail-closed for what cannot be continued -- no literal on the line, two literals (ambiguous), non-literal text that alone overflows, or a `CBL`/`PROCESS` directive. See `docs/2026-09-04-export-literal-continuation-design.md`.
- **`SET ADDRESS OF <item>` on a LINKAGE item folded into WORKING-STORAGE no longer fails the compile.** The ENTRY/LINKAGE neutralization exists to give a program's LINKAGE items real, addressable storage -- and that is exactly what makes rebinding their address illegal afterwards: GnuCOBOL rejects `SET ADDRESS OF X TO <ptr>` with `cannot change address of 'X', which is not BASED or a LINKAGE item`. On the IMS DL/I PSB-scheduling idiom (a `7000-SCHEDULE-PSB` paragraph doing this once per PCB/DIB mask) that is ~20 hard compile errors per program, all introduced by the fold itself. Marking the folded items `BASED` instead would restore the statement's legality by taking their storage away again -- the precise unbound-memory SIGSEGV the fold was built to prevent -- so the statement gives, not the storage: `splicer.linkage.redirect_address_of` rewrites each **receiving-side** `ADDRESS OF <folded item>` to a scratch `UT-ADDR-SINK USAGE POINTER`, space-padded to the identical width via `stub_writer.replace_columns` so no line and no column any AST location indexes into moves. The rebind is discarded, the `SET` keeps executing, and a sibling statement sharing the line is untouched. Value-side occurrences (`SET <ptr> TO ADDRESS OF <folded item>`) are deliberately left alone -- taking the address of a WORKING-STORAGE item is legal and stays correct after the fold. Detection is textual because cobolparser's `SetStatement` drops the target-side `ADDRESS OF` entirely (`SET ADDRESS OF X TO Y` and `SET X TO Y` both arrive as `targets=["X"]`), and anything it cannot classify or express as a single-line span -- an `ADDRESS OF` continued onto the next line, one with no `SET` on its own line -- is a new fail-closed `UNSUPPORTED_LINKAGE_ADDRESSING` refusal rather than a guess. Verified end to end against real GnuCOBOL 4.0: the rewritten program compiles, runs, and passes its test case; the un-rewritten one does not compile.
- **A VALUE clause holding a double quote generated an unterminated literal in `UT-RESET-WORKING-STORAGE`.** CICS's `DFHAID` copybook legitimately declares `DFHTRIG PIC X VALUE IS '"'` -- content: one quote character. cobolparser (through 1.8.0) re-quotes a decoded literal without doubling an embedded quote, so it arrived as three quote characters and the reset paragraph emitted `MOVE """ TO DFHTRIG`, desynchronizing `cobc`'s tokenizer for the rest of the program -- surfacing as a bogus `invalid symbol '%'` error two lines further on, nowhere near the cause. Fixed upstream (cobol-parser `_literals.quote_literal`), but the dependency floor is `cobol-parser>=1.7.7`, so `splicer.reset.cobol_literal` normalizes the clause here too: a run of quote characters is grown to the next even length, which repairs the malformed shape and is idempotent against the fixed parser. Verified against real GnuCOBOL 4.0.
- **`compile_source` couldn't compile real z/OS mainframe sources containing `EJECT`/`SKIP1`/`SKIP2`/`SKIP3` compiler-directing statements.** GnuCOBOL's default dialect doesn't implement those IBM listing directives at all, even though cobol-parser itself already treats them as no-ops (see its `EjectStatement`/`SkipStatement` AST nodes). Added `-std=mvs` to the `cobc` invocation in `docker_toolchain.py`, which GnuCOBOL does implement them under.
- **`find_goto_exit_plans`: transitive fallthrough chain among top-level GO-TO-exit paragraphs declined all at once (HIGH).** The function evaluated every exit-only-paragraph candidate against `_go_to_targets`/`_go_to_fallthrough_targets` computed ONCE, up front, from the raw whole-program GO TO set — so back-to-back validation paragraphs each with their own adjacent bare-EXIT label (`2211-VALIDER-MNT`/`2211-EXIT`, immediately followed by `2212-...`/`2212-EXIT`, and so on, chaining through ~20 paragraphs on a real program) were all declined together: neutralizing the first would have removed its exit label from `_go_to_targets`, un-marking the second as a fallthrough hazard and unblocking it in turn, but the single static pass never got to see that. Now iterates to a fixpoint — each round narrows `_go_to_targets` by every target confirmed in an earlier round, re-derives `_go_to_fallthrough_targets`, and re-evaluates every still-undecided candidate — until a round confirms nothing new, resolving the whole chain instead of declining it wholesale. Pinned by `tests/unit/test_goto_exit.py::test_find_goto_exit_plans_resolves_a_transitive_fallthrough_chain`.
- **Reachability gate: section-scoped GO TO fall-through false cascade (HIGH).** The "GO TO <own-exit-label>" idiom several validation paragraphs in the SAME SECTION each use as an early bailout to a shared, section-scoped exit label could not be neutralized by `find_goto_exit_plans` (its adjacency check only ever matches ONE of the several enclosing paragraphs, so its all-or-nothing rule declines the whole target), leaving `_reachable_paragraphs`/`union_executed_paragraphs` to model the un-neutralized exit label's fall-through as cascading past the section boundary into every paragraph physically after it — demanding mocks for boundaries a `PERFORM <section-name>`-entered test can never reach, hundreds of spurious `UNMOCKED_*` refusals on a real program. New `_fallthrough_safe_sections`/`_walk_fallthrough_from` recognize a SECTION provably entered only via `PERFORM <section-name>` and stop the fall-through walk at the section's own last paragraph instead of cascading past it — gate-only, `find_goto_exit_plans`/`find_terminator_plans` splice exactly as before. Pinned by `tests/unit/test_reachability_goto_exit_section_scoped.py`.
- **`linkage_plan`'s LINKAGE SECTION header line derivation.** `header_line` used to be computed as "one line before the first LINKAGE SECTION data item" — a workaround for a since-fixed cobolparser bug where a `DATA DIVISION` section reported its parent division's location instead of its own header token. On a real IMS PCB-mask LINKAGE SECTION (a boilerplate comment block before the first `01`-level item, as in `ACCTPRG`/`DEPTIMSM`-style programs), that derivation landed inside the comment block instead of on the header — measured to drift 12-14 lines on real-world programs — and `check_linkage_layout` correctly refused (`UNSUPPORTED_LINKAGE_LAYOUT`, "could not locate the LINKAGE SECTION header line") rather than comment out the wrong line, but that meant the ENTRY/LINKAGE neutralization feature never engaged for those programs. Now reads the LINKAGE SECTION's own `CobolSection.location` directly, which cobolparser has reported correctly since its "Section/Paragraph Location Tracking" fix. Pinned by `tests/unit/test_linkage.py`'s new comment-block regression cases.
- **Reachability gate: GO TO fall-through closure (HIGH).** `_reachable_paragraphs` stopped at a `GO TO` target, so a paragraph entered by falling off that target's end — ordinary sequential execution, which `union_executed_paragraphs`, the terminator guard, and cobolparser's `ProgramFlowAnalyzer` all already modeled — was invisible to the per-case mock gates: a `CALL`/file-op/`ACCEPT` there passed `lint`/`run` unmocked (exit 0) and executed for real at runtime. The BFS now closes over the fall-through hazard to a fixpoint via `_falls_through`, failing closed (`UNRESOLVED_FLOW_TARGET`) when paragraph source order is unverifiable or a GO TO target cannot be anchored in it. Pinned by `tests/unit/test_refusal_goto_fallthrough.py`.
- `mockymock generate --with-data --placeholder CATEGORY:KEY` (#47): downgrading a loop-driving boundary (a multi-row `READ`, a multi-row `SQL ... ROWS` cursor fetch) no longer leaves a DIFFERENT boundary's `VERIFY ... WAS CALLED n TIMES` pinned to the bundle's original, now-stale count when that other boundary is only reached from inside the same loop (e.g. a `CALL` made once per row) -- its VERIFY is demoted to a `*>` comment too, on the same "declared in the same paragraph as the downgraded boundary" heuristic.
- **`find_goto_exit_plans`: adjacency check broke on a phantom `"."` paragraph between enclosing and target.** cobolparser inserts an empty-artifact paragraph literally named `"."` for a bare `.` line sitting on its own between a paragraph's last statement and the next paragraph's header; `immediately_follows` required `target_idx == enclosing_idx + 1` exactly, so a phantom sitting between an otherwise-adjacent `GO TO`'s enclosing paragraph and its exit-only target broke the adjacency check and cascaded into declining that target and every paragraph transitively chained after it. `immediately_follows` now accepts any run of only phantom `"."` paragraphs strictly between the two, the same tolerance `_expand_thru_range` already applies elsewhere. Pinned by `tests/unit/test_goto_exit.py::test_find_goto_exit_plans_tolerates_a_phantom_paragraph_before_the_target`.

## [0.8.0](https://github.com/Landparty/mocky-mock/compare/v0.7.0...v0.8.0) (2026-09-04)


### Features

* **generate:** scaffold CAPTURE ARG, and synthesize the storage it needs ([25076e0](https://github.com/Landparty/mocky-mock/commit/25076e01911e569e165c8a7cf9677adf878434b9))
* **generate:** surface cobol-parser's unverified-scenario verdict in the generated .cut ([bec5a85](https://github.com/Landparty/mocky-mock/commit/bec5a85b02282396330820d270d6daaf3adafe23))
* lead coverage with the original program's number, gate CI on it, and explain stillborn mutants ([073d4f7](https://github.com/Landparty/mocky-mock/commit/073d4f7b9763b96e2725b947ac1d2e5cb4f9aea9))
* **mutate:** coverage gate and --jobs, the two mutation cost levers ([2127755](https://github.com/Landparty/mocky-mock/commit/212775556c6207588f671910b710ecca0dd94d7b))
* refuse or mock every COBOL dependency cobol-parser now parses ([0fc46f2](https://github.com/Landparty/mocky-mock/commit/0fc46f28a6ed2a5852874d85300b320646c215eb))


### Bug Fixes

* address four review findings on the capture/export/coverage work ([1a8daea](https://github.com/Landparty/mocky-mock/commit/1a8daea47cce20c57a29b980d899f94c36417879))
* correct VERIFY syntax in design note; cover all three exhaustion paths ([d343d9b](https://github.com/Landparty/mocky-mock/commit/d343d9b798e7ce0990b6fd4faf1011e47f6bbcd4))
* **export:** continue a long literal instead of refusing the line ([4c9838f](https://github.com/Landparty/mocky-mock/commit/4c9838fea95c2282d80723afcaf80551f73763d5))
* **export:** name the two literal-continuation failure modes apart ([26e3624](https://github.com/Landparty/mocky-mock/commit/26e36249ad669f015d801a7d9b63fa8f21f4d745))
* **export:** wrap over-long lines instead of refusing, and name the real overflow source ([c7fef8f](https://github.com/Landparty/mocky-mock/commit/c7fef8f920da5ae7ce395d1977d90755d1670159))
* **generate:** emit real READ exhaustion arms and stop dropping boundary stub expectations ([9fc8f7d](https://github.com/Landparty/mocky-mock/commit/9fc8f7d83eb57e041b8794fdfc1c9fc755a142e8))
* **generate:** replicate AT END SET &lt;88&gt; TO TRUE into READ mock exhaustion ([625eec0](https://github.com/Landparty/mocky-mock/commit/625eec0cdf627fd4a7cc3a77459afa0e3aa84e6b))
* **mutate:** stop generating mutants that cannot compile ([6ef9fee](https://github.com/Landparty/mocky-mock/commit/6ef9fee462cebede685d064220021f36faac89f5))
* **mutate:** type the stillborn reason as a literal, not a narrowed str ([b193603](https://github.com/Landparty/mocky-mock/commit/b1936032803b61f6c6ad8c44a04fc221a8dca1da))


### Documentation

* **mutate:** say what _sequence_area_end actually returns ([e63320a](https://github.com/Landparty/mocky-mock/commit/e63320abdcfcd415ec7967087bb892c4e4940359))
* record that generated scenarios never assert which branch they reach ([f45e228](https://github.com/Landparty/mocky-mock/commit/f45e2286a75cc87a5e77067318ebddaf95f97d3d))

## [0.7.0](https://github.com/Landparty/mocky-mock/compare/v0.6.4...v0.7.0) (2026-09-01)


### Features

* **cics:** synthesize DFHEIBLK EIB fields and generalize LINKAGE neutralization to no-ENTRY programs ([4623b25](https://github.com/Landparty/mocky-mock/commit/4623b254f6dcca13e48904b893b17aa9762afc89))
* consume cobol-parser from PyPI, publish mockymock to PyPI ([eb76616](https://github.com/Landparty/mocky-mock/commit/eb766167137343d08d4795c2253529c6cf765d0e))
* EXPECT negation and comparison operators in the .cut DSL ([97aaf0c](https://github.com/Landparty/mocky-mock/commit/97aaf0cd7e85088f646dad075607a42a475ac173))
* mock plain-file-form SORT/MERGE (USING ... GIVING ...) ([7872a68](https://github.com/Landparty/mocky-mock/commit/7872a68252773fdd61c3d64e49030658f9116fcf))
* mock SORT/MERGE (USING/GIVING form + RELEASE/RETURN) ([989784e](https://github.com/Landparty/mocky-mock/commit/989784e3d2f17a19da8f3df7f5230de8e0c7d3b2))
* mock SORT/MERGE's INPUT/OUTPUT PROCEDURE form via RELEASE/RETURN ([a32c20e](https://github.com/Landparty/mocky-mock/commit/a32c20ef8b4b4173d9d8bc6108177b41eddd621a))


### Bug Fixes

* **analysis:** resolve botched merge leaving stale refusal package ([d802f0c](https://github.com/Landparty/mocky-mock/commit/d802f0c3801e8878dc3c963d48703dccee919cc2))
* **analysis:** resolve transitive GO-TO-exit fallthrough chains to a fixpoint ([46aa88a](https://github.com/Landparty/mocky-mock/commit/46aa88a8f313053712b4a4d91414e24db1522caf))
* **analysis:** stop GO TO fall-through cascade past a safely-entered section ([63b8e69](https://github.com/Landparty/mocky-mock/commit/63b8e69b40bfce096364f163a98785250c1bfaea))
* **analysis:** stop GO-TO-exit fall-through cascade in reachability gates ([25965c0](https://github.com/Landparty/mocky-mock/commit/25965c099e8d3499ba34879ede51586486ae7a79))
* **cics:** COBOL-aware word boundaries and case-insensitive EIB/DFHCOMMAREA/DFHRESP matching ([cc07964](https://github.com/Landparty/mocky-mock/commit/cc07964f66a6d7a1e225f775d5d0d81da29eb1c0))
* correct project name in pyproject.toml ([e26373b](https://github.com/Landparty/mocky-mock/commit/e26373be1a1063579689ae854320f1490da91503))
* correct scenario_coverage documentation in scenario-generation.md ([2b2689f](https://github.com/Landparty/mocky-mock/commit/2b2689f419a2565ed24732c736f352ba85d0cb5a))
* disable test suite in CI due to long execution time ([930b391](https://github.com/Landparty/mocky-mock/commit/930b391736dc0c7e14f52eb93bb9b18bdcd235d3))
* **linkage:** read LINKAGE SECTION header line from CobolSection.location ([6d52232](https://github.com/Landparty/mocky-mock/commit/6d522326da3714596535cfc23261df3e023818d2))
* prevent recommending --scenarios branches when all arms are missed ([5ff55b6](https://github.com/Landparty/mocky-mock/commit/5ff55b607b598c447da2485c771ad3c56965cdbe))
* **refusal:** scope UNSUPPORTED_CICS_MACRO by reachability ([2df9002](https://github.com/Landparty/mocky-mock/commit/2df9002303946bbb098b62904c06b069f8b3722f))
* **refusal:** tolerate phantom "." paragraphs in goto-exit adjacency check ([c8124f7](https://github.com/Landparty/mocky-mock/commit/c8124f77fee8f4de41b0845fa051dc85fb545652))
* regenerate stale uv.lock pinning cobolparser to a July git SHA ([e305e1f](https://github.com/Landparty/mocky-mock/commit/e305e1f598fc289099e829a318d1ba2a621cba1b))
* **runtime:** add -std=mvs so cobc compiles EJECT/SKIP1-3 sources ([ecc7dbe](https://github.com/Landparty/mocky-mock/commit/ecc7dbeacf4de9ac410e8c2a9d40fef114c0b416))
* **splicer:** repair two compile-blocking codegen bugs from the corpus ([69ce403](https://github.com/Landparty/mocky-mock/commit/69ce403b849d04ff77e0de21f356dd5026f141b4))
* **splicer:** validate replace_columns' span against the line ([1a11c8b](https://github.com/Landparty/mocky-mock/commit/1a11c8bbce099362e458a0c87d42c71198eee9af))


### Performance Improvements

* **analysis:** remove the quadratic scans from the static-check pass ([cc1f17e](https://github.com/Landparty/mocky-mock/commit/cc1f17e2d2dd5bdd24b1a0ba1353fff25fc25304))


### Documentation

* add scenario-generation reference for the mockymock skill ([9cbd3c7](https://github.com/Landparty/mocky-mock/commit/9cbd3c7c91a4571f868868554b1a0e04307a81a6))
* fix OUT-boundary filter and overclaims in scenario-generation.md ([635fec3](https://github.com/Landparty/mocky-mock/commit/635fec32803b3ad7fe7bdcbc782f9d1ca40cccfe))
* teach the mockymock skill to reason about scenario generation ([e5f3b0e](https://github.com/Landparty/mocky-mock/commit/e5f3b0e04d77333b7f251ce5f032884abe98a68d))
* update OKF for scenario-generation skill enrichment ([98c54f5](https://github.com/Landparty/mocky-mock/commit/98c54f5d3385e10570cd98dbe57ef73eed77a305))

## [0.6.4](https://github.com/Landparty/mocky-mock/compare/v0.6.3...v0.6.4) (2026-08-14)


### Bug Fixes

* cache Nuitka onefile extraction across CLI launches ([2952a95](https://github.com/Landparty/mocky-mock/commit/2952a951fa35be09506d310d2c00b01be7112567))
* cache Nuitka onefile extraction across CLI launches ([6cd6f81](https://github.com/Landparty/mocky-mock/commit/6cd6f81e2afd0bb135d396a02e4f4aa9b252af75))

## [0.6.3](https://github.com/Landparty/mocky-mock/compare/v0.6.2...v0.6.3) (2026-08-13)


### Bug Fixes

* lead GO TO/fall-through terminator refusals with the COBOL cause, not the mechanism ([33f0c2f](https://github.com/Landparty/mocky-mock/commit/33f0c2ff5a13cbf2bc1e0b2ce0796b12ae5b8b21))

## [0.6.2](https://github.com/Landparty/mocky-mock/compare/v0.6.1...v0.6.2) (2026-08-13)


### Bug Fixes

* run reports on refusal/compile failure, add --timeout, fix fixture-bundle type gap ([c00c4d2](https://github.com/Landparty/mocky-mock/commit/c00c4d29dd76b24bece61208f290872c0fc9c071))

## [0.6.1](https://github.com/Landparty/mocky-mock/compare/v0.6.0...v0.6.1) (2026-08-12)


### Bug Fixes

* close the reachability BFS over GO TO fall-through ([b5301ce](https://github.com/Landparty/mocky-mock/commit/b5301ce2be1e04e93e8695ebecba2ae62e49f3e8))
* close the reachability BFS over GO TO fall-through ([162f205](https://github.com/Landparty/mocky-mock/commit/162f2050b5f2179448ed93cb6fb59431806d5815))
* key orphan-record skip diagnosis on (case_id, data_name) ([dc95c4d](https://github.com/Landparty/mocky-mock/commit/dc95c4d7fda5a70043acec47a6b899f4480214d4))
* remediate 19 of the 2026-08-12 audit's 20 findings, TDD at the pin ([a9c7ba6](https://github.com/Landparty/mocky-mock/commit/a9c7ba68d93ad14ebed76cd5def4d3c2a17e31ea))


### Documentation

* sixth framework audit — 20 new findings, none fixed ([04fccda](https://github.com/Landparty/mocky-mock/commit/04fccdaf6dd3c42ef2624c548fbbe5cda50072e7))

## [0.6.0](https://github.com/Landparty/mocky-mock/compare/v0.5.2...v0.6.0) (2026-08-11)


### Features

* add CAPTURE ARG &lt;n&gt; INTO &lt;target&gt; grammar to MOCK CALL bodies ([18b7ca7](https://github.com/Landparty/mocky-mock/commit/18b7ca785e19a69c0ae3f468f1fb15789142d865))
* refuse CAPTURE_ARG_OUT_OF_RANGE when a CAPTURE index exceeds a site's real USING-parameter count ([b8c6654](https://github.com/Landparty/mocky-mock/commit/b8c6654fa5db08984a3cd931e6e22fcba44ff8a1))
* splice CAPTURE ARG's resolved MOVE before a CALL/DYNCALL mock's body lines ([ff22fbb](https://github.com/Landparty/mocky-mock/commit/ff22fbb66943468fcacc620691c824be4e331639))


### Bug Fixes

* add fail-closed guard for malformed CAPTURE statements + test coverage ([c8da6fa](https://github.com/Landparty/mocky-mock/commit/c8da6fa9ea4bd9ea1bd004ddac05b41b49770f5c))
* check AMBIGUOUS_MOCK (and nested/layout checks) against every matching site program-wide ([3e0c286](https://github.com/Landparty/mocky-mock/commit/3e0c286164f968b22f8ca5ccd1333d183025057c))
* check AMBIGUOUS_MOCK against every matching site program-wide ([251d9e8](https://github.com/Landparty/mocky-mock/commit/251d9e87adff8d875d88d6e3835a98473acd2649))
* check CAPTURE_ARG_OUT_OF_RANGE against every matching site program-wide ([723079b](https://github.com/Landparty/mocky-mock/commit/723079bcc846f94d4ca8a85f7ffd7347b4fa35e1))
* handle oversized CAPTURE ARG index parse errors and align design doc semantics ([c45aad4](https://github.com/Landparty/mocky-mock/commit/c45aad49f0873de58fe5fda9a4c49d48da8e1fa4))
* resolve audit doc contradiction and refresh OKF timestamps ([95ff0fd](https://github.com/Landparty/mocky-mock/commit/95ff0fda6fb533f25d5d8ff57d6d243e561926ef))


### Documentation

* demonstrate CAPTURE ARG in the ordrproc worked example, proven via Docker ([b4cbb8a](https://github.com/Landparty/mocky-mock/commit/b4cbb8a3825006846dd225833302a02a66fedf87))
* document CAPTURE ARG argument capture across OKF bundle, AI skill, and audit doc ([a3fbcaf](https://github.com/Landparty/mocky-mock/commit/a3fbcaf76d560da57f1daf5a302dac4ca70bc9d5))
* mark argument capture closed in the 2026-08-10 framework audit roadmap ([513ba7a](https://github.com/Landparty/mocky-mock/commit/513ba7ab8b31762ed282202e2a47f5023ae1ad8b))

## [0.5.2](https://github.com/Landparty/mocky-mock/compare/v0.5.1...v0.5.2) (2026-08-11)


### Bug Fixes

* 47 stale downstream VERIFY counts, add [#48](https://github.com/Landparty/mocky-mock/issues/48) Docker coverage for READ ROWS/TERMINAL ([7e0ee64](https://github.com/Landparty/mocky-mock/commit/7e0ee64a878c844a05113b629d8bd3050cd5e399))
* Replace verbose Gotchas section with condensed pointer list to .okf/ ([b8696e5](https://github.com/Landparty/mocky-mock/commit/b8696e5100d9c3ba790b0b3394058e5469f9c6cf))
* Restore 6th gotcha (Docker tests) and use quote-based references instead of ordinals ([c7ec53f](https://github.com/Landparty/mocky-mock/commit/c7ec53ff94f825d969cfb6c91909372edc633c18))

## [0.5.1](https://github.com/Landparty/mocky-mock/compare/v0.5.0...v0.5.1) (2026-08-10)


### Documentation

* fix stale org references in install instructions ([a6bdab8](https://github.com/Landparty/mocky-mock/commit/a6bdab88cee56ebc3d9a0f319f8c9dace9b49a5c))
* fix stale present-tense claims and commit citation from prior pass ([4a13386](https://github.com/Landparty/mocky-mock/commit/4a13386bd783f3bf27f13e1a269052ca8b5b6236))
* fix whole-branch review accuracy defects vs sibling repo's actual workflow ([fda5926](https://github.com/Landparty/mocky-mock/commit/fda59265fdb449e53d72150fe92413e33b61fe18))
* update publishing docs for the retired standalone pipeline ([fd9a7b4](https://github.com/Landparty/mocky-mock/commit/fd9a7b4e645a798effe1d5222fede395c5365302))

## [0.5.0](https://github.com/samdion1994/mocky-mock/compare/v0.4.0...v0.5.0) (2026-08-07)


### Features

* add mockymock analyze passthrough to cobol-parser's CLI ([f43dc11](https://github.com/samdion1994/mocky-mock/commit/f43dc117bbf132dc2e79b67552c295fe378ac92c))
* **refusal:** narrow PARSE_WARNING/UNRESOLVED_COPYBOOK to paragraph scope ([ac17f9e](https://github.com/samdion1994/mocky-mock/commit/ac17f9e2f0b92273ca460cfaa0b768fb7bda5b95))


### Bug Fixes

* **mutation:** propagate scoped-refusal waiver notes through mutate ([cbcc6f9](https://github.com/samdion1994/mocky-mock/commit/cbcc6f929dc376ae282365171645ba61f501d9cc))
* **refusal:** add independent safety net for PARSE_WARNING line trust ([0260ea5](https://github.com/samdion1994/mocky-mock/commit/0260ea5b6468fe97e6fbb2a345ee1c4528a38ccf))
* **refusal:** verify a waivable COPY's span textually, not via PERIOD tokens ([7d3ce74](https://github.com/samdion1994/mocky-mock/commit/7d3ce74690abff17770f52c526d639707fcd5712))
* update second stale INVOKE fixture, drop dangling unused import ([bf1cabd](https://github.com/samdion1994/mocky-mock/commit/bf1cabd818662d997549d346756bd6cd3cbebf8b))
* update stale INVOKE unsupported-verb fixture to EXHIBIT ([6eabb5f](https://github.com/samdion1994/mocky-mock/commit/6eabb5fe42f88c1238e6c3fc63028380d0db13a3))

## [0.4.0](https://github.com/samdion1994/mocky-mock/compare/v0.3.0...v0.4.0) (2026-08-06)


### Features

* **cli:** --rows and --placeholder on generate --with-data (Task 4) ([8799281](https://github.com/samdion1994/mocky-mock/commit/879928121d2afc8eea1df4d6a0fd03490c5bb336))
* **cli:** add generate --with-data for bundle-driven .cut scaffolding ([19c2986](https://github.com/samdion1994/mocky-mock/commit/19c29866c9c2c72b458b85b66090caae9b7dfada))
* **cli:** add run --record-expectations for golden/characterization testing ([acb1663](https://github.com/samdion1994/mocky-mock/commit/acb1663ad97071e82609853b3f9884307fe495fb))
* **cli:** hand-port the `mockymock fixtures` subcommand ([c2ab4a8](https://github.com/samdion1994/mocky-mock/commit/c2ab4a86d6155dcd8c24e625dd87d568fa8e4c6f))
* **cli:** record-expectations golden mode + generate --with-data (gen-fixtures Phases 7b/8) ([e87c027](https://github.com/samdion1994/mocky-mock/commit/e87c0273351bb59b78cd04c7e3068b95d92088b2))
* **dsl:** ROWS on MOCK READ with optional TERMINAL group ([fce3f04](https://github.com/samdion1994/mocky-mock/commit/fce3f04246eb3b64c6c7093debd6a7a610c22bdc))
* **splicer:** READ ROWS dispatch with terminal branch + fail-closed refusal ([40ecbad](https://github.com/samdion1994/mocky-mock/commit/40ecbad9c99e99e140df4b49fd0bc3b45f3490cb))


### Bug Fixes

* **cli:** fixtures runs the same fail-closed gates as generate ([d0006b6](https://github.com/samdion1994/mocky-mock/commit/d0006b6255abc20c551c6d6ff1ad43b392e4c80d))
* **docs/tests:** fold in review round 1 findings for Task 5 ([07a8fbc](https://github.com/samdion1994/mocky-mock/commit/07a8fbc4db0128becd0eced97a38633f2dd433b0))
* **dsl:** preserve READ/SQL-ROWS loop-termination through --placeholder/--rows 0 ([8ccb590](https://github.com/samdion1994/mocky-mock/commit/8ccb590bad9be7eb8bbb7dd59cd4d3eaf705ed84))
* **dsl:** recompute VERIFY call_count for a downgraded loop-bearing boundary ([427474a](https://github.com/samdion1994/mocky-mock/commit/427474a2259d1e08ab0716635586749609494d77))
* **dsl:** replicate READ's AT END clause to prevent infinite loops ([3ad3378](https://github.com/samdion1994/mocky-mock/commit/3ad3378c76a6a764e70a3afb7202254129dea94d))
* **review:** PR [#46](https://github.com/samdion1994/mocky-mock/issues/46) post-review polish pass ([53669b4](https://github.com/samdion1994/mocky-mock/commit/53669b4b3f66f13fbbf0e3938b1184e72a693772))


### Documentation

* **plan:** record cobolparser pin amendment to ff64b25 (Task 1) ([957c4d9](https://github.com/samdion1994/mocky-mock/commit/957c4d9ed5ef7b943aa38b77efe424bb653e08b1))
* reconciliation plan -- port branch deliverables onto main's engine ([bc84332](https://github.com/samdion1994/mocky-mock/commit/bc8433270f35f69b81e9bb413440efe6551a2b29))
* **splicer:** note READ ROWS terminal resolution and the fail-closed guard's production invariant ([4463bf0](https://github.com/samdion1994/mocky-mock/commit/4463bf0a53dfbfae1c375e705e565566c7680351))

## [0.3.0](https://github.com/samdion1994/mocky-mock/compare/v0.2.0...v0.3.0) (2026-08-04)


### Features

* **cli:** add column-restoration and provenance-header helpers for mainframe export ([050e418](https://github.com/samdion1994/mocky-mock/commit/050e41870d2621ef95b114e763d9e23a85f41e4d))
* **cli:** add mockymock export for real fixed-format (z/OS) COBOL compiles ([60b19cf](https://github.com/samdion1994/mocky-mock/commit/60b19cf1c0a4ac15a183f25a134a735ef8aa52d7))
* **cli:** add mockymock export subcommand ([9437fd4](https://github.com/samdion1994/mocky-mock/commit/9437fd436d884496399cc048058fe1d3176b0674))
* **cli:** add preserve_compiler_directives option to run_static_checks ([3ccbc6b](https://github.com/samdion1994/mocky-mock/commit/3ccbc6be7ac6e83864f9a029895c8bd58cd59b64))
* **cli:** wrap over-72-column generated DISPLAY statements for mainframe export ([44a52a5](https://github.com/samdion1994/mocky-mock/commit/44a52a504c65efc6240a6a347233cd4bf6407fe9))


### Bug Fixes

* **cli:** address final whole-branch review findings for export ([5b125d1](https://github.com/samdion1994/mocky-mock/commit/5b125d159ef81ad4cd89d42cc48de2c68404b436))
* **cli:** clarify why the not-tail safety net isn't dead code ([b164e91](https://github.com/samdion1994/mocky-mock/commit/b164e910cb53428ee3decb01bda71fd5260b59fb))
* **cli:** rename ambiguous loop variable to satisfy ruff E741 ([2e124d3](https://github.com/samdion1994/mocky-mock/commit/2e124d3b4ae7b0f0a437f079b11b740f2983e61d))
* **tests:** stop hardcoding version in test_mockymock_has_a_version ([e50882a](https://github.com/samdion1994/mocky-mock/commit/e50882a83c30d92252e70023eb3f9d7cd46af013))


### Documentation

* add mainframe (z/OS) export command design ([a2dd00a](https://github.com/samdion1994/mocky-mock/commit/a2dd00a6c85c16c898c63847297a8476a3203b6d))
* correct stale algorithm claims after chunking redesign ([d79accc](https://github.com/samdion1994/mocky-mock/commit/d79accc363c39c2738fe44f78d0aa8d39d465f74))
* document mockymock export in the OKF bundle and README ([6bf9685](https://github.com/samdion1994/mocky-mock/commit/6bf9685e0a6ca8f33a8121c643a10740f38c4cdd))
* revise export command design after empirical column spike ([bf2de7f](https://github.com/samdion1994/mocky-mock/commit/bf2de7f67f86f504e0dcc0aeb4bb68294082884d))

## [0.2.0](https://github.com/samdion1994/mocky-mock/compare/v0.1.1...v0.2.0) (2026-08-03)


### Features

* **cli:** add `mockymock dashboard`, a local toolchain status page ([ff151e5](https://github.com/samdion1994/mocky-mock/commit/ff151e578c79ccaa4dcb2afd01d85b75b5a49b84))
* **cli:** add `mockymock dashboard`, a local toolchain status page ([557d0a8](https://github.com/samdion1994/mocky-mock/commit/557d0a8a6185a2b388b4f5b11d956412f124c9e4))


### Documentation

* **okf:** document the v0.1.0 asset-loss/v0.1.1 recovery and its two root causes ([d03f634](https://github.com/samdion1994/mocky-mock/commit/d03f634569adb35734a38ffff74a4e4d5162a36b))

## [0.1.1](https://github.com/samdion1994/mocky-mock/compare/v0.1.0...v0.1.1) (2026-08-03)


### Bug Fixes

* **release:** remove stale release-as pin from release-please-config ([2c08bd2](https://github.com/samdion1994/mocky-mock/commit/2c08bd2187ccb18fbcf19bf2069e3ee7c69cdadf))


### Miscellaneous Chores

* force a release to ship v0.1.0's CI-fixed binaries ([02a5246](https://github.com/samdion1994/mocky-mock/commit/02a524633f163bf6ab671ed25300e2e0e4422ee7))

## 0.1.0 (2026-08-03)


### ⚠ BREAKING CHANGES

* remove local cobc toolchain; all compile/run goes through Docker

### Features

* .cut DSL model and parser ([7ef2fbc](https://github.com/samdion1994/mocky-mock/commit/7ef2fbc6c53996a8e3258ad0dc223630d0cc2674))
* .cut DSL parses PERFORM &lt;target&gt; THRU &lt;endpoint&gt; ([930ce61](https://github.com/samdion1994/mocky-mock/commit/930ce61d20504c4c5e36a06f3744fbc7cf4e4467))
* add BEFORE-EACH/BEFORE-ALL mock scoping to the .cut DSL ([49210ca](https://github.com/samdion1994/mocky-mock/commit/49210ca3d979103814db5e778d232135dfc10497))
* add DEPTMQC example with MQ consumer logic and related copybooks ([50fff6a](https://github.com/samdion1994/mocky-mock/commit/50fff6a5a2f4cb0e15d4aa2b404f799e6d069092))
* add FILE-STATUS IS sugar to the .cut DSL ([347fbf1](https://github.com/samdion1994/mocky-mock/commit/347fbf1ce51f211b6d94865aabe3b574059765d5))
* add terminator reachability primitives + span/line validation ([b35b4ab](https://github.com/samdion1994/mocky-mock/commit/b35b4abee01e19d8ad26920e044caada4efaa83a))
* **analysis,splicer:** support IMS DL/I ENTRY/LINKAGE programs instead of crashing ([7bb9004](https://github.com/samdion1994/mocky-mock/commit/7bb9004f92071135c3fac2c55453470e891b24f0))
* **analysis:** add whole-program safe-section-entry detection ([60b8894](https://github.com/samdion1994/mocky-mock/commit/60b8894994fd87446d7d99a2d8095fd0c1b6c7b3))
* **analysis:** classify STOP RUN/GOBACK as detected terminator sites ([aaee393](https://github.com/samdion1994/mocky-mock/commit/aaee3938ef3664f27b42b1bcbcffac6ae8c49d87))
* **analysis:** classify STOP RUN/GOBACK as detected terminator sites ([5f2c70b](https://github.com/samdion1994/mocky-mock/commit/5f2c70b9c1f3cf3fe88a025a63dcb15906640575))
* **analysis:** classify STOP RUN/GOBACK as detected terminator sites ([dba4da6](https://github.com/samdion1994/mocky-mock/commit/dba4da6ee5e3a19061f78e0b26265e5866ad77b3))
* **analysis:** follow conditionally-nested intermediate PERFORM edges ([ec05b32](https://github.com/samdion1994/mocky-mock/commit/ec05b3264e2cb457961d826e641d8780ce047634))
* **analysis:** recognize safe SECTION-scoped terminators in find_terminator_plans ([c0773a8](https://github.com/samdion1994/mocky-mock/commit/c0773a826fcf815b15c67417f2431e5e989acb60))
* **analysis:** resolve safe section entries in the safe-chain BFS ([3ccccea](https://github.com/samdion1994/mocky-mock/commit/3cccceaded7c6a7d7ad66bdaf6d095eefc13c152))
* **analysis:** safe-chain terminator detection + UNSUPPORTED_TERMINATOR_LAYOUT ([e3aee11](https://github.com/samdion1994/mocky-mock/commit/e3aee114327ef0c914b155aa7f42f0f58b235054))
* auto-scaffold starter .cut files from the mock surface ([9f76605](https://github.com/samdion1994/mocky-mock/commit/9f766054179e61d19ded06e9356ce97e503edc08))
* category-generic DSL (MOCK/VERIFY for file ops, SQL, CICS, DLI, ACCEPT, MQ) + generalized dispatch/driver codegen ([74ea3a8](https://github.com/samdion1994/mocky-mock/commit/74ea3a81fb3e8fe4979fe8334d4e35033c8368ea))
* CLI setup/run drive the Docker toolchain, fail loudly without Docker ([b886551](https://github.com/samdion1994/mocky-mock/commit/b88655169d16a92c49a4dad9f9eb00e9a043f228))
* **cli:** add --keep-sandbox and --verbose for run debugging ([94ef581](https://github.com/samdion1994/mocky-mock/commit/94ef5819f93625b0c4dccd08943b627fcf49689e))
* **cli:** add --trace and --trace-json to run ([b52f199](https://github.com/samdion1994/mocky-mock/commit/b52f1998790db49903ae7531ed6d7d731fa96055))
* **cli:** improve cross-platform reliability and add regnavg example ([4ee0fd5](https://github.com/samdion1994/mocky-mock/commit/4ee0fd5452e6feeb402d880bf3ba4ba103dec76a))
* **cli:** support test cases whose PERFORM target reaches a terminator ([a707572](https://github.com/samdion1994/mocky-mock/commit/a707572326ebd12d85ded1389090af469352f92a))
* **cli:** thread --copybook-path into EXEC SQL INCLUDE resolution for run ([c759c36](https://github.com/samdion1994/mocky-mock/commit/c759c36760c76eb5c916e69872224ced540b2069))
* **cli:** wire the debug subcommand into mockymock, add end-to-end test ([eac848b](https://github.com/samdion1994/mocky-mock/commit/eac848b6f3fb39d3bada41689dd87ab1ae99ac0f))
* comment-and-replace statement span surgery ([4179a0c](https://github.com/samdion1994/mocky-mock/commit/4179a0c4d81677ed17caf826a0b7807fe8d72a79))
* **coverage:** add DEPTIMSM example, proven end-to-end with --coverage ([8627aa9](https://github.com/samdion1994/mocky-mock/commit/8627aa9b55d62b74ba5f7caaf0ed8a6b757b3383))
* **coverage:** compile_source gains a coverage flag ([1a7ff6e](https://github.com/samdion1994/mocky-mock/commit/1a7ff6e315d0784164192cae3f218912fe6d7000))
* **coverage:** parse and format gcov's per-line COBOL coverage output ([dff5c98](https://github.com/samdion1994/mocky-mock/commit/dff5c98b375c662bb1ff5af83991e3d14e401d3d))
* **coverage:** run_gcov executes gcov inside the mockymock-cobc container ([6f4c89f](https://github.com/samdion1994/mocky-mock/commit/6f4c89f01f5ab3488fe4791292b43e0512471073))
* **coverage:** wire --coverage/--coverage-out into mockymock run ([fb7acbc](https://github.com/samdion1994/mocky-mock/commit/fb7acbcef00757a9a72e7b73a67068a2b742041c))
* DATA DIVISION EXEC SQL transform — generated SQLCA, DECLARE stubs, fail-closed INCLUDE ([aaa1ef8](https://github.com/samdion1994/mocky-mock/commit/aaa1ef805ca4b5a999ab5712eddff117d12cecd5))
* **debug:** add bidirectional line mapping for breakpoints ([28c01f2](https://github.com/samdion1994/mocky-mock/commit/28c01f20193e45e64b1bd4537e67738e26e745db))
* **debug:** add DAP adapter on stdio ([01a599e](https://github.com/samdion1994/mocky-mock/commit/01a599ed902024fa728dd564d2f7ac0b45fe31f4))
* **debug:** add GDB/MI session wrapper with coalesced stepping ([13b7344](https://github.com/samdion1994/mocky-mock/commit/13b73440cb683a63c8e0251c8662bb89138e4800))
* **debug:** map COBOL data items to gdb expressions via .c.l.h ([a9ebb91](https://github.com/samdion1994/mocky-mock/commit/a9ebb91d632790acf48f4e14d4ed13e7fe2bdd56))
* **debug:** synthesize the COBOL call stack from GnuCOBOL's frame_stack ([fa917ef](https://github.com/samdion1994/mocky-mock/commit/fa917ef384f7e7394010a062942d96a6d6456b25))
* docker exec-based compile_source ([08fb1c4](https://github.com/samdion1994/mocky-mock/commit/08fb1c41802c52e790ff732311373bcdf82768f0))
* docker exec-based run_binary with container-side timeout ([8af9395](https://github.com/samdion1994/mocky-mock/commit/8af9395af2b690473424ed9d3f020889d6ed30b8))
* Docker toolchain skeleton — image, constants, path mapping ([8bbcd7d](https://github.com/samdion1994/mocky-mock/commit/8bbcd7da7b976793a05619ecd668fb41f7f2bf52))
* driver emits PERFORM ... THRU for range entry points ([3d88412](https://github.com/samdion1994/mocky-mock/commit/3d88412b4891ff0390ad35cbcc6a3053669015a3))
* **dsl:** add MOCK SQL ... ROWS grammar for cursor row sequences ([1bc6fe8](https://github.com/samdion1994/mocky-mock/commit/1bc6fe8d8ca979d132bc413b32e314480e8755e9))
* enhance Windows compatibility and error handling in mockymock ([1e88abd](https://github.com/samdion1994/mocky-mock/commit/1e88abd88f5e28c803abcbb6d62c7c60b2be3349))
* ensure_toolchain() brings up the GnuCOBOL container idempotently ([eea320c](https://github.com/samdion1994/mocky-mock/commit/eea320c9867508a311289309dc29f634cdd2a4fa))
* **examples:** add CICS and dynamic-CALL routing worked examples ([279fb63](https://github.com/samdion1994/mocky-mock/commit/279fb6376db46e2313f273fd9c90dad28b799404))
* **examples:** add CUSTPROG and CLAIMSEG examples and improve discoverability ([6de2d5f](https://github.com/samdion1994/mocky-mock/commit/6de2d5f7f9ccf45c5075d9ac750a8b3214746da1))
* expand USING PROVIDER TESTCASEs into one case per row ([9073baa](https://github.com/samdion1994/mocky-mock/commit/9073baaa814506517c8fda40c728ff46bb4e25c0))
* extract declared FILE STATUS fields from FILE-CONTROL ([6559f97](https://github.com/samdion1994/mocky-mock/commit/6559f97d553edd51819ae13908f0b4a5a90be5ff))
* generate TESTSUITE/TESTCASE driver paragraphs ([fc49a41](https://github.com/samdion1994/mocky-mock/commit/fc49a410564bad78695177a8d4c0855d9a080ccc))
* GnuCOBOL bootstrap and mockymock setup command ([8938b17](https://github.com/samdion1994/mocky-mock/commit/8938b1726f96002739edf286a5381ca79ac62f46))
* Initialize mocky-mock OKF Bundle and add core documentation ([9369ac0](https://github.com/samdion1994/mocky-mock/commit/9369ac016c383d4a7b2bfbb3e2043f2da472fe08))
* inject default-success and FILE-STATUS IS overrides at splice time ([7b54dea](https://github.com/samdion1994/mocky-mock/commit/7b54dea14f2498a12a5695750e0e70a79056ef2a))
* INVUPDT all-boundaries example + integration tests; escape quotes in driver DISPLAYs; docs ([6ab4953](https://github.com/samdion1994/mocky-mock/commit/6ab4953e6a3e6e8bae723e0ce89918de739c8fe7))
* make mockymock installable via uv from anywhere ([de6ad0d](https://github.com/samdion1994/mocky-mock/commit/de6ad0d913bfd3765169c939101fbf3f281a40f0))
* merge per-testcase MOCK CALL bodies into EVALUATE dispatch ([ceb6c1f](https://github.com/samdion1994/mocky-mock/commit/ceb6c1f917a64632465cd2af218efb82a9f55dfe))
* mock dynamic CALLs by the identifier they call through ([34efb56](https://github.com/samdion1994/mocky-mock/commit/34efb56052fe0527daf78b1d41c79c90abd5d1ca))
* mock internal flow targets with MOCK PARAGRAPH / MOCK SECTION ([6233915](https://github.com/samdion1994/mocky-mock/commit/6233915639e7507e0ed54d149e9124f17b527d95))
* mock surface analyzer classifies static/dynamic CALL and detects file/EXEC ([dd77152](https://github.com/samdion1994/mocky-mock/commit/dd771520ceede6a8eb5cc64d807fbad24fbd0b4f))
* mock surface records per-site BoundarySite inventory for every category ([7c482bc](https://github.com/samdion1994/mocky-mock/commit/7c482bc3c822715f4729964a8704901a39e8d55f))
* mutation testing v1 (mockymock mutate) ([56a2006](https://github.com/samdion1994/mocky-mock/commit/56a200619faaf28b91a9dcaee76b6df7d4b4a424))
* ORDRPROC worked example and end-to-end capstone test ([42fb8a0](https://github.com/samdion1994/mocky-mock/commit/42fb8a029fb98122300cfa22211c240b71291806))
* parse __MOCKYMOCK__ stdout output into structured results ([d441e1d](https://github.com/samdion1994/mocky-mock/commit/d441e1d61237255da4da0af670ab76f3d99aa13e))
* parse PROVIDER/HEADER/ROW data-table blocks in .cut files ([9394a55](https://github.com/samdion1994/mocky-mock/commit/9394a552a331c6baeb5dcf594567369e4a05a041))
* per-site splice orchestrator + CLI run pipeline for all categories ([6d99206](https://github.com/samdion1994/mocky-mock/commit/6d99206602ec52226747468fb73c81782c32ad60))
* per-testcase and whole-program refusal gate ([a1d76f4](https://github.com/samdion1994/mocky-mock/commit/a1d76f41b52f16fd6042f30d944baff3c9e3e82b))
* pytest-grade CLI surface -- lint, collect, --case/--tag, JSON report, original-line coverage ([0e4ba33](https://github.com/samdion1994/mocky-mock/commit/0e4ba3353abc754e43368b4ae1708c9a254f990c))
* range-expand PERFORM THRU in reachability; narrow UNSUPPORTED_PERFORM_THRU to degenerate ranges ([8bf42c3](https://github.com/samdion1994/mocky-mock/commit/8bf42c3de954bb32bf9a41155175325b6c8378a3))
* refusal gate matches directives to boundary sites across all categories ([9640a9b](https://github.com/samdion1994/mocky-mock/commit/9640a9b906752701fb5466130d5914efb34e8407))
* refusal gate narrows nested refusals to unspliceable layouts ([b33e91d](https://github.com/samdion1994/mocky-mock/commit/b33e91dd0df16338c6614b1c62e2b27730e627fc))
* **refusal:** refuse on cobolparser dropped-content and lossy-decode warnings ([4da9fa5](https://github.com/samdion1994/mocky-mock/commit/4da9fa5f4349b1d8355a347bc9b7c9dec0772ca3))
* refuse FILE-STATUS IS on a file with no declared status field ([c01f324](https://github.com/samdion1994/mocky-mock/commit/c01f3247a976078ebeb6c5c0e6a19325122fdad6))
* remove local cobc toolchain; all compile/run goes through Docker ([f1aa83c](https://github.com/samdion1994/mocky-mock/commit/f1aa83cf35ed91151eae1262566d54b24be0baee))
* **report:** add trace parser and trace-JSON contract ([2e7459a](https://github.com/samdion1994/mocky-mock/commit/2e7459a7e50be0cd0fd5712579d77236900cd058))
* **report:** parse __MOCKYMOCK__ MOCK markers into TestResult.mock_hits ([8782884](https://github.com/samdion1994/mocky-mock/commit/8782884ddcc51789842716c13bf9bc6a2be537be))
* repository skeleton with cobolparser dependency ([9066c7b](https://github.com/samdion1994/mocky-mock/commit/9066c7b1cec75283b9465b94a7c11930ab1dfe9d))
* **runtime:** compile with -ftraceall and enable COB_SET_TRACE into the sandbox ([24e1b26](https://github.com/samdion1994/mocky-mock/commit/24e1b26199ca6f633fb53d16ed78caea90d537ff))
* **runtime:** compile with -g and start a long-lived gdb MI session ([c703f41](https://github.com/samdion1994/mocky-mock/commit/c703f41280bf8bce1e7a3ca4d3d4df9615b335a1))
* sandbox_dir accepts a root so sandboxes can live under the Docker mount ([a046b7a](https://github.com/samdion1994/mocky-mock/commit/a046b7a13b6404177a39269258e8a17a24f27051))
* scaffold + CLI wire nested-site annotation through generate/run ([e6d006d](https://github.com/samdion1994/mocky-mock/commit/e6d006d856bbc2e59d032f51a19369044f7f1974))
* scaffold generator covers every mockable category, labels MQ, unique SQL prefixes ([f52f990](https://github.com/samdion1994/mocky-mock/commit/f52f9905793ae60817524a972e2400b632733b77))
* scope map + nested-site span annotation in source_map ([a6ff06f](https://github.com/samdion1994/mocky-mock/commit/a6ff06f4b1b9aff473038876c24aaee4028c5f2c))
* SECTION-scoped terminator support (narrow shape) ([ab9e3b4](https://github.com/samdion1994/mocky-mock/commit/ab9e3b49a64b8a9a2a13163380087812bd7903f3))
* splice nested boundary sites at their annotated spans ([9e43755](https://github.com/samdion1994/mocky-mock/commit/9e43755b75a35474918c1d9a411d155c2fb256f7))
* **splicer:** add insert_lines_after primitive ([e017183](https://github.com/samdion1994/mocky-mock/commit/e017183b91c4f5ab9f4303e42f58f7a99347eee5))
* **splicer:** codegen ROWS mocks as a tally-driven EVALUATE block ([fc29cca](https://github.com/samdion1994/mocky-mock/commit/fc29cca0b42b5d4ba46dd8b81d00c1d033404fe6))
* **splicer:** declare and reset UT-EARLY-EXIT per test case ([7b54413](https://github.com/samdion1994/mocky-mock/commit/7b54413c339695cc61751a5119c7b9d04c848c87))
* **splicer:** emit __MOCKYMOCK__ MOCK markers in trace mode ([4bbb2bb](https://github.com/samdion1994/mocky-mock/commit/4bbb2bb8c47fee84f087cc58cd2d10fe29e09a8d))
* **splicer:** emit EXIT SECTION for section-scoped terminator plans ([30e5152](https://github.com/samdion1994/mocky-mock/commit/30e5152625d1776e30659d5ad0ec8e6b1e9a0b7b))
* **splicer:** include actual values in EXPECT/VERIFY failure messages ([b2c52be](https://github.com/samdion1994/mocky-mock/commit/b2c52bec071c3a6ab14eef606e26dc9bd61996b3))
* **splicer:** resolve EXEC SQL INCLUDE host-variable copybooks via --copybook-path ([0499c72](https://github.com/samdion1994/mocky-mock/commit/0499c72e3c33055e7bf046161eb30b9249f1cea0))
* **splicer:** splice terminator neutralization + chain-check insertions ([76c2773](https://github.com/samdion1994/mocky-mock/commit/76c277395c5146ea006109a37d86af03d4f0bfa7))
* **splicer:** terminator neutralization + chain-check codegen ([95fb1a7](https://github.com/samdion1994/mocky-mock/commit/95fb1a739949e5051eab28b4ab07c903ab0ef644))
* statement span detection via sorted boundary markers ([896d983](https://github.com/samdion1994/mocky-mock/commit/896d983cfc69b38b5cc8356954c91018feecf0f9))
* track nested_in_boundary ancestry + annotation fields on BoundarySite ([62a48c0](https://github.com/samdion1994/mocky-mock/commit/62a48c0f605edff9f002eb3fc776017375141be9))
* walking skeleton proves compile+run loop against real cobc ([79d7853](https://github.com/samdion1994/mocky-mock/commit/79d7853f4239833628785a75a9fba0a6ebf0c712))
* wire copybook expansion into generate and run ([3e9f6f1](https://github.com/samdion1994/mocky-mock/commit/3e9f6f1165f1740bbdef55e0e76061f7900ec9bc))
* wire generate and run subcommands end to end ([dc21e0b](https://github.com/samdion1994/mocky-mock/commit/dc21e0bcfbc5a7cd0300e36ec680793257eb5678))
* working-storage reset generation for test-case isolation ([35bf83a](https://github.com/samdion1994/mocky-mock/commit/35bf83abab42eb3bfc4c8a780e4c3ea6e28e4936))


### Bug Fixes

* address whole-branch review findings for BEFORE blocks + FILE-STATUS ([4e0185a](https://github.com/samdion1994/mocky-mock/commit/4e0185aaf8418786e8f716383ec73c06a3152d0a))
* **analysis:** address Task 3 review nits in find_terminator_plans ([8b8378d](https://github.com/samdion1994/mocky-mock/commit/8b8378df9d8d8b042a5865eab9073d40bcbee674))
* **analysis:** refuse terminators reached only via a looping PERFORM ([524a72e](https://github.com/samdion1994/mocky-mock/commit/524a72e7b508878b48e31566e161e4202aaf5a3e))
* **analysis:** refuse terminators reached via GO TO fall-through ([57526fc](https://github.com/samdion1994/mocky-mock/commit/57526fcefd87e1b4415855b6304ab5a1d44126ec))
* **analysis:** refuse terminators reached via GO TO fall-through ([8fa96ec](https://github.com/samdion1994/mocky-mock/commit/8fa96ec77b797da03f4870dd9bc9e9c8598f5bc7))
* bound compile_source docker exec with a host-side timeout ([f677a4a](https://github.com/samdion1994/mocky-mock/commit/f677a4aaf8a3d3e4a6aeb6963b10c367018b1bf9))
* bundle Dockerfile inside the package so `uv tool install` works ([34caac6](https://github.com/samdion1994/mocky-mock/commit/34caac63c09139e26af7bb222fbf46c3772d0e6a))
* catch subprocess.TimeoutExpired/FileNotFoundError in run_binary ([c82ffe7](https://github.com/samdion1994/mocky-mock/commit/c82ffe7265574d2b5c9e3e4b5340434a9b3a3784))
* **cli:** print individual parse errors in run; correct refusal docstring ([48992b1](https://github.com/samdion1994/mocky-mock/commit/48992b111d8bdcc74a756ccfa374fed13a749356))
* **cli:** retain sandbox for --verbose so the printed path is actionable ([f862c89](https://github.com/samdion1994/mocky-mock/commit/f862c89b2a750fca9bd8da4da7de93819652af26))
* **cli:** strip PROCESS/CBL precompiler directives before compiling ([aebc242](https://github.com/samdion1994/mocky-mock/commit/aebc242b135eeabff7f8ca6ef3846e2885a7e34a))
* close silent-gap findings in report layer, DSL, and CLI report writes ([988c814](https://github.com/samdion1994/mocky-mock/commit/988c814a59ada5a088e619f4d87baa6c263b3fc9))
* correct PROVIDER grammar diagram order in dsl.md (after TESTSUITE, not before) ([04a215c](https://github.com/samdion1994/mocky-mock/commit/04a215c71a90034d9c36fd3574194c1f6da07c70))
* **coverage:** compile_source pins the container working directory ([dee5934](https://github.com/samdion1994/mocky-mock/commit/dee59346d2e0ebd5a0609dee0101366502f355f6))
* **debug:** harden MI parser, honor setBreakpoints replace, guard dispatch ([2428c36](https://github.com/samdion1994/mocky-mock/commit/2428c36a998c2380464a9cc266ddcc9ca47b5706))
* **debug:** implement evaluate handler and improve step coalescing ([60f62c6](https://github.com/samdion1994/mocky-mock/commit/60f62c637ffa8df7abe830b377e3e9d0dab32154))
* **deps:** bump cobolparser pin to b130ec8; adapt UNRESOLVED_COPYBOOK to structured COPY warning ([ca39671](https://github.com/samdion1994/mocky-mock/commit/ca39671799acd866af754e14718be4e479953e3e))
* **deps:** bump cobolparser pin to b3e81ed (PR [#89](https://github.com/samdion1994/mocky-mock/issues/89) review fixes) ([cca9991](https://github.com/samdion1994/mocky-mock/commit/cca999126a8a458a041c96d63e4b4f86f0890af4))
* **deps:** bump cobolparser pin to c9a9499, fix statement_span blank-line trim ([d8fd9cb](https://github.com/samdion1994/mocky-mock/commit/d8fd9cbe8812e9342f768b40fe608d71b1b2a894))
* **deps:** bump cobolparser pin to c9a9499, fix statement_span blank-line trim ([19e388f](https://github.com/samdion1994/mocky-mock/commit/19e388fa1a79b1286dd83c6926034d4e9125f2ee))
* **deps:** bump cobolparser pin to d2bc7c2, fixes NIST IC101A/IC116M ([1086ba1](https://github.com/samdion1994/mocky-mock/commit/1086ba1283addc9e4e43cde695f5445b1bcedfc7))
* drop deprecated license classifier that breaks pip install ([61959e7](https://github.com/samdion1994/mocky-mock/commit/61959e7eeda7c5d2bc2a0818626a8ce76773f54d))
* **dsl:** raise on unterminated MOCK body instead of swallowing file ([6eb371b](https://github.com/samdion1994/mocky-mock/commit/6eb371b5e81cff39f2125c4e4117f4ae2c214195))
* **dsl:** reject duplicate PERFORM in a single TESTCASE ([4385223](https://github.com/samdion1994/mocky-mock/commit/4385223d298ac7c9badb07edda6df3a3f6f22880))
* **dsl:** support subscripted table names in EXPECT/MOVE directives ([aecf9a2](https://github.com/samdion1994/mocky-mock/commit/aecf9a2a7dad8d6e49e609929b903e7562105828))
* **examples:** ACCTPRG.cut mock READ set a field the splice removes ([31ef2c6](https://github.com/samdion1994/mocky-mock/commit/31ef2c604cbf17b7d5bd0d6094032440d94d8f8b))
* guard publish-public.yml's tag resolution against bad/missing manifest data ([b371c2f](https://github.com/samdion1994/mocky-mock/commit/b371c2f400e7cd383ab9ac624adf0490764e2f01))
* JUnit XML failures attribute counts failed cases, not failed checks ([26a0fe5](https://github.com/samdion1994/mocky-mock/commit/26a0fe586f432b4a32cd4cc61f4940e76918171e))
* main was broken (unresolved merge markers) + all 24 examples now pass ([cc05ee3](https://github.com/samdion1994/mocky-mock/commit/cc05ee354ab672a105d0f49d11773802ad4e1cba))
* **plan:** Task 1 must also exclude terminator labels from check_test_case's SORT/MERGE catch-all ([374998e](https://github.com/samdion1994/mocky-mock/commit/374998e48ae2e2fda9a519981a5e1ea19a98a32b))
* **plan:** Task 1 review found two more consequences of the new labels ([ac8e1df](https://github.com/samdion1994/mocky-mock/commit/ac8e1dfbc8051e7f49f0efc0505b5d6948092f28))
* **plan:** wire up terminator-own-span and chain-line-ownership checks ([3f95682](https://github.com/samdion1994/mocky-mock/commit/3f9568244f778c075ffac2b384acfd655f89aed2))
* recurse into nested statement bodies and refuse PERFORM THRU in reachability BFS ([23d2697](https://github.com/samdion1994/mocky-mock/commit/23d2697dde50cc1c6f3ef0565a1ab3939f0db9a9))
* recurse into nested statement bodies in mock surface analysis ([5144ba2](https://github.com/samdion1994/mocky-mock/commit/5144ba25cb8790a6591b85b0db3cfa859ff78c98))
* refuse empty PROVIDER row values; document mock-directive aliasing ([9d5bf87](https://github.com/samdion1994/mocky-mock/commit/9d5bf8709c1fdc46c00c27b6fb3740f7facf5cd1))
* refuse malformed FILE-STATUS lines instead of splicing them verbatim ([4aeec1d](https://github.com/samdion1994/mocky-mock/commit/4aeec1de6b3ec69f9987a265d522b3163d79c6cf))
* refuse MOCK CALL targeting a nested (unsplicable) call site ([ef66795](https://github.com/samdion1994/mocky-mock/commit/ef667957349f4ffc5c49dc4fe7499f65123abfd3))
* refuse stray statements inside an open PROVIDER block ([9880583](https://github.com/samdion1994/mocky-mock/commit/98805833382cecf2d8e6345ffa10aa19f66fd052))
* refuse unmocked reachable static CALL sites (UNMOCKED_CALL) ([5ed3ac0](https://github.com/samdion1994/mocky-mock/commit/5ed3ac095b2b53c76cc3ae9032fa7294c47a19cb))
* refuse unresolved COPY statements (UNRESOLVED_COPYBOOK) ([6cd994f](https://github.com/samdion1994/mocky-mock/commit/6cd994fd72f708d69a6a8081dea55bc8c8da8da0))
* reject BEFORE-ALL/BEFORE-EACH opening while a prior before-block is unterminated ([beb963f](https://github.com/samdion1994/mocky-mock/commit/beb963f6adf441a75d6979c3ca15a71e2eaee907))
* rename duplicate-case-start "first name" to "previous name" ([669a871](https://github.com/samdion1994/mocky-mock/commit/669a871e6278781af69f87c9a21b98a7465f906f))
* **report:** count orphan testcases in JUnit tests= attribute ([531f63e](https://github.com/samdion1994/mocky-mock/commit/531f63e4cf5eb78749de874a328b2ada811f365e))
* **report:** surface FAIL lines with unknown case id instead of dropping them ([75ec041](https://github.com/samdion1994/mocky-mock/commit/75ec0413139fb67b1ee3333f0018cfca898b164d))
* **reset:** never target FILLER items when restoring group child VALUEs ([5d60c8f](https://github.com/samdion1994/mocky-mock/commit/5d60c8ffdda74f14cad8fc6bf566e85dea0f4fec))
* **reset:** restore group children's VALUE clauses after INITIALIZE ([cdd909d](https://github.com/samdion1994/mocky-mock/commit/cdd909d232339e27c592d9974e7ddda36d31d585))
* resolve unresolved merge-conflict markers left on main ([bd60da9](https://github.com/samdion1994/mocky-mock/commit/bd60da966cf52e42e7288af1578ff402050814bb))
* **runtime:** content-tag the GnuCOBOL image so Dockerfile edits rebuild ([b84609a](https://github.com/samdion1994/mocky-mock/commit/b84609aa641606caf266adea2ab9e25fcf3811db))
* **runtime:** harden the GnuCOBOL container that runs untrusted COBOL ([6b16dc6](https://github.com/samdion1994/mocky-mock/commit/6b16dc6d5fc2149cf734043d5e96a0ac850ae55d))
* **runtime:** keep DAC_OVERRIDE so container-root can read the bind mount ([ab719da](https://github.com/samdion1994/mocky-mock/commit/ab719da9391d8d242fdf17eea93bdfd2b99343b8))
* **splicer:** satisfy mypy and black on Task 6's terminator-splice changes ([77b7062](https://github.com/samdion1994/mocky-mock/commit/77b7062c6a353b6f492c27328835ab200bb9c59b))
* **splicer:** terminate chain-check insertion when the PERFORM it follows ends its own sentence ([d6d7913](https://github.com/samdion1994/mocky-mock/commit/d6d7913322b5f0bc71c706eb0b55a40eb4cf4a2f))
* strengthen STATELKUP collect test, correct README line numbers ([f1a3ddc](https://github.com/samdion1994/mocky-mock/commit/f1a3ddc741d929af2ba14584e2c0fece627ed132))
* **test:** give the debug spike a visible statement to step onto ([2c65d95](https://github.com/samdion1994/mocky-mock/commit/2c65d9590942014825d9096adcd0ef77652a5b3e))
* **tests:** rewrite stale out-of-line PERFORM VARYING integration pin ([b7bc45b](https://github.com/samdion1994/mocky-mock/commit/b7bc45bdf0c59ffb31afba124ebafcfc86001f7c))
* **tests:** rewrite stale out-of-line PERFORM VARYING pinning tests ([f959e5e](https://github.com/samdion1994/mocky-mock/commit/f959e5e2390f8afab9fb4f4089f69005b560cbef))


### Documentation

* add 2026-07-07 full-repo audit report ([e53e318](https://github.com/samdion1994/mocky-mock/commit/e53e318625b4f73de901621d339307d7b1ca438d))
* add CLI implementation plan for execution-trace debug support ([f9db252](https://github.com/samdion1994/mocky-mock/commit/f9db25269210c4d06e08e5466dcc5090e3541023))
* add coverage-reporting design (v1 scope) ([3598bda](https://github.com/samdion1994/mocky-mock/commit/3598bda32c5fd7b302bfa474c3e8557cc7a056b5))
* add design and plan for the cobol-mocky-mock publish pipeline ([f7218d3](https://github.com/samdion1994/mocky-mock/commit/f7218d33c9b614a5fd8f988db2bd8beb0e3eac26))
* add implementation plan for BEFORE-EACH/BEFORE-ALL and FILE-STATUS ([97f893f](https://github.com/samdion1994/mocky-mock/commit/97f893fdaae8b3da8ade3cd75242ebad2835a5f0))
* add implementation plan for coverage reporting ([3dc7719](https://github.com/samdion1994/mocky-mock/commit/3dc7719d77779f0e07f2955ca4e2c825cb5b91b7))
* add implementation plan for GOBACK/STOP RUN terminator support ([ab40693](https://github.com/samdion1994/mocky-mock/commit/ab406930961351c317ff4814a58dbcca75f8adbf))
* add implementation plan for narrow SECTION-scoped terminator support ([6d53ea9](https://github.com/samdion1994/mocky-mock/commit/6d53ea920b6b3be368758fd8fe54ebc5f375355b))
* add implementation plan for SQL v1 (EXEC SQL INCLUDE + cursor ROWS) ([fae822f](https://github.com/samdion1994/mocky-mock/commit/fae822f223d72a4eb586cc68ca3693300211f9c7))
* add integration-testing direction design notes ([0a7da52](https://github.com/samdion1994/mocky-mock/commit/0a7da52cfa8bf38bade1b9934f4406c8270ee60d))
* add mockymock lint command design ([083afa2](https://github.com/samdion1994/mocky-mock/commit/083afa2c1b3445dc2801a28f359145f7413317ac))
* add MVP design spec for mockymock ([a3081e9](https://github.com/samdion1994/mocky-mock/commit/a3081e967f482c590ff229c16fc06d4d7bf5f24a))
* add MVP implementation plan for mockymock ([d72192c](https://github.com/samdion1994/mocky-mock/commit/d72192cd5968393a54eda1ae31794ba191b09323))
* add PROVIDER parameterized test cases implementation plan ([a662974](https://github.com/samdion1994/mocky-mock/commit/a6629748651d40980f97887841445388f383a549))
* add real-world readiness audit for mockymock with findings and recommendations ([340e355](https://github.com/samdion1994/mocky-mock/commit/340e355cc540621b101dd4c6e08f0eb7f12ebb71))
* add Task 16 (copybook expansion wiring) to the plan ([f914314](https://github.com/samdion1994/mocky-mock/commit/f914314d986e20132096d68e4b8391d0072e0cc3))
* add TAXFILE example and document BEFORE-EACH/FILE-STATUS features ([252134c](https://github.com/samdion1994/mocky-mock/commit/252134cbbd14ea0be435c4793664c42f252a5449))
* addendum -- per-site mock dispatch is a second uncovered-line source ([5f7e6fe](https://github.com/samdion1994/mocky-mock/commit/5f7e6fe56aa1e4d04f714694198b7ee78a6cb06e))
* clarify relationship with cobol-check in README ([1bf7e2d](https://github.com/samdion1994/mocky-mock/commit/1bf7e2d62546e1d0c4b28a0153ce112c330c55c3))
* clarify SECTION-scoped terminator exclusion in find_terminator_plans docstring ([9ebdb5a](https://github.com/samdion1994/mocky-mock/commit/9ebdb5a9d6c3bee4b502a1e32a5849b9b59efeaa))
* correct call-stack synthesis mechanism per real implementation ([cb83b95](https://github.com/samdion1994/mocky-mock/commit/cb83b959bc2f64da4a64a7ca83ba118187d1f04a))
* correct post-extraction build-job description ([735873c](https://github.com/samdion1994/mocky-mock/commit/735873c3ebd9a57f413aa78ed585d12059b5d2dd))
* correct run_gcov mechanism -- docker exec -w works fine via subprocess ([a0c90ed](https://github.com/samdion1994/mocky-mock/commit/a0c90ed8d700435267770320c3c3f43d4ace3631))
* correct Task 14 nested-CALL fix design after BLOCKED discovery ([37b0eba](https://github.com/samdion1994/mocky-mock/commit/37b0ebab52e4e3a1b22c1bcb77b55c3ea4783ddc))
* **coverage:** README + OKF concept for coverage reporting ([878bd62](https://github.com/samdion1994/mocky-mock/commit/878bd62caf99801f6a298b19cee7447f92a35227))
* design + plan for nested mock targets ([c17b550](https://github.com/samdion1994/mocky-mock/commit/c17b550eebfa62866694b89889c795d27c61cb3a))
* design BEFORE-EACH/BEFORE-ALL scoping and FILE-STATUS sugar ([3ae0b45](https://github.com/samdion1994/mocky-mock/commit/3ae0b45ee43a9746a537aaf177a8035f7feaadc1))
* design conditionally-nested intermediate PERFORM support ([3e8a118](https://github.com/samdion1994/mocky-mock/commit/3e8a118e509c6d04dfd07923f5da7af4f4247612))
* design EXEC SQL INCLUDE host-var copybook expansion + cursor ROWS sugar ([7a8cb6a](https://github.com/samdion1994/mocky-mock/commit/7a8cb6a6082da9588b9c57f4897472c95996a776))
* design execution-trace debug support for CLI + VS Code extension ([c9db7b3](https://github.com/samdion1994/mocky-mock/commit/c9db7b375cf565addfc0eafdcc9c3b691c1177ef))
* design for GOBACK/STOP RUN terminator support ([ed7f402](https://github.com/samdion1994/mocky-mock/commit/ed7f4025f0acddc9439f57bec487c8448fda3bd9))
* design for IMS DL/I ENTRY/LINKAGE support (neutralize-and-promote) ([7a80593](https://github.com/samdion1994/mocky-mock/commit/7a805934145ba1315d5049b26148d2e5189f4f40))
* design for real-world COBOL e2e examples sourced from legacy-application ([5600e18](https://github.com/samdion1994/mocky-mock/commit/5600e1817f44df4d493bb4ca68e1af5fb5cdf7d3))
* design GO TO fall-through terminator hazard guard ([aa6956d](https://github.com/samdion1994/mocky-mock/commit/aa6956d2629cd79c01ab58996cfb89ce28446b36))
* design GO TO-reachable terminator investigation ([2b74c1d](https://github.com/samdion1994/mocky-mock/commit/2b74c1df2c182df96820fd8073d7451d2950f4ec))
* design narrow SECTION-scoped terminator support (shape 1 only) ([9e8b5ac](https://github.com/samdion1994/mocky-mock/commit/9e8b5ac1b632c8f75264a015fbb0ae569293c325))
* design PROVIDER parameterized test cases ([d6f6169](https://github.com/samdion1994/mocky-mock/commit/d6f616989dd1995f9ef0592b8ab0f3633623fb61))
* Docker GnuCOBOL toolchain design spec ([a290cb5](https://github.com/samdion1994/mocky-mock/commit/a290cb528b995ba68621dcf2417ecae9e20d41b9))
* Docker toolchain implementation plan ([f97f4a0](https://github.com/samdion1994/mocky-mock/commit/f97f4a0e813c2e7d0bf22ce54dca9ce92d53a424))
* document --trace in README and OKF bundle ([acd0120](https://github.com/samdion1994/mocky-mock/commit/acd0120645cda4c1329f82f820d80477c3c1ddb9))
* document call-site splicer nested-statement fix (Task 14 Important finding) ([cede0b4](https://github.com/samdion1994/mocky-mock/commit/cede0b430b010c56d89ee9138a40fd648befcc21))
* document EXEC SQL INCLUDE resolution and ROWS cursor sugar ([c76097a](https://github.com/samdion1994/mocky-mock/commit/c76097a31a835799c6ef3bd29e494005e3c78444))
* document EXEC SQL INCLUDE resolution and ROWS cursor sugar ([dcfadc9](https://github.com/samdion1994/mocky-mock/commit/dcfadc9af3eb542912c82072c7da8f75fcd32048))
* document mockymock debug in OKF bundle and README ([37a56b3](https://github.com/samdion1994/mocky-mock/commit/37a56b3957d001ae776f33efd6908925b70c67b5))
* document PROVIDER parameterized test cases ([43e0952](https://github.com/samdion1994/mocky-mock/commit/43e095247a656589cb5bda3b868d7b3d8faa4ec2))
* document recursive nested-statement detection requirement (Task 5) ([132ce87](https://github.com/samdion1994/mocky-mock/commit/132ce871937d48111a7fb8dc89158ea11b049b31))
* document refusal-gate reachability BFS fix (Task 6 Critical finding) ([50facc3](https://github.com/samdion1994/mocky-mock/commit/50facc3cba6d1cb08451542aea69486041f61a07))
* document the public binary publish pipeline ([491b46b](https://github.com/samdion1994/mocky-mock/commit/491b46b4c0b40c24903f623ec9268a8af4f221e2))
* fix .okf/log.md entry ordering to newest-first ([34e9731](https://github.com/samdion1994/mocky-mock/commit/34e97319f3d55f1f1788f22d8daaaa56ef1449b6))
* fix documentation inconsistencies flagged in PR review ([1057335](https://github.com/samdion1994/mocky-mock/commit/105733546fff103c845b6a7e44645d998614547a))
* fix PROVIDER HEADER/ROW quoting convention ([e224f7a](https://github.com/samdion1994/mocky-mock/commit/e224f7abd1dde04ed05ab8d8fe9bcd264bd37137))
* GO TO-reachable terminators investigation (no fix found, refusal confirmed permanent) ([3ab8c0d](https://github.com/samdion1994/mocky-mock/commit/3ab8c0db5e00f418b3671f73057bcb14fedfbd8d))
* implementation plan for conditionally-nested intermediate PERFORM ([53690d6](https://github.com/samdion1994/mocky-mock/commit/53690d67b31b7cc8728836b79592f21daae3136e))
* implementation plan for GO TO fall-through terminator hazard guard ([cd617a1](https://github.com/samdion1994/mocky-mock/commit/cd617a126f3caf2b1e90cb9e79ecfc25f12b1c1f))
* implementation plan for GO TO-reachable terminator investigation ([0ec47b5](https://github.com/samdion1994/mocky-mock/commit/0ec47b5d5102b651f70af8cf846b893387468aa0))
* implementation plan for real-world DEPTMQP/DEPTMQC e2e examples ([3ede03b](https://github.com/samdion1994/mocky-mock/commit/3ede03bc592c3860289e17b580d00f38372606a4))
* link publishing.md's See Also citations ([f2e7852](https://github.com/samdion1994/mocky-mock/commit/f2e7852f39ac6e25afd6fc0ccd5e362ca15f23b2))
* mark coverage-reporting design doc as implemented/superseded ([a86490a](https://github.com/samdion1994/mocky-mock/commit/a86490a2d70d9b8172ef66bb20987d9b3bc1685b))
* mock-all-boundaries v2 design — FILE/SQL/CICS/DLI/ACCEPT/MQ mock categories ([56f35a6](https://github.com/samdion1994/mocky-mock/commit/56f35a62cfafae03f66fee0364ca995cfd2432fb))
* note INCLUDE-resolved host vars aren't reset between test cases ([303db3c](https://github.com/samdion1994/mocky-mock/commit/303db3c53d3fd46a87736f597fe46a734a05119d))
* PERFORM THRU implementation plan; design facts corrected (phantom paragraphs are empty artifacts) ([c72cc0f](https://github.com/samdion1994/mocky-mock/commit/c72cc0fa6f84e3e992239993ec5b090d140f076d))
* PERFORM THRU support design (range-expanded reachability + .cut driver THRU) ([f636ab3](https://github.com/samdion1994/mocky-mock/commit/f636ab3a8b6b648062eb28a5ccb6bba23660ef61))
* point README at the new .okf/ knowledge bundle ([ec0ee88](https://github.com/samdion1994/mocky-mock/commit/ec0ee8866842709a5f24c240063696b3cc36bc05))
* polish GO TO investigation writeup per final review ([2900520](https://github.com/samdion1994/mocky-mock/commit/290052018024c131d95830839eeb5bd8a8e2fd80))
* README reflects nested-mock-target support and narrowed refusals ([fd12393](https://github.com/samdion1994/mocky-mock/commit/fd123939b485c432c17a2178ebf1fb1e472a823d))
* real-world readiness implementation plan ([db37b3a](https://github.com/samdion1994/mocky-mock/commit/db37b3a035f5523ee53962910b1cdda18720f4c8))
* reconcile hardening descriptions with the retained DAC_OVERRIDE cap ([16c6551](https://github.com/samdion1994/mocky-mock/commit/16c6551d03306fc69ce51bf8cd3f4dda7e0ebad5))
* reconcile plan's pytest-cov contradiction (Task 1 review finding) ([6f4ebfc](https://github.com/samdion1994/mocky-mock/commit/6f4ebfc74e8fd72c423d70c9d8b625a0ca77ff47))
* record GO TO-reachable terminator investigation outcome ([fd918e9](https://github.com/samdion1994/mocky-mock/commit/fd918e9293f56c3b25fc8fea036462f8769de65f))
* refine INCLUDE resolution to route through public expand_copybooks ([716c116](https://github.com/samdion1994/mocky-mock/commit/716c11650d6e02695ac78976e45f660b2092c61f))
* refine wiring to precompute nested insertion points in refusal.py ([2349ca0](https://github.com/samdion1994/mocky-mock/commit/2349ca0726293cdfaba15ed31365a6a562805915))
* refresh timestamps on analysis.md/splicer.md for SECTION-scoped update ([b76a533](https://github.com/samdion1994/mocky-mock/commit/b76a53389b3039b94f11968ff2d99a7446df1aaf))
* remove obsolete local-GnuCOBOL Windows notes from README ([c177808](https://github.com/samdion1994/mocky-mock/commit/c177808342a981a2f47bf323522585067acb1c6f))
* revise GOBACK/STOP RUN design to Approach B (EXIT PARAGRAPH propagation) ([b018ff2](https://github.com/samdion1994/mocky-mock/commit/b018ff2c5cf2873aca07f013ace37f3da30ab095))
* revise real-world COBOL examples design after spiking all candidates ([3eeecfb](https://github.com/samdion1994/mocky-mock/commit/3eeecfb1e98301c89bbe4d76ad00620ca229adc7))
* rewrite implementation plan for Approach B (EXIT PARAGRAPH propagation) ([e762c7c](https://github.com/samdion1994/mocky-mock/commit/e762c7c5dc0eb6d8b68dc68f8075f8bb239f3c62))
* sync GOBACK/STOP RUN terminator support (Approach B) ([64c3e65](https://github.com/samdion1994/mocky-mock/commit/64c3e65a223e572c969d49fd0eee4d0f03126ddc))
* sync README DSL reference and OKF concepts with BEFORE/FILE-STATUS/PROVIDER wave ([e783c37](https://github.com/samdion1994/mocky-mock/commit/e783c3780b9a38cedede8c912a112e3031c50496))
* sync SECTION-scoped terminator support (narrow shape) ([7a68afb](https://github.com/samdion1994/mocky-mock/commit/7a68afb6bac4af5a2fa37f286ec5730d71af3bc2))
* **test:** note that the unneutralized-shape crash is UB, not guaranteed ([8356f16](https://github.com/samdion1994/mocky-mock/commit/8356f164f199f962dd81971758eb96991d17836a))
* update testing documentation and logs ([9038462](https://github.com/samdion1994/mocky-mock/commit/903846223d7abe4c7e8868a49dde3e3d36f2338a))
