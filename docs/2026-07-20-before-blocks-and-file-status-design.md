# mockymock — `BEFORE-EACH`/`BEFORE-ALL` Scoping and `FILE-STATUS` Sugar

Date: 2026-07-20
Status: proposed

## Motivation

Comparing mockymock's `.cut` DSL against the (unrelated, precursor)
Cobol Check project's own design wiki surfaced two ergonomics gaps that
are genuinely worth closing, out of a larger list of gaps that don't fit
mockymock's splice-and-replace architecture (partial call-parameter
matching, resource-typed mocks with nested `ON <action>` clauses,
runtime data-value-based dispatch — see the 2026-07-20 comparison
conversation for why those were rejected):

1. **Every `MOCK` must be re-declared in every `TESTCASE` that needs it.**
   A suite where ten test cases all need `MOCK OPEN INV-FILE` to succeed
   repeats that same three-line block ten times. This is exactly the
   "DSL/authoring ergonomics" gap flagged in the 2026-07-06 readiness
   audit's Finding 6.
2. **File status is entirely hand-rolled.** A `.cut` author must already
   know which WORKING-STORAGE field a file's `FILE STATUS IS` clause
   points at, and must spell out the raw two-character status code from
   memory (`"35"` for file-not-found, `"23"` for record-not-found, ...).
   An empty `MOCK OPEN X` body today leaves that field at whatever
   `UT-RESET-WORKING-STORAGE` left it — not necessarily `"00"` — a silent
   footgun.

## Scope

**In scope:**
- `BEFORE-ALL` / `BEFORE-EACH` blocks holding `MOCK` directives shared
  across every `TESTCASE` in a suite, resolved by parse-time desugaring.
- A `FILE-STATUS IS <mnemonic-or-code>` statement usable inside
  `MOCK OPEN|CLOSE|READ|DELETE|START|UNLOCK` bodies, resolved against the
  target `.cbl`'s `SELECT ... FILE STATUS IS <field>` clause.
- An implicit default-success (`"00"`) status for those same six
  categories whenever the target file declares a `FILE STATUS` field at
  all, whether or not the mock body sets one explicitly.

**Explicitly out of scope** (considered, deferred):
- `MOCK WRITE` / `MOCK REWRITE` for the `FILE-STATUS` feature. Those key
  on the *record* name, not the file name; resolving record → owning FD →
  file name needs DATA DIVISION record-ownership analysis mockymock
  doesn't do today. A real gap, but a separate, harder project.
- `MOVE`/`PERFORM`/`EXPECT`/`VERIFY` inside `BEFORE-EACH`/`BEFORE-ALL` —
  only `MOCK` blocks are shared. Matches the Cobol Check wiki's own
  examples and keeps the desugar purely additive to `case.mocks`.
- Any FILE STATUS mnemonic not in the fixed table below — a literal
  quoted two-character code always works as the escape hatch, so this
  isn't a hard limit, just a smaller initial vocabulary.
- Partial call-parameter matching, resource-typed nested-`ON` mocks,
  data-value-based dispatch (rejected architecturally, see Motivation).

## Design: `BEFORE-EACH` / `BEFORE-ALL`

### Grammar

Two new optional blocks, each at most once per `TESTSUITE`, appearing
after the `TESTSUITE` header and before the first `TESTCASE`:

```
TESTSUITE "..."

BEFORE-ALL
    MOCK OPEN FILE1
    END-MOCK
END-BEFORE

BEFORE-EACH
    MOCK READ FILE2
        MOVE "default row" TO WS-RECORD
    END-MOCK
END-BEFORE

TESTCASE "..."
    ...
```

Body content is one or more `MOCK ... END-MOCK` blocks, parsed with the
exact same `_MOCK_QUOTED_RE`/`_MOCK_BARE_RE`/duplicate-check machinery
`parser.py` already uses inside a `TESTCASE` — just collected into the
suite-level `before_all`/`before_each` lists instead of a case's `mocks`.
`END-BEFORE` is case-insensitive with an optional trailing period, same
rationale as `END-MOCK`: a missed terminator must not silently swallow
the rest of the file into the block body.

A `BEFORE-ALL`/`BEFORE-EACH` appearing after any `TESTCASE`, or a second
`BEFORE-ALL`/`BEFORE-EACH` in one suite, is a `CutParseError`.

### Desugaring (parse time, not runtime)

After the whole file is parsed, each `TESTCASE`'s `mocks` list is
rewritten to:

