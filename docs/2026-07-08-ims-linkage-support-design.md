# IMS DL/I ENTRY/LINKAGE Support — Design

Date: 2026-07-08
Status: approved for implementation

## Problem

Five real-world programs (`ACCTPRG`, `DEPTBMP`, `DEPTIMSM`, `FNDTXFR`,
`LNRECOV`) declare a named `ENTRY 'DLITCBL' USING <pcb-linkage-group>`
alongside a bare, no-`USING` default entry (`PROCEDURE DIVISION.` with
nothing else on the line). mockymock's driver only ever `PERFORM`s the
program's default entry directly, in the same compilation unit — it never
`CALL`s the program through the named entry. The LINKAGE SECTION storage
that entry's `USING` clause would bind is therefore never allocated, and any
reference to it from code reachable off the default entry (e.g.
`EVALUATE CUST-STATUS` in `ACCTPRG`'s `1000-INITIALIZE`) dereferences
unbound memory.

Confirmed live against the real `mockymock-cobc` GnuCOBOL 3.2 container: a
minimal repro of this shape compiles cleanly and then **crashes at runtime
with SIGSEGV (exit 139, "attempt to reference invalid memory address")**.
`docs/corpus-sweep-report.md`'s static sweep (`mockymock generate`) does not
catch this — it only measures parse/whole-program-refusal/unmockable-boundary
signals, none of which fire for these 5 programs today; the crash is a
runtime-only gap the sweep's own "next steps" section flagged as untested.

The originally scoped fix for this (see git history around this doc) was a
static refusal (`UNBOUND_LINKAGE_SECTION`) that would turn the crash into an
honest, permanent refusal. On review, the better outcome is to actually
support this shape: these 5 programs' only IMS access pattern is
`CALL 'CBLTDLI' USING ...`, already an ordinary mockable `MockCategory.CALL`
boundary — nothing else about them is exotic. If the LINKAGE storage can be
made safe to reference, they become fully testable with zero new mocking
primitives.

## Key facts (verified empirically against the real GnuCOBOL toolchain)

Three synthetic variants were compiled and run in the `mockymock-cobc`
container (`cobc -free -x`), mirroring `ACCTPRG`'s exact shape (bare default
entry, separate named `ENTRY ... USING <linkage-group>`, a field from that
group read in the first paragraph the default entry reaches):

1. **Original shape** (`ENTRY` present, `LINKAGE SECTION` present, unchanged):
   compiles clean, **crashes at runtime** (exit 139).
2. **`ENTRY` statement commented out, `LINKAGE SECTION` left untouched**:
   compiles clean, **still crashes** (exit 139) — the storage is still
   BASED/unbound regardless of whether anything declares `USING` against it;
   commenting the `ENTRY` alone does not help.
3. **`ENTRY` statement commented out AND the `LINKAGE SECTION.` header line
   commented out, data items left physically in place**: compiles clean,
   **runs clean** (exit 0), and the field reads its natural default (spaces)
   with no explicit initialization.

The mechanism behind (3): removing the `LINKAGE SECTION.` header line with
no other section header in between causes GnuCOBOL to treat every
declaration that follows (up to the next section header or
`PROCEDURE DIVISION`) as a continuation of the *previous* section —
`WORKING-STORAGE SECTION` in every corpus case. The data items do not need
to be physically moved; only the section-header line needs to be commented
out. Confirmed against the real `ACCTPRG.cbl` text: `normalize_fixed_format`
output line 71 is `LINKAGE SECTION.`, line 72 is `01  CUST-PCB-LNK.`
(`CUST-PCB-LNK.location.line == 72`) — i.e. the header line is reliably
`(first LINKAGE item).location.line - 1` once blank/comment lines have
already been stripped by normalization.

Also verified directly against `cobolparser` (as installed, no upstream
change needed):
- `CobolProgram.get_entry_statements() -> list[EntryStatement]` already
  exists and returns every `ENTRY` statement in the program, each with
  `.entry_name: str | None` and `.location.line`.
