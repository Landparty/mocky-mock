# mockymock — Argument-Capture Assertions on Mocked `CALL`s

Date: 2026-08-11
Status: proposed

## Motivation

`docs/2026-07-06-real-world-readiness-audit.md` Finding 6 (DSL/authoring
ergonomics) has flagged, unaddressed since the audit, that a `.cut` author
has no way to assert on what value a mocked `CALL` actually *received*:

- `EXPECT <data-name> TO BE <value>` checks WORKING-STORAGE equality after
  `PERFORM` completes — it has no relationship to a CALL's arguments.
- `VERIFY <category> <key> WAS CALLED <expectation>` only checks the
  per-`(category, key)` tally count (`ONCE`/`NEVER`/`AT LEAST ONCE`/`<n>
  TIMES`) — it has no visibility into argument *values* at all.

This is the "argument capture/spies" gap named explicitly in the audit's
Finding 6 bullet list and re-confirmed open in the 2026-08-10 follow-up
audit. It matters concretely: a `.cut` author mocking `CALL "CALCDISC"`
today can assert the call happened (`VERIFY`) and can control what the
mock *returns* (an ordinary `MOVE` in the mock body), but cannot assert
what discount rate the real program actually passed in — the exact thing
a "spy" mock is for.

## Scope

**In scope:**
- A new `CAPTURE ARG <n> INTO <target>` statement, usable inside a
  `MOCK CALL "..."` / `MOCK MQ "..."` (quoted-key CALL) or
  `MOCK CALL <identifier>` (bare-key DYNCALL) body — the two categories a
  COBOL `USING` clause can appear on.
- Positional (1-based) selection of the CALL's `USING` parameter, resolved
  per physical call site against the real AST — not a COBOL variable-name
  reference — so one `.cut` line stays correct even when two call sites
  sharing the same mocked key use differently-named arguments.
- A new fail-closed refusal (`CAPTURE_ARG_OUT_OF_RANGE`) when a requested
  index exceeds what some matching call site actually declares.
- Reuse of the existing `EXPECT` statement to assert the captured value —
  no new assertion syntax.

**Explicitly out of scope** (deferred, not rejected):
- Capturing `GIVING`/`RETURNING` — that is the mock's own *output*, which
  the `.cut` author already fully controls via the mock body's own `MOVE`
  statements. Nothing to spy on.
- Per-call history/table capture. A site invoked more than once in one
  `TESTCASE` (e.g. inside a loop) captures only its *last* call — see
  "Multi-call semantics" below. Capturing every call into an `OCCURS`
  table is a real future extension but adds a second storage shape
  (indexed by call number) this pass doesn't need.