```
case.mocks (own, as parsed today)
  + every BEFORE-EACH mock whose (category, key) the case didn't already declare
  + every BEFORE-ALL mock whose (category, key) neither the case nor BEFORE-EACH already declared
```

Precedence when the same `(category, key)` appears in more than one
place: **TESTCASE > BEFORE-EACH > BEFORE-ALL**, silently — no error, by
design (Q&A from the design conversation: a shared default should be
overridable per-case without touching the shared block).

A duplicate `(category, key)` declared twice *within* the same
`BEFORE-EACH` (or the same `BEFORE-ALL`) is still a `CutParseError`,
identical to today's in-`TESTCASE` duplicate check — that's a real
authoring mistake, not an override.

This is a pure `MockTestSuite`-construction step: `refusal.py`,
`injector.py`, `driver.py`, and `naming.TallyRegistry` never learn that
`BEFORE-EACH`/`BEFORE-ALL` exist. They already operate on
`MockTestCase.mocks`, which after desugaring looks exactly like a suite
where every case wrote its mocks out by hand. This is deliberate: it
minimizes blast radius across the four modules that already consume
`case.mocks`, and it means a `TESTCASE` can `VERIFY` a
`BEFORE-EACH`/`BEFORE-ALL`-declared mock for free — `driver.py`'s
existing `(verification.category, verification.key) not in case_mocks`
check already passes, since the mock is now genuinely part of the case.

### Why desugar instead of threading scope through the pipeline

Alternative: keep `BEFORE-EACH`/`BEFORE-ALL` mocks in their own fields on
`MockTestSuite` and teach `refusal.py`/`injector.py`/`driver.py` to
consult them in addition to `case.mocks`. Rejected — every one of those
modules has at least two call sites that iterate `case.mocks` today
(reachability checks, tally zeroing, dispatch matching, `VERIFY`
validation); duplicating "case mocks, plus shared mocks the case doesn't
override" at each of those call sites is real duplicated-rule risk for
no benefit, versus computing it once, right after parsing.

## Design: `FILE-STATUS` sugar

### Where the field name comes from

Confirmed directly against `cobolparser`'s AST (not assumed): a `SELECT`
clause's `FILE STATUS IS <field>` becomes a `SelectStatement.file_status`
attribute, keyed by `SelectStatement.file_name`, reachable via
`program.get_division("ENVIRONMENT")`'s `INPUT-OUTPUT` section's
`FILE-CONTROL` paragraph statements. mockymock doesn't read the
`ENVIRONMENT` division at all today (`mock_surface.py` only walks
`PROCEDURE`) — this is new analysis, not a repurposed existing map.

A new function (name/module decided during planning; natural home is
alongside `mock_surface.analyze`) builds `file_status_fields: dict[str,
str]` — uppercased file name → declared status field name — once per
target program. A file with no `FILE STATUS` clause simply has no entry.

### Grammar: `FILE-STATUS IS <value>`

Usable at most once inside a `MOCK OPEN|CLOSE|READ|DELETE|START|UNLOCK`
body (not `WRITE`/`REWRITE` — see Scope — and not `CALL`/`SQL`/`CICS`/
`DLI`/`ACCEPT`/`PARAGRAPH`/`SECTION`, where "file status" is meaningless).
`<value>` is either a mnemonic word or a quoted two-character literal:

| Mnemonic            | Code |
|----------------------|------|
| `SUCCESS`             | `00` |
| `END-OF-FILE`         | `10` |
| `DUPLICATE-KEY`       | `22` |
| `RECORD-NOT-FOUND`    | `23` |
| `FILE-NOT-FOUND`      | `35` |
| `ALREADY-OPEN`        | `41` |
| `NOT-OPEN`            | `42` |
| `NO-CURRENT-RECORD`   | `43` |

`FILE-STATUS IS "92"` (any quoted 2-character literal) always works too,
as the escape hatch for a code not in the table. An unrecognized bare
word, a literal that isn't exactly two characters, `FILE-STATUS IS`
inside an ineligible category, or a second `FILE-STATUS IS` in the same
body are all `CutParseError`s at parse time, line-numbered.

`FILE-STATUS IS` on a file that has **no** declared `FILE STATUS` clause
in its `SELECT` entry can't be a parse-time error (`.cut` parsing doesn't
see the `.cbl` at all), but must not silently do nothing either — that
would discard the author's explicit intent with no signal. This is a
new analysis-phase refusal, in the same family as the codebase's
existing fail-closed checks (`UNSUPPORTED_TERMINATOR_LAYOUT`,
`UNRESOLVED_FLOW_MOCK_TARGET`, ...): `UNRESOLVED_FILE_STATUS_TARGET`,
raised once the target `.cbl`'s `FILE-CONTROL` has been analyzed and the
mock's file is confirmed to have no status field to target.