- `CobolProgram.get_division("DATA")._sections["LINKAGE"].data_items` gives
  the LINKAGE SECTION's top-level data items (empty/absent when there is no
  LINKAGE SECTION) — the same `._sections` access pattern
  `reset.py` already uses to find WORKING-STORAGE.
- **`CobolSection.location.line` for a DATA DIVISION section is not
  reliable** — it reports the enclosing DATA DIVISION's own line for every
  section (`FILE`/`WORKING-STORAGE`/`LINKAGE` all reported line 12 on
  `ACCTPRG.cbl`, not each section's own header line). The header line must
  be derived from the first data item's location instead (see above), with
  a textual check before ever commenting it out.
- Across the 6 CBLTDLI-calling corpus programs, exactly the 5 named above
  have both a named `ENTRY` and a non-empty `LINKAGE SECTION`; `LOANPMT`
  (the 6th) has neither. No fixture or example anywhere in mockymock today
  has *any* `LINKAGE SECTION`, so this change has zero regression surface
  against the existing passing corpus.
- No program anywhere in the corpus declares `PROCEDURE DIVISION USING`
  on its default entry (grepped `legacy-application/cobol`,
  `mocky-mock/examples`, `mocky-mock/tests`: zero hits). That broader
  "ordinary CALLed subprogram" pattern is explicitly out of scope here — it
  remains Milestone B (`docs/superpowers/plans/2026-07-06-real-world-readiness.md`)
  territory, untested and unsolved by this design.

## Approaches considered

**A. Refuse only (`UNBOUND_LINKAGE_SECTION`).** Cheapest, matches the
original ask. Rejected on review: it leaves 5 real programs permanently
untestable when a proven, low-risk fix exists.

**B. General CALL-based driving (Milestone B).** Have the driver actually
`CALL` the program through its named entry, allocating LINKAGE storage
properly. Correct in general, but a much larger engine change (COMMAREA/PCB
allocation, `CALL`-vs-`PERFORM` driver rewrite) that the existing plan
already scopes as its own milestone, gated on its own GnuCOBOL semantics
spike. Rejected for *this* fix — no need to build the general mechanism to
solve the one shape that actually occurs in the corpus.

**C. Neutralize ENTRY + relocate LINKAGE into WORKING-STORAGE (chosen).**
Comment out the `ENTRY` statement(s) and the `LINKAGE SECTION.` header line
via the existing `stub_writer.comment_and_replace` splice primitive. No new
storage-allocation mechanism, no AST surgery, reuses machinery the splicer
already has. Verified empirically (above) to compile and run clean. Solves
exactly the 5 real programs; anything structurally different (guardrails
below) refuses rather than guessing.

## Design (approach C)

### Guardrails — apply the transform only when structurally safe

Given a program with ≥1 `ENTRY` statement and a non-empty `LINKAGE SECTION`:

1. The default entry (the bare `PROCEDURE DIVISION.` header) must have **no
   `USING` of its own** — only the named `ENTRY` declares one. (No corpus
   example has a default-entry `USING`; untested combination, refuse rather
   than guess.)
2. `LINKAGE SECTION` must be the **last section** in `DATA DIVISION` (no
   `REPORT SECTION`/`SCREEN SECTION` etc. after it) — otherwise removing the
   header would silently absorb unrelated sections into WORKING-STORAGE too.
3. The candidate header line (`first_linkage_item.location.line - 1`) must
   **textually verify** as `LINKAGE SECTION` (case-insensitive, whole
   words) before being commented — if it doesn't match, something about the
   layout isn't what was verified above, so refuse rather than comment the
   wrong line.

If any guardrail fails: refuse whole-program with a new code,
`UNSUPPORTED_LINKAGE_LAYOUT`, describing which guardrail failed. This sits
alongside `UNSUPPORTED_DECLARATIVES`/`UNSUPPORTED_ALTER` in
`refusal.check_whole_program`'s family.

If all guardrails hold: apply the transform (below). No refusal — this is
the new, supported path.

### Transform

A new splicer step, `mockymock/splicer/linkage.py`:
- For every `EntryStatement` in the program: compute its line span (reuse
  `source_map.statement_span`, the same helper other top-level splices use)
  and comment it out via `stub_writer.comment_and_replace`.
- Comment out the single `LINKAGE SECTION.` header line the same way.
- No data is physically relocated.

Ordering: this step must run **before** `reset.py`'s WORKING-STORAGE walk,
so the promoted fields are swept into the existing reset-between-cases
mechanism automatically (they get `INITIALIZE`/type-default treatment like
any other WORKING-STORAGE group with no `VALUE` clause — matching the
verified runtime behavior, spaces/zeros). It must also run before
`mock_surface.analyze()` is used for splicing decisions that depend on
line numbers shifting — in practice, easiest to apply as the very first
line-level transform in the `_cmd_run`/`orchestrator.splice_program`
pipeline, immediately after `normalize_fixed_format`.

### Consequence for `CALL 'CBLTDLI'`

No special-casing needed: it is already classified as an ordinary
`MockCategory.CALL` boundary site by `mock_surface.py`. A `.cut` author can
write `MOCK CALL "CBLTDLI"` with a body that sets `CUST-STATUS` (now real,
addressable WORKING-STORAGE) to simulate GHN success, end-of-database
(`'GB'`), or DLET success/failure — exactly like any other mocked CALL.

### Worked example

`examples/real-world/ACCTPRG/` (mirrors the `DEPTMQP`/`DEPTMQC`
convention): `ACCTPRG.cbl` plus `copybooks/{WSCOMMON,ERRORCD,IMSPCB}.cpy`
copied from `../legacy-application/copybook`. Test cases target
**sub-paragraphs** (`1000-INITIALIZE`, `2000-SCAN-AND-PURGE`), not
`0000-MAIN-PROCESS` — the latter ends in `GOBACK`, an existing, separate,
documented program-terminator limitation (`docs/2026-07-06-real-world-readiness-audit.md`
Finding 3) that would kill the whole test binary regardless of this fix.
(Partially resolved by `docs/2026-07-08-goback-stop-run-support-design.md`
— see Task 10 of its implementation plan for re-targeting this example at
`0000-MAIN-PROCESS`, if its GOBACK is reached via a plain PERFORM chain.)
This is the same workaround `DEPTMQP`/`DEPTMQC` already use.

### Testing

- Unit (Docker-free): guardrail detection on synthetic fixtures (qualifying
  shape, default-entry-USING shape, non-last-LINKAGE shape, no-ENTRY/no-LINKAGE
  shape); the line-splice transform against a synthetic fixture and against
  the real `ACCTPRG.cbl` text (asserting the exact header/entry lines it
  comments out).
- Integration (`Verify (integration/Docker)`, `@requires_docker`): the new
  `examples/real-world/ACCTPRG` example runs green end-to-end through
  `mockymock run` — proving the SIGSEGV is gone and the program is
  genuinely testable, not just non-crashing.

### Docs sync

- `.okf/analysis.md` / `.okf/splicer.md`: new concept rows for
  `UNSUPPORTED_LINKAGE_LAYOUT` and the neutralization transform.
- `docs/corpus-sweep-report.md`: note that the 5 IMS programs now go
  through this transform (no longer "zero refusal codes" in the naive
  sense measured by the original sweep).
- `docs/superpowers/plans/2026-07-06-real-world-readiness.md`: note that
  Milestone B's scope narrows — the IMS named-ENTRY subset is solved by
  this design; general CALL-based subprogram driving remains future work.

## Out of scope

- `PROCEDURE DIVISION USING` on a program's default entry (no named
  `ENTRY`) — Milestone B territory, no corpus evidence today.
- CICS COMMAREA-style entry binding — different mechanism, no corpus
  example.
- Making `0000-MAIN-PROCESS`'s full read-loop (through `GOBACK`) testable —
  Milestone A (`STOP RUN`/`GOBACK` handling), independent of this design.
