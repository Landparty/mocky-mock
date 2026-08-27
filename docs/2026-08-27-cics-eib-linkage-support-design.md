# CICS Implicit-Linkage Support — Design

Date: 2026-08-27
Status: approved for implementation

## Problem

A real CICS COBOL program routinely references identifiers no `.cbl` source
ever declares: `EIBCALEN`, `EIBAID`, `EIBTIME`, `EIBTRMID`, `EIBDATE`, and
the other ~30 fields of the CICS Execute Interface Block (`DFHEIBLK`). In a
real mainframe build, the CICS translator inserts `DFHEIBLK`'s LINKAGE
SECTION layout and an implicit `PROCEDURE DIVISION USING DFHEIBLK,
DFHCOMMAREA` ahead of `cobc`/the native compiler ever seeing the source —
neither is visible in the `.cbl` a programmer writes or mockymock parses.

mockymock's own CICS support (resolved 2026-07-10, `examples/custinq/`) only
proved out `EXEC CICS` statements themselves: `injector.build_exec_trap`
splices every unmocked `EXEC CICS...END-EXEC` block out before compilation,
so GnuCOBOL never needs a real CICS translator for the command syntax. That
says nothing about EIB fields referenced from *ordinary* COBOL statements
outside any `EXEC CICS` block — e.g. `IF EIBCALEN = 0` to detect a program's
first invocation, or `IF EIBAID = DFHENTER` to branch on which key was
pressed. `examples/custinq/CUSTINQ.cbl` never does this (no `LINKAGE
SECTION`, no EIB reference anywhere), so the gap was never exercised: a
repo-wide grep for `EIBCALEN|EIBAID|EIBTIME|EIBTRMID|EIBDATE|DFHEIBLK`
across mocky-mock returns zero hits outside this design doc and its
implementation.

Left alone, a program using this (extremely common, real-world) idiom fails
`cobc` compilation outright: `EIBCALEN` etc. are undeclared data names, a
hard compile error, not a runtime crash like the IMS LINKAGE case this
design's mechanism is modeled on (`docs/2026-07-08-ims-linkage-support-design.md`).

## A second, related gap: `DFHCOMMAREA` without a binding `ENTRY`

Separately: a CICS program that *does* want its passed COMMAREA typically
hand-declares it —

```cobol
LINKAGE SECTION.
01  DFHCOMMAREA.
    05  ...
PROCEDURE DIVISION.
```