The mnemonic → code resolution happens at `.cut`-parse time (pure DSL
vocabulary, no `.cbl` knowledge needed). The resolved code is stored on
`MockDirective` (new field, e.g. `file_status: str | None`) — *not*
immediately rewritten into a `MOVE`, since the target field name isn't
knowable until the `.cbl`'s `FILE-CONTROL` has been analyzed, which
happens later in the pipeline than `.cut` parsing.

### Codegen: default-success plus override

Confirmed against `injector.build_site_dispatch` (`mockymock/splicer/
injector.py`): for a file-op directive, the generated `WHEN "<case>"`
branch today is `ADD 1 TO <tally>` followed by
`directive.body_lines` verbatim. The change is additive, right there:
for directives in the six eligible categories whose `key` resolves via
`file_status_fields`, prepend `MOVE "00" TO <field>` before
`directive.body_lines`; if `directive.file_status` is set, prepend
`MOVE "<code>" TO <field>` *after* the default (so it naturally wins,
whether it came from `FILE-STATUS IS` or the field just happens to also
be set by a hand-written `MOVE` later in the body — last write wins,
standard COBOL sequential execution, no special-case detection needed).

Concretely, a mock body becomes, in order:
1. `MOVE "00" TO <field>` — only if the file declares a status field.
2. `MOVE "<code>" TO <field>` — only if `FILE-STATUS IS` was used.
3. The user's own hand-written body lines, unchanged.

A file with no declared `FILE STATUS` clause gets nothing injected at
step 1 — there's no field to target, so this is a fail-safe no-op, not
an error.

## Testing

- **Unit (`BEFORE-EACH`/`BEFORE-ALL`)**: grammar parsing (block position,
  one-per-suite limit, `END-BEFORE` leniency), desugar precedence
  (`TESTCASE` overrides `BEFORE-EACH` overrides `BEFORE-ALL`), in-block
  duplicate detection, and a case that `VERIFY`s a shared mock.
- **Unit (`FILE-STATUS`)**: mnemonic table resolution, quoted-literal
  escape hatch, category restriction errors, duplicate-in-body error,
  the new `file_status_fields` extraction against a fixture `.cbl` with
  and without `FILE STATUS` clauses, and the `UNRESOLVED_FILE_STATUS_TARGET`
  refusal when `FILE-STATUS IS` targets a file with no declared status
  field.
- **Integration**: a real GnuCOBOL/Docker compile-and-run test for both
  features (matching this project's established verification standard —
  unit tests alone don't prove generated COBOL actually compiles and
  behaves), plus a small addition to `examples/` demonstrating both
  (likely extending `examples/invupdt/`, which already exercises
  `MOCK OPEN`/`MOCK READ` on a real file with a declared status field).

## Docs to update after implementation

- `.okf/dsl.md` — document both new statements and the mnemonic table.
- `README.md` — DSL reference section.
- `docs/2026-07-06-real-world-readiness-audit.md` Finding 6 — mark the
  "every MOCK re-declared per TestCase" and "no default file-status"
  footguns closed (partially, for the six eligible categories).

## Alternatives considered

- **`FILE-STATUS IS` inline on the `MOCK` header line** (e.g.
  `MOCK OPEN INV-FILE FILE-STATUS IS FILE-NOT-FOUND`) instead of as a
  body statement. Rejected: doesn't compose with a body that also needs
  to set fake record data (the wiki's own `READ` examples do both in one
  mock), and would need a second, header-level grammar path instead of
  reusing the body-line loop.
- **Resource-typed `MOCK` with nested `ON <action>` clauses** (the Cobol
  Check wiki's actual shape) as the vehicle for both features. Rejected
  in the original comparison conversation: mockymock's flat
  `MOCK <category> <key>` model is load-bearing for the
  `(category, key)`-keyed tally registry, `VERIFY` matching, and
  `directive_matches_site`; restructuring to nested resources would touch
  every one of those, for a cosmetic regrouping with no new capability.
- **`BEFORE-EACH`/`BEFORE-ALL` erroring on override instead of
  TESTCASE-wins precedence.** Considered and rejected during the design
  conversation: it would force anything that varies per-case out of the
  shared block entirely, defeating the "declare the common default once"
  purpose.