- `EXEC SQL`/`EXEC CICS`/`EXEC DLI` host-variable capture. The audit
  finding names `CALL`s specifically; SQL/CICS/DLI host variables are
  already directly readable/writable via ordinary `MOVE`s in the mock
  body today (no LINKAGE-crossing indirection exists there the way a
  CALL's `USING` clause has), so there's no equivalent gap to close.
- `mockymock generate`/`generate --with-data` emitting `CAPTURE`
  automatically. Hand-authoring only for v1, same as the `ROWS`/`TERMINAL`
  inline sugar (see `.okf/dsl.md`).

## Design

### Grammar: `CAPTURE ARG <n> INTO <target>`

```
MOCK CALL "CALCDISC"
    CAPTURE ARG 1 INTO WS-CAPTURED-RATE
    MOVE 0 TO RETURN-CODE
END-MOCK
...
PERFORM APPLY-DISCOUNT
EXPECT WS-CAPTURED-RATE TO BE 0.15
```

- `<n>` is a positive integer literal (`^[1-9][0-9]*$`), 1-based, naming
  the CALL's `USING` parameter position — matching COBOL's own 1-based
  convention for e.g. `SEARCH ... AT END`-style positional references, and
  the same ordinal convention `MOCK READ ... ROWS`'s `WHEN <tally> = N`
  branches already use internally.
- `<target>` reuses `_SUBSCRIPTED_NAME` (`dsl/parser.py`), the same
  fragment `EXPECT`'s data-name and `MOVE`'s target already parse with —
  so a subscripted capture target (`WS-TABLE(1, 1)`) or reference
  modification (`FIELD(1:5)`) works identically to every other place this
  grammar already accepts one.
- Usable **only** inside a `MOCK CALL`/`MOCK MQ` (category `CALL`) or bare
  `MOCK CALL <identifier>` (category `DYNCALL`) body. Any other category —
  `CAPTURE` inside `MOCK OPEN`, `MOCK SQL`, etc. — is a `CutParseError` at
  that line, mirroring `FILE-STATUS IS`'s category restriction
  (`dsl/parser.py`'s `_FILE_STATUS_RE` branch) and `ROWS`'s SQL/READ-only
  restriction.
- Multiple `CAPTURE` lines are allowed in one mock body (one CALL can have
  several `USING` parameters worth capturing); the same `<n>` used twice
  in one body is a `CutParseError` (`"duplicate CAPTURE ARG n"`) — same
  "don't silently let the second one win" posture as the existing
  duplicate-`(category, key)` and duplicate-`TERMINAL` checks.
- `<n>` of `0` or a non-numeric token is a `CutParseError` naming the line
  — fail closed at parse time, not a raw `ValueError`/`IndexError` later
  in codegen (matching `_validate_expectation`'s and `FILE-STATUS
  IS`'s own precedent: DSL-shaped mistakes are `.cut`-level errors, not
  Python exceptions from deeper in the pipeline).

Storage: `MockDirective` (`dsl/model.py`) gains one new field,
`captures: list[tuple[int, str]] = field(default_factory=list)` — parallel
in spirit to `terminal_row`'s `list[tuple[str, str]]`, just keyed by
integer position instead of field name.

### Where the real argument name comes from

Confirmed directly against the pinned `cobolparser` AST (not assumed):
`CallStatement.using_parameters: list[CallParameter]`
(`cobolparser/models/statements/call.py`), where `CallParameter.name: str`
is the `USING` clause's Nth data-name, in source order, for **both**
static and dynamic `CallStatement`s (dynamic-CALL identity is a separate
field, `.called_program` + `.is_dynamic`, unrelated to `.using_parameters`
— so `CAPTURE` works identically for `CALL`/`MQ` and `DYNCALL`
directives). This attribute is not currently in mockymock's pinned
dependency surface (`interface-contract.md`) — it exists upstream, unused
today, so no cobolparser change is needed, only a contract-doc addition.

`mock_surface.py`'s `BoundarySite.statement: object` already holds the
original AST node for every site (`mock_surface.py:328`), including CALL
sites — so **no new field on `BoundarySite` is needed**. Both the new
refusal check and the splicer narrow `site.statement` with
`isinstance(site.statement, CallStatement)` (true for every `CALL`
category site by construction — `_classify_statement` only creates a
`CALL`/`DYNCALL` `BoundarySite` from a `CallStatement`) and read
`.using_parameters` directly off it.

### Fail-closed validation: `CAPTURE_ARG_OUT_OF_RANGE`

New per-test-case check in `refusal.check_test_case` (`analysis/refusal.py`),
in the same final pass that already checks `UNRESOLVED_FILE_STATUS_TARGET`
over `case.mocks`: for every directive with a non-empty `captures` list,
for every program-wide boundary site that directive matches
(`directive_matches_site`), if `capture_index > len(site.statement.using_parameters)`
for any `(capture_index, _)` in `directive.captures`, refuse — naming the
directive's `.describe()` text, the requested index, and the actual
`USING` parameter count at that site (and the site's paragraph/line, same
as other per-site refusal messages) — rather than let the splicer either
crash on an out-of-range list index or (worse) silently move nothing.

This mirrors why `UNRESOLVED_FILE_STATUS_TARGET` exists: a `.cut`-level
request that the target program cannot satisfy must fail loudly, before
`orchestrator.splice_program` is ever reached, not surface as a Python
traceback or — worse — a compiled program that silently does something
other than what the author asked for.

**Multi-site nuance:** because dispatch is per **physical site**
(`build_site_dispatch` is called once per `BoundarySite`, not once per
`(category, key)`), two call sites sharing one mocked key can legitimately
declare a different number of `USING` parameters (e.g. two different
`CALL "VALIDATE"` sites in different paragraphs, one passing one argument,
the other passing two). `CAPTURE ARG 2` is valid for the second site and
invalid for the first. This check refuses if **any** matching site fails —
same fail-closed-over-partial-safety posture the codebase
uses throughout (e.g. `UNRESOLVED_FILE_STATUS_TARGET` doesn't try to
special-case "safe for some call sites, unsafe for others" either). A
`.cut` author who genuinely needs to capture from only the site that has
that argument should give that site its own dedicated mocked key, or (if
the sites are truly interchangeable in every other way) accept that
`CAPTURE` isn't usable for that particular shared key — this is a
documented limitation, not silently wrong behavior.

### Codegen: `injector.build_site_dispatch`

Confirmed against `splicer/injector.py`: today, for a matched directive,
the generated `WHEN "<case>"` branch is `ADD 1 TO <tally>` followed by
`directive.body_lines` verbatim (plus the FILE-STATUS default/override
MOVEs for eligible file-op categories, N/A here — `CALL`/`DYNCALL` are not
in `FILE_STATUS_CATEGORIES`). The change is additive, in the same branch:
for a matched directive with a non-empty `captures` list, emit one
`MOVE <site.statement.using_parameters[n - 1].name> TO <target>` line per
`(n, target)` in `directive.captures`, in the order declared, **before**
`directive.body_lines` — so a capture always reflects the argument's value
*as the real caller passed it*, never a value some earlier body line
might otherwise have overwritten it with (not a real risk today since
`<target>` is the author's own scratch field, never the CALL's own
argument variable, but ordering-first keeps the invariant simple and
matches the FILE-STATUS default's own "implicit thing first" convention).

Concretely, a mock body's generated `WHEN` branch becomes, in order:
1. `ADD 1 TO <tally>` (unchanged, existing behavior).
2. `MOVE <real-arg-name> TO <capture-target>` — one per `CAPTURE` line,
   only for `CALL`/`DYNCALL` directives with `captures`.
3. `directive.body_lines`, unchanged verbatim (existing behavior).

### Multi-call semantics: last call wins

A `CAPTURE`-generated `MOVE` re-executes on every dispatch through that
`WHEN` branch — identical to how any hand-written mock-body `MOVE` already
behaves (e.g. a body's own `MOVE 0 TO RETURN-CODE` doesn't accumulate
across repeated calls either). So if the mocked CALL is reached more than
once within one `TESTCASE` (a loop calling it per record, say), by the
time `PERFORM` returns and `EXPECT` runs, the capture target holds
whichever call happened **last**. This needs zero new engine machinery —
it falls directly out of the existing per-dispatch execution model — and
is the same tradeoff `VERIFY`'s tally count already makes implicitly
symmetric with (`VERIFY` counts every call; `CAPTURE` — deliberately, for
v1 — only remembers the most recent one). Documented as a real, named
limitation rather than a silent surprise; capturing every call's argument
history is the deferred future extension noted in Scope.

### Why reuse `EXPECT` instead of a dedicated capture+assert statement

Considered and rejected: a combined statement (e.g. `VERIFY CALL "X" WAS
CALLED WITH ARG 1 = <value>`) that captures and asserts in one line.
Rejected because it would require building a second, parallel assertion
engine next to the one that already exists — new comparison codegen, a
new `__MOCKYMOCK__` DISPLAY marker, new `report.py` parsing, new
driver-side FAIL-line formatting — to duplicate exactly what `EXPECT`
already does. Routing the captured value through an ordinary
WORKING-STORAGE field and letting `EXPECT` check it instead means:
- Zero new report/runtime protocol.
- Free interop with everything `EXPECT` already supports: subscripted
  data-names, `PROVIDER`/`{Placeholder}` substitution, the existing
  FAIL-line format authors already read.
- Consistency with this codebase's established pattern: `FILE-STATUS IS`
  and `record_targets`/`RECORD` both work by getting a real value into an
  ordinary WORKING-STORAGE field and reusing the existing equality
  machinery to check it, rather than inventing a parallel comparison path
  per feature.

The cost: a `.cut` author must declare (or reuse) a scratch WORKING-STORAGE
field as the capture target, and remember it resets to its declared
default every `TESTCASE` like any other field — an existing, already
-documented property of every WORKING-STORAGE item, not a new footgun
specific to this feature.

## Testing

- **Unit (`dsl/parser.py`)**: grammar parsing (`CAPTURE ARG <n> INTO
  <target>`, subscripted target), category restriction (`CutParseError`
  inside `MOCK OPEN`/`MOCK SQL`/etc.), bad index (`0`, non-numeric,
  missing), duplicate `<n>` within one body.
- **Unit (`analysis/refusal.py`)**: `CAPTURE_ARG_OUT_OF_RANGE` fires when
  a directive's capture index exceeds a matching site's actual `USING`
  parameter count; does not fire when it's in range; the multi-site
  partial-safety case (two sites sharing a key, only one has enough args)
  refuses.
- **Unit (`splicer/injector.py`)**: `build_site_dispatch` emits the
  correct `MOVE <real-arg-name> TO <target>` line(s), in declared order,
  before `directive.body_lines`; a directive with no `captures` is
  byte-for-byte unaffected (regression-guards the "opt-in, zero-cost when
  absent" property every other optional directive field already has).
- **Integration**: a real GnuCOBOL/Docker compile-and-run test proving a
  captured argument round-trips end-to-end — extend an existing
  CALL-mocking `examples/` fixture (or add a small new one) with a
  `CAPTURE`+`EXPECT` pair that passes against the real value and fails
  against a wrong one, matching this project's established
  "unit tests alone don't prove generated COBOL actually compiles and
  behaves" verification standard.

## Docs to update after implementation

- `.okf/dsl.md` — new `CAPTURE ARG <n> INTO <target>` grammar section
  (alongside `FILE-STATUS IS`/`ROWS`/`TERMINAL`), `MockDirective.captures`
  in the AST model table.
- `.okf/splicer.md` — `build_site_dispatch`'s codegen ordering, and note
  that `BoundarySite.statement` (already carrying the real AST node) is
  what makes this possible with no new analysis-phase field.
- `.okf/analysis.md` — `CAPTURE_ARG_OUT_OF_RANGE` in the per-test-case
  refusal table.
- `interface-contract.md` / `.okf/integration.md` — pin
  `CallStatement.using_parameters: list[CallParameter]`,
  `CallParameter.name: str`.
- `.okf/log.md` — dated entry.
- `mockymock/cli/skills/mockymock/reference/cut-dsl.md` — the AI-skill's
  own DSL reference copy.
- `docs/2026-07-06-real-world-readiness-audit.md` Finding 6 — mark the
  "argument capture/spies" bullet closed.
- `README.md` — DSL reference section, if it documents `MOCK CALL` bodies
  in similar depth to `FILE-STATUS IS`/`ROWS` already.

## Alternatives considered

- **Dedicated `VERIFY ... WAS CALLED WITH ARG n = value` combined
  syntax.** Rejected — see "Why reuse EXPECT" above.
- **Reference the `USING` argument by its real COBOL variable name**
  instead of positionally, e.g. `CAPTURE WS-DISC-RATE INTO
  WS-CAPTURED-RATE` (mirroring how a `.cut` author could, in principle,
  already hand-write `MOVE WS-DISC-RATE TO WS-CAPTURED-RATE` directly in
  the mock body today, since mock bodies splice into the caller's own
  scope). Rejected as the primary mechanism: it silently breaks the
  moment two physical call sites sharing one mocked key use differently
  -named arguments (a very ordinary shape — two paragraphs both calling
  `CALCDISC`, with their own local WORKING-STORAGE names for "the rate").
  Positional indexing is the only form that's correct across every site a
  directive can match, which is the entire reason a dedicated `CAPTURE`
  primitive is worth building instead of just documenting "you can already
  do this with a hand-written `MOVE`."
- **Capture every call into an `OCCURS` table**, so a `.cut` author could
  assert on call N specifically instead of only the last one. Deferred,
  not rejected — real added value for a loop-heavy program, but needs a
  second storage/indexing shape (a per-directive tally-indexed table
  mirroring `naming.TallyRegistry`'s own `UT-*-TALLY` counter) that adds
  meaningfully more surface than this pass's scope; last-call-wins covers
  the common "assert the CALL got the value I expect" case with zero new
  engine mechanism.
- **New field on `BoundarySite` for `using_parameters`**, populated by
  `mock_surface.py` at analysis time (mirroring `keys`/`match_text`).
  Rejected once `BoundarySite.statement: object` was confirmed to already
  carry the original `CallStatement` — adding a redundant, narrower field
  would just be two ways to reach the same data, with the redundant one
  needing to be kept in sync.