— with no `ENTRY` statement at all: CICS runtime maps the real COMMAREA
into this LINKAGE storage directly (not via an ordinary COBOL `CALL...USING`
mockymock's driver could ever perform). `analysis.linkage.linkage_plan`
today requires at least one `ENTRY` statement before it looks at LINKAGE
SECTION at all (`if not entries: return None`) — a CICS program with a
LINKAGE SECTION and *no* `ENTRY` falls through that check entirely and hits
the exact unbound-LINKAGE-SECTION crash `docs/2026-07-08-ims-linkage-support-design.md`
verified for the IMS case (finding 2: "`ENTRY` statement commented out,
`LINKAGE SECTION` left untouched: compiles clean, still crashes — the
storage is still BASED/unbound regardless of whether anything declares
`USING` against it"). That finding already proves the fix generalizes:
nothing about *why* the LINKAGE SECTION exists matters to the transform,
only whether mockymock's `PERFORM`-based driver ever binds it — which it
never does, `ENTRY` or not.

`docs/2026-07-08-ims-linkage-support-design.md`'s own "Out of scope" section
flagged this directly: *"CICS COMMAREA-style entry binding — different
mechanism, no corpus example."* This design closes that gap by generalizing
the existing mechanism, not building a new one.

## No corpus evidence, unlike the IMS design

The IMS linkage design was driven by 5 real, broken programs verified live
against the `mockymock-cobc` GnuCOBOL container (compile-clean,
runtime-SIGSEGV, then compile-and-run-clean after the fix). This design has
no equivalent: mocky-mock's corpus contains exactly one `EXEC CICS` program
(`examples/custinq/CUSTINQ.cbl`), and it doesn't exercise either gap above.
This session also has no working Docker daemon (`docker info` fails), so
neither part of this design could be verified against the real toolchain the
way the IMS design was. The DFHEIBLK layout below is the standard,
decades-stable IBM CICS EIB layout (unchanged across CICS TS releases); the
two guardrails are deliberately conservative (refuse rather than guess) for
exactly this reason. **Follow-up work should add a real-world CICS example
under `examples/real-world/` and run it through the Docker-gated integration
suite (`@requires_docker`) the first time a working toolchain is available**,
the same proof-of-life step the IMS design's `ACCTPRG` example provided.

## Approaches considered

**A. Build a real CICS translator.** Correct in general, huge scope (parse
every `EXEC CICS` command's semantics, not just splice the block away;
expand `DFHRESP`/`DFHVALUE` against the full ~100-entry CICS condition
table). Rejected: existing `EXEC CICS` handling already avoids needing this
for the command syntax itself; building it only to resolve EIB field
declarations and DFHCOMMAREA binding is disproportionate.

**B. Refuse whole-program whenever any EIB field or DFHCOMMAREA is
referenced.** Cheapest, but permanently blocks a mainstream, idiomatic CICS
pattern with a proven low-risk fix available (below). Rejected for the EIB
case; kept as the fallback for the two situations that genuinely can't be
solved safely (see Guardrails).

**C. Synthesize the standard `DFHEIBLK` layout; generalize the existing
LINKAGE neutralization for `DFHCOMMAREA` (chosen).** Two independent, additive
mechanisms:

1. **EIB field synthesis** (new): when the program references any EIB field
   name or `DFHEIBLK` itself, and none of them is already declared anywhere
   in its own DATA DIVISION, insert a synthesized `01 DFHEIBLK.` WORKING-STORAGE
   group with the standard layout — the same insertion mechanism `driver.py`
   already uses for its own bookkeeping fields (`UT-CURRENT-CASE` etc.), so
   no new splice primitive is needed.
2. **LINKAGE neutralization without `ENTRY`** (generalized existing
   mechanism): drop `linkage_plan`'s requirement of a non-empty
   `get_entry_statements()` — an unbound LINKAGE SECTION is exactly as
   unsafe with zero `ENTRY` statements as with one, per the IMS design's own
   empirical finding 2 above. `neutralize`'s `ENTRY`-commenting loop is
   already a no-op over an empty list, so this needs no change to the
   transform itself, only to the detection gate.

## Design

### Part 1 — Generalized LINKAGE neutralization (covers `DFHCOMMAREA`)

`mockymock/analysis/linkage.py`: `linkage_plan(program)` now returns `None`
only when the LINKAGE SECTION itself is absent/empty — the `entries` list it
carries may now be empty (`LinkagePlan.entry_statements: list` — an ordinary
Python list, `[]` is a normal value, no type change). `splicer/linkage.py`'s
`neutralize`/`extra_reset_lines` and `refusal.check_linkage_layout`'s three
guardrails (LINKAGE-must-be-last-section; default entry must have no own
`USING`; header line must textually verify) are unchanged — they already
tolerate zero `ENTRY` statements structurally, this was only ever gated by
the early return.

This alone makes the idiomatic `LINKAGE SECTION. 01 DFHCOMMAREA. ...` /
`PROCEDURE DIVISION.` (no `ENTRY`) shape fully supported: real, addressable
WORKING-STORAGE, reset between test cases, `.cut` authors read/write
`DFHCOMMAREA` fields directly as ordinary `MOCK`/`EXPECT` targets.

Zero regression risk: per the IMS design doc, *"No fixture or example
anywhere in mockymock today has any LINKAGE SECTION"* — broadening the gate
changes behavior for zero currently-passing programs.

A `DFHCOMMAREA` referenced but never declared anywhere (no `LINKAGE
SECTION` entry for it at all) has no knowable size — Part 1 has nothing to
neutralize in that case. Guardrailed explicitly in Part 3 below rather than
silently doing nothing.

### Part 2 — `DFHEIBLK`/EIB field synthesis

New `mockymock/analysis/cics_eib.py` (detection, pure query):

```python
EIB_FIELD_NAMES: frozenset[str]  # the 29 named DFHEIBLK fields, uppercase
DFHEIBLK_NAME = "DFHEIBLK"

@dataclass
class CicsEibPlan:
    referenced_names: list[str]  # sorted, for the transparency message

def cics_eib_plan(program, lines: list[str]) -> CicsEibPlan | None:
    ...
```

`cics_eib_plan`:
1. Whole-word-regex-scans `lines` (the same normalized text the splicer
   edits) for any name in `EIB_FIELD_NAMES | {DFHEIBLK_NAME}`. No matches
   -> `None` (ordinary non-CICS program, untouched).
2. Collects every already-declared DATA DIVISION name via
   `cobolparser.analysis.unused_variables.collect_declared_items(program)`
   (the same FILE/WORKING-STORAGE/LOCAL-STORAGE/LINKAGE walk, including
   nested children, that analyzer already exposes for reuse). If any
   referenced name is already declared — the program hand-declared its own
   copy, e.g. via `COPY DFHEIBLK` — return `None`: synthesizing a second
   `DFHEIBLK` would be a duplicate-data-name compile error, and the program
   already supplies real storage.
3. Otherwise return a `CicsEibPlan` naming which fields were actually
   referenced (transparency message only — synthesis always emits the full
   fixed layout, below, regardless of which specific fields matched: a real
   CICS translator always inserts the whole block, and emitting a subset
   would silently drift from the real interface's field offsets).

New `mockymock/splicer/cics_eib.py` (synthesis):

```python
def working_storage_lines(plan: CicsEibPlan) -> list[str]: ...
def reset_lines(plan: CicsEibPlan) -> list[str]: ...  # ["INITIALIZE DFHEIBLK"]
```

`working_storage_lines` returns the fixed `01 DFHEIBLK.` group (below).
Unlike `splicer.linkage.neutralize` (comment-only, so line-count-preserving
and safe to run at any point in the pipeline), this *inserts* new physical
lines — every AST-`SourceLocation`-driven step downstream (`mock_surface`,
`collect_scope_map`, `splice_program`'s boundary spans, ...) would silently
misalign if this ran before them. So it never runs as an early text-edit
step like Part 1's `neutralize`; instead its output is merged into
`DriverArtifact.working_storage_lines` right before `_insert_driver` — the
one point in every pipeline (`run`/`debug`/`export`/`mutate`) already proven
safe for adding new WORKING-STORAGE, since the driver's own bookkeeping
fields (`UT-CURRENT-CASE` etc.) are inserted exactly the same way, at the
same point, today.

`build_driver` gains an optional `extra_working_storage_lines: list[str] |
None` parameter, appended to its own `working_storage` list before
returning `DriverArtifact` — the minimal change that avoids a second,
parallel insertion mechanism.

`reset_lines`: a single `INITIALIZE DFHEIBLK` line, appended to
`reset_move_lines`'s output the same way `splicer.linkage.extra_reset_lines`
already is (`reset.py`'s own rule for a VALUE-less group). A `.cut` test
case can still `MOVE ... TO EIBAID`/`EIBCALEN` etc. as an ordinary
`setup_moves` GIVEN — the synthesized group is real, addressable
WORKING-STORAGE like any other.

#### The `DFHEIBLK` layout

The standard IBM CICS Execute Interface Block, unchanged across CICS TS
releases. The two reserved filler slots exist for byte-alignment (real EIB
byte layout) but are never referenced by application code, and their exact
internal field names are not asserted here (no verified source to confirm
spelling) — declared as `FILLER` instead, which is both honest about that
and — being unaddressable by definition — behaviorally identical either way:

```cobol
01  DFHEIBLK.
    05  EIBTIME      PIC S9(7) COMP-3.
    05  EIBDATE      PIC S9(7) COMP-3.
    05  EIBTRNID     PIC X(4).
    05  EIBTASKN     PIC S9(7) COMP-3.
    05  EIBTRMID     PIC X(4).
    05  FILLER       PIC S9(4) COMP.
    05  EIBCPOSN     PIC S9(4) COMP.
    05  EIBCALEN     PIC S9(4) COMP.
    05  EIBAID       PIC X(1).
    05  EIBFN        PIC X(2).
    05  EIBRCODE     PIC X(6).
    05  EIBDS        PIC X(8).
    05  EIBREQID     PIC X(8).
    05  EIBRSRCE     PIC X(8).
    05  EIBSYNC      PIC X(1).
    05  EIBFREE      PIC X(1).
    05  EIBRECV      PIC X(1).
    05  FILLER       PIC X(1).
    05  EIBATT       PIC X(1).
    05  EIBEOC       PIC X(1).
    05  EIBFMH       PIC X(1).
    05  EIBCOMPL     PIC X(1).
    05  EIBSIG       PIC X(1).
    05  EIBCONF      PIC X(1).
    05  EIBERR       PIC X(1).
    05  EIBERRCD     PIC X(4).
    05  EIBSYNRB     PIC X(1).
    05  EIBNODAT     PIC X(1).
    05  EIBRESP      PIC S9(8) COMP.
    05  EIBRESP2     PIC S9(8) COMP.
    05  EIBRLDBK     PIC X(1).
```

No `VALUE` clauses: `INITIALIZE DFHEIBLK` zeros the COMP/COMP-3 numeric
fields and space-fills the alphanumeric ones, which happens to already be
the realistic "no COMMAREA passed, first invocation" default (`EIBCALEN =
0`) without needing an explicit override.

### Part 3 — Guardrails (`refusal.check_cics_eib_layout`)

New `check_cics_eib_layout(program, lines) -> list[RefusalReason]`, run
alongside `check_linkage_layout` in `checks.py` step 5, independent of
whether `cics_eib_plan` found anything (both checks below can fire even for
a program with zero EIB field references):

1. **`UNSUPPORTED_CICS_MACRO`** — `lines` contains `DFHRESP(` or
   `DFHVALUE(` (whole-program regex, case-insensitive) anywhere. These are
   CICS-translator macro-functions (`DFHRESP(NORMAL)` expands to a literal
   response code; the full mapping is a ~100-entry, translator-version-
   sensitive table) that only ever appear in ordinary COBOL conditions
   (never inside `EXEC CICS` command syntax, which uses bare condition names
   like `MAPFAIL` as `HANDLE CONDITION`/`RESP` targets instead — those stay
   inside the `EXEC CICS...END-EXEC` block `injector.build_exec_trap`
   already splices away whole, so they need no handling here). No safe
   expansion without a real translator: refuse rather than guess a value
   that silently diverges from the target CICS version's actual codes.
2. **`UNSUPPORTED_CICS_DFHCOMMAREA`** — `DFHCOMMAREA` is referenced
   (whole-word regex over `lines`) but not declared anywhere in the
   program's own DATA DIVISION (same `collect_declared_items` check as Part
   2). Part 1 can only neutralize a LINKAGE SECTION the program itself
   declares; a `DFHCOMMAREA` reference with no declaration anywhere has no
   knowable size or layout to synthesize — refuse rather than guess one.

Both join `check_linkage_layout` in `checks.py` step 5 (same list,
same-shaped `RefusalReason`, same short-circuit-if-refused control flow);
neither has anything to do with `check_linkage_layout`'s own three
guardrails, so they're additive, not exclusive-or.

### Testing

- Unit (Docker-free): `cics_eib_plan` (no match -> `None`; match -> plan;
  already-declared -> `None`), `check_cics_eib_layout` (both new refusal
  codes, and a clean pass for an ordinary EIB-referencing program),
  `splicer.cics_eib.working_storage_lines`/`reset_lines` (exact emitted
  text), the generalized `linkage_plan` (`ENTRY`-less `DFHCOMMAREA` shape
  now returns a plan instead of `None`, existing IMS-shaped fixtures
  unaffected).
- Integration: none added by this design (no working Docker daemon this
  session to prove one out against the real toolchain — see "No corpus
  evidence" above). Follow-up work should add one once a real CICS example
  program and a working toolchain are both available, mirroring
  `ACCTPRG`'s `@requires_docker` proof-of-life test.

### Docs sync

- `.okf/analysis.md` / `.okf/splicer.md`: new sections for
  `UNSUPPORTED_CICS_MACRO`/`UNSUPPORTED_CICS_DFHCOMMAREA` and the EIB
  synthesis transform; note on `linkage_plan`'s generalized (no-`ENTRY`)
  detection.
- `CHANGELOG.md`: `Added` entry.

## Out of scope

- Expanding `DFHRESP`/`DFHVALUE` macro calls against the real CICS
  condition-name table — `UNSUPPORTED_CICS_MACRO` refuses these permanently
  until a future design takes this on directly.
- Synthesizing a `DFHCOMMAREA` layout when the program never declares one
  itself — `UNSUPPORTED_CICS_DFHCOMMAREA` refuses; no safe default size
  exists to guess.
- A general CICS translator (expanding `EXEC CICS` command semantics beyond
  what `injector.build_exec_trap`'s splice-away already provides) — approach
  A above, explicitly rejected.
- Verifying either mechanism against the real GnuCOBOL toolchain — no
  working Docker daemon this session; flagged as required follow-up above.
